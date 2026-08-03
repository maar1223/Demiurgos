# ---------------------------------------------------------------------------
# Demiurgos startup script — one entry point to bring the whole stack up.
#
#  1. Hermes Gateway (port 8642)   — persistent AI daemon
#  2. Graph MCP warm-up (background) — pays the one-time ~2min cold start
#     so the user's first real message is fast
#  3. Demiurgos Wiki API (port 8000)
#  4. Frontend dev server (port 5173)
#
# Run: powershell -File start-demiurgos.ps1
# ---------------------------------------------------------------------------

$ErrorActionPreference = "Continue"

$root = "<local-path>\Proyectos\Demiurgos"
$hermesBin = "C:\Users\Miguel Angel\AppData\Local\hermes\hermes-agent\venv\Scripts\hermes.exe"

Write-Host "== Demiurgos stack ==" -ForegroundColor Cyan

# 1. Gateway
Write-Host "[1/4] Hermes Gateway (8642)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-File", "$root\start-gateway.ps1"
Start-Sleep -Seconds 3

# 2. Warm-up in background (does not block UI readiness)
Write-Host "[2/4] Graph warm-up (background)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root'; python src\tools\demiurgos-suite\wiki\warmup_gateway.py"

# 3. API server
Write-Host "[3/4] Wiki API (8000)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-File", "$root\start-api.ps1"

# 4. Frontend
Write-Host "[4/4] Frontend (5173)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\frontend'; npm run dev"

Write-Host ""
Write-Host "Stack launching. Frontend: http://localhost:5173" -ForegroundColor Green
Write-Host "First AI message may wait for the warm-up (~2 min after gateway boot)." -ForegroundColor DarkYellow
