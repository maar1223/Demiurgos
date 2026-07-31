# start-sync.ps1 — Watcher automático de cambios → sync a Google Drive
# Uso: .\scripts\start-sync.ps1
# Corre en background. Para detener: Ctrl+C
# Configurable: $DebounceSeconds (espera N segundos tras último cambio antes de sync)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DebounceSeconds = 60  # Esperar 60s de inactividad antes de sincronizar

# Carpetas a observar
$WatchPaths = @(
    (Join-Path $ProjectRoot "mundos"),
    (Join-Path $ProjectRoot "Ideas"),
    (Join-Path $ProjectRoot "plantillas"),
    (Join-Path $ProjectRoot "_archivo_produccion")
)

Write-Output "╔══════════════════════════════════════════╗"
Write-Output "║  Demiurgos — Watcher de Sync           ║"
Write-Output "║  Observando cambios cada ${DebounceSeconds}s    ║"
Write-Output "╚══════════════════════════════════════════╝"
Write-Output ""
Write-Output "Observando:"
foreach ($path in $WatchPaths) {
    if (Test-Path $path) {
        Write-Output "  👁️  $path"
    } else {
        Write-Output "  ⚠️  $path (no existe)"
    }
}
Write-Output ""
Write-Output "Presioná Ctrl+C para detener."
Write-Output ""

# Timer para debounce
$timer = New-Object System.Timers.Timer
$timer.Interval = $DebounceSeconds * 1000
$timer.AutoReset = $false

$syncScript = Join-Path $ProjectRoot "scripts\sync-now.ps1"
$syncInProgress = $false

# Acción del timer: ejecutar sync
$syncAction = {
    if ($global:syncInProgress) { return }
    $global:syncInProgress = $true
    try {
        Write-Output ""
        Write-Output "[$(Get-Date -Format 'HH:mm:ss')] Cambios detectados — sincronizando..."
        & $using:syncScript
    } finally {
        $global:syncInProgress = $false
    }
}

$timer.Add_Elapsed($syncAction)

# FileSystemWatchers para cada carpeta
$watchers = @()
foreach ($watchPath in $WatchPaths) {
    if (-not (Test-Path $watchPath)) { continue }
    
    $watcher = New-Object System.IO.FileSystemWatcher
    $watcher.Path = $watchPath
    $watcher.IncludeSubdirectories = $true
    $watcher.EnableRaisingEvents = $true
    
    # Reiniciar timer en cada cambio (debounce)
    $onChange = {
        $timer.Stop()
        $timer.Start()
    }
    
    Register-ObjectEvent $watcher "Changed" -Action $onChange | Out-Null
    Register-ObjectEvent $watcher "Created" -Action $onChange | Out-Null
    Register-ObjectEvent $watcher "Deleted" -Action $onChange | Out-Null
    Register-ObjectEvent $watcher "Renamed" -Action $onChange | Out-Null
    
    $watchers += $watcher
}

Write-Output "Watcher activo. $(Get-Date -Format 'HH:mm:ss')"

# Mantener el script corriendo
try {
    while ($true) {
        Start-Sleep -Seconds 10
    }
} finally {
    foreach ($watcher in $watchers) {
        $watcher.Dispose()
    }
    $timer.Dispose()
    Write-Output "Watcher detenido."
}
