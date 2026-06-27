#!/usr/bin/env bash
# Demiurgos — Setup Google Drive sync via rclone
# Usage: ./install-sync.sh
# Requires: rclone installed
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "╔══════════════════════════════════════════╗"
echo "║  Demiurgos — Configuración de Sync      ║"
echo "║  Google Drive                           ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── Step 1: Check rclone ──────────────────────────────
echo "[1/3] Verificando rclone..."
if ! command -v rclone &>/dev/null; then
    echo "  ERROR: rclone no está instalado."
    echo "  Instalalo con: brew install rclone       (macOS)"
    echo "               curl https://rclone.org/install.sh | sudo bash  (Linux)"
    exit 1
fi
echo "  OK $(rclone version --check 2>&1 | head -1)"
echo ""

# ── Step 2: Configure Google Drive remote ─────────────
echo "[2/3] Configurando Google Drive..."
if rclone listremotes 2>/dev/null | grep -q "Demiurgos:"; then
    echo "  OK Remote 'Demiurgos:' ya configurado."
    echo "  Para reconectar: rclone config reconnect Demiurgos:"
else
    echo "  Creando remote 'Demiurgos:'..."
    echo "  Se va a abrir el navegador para autorizar."
    echo "  Iniciá sesión con tu cuenta de Google."
    echo ""
    rclone config create Demiurgos drive scope=drive.file
    echo "  OK Remote creado."
fi
echo ""

# ── Step 3: Verify filters ────────────────────────────
echo "[3/3] Verificando filtros..."
if [[ -f "$PROJECT_ROOT/rclone-filters.txt" ]]; then
    echo "  OK rclone-filters.txt encontrado."
else
    echo "  ERROR: rclone-filters.txt no existe en $PROJECT_ROOT"
    exit 1
fi
echo ""

# ── Done ──────────────────────────────────────────────
echo "╔══════════════════════════════════════════╗"
echo "║  ✓  Configuración completa              ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Para sincronizar ahora:   ./scripts/sync-now.sh"
echo "Para sincro automática:   ./scripts/start-sync.sh"
