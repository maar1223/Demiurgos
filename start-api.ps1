# ---------------------------------------------------------------------------
# Demiurgos standalone API launcher (Windows PowerShell 5.1).
#
# Starts ONLY the FastAPI process (uvicorn) in the foreground. All paths are
# derived from the script's own location and the frozen install layout
# (docs/architecture/INSTALL_LAYOUT.md - S0-C); no machine-specific absolute
# path is hardcoded. The data root resolves env -> pointer -> bootstrap-once
# and its .env (auth mode, locale) is parsed in pure PowerShell (S2-4/S0-A).
#
# ASCII-only on purpose: Windows PowerShell 5.1 mis-decodes BOM-less UTF-8.
#
# Run:  powershell.exe -NoProfile -File start-api.ps1
# ---------------------------------------------------------------------------

$ErrorActionPreference = "Stop"

# --- Paths derived from this launcher's own location (S0-C rule 1) ---------
$scriptDir = $PSScriptRoot
if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if ((Split-Path -Leaf $scriptDir) -eq "scripts") {
    $appRoot = Split-Path -Parent $scriptDir
} else {
    $appRoot = $scriptDir
}

if ($env:DEMIURGOS_HOME) {
    $installRoot = $env:DEMIURGOS_HOME
} elseif ((Split-Path -Leaf $appRoot) -eq "current") {
    $installRoot = Split-Path -Parent $appRoot
} else {
    $installRoot = $appRoot
}

$pythonBin = Join-Path $appRoot ".venv\Scripts\python.exe"
$apiDir = Join-Path $appRoot "src\tools\demiurgos-suite\wiki"
$apiPort = if ($env:DEMIURGOS_API_PORT) { [int]$env:DEMIURGOS_API_PORT } else { 8000 }

# --- Data-root pointer (S2-3): %APPDATA%\demiurgos\data-root.json ----------
$configDir = Join-Path $env:APPDATA "demiurgos"
$pointerFile = Join-Path $configDir "data-root.json"

function Get-DocumentsDir {
    # The OS documents folder (step 3), never a literal $env:USERPROFILE\Documents:
    # the shell API follows a redirection (OneDrive Known Folder Move) and the
    # user's localized folder name. Pure .NET, no extra module.
    $path = [Environment]::GetFolderPath('MyDocuments')
    if ([string]::IsNullOrWhiteSpace($path)) {
        $path = Join-Path $env:USERPROFILE 'Documents'
    }
    return $path
}

function Resolve-DataRoot {
    if ($env:DEMIURGOS_DATA_ROOT) {
        return $env:DEMIURGOS_DATA_ROOT
    }
    if (Test-Path -LiteralPath $pointerFile -PathType Leaf) {
        try {
            $record = Get-Content -LiteralPath $pointerFile -Raw | ConvertFrom-Json
            if ($record.data_root) {
                return [string]$record.data_root
            }
        } catch {
            Write-Warning "Data-root pointer $pointerFile is unreadable; refusing to guess."
        }
    }
    $root = Join-Path (Get-DocumentsDir) "Demiurgos"
    New-Item -ItemType Directory -Force -Path $root, $configDir | Out-Null
    $record = @{
        schema_version = 1
        data_root = $root
        updated_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    } | ConvertTo-Json
    Set-Content -LiteralPath $pointerFile -Value $record -Encoding ASCII
    Write-Host "Bootstrapped data root at $root"
    return $root
}

function Load-DataRootEnv {
    $envFile = Join-Path $dataRoot ".env"
    if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) { return }
    Get-Content -LiteralPath $envFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $eq = $line.IndexOf("=")
        if ($eq -le 0) { return }
        $key = $line.Substring(0, $eq).Trim()
        $value = $line.Substring($eq + 1).Trim()
        if ($value.Length -ge 2 -and $value.StartsWith('"') -and $value.EndsWith('"')) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $value = $value.TrimEnd("`r")
        if ($key -like "DEMIURGOS_*") {
            Set-Item -Path ("Env:" + $key) -Value $value
        }
    }
}

$dataRoot = Resolve-DataRoot
Load-DataRootEnv
$env:DEMIURGOS_DATA_ROOT = $dataRoot
$env:DEMIURGOS_FRONTEND_DIST = Join-Path $appRoot "frontend\dist"
$env:DEMIURGOS_ROOT = $appRoot

Write-Host "Demiurgos API: 127.0.0.1:$apiPort  (data root: $dataRoot)"
Set-Location $apiDir
& $pythonBin -m uvicorn api_server:app --host 127.0.0.1 --port $apiPort --log-level info