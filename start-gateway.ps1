# ---------------------------------------------------------------------------
# Demiurgos standalone Hermes gateway launcher (Windows PowerShell 5.1).
#
# Starts the Hermes gateway in the foreground. Hermes is resolved portably
# (Get-Command, then the per-user $env:USERPROFILE\.local\bin\hermes.exe
# fallback); no machine-specific absolute path is hardcoded. The data root
# resolves env -> pointer -> bootstrap-once and is exported alongside the
# legacy DEMIURGOS_ROOT, mirroring the POSIX launcher contract (S2-3).
#
# ASCII-only on purpose: Windows PowerShell 5.1 mis-decodes BOM-less UTF-8.
#
# Run:  powershell.exe -NoProfile -File start-gateway.ps1
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

# --- Portable Hermes resolution (S2-2) --------------------------------------
$hermesBin = $null
$hermesCmd = Get-Command hermes -ErrorAction SilentlyContinue
if ($hermesCmd) { $hermesBin = $hermesCmd.Source }
if (-not $hermesBin) {
    $fallback = Join-Path $env:USERPROFILE ".local\bin\hermes.exe"
    if (Test-Path -LiteralPath $fallback -PathType Leaf) { $hermesBin = $fallback }
}
if (-not $hermesBin) {
    Write-Error "Hermes CLI not found. Install Hermes or add it to PATH, then retry."
    exit 1
}

$gatewayPort = if ($env:DEMIURGOS_GATEWAY_PORT) { [int]$env:DEMIURGOS_GATEWAY_PORT } else { 8642 }

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

$dataRoot = Resolve-DataRoot
$env:DEMIURGOS_ROOT = $appRoot
$env:DEMIURGOS_DATA_ROOT = $dataRoot
$env:HERMES_ENABLE_PROJECT_PLUGINS = "1"
$env:HERMES_GATEWAY_HOST = "127.0.0.1"
$env:HERMES_GATEWAY_PORT = "$gatewayPort"

Write-Host "Demiurgos Hermes gateway: 127.0.0.1:$gatewayPort  (data root: $dataRoot)"
Set-Location $appRoot
& $hermesBin gateway run