#!/usr/bin/env bash
# Demiurgos — One-time sync to Google Drive
# Usage: ./sync-now.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "╔══════════════════════════════════════════╗"
echo "║  Demiurgos — Sync → Google Drive        ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Check rclone
if ! command -v rclone &>/dev/null; then
    echo "rclone no está instalado. Ejecutá ./scripts/install-sync.sh primero."
    exit 1
fi

# Check remote
if ! rclone listremotes 2>/dev/null | grep -q "Demiurgos:"; then
    echo "Remote 'Demiurgos:' no configurado. Ejecutá ./scripts/install-sync.sh primero."
    exit 1
fi

# Sync
echo "Sincronizando $PROJECT_ROOT → Demiurgos:..."
rclone sync "$PROJECT_ROOT" "Demiurgos:" \
    --filter-from "$PROJECT_ROOT/rclone-filters.txt" \
    --progress \
    --verbose

echo ""
echo "✓ Sync completado."
