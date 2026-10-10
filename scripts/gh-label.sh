#!/usr/bin/env bash
# gh-label — add/remove issue or PR labels without the `gh pr edit --add-label`
# GraphQL bug.
#
# Background: `gh pr edit --add-label` fails with
#   GraphQL: Projects (classic) is being deprecated ... (repository.pullRequest.projectCards)
# because the command still requests the legacy `projectCards` field, which was
# removed from the GitHub API in April 2025. Updating `gh` does NOT fix it (the
# field is still referenced in pkg/cmd/pr/edit/edit.go as of v2.98.0); there is
# no upstream fix yet (cli/cli#11769). This helper routes through the REST API,
# which is unaffected.
#
# Usage:
#   gh-label add   <repo-owner/repo> <issue-or-pr-number> <label>
#   gh-label remove <repo-owner/repo> <issue-or-pr-number> <label>
#
# Examples:
#   gh-label add   maar1223/Demiurgos 67 "type:feature"
#   gh-label remove maar1223/Demiurgos 67 "type:bug"
#
# Exit codes: 0 on success, non-zero on failure.
set -euo pipefail

usage() {
  sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

action="${1:-}"
repo="${2:-}"
number="${3:-}"
label="${4:-}"

if [[ "$action" != "add" && "$action" != "remove" ]]; then
  echo "error: first argument must be 'add' or 'remove'" >&2
  usage
fi

[[ -n "$repo" ]] && [[ -n "$number" ]] && [[ -n "$label" ]] || usage

# Validate the repo shape (owner/name) and that the target is numeric.
if [[ ! "$repo" =~ ^[^/]+/[^/]+$ ]]; then
  echo "error: repo must be <owner>/<name>, got '${repo}'" >&2
  exit 1
fi
if [[ ! "$number" =~ ^[0-9]+$ ]]; then
  echo "error: number must be numeric, got '${number}'" >&2
  exit 1
fi

url="repos/${repo}/issues/${number}/labels"
encoded_label=$(printf '%s' "$label" | tr ' ' '-')

case "$action" in
  add)
    # POST /repos/{owner}/{repo}/issues/{n}/labels { "labels": ["<label>"] }
    gh api -X POST "$url" -f "labels[]=${encoded_label}" >/dev/null
    echo "added label '${label}' to ${repo}#${number}"
    ;;
  remove)
    # DELETE /repos/{owner}/{repo}/issues/{n}/labels/{name}
    if ! gh api -X DELETE "${url}/${encoded_label}" >/dev/null 2>&1; then
      echo "error: could not remove label '${label}' (not present?)" >&2
      exit 1
    fi
    echo "removed label '${label}' from ${repo}#${number}"
    ;;
esac
