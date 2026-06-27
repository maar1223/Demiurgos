# install-sync.ps1 — Configuración inicial del sync Demiurgos → Google Drive
# Uso: .\scripts\install-sync.ps1
# Requiere: rclone instalado (scoop install rclone)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Write-Output "╔══════════════════════════════════════════╗"
Write-Output "║  Demiurgos — Configuración de Sync      ║"
Write-Output "║  Google Drive                           ║"
Write-Output "╚══════════════════════════════════════════╝"
Write-Output ""

# === Paso 1: Verificar rclone ===
Write-Output "[1/3] Verificando rclone..."
if (-not (Get-Command rclone -ErrorAction SilentlyContinue)) {
    Write-Error "rclone no está instalado."
    Write-Output "Instalalo con: scoop install rclone"
    Write-Output "O desde: https://rclone.org/downloads/"
    exit 1
}
$rcloneVersion = rclone version --check 2>&1 | Select-Object -First 1
Write-Output "  ✅ $rcloneVersion"
Write-Output ""

# === Paso 2: Configurar remote de Google Drive ===
Write-Output "[2/3] Configurando Google Drive..."
$remotes = rclone listremotes 2>$null
if ($remotes -match "Demiurgos:") {
    Write-Output "  ✅ Remote 'Demiurgos:' ya configurado."
    Write-Output "  Para reconectar: rclone config reconnect Demiurgos:"
} else {
    Write-Output "  Creando remote 'Demiurgos:'..."
    Write-Output "  Se va a abrir el navegador para autorizar."
    Write-Output "  Iniciá sesión con tu cuenta de Google."
    Write-Output ""
    rclone config create Demiurgos drive scope=drive.file
    Write-Output "  ✅ Remote creado."
}
Write-Output ""

# === Paso 3: Verificar filtros ===
Write-Output "[3/3] Verificando filtros..."
$filterFile = Join-Path $ProjectRoot "rclone-filters.txt"
if (Test-Path $filterFile) {
    Write-Output "  ✅ rclone-filters.txt encontrado."
} else {
    Write-Error "  ❌ rclone-filters.txt no existe en la raíz del proyecto."
    exit 1
}
Write-Output ""

# === Verificación final ===
Write-Output "╔══════════════════════════════════════════╗"
Write-Output "║  ✅ Configuración completa              ║"
Write-Output "╚══════════════════════════════════════════╝"
Write-Output ""
Write-Output "Para sincronizar ahora: .\scripts\sync-now.ps1"
Write-Output "Para sincronización automática: .\scripts\start-sync.ps1"
Write-Output ""
