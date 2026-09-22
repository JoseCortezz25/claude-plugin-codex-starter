#!/usr/bin/env bash
# PreToolUse hook (Write|Edit|NotebookEdit): deny writes into a Codex brand project
# unless the session was started at that project's root.
set -euo pipefail

LOCK="codex-lock.json"
input="$(cat)"
cwd="$(jq -r '.cwd // empty' <<<"$input" 2>/dev/null || true)"
path="$(jq -r '.tool_input.file_path // .tool_input.notebook_path // empty' <<<"$input" 2>/dev/null || true)"
[[ -n "$path" ]] || exit 0

session_root="${CLAUDE_PROJECT_DIR:-$cwd}"
[[ -n "$session_root" ]] || exit 0

# Resolve a relative target against the hook cwd.
[[ "$path" == /* ]] || path="${cwd:-$session_root}/$path"

# Walk up to the nearest existing directory (the file itself may not exist yet).
dir="$(dirname "$path")"
while [[ ! -d "$dir" && "$dir" != "/" ]]; do
  dir="$(dirname "$dir")"
done
dir="$(cd "$dir" && pwd -P)"

project=""
while :; do
  if [[ -f "$dir/$LOCK" ]]; then
    project="$dir"
    break
  fi
  [[ "$dir" == "/" ]] && break
  dir="$(dirname "$dir")"
done

[[ -n "$project" ]] || exit 0

if [[ -d "$session_root" ]]; then
  session_root="$(cd "$session_root" && pwd -P)"
fi
[[ "$project" == "$session_root" ]] && exit 0

jq -n --arg project "$project" --arg root "$session_root" '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: ("This file belongs to the Codex brand project at " + $project + ", but this session was started at " + $root + ". The project'"'"'s rules and protections only load in a session started inside it. Tell the user (in Spanish) to open a new session there: cd \"" + $project + "\" && claude")
  }
}'
