#!/usr/bin/env bash
#
# payload_audit.sh — default-DENY payload audit (design v2 S5-3 / tasks 8.1).
#
# The release packaging gate: only the files named by payload_manifest.json
# (the derived allow-list, created in S0-D / PR 0) may ship. Every other file
# in the audited tree is denied, and each allowed file is additionally
# content-scanned with the SAME rules as scripts/secret_scan.sh — this script
# DELEGATES the content scan to it, so the two pattern lists cannot diverge.
#
# Explicit DENY additions (fail the audit wherever they appear):
#   config/idea-capture.yaml  config/hermes-mcp-profile.yaml.example
#   docs/MARCA.md  src/tools/dev_diary.py  engram-export.json
#   .env  .env.backup  .secrets/  mundos/  .git/
#   src/tools/opencode-bridge.py  start-opencode-*.ps1  sync-ideas.py.bak-*
#
# --allow FILE (S5b / task 8.5): extra shippable paths beyond the manifest —
# the explicit artifact extras (bootstraps, cores, launchers, requirements,
# LICENSE) and the shared dist tree. One path per line; '#' comments and blank
# lines allowed; an entry ending in '/' allows everything under that prefix
# (the content-hashed frontend/dist tree). Deny rules still win over --allow.
#
# --content-scan-skip PREFIX (S5b): files under the prefix are still
# path-checked (deny / manifest / allow) but are NOT content-scanned. Used for
# the derived frontend/dist tree: a BUILT artifact whose sources (frontend/src)
# are covered by the tree scan (scripts/secret_scan.sh --tree, exit 0) and
# whose baked origins are guarded by the S1-7 same-origin check; minified
# CSS/JS utility names (e.g. Tailwind/xyflow "sk-*" classes) false-positive the
# openai-key heuristic. No rule is weakened — only the scanned file set is
# scoped. Repeatable.
#
# Output: one "deny: <path> (<reason>)" line per denied path, plus the content
# scan hits forwarded from secret_scan.sh ("<path>:<line>: <rule>"). Matched
# values are NEVER printed. A summary line goes to stderr.
#
# Exit codes: 0 = clean, 1 = deny or content-scan finding, 2 = usage/manifest
# error.
#
# Candidate enumeration:
#   - default (no --root): the audit runs over the repository root and uses
#     the git-tracked surface (git ls-files -co --exclude-standard, i.e.
#     tracked + untracked-not-ignored). Gitignored files (.env, .secrets/,
#     mundos/, node_modules, ...) cannot ship from a git-based packaging
#     flow, so they are not audited here — the deny list protects
#     packaging/staging trees. Use --git-mode to force this for another repo.
#   - with an explicit --root (a packaging/staging tree or a test fixture):
#     every regular file under --root is audited via a filesystem walk,
#     including any .git/ that accidentally landed in the tree. Use
#     --walk-fs to force the filesystem walk for the repo root too.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRET_SCAN="$SCRIPT_DIR/secret_scan.sh"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MANIFEST="$ROOT/payload_manifest.json"
ALLOWLIST_ARGS=()
USE_DEFAULT_SCAN_ALLOWLIST=1
ALLOW=()
SCAN_SKIP=()
ENUM="auto"
ROOT_GIVEN=0
DENY_COUNT=0
SCAN_OUT=""
SCAN_EXIT=0
SCAN_LINES=0

# ---------------------------------------------------------------------------
# Explicit deny lists (tasks 8.1). Exact = path (any depth); dirs = any path
# component; globs = basename match.
# ---------------------------------------------------------------------------
DENY_EXACT="
config/idea-capture.yaml
config/hermes-mcp-profile.yaml.example
docs/MARCA.md
src/tools/dev_diary.py
src/tools/opencode-bridge.py
engram-export.json
.env
.env.backup
"

DENY_DIRS=".secrets mundos .git"

DENY_GLOBS="start-opencode-*.ps1 sync-ideas.py.bak-*"

usage() {
    cat <<'USAGE'
Usage: payload_audit.sh [--root DIR] [--manifest FILE] [--allow FILE]
                        [--content-scan-skip PREFIX] [--allowlist FILE]
                        [--no-default-allowlist] [--help]

  --root DIR             tree to audit (default: repo root)
  --manifest FILE        payload allow-list JSON (default: <root>/payload_manifest.json)
  --allow FILE           extra shippable paths (one per line; trailing '/'
                         allows a whole prefix; '#' comments allowed) — the
                         packaging extras and the shared dist tree
  --content-scan-skip PREFIX
                         path-check files under PREFIX but do NOT content-scan
                         them (the derived frontend/dist tree; repeatable)
  --allowlist FILE       forward an extra allowlist to the content scan
  --no-default-allowlist forward --no-default-allowlist to the content scan
  --git-mode             force git-tracked-surface enumeration
  --walk-fs              force a full filesystem walk
  --help                 show this help

Exit codes: 0 clean, 1 findings, 2 usage/manifest error.
USAGE
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --root)
            [ $# -ge 2 ] || usage
            shift
            ROOT="$1"
            ROOT_GIVEN=1
            ;;
        --manifest)
            [ $# -ge 2 ] || usage
            shift
            MANIFEST="$1"
            ;;
        --git-mode) ENUM="git" ;;
        --walk-fs) ENUM="fs" ;;
        --content-scan-skip)
            [ $# -ge 2 ] || usage
            shift
            SCAN_SKIP+=("$1")
            ;;
        --allow)
            [ $# -ge 2 ] || usage
            shift
            while IFS= read -r _line; do
                case "$_line" in
                    "" | \#*) continue ;;
                esac
                ALLOW+=("$_line")
            done < "$1"
            ;;
        --allowlist)
            [ $# -ge 2 ] || usage
            shift
            ALLOWLIST_ARGS+=(--allowlist "$1")
            ;;
        --no-default-allowlist)
            ALLOWLIST_ARGS+=(--no-default-allowlist)
            USE_DEFAULT_SCAN_ALLOWLIST=0
            ;;
        --help|-h) usage ;;
        -*) usage ;;
        *) usage ;;
    esac
    shift
done

if [ ! -f "$MANIFEST" ]; then
    echo "payload_audit: manifest not found: $MANIFEST" >&2
    echo "payload_audit: derive it with scripts/derive_payload_manifest.py (S0-D)" >&2
    exit 2
fi

if [ ! -x "$SECRET_SCAN" ]; then
    echo "payload_audit: content-scan dependency not found/executable: $SECRET_SCAN" >&2
    exit 2
fi

# The content-scan allow-list is a contract input, not an optimisation: both
# release ports read scripts/payload_scan_allowlist.txt, and a missing or
# unreadable file must fail the audit (exit 2) even when the stage happens to
# contain nothing to scan. Without this the audit could report "clean" on a
# tree it was never able to scan under the shared rules.
if [ "$USE_DEFAULT_SCAN_ALLOWLIST" -eq 1 ] \
    && [ ! -r "$SCRIPT_DIR/payload_scan_allowlist.txt" ]; then
    echo "payload_audit: cannot read the shared allow-list: $SCRIPT_DIR/payload_scan_allowlist.txt" >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# Manifest parsing: python3 (exact JSON) with a POSIX fallback that assumes
# the flat payload array emitted by scripts/derive_payload_manifest.py.
# ---------------------------------------------------------------------------
_extract_payload() {
    if command -v python3 >/dev/null 2>&1; then
        python3 - "$MANIFEST" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
for path in data.get("payload", []):
    print(path)
PY
    else
        sed -n '/"payload"[[:space:]]*:/,/^[[:space:]]*]/p' "$MANIFEST" \
            | grep -oE '"[^"]+"' \
            | sed '1d' \
            | tr -d '"'
    fi
}

PAYLOAD=()
while IFS= read -r _entry; do
    [ -z "$_entry" ] && continue
    PAYLOAD+=("$_entry")
done < <(_extract_payload)

_in_manifest() {
    local _rel="$1" _entry
    for _entry in "${PAYLOAD[@]+"${PAYLOAD[@]}"}"; do
        [ "$_rel" = "$_entry" ] && return 0
    done
    return 1
}

_is_deny_exact() {
    local _rel="$1" _entry
    for _entry in $DENY_EXACT; do
        case "$_rel" in
            "$_entry" | */"$_entry") return 0 ;;
        esac
    done
    return 1
}

_has_deny_dir() {
    local _rel="$1" _dir
    for _dir in $DENY_DIRS; do
        case "$_rel" in
            "$_dir" | */"$_dir"/*) return 0 ;;
        esac
    done
    return 1
}

_matches_deny_glob() {
    local _rel="$1" _base="${1##*/}" _glob
    for _glob in $DENY_GLOBS; do
        case "$_base" in
            $_glob) return 0 ;;
        esac
    done
    return 1
}

_in_allow() {
    local _rel="$1" _entry
    for _entry in "${ALLOW[@]+"${ALLOW[@]}"}"; do
        case "$_entry" in
            */)
                # prefix allow: everything under the entry (the dist tree)
                case "$_rel" in
                    "$_entry"*) return 0 ;;
                esac
                ;;
            *)
                # exact path, any depth (mirrors _in_manifest)
                case "$_rel" in
                    "$_entry" | */"$_entry") return 0 ;;
                esac
                ;;
        esac
    done
    return 1
}

# ---------------------------------------------------------------------------
# Candidate enumeration (documented above).
# ---------------------------------------------------------------------------
if [ "$ENUM" = "auto" ]; then
    if [ "$ROOT_GIVEN" -eq 0 ] && [ -d "$ROOT/.git" ]; then
        ENUM="git"
    else
        ENUM="fs"
    fi
fi

CANDIDATES=()
if [ "$ENUM" = "git" ]; then
    if [ ! -d "$ROOT/.git" ]; then
        echo "payload_audit: --git-mode requires a git repository at --root ($ROOT)" >&2
        exit 2
    fi
    while IFS= read -r _p; do
        CANDIDATES+=("$_p")
    done < <(git -C "$ROOT" ls-files -co --exclude-standard)
else
    while IFS= read -r _p; do
        CANDIDATES+=("${_p#$ROOT/}")
    done < <(find "$ROOT" -type f)
fi

ALLOWED=()
for _rel in "${CANDIDATES[@]+"${CANDIDATES[@]}"}"; do
    _rel="${_rel#./}"
    _reason=""
    if _is_deny_exact "$_rel"; then
        _reason="explicit deny path"
    elif _has_deny_dir "$_rel"; then
        _reason="explicit deny directory"
    elif _matches_deny_glob "$_rel"; then
        _reason="explicit deny glob"
    elif ! _in_manifest "$_rel" && ! _in_allow "$_rel"; then
        _reason="not in manifest allow-list"
    fi
    if [ -n "$_reason" ]; then
        printf 'deny: %s (%s)\n' "$_rel" "$_reason"
        DENY_COUNT=$((DENY_COUNT + 1))
    else
        ALLOWED+=("$_rel")
    fi
done

_scan_skipped() {
    local _rel="$1" _prefix
    for _prefix in "${SCAN_SKIP[@]+"${SCAN_SKIP[@]}"}"; do
        case "$_rel" in
            "$_prefix"*) return 0 ;;
        esac
    done
    return 1
}

# ---------------------------------------------------------------------------
# Content scan over the allowed files — delegated to secret_scan.sh so the
# pattern rules stay in exactly one place. Files under a --content-scan-skip
# prefix (the derived frontend/dist tree) are path-checked but not scanned.
# ---------------------------------------------------------------------------
SCAN_TARGETS=()
for _rel in "${ALLOWED[@]+"${ALLOWED[@]}"}"; do
    _scan_skipped "$_rel" || SCAN_TARGETS+=("$_rel")
done

if [ ${#SCAN_TARGETS[@]} -gt 0 ]; then
    SCAN_OUT=$("$SECRET_SCAN" --tree --root "$ROOT" \
        ${ALLOWLIST_ARGS[@]+"${ALLOWLIST_ARGS[@]}"} -- "${SCAN_TARGETS[@]}" 2>&1)
    SCAN_EXIT=$?
    if [ -n "$SCAN_OUT" ]; then
        printf '%s\n' "$SCAN_OUT"
        SCAN_LINES=$(printf '%s\n' "$SCAN_OUT" | grep -c .)
    fi
fi

if [ "$DENY_COUNT" -gt 0 ] || [ "$SCAN_EXIT" -ne 0 ]; then
    printf 'payload_audit: %d deny findings, %d content-scan hits\n' \
        "$DENY_COUNT" "$SCAN_LINES" >&2
    [ "$SCAN_EXIT" -eq 2 ] && exit 2
    exit 1
fi
printf 'payload_audit: clean (%d files allowed, no findings)\n' \
    "${#ALLOWED[@]}" >&2
exit 0