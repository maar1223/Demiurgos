# sync-now.ps1 — Sincronización inmediata Demiurgos → Google Drive
# Uso: .\scripts\sync-now.ps1
# O desde cualquier directorio: powershell -File scripts\sync-now.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Write-Output "=== Demiurgos → Google Drive ==="
Write-Output "Origen : $ProjectRoot"
Write-Output "Destino: Demiurgos:"
Write-Output ""

# Verificar que rclone existe
if (-not (Get-Command rclone -ErrorAction SilentlyContinue)) {
    Write-Error "rclone no está instalado. Ejecutá install-sync.ps1 primero."
    exit 1
}

# Verificar que el remote existe
$remotes = rclone listremotes 2>$null
if ($remotes -notmatch "Demiurgos:") {
    Write-Error "Remote 'Demiurgos:' no configurado. Ejecutá install-sync.ps1 primero."
    exit 1
}

# Sincronizar
Write-Output "Iniciando sincronización..."
$filterFile = Join-Path $ProjectRoot "rclone-filters.txt"

rclone sync $ProjectRoot "Demiurgos:" `
    --filter-from $filterFile `
    --progress `
    --stats 10s `
    --verbose

if ($LASTEXITCODE -eq 0) {
    Write-Output ""
    Write-Output "✅ Sincronización completada."
} else {
    Write-Error "❌ La sincronización falló con código $LASTEXITCODE"
    exit $LASTEXITCODE
}
