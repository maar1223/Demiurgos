#!/usr/bin/env bash
# Demiurgos — Start file watcher for automatic sync to Google Drive
# Usage: ./start-sync.sh [interval_seconds]
#   Default interval: 300 (5 minutes)
set -euo pipefail

INTERVAL="${1:-300}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "╔══════════════════════════════════════════╗"
echo "║  Demiurgos — Auto-Sync Watcher          ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  Observando cambios en: $PROJECT_ROOT"
echo "  Intervalo: ${INTERVAL}s"
echo "  Destino: Google Drive (Demiurgos:)"
echo ""
echo "  Presioná Ctrl+C para detener."
echo ""

# Track last sync time
LAST_SYNC=0

while true; do
    sleep 10  # Check every 10 seconds
    
    # Find files modified since last sync
    RECENT=$(find "$PROJECT_ROOT" \
        -not -path "*/.git/*" \
        -not -path "*/.tmp*" \
        -not -path "*/__pycache__/*" \
        -not -path "*/.pytest_cache/*" \
        -not -name ".env" \
        -newermt "@$LAST_SYNC" \
        -type f 2>/dev/null | wc -l | tr -d ' ')
    
    NOW=$(date +%s)
    ELAPSED=$((NOW - LAST_SYNC))
    
    if [[ $RECENT -gt 0 && $ELAPSED -ge $INTERVAL ]]; then
        echo "[$(date '+%H:%M:%S')] $RECENT archivo(s) modificado(s). Sincronizando..."
        rclone sync "$PROJECT_ROOT" "Demiurgos:" \
            --filter-from "$PROJECT_ROOT/rclone-filters.txt" \
            --quiet 2>&1 && echo "  ✓ Sync completado." || echo "  ✗ Error en sync."
        LAST_SYNC=$NOW
    fi
done
