#!/usr/bin/env bash
# Demiurgos portable POSIX launcher (Linux + macOS).
#
# One start/stop/restart entry point for the web platform, derived entirely
# from its own location and the frozen install layout
# (docs/architecture/INSTALL_LAYOUT.md — S0-C). The same script serves the
# dev checkout and the installed layout (<install_root>/current) because both
# share the same relative structure (<root>/scripts/start-demiurgos.sh).
#
# It manages the FastAPI process (which serves the SPA and /api on one port)
# plus the Hermes gateway; the Vite dev/preview stack is gone. It uses ZERO
# system Python: the interpreter always comes from the layout venv
# (PYTHON_BIN) and the data-root .env is parsed in pure shell.
#
# Actions: start | restart | stop | install
#
# Headless guard: set DEMIURGOS_NO_BROWSER=1 (or true/yes) to skip the
# automatic browser launch on `start`. Harnesses, system_control restarts and
# CI run headless and MUST set it; without it, `start` opens the default
# browser at the API URL.
set -euo pipefail

# --- OS branch (S2-1/S2-5) -------------------------------------------------
# `uname -s` is the single OS discriminator. Every platform-specific tool
# (ss, lsof, xdg-open, open, /proc) is selected behind this branch; nothing
# is assumed present on the other OS.
OS="$(uname -s)"

# --- Paths derived from this launcher's own location (S0-C rule 1) --------
# APP_ROOT is <launcher_dir>/.. resolved LOGICALLY (not -P) so the installed
# layout keeps the `current` symlink visible: basename(APP_ROOT) == "current"
# means we run from <install_root>/current. One launcher serves both layouts.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Install root: $DEMIURGOS_HOME override -> the parent of `current` in the
# installed layout -> the checkout root in dev.
if [ -n "${DEMIURGOS_HOME:-}" ]; then
    INSTALL_ROOT="$DEMIURGOS_HOME"
elif [ "$(basename "$APP_ROOT")" = "current" ]; then
    INSTALL_ROOT="$(dirname "$APP_ROOT")"
else
    INSTALL_ROOT="$APP_ROOT"
fi

# Interpreter from the frozen layout (S2-4): the layout venv, never a
# system Python and never a hardcoded path.
PYTHON_BIN="$APP_ROOT/.venv/bin/python"
API_DIR="$APP_ROOT/src/tools/demiurgos-suite/wiki"
HERMES_BIN="$(command -v hermes 2>/dev/null || true)"
if [ -z "$HERMES_BIN" ] && [ -x "$HOME/.local/bin/hermes" ]; then
    HERMES_BIN="$HOME/.local/bin/hermes"
fi

# Persistent logs under the install root (S2-6); runtime state (pid files) in
# the per-user runtime dir from the layout contract — never hardcoded temp
# paths that a reboot or a different filesystem would lose.
LOG_DIR="$INSTALL_ROOT/logs"
RUNTIME_BASE="${XDG_RUNTIME_DIR:-$TMPDIR}"
STATE_DIR="$RUNTIME_BASE/demiurgos-launcher"
API_LOG="$LOG_DIR/demiurgos-api.log"
GATEWAY_LOG="$LOG_DIR/demiurgos-gateway.log"

# Data-root pointer (S2-8): platformdirs user_config_dir("demiurgos") — the
# byte-compatible location owned by data_root.py (POINTER_NAME = data-root.json).
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/demiurgos"
POINTER_FILE="$CONFIG_DIR/data-root.json"

# Ports. Overridable via env (DEMIURGOS_API_PORT / DEMIURGOS_GATEWAY_PORT) so
# parallel instances and the CI test matrix can use distinct ports; the
# defaults are the product ports.
API_PORT="${DEMIURGOS_API_PORT:-8000}"
GATEWAY_PORT="${DEMIURGOS_GATEWAY_PORT:-8642}"
DESKTOP_SOURCE="$APP_ROOT/desktop/Demiurgos.desktop"
APPLICATIONS_DIR="$HOME/.local/share/applications"
DESKTOP_DIR="$HOME/Desktop"

# --- Data-root resolution (S2-3) -------------------------------------------
# Order: existing env -> existing pointer (left intact) -> bootstrap-once the
# default <install_root>/data. An existing pointer is never re-oriented.
resolve_data_root() {
    local pointed=""
    if [ -n "${DEMIURGOS_DATA_ROOT:-}" ]; then
        DATA_ROOT="$DEMIURGOS_DATA_ROOT"
        return 0
    fi
    if [ -r "$POINTER_FILE" ]; then
        pointed="$(sed -n 's/.*"data_root"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$POINTER_FILE" | sed -n '1p')"
        if [ -n "$pointed" ]; then
            DATA_ROOT="$pointed"
            return 0
        fi
        printf 'Data-root pointer %s is unreadable; refusing to guess.\n' "$POINTER_FILE" >&2
        return 1
    fi
    # Bootstrap-once: write the byte-compatible pointer (data_root.py format)
    # so subsequent starts and the backend resolve the same root.
    DATA_ROOT="$INSTALL_ROOT/data"
    mkdir -p "$DATA_ROOT" "$CONFIG_DIR"
    printf '{\n  "schema_version": 1,\n  "data_root": "%s",\n  "updated_at": "%s"\n}\n' \
        "$DATA_ROOT" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$POINTER_FILE"
    printf 'Bootstrapped data root at %s\n' "$DATA_ROOT" >&2
}

# Parse the resolved data-root .env in pure shell (S2-4/S0-A) and export every
# DEMIURGOS_* key. The launcher is the bridge between the installer's seed
# (DEMIURGOS_AUTH_MODE=local-dev, DEMIURGOS_LANGUAGE, optional DEMIURGOS_WORLD)
# and the env-only backend (_auth_mode()); no system Python anywhere.
load_data_root_env() {
    local env_file="$DATA_ROOT/.env" key value
    [ -r "$env_file" ] || return 0
    while IFS='=' read -r key value || [ -n "$key" ]; do
        case "$key" in
            ''|'#'*) continue ;;
            DEMIURGOS_*)
                # Strip one layer of surrounding quotes and a trailing CR
                # (CRLF .env files) so the value reaches the app cleanly.
                value="${value%\"}"
                value="${value#\"}"
                value="${value%\'}"
                value="${value#\'}"
                value="${value%$'\r'}"
                export "$key=$value"
                ;;
        esac
    done < "$env_file"
}

ensure_runtime_dirs() {
    mkdir -p "$STATE_DIR" "$LOG_DIR"
}

pid_file() {
    printf '%s/%s.pid\n' "$STATE_DIR" "$1"
}

# Command line of a pid. `ps -ww -o command=` is the portable path — -ww is
# MANDATORY because macOS truncates the command line otherwise and the
# ownership match below would silently fail. /proc/<pid>/cmdline is a Linux
# fast path only, never assumed present on macOS.
command_of_pid() {
    local pid="$1"
    if [ "$OS" = "Linux" ] && [ -r "/proc/$pid/cmdline" ]; then
        tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true
    else
        ps -ww -o command= -p "$pid" 2>/dev/null || true
    fi
}

owned_pid() {
    local name="$1" pid file cmdline
    file="$(pid_file "$name")"
    [ -r "$file" ] || return 1
    read -r pid < "$file" || return 1
    case "$pid" in
        ''|*[!0-9]*) return 1 ;;
    esac
    cmdline="$(command_of_pid "$pid")"
    [ -n "$cmdline" ] || return 1
    case "$name" in
        api) [[ "$cmdline" == *"$PYTHON_BIN"* && "$cmdline" == *"uvicorn api_server:app"* ]] ;;
        gateway) [[ "$cmdline" == *"hermes gateway run"* ]] ;;
        *) return 1 ;;
    esac
}

remove_pid_file() {
    rm -f "$(pid_file "$1")"
}

# Listening check via a bash /dev/tcp probe (S2-5) — no `ss` required. The
# connection is opened and closed inside a subshell; nothing leaks.
port_is_listening() {
    local port="$1"
    ( : > "/dev/tcp/127.0.0.1/$port" ) 2>/dev/null
}

# PID owning a listening port (stop/restart only). Linux: `ss -Hlnpt` and its
# pid= marker; Darwin: `lsof -iTCP:<port> -sTCP:LISTEN -t`. A foreign owner is
# reported by the caller and NEVER killed (S2-5, spec "Port already in use").
port_owner_pid() {
    local port="$1" pid=""
    if [ "$OS" = "Darwin" ]; then
        pid="$(lsof -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | sed -n '1p' || true)"
    else
        pid="$(ss -Hlnpt 2>/dev/null \
            | grep ":$port[[:space:]]" \
            | grep -o 'pid=[0-9]*' \
            | sed -n 's/pid=//p' \
            | sed -n '1p' || true)"
    fi
    if [ -n "$pid" ] && [[ "$pid" =~ ^[0-9]+$ ]]; then
        printf '%s\n' "$pid"
    fi
}

# Verify that pid's cmdline identifies it as the named Demiurgos component.
# Shared by adopt_existing_component and the stop_component port fallback so
# both gate on the exact same matching. The API gate pins the layout venv
# python plus the uvicorn module — never adopt/kill an arbitrary `uvicorn`
# from another project or an unrelated port squatter.
_validate_cmdline_for_name() {
    local name="$1" pid="$2" cmdline
    cmdline="$(command_of_pid "$pid")"
    case "$name" in
        api) [[ ( "$cmdline" == *"$PYTHON_BIN"* && "$cmdline" == *"uvicorn api_server:app"* ) || "$cmdline" == *"$API_DIR"* ]] || return 1 ;;
        gateway) [[ "$cmdline" == *"hermes gateway run"* ]] || return 1 ;;
        *) return 1 ;;
    esac
}

adopt_existing_component() {
    local name="$1" port="$2" pid=""
    pid="$(port_owner_pid "$port")"
    [ -n "$pid" ] || return 1
    _validate_cmdline_for_name "$name" "$pid" || return 1
    printf '%s\n' "$pid" > "$(pid_file "$name")"
    printf 'Adopted existing %s (pid %s)\n' "$name" "$pid"
}

# Wait until a port is listening (bounded). Once `start_component` has either
# launched or adopted the component, "listening" is the readiness signal;
# port-squatting is already rejected by `start_component` before we get here.
wait_for_port() {
    local port="$1" seconds=0
    while [ "$seconds" -lt 20 ]; do
        if port_is_listening "$port"; then return 0; fi
        sleep 1
        seconds=$((seconds + 1))
    done
    return 1
}

# Wait until a port is no longer listening (bounded). `restart` starts right
# after `stop_all`; without this, `start_component` can `adopt` a process that
# is still inside its SIGTERM->exit window, record its (dying) pid, and leave
# the component down.
wait_for_port_free() {
    local port="$1" tries=0
    while [ "$tries" -lt 40 ]; do
        port_is_listening "$port" || return 0
        sleep 0.25
        tries=$((tries + 1))
    done
    return 1
}

# Send TERM, wait up to ~6s (30 x 0.2s), escalate to KILL — the standard
# shutdown sequence for launcher-managed processes. Children are killed
# BEFORE their parent so a process wrapper cannot leave its server child
# orphaned (reparented to init) when the wrapper dies first.
#
# Self-kill guard: the launcher must never TERM its own PID. When the API
# dispatches this script (``/api/system`` restart/shutdown), the launcher is
# spawned as a CHILD of the API process, so ``pgrep -P <api_pid>`` lists the
# launcher itself. Without this guard the launcher TERMs itself before it
# reaches ``kill -TERM <api_pid>`` — the API survives (stale process running
# old code), which is why "Reiniciar"/"Apagar Demiurgos" from the web UI
# never actually restarted the backend. Skip ``$$`` (and its subtree) so the
# kill reaches the API and the launcher keeps running to finish the sequence.
_kill_descendants() {
    local parent="$1" child
    for child in $(pgrep -P "$parent" 2>/dev/null || true); do
        [ "$child" = "$$" ] && continue
        _kill_descendants "$child"
    done
    kill -TERM "$parent" 2>/dev/null || true
}

_kill_process() {
    local pid="$1" child
    _kill_descendants "$pid"
    for _ in {1..30}; do
        kill -0 "$pid" 2>/dev/null || return 0
        sleep 0.2
    done
    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" 2>/dev/null || true
    fi
    # Clean up any descendant that survived the TERM phase.
    for child in $(pgrep -P "$pid" 2>/dev/null || true); do
        kill -KILL "$child" 2>/dev/null || true
    done
}

stop_component() {
    local name="$1" pid file port
    file="$(pid_file "$name")"
    if owned_pid "$name"; then
        read -r pid < "$file"
        _kill_process "$pid"
        printf 'Stopped %s (pid %s)\n' "$name" "$pid"
        remove_pid_file "$name"
        return 0
    fi

    # Port-based fallback: stop Demiurgos processes started outside the
    # launcher (no pid file). Never kill an arbitrary process squatting on
    # the port — the cmdline check below is the safety gate (2.10).
    case "$name" in
        api) port="$API_PORT" ;;
        gateway) port="$GATEWAY_PORT" ;;
        *) remove_pid_file "$name"; return 1 ;;
    esac

    pid="$(port_owner_pid "$port")"
    if [ -z "$pid" ]; then
        remove_pid_file "$name"
        return 0
    fi
    if ! _validate_cmdline_for_name "$name" "$pid"; then
        printf 'Skipped %s: port %s owner is not a Demiurgos process (pid %s)\n' \
            "$name" "$port" "$pid" >&2
        remove_pid_file "$name"
        return 1
    fi
    _kill_process "$pid"
    printf 'Stopped %s (pid %s)\n' "$name" "$pid"
    remove_pid_file "$name"
}

stop_all() {
    # `|| true`: a component whose port is held by a non-Demiurgos process
    # must not abort the shutdown of the rest of the stack under `set -e`.
    stop_component gateway || true
    stop_component api || true
    # Wait until every managed port is actually free so `start_component`
    # never adopts a process that is still shutting down.
    local port
    for port in "$GATEWAY_PORT" "$API_PORT"; do
        if ! wait_for_port_free "$port"; then
            printf 'Port %s still busy after stop; continuing anyway\n' "$port" >&2
        fi
    done
}

start_component() {
    local name="$1" pid port
    if owned_pid "$name"; then
        read -r pid < "$(pid_file "$name")"
        printf 'Already running %s (pid %s)\n' "$name" "$pid"
        return 0
    fi

    case "$name" in
        api) port="$API_PORT" ;;
        gateway) port="$GATEWAY_PORT" ;;
        *) printf 'Unknown component: %s\n' "$name" >&2; return 1 ;;
    esac
    if port_is_listening "$port"; then
        if adopt_existing_component "$name" "$port"; then
            return 0
        fi
        printf 'Cannot start %s: port %s is already in use by an untracked process\n' "$name" "$port" >&2
        return 1
    fi

    case "$name" in
        api)
            (cd "$API_DIR" && exec nohup "$PYTHON_BIN" -m uvicorn api_server:app \
                --host 127.0.0.1 --port "$API_PORT" >>"$API_LOG" 2>&1) & ;;
        gateway)
            # CWD = app root so Path.cwd()/.hermes/plugins resolves to the
            # project plugins; HERMES_ENABLE_PROJECT_PLUGINS=1 opts them in
            # (plugins.enabled in ~/.hermes/config.yaml gates which load).
            (cd "$APP_ROOT" && exec nohup env \
                DEMIURGOS_ROOT="$APP_ROOT" \
                HERMES_ENABLE_PROJECT_PLUGINS=1 \
                HERMES_GATEWAY_HOST=127.0.0.1 HERMES_GATEWAY_PORT="$GATEWAY_PORT" \
                "$HERMES_BIN" gateway run >>"$GATEWAY_LOG" 2>&1) & ;;
        *) return 1 ;;
    esac
    pid=$!
    printf '%s\n' "$pid" > "$(pid_file "$name")"
}

start_all() {
    ensure_runtime_dirs
    resolve_data_root
    load_data_root_env
    # Layout-contract exports: the launcher is the SOLE exporter of
    # DEMIURGOS_FRONTEND_DIST (S1-6) and the bridge for the data-root .env
    # auth mode (S0-A); DEMIURGOS_ROOT stays for legacy Hermes reads (S2-3).
    # Both children are subshells of this shell, so a single export reaches
    # the API and the Hermes gateway alike.
    export DEMIURGOS_DATA_ROOT="$DATA_ROOT"
    export DEMIURGOS_FRONTEND_DIST="$APP_ROOT/frontend/dist"
    export DEMIURGOS_ROOT="$APP_ROOT"

    # Hermes is OPTIONAL (S2-2): the app boots without the provider and the
    # assistant degrades. The gateway is started only when the CLI is found;
    # otherwise an advisory is printed and the boot continues.
    if [ -z "$HERMES_BIN" ] || [ ! -x "$HERMES_BIN" ]; then
        printf 'Hermes CLI not found; the assistant will be unavailable.\n' >&2
        printf 'Install or enable Hermes later to use the assistant.\n' >&2
    else
        start_component gateway
    fi
    start_component api

    # Required readiness covers the API ONLY (S2-2). The gateway is best-effort:
    # when present it is reported, but its absence never aborts the boot.
    if wait_for_port "$API_PORT"; then
        printf 'API ready on 127.0.0.1:%s\n' "$API_PORT"
    else
        printf 'API did not become ready; check its log\n' >&2
        return 1
    fi
    if [ -n "$HERMES_BIN" ] && [ -x "$HERMES_BIN" ]; then
        if wait_for_port "$GATEWAY_PORT"; then
            printf 'Hermes Gateway ready on 127.0.0.1:%s\n' "$GATEWAY_PORT"
        else
            printf 'Hermes Gateway did not become ready; check its log\n' >&2
        fi
    fi
}

open_browser() {
    local url="$1" opener=""
    # Headless suppression switch (S2b incident fix): a truthy
    # DEMIURGOS_NO_BROWSER (1|true|yes) skips the browser launch entirely.
    # Harnesses and CI set it; system_control restarts never open a tab.
    case "${DEMIURGOS_NO_BROWSER:-}" in
        1|true|yes|TRUE|YES|True)
            printf 'DEMIURGOS_NO_BROWSER is set; not opening %s\n' "$url" >&2
            return 0
            ;;
    esac
    case "$OS" in
        Darwin) opener="open" ;;
        *) opener="xdg-open" ;;
    esac
    if command -v "$opener" >/dev/null 2>&1; then
        nohup "$opener" "$url" >/dev/null 2>&1 &
    else
        printf 'Default browser opener not found; open %s manually\n' "$url" >&2
    fi
}

show_status() {
    printf '\nDemiurgos is running\n'
    printf 'API:      http://127.0.0.1:%s\n' "$API_PORT"
    if [ -n "$HERMES_BIN" ] && [ -x "$HERMES_BIN" ]; then
        printf 'Hermes:   127.0.0.1:%s\n' "$GATEWAY_PORT"
    else
        printf 'Hermes:   not installed (assistant unavailable)\n'
    fi
    printf 'Data root: %s\n' "$DATA_ROOT"
    printf 'Logs: %s, %s\n' "$API_LOG" "$GATEWAY_LOG"
    printf '\nServices continue running in the background.\n'
    # Only block for Enter when there is a real interactive terminal (the
    # script was launched from a terminal by hand). When launched "as a
    # program" (file manager, no TTY), never block — that left a zombie
    # waiting forever for input nobody would send.
    if [ -t 0 ]; then
        printf 'Press Enter to close this window.\n'
        read -r || true
    fi
}

install_desktop() {
    [ -f "$DESKTOP_SOURCE" ] || { printf 'Desktop file missing: %s\n' "$DESKTOP_SOURCE" >&2; return 1; }
    mkdir -p "$APPLICATIONS_DIR"
    # Substitute the app-root placeholder so the launcher survives moves.
    sed "s|@PROJECT_ROOT@|$APP_ROOT|g" "$DESKTOP_SOURCE" \
        > "$APPLICATIONS_DIR/Demiurgos.desktop"
    chmod 0644 "$APPLICATIONS_DIR/Demiurgos.desktop"
    if [ -d "$DESKTOP_DIR" ]; then
        sed "s|@PROJECT_ROOT@|$APP_ROOT|g" "$DESKTOP_SOURCE" \
            > "$DESKTOP_DIR/Demiurgos.desktop"
        chmod 0755 "$DESKTOP_DIR/Demiurgos.desktop"
    fi
    printf 'Installed: %s/Demiurgos.desktop\n' "$APPLICATIONS_DIR"
    [ -d "$DESKTOP_DIR" ] && printf 'Installed: %s/Demiurgos.desktop\n' "$DESKTOP_DIR"
}

usage() {
    printf 'Usage: %s {start|restart|stop|install}\n' "$0"
}

main() {
    local action="${1:-restart}"
    case "$action" in
        start) start_all; open_browser "http://127.0.0.1:$API_PORT"; show_status ;;
        # Restart does NOT reopen the browser: the already-open tab detects the
        # backend is back and reloads itself (auto-reload in the Navbar), so
        # opening a new tab would double-enter the app.
        restart) stop_all; start_all; show_status ;;
        stop) stop_all ;;
        install) install_desktop ;;
        *) usage >&2; return 2 ;;
    esac
}

main "$@"