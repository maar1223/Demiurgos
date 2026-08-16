#!/usr/bin/env bash
# Demiurgos Linux launcher. Manages only processes started by this script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
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
API_LOG="/tmp/demiurgos-api.log"
FRONTEND_LOG="/tmp/demiurgos-frontend.log"
GATEWAY_LOG="/tmp/demiurgos-gateway.log"

mkdir -p "$STATE_DIR"

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
        frontend) [[ "$cmdline" == *"vite"* && "$cmdline" == *"--host 127.0.0.1"* ]] ;;
        gateway) [[ "$cmdline" == *"hermes gateway run"* ]] ;;
        *) return 1 ;;
    esac
}

remove_pid_file() {
    rm -f "$(pid_file "$1")"
}

stop_component() {
    local name="$1" pid file
    file="$(pid_file "$name")"
    if owned_pid "$name"; then
        read -r pid < "$file"
        kill -TERM "$pid" 2>/dev/null || true
        for _ in {1..30}; do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.2
        done
        if kill -0 "$pid" 2>/dev/null; then
            kill -KILL "$pid" 2>/dev/null || true
        fi
        printf 'Stopped %s (pid %s)\n' "$name" "$pid"
    elif [ -e "$file" ]; then
        printf 'Skipped %s: recorded PID is not a Demiurgos process\n' "$name"
    fi
    remove_pid_file "$name"
}

stop_all() {
    stop_component frontend
    stop_component api
    stop_component gateway
}

port_is_loopback() {
    local port="$1"
    command -v ss >/dev/null 2>&1 || return 1
    ss -Hln 2>/dev/null | grep -Eq "[[:space:]](127\\.0\\.0\\.1|\\[::1\\]):${port}[[:space:]]"
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

adopt_existing_component() {
    local name="$1" port="$2" pid="" cmdline=""
    pid="$(port_owner_pid "$port")"
    [ -n "$pid" ] || return 1
    [ -r "/proc/$pid/cmdline" ] || return 1
    cmdline="$(tr '\0' ' ' < "/proc/$pid/cmdline")"
    case "$name" in
        api) [[ "$cmdline" == *"$API_DIR"* && "$cmdline" == *"uvicorn"* ]] || return 1 ;;
        frontend) [[ "$cmdline" == *"$FRONTEND_DIR"* && "$cmdline" == *"vite"* ]] || return 1 ;;
        gateway) [[ "$cmdline" == *"hermes gateway run"* ]] || return 1 ;;
        *) return 1 ;;
    esac
    printf '%s\n' "$pid" > "$(pid_file "$name")"
    printf 'Adopted existing %s (pid %s)\n' "$name" "$pid"
}

wait_for_port() {
    local port="$1" seconds=0
    while [ "$seconds" -lt 20 ]; do
        if port_is_loopback "$port"; then return 0; fi
        if port_is_listening "$port"; then return 2; fi
        sleep 1
        seconds=$((seconds + 1))
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
        gateway)
            (cd "$PROJECT_ROOT" && exec nohup env \
                HERMES_GATEWAY_HOST=127.0.0.1 HERMES_GATEWAY_PORT="$GATEWAY_PORT" \
                "$HERMES_BIN" gateway run >>"$GATEWAY_LOG" 2>&1) & ;;
        *) return 1 ;;
    esac
    pid=$!
    printf '%s\n' "$pid" > "$(pid_file "$name")"
}

start_all() {
    load_project_auth_mode
    if [ -z "$HERMES_BIN" ] || [ ! -x "$HERMES_BIN" ]; then
        printf 'Hermes CLI not found\n' >&2
        return 1
    fi
    start_component gateway
    start_component api
    start_component frontend
    for port in "$GATEWAY_PORT" "$API_PORT" "$FRONTEND_PORT"; do
        case "$port" in
            "$GATEWAY_PORT") name="Hermes Gateway" ;;
            "$API_PORT") name="API" ;;
            *) name="Frontend" ;;
        esac
        if wait_for_port "$port"; then
            printf '%s ready on 127.0.0.1:%s\n' "$name" "$port"
        elif [ "$?" -eq 2 ]; then
            printf '%s refused: port %s is already used outside Demiurgos\n' "$name" "$port" >&2
            return 1
        else
            printf '%s did not become ready; check its log\n' "$name" >&2
            return 1
        fi
    done
}

open_frontend() {
    if ! command -v xdg-open >/dev/null 2>&1; then
        printf 'Default browser opener not found; open http://127.0.0.1:%s manually\n' "$FRONTEND_PORT" >&2
        return 0
    fi
    nohup xdg-open "http://127.0.0.1:${FRONTEND_PORT}" >/dev/null 2>&1 &
}

show_status() {
    printf '\nDemiurgos is running\n'
    printf 'API:     http://127.0.0.1:%s\n' "$API_PORT"
    printf 'Frontend: http://127.0.0.1:%s\n' "$FRONTEND_PORT"
    printf 'Hermes:  127.0.0.1:%s\n' "$GATEWAY_PORT"
    printf 'Logs: %s, %s, %s\n' "$API_LOG" "$FRONTEND_LOG" "$GATEWAY_LOG"
    printf '\nPress Enter to close this window. Services continue running.\n'
    read -r || true
}

install_desktop() {
    [ -f "$DESKTOP_SOURCE" ] || { printf 'Desktop file missing: %s\n' "$DESKTOP_SOURCE" >&2; return 1; }
    mkdir -p "$APPLICATIONS_DIR"
    install -m 0644 "$DESKTOP_SOURCE" "$APPLICATIONS_DIR/Demiurgos.desktop"
    if [ -d "$DESKTOP_DIR" ]; then
        install -m 0755 "$DESKTOP_SOURCE" "$DESKTOP_DIR/Demiurgos.desktop"
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
        start) start_all; open_frontend; show_status ;;
        restart) stop_all; start_all; open_frontend; show_status ;;
        stop) stop_all ;;
        install) install_desktop ;;
        *) usage >&2; return 2 ;;
    esac
}

main "$@"
