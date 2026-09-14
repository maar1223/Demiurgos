#!/usr/bin/env bash
# Demiurgos MVP launcher — serves the production build on port 4173.
#
# Thin alias over the main launcher: DEMIURGOS_SKIP_FRONTEND=1 puts
# start-demiurgos-linux.sh in MVP mode, where it manages the preview component
# (build + `vite preview`) instead of the dev frontend. Because the mode flows
# through the environment, an in-app "Reiniciar Demiurgos"
# (/api/system/restart -> start-demiurgos-linux.sh restart, inherited env)
# rebuilds and restarts the preview too — no more stale bundle after a restart.
#
# Usage: ./start-demiurgos-mvp-linux.sh [start|restart|stop]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

DEMIURGOS_SKIP_FRONTEND=1 exec "$SCRIPT_DIR/start-demiurgos-linux.sh" "${1:-start}"
