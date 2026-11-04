# ---------------------------------------------------------------------------
# Demiurgos Windows stack launcher (Windows PowerShell 5.1).
#
# Portable start/restart/stop for the web platform on Windows, derived
# entirely from the script's own location and the frozen install layout
# (docs/architecture/INSTALL_LAYOUT.md - S0-C). The dev checkout and the
# installed layout (<install_root>\current) share the same relative
# structure, so one launcher serves both.
#
# The launcher manages ONLY the FastAPI process (uvicorn), which serves the
# SPA and /api on one port. Hermes is OPTIONAL (S2-2): the gateway is never
# started here and the app boots without the provider. Use start-gateway.ps1
# to bring the assistant up later.
#
# Bounded boot rollback (S6-2/D6): readiness requires a real HTTP 200 on
# GET /health (Wait-ApiReady). When the new version fails to boot, the
# launcher falls back ONCE to the previous bootable app\<version> (local scan
# only; no update or download - G9 untouched) and restarts it.
#
# ASCII-only on purpose: Windows PowerShell 5.1 mis-decodes BOM-less UTF-8.
#
# Run:  powershell.exe -NoProfile -File start-demiurgos.ps1
#       powershell.exe -NoProfile -File start-demiurgos.ps1 restart
#       powershell.exe -NoProfile -File start-demiurgos.ps1 stop
#       powershell.exe -NoProfile -File start-demiurgos.ps1 install [-Desktop]
# ---------------------------------------------------------------------------

param(
    [ValidateSet("start", "restart", "stop", "install")]
    [string]$Action = "start",
    # `install` only: also drop the visible Desktop icon. The Start Menu entry
    # is written either way (scripts/lib/desktop-shortcut.ps1 owns the rule).
    [switch]$Desktop
)

$ErrorActionPreference = "Stop"

# --- Paths derived from this launcher's own location (S0-C rule 1) ---------
# Dev checkout: the script sits at <root>\start-demiurgos.ps1, so APP_ROOT is
# its own directory. Installed layout: <current>\scripts\start-demiurgos.ps1,
# so APP_ROOT is the parent of the scripts directory.
$scriptDir = $PSScriptRoot
if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if ((Split-Path -Leaf $scriptDir) -eq "scripts") {
    $appRoot = Split-Path -Parent $scriptDir
} else {
    $appRoot = $scriptDir
}

# Install root: $env:DEMIURGOS_HOME override -> the parent of `current` in the
# installed layout -> the checkout root in dev.
if ($env:DEMIURGOS_HOME) {
    $installRoot = $env:DEMIURGOS_HOME
} elseif ((Split-Path -Leaf $appRoot) -eq "current") {
    $installRoot = Split-Path -Parent $appRoot
} else {
    $installRoot = $appRoot
}

# --- install action (desktop integration) ----------------------------------
# Handled here, before any runtime work, on purpose: registering the menu
# entry must not load the data-root .env, bootstrap a pointer, warn about a
# missing Hermes CLI or touch a port. Mirrors the POSIX launcher's `install`.
if ($Action -eq "install") {
    try {
        . (Join-Path $appRoot "scripts\lib\desktop-shortcut.ps1")
        $entries = Install-DemiurgosShortcuts -AppRoot $appRoot -Desktop:$Desktop
        foreach ($entry in $entries) { Write-Host "Installed: $entry" }
    } catch {
        Write-Host $_.Exception.Message -ForegroundColor Red
        exit 1
    }
    exit 0
}

# Layout contract: venv <current>\.venv\Scripts\python.exe, API dir, logs
# under <install_root>\logs, runtime state under %LOCALAPPDATA%\Demiurgos\run.
$pythonBin = Join-Path $appRoot ".venv\Scripts\python.exe"
$apiDir = Join-Path $appRoot "src\tools\demiurgos-suite\wiki"
$logDir = Join-Path $installRoot "logs"
$runDir = Join-Path $env:LOCALAPPDATA "Demiurgos\run"
$apiLog = Join-Path $logDir "demiurgos-api.log"
$apiErrLog = Join-Path $logDir "demiurgos-api.err.log"
$gatewayLog = Join-Path $logDir "demiurgos-gateway.log"
$gatewayErrLog = Join-Path $logDir "demiurgos-gateway.err.log"
$gatewayPidFile = Join-Path $runDir "gateway.pid"

# Ports, overridable via env for parallel instances and the CI matrix; the
# defaults are the product ports (mirror of the POSIX launcher).
$apiPort = if ($env:DEMIURGOS_API_PORT) { [int]$env:DEMIURGOS_API_PORT } else { 8000 }
$gatewayPort = if ($env:DEMIURGOS_GATEWAY_PORT) { [int]$env:DEMIURGOS_GATEWAY_PORT } else { 8642 }

# --- Product-owned Hermes resolution (S2-2/S5) ------------------------------
# Mirror start-gateway.ps1: the pinned checkout and the installer-published
# bin win; Get-Command / .local\bin stay as the dev fallback only. The gateway
# is optional and never a boot gate, but when it is present the launcher starts
# it in the background so the Windows one-command start matches POSIX.
if ($env:DEMIURGOS_HOME) {
    $productRoot = $env:DEMIURGOS_HOME
} elseif ((Split-Path -Leaf $appRoot) -eq "current") {
    $productRoot = Split-Path -Parent $appRoot
} else {
    $productRoot = Join-Path $env:LOCALAPPDATA "Demiurgos"
}
$productHermesHome = if ($env:DEMIURGOS_HERMES_HOME) { $env:DEMIURGOS_HERMES_HOME } else { Join-Path $productRoot "hermes" }
$productAgentRoot = Join-Path $productRoot "hermes-agent"

$hermesBin = $null
$hermesCandidates = @(
    (Join-Path $productAgentRoot ".hermes\bin\hermes.exe"),
    (Join-Path $productAgentRoot ".hermes\bin\hermes.cmd"),
    (Join-Path $productHermesHome "bin\hermes.exe"),
    (Join-Path $productHermesHome "bin\hermes.cmd")
)
foreach ($candidate in $hermesCandidates) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $hermesBin = $candidate; break }
}
if (-not $hermesBin) {
    $hermesCmd = Get-Command hermes -ErrorAction SilentlyContinue
    if ($hermesCmd) { $hermesBin = $hermesCmd.Source }
}
if (-not $hermesBin) {
    $fallback = Join-Path $env:USERPROFILE ".local\bin\hermes.exe"
    if (Test-Path -LiteralPath $fallback -PathType Leaf) { $hermesBin = $fallback }
}

# --- Data-root pointer (S2-3): %APPDATA%\demiurgos\data-root.json ----------
# Windows follows platformdirs user_config_dir("demiurgos") -> %APPDATA%.
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
    # Order contract (S2-3): existing env -> existing pointer (left intact) ->
    # bootstrap-once <install_root>\data. An existing pointer is never
    # re-oriented.
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
    # Bootstrap-once: write the byte-compatible pointer (data_root.py format)
    # so subsequent starts and the backend resolve the same root.
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

# Parse the data-root .env in pure PowerShell (S2-4/S0-A) and export every
# DEMIURGOS_* key: the bridge between the installer's seed (auth mode,
# locale) and the env-only backend (_auth_mode()). No Python involved.
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
        # Strip one layer of surrounding quotes and a trailing CR (CRLF .env).
        if ($value.Length -ge 2 -and $value.StartsWith('"') -and $value.EndsWith('"')) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $value = $value.TrimEnd("`r")
        if ($key -like "DEMIURGOS_*" -or $key -eq "HERMES_GATEWAY_KEY") {
            Set-Item -Path ("Env:" + $key) -Value $value
        }
    }
}

# --- Gateway key (fresh-install assistant setup) ---------------------------
# The data-root .env may carry HERMES_GATEWAY_KEY; when it does not, generate
# one once and persist it so the API client and the gateway API server share
# the same secret across restarts. ASCII-only and PS 5.1-compatible.
function Read-EnvValue([string]$File, [string]$Key) {
    if (-not (Test-Path -LiteralPath $File -PathType Leaf)) { return "" }
    foreach ($raw in @(Get-Content -LiteralPath $File)) {
        $line = $raw.TrimEnd("`r")
        $eq = $line.IndexOf("=")
        if ($eq -le 0) { continue }
        if ($line.Substring(0, $eq).Trim() -eq $Key) {
            return $line.Substring($eq + 1).Trim().Trim('"').Trim("'")
        }
    }
    return ""
}

function Set-EnvValue([string]$File, [string]$Key, [string]$Value) {
    $want = "$Key=$Value"
    $lines = @()
    if (Test-Path -LiteralPath $File -PathType Leaf) { $lines = @(Get-Content -LiteralPath $File) }
    $found = $false
    $changed = $false
    $out = @()
    foreach ($raw in $lines) {
        $line = $raw.TrimEnd("`r")
        $eq = $line.IndexOf("=")
        if ($eq -gt 0 -and $line.Substring(0, $eq).Trim() -eq $Key) {
            $found = $true
            if ($line -ceq $want) { $out += $line } else { $out += $want; $changed = $true }
        } else {
            $out += $line
        }
    }
    if (-not $found) { $out += $want; $changed = $true }
    if (-not $changed) { return }
    $dir = Split-Path -Parent $File
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    Set-Content -LiteralPath $File -Value $out -Encoding ASCII
}

function Initialize-GatewayKey([string]$Root) {
    if ($env:HERMES_GATEWAY_KEY) { return $env:HERMES_GATEWAY_KEY }
    $envFile = Join-Path $Root ".env"
    $key = Read-EnvValue $envFile "HERMES_GATEWAY_KEY"
    if (-not $key) {
        $key = [guid]::NewGuid().ToString("N")
        Set-EnvValue $envFile "HERMES_GATEWAY_KEY" $key
        Write-Host "Generated the Hermes gateway key in $envFile"
    }
    $env:HERMES_GATEWAY_KEY = $key
    return $key
}

# --- Process/port inspection (S2-5): Get-NetTCPConnection + cmdline ownership
function Test-PortListening([int]$port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Get-ListenerProcIds([int]$port) {
    return @(
        Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { $_.OwningProcess } | Sort-Object -Unique
    )
}

function Get-ProcessCommandLine([int]$procId) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $procId" -ErrorAction SilentlyContinue
    if ($proc) { return [string]$proc.CommandLine }
    return ""
}

# The API ownership gate: only a process whose command line identifies it as
# the Demiurgos API (uvicorn api_server:app) may be adopted or stopped. A
# foreign port squatter is never touched (spec "Port already in use").
function Test-ApiOwnership([int]$procId) {
    $cmd = Get-ProcessCommandLine $procId
    return ($cmd -like "*uvicorn api_server:app*")
}

function Start-Api {
    if (Test-PortListening $apiPort) {
        $owners = @(Get-ListenerProcIds $apiPort)
        if ($owners.Count -ge 1 -and (Test-ApiOwnership $owners[0])) {
            Write-Host "Already running api (pid $($owners[0]))"
            return
        }
        Write-Host "Cannot start api: port $apiPort is already in use by an untracked process"
        exit 1
    }
    New-Item -ItemType Directory -Force -Path $logDir, $runDir | Out-Null
    $uvicornArgs = @("-m", "uvicorn", "api_server:app", "--host", "127.0.0.1", "--port", "$apiPort", "--log-level", "info")
    $proc = Start-Process -FilePath $pythonBin -ArgumentList $uvicornArgs -WorkingDirectory $apiDir -RedirectStandardOutput $apiLog -RedirectStandardError $apiErrLog -PassThru -WindowStyle Hidden
    Set-Content -LiteralPath (Join-Path $runDir "api.pid") -Value $proc.Id -Encoding ASCII
    Write-Host "Started api (pid $($proc.Id))"
}

# Readiness covers the API only (S2-2): the gateway is optional and never
# gates the boot.
function Wait-ApiReady {
    $url = "http://127.0.0.1:$apiPort/health"
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { return $true }
        } catch { }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Stop-Api {
    $owners = @(Get-ListenerProcIds $apiPort)
    if ($owners.Count -eq 0) {
        Write-Host "Api not running"
        return
    }
    foreach ($owner in $owners) {
        if (Test-ApiOwnership $owner) {
            Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
            Write-Host "Stopped api (pid $owner)"
        } else {
            Write-Host "Skipped api: port $apiPort owner is not a Demiurgos process (pid $owner)"
        }
    }
}

# --- Hermes gateway (Windows parity of the POSIX launcher) ------------------
# start-gateway.ps1 owns the product-runtime resolution and the pin check; the
# launcher owns only its lifecycle (background start, tracked pid, stop). The
# gateway is optional: without Hermes the API still boots and the assistant
# reports pending.

function Test-GatewayTracked {
    if (-not (Test-Path -LiteralPath $gatewayPidFile -PathType Leaf)) { return $null }
    $raw = Get-Content -LiteralPath $gatewayPidFile -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $raw) { return $null }
    $procId = 0
    if (-not [int]::TryParse(([string]$raw).Trim(), [ref]$procId)) { return $null }
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($proc) { return $procId }
    return $null
}

function Start-Gateway {
    $gatewayLauncher = Join-Path $appRoot "start-gateway.ps1"
    if (-not (Test-Path -LiteralPath $gatewayLauncher -PathType Leaf)) {
        Write-Host "Gateway launcher not found at $gatewayLauncher; the assistant stays unavailable." -ForegroundColor Yellow
        return
    }
    $tracked = Test-GatewayTracked
    if ($tracked) {
        Write-Host "Already running gateway (pid $tracked)"
        return
    }
    if (Test-PortListening $gatewayPort) {
        Write-Host "Cannot start gateway: port $gatewayPort is already in use by an untracked process" -ForegroundColor Yellow
        return
    }
    if (-not $hermesBin) {
        Write-Host "Hermes CLI not found; the assistant will be unavailable." -ForegroundColor Yellow
        Write-Host "Install Hermes later and re-run this launcher to enable it." -ForegroundColor Yellow
        return
    }
    New-Item -ItemType Directory -Force -Path $logDir, $runDir | Out-Null
    # -ArgumentList joins with spaces and does not quote, so the launcher path
    # must be quoted when the install root contains a space (a username with one).
    $argLine = "-NoProfile -ExecutionPolicy Bypass -File `"$gatewayLauncher`""
    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $argLine `
        -RedirectStandardOutput $gatewayLog -RedirectStandardError $gatewayErrLog `
        -PassThru -WindowStyle Hidden
    Set-Content -LiteralPath $gatewayPidFile -Value $proc.Id -Encoding ASCII
    Write-Host "Started gateway (pid $($proc.Id))"
}

function Wait-GatewayReady {
    for ($i = 0; $i -lt 20; $i++) {
        if (Test-PortListening $gatewayPort) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Stop-Gateway {
    $tracked = Test-GatewayTracked
    if ($tracked) {
        # The tracked pid is the PowerShell wrapper; /T also kills its hermes child.
        & taskkill /PID $tracked /T /F 2>&1 | Out-Null
        Remove-Item -LiteralPath $gatewayPidFile -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped gateway (pid $tracked)"
        return
    }
    if (Test-PortListening $gatewayPort) {
        Write-Host "Skipped gateway: port $gatewayPort owner is not tracked by the launcher" -ForegroundColor Yellow
    }
}

function Open-Browser {
    $flag = [string]$env:DEMIURGOS_NO_BROWSER
    if ($flag -in @("1", "true", "yes")) {
        Write-Host "DEMIURGOS_NO_BROWSER is set; not opening http://127.0.0.1:$apiPort"
        return
    }
    Start-Process "http://127.0.0.1:$apiPort" | Out-Null
}

# --- Bounded boot rollback (S6-2/D6): local app\<version> scan only ---------
# Rollback ONLY: no update/download logic (G9 untouched); no network beyond
# the loopback /health probe in Wait-ApiReady.

function Get-CurrentVersionName {
    # Resolve the ACTIVE version: in the installed layout $appRoot is the
    # `current` junction itself, so its Target yields app\<version>; in dev
    # the checkout name is used and no app\ siblings exist, so none is found.
    $item = Get-Item -LiteralPath $appRoot -Force -ErrorAction SilentlyContinue
    if ($item -and $item.LinkType) {
        return [string](Split-Path -Leaf $item.Target)
    }
    return [string](Split-Path -Leaf $appRoot)
}

function Find-PreviousVersion {
    # Newest OTHER bootable app\<version> directory by LastWriteTime. A
    # version is bootable when it contains the launcher and the layout venv.
    $currentName = Get-CurrentVersionName
    $appDir = Join-Path $installRoot "app"
    if (-not (Test-Path -LiteralPath $appDir -PathType Container)) { return $null }
    $candidates = @(
        Get-ChildItem -LiteralPath $appDir -Directory -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -ne $currentName -and
                (Test-Path -LiteralPath (Join-Path $_.FullName "scripts\start-demiurgos.ps1") -PathType Leaf) -and
                (Test-Path -LiteralPath (Join-Path $_.FullName ".venv") -PathType Container)
            }
    )
    if ($candidates.Count -eq 0) { return $null }
    return [string]($candidates | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
}

function Invoke-BootRollback {
    # At most ONE rollback attempt, guarded by an exported env marker so a
    # broken previous version cannot loop.
    if ($env:DEMIURGOS_ROLLBACK_ATTEMPTED -eq "1") {
        Write-Host "Boot failed again after the rollback; no further fallback." -ForegroundColor Red
        Write-Host "Check the API log: $apiErrLog" -ForegroundColor Red
        return $false
    }
    $prev = Find-PreviousVersion
    if (-not $prev) {
        Write-Host "No bootable previous version found under $installRoot\app; cannot roll back." -ForegroundColor Red
        Write-Host "Check the API log: $apiErrLog" -ForegroundColor Red
        return $false
    }
    # Best-effort: stop the broken gateway and API so the previous version can
    # bind both ports.
    Stop-Gateway
    Stop-Api
    Write-Host "API failed to become ready; rolling back current -> $prev" -ForegroundColor Yellow
    $current = Join-Path $installRoot "current"
    $currentItem = Get-Item -LiteralPath $current -Force -ErrorAction SilentlyContinue
    if ($currentItem) {
        if ($currentItem.LinkType) {
            # Deleting a junction removes the link only, never the target.
            $currentItem.Delete()
        } else {
            Write-Host "current exists and is not a junction; refusing to clobber it" -ForegroundColor Red
            return $false
        }
    }
    New-Item -ItemType Junction -Path $current -Target $prev | Out-Null
    $env:DEMIURGOS_ROLLBACK_ATTEMPTED = "1"
    # Re-exec the launcher from the flipped `current` so every derived path
    # resolves against the previous version (S0-C rule 1). A child process
    # inherits the parent env (the marker) and propagates the exit code.
    $launcher = Join-Path $current "scripts\start-demiurgos.ps1"
    $child = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-File", $launcher, "restart") -Wait -PassThru -WindowStyle Hidden
    exit $child.ExitCode
}

# --- Resolve + export the contract environment BEFORE any child starts ------
# The launcher is the SOLE exporter of DEMIURGOS_FRONTEND_DIST (S1-6) and the
# bridge for the data-root .env auth mode (S0-A); DEMIURGOS_ROOT stays for
# legacy Hermes reads (S2-3).
$dataRoot = Resolve-DataRoot
Load-DataRootEnv
$env:DEMIURGOS_DATA_ROOT = $dataRoot
# Dedicated product profile/checkout (S5): export HERMES_HOME to the API child
# only when the product profile/checkout is provisioned, mirroring POSIX.
if ((Test-Path -LiteralPath (Join-Path $productHermesHome "config.yaml") -PathType Leaf) -or
    (Test-Path -LiteralPath (Join-Path $productAgentRoot ".git") -PathType Container)) {
    $env:HERMES_HOME = $productHermesHome
}
if (Test-Path -LiteralPath (Join-Path $productAgentRoot "plugins") -PathType Container) {
    $env:HERMES_AGENT_ROOT = $productAgentRoot
}
# The API client authenticates to the gateway with this key; the gateway child
# (start-gateway.ps1) bridges the same value into API_SERVER_KEY. The assistant
# is optional (S2-2): a key failure never aborts the whole boot.
try { Initialize-GatewayKey $dataRoot | Out-Null } catch {
    Write-Host "Continuing without a gateway key; the assistant stays unavailable." -ForegroundColor Yellow
}
$env:DEMIURGOS_FRONTEND_DIST = Join-Path $appRoot "frontend\dist"
$env:DEMIURGOS_ROOT = $appRoot
# Runtime version identity (install layout): <install_root>\current -> app\<version>.
# Windows parity of the POSIX export: only when a junction/symlink `current`
# layout exists (the PowerShell installer commits `current` as a junction);
# never an empty value. `@($target)[0]` normalizes the possibly-array Target.
if ((Split-Path -Leaf $appRoot) -eq "current") {
    $target = (Get-Item -LiteralPath $appRoot -Force).Target
    if ($target) { $env:DEMIURGOS_APP_VERSION = Split-Path -Leaf @($target)[0] }
}

function Show-Startup {
    # Start the optional gateway and the API, then report. The browser opens as
    # soon as the API is ready; the gateway warms in parallel and never gates
    # the boot (S2-2).
    Start-Gateway
    Start-Api
    if (Wait-ApiReady) {
        Write-Host "API ready on 127.0.0.1:$apiPort" -ForegroundColor Green
        Open-Browser
        if ($hermesBin) {
            if (Wait-GatewayReady) {
                Write-Host "Gateway ready on 127.0.0.1:$gatewayPort" -ForegroundColor Green
            } else {
                Write-Host "Gateway still warming; check $gatewayErrLog" -ForegroundColor Yellow
            }
        }
    } else {
        Write-Host "API did not become ready; check $apiErrLog" -ForegroundColor Red
        # S6-2/D6: bounded boot rollback - one fallback to the previous
        # bootable version, then exit non-zero when it also fails.
        if (-not (Invoke-BootRollback)) { exit 1 }
    }
}

switch ($Action) {
    "start" { Show-Startup }
    "restart" {
        Stop-Gateway
        Stop-Api
        Start-Sleep -Seconds 1
        Show-Startup
    }
    "stop" {
        Stop-Gateway
        Stop-Api
    }
}