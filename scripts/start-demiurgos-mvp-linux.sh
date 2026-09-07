#!/usr/bin/env bash
# Demiurgos MVP launcher — serves the production build (Relaciones y Canon
# hidden by the DEV gate) on port 4173, reusing the existing launcher for the
# backend (API + gateway) without starting the dev frontend.
#
# Usage: ./start-demiurgos-mvp-linux.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
PREVIEW_PORT=4173
LOG="/tmp/demiurgos-mvp.log"

# Start the backend (API + gateway) only. The dev frontend is skipped so the
# production build can be served on the preview port instead.
DEMIURGOS_SKIP_FRONTEND=1 "$SCRIPT_DIR/start-demiurgos-linux.sh" start

# Build the production bundle. Relaciones y Canon is hidden because the DEV
# gate (`import.meta.env.DEV`) is false in a production build.
echo "Building Demiurgos MVP…" >&2
(cd "$FRONTEND_DIR" && npm run build)

# Serve the production build on the preview port.
echo "Serving MVP on http://127.0.0.1:${PREVIEW_PORT}" >&2
(cd "$FRONTEND_DIR" && nohup npm run preview -- \
    --host 127.0.0.1 --port "$PREVIEW_PORT" >>"$LOG" 2>&1 &)

# Wait for the preview server to be listening.
for _ in {1..20}; do
    if ss -Hln 2>/dev/null | grep -Eq ":${PREVIEW_PORT}[[:space:]]"; then
        break
    fi
    sleep 0.5
done

# Open the browser.
if command -v xdg-open >/dev/null 2>&1; then
    nohup xdg-open "http://127.0.0.1:${PREVIEW_PORT}" >/dev/null 2>&1 &
else
    echo "Open http://127.0.0.1:${PREVIEW_PORT} manually" >&2
fi

echo "Demiurgos MVP running on http://127.0.0.1:${PREVIEW_PORT}" >&2
