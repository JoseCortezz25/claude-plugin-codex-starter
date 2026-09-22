#!/usr/bin/env bash
# Scaffold a new Codex brand project from the harness template, pinned to a GitHub release.
#
# Usage:
#   new-project.sh --brand <name> --slug <folder> --parent <dir> --purpose <text> [--version <tag>]
#
# Env:
#   CODEX_TEMPLATE_REPO  owner/repo of the harness template (default: JoseCortezz25/delivery-system-starter)
#
# On success the last line of stdout is: CODEX_PROJECT_PATH=<absolute path>
set -euo pipefail

TEMPLATE_REPO="${CODEX_TEMPLATE_REPO:-JoseCortezz25/delivery-system-starter}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$SCRIPT_DIR")}"
PLUGIN_MANIFEST="$PLUGIN_ROOT/.claude-plugin/plugin.json"
LOCK_FILE_NAME="codex-lock.json"
CODEX_FORMAT_VERSION="0.1.0"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

BRAND="" SLUG="" PARENT="" PURPOSE="" VERSION=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --brand)   BRAND="${2-}"; shift 2 ;;
    --slug)    SLUG="${2-}"; shift 2 ;;
    --parent)  PARENT="${2-}"; shift 2 ;;
    --purpose) PURPOSE="${2-}"; shift 2 ;;
    --version) VERSION="${2-}"; shift 2 ;;
    -h|--help) usage ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ -n "$BRAND" ]]   || die "--brand is required"
[[ -n "$SLUG" ]]    || die "--slug is required"
[[ -n "$PARENT" ]]  || die "--parent is required"
[[ -n "$PURPOSE" ]] || die "--purpose is required"
[[ "$SLUG" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] || die "--slug must be kebab-case (a-z, 0-9, '-'): got '$SLUG'"

# --- Tooling -----------------------------------------------------------------
for bin in git gh jq; do
  command -v "$bin" >/dev/null 2>&1 || die "'$bin' is required but not installed."
done

[[ -f "$PLUGIN_MANIFEST" ]] || die "plugin manifest not found at $PLUGIN_MANIFEST"
PLUGIN_NAME="$(jq -r '.name // empty' "$PLUGIN_MANIFEST")"
PLUGIN_VERSION="$(jq -r '.version // empty' "$PLUGIN_MANIFEST")"
[[ -n "$PLUGIN_NAME" ]] || die "could not read plugin name from $PLUGIN_MANIFEST"

if ! gh auth status >/dev/null 2>&1; then
  die "GitHub CLI is not logged in. Run 'gh auth login' with an account that has access to $TEMPLATE_REPO."
fi

GIT_USER_NAME="$(git config --get user.name || true)"
GIT_USER_EMAIL="$(git config --get user.email || true)"
if [[ -z "$GIT_USER_NAME" || -z "$GIT_USER_EMAIL" ]]; then
  die "git user.name and user.email must be set before scaffolding. Run: git config --global user.name \"Your Name\" && git config --global user.email \"you@example.com\""
fi

# --- Paths -------------------------------------------------------------------
[[ -d "$PARENT" ]] || die "parent directory does not exist: $PARENT"
PARENT_ABS="$(cd "$PARENT" && pwd -P)"
TARGET="$PARENT_ABS/$SLUG"

dir="$PARENT_ABS"
while :; do
  if [[ -f "$dir/$LOCK_FILE_NAME" ]]; then
    die "parent '$PARENT_ABS' is inside an existing Codex project ($dir). Choose a location outside any Codex project."
  fi
  [[ "$dir" == "/" ]] && break
  dir="$(dirname "$dir")"
done

if [[ -e "$TARGET" ]]; then
  if [[ ! -d "$TARGET" ]]; then
    die "target exists and is not a directory: $TARGET"
  fi
  if [[ -n "$(ls -A "$TARGET" 2>/dev/null)" ]]; then
    die "target folder already exists and is not empty: $TARGET"
  fi
fi

# --- Access + version --------------------------------------------------------
if ! gh repo view "$TEMPLATE_REPO" --json name >/dev/null 2>&1; then
  die "cannot access the harness template repo '$TEMPLATE_REPO'. Make sure your GitHub account has access to this private repository."
fi

if [[ -z "$VERSION" ]]; then
  if ! VERSION="$(gh release view --repo "$TEMPLATE_REPO" --json tagName --jq .tagName 2>/dev/null)" || [[ -z "$VERSION" ]]; then
    die "the harness has no published release yet ($TEMPLATE_REPO). Publish a GitHub release of the template, or pass --version <tag>."
  fi
else
  if ! gh release view "$VERSION" --repo "$TEMPLATE_REPO" --json tagName >/dev/null 2>&1; then
    die "release '$VERSION' was not found in $TEMPLATE_REPO."
  fi
fi

# --- Clone + re-init ---------------------------------------------------------
echo "Cloning $TEMPLATE_REPO@$VERSION into $TARGET ..."
CREATED_TARGET=0
[[ -e "$TARGET" ]] || CREATED_TARGET=1
cleanup_on_error() {
  local rc=$?
  if [[ $rc -ne 0 && $CREATED_TARGET -eq 1 && -d "$TARGET" ]]; then
    rm -rf "$TARGET"
  fi
}
trap cleanup_on_error EXIT

# Clone over HTTPS with gh as the credential helper, so it works with the user's `gh auth login`
# regardless of their SSH setup or gh's git_protocol preference.
git -c credential.helper= -c 'credential.helper=!gh auth git-credential' -c advice.detachedHead=false \
  clone --depth 1 --branch "$VERSION" --quiet "https://github.com/$TEMPLATE_REPO.git" "$TARGET" \
  || die "clone of $TEMPLATE_REPO@$VERSION failed."

COMMIT_SHA="$(git -C "$TARGET" rev-parse HEAD)"
rm -rf "$TARGET/.git"
git -C "$TARGET" init --quiet

CREATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
jq -n \
  --arg version "$VERSION" \
  --arg repo "https://github.com/$TEMPLATE_REPO" \
  --arg commit "$COMMIT_SHA" \
  --arg brand "$BRAND" \
  --arg codexVersion "$CODEX_FORMAT_VERSION" \
  --arg slug "$SLUG" \
  --arg purpose "$PURPOSE" \
  --arg createdAt "$CREATED_AT" \
  --arg plugin "$PLUGIN_NAME" \
  --arg pluginVersion "$PLUGIN_VERSION" \
  '{
    schemaVersion: 1,
    harness: { name: "codex", version: $version, repo: $repo, commit: $commit },
    brand: { name: $brand, codexVersion: $codexVersion },
    project: { name: $slug, purpose: $purpose, createdAt: $createdAt },
    createdWith: { plugin: $plugin, pluginVersion: $pluginVersion }
  }' > "$TARGET/$LOCK_FILE_NAME"

git -C "$TARGET" add -A
git -C "$TARGET" commit --quiet -m "chore: scaffold $BRAND codex project from $TEMPLATE_REPO@$VERSION"

trap - EXIT
echo "Created Codex project '$BRAND' at $TARGET (harness $VERSION, commit ${COMMIT_SHA:0:12})."
echo "CODEX_PROJECT_PATH=$TARGET"
