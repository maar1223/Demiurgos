#!/usr/bin/env bash
# Provision the product-owned Hermes runtime (S5/S7, hermes-core-runtime T3).
#
# The runtime is the pinned Demiurgos fork, installed under the product root so
# it never touches the user's personal ~/.hermes (config, .env, profiles) and
# never resolves `hermes` from the user's PATH:
#
#   <install root>/hermes-agent   pinned git checkout (exact-install launcher
#                                 at <checkout>/.hermes/bin/hermes)
#   <install root>/hermes         dedicated HERMES_HOME (skills, tools store)
#   <install root>/hermes/tools   HERMES_RUNTIME_DIR (pm tool store)
#
# A pre-existing Hermes on the machine is detected and reported, never
# modified. Provisioning is idempotent: a checkout already at the pin with a
# usable launcher returns immediately; a stale checkout is replaced only after
# the pinned tree has been fetched successfully.
#
# The setup script normally publishes a `hermes` convenience into the user's
# ~/.local/bin and edits the user's shell rc. Product provisioning runs it
# with a scratch HOME so those writes land in the scratch dir and are deleted
# with it; the checkout's own exact-install launcher is the product entry point.
#
# Usage:
#   provision-hermes.sh [--install-root PATH]
#   provision-hermes.sh --check [--install-root PATH]
#
# Test seams (documented, never used in normal installs):
#   DEMIURGOS_HERMES_FORK_URL  override the fork URL
#   DEMIURGOS_HERMES_PIN       override the pinned commit
#   DEMIURGOS_HERMES_SKIP=1    skip provisioning entirely (hermetic installers)
#   DEMIURGOS_GIT              git executable (default: git)

set -euo pipefail

# --- fixed product contract ------------------------------------------------
HERMES_FORK_URL="${DEMIURGOS_HERMES_FORK_URL:-https://github.com/maar1223/hermes-agent-demiurgos.git}"
HERMES_PIN="${DEMIURGOS_HERMES_PIN:-d046ff9905b8470c4a0cfd5e9da566986056b438}"
GIT_BIN="${DEMIURGOS_GIT:-git}"

log() { printf 'provision-hermes: %s\n' "$*" >&2; }
warn() { printf 'provision-hermes: warning: %s\n' "$*" >&2; }
fail() {
    printf 'provision-hermes: error: %s\n' "$*" >&2
    exit 1
}

# --- paths (same chain as the launchers/installers) -------------------------
resolve_paths() {
    local root_override="${1:-}"
    if [ -n "$root_override" ]; then
        INSTALL_ROOT="$root_override"
    else
        INSTALL_ROOT="${DEMIURGOS_HOME:-$HOME/.demiurgos}"
    fi
    HERMES_HOME="${DEMIURGOS_HERMES_HOME:-$INSTALL_ROOT/hermes}"
    AGENT_ROOT="${DEMIURGOS_HERMES_AGENT_ROOT:-$INSTALL_ROOT/hermes-agent}"
    RUNTIME_DIR="$HERMES_HOME/tools"
}

# --- helpers ---------------------------------------------------------------
is_valid_pin() {
    case "$1" in
        *[!0-9a-fA-F]*|"") return 1 ;;
    esac
    [ "${#1}" -eq 40 ]
}

checkout_head() {
    "$GIT_BIN" -C "$1" rev-parse HEAD 2>/dev/null || true
}

checkout_matches_pin() {
    local dir="$1" head
    [ -d "$dir/.git" ] || return 1
    head="$(checkout_head "$dir")"
    [ "$head" = "$HERMES_PIN" ]
}

runtime_launcher() {
    printf '%s' "$AGENT_ROOT/.hermes/bin/hermes"
}

is_provisioned() {
    checkout_matches_pin "$AGENT_ROOT" && [ -x "$(runtime_launcher)" ]
}

# Detect (never modify) a Hermes the user already has.
report_prior_install() {
    local found=0 on_path
    on_path="$(command -v hermes 2>/dev/null || true)"
    if [ -n "$on_path" ]; then
        printf 'provision-hermes: found an existing Hermes on PATH: %s (left untouched)\n' "$on_path"
        found=1
    fi
    if [ -d "$HOME/.hermes" ]; then
        printf 'provision-hermes: found an existing personal profile: %s (left untouched)\n' "$HOME/.hermes"
        found=1
    fi
    if [ "$found" = "1" ]; then
        printf 'provision-hermes: the product-owned runtime below is used regardless.\n'
    fi
}

# Fail closed with expected-vs-found when the product runtime is not usable.
check_runtime() {
    local head launcher
    if [ ! -d "$AGENT_ROOT/.git" ]; then
        printf 'provision-hermes: expected the product runtime at %s (pin %s), found nothing; re-run the installer or this script.\n' \
            "$AGENT_ROOT" "$HERMES_PIN" >&2
        return 1
    fi
    head="$(checkout_head "$AGENT_ROOT")"
    if [ "$head" != "$HERMES_PIN" ]; then
        printf 'provision-hermes: expected pin %s at %s, found %s; re-run the installer or this script.\n' \
            "$HERMES_PIN" "$AGENT_ROOT" "${head:-unknown}" >&2
        return 1
    fi
    launcher="$(runtime_launcher)"
    if [ ! -x "$launcher" ]; then
        printf 'provision-hermes: expected the runtime launcher at %s, found none; re-run the installer or this script.\n' \
            "$launcher" >&2
        return 1
    fi
    return 0
}

# Fetch the pinned commit into an EMPTY destination (no full clone).
fetch_pinned_checkout() {
    local dest="$1"
    is_valid_pin "$HERMES_PIN" \
        || fail "invalid pinned commit '$HERMES_PIN' (expected 40 hexadecimal characters)"
    "$GIT_BIN" init -q "$dest" \
        || fail "cannot initialise the runtime checkout at $dest (is git installed?)"
    "$GIT_BIN" -C "$dest" remote add origin "$HERMES_FORK_URL" \
        || fail "cannot configure the runtime fork remote ($HERMES_FORK_URL)"
    "$GIT_BIN" -C "$dest" fetch --depth 1 origin "$HERMES_PIN" \
        || fail "cannot fetch the pinned commit $HERMES_PIN from $HERMES_FORK_URL"
    "$GIT_BIN" -C "$dest" checkout -q FETCH_HEAD \
        || fail "cannot check out the pinned commit $HERMES_PIN"
    [ "$(checkout_head "$dest")" = "$HERMES_PIN" ] \
        || fail "expected pin $HERMES_PIN, the fetched checkout reports $(checkout_head "$dest")"
    # S3: the Demiurgos patch (tool_choice "none" -> empty toolset) must be
    # present in the pinned tree, not merely in the fork's history.
    grep -q 'no_tools' "$dest/gateway/platforms/api_server.py" \
        || fail "the pinned tree at $dest does not carry the Demiurgos no_tools patch (S3)"
}

# Replace a stale checkout only after the pinned tree is fully fetched.
provision_checkout() {
    local staging backup
    if checkout_matches_pin "$AGENT_ROOT"; then
        log "runtime checkout already at the pinned commit $HERMES_PIN"
        return 0
    fi
    mkdir -p "$INSTALL_ROOT"
    staging="$INSTALL_ROOT/.provision-hermes.$$"
    rm -rf "$staging"
    mkdir -p "$staging/tree"
    fetch_pinned_checkout "$staging/tree"
    if [ -e "$AGENT_ROOT" ]; then
        backup="$INSTALL_ROOT/hermes-agent.previous-$(date +%Y%m%d%H%M%S)"
        mv "$AGENT_ROOT" "$backup" \
            || { rm -rf "$staging"; fail "cannot move the previous checkout aside to $backup"; }
        warn "previous runtime checkout moved to $backup"
    fi
    mv "$staging/tree" "$AGENT_ROOT" \
        || { rm -rf "$staging"; fail "cannot install the pinned checkout at $AGENT_ROOT"; }
    rm -rf "$staging"
}

# Run the pinned setup with product paths and a scratch HOME so the user's
# ~/.local/bin and shell rc files are never written.
run_setup() {
    local setup="$AGENT_ROOT/setup-hermes.sh" scratch
    [ -f "$setup" ] || fail "the pinned tree at $AGENT_ROOT has no setup-hermes.sh; fix the pin and re-run"
    scratch="$INSTALL_ROOT/.provision-hermes-home.$$"
    rm -rf "$scratch"
    mkdir -p "$scratch"
    log "installing the runtime (first run can take 1-5 minutes)"
    if ! (
        cd "$AGENT_ROOT"
        HOME="$scratch" \
        XDG_CONFIG_HOME="$scratch/.config" \
        XDG_DATA_HOME="$scratch/.local/share" \
        XDG_CACHE_HOME="$scratch/.cache" \
        UV_CACHE_DIR="$scratch/uv-cache" \
        UV_PYTHON_INSTALL_DIR="$scratch/uv-python" \
        HERMES_HOME="$HERMES_HOME" \
        HERMES_RUNTIME_DIR="$RUNTIME_DIR" \
        HERMES_AGENT_ROOT="$AGENT_ROOT" \
        bash "$setup"
    ); then
        rm -rf "$scratch"
        fail "setup-hermes.sh failed; expected pin $HERMES_PIN at $AGENT_ROOT — fix the error above and re-run"
    fi
    rm -rf "$scratch"
}

provision() {
    report_prior_install
    if is_provisioned; then
        log "runtime already provisioned at $AGENT_ROOT (pin $HERMES_PIN)"
        return 0
    fi
    is_valid_pin "$HERMES_PIN" \
        || fail "invalid pinned commit '$HERMES_PIN' (expected 40 hexadecimal characters)"
    provision_checkout
    run_setup
    check_runtime \
        || fail "post-install verification failed; the assistant runtime is not usable"
    log "runtime ready at $AGENT_ROOT (pin $HERMES_PIN)"
}

usage() {
    printf 'usage: provision-hermes.sh [--install-root PATH] | --check [--install-root PATH]\n' >&2
}

main() {
    local mode="install" root_override=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --check) mode="check" ;;
            --install-root)
                shift
                [ "$#" -gt 0 ] || { usage; exit 2; }
                root_override="$1"
                ;;
            --help|-h) usage; exit 0 ;;
            *) usage; fail "unknown argument: $1" ;;
        esac
        shift
    done
    resolve_paths "$root_override"
    if [ "${DEMIURGOS_HERMES_SKIP:-0}" = "1" ]; then
        log "provisioning skipped (DEMIURGOS_HERMES_SKIP=1)"
        return 0
    fi
    if [ "$mode" = "check" ]; then
        check_runtime
        return $?
    fi
    provision
}

# Source-safe: tests source this file to exercise the helpers hermetically.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
