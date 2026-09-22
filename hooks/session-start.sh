#!/usr/bin/env bash
# SessionStart hook: detect whether the session runs inside a Codex brand project,
# or in a parent folder that contains Codex projects (which must not be operated from here).
set -euo pipefail

LOCK="codex-lock.json"
input="$(cat)"
cwd="$(jq -r '.cwd // empty' <<<"$input" 2>/dev/null || true)"
[[ -n "$cwd" ]] || cwd="${CLAUDE_PROJECT_DIR:-$PWD}"
[[ -d "$cwd" ]] || exit 0
cwd="$(cd "$cwd" && pwd -P)"

emit() {
  jq -n --arg ctx "$1" \
    '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}'
}

# 1) cwd is inside a Codex project (itself or an ancestor has the lock file).
dir="$cwd"
while :; do
  if [[ -f "$dir/$LOCK" ]]; then
    brand="$(jq -r '.brand.name // "unknown"' "$dir/$LOCK" 2>/dev/null || echo unknown)"
    harness="$(jq -r '.harness.version // "unknown"' "$dir/$LOCK" 2>/dev/null || echo unknown)"
    emit "Codex brand project: brand \"$brand\", harness $harness (root: $dir)."
    exit 0
  fi
  [[ "$dir" == "/" ]] && break
  dir="$(dirname "$dir")"
done

# 2) cwd is a parent folder containing Codex projects (child folders up to depth 2).
projects=()
while IFS= read -r lock; do
  projects+=("$(dirname "$lock")")
done < <(find "$cwd" -maxdepth 3 \
  \( -name .git -o -name node_modules \) -prune -o \
  -type f -name "$LOCK" -print 2>/dev/null | sort)

[[ ${#projects[@]} -gt 0 ]] || exit 0

list=""
for p in "${projects[@]}"; do
  list+=$'\n'"- $p"
done
first="${projects[0]}"

emit "This folder ($cwd) is a PARENT folder containing Codex brand projects:${list}
Do not read, edit, or generate brand work for these projects from this session: each project's rules, hooks, and protections live in its own .claude/ and only load when Claude Code is started inside that project folder.
If the user asks to work on one of them, stop and tell them in Spanish to open a new session inside the project, e.g.: cd \"$first\" && claude"
