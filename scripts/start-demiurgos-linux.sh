#!/usr/bin/env bash
# Demiurgos Linux launcher. Manages only processes started by this script.
#
# Two frontend modes, selected by DEMIURGOS_SKIP_FRONTEND:
#   unset  -> dev frontend: `vite dev` on 5173 (HMR; no build needed).
#   "1"    -> MVP: build the production bundle and serve it with `vite preview`
#             on 4173. `restart` rebuilds too, so a UI-driven restart never
#             leaves a stale bundle served.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
# Author data root (WU-3 / SC-DR-3.4). Exported ONCE so every child launched
# by start_component inherits it: the API and the Hermes gateway are both
# subshells of this shell, so this single export reaches both. The resolver
# reads DEMIURGOS_DATA_ROOT first (then the user-config pointer, else raises),
# so this alone satisfies the launcher path. Kept separate from DEMIURGOS_ROOT,
# which Hermes may still read.
export DEMIURGOS_DATA_ROOT="$PROJECT_ROOT"
API_DIR="$PROJECT_ROOT/src/tools/demiurgos-suite/wiki"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
HERMES_BIN="$(command -v hermes 2>/dev/null || true)"
if [ -z "$HERMES_BIN" ] && [ -x "$HOME/.local/bin/hermes" ]; then
    HERMES_BIN="$HOME/.local/bin/hermes"
fi
STATE_DIR="/tmp/demiurgos-launcher"
DESKTOP_SOURCE="$PROJECT_ROOT/desktop/Demiurgos.desktop"
APPLICATIONS_DIR="$HOME/.local/share/applications"
DESKTOP_DIR="$HOME/Desktop"

API_PORT=8000
FRONTEND_PORT=5173
GATEWAY_PORT=8642
PREVIEW_PORT=4173
API_LOG="/tmp/demiurgos-api.log"
FRONTEND_LOG="/tmp/demiurgos-frontend.log"
GATEWAY_LOG="/tmp/demiurgos-gateway.log"
PREVIEW_LOG="/tmp/demiurgos-mvp.log"

mkdir -p "$STATE_DIR"

# Whether the dev frontend should be launched. The MVP launcher sets
# DEMIURGOS_SKIP_FRONTEND=1 to start only the backend (API + gateway) and
# serve the production build itself on the preview port.
frontend_enabled() {
    [ "${DEMIURGOS_SKIP_FRONTEND:-}" != "1" ]
}

# Whether the MVP production preview should be managed instead of the dev
# frontend. Same mode signal as `frontend_enabled` (DEMIURGOS_SKIP_FRONTEND),
# deliberately: /api/system dispatches this script with the API's inherited
# environment, so an in-app "Reiniciar Demiurgos" also rebuilds and restarts
# the preview instead of leaving a stale `dist` served on the preview port.
preview_enabled() {
    [ "${DEMIURGOS_SKIP_FRONTEND:-}" = "1" ]
}

load_project_auth_mode() {
    local mode
    mode="$(PROJECT_ENV="$PROJECT_ROOT/.env" python3 - <<'PY'
from os import environ
from pathlib import Path

path = Path(environ["PROJECT_ENV"])
if path.is_file():
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("DEMIURGOS_AUTH_MODE="):
            print(line.split("=", 1)[1].strip())
            break
PY
)"
    if [ -n "$mode" ]; then
        export DEMIURGOS_AUTH_MODE="$mode"
    fi
}

pid_file() {
    printf '%s/%s.pid\n' "$STATE_DIR" "$1"
}

owned_pid() {
    local name="$1" pid file cmdline
    file="$(pid_file "$name")"
    [ -r "$file" ] || return 1
    read -r pid < "$file" || return 1
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    [ -r "/proc/$pid/cmdline" ] || return 1
    cmdline="$(tr '\0' ' ' < "/proc/$pid/cmdline")"
    case "$name" in
        api) [[ "$cmdline" == *"uvicorn api_server:app"* ]] ;;
        frontend) [[ ( "$cmdline" == *"vite"* || "$cmdline" == *"npm run dev"* ) && "$cmdline" == *"--host 127.0.0.1"* ]] ;;
        preview) [[ ( "$cmdline" == *"vite preview"* || "$cmdline" == *"npm run preview"* ) && "$cmdline" == *"--host 127.0.0.1"* ]] ;;
        gateway) [[ "$cmdline" == *"hermes gateway run"* ]] ;;
        *) return 1 ;;
    esac
}

remove_pid_file() {
    rm -f "$(pid_file "$1")"
}

# Send TERM, wait up to ~6s (30 x 0.2s), escalate to KILL — the standard
# shutdown sequence for launcher-managed processes. Children are killed
# BEFORE their parent so a dev-server wrapper (``npm run dev`` → ``vite``)
# cannot leave its server child orphaned (reparented to init) when the
# wrapper dies first — which kept the frontend alive after "Apagar Demiurgos".
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
    # the port — the cmdline check below is the safety gate.
    case "$name" in
        api) port="$API_PORT" ;;
        frontend) port="$FRONTEND_PORT" ;;
        preview) port="$PREVIEW_PORT" ;;
        gateway) port="$GATEWAY_PORT" ;;
        *) remove_pid_file "$name"; return 1 ;;
    esac

    pid="$(port_owner_pid "$port" || true)"
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
    stop_component frontend || true
    stop_component preview || true
    stop_component api || true
    stop_component gateway || true
    # `restart` starts immediately after this; wait until every managed port
    # is actually free so `start_component` never adopts a process that is
    # still shutting down.
    local port
    for port in "$FRONTEND_PORT" "$PREVIEW_PORT" "$API_PORT" "$GATEWAY_PORT"; do
        if ! wait_for_port_free "$port"; then
            printf 'Port %s still busy after stop; continuing anyway\n' "$port" >&2
        fi
    done
}

port_is_listening() {
    local port="$1"
    command -v ss >/dev/null 2>&1 || return 1
    ss -Hln 2>/dev/null | grep -Eq ":${port}[[:space:]]"
}

port_owner_pid() {
    local port="$1"
    ss -Hlnpt 2>/dev/null | PORT="$port" python3 -c '
import os
import re
import sys

port = os.environ["PORT"]
for line in sys.stdin:
    if re.search(rf":{re.escape(port)}\b", line):
        match = re.search(r"pid=(\d+)", line)
        if match:
            print(match.group(1))
            break
'
}

# Verify that pid's cmdline identifies it as the named Demiurgos component.
# Shared by adopt_existing_component and the stop_component port fallback so
# both gate on the exact same matching.
_validate_cmdline_for_name() {
    local name="$1" pid="$2" cmdline=""
    [ -r "/proc/$pid/cmdline" ] || return 1
    cmdline="$(tr '\0' ' ' < "/proc/$pid/cmdline")"
    case "$name" in
        # The API is launched as `python -m uvicorn api_server:app` from a cd'd
        # API_DIR, so the cmdline never contains $API_DIR — only the venv python
        # path plus the uvicorn module. Gate on those (project-scoped venv ⇒
        # never adopt/kill an arbitrary `uvicorn` from another project).
        api) [[ ( "$cmdline" == *"$PROJECT_ROOT/.venv/bin/python"* && "$cmdline" == *"uvicorn api_server:app"* ) || "$cmdline" == *"$API_DIR"* ]] || return 1 ;;
        frontend) [[ ( "$cmdline" == *"$FRONTEND_DIR"* && "$cmdline" == *"vite"* ) || "$cmdline" == *"npm run dev"* ]] || return 1 ;;
        preview) [[ ( "$cmdline" == *"$FRONTEND_DIR"* && "$cmdline" == *"vite"* && "$cmdline" == *"preview"* ) || ( "$cmdline" == *"npm run preview"* && "$cmdline" == *"--host 127.0.0.1"* ) ]] || return 1 ;;
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
# launched or adopted the component, "listening" is the readiness signal. The
# old "listening but not loopback" -> error heuristic produced false negatives
# when a service (hermes) briefly binds before settling on its final address,
# aborting an otherwise-healthy start; port-squatting is already rejected by
# `start_component` before we get here.
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
# the component down. Waiting for the port to clear makes the restart settle
# on a live process instead of racing a corpse.
wait_for_port_free() {
    local port="$1" tries=0
    while [ "$tries" -lt 40 ]; do
        port_is_listening "$port" || return 0
        sleep 0.25
        tries=$((tries + 1))
    done
    return 1
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
        frontend) port="$FRONTEND_PORT" ;;
        preview) port="$PREVIEW_PORT" ;;
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
        frontend)
            (cd "$FRONTEND_DIR" && exec nohup npm run dev -- \
                --host 127.0.0.1 --port "$FRONTEND_PORT" >>"$FRONTEND_LOG" 2>&1) & ;;
        preview)
            (cd "$FRONTEND_DIR" && exec nohup npm run preview -- \
                --host 127.0.0.1 --port "$PREVIEW_PORT" >>"$PREVIEW_LOG" 2>&1) & ;;
        gateway)
            # CWD = repo root so Path.cwd()/.hermes/plugins resolves to the
            # project plugins; HERMES_ENABLE_PROJECT_PLUGINS=1 opts them in
            # (plugins.enabled in ~/.hermes/config.yaml gates which load).
            (cd "$PROJECT_ROOT" && exec nohup env \
                DEMIURGOS_ROOT="$PROJECT_ROOT" \
                HERMES_ENABLE_PROJECT_PLUGINS=1 \
                HERMES_GATEWAY_HOST=127.0.0.1 HERMES_GATEWAY_PORT="$GATEWAY_PORT" \
                "$HERMES_BIN" gateway run >>"$GATEWAY_LOG" 2>&1) & ;;
        *) return 1 ;;
    esac
    pid=$!
    printf '%s\n' "$pid" > "$(pid_file "$name")"
}

# Rebuild the production bundle the MVP preview serves. Runs synchronously
# BEFORE the preview server so a restart never serves a half-written bundle
# (`vite build` empties `dist` at the start of the build). A build failure is
# reported but does NOT abort the stack: the API still comes back and the
# preview serves whatever bundle is on disk — which a mid-build `vite`
# failure may have left incomplete, so check the log on failure.
build_preview_bundle() {
    printf 'Building production bundle (MVP)…\n' >&2
    if ! (cd "$FRONTEND_DIR" && npm run build >>"$PREVIEW_LOG" 2>&1); then
        printf 'Build failed; the preview may serve an incomplete bundle. See %s\n' "$PREVIEW_LOG" >&2
        return 1
    fi
}

start_all() {
    load_project_auth_mode
    if [ -z "$HERMES_BIN" ] || [ ! -x "$HERMES_BIN" ]; then
        printf 'Hermes CLI not found\n' >&2
        return 1
    fi
    start_component gateway
    # MVP: build + start the preview BEFORE the API. The already-open tab
    # polls the API and reloads the moment it answers, so the preview must
    # already be listening — otherwise the reload races a still-building
    # `dist` and the browser shows a connection error.
    if preview_enabled; then
        build_preview_bundle || true
        start_component preview
    fi
    start_component api
    if frontend_enabled; then
        start_component frontend
    fi

    local ports=("$GATEWAY_PORT" "$API_PORT")
    if preview_enabled; then
        ports+=("$PREVIEW_PORT")
    elif frontend_enabled; then
        ports+=("$FRONTEND_PORT")
    fi
    local port name
    for port in "${ports[@]}"; do
        case "$port" in
            "$GATEWAY_PORT") name="Hermes Gateway" ;;
            "$API_PORT") name="API" ;;
            "$PREVIEW_PORT") name="MVP preview" ;;
            *) name="Frontend" ;;
        esac
        if wait_for_port "$port"; then
            printf '%s ready on 127.0.0.1:%s\n' "$name" "$port"
        else
            printf '%s did not become ready; check its log\n' "$name" >&2
            return 1
        fi
    done
}

open_frontend() {
    local port="$FRONTEND_PORT"
    if preview_enabled; then
        port="$PREVIEW_PORT"
    fi
    if ! command -v xdg-open >/dev/null 2>&1; then
        printf 'Default browser opener not found; open http://127.0.0.1:%s manually\n' "$port" >&2
        return 0
    fi
    nohup xdg-open "http://127.0.0.1:${port}" >/dev/null 2>&1 &
}

show_status() {
    printf '\nDemiurgos is running\n'
    printf 'API:     http://127.0.0.1:%s\n' "$API_PORT"
    if preview_enabled; then
        printf 'Preview: http://127.0.0.1:%s\n' "$PREVIEW_PORT"
    else
        printf 'Frontend: http://127.0.0.1:%s\n' "$FRONTEND_PORT"
    fi
    printf 'Hermes:  127.0.0.1:%s\n' "$GATEWAY_PORT"
    printf 'Logs: %s, %s, %s, %s\n' "$API_LOG" "$FRONTEND_LOG" "$GATEWAY_LOG" "$PREVIEW_LOG"
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
    # Substitute the project-root placeholder so the launcher survives moves.
    sed "s|@PROJECT_ROOT@|$PROJECT_ROOT|g" "$DESKTOP_SOURCE" \
        > "$APPLICATIONS_DIR/Demiurgos.desktop"
    chmod 0644 "$APPLICATIONS_DIR/Demiurgos.desktop"
    if [ -d "$DESKTOP_DIR" ]; then
        sed "s|@PROJECT_ROOT@|$PROJECT_ROOT|g" "$DESKTOP_SOURCE" \
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
        start) start_all; if frontend_enabled || preview_enabled; then open_frontend; fi; show_status ;;
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
