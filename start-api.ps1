# The API reads DEMIURGOS_AUTH_MODE from its process environment. Load only
# that allowlisted, non-secret setting before starting Python.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $root "scripts\import-auth-mode.ps1")
$authMode = Set-DemiurgosAuthModeFromDotEnv -ProjectRoot $root

$env:PYTHONPATH = "src\tools\demiurgos-suite\wiki;src\tools\demiurgos-suite"
# Author data root for the resolver (WU-3 / SC-DR-3.4). Set alongside the
# PYTHONPATH so this standalone launcher also resolves author data.
$env:DEMIURGOS_DATA_ROOT = $root
Set-Location $root
Write-Host "Demiurgos API auth mode: $authMode"

# If port 8000 already has an API listener, stop that process explicitly before
# rerunning this script so it can receive the current configuration.
python -c "import uvicorn; from api_server import app; uvicorn.run(app, host='127.0.0.1', port=8000, log_level='info')"
