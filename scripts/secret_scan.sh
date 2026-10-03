#!/usr/bin/env bash
#
# secret_scan.sh — dependency-free secret/PII scanner for the Demiurgos repo.
#
# Scans for the author-specific secret patterns defined by the release gate
# (design v2 S5-3 / tasks 8.1). Uses only grep/sed/git — no gitleaks, no
# pre-commit, no Python required at runtime.
#
# Patterns (this file is the SINGLE source of truth; payload_audit.sh
# delegates its content scan to this script so the lists cannot diverge):
#
#   bot-token       [0-9]{8,10}:[A-Za-z0-9_-]{35}        Telegram bot tokens
#   openai-key      sk-[A-Za-z0-9_-]{20,}                OpenAI-style keys
#   google-api-key  AIza[0-9A-Za-z_-]{35}                Google API keys
#   author-path     H:\ | /home/ | C:\Users | spreadsheetId
#   author-id       <telegram-id>
#
# Output: one line per hit — "<path>:<line>: <rule-name>". The matched value
# is NEVER printed; hits are identified by path + line + rule name only.
#
# Exit codes: 0 = no hits, 1 = hits found, 2 = usage error.
#
# Modes:
#   --staged   scan the staged changes (the git index) — the pre-commit path.
#              Content is read from the INDEX (git show :<path>), not the
#              working tree, so only what is about to be committed is scanned
#              and pre-existing baseline files never block new commits.
#   --tree     scan the whole tree (default) — the CI/audit path.
#              - inside a git repo: tracked + untracked-not-ignored files
#                (git ls-files -co --exclude-standard)
#              - otherwise: every regular file under --root
#   <paths>    scan exactly these files (resolved against --root when
#              relative).
#
# Allowlist (explicit and documented):
#   --allowlist FILE          add an allowlist file (one path pattern per
#                             line; '#' comments and blank lines allowed)
#   --no-default-allowlist    drop the built-in allowlist
#
#   The built-in allowlist covers ONLY:
#     * the scanner's own files — they contain the rule definitions by
#       design, so they necessarily match some patterns;
#     * obviously-fake test fixtures — placeholder values only, never real
#       credentials and never real author data;
#     * test harnesses that deliberately reference the patterns as
#       functional predicates (PATH scrubbing) or negative assertions;
#     * the two personal Google-Sheets tools (dev_diary.py, sync-ideas.py) —
#       their only residual match is the required Sheets API parameter name
#       `spreadsheetId=`; the real sheet ids are read from environment
#       variables, never committed.
#   No entry hides a real credential or a real author path: baseline
#   violations must surface in tree/CI scans until their owning slice cleans
#   them up.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MODE="tree"
ROOT="$REPO_ROOT"
ALLOWLIST_FILES=()
USE_DEFAULT_ALLOWLIST=1
POSITIONAL=()
HIT_COUNT=0

# ---------------------------------------------------------------------------
# Rules — single source of truth. Lines: rule-name<TAB>extended-regex.
# TAB (not '|') is the delimiter so the author-path alternation stays intact.
# ---------------------------------------------------------------------------
RULES_SRC=$(cat <<'EOF'
bot-token	[0-9]{8,10}:[A-Za-z0-9_-]{35}
openai-key	sk-[A-Za-z0-9_-]{20,}
google-api-key	AIza[0-9A-Za-z_-]{35}
author-path	H:\\|/home/|C:\\Users|spreadsheetId
author-id	<telegram-id>
EOF
)

RULE_NAMES=()
RULE_PATTERNS=()
while IFS=$'\t' read -r _name _pattern; do
    [ -z "$_name" ] && continue
    RULE_NAMES+=("$_name")
    RULE_PATTERNS+=("$_pattern")
done <<< "$RULES_SRC"

# ---------------------------------------------------------------------------
# Built-in allowlist — documented above: scanner self-files + fake fixtures.
# ---------------------------------------------------------------------------
DEFAULT_ALLOWLIST=(
    # Scanner self-files: contain the rule definitions by design.
    scripts/secret_scan.sh
    scripts/payload_audit.sh
    scripts/payload_audit.ps1
    .gitleaks.toml
    # Obvious test fixtures only (fake values for the secret-scan suite).
    src/tools/demiurgos-suite/wiki/tests/test_payload_audit.py
    # Pre-existing frontend fixtures with placeholder paths/ids.
    frontend/src/__tests__/BackupSection.test.tsx
    frontend/src/__tests__/MethodologyLibrary.test.tsx
    # Test harnesses that deliberately reference the patterns:
    #   test_launcher_boot_smoke.py — scrubs /home/ paths from PATH so the
    #     hermetic boot never touches the real home directory (functional).
    #   test_launcher_portable.py   — negative assertions: "H:\"/"C:\Users"
    #     must NOT appear in the shipped launchers.
    #   test_launcher_boot_rollback.py — same /home/ PATH scrub as the boot
    #     smoke; rollback harness fixtures (app/<version> stubs).
    src/tools/demiurgos-suite/wiki/tests/test_launcher_boot_smoke.py
    src/tools/demiurgos-suite/wiki/tests/test_launcher_portable.py
    src/tools/demiurgos-suite/wiki/tests/test_launcher_boot_rollback.py
    # Personal author tooling (Google Sheets): the ONLY residual match is the
    # required Sheets API parameter name `spreadsheetId=`; the real sheet ids
    # are read from env vars (DEMIURGOS_DEV_DIARY_SHEET_ID / GOOGLE_SHEETS_ID),
    # never committed. No real value is hidden by this entry.
    src/tools/dev_diary.py
    src/tools/sync-ideas.py
)

usage() {
    cat <<'USAGE'
Usage: secret_scan.sh [--staged|--tree] [--root DIR] [--allowlist FILE]
                      [--no-default-allowlist] [--] [path ...]

  --staged               scan staged changes from the git index
  --tree                 scan the whole tree (default)
  --root DIR             base directory (default: repo root)
  --allowlist FILE       extra allowlist file (path patterns, one per line)
  --no-default-allowlist drop the built-in allowlist
  --help                 show this help

Exit codes: 0 no hits, 1 hits found, 2 usage error.
Output: "<path>:<line>: <rule-name>" per hit; matched values are never printed.
USAGE
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --staged) MODE="staged" ;;
        --tree) MODE="tree" ;;
        --root)
            [ $# -ge 2 ] || usage
            shift
            ROOT="$1"
            ;;
        --allowlist)
            [ $# -ge 2 ] || usage
            shift
            ALLOWLIST_FILES+=("$1")
            ;;
        --no-default-allowlist) USE_DEFAULT_ALLOWLIST=0 ;;
        --help|-h) usage ;;
        --)
            shift
            while [ $# -gt 0 ]; do
                POSITIONAL+=("$1")
                shift
            done
            ;;
        -*) usage ;;
        *) POSITIONAL+=("$1") ;;
    esac
    shift
done

ALLOWLIST=()
if [ "$USE_DEFAULT_ALLOWLIST" -eq 1 ]; then
    ALLOWLIST=("${DEFAULT_ALLOWLIST[@]}")
fi
for _af in "${ALLOWLIST_FILES[@]}"; do
    if [ ! -r "$_af" ]; then
        echo "secret_scan: cannot read allowlist: $_af" >&2
        exit 2
    fi
    while IFS= read -r _line; do
        case "$_line" in
            "" | \#*) continue ;;
        esac
        ALLOWLIST+=("$_line")
    done < "$_af"
done

# _is_allowed <display-path> — allowlisted when equal to an entry or ending
# with "/<entry>" (works for absolute and root-relative paths alike).
_is_allowed() {
    local _p="$1" _entry
    for _entry in "${ALLOWLIST[@]+"${ALLOWLIST[@]}"}"; do
        case "$_p" in
            "$_entry" | */"$_entry") return 0 ;;
        esac
    done
    return 1
}

# _scan_file <display-path> <target-file> — grep every rule against the
# target file (working-tree file or a staged blob) and print hits as
# "<display-path>:<line>: <rule-name>" without ever echoing the matched
# value. Display and target differ when paths are root-relative.
_scan_file() {
    local _display="$1" _target="$2"
    local _i _name _pattern _hits _ln
    for _i in "${!RULE_NAMES[@]}"; do
        _name="${RULE_NAMES[$_i]}"
        _pattern="${RULE_PATTERNS[$_i]}"
        _hits=$(grep -nIE "$_pattern" "$_target" 2>/dev/null | cut -d: -f1)
        for _ln in $_hits; do
            printf '%s:%s: %s\n' "$_display" "$_ln" "$_name"
            HIT_COUNT=$((HIT_COUNT + 1))
        done
    done
}

case "$MODE" in
    staged)
        if [ ! -d "$ROOT/.git" ]; then
            echo "secret_scan: --staged requires a git repository at --root ($ROOT)" >&2
            exit 2
        fi
        _tmp=""
        while IFS= read -r _path; do
            [ -z "$_path" ] && continue
            _tmp="$(mktemp)" || exit 2
            git -C "$ROOT" show ":$_path" 2>/dev/null > "$_tmp" || {
                rm -f "$_tmp"
                continue
            }
            if _is_allowed "$_path"; then
                rm -f "$_tmp"
                continue
            fi
            _scan_file "$_path" "$_tmp"
            rm -f "$_tmp"
        done < <(git -C "$ROOT" diff --cached --name-only --diff-filter=ACMR)
        ;;
    tree)
        if [ ${#POSITIONAL[@]} -gt 0 ]; then
            for _p in "${POSITIONAL[@]}"; do
                case "$_p" in
                    /*) _f="$_p" ;;
                    *) _f="$ROOT/$_p" ;;
                esac
                if [ ! -f "$_f" ]; then
                    echo "secret_scan: not a regular file: $_p" >&2
                    exit 2
                fi
                _is_allowed "$_p" && continue
                _scan_file "$_p" "$_f"
            done
        elif [ -d "$ROOT/.git" ]; then
            while IFS= read -r _p; do
                _is_allowed "$_p" && continue
                _scan_file "$_p" "$ROOT/$_p"
            done < <(git -C "$ROOT" ls-files -co --exclude-standard)
        else
            while IFS= read -r _p; do
                _rel="${_p#$ROOT/}"
                _is_allowed "$_rel" && continue
                _scan_file "$_rel" "$_p"
            done < <(find "$ROOT" -type f)
        fi
        ;;
esac

if [ "$HIT_COUNT" -gt 0 ]; then
    exit 1
fi
exit 0