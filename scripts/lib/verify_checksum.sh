#!/usr/bin/env bash
# Demiurgos shared checksum verifier (design S3-2 / task 4.2).
#
# Verification order — NEVER system Python:
#   1. sha256sum            (Linux / most POSIX)
#   2. shasum -a 256        (macOS ships shasum, not sha256sum)
#   3. bundled-Python hashlib via `uv run python -c` (the installer's own
#      verified uv; UV_BIN env override for hermetic tests)
#
# The library is sourced by scripts/install-demiurgos.sh and also usable
# standalone:  verify_checksum.sh <file> <expected-sha256>
# Exit codes: 0 = match, 1 = mismatch or unusable, 2 = usage error.

verify_sha256() {
    local file="$1" expected="$2" actual="" tool=""
    if command -v sha256sum >/dev/null 2>&1; then
        tool="sha256sum"
        actual="$(sha256sum "$file" 2>/dev/null | awk '{print $1}')" || actual=""
    fi
    if [ -z "$actual" ] && command -v shasum >/dev/null 2>&1; then
        tool="shasum -a 256"
        actual="$(shasum -a 256 "$file" 2>/dev/null | awk '{print $1}')" || actual=""
    fi
    if [ -z "$actual" ]; then
        # Bundled-Python hashlib via the installer's verified uv — the last
        # resort on systems without sha256sum/shasum. Never a system python.
        local uv_bin="${UV_BIN:-uv}"
        tool="$uv_bin run python"
        actual="$("$uv_bin" run python -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$file" 2>/dev/null)" || actual=""
    fi
    if [ -z "$actual" ]; then
        printf 'verify_checksum: no verifier produced a hash for %s\n' "$file" >&2
        return 1
    fi
    if [ "$actual" = "$expected" ]; then
        return 0
    fi
    printf 'verify_checksum: MISMATCH for %s\n' "$file" >&2
    printf '  expected: %s\n  actual:   %s\n' "$expected" "$actual" >&2
    return 1
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    if [ "$#" -ne 2 ]; then
        printf 'usage: %s <file> <expected-sha256>\n' "$0" >&2
        exit 2
    fi
    verify_sha256 "$1" "$2"
    exit $?
fi