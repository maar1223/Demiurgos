#!/usr/bin/env bash
# Demiurgos POSIX installer core (S3a — design S3-1..S3-7, tasks 4.1-4.12).
#
# Provisions a runnable Demiurgos on Linux/macOS with NO pre-installed
# Python/Node/compiler, NO admin rights and NO source clone:
#
#   1. floors preflight      macOS >= 13, glibc >= 2.28, free disk,
#                            Windows LongPathsEnabled parity note (S3b owns it)
#   2. version resolve       DEMIURGOS_VERSION else `latest`
#   3. download+verify       version.json, SHA256SUMS (+ .minisig when
#                            present), payload from DEMIURGOS_URL_BASE
#                            (https:// or file:// for hermetic harnesses)
#   4. uv provisioning       pinned UV_VERSION, verified against the baked
#                            checksum (DEMIURGOS_UV_SHA256 override for tests),
#                            codesign --verify --deep --strict on macOS (M2)
#   5. runtime               UV_PYTHON_INSTALL_DIR uv python install 3.12,
#                            uv venv --python 3.12 <stage>/.venv,
#                            uv pip install --require-hashes
#                            --only-binary=:all: -r requirements.lock
#                            (mandatory; optional extras best-effort)
#   6. atomic staging        <install_root>/.staging/<version>-<rand> on the
#                            SAME filesystem -> mv -> app/<version> ->
#                            flip `current` symlink; failure leaves NO
#                            runnable state
#   7. data root             bootstrap-once pointer + .env seed (S0-A):
#                            only when neither env nor pointer exists
#
# The core NEVER runs a package manager other than the verified uv, NEVER
# executes files from the payload (only the launcher the user starts runs),
# and NEVER requires elevation.
#
# Env contract (frozen layout, docs/architecture/INSTALL_LAYOUT.md):
#   DEMIURGOS_URL_BASE   channel base (REQUIRED; https:// or file://)
#   DEMIURGOS_VERSION    pin; default `latest`
#   DEMIURGOS_HOME       install root; default ~/.demiurgos
#   DEMIURGOS_DATA_ROOT  data root override (wins); default pointer/bootstrap
#   DEMIURGOS_UV_SHA256  expected uv archive sha256 (test seam; release
#                        pipeline bakes the real value at publish time)
#   UV_VERSION           pinned uv version
#   DEMIURGOS_LANGUAGE   seeded data-root locale (default es)
#   DEMIURGOS_WORLD      optional seeded world
#   DEMIURGOS_SEED_ONLY  "1" -> seed-only entry point: run ONLY the
#                        data-root bootstrap-once + .env seed (design S3-7)
#                        and exit 0. No download, no uv, no staging, no
#                        DEMIURGOS_URL_BASE required. Resolution order is the
#                        installer's own (DEMIURGOS_DATA_ROOT env -> existing
#                        pointer -> bootstrap-once). Idempotent: an existing
#                        pointer and .env are preserved byte-for-byte. The
#                        gated-write regression harness
#                        (test_install_auth_gated_write.py) invokes this mode
#                        to exercise the REAL shipping seed path.
#
# Decision #3565 supersedes the old "musl unsupported" wording: musl selects
# the musl uv binary and proceeds; the actual mandatory closure is what
# decides. Real musl/Intel confirmation is the before-S5 gate (D3).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/verify_checksum.sh
source "$SCRIPT_DIR/lib/verify_checksum.sh"

# Work dirs created under the staging root (same filesystem, never a temp dir
# on another FS). Cleaned on exit so a failed install leaves no debris and no
# runnable state; the committed app/<version> is never touched.
WORK_DIRS=""

cleanup() {
    local d
    for d in $WORK_DIRS; do
        rm -rf "$d"
    done
    if [ -n "${STAGE_DIR:-}" ]; then
        rm -rf "$STAGE_DIR"
    fi
}
trap cleanup EXIT

# --- defaults -------------------------------------------------------------
URL_BASE="${DEMIURGOS_URL_BASE:-}"
INSTALL_ROOT="${DEMIURGOS_HOME:-$HOME/.demiurgos}"
VERSION="${DEMIURGOS_VERSION:-latest}"
UV_VERSION="${UV_VERSION:-0.5.24}"
uv="$INSTALL_ROOT/bin/uv"
UV_PYTHON_INSTALL_DIR="$INSTALL_ROOT/python"
VENV_PYTHON_REL=".venv/bin/python"
STAGING_ROOT="$INSTALL_ROOT/.staging"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/demiurgos"
POINTER_FILE="$CONFIG_DIR/data-root.json"
MACOS_MIN_MAJOR=13
GLIBC_MIN="2.28"
MIN_FREE_KB=2097152   # 2 GiB
OS="$(uname -s)"
ARCH="$(uname -m)"
LIBC="glibc"

fail() {
    printf 'install-demiurgos: error: %s\n' "$1" >&2
    exit 1
}

warn() {
    printf 'install-demiurgos: warning: %s\n' "$1" >&2
}

# --- OS / arch / libc ------------------------------------------------------

uv_arch() {
    case "$ARCH" in
        x86_64|amd64) printf 'x86_64' ;;
        aarch64|arm64) printf 'aarch64' ;;
        *) fail "unsupported architecture: $ARCH" ;;
    esac
}

detect_libc() {
    if [ -f /etc/alpine-release ]; then
        LIBC="musl"
    elif command -v ldd >/dev/null 2>&1 && ldd --version 2>&1 | grep -qi musl; then
        LIBC="musl"
    fi
}

uv_target() {
    local a
    a="$(uv_arch)"
    case "$OS" in
        Linux)
            if [ "$LIBC" = "musl" ]; then
                printf '%s-unknown-linux-musl\n' "$a"
            else
                printf '%s-unknown-linux-gnu\n' "$a"
            fi
            ;;
        Darwin)
            printf '%s-apple-darwin\n' "$a"
            ;;
        *)
            fail "unsupported OS: $OS (this core covers Linux and macOS; Windows is S3b)"
            ;;
    esac
}

# --- floors preflight (4.4) ------------------------------------------------

version_ge() {  # a b  -> a >= b as dotted numbers
    local a="$1" b="$2" a_major a_minor b_major b_minor
    a_major="${a%%.*}"; a_minor="${a#*.}"
    b_major="${b%%.*}"; b_minor="${b#*.}"
    [ "$a_major" -gt "$b_major" ] && return 0
    [ "$a_major" -lt "$b_major" ] && return 1
    [ "${a_minor:-0}" -ge "${b_minor:-0}" ]
}

check_floors() {
    case "$OS" in
        Darwin)
            local sw major
            sw="$(sw_vers -productVersion 2>/dev/null || true)"
            major="${sw%%.*}"
            if [ -z "$major" ] || [ "$major" -lt "$MACOS_MIN_MAJOR" ]; then
                fail "macOS $MACOS_MIN_MAJOR or newer is required (found ${sw:-unknown}); upgrade macOS and re-run"
            fi
            if [ "$(uv_arch)" = "x86_64" ]; then
                warn "Intel macOS detected: optional extras (markitdown/watchdog) are degraded or unavailable; the app itself runs"
            fi
            ;;
        Linux)
            if [ "$LIBC" = "musl" ]; then
                printf '%s\n' "install-demiurgos: musl/Alpine detected: selecting the musl uv binary and attempting the wheels-only closure; failing only if the mandatory closure actually fails (the full-matrix proof + published floors is the before-S5 gate (D3))"
            else
                local glibc_ver
                glibc_ver="$(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}' || true)"
                if [ -z "$glibc_ver" ] || ! version_ge "$glibc_ver" "$GLIBC_MIN"; then
                    fail "glibc $GLIBC_MIN or newer is required (found ${glibc_ver:-unknown}); upgrade the OS and re-run"
                fi
            fi
            ;;
        *)
            fail "unsupported OS: $OS (this core covers Linux and macOS; Windows is S3b)"
            ;;
    esac
    local free_kb
    free_kb="$(df -Pk "$INSTALL_ROOT" 2>/dev/null | awk 'NR==2 {print $4}' || true)"
    if [ -z "$free_kb" ] || [ "$free_kb" -lt "$MIN_FREE_KB" ]; then
        fail "at least 2 GiB of free disk space is required at $INSTALL_ROOT (found ${free_kb:-unknown} KiB); free space and re-run"
    fi
    printf '%s\n' "install-demiurgos: note: the Windows floor (LongPathsEnabled) is enforced by the S3b Windows core (parity note)"
}

# --- download helpers (https + file:// test seam) ---------------------------

download() {  # url dest
    case "$1" in
        file://*) cp "${1#file://}" "$2" ;;
        https://*) curl --proto '=https' --tlsv1.2 --retry 3 --max-time 120 -fsSL -o "$2" "$1" ;;
        *) fail "unsupported URL scheme in $1 (use https:// or file://)" ;;
    esac
}

download_stdout() {  # url  -> stdout
    case "$1" in
        file://*) cat "${1#file://}" ;;
        https://*) curl --proto '=https' --tlsv1.2 --retry 3 --max-time 120 -fsSL "$1" ;;
        *) fail "unsupported URL scheme in $1 (use https:// or file://)" ;;
    esac
}

json_str() {  # file key  -> first "key": "value"
    sed -n "s/.*\"$2\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" "$1" | sed -n '1p'
}

sha_for() {  # sums_file name -> first sha256 for name
    awk -v name="$2" '$2==name {print $1; exit}' "$1"
}

# --- version resolve + release download (4.3) -------------------------------

resolve_version() {
    if [ "$VERSION" = "latest" ]; then
        VERSION="$(download_stdout "$URL_BASE/latest" | tr -d '[:space:]' | sed -n '1p')"
    fi
    [ -n "$VERSION" ] || fail "could not resolve a version from $URL_BASE/latest; set DEMIURGOS_VERSION explicitly and re-run"
    printf 'install-demiurgos: resolved version %s\n' "$VERSION" >&2
}

fetch_and_verify_payload() {
    local workdir version_json sums payload_name expected
    workdir="$STAGING_ROOT/.work-$VERSION-$$"
    WORK_DIRS="$WORK_DIRS $workdir"
    mkdir -p "$workdir"
    download "$URL_BASE/version.json" "$workdir/version.json" \
        || fail "cannot download version.json from $URL_BASE; check the channel and re-run"
    download "$URL_BASE/SHA256SUMS" "$workdir/SHA256SUMS" \
        || fail "cannot download SHA256SUMS from $URL_BASE; check the channel and re-run"
    # Signature file is downloaded when present; verification is S5b's gate.
    download "$URL_BASE/SHA256SUMS.minisig" "$workdir/SHA256SUMS.minisig" 2>/dev/null || true

    payload_name="$(json_str "$workdir/version.json" posix)"
    [ -n "$payload_name" ] || payload_name="demiurgos-app-$VERSION.tar.gz"
    PAYLOAD_FILE="$workdir/$payload_name"
    download "$URL_BASE/$payload_name" "$PAYLOAD_FILE" \
        || fail "cannot download $payload_name from $URL_BASE; check the channel and re-run"

    expected="$(sha_for "$workdir/SHA256SUMS" "$payload_name")"
    [ -n "$expected" ] || fail "no checksum entry for $payload_name in SHA256SUMS; fix the channel and re-run"
    verify_sha256 "$PAYLOAD_FILE" "$expected" \
        || fail "checksum mismatch for $payload_name; the download is corrupt or tampered — fix the channel and re-run"
}

# --- uv provisioning (4.5/4.6, M2) ------------------------------------------

uv_expected_sha256() {
    if [ -n "${DEMIURGOS_UV_SHA256:-}" ]; then
        printf '%s\n' "$DEMIURGOS_UV_SHA256"
        return 0
    fi
    # Baked per-target checksums live here in the release build (S5a fills the
    # real values for the pinned UV_VERSION at publish time). Empty table with
    # no override -> refuse to install an unverified toolchain.
    local t
    t="$(uv_target)"
    case "$t" in
        x86_64-unknown-linux-gnu) printf '%s\n' "${UV_SHA_X86_64_LINUX_GNU:-}" ;;
        aarch64-unknown-linux-gnu) printf '%s\n' "${UV_SHA_AARCH64_LINUX_GNU:-}" ;;
        x86_64-unknown-linux-musl) printf '%s\n' "${UV_SHA_X86_64_LINUX_MUSL:-}" ;;
        aarch64-unknown-linux-musl) printf '%s\n' "${UV_SHA_AARCH64_LINUX_MUSL:-}" ;;
        x86_64-apple-darwin) printf '%s\n' "${UV_SHA_X86_64_DARWIN:-}" ;;
        aarch64-apple-darwin) printf '%s\n' "${UV_SHA_AARCH64_DARWIN:-}" ;;
        *) fail "unsupported uv target: $t" ;;
    esac
}

provision_uv() {
    local target expected url workdir uvfile
    target="$(uv_target)"
    expected="$(uv_expected_sha256)"
    [ -n "$expected" ] || fail "no uv checksum available for $target; set DEMIURGOS_UV_SHA256 or rebuild with baked checksums — refusing an unverified toolchain"
    url="$URL_BASE/uv/uv-$target-$UV_VERSION.tar.gz"
    workdir="$STAGING_ROOT/.uv-$VERSION-$$"
    WORK_DIRS="$WORK_DIRS $workdir"
    mkdir -p "$workdir"
    UV_ARCHIVE="$workdir/uv.tar.gz"
    download "$url" "$UV_ARCHIVE" \
        || fail "cannot download $url (uv provider unreachable); no runnable state was left — re-run when the provider is reachable"
    verify_sha256 "$UV_ARCHIVE" "$expected" \
        || fail "checksum mismatch for the uv archive $url; refusing to install an unverified toolchain — fix the channel and re-run"
    tar -xzf "$UV_ARCHIVE" -C "$workdir" || fail "cannot extract the uv archive; it may be corrupt — re-run"
    uvfile="$(find "$workdir" -maxdepth 2 -type f -name uv | sed -n '1p')"
    [ -n "$uvfile" ] || fail "the uv archive contains no uv binary; fix the channel and re-run"
    mkdir -p "$INSTALL_ROOT/bin"
    cp "$uvfile" "$uv"
    chmod +x "$uv"
    if [ "$OS" = "Darwin" ] && command -v codesign >/dev/null 2>&1; then
        codesign --verify --deep --strict "$uv" || fail "codesign verification failed for $uv (Gatekeeper/quarantine); see the docs"
    fi
    printf 'install-demiurgos: uv %s installed at %s\n' "$UV_VERSION" "$uv" >&2
}

# --- stage, venv, install (4.6/4.7/4.8) --------------------------------------

find_req_file() {  # name -> first match under the staged tree
    local name="$1"
    for cand in "$STAGE_DIR/$name" "$STAGE_DIR/src/tools/demiurgos-suite/$name"; do
        if [ -f "$cand" ]; then
            printf '%s\n' "$cand"
            return 0
        fi
    done
    return 1
}

stage_and_install() {
    local req opt
    STAGE_DIR="$STAGING_ROOT/$VERSION-$RANDOM"
    mkdir -p "$STAGE_DIR"
    tar -xzf "$PAYLOAD_FILE" -C "$STAGE_DIR" \
        || { rm -rf "$STAGE_DIR"; fail "cannot extract the payload; it may be corrupt — re-run"; }

    UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" "$uv" python install 3.12 \
        || { rm -rf "$STAGE_DIR"; fail "uv python install failed (uv unreachable or broken); no runnable state was left — re-run"; }
    UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" "$uv" venv --python 3.12 "$STAGE_DIR/.venv" \
        || { rm -rf "$STAGE_DIR"; fail "uv venv creation failed; no runnable state was left — re-run"; }

    req="$(find_req_file requirements.lock || true)"
    [ -n "$req" ] || req="$(find_req_file requirements.txt || true)"
    [ -n "$req" ] || { rm -rf "$STAGE_DIR"; fail "no hash-locked requirements file (requirements.lock) in the payload; refusing a non-locked install — fix the channel and re-run"; }

    if ! "$uv" pip install --python "$STAGE_DIR/.venv/bin/python" --require-hashes --only-binary=:all: -r "$req"; then
        rm -rf "$STAGE_DIR"
        fail "the mandatory wheel-only install failed; aborting with no runnable half-install — see the error above and re-run"
    fi

    opt="$(find_req_file requirements-optional.txt || true)"
    if [ -n "$opt" ]; then
        "$uv" pip install --python "$STAGE_DIR/.venv/bin/python" --only-binary=:all: -r "$opt" \
            || warn "optional extras failed to install; the app runs with degraded optional features (document conversion / live watching unavailable)"
    else
        warn "no requirements-optional.txt in the payload; optional extras are skipped"
    fi
}

commit_staging() {
    mkdir -p "$INSTALL_ROOT/app"
    mv "$STAGE_DIR" "$INSTALL_ROOT/app/$VERSION" \
        || { rm -rf "$STAGE_DIR"; fail "cannot move the staged app into app/$VERSION (staging is on the same filesystem); re-run"; }
    STAGE_DIR=""
    ln -sfn "app/$VERSION" "$INSTALL_ROOT/current" \
        || fail "cannot flip current -> app/$VERSION; the previous version (if any) is untouched"
    printf 'install-demiurgos: installed %s at %s/current\n' "$VERSION" "$INSTALL_ROOT" >&2
}

# --- data-root bootstrap-once + .env seed (4.9, S0-A) ------------------------

seed_env_file() {
    local env_file locale
    ENV_FILE="$DATA_ROOT/.env"
    if [ ! -f "$ENV_FILE" ]; then
        locale="${DEMIURGOS_LANGUAGE:-es}"
        {
            printf 'DEMIURGOS_AUTH_MODE=local-dev\n'
            printf 'DEMIURGOS_LANGUAGE=%s\n' "$locale"
            if [ -n "${DEMIURGOS_WORLD:-}" ]; then
                printf 'DEMIURGOS_WORLD=%s\n' "$DEMIURGOS_WORLD"
            fi
        } > "$ENV_FILE"
        printf 'install-demiurgos: seeded %s (DEMIURGOS_AUTH_MODE=local-dev)\n' "$ENV_FILE" >&2
    fi
}

bootstrap_data_root() {
    local pointed
    if [ -n "${DEMIURGOS_DATA_ROOT:-}" ]; then
        DATA_ROOT="$DEMIURGOS_DATA_ROOT"
        printf 'install-demiurgos: using DEMIURGOS_DATA_ROOT=%s (env override; pointer untouched)\n' "$DATA_ROOT" >&2
        return 0
    fi
    if [ -r "$POINTER_FILE" ]; then
        pointed="$(sed -n 's/.*"data_root"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$POINTER_FILE" | sed -n '1p')"
        if [ -n "$pointed" ]; then
            DATA_ROOT="$pointed"
            printf 'install-demiurgos: preserving existing data-root pointer -> %s\n' "$DATA_ROOT" >&2
            return 0
        fi
        fail "data-root pointer $POINTER_FILE is unreadable; refusing to guess"
    fi
    # Bootstrap-once: pointer + .env seed, only when neither env nor pointer
    # exists. Format is byte-compatible with data_root.py (schema_version 1,
    # indent 2, trailing newline) so Python's read_pointer reads it back.
    DATA_ROOT="$INSTALL_ROOT/data"
    mkdir -p "$CONFIG_DIR" "$DATA_ROOT" "$DATA_ROOT/mundos" "$DATA_ROOT/ideas" "$DATA_ROOT/data" "$DATA_ROOT/config"
    printf '{\n  "schema_version": 1,\n  "data_root": "%s",\n  "updated_at": "%s"\n}\n' \
        "$DATA_ROOT" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$POINTER_FILE"
    printf 'install-demiurgos: bootstrapped data root at %s\n' "$DATA_ROOT" >&2
    seed_env_file
}

# --- seed-only entry point (S0-A; test/ops seam) -----------------------------
# DEMIURGOS_SEED_ONLY=1 performs ONLY the data-root bootstrap-once + .env seed
# (design S3-7) and exits 0 — the exact code path the full install runs at the
# end (bootstrap_data_root), so the gated-write regression harness
# (test_install_auth_gated_write.py) exercises the REAL shipping seed against a
# tmp HOME/XDG_CONFIG_HOME/DEMIURGOS_HOME. Never downloads, never touches uv,
# never requires DEMIURGOS_URL_BASE. Idempotence is preserved: an existing
# pointer and an existing .env are left byte-for-byte untouched.
if [ "${DEMIURGOS_SEED_ONLY:-0}" = "1" ]; then
    bootstrap_data_root
    printf 'install-demiurgos: seed-only done; data root is %s\n' "$DATA_ROOT" >&2
    exit 0
fi

# --- main --------------------------------------------------------------------

[ -n "$URL_BASE" ] || fail "DEMIURGOS_URL_BASE is not set; it is required (https:// or file:// channel base)"

detect_libc
mkdir -p "$INSTALL_ROOT"
check_floors
resolve_version

# Idempotent re-run: same version already current -> exit 0, nothing to do.
if [ -L "$INSTALL_ROOT/current" ] && [ "$(readlink "$INSTALL_ROOT/current")" = "app/$VERSION" ] && [ -d "$INSTALL_ROOT/app/$VERSION" ]; then
    printf 'install-demiurgos: %s is already installed and current; nothing to do\n' "$VERSION" >&2
    exit 0
fi

mkdir -p "$STAGING_ROOT"
fetch_and_verify_payload
provision_uv
stage_and_install
commit_staging
bootstrap_data_root

printf '%s\n' "install-demiurgos: done. Start Demiurgos with:"
printf '%s\n' "  $INSTALL_ROOT/current/scripts/start-demiurgos.sh start"