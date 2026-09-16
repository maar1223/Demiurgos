# ---------------------------------------------------------------------------
# Demiurgos - single entry point to bring the whole stack up.
#
#  1. Hermes Gateway        (port 8642)  - persistent AI daemon
#  2. Demiurgos Wiki API    (port 8000)  - api_server.py (uvicorn)
#  3. Graph warm-up (background)         - pays the ~2min cold start
#  4. Frontend dev server   (port 5173)  - Vite
#
# Idempotent: any service already listening on its port is left untouched,
# so running this script twice never spawns duplicate processes.
#
# Run:  powershell -ExecutionPolicy Bypass -File start-demiurgos.ps1
# Apply current .env auth mode to an existing API only with explicit confirmation:
# Run:  powershell -ExecutionPolicy Bypass -File start-demiurgos.ps1 -RestartApi
# ---------------------------------------------------------------------------

param(
    [switch]$RestartApi
)

$ErrorActionPreference = "Continue"

$root    = "<local-path>\Proyectos\Demiurgos"
$hermes  = "C:\Users\Miguel Angel\AppData\Local\hermes\hermes-agent\venv\Scripts\hermes.exe"
$gatewayPort = 8642
$apiPort     = 8000
$frontendPort = 5173
$apiUrl    = "http://localhost:$apiPort/health"
$frontendUrl = "http://localhost:$frontendPort"
$hermesHealthUrl = "http://localhost:$gatewayPort/health"

. (Join-Path $root "scripts\import-auth-mode.ps1")
$authMode = Set-DemiurgosAuthModeFromDotEnv -ProjectRoot $root

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Demiurgos - stack launcher" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Auth mode configurado para la API: $authMode" -ForegroundColor DarkCyan

# --- Helper: is a TCP port already listening? ---------------------------------
function Test-PortListening([int]$port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Test-HermesHealthy {
    try {
        $response = Invoke-WebRequest -Uri $hermesHealthUrl -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch { return $false }
}

# --- Helper: start a detached PowerShell window that stays open for logs -------
function Start-ServiceWindow([string]$title, [string]$command) {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $command |
        Out-Null
    Write-Host "  [OK]  $title lanzado en ventana propia." -ForegroundColor Green
}

function Get-ApiListenerPids {
    @(
        Get-NetTCPConnection -LocalPort $apiPort -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { $_.OwningProcess } |
            Sort-Object -Unique
    )
}

function Stop-ApiForExplicitRestart {
    $ownerPids = @(Get-ApiListenerPids)
    if ($ownerPids.Count -eq 0) {
        return $true
    }
    if ($ownerPids.Count -ne 1) {
        Write-Host "  [!!]  No se reinicia: hay varios procesos escuchando en $apiPort." -ForegroundColor Red
        return $false
    }

    $ownerPid = [int]$ownerPids[0]
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerPid" -ErrorAction SilentlyContinue
    $commandLine = if ($processInfo) { [string]$processInfo.CommandLine } else { "" }
    if ([string]::IsNullOrWhiteSpace($commandLine) -or
        $commandLine -notmatch '(?i)(api_server:app|api_server\.py|start-api\.ps1)') {
        Write-Host "  [!!]  No se reinicia: el proceso de $apiPort no se identifico como la API de Demiurgos." -ForegroundColor Red
        return $false
    }

    Write-Host "  [!!]  Reinicio solicitado: se detendra el proceso API identificado (PID $ownerPid)." -ForegroundColor Yellow
    $confirmation = Read-Host "Escribe RESTART para confirmar; cualquier otra cosa cancela"
    if ($confirmation -cne "RESTART") {
        Write-Host "  [OK]  Reinicio cancelado; el proceso existente queda intacto." -ForegroundColor Green
        return $false
    }

    Stop-Process -Id $ownerPid -ErrorAction Stop
    for ($i = 0; $i -lt 20 -and (Test-PortListening $apiPort); $i++) {
        Start-Sleep -Milliseconds 250
    }
    if (Test-PortListening $apiPort) {
        Write-Host "  [!!]  La API no libero el puerto $apiPort; no se inicia otra instancia." -ForegroundColor Red
        return $false
    }
    return $true
}

# --- 1. Hermes Gateway ----------------------------------------------------------
Write-Host "[1/4] Hermes Gateway ($gatewayPort)..." -ForegroundColor Yellow
if (Test-PortListening $gatewayPort) {
    if (Test-HermesHealthy) {
        Write-Host "  [OK]  Hermes saludable en el puerto $gatewayPort - sin cambios." -ForegroundColor Green
    } else {
        Write-Host "  [!!]  Hermes escucha pero no esta saludable; no se inicia una segunda instancia." -ForegroundColor Red
    }
} else {
    Start-ServiceWindow "Gateway" "Set-Location '$root'; `$env:DEMIURGOS_ROOT='$root'; `$env:DEMIURGOS_DATA_ROOT='$root'; `$env:HERMES_ENABLE_PROJECT_PLUGINS='1'; & '$hermes' plugins enable demiurgos-idea-capture *> `$null; if (`$LASTEXITCODE -ne 0) { throw 'Could not enable the Demiurgos Hermes project plugin.' }; & '$hermes' gateway run -v"
}

# --- 2. Wiki API -----------------------------------------------------------------
Write-Host "[2/4] Wiki API ($apiPort)..." -ForegroundColor Yellow
if (Test-PortListening $apiPort) {
    if ($RestartApi -and (Stop-ApiForExplicitRestart)) {
        Write-Host "  [OK]  API anterior detenida de forma explicita; se inicia con el modo $authMode." -ForegroundColor Green
        $env:PYTHONPATH = "src\tools\demiurgos-suite\wiki;src\tools\demiurgos-suite"
        Start-ServiceWindow "API" "Set-Location '$root'; `$env:PYTHONPATH='src\tools\demiurgos-suite\wiki;src\tools\demiurgos-suite'; `$env:DEMIURGOS_DATA_ROOT='$root'; python -m uvicorn api_server:app --host 127.0.0.1 --port 8000 --log-level info"
    } else {
        Write-Host "  [OK]  Ya esta escuchando en el puerto $apiPort - sin cambios; conserva su entorno anterior." -ForegroundColor Green
        Write-Host "        Usa -RestartApi y confirma RESTART para aplicar el .env actual." -ForegroundColor DarkYellow
    }
} else {
    $env:PYTHONPATH = "src\tools\demiurgos-suite\wiki;src\tools\demiurgos-suite"
    Start-ServiceWindow "API" "Set-Location '$root'; `$env:PYTHONPATH='src\tools\demiurgos-suite\wiki;src\tools\demiurgos-suite'; `$env:DEMIURGOS_DATA_ROOT='$root'; python -m uvicorn api_server:app --host 127.0.0.1 --port 8000 --log-level info"
}

# --- 3. Graph warm-up (background, does not block) --------------------------------
Write-Host "[3/4] Graph warm-up (background)..." -ForegroundColor Yellow
Start-ServiceWindow "Warmup" "Set-Location '$root'; python src\tools\demiurgos-suite\wiki\warmup_gateway.py"

# --- 4. Frontend -------------------------------------------------------------------
Write-Host "[4/4] Frontend ($frontendPort)..." -ForegroundColor Yellow
if (Test-PortListening $frontendPort) {
    Write-Host "  [OK]  Ya esta escuchando en el puerto $frontendPort - sin cambios." -ForegroundColor Green
} else {
    Start-ServiceWindow "Frontend" "Set-Location '$root\frontend'; npm run dev"
}

# --- Wait for readiness (API + frontend) -------------------------------------------
Write-Host ""
Write-Host "Esperando a que los servicios respondan..." -ForegroundColor DarkYellow

$apiReady = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-WebRequest -Uri $apiUrl -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $apiReady = $true; break }
    } catch { }
}
if ($apiReady) {
    Write-Host "  [OK]  API listo ($apiUrl)." -ForegroundColor Green
} else {
    Write-Host "  [!!]  API no respondio a tiempo. Revisa la ventana del API." -ForegroundColor Red
}

$feReady = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-WebRequest -Uri $frontendUrl -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $feReady = $true; break }
    } catch { }
}
if ($feReady) {
    Write-Host "  [OK]  Frontend listo ($frontendUrl)." -ForegroundColor Green
} else {
    Write-Host "  [!!]  Frontend no respondio a tiempo. Revisa la ventana del Frontend." -ForegroundColor Red
}

# --- Open the browser ----------------------------------------------------------------
if ($feReady) {
    Start-Process $frontendUrl
}

Write-Host ""
Write-Host "Stack listo. Frontend: $frontendUrl" -ForegroundColor Green
Write-Host "Cierra las ventanas de servicio para apagar el stack." -ForegroundColor DarkYellow
Write-Host ""
