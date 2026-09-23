#!/usr/bin/env bash
# Scaffold a new Codex brand project from the harness template, pinned to a GitHub release.
#
# Usage:
#   new-project.sh --brand <name> --slug <folder> --parent <dir> --purpose <text> [--version <tag>]
#
# Env:
#   CODEX_TEMPLATE_REPO  owner/repo of the harness template (default: JoseCortezz25/delivery-system-starter)
#   CODEX_TEMPLATE_URL   git URL used when GitHub CLI is unavailable (default: https://github.com/<repo>.git;
#                        set to git@github.com:<repo>.git to use SSH)
#
# Uses GitHub CLI (gh) when it is installed and logged in; otherwise falls back to plain git with the
# user's own credentials (credential helper / keychain, or SSH via CODEX_TEMPLATE_URL).
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
for bin in git jq; do
  command -v "$bin" >/dev/null 2>&1 || die "'$bin' is required but not installed."
done

[[ -f "$PLUGIN_MANIFEST" ]] || die "plugin manifest not found at $PLUGIN_MANIFEST"
PLUGIN_NAME="$(jq -r '.name // empty' "$PLUGIN_MANIFEST")"
PLUGIN_VERSION="$(jq -r '.version // empty' "$PLUGIN_MANIFEST")"
[[ -n "$PLUGIN_NAME" ]] || die "could not read plugin name from $PLUGIN_MANIFEST"

TEMPLATE_URL="${CODEX_TEMPLATE_URL:-https://github.com/$TEMPLATE_REPO.git}"
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  USE_GH=1
else
  USE_GH=0
  echo "GitHub CLI not available or not logged in; using plain git ($TEMPLATE_URL)."
  # Never hang on an interactive credential prompt: fail fast with a clear message instead.
  export GIT_TERMINAL_PROMPT=0
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
NO_RELEASE_MSG="the harness has no published release yet ($TEMPLATE_REPO). Publish a GitHub release of the template, or pass --version <tag>."
if [[ $USE_GH -eq 1 ]]; then
  if ! gh repo view "$TEMPLATE_REPO" --json name >/dev/null 2>&1; then
    die "cannot access the harness template repo '$TEMPLATE_REPO'. Make sure your GitHub account has access to this private repository."
  fi
  if [[ -z "$VERSION" ]]; then
    if ! VERSION="$(gh release view --repo "$TEMPLATE_REPO" --json tagName --jq .tagName 2>/dev/null)" || [[ -z "$VERSION" ]]; then
      die "$NO_RELEASE_MSG"
    fi
  elif ! gh release view "$VERSION" --repo "$TEMPLATE_REPO" --json tagName >/dev/null 2>&1; then
    die "release '$VERSION' was not found in $TEMPLATE_REPO."
  fi
else
  # Without gh, releases are resolved from their git tags (every published release creates one).
  if ! REMOTE_TAGS="$(git ls-remote --tags --refs "$TEMPLATE_URL" 2>/dev/null | sed 's#.*refs/tags/##')"; then
    die "cannot access '$TEMPLATE_URL' with git. Make sure your GitHub account has access to this private repository and git has credentials for it: run 'git clone $TEMPLATE_URL' once in a terminal to store them (use a GitHub personal access token as the password), or set CODEX_TEMPLATE_URL=git@github.com:$TEMPLATE_REPO.git to use SSH."
  fi
  if [[ -z "$VERSION" ]]; then
    VERSION="$(printf '%s\n' "$REMOTE_TAGS" | grep -E '^v?[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -n 1 || true)"
    [[ -n "$VERSION" ]] || die "$NO_RELEASE_MSG"
  elif ! printf '%s\n' "$REMOTE_TAGS" | grep -qxF "$VERSION"; then
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

if [[ $USE_GH -eq 1 ]]; then
  # HTTPS with gh as the credential helper: works with `gh auth login` regardless of SSH setup.
  git -c credential.helper= -c 'credential.helper=!gh auth git-credential' -c advice.detachedHead=false \
    clone --depth 1 --branch "$VERSION" --quiet "https://github.com/$TEMPLATE_REPO.git" "$TARGET" \
    || die "clone of $TEMPLATE_REPO@$VERSION failed."
else
  git -c advice.detachedHead=false clone --depth 1 --branch "$VERSION" --quiet "$TEMPLATE_URL" "$TARGET" \
    || die "clone of $TEMPLATE_URL@$VERSION failed. Check that git has credentials for this private repository."
fi

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
