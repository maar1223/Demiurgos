#!/usr/bin/env bash
# Demiurgos shared integrity verifier (design S3-2 / task 4.2 + S5b task 8.4).
#
# Checksum verification order — NEVER system Python:
#   1. sha256sum            (Linux / most POSIX)
#   2. shasum -a 256        (macOS ships shasum, not sha256sum)
#   3. bundled-Python hashlib via `uv run python -c` (the installer's own
#      verified uv; UV_BIN env override for hermetic tests)
#
# Signature verification (S5b): verify_minisig checks the channel
# SHA256SUMS.minisig against the embedded minisign PUBLIC key BEFORE any
# checksum is trusted. The public key is already embedded below; it must match
# the private key held in the repository secret `MINISIGN_SECRET_KEY`. If you
# regenerate the signing key (`minisign -G`), re-embed the matching public key
# here and in the other three carrier files (install.sh, install.ps1,
# scripts/lib/verify_checksum.ps1). The MINISIGN_PUBKEY env override is the
# documented seam used by the CI smoke and the hermetic tests.
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

# --- S5b: signed-manifest gate (task 8.4) -----------------------------------
# Real public key line (the RW... line of minisign.pub) generated with
# `minisign -G` (S5b signing-key custody, set 2026-10-02).
DEFAULT_MINISIGN_PUBKEY="RWRZGmxh1+0HULxpc0FTGSGQCy4fyfNiukXM3bBxt2MmI+PEMPEBcSiy"

verify_minisig() {  # sums_file sig_file [pubkey]
    local sums="$1" sig="$2" pubkey="${3:-${MINISIGN_PUBKEY:-$DEFAULT_MINISIGN_PUBKEY}}"
    if ! command -v minisign >/dev/null 2>&1; then
        printf 'verify_checksum: minisign is required to verify the signed manifest; install it (apt install minisign / brew install minisign / https://jedisct1.github.io/minisign/) and re-run\n' >&2
        return 1
    fi
    if [ ! -f "$sig" ]; then
        printf 'verify_checksum: signature file %s is missing; the channel manifest is not signed — refusing to continue\n' "$sig" >&2
        return 1
    fi
    if ! minisign -Vm "$sums" -P "$pubkey" >/dev/null 2>&1; then
        printf 'verify_checksum: SIGNATURE VERIFICATION FAILED for %s; the manifest is tampered or the public key is wrong — refusing to continue\n' "$sums" >&2
        return 1
    fi
    return 0
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    if [ "$#" -ne 2 ]; then
        printf 'usage: %s <file> <expected-sha256>\n' "$0" >&2
        exit 2
    fi
    verify_sha256 "$1" "$2"
    exit $?
fi