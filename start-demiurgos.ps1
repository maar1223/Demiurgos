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
# ---------------------------------------------------------------------------

$ErrorActionPreference = "Continue"

$root    = "<local-path>\Proyectos\Demiurgos"
$hermes  = "C:\Users\Miguel Angel\AppData\Local\hermes\hermes-agent\venv\Scripts\hermes.exe"
$gatewayPort = 8642
$apiPort     = 8000
$frontendPort = 5173
$apiUrl    = "http://localhost:$apiPort/health"
$frontendUrl = "http://localhost:$frontendPort"

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Demiurgos - stack launcher" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# --- Helper: is a TCP port already listening? ---------------------------------
function Test-PortListening([int]$port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

# --- Helper: start a detached PowerShell window that stays open for logs -------
function Start-ServiceWindow([string]$title, [string]$command) {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $command |
        Out-Null
    Write-Host "  [OK]  $title lanzado en ventana propia." -ForegroundColor Green
}

# --- 1. Hermes Gateway ----------------------------------------------------------
Write-Host "[1/4] Hermes Gateway ($gatewayPort)..." -ForegroundColor Yellow
if (Test-PortListening $gatewayPort) {
    Write-Host "  [OK]  Ya esta escuchando en el puerto $gatewayPort - sin cambios." -ForegroundColor Green
} else {
    Start-ServiceWindow "Gateway" "& '$hermes' gateway run -v"
}

# --- 2. Wiki API -----------------------------------------------------------------
Write-Host "[2/4] Wiki API ($apiPort)..." -ForegroundColor Yellow
if (Test-PortListening $apiPort) {
    Write-Host "  [OK]  Ya esta escuchando en el puerto $apiPort - sin cambios." -ForegroundColor Green
} else {
    $env:PYTHONPATH = "src\tools\demiurgos-suite\wiki;src\tools\demiurgos-suite"
    Start-ServiceWindow "API" "Set-Location '$root'; `$env:PYTHONPATH='src\tools\demiurgos-suite\wiki;src\tools\demiurgos-suite'; python -m uvicorn api_server:app --host 127.0.0.1 --port 8000 --log-level info"
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