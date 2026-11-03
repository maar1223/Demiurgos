# ---------------------------------------------------------------------------
# Provision the product-owned Hermes runtime (S5/S7, hermes-core-runtime T4).
#
# Windows parity of scripts/provision-hermes.sh. The runtime is the pinned
# Demiurgos fork installed under the product root, never the user's personal
# %USERPROFILE%\.hermes and never whatever `hermes` happens to be on PATH:
#
#   <install root>\hermes-agent   pinned git checkout (exact launcher at
#                                 <checkout>\.hermes\bin\hermes.exe)
#   <install root>\hermes         dedicated HERMES_HOME (skills, tools store)
#   <install root>\hermes\tools   HERMES_RUNTIME_DIR (pm tool store)
#
# A pre-existing Hermes is reported, never modified. The checkout's exact
# launcher is the product entry point; the setup script publishes Windows
# conveniences inside the dedicated HERMES_HOME, not the user profile.
#
# Usage:
#   powershell.exe -NoProfile -File provision-hermes.ps1 [-InstallRoot PATH]
#   powershell.exe -NoProfile -File provision-hermes.ps1 -Check [-InstallRoot PATH]
#
# Test seams: DEMIURGOS_HERMES_FORK_URL, DEMIURGOS_HERMES_PIN,
# DEMIURGOS_HERMES_SKIP=1, DEMIURGOS_GIT.
#
# ASCII-only on purpose: Windows PowerShell 5.1 mis-decodes BOM-less UTF-8.
# ---------------------------------------------------------------------------

param(
    [switch]$Check,
    [string]$InstallRoot = ""
)

$ErrorActionPreference = "Stop"

$forkUrl = if ($env:DEMIURGOS_HERMES_FORK_URL) { $env:DEMIURGOS_HERMES_FORK_URL } else { "https://github.com/maar1223/hermes-agent-demiurgos.git" }
$pin = if ($env:DEMIURGOS_HERMES_PIN) { $env:DEMIURGOS_HERMES_PIN } else { "d046ff9905b8470c4a0cfd5e9da566986056b438" }
$gitBin = if ($env:DEMIURGOS_GIT) { $env:DEMIURGOS_GIT } else { "git" }

if ($InstallRoot) {
    $root = $InstallRoot
} elseif ($env:DEMIURGOS_HOME) {
    $root = $env:DEMIURGOS_HOME
} else {
    $root = Join-Path $env:LOCALAPPDATA "Demiurgos"
}
$hermesHome = if ($env:DEMIURGOS_HERMES_HOME) { $env:DEMIURGOS_HERMES_HOME } else { Join-Path $root "hermes" }
$agentRoot = if ($env:DEMIURGOS_HERMES_AGENT_ROOT) { $env:DEMIURGOS_HERMES_AGENT_ROOT } else { Join-Path $root "hermes-agent" }
$runtimeDir = Join-Path $hermesHome "tools"

function Write-Log([string]$message) { Write-Host "provision-hermes: $message" }
function Write-Warn([string]$message) { Write-Host "provision-hermes: warning: $message" -ForegroundColor Yellow }
function Fail([string]$message) {
    Write-Host "provision-hermes: error: $message" -ForegroundColor Red
    exit 1
}

function Test-ValidPin([string]$value) {
    return ($value -match '^[0-9a-fA-F]{40}$')
}

function Get-CheckoutHead([string]$dir) {
    if (-not (Test-Path -LiteralPath (Join-Path $dir ".git") -PathType Container)) { return "" }
    $head = & $gitBin -C $dir rev-parse HEAD 2>$null
    if ($LASTEXITCODE -ne 0) { return "" }
    return ([string]$head).Trim()
}

function Test-CheckoutAtPin([string]$dir) {
    return ((Get-CheckoutHead $dir) -eq $pin)
}

function Get-RuntimeLauncher {
    return (Join-Path $agentRoot ".hermes\bin\hermes.exe")
}

function Test-Provisioned {
    return ((Test-CheckoutAtPin $agentRoot) -and (Test-Path -LiteralPath (Get-RuntimeLauncher) -PathType Leaf))
}

function Report-PriorInstall {
    $found = $false
    $onPath = Get-Command hermes -ErrorAction SilentlyContinue
    if ($onPath) {
        Write-Log "found an existing Hermes on PATH: $($onPath.Source) (left untouched)"
        $found = $true
    }
    $personal = Join-Path $env:USERPROFILE ".hermes"
    if (Test-Path -LiteralPath $personal -PathType Container) {
        Write-Log "found an existing personal profile: $personal (left untouched)"
        $found = $true
    }
    if ($found) {
        Write-Log "the product-owned runtime below is used regardless."
    }
}

function Test-Runtime {
    if (-not (Test-Path -LiteralPath (Join-Path $agentRoot ".git") -PathType Container)) {
        Write-Host "provision-hermes: expected the product runtime at $agentRoot (pin $pin), found nothing; re-run the installer or this script." -ForegroundColor Red
        return $false
    }
    $head = Get-CheckoutHead $agentRoot
    if ($head -ne $pin) {
        Write-Host "provision-hermes: expected pin $pin at $agentRoot, found $(if ($head) { $head } else { 'unknown' }); re-run the installer or this script." -ForegroundColor Red
        return $false
    }
    $launcher = Get-RuntimeLauncher
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
        Write-Host "provision-hermes: expected the runtime launcher at $launcher, found none; re-run the installer or this script." -ForegroundColor Red
        return $false
    }
    return $true
}

function Invoke-FetchPinnedCheckout([string]$dest) {
    if (-not (Test-ValidPin $pin)) {
        Fail "invalid pinned commit '$pin' (expected 40 hexadecimal characters)"
    }
    & $gitBin init -q $dest
    if ($LASTEXITCODE -ne 0) { Fail "cannot initialise the runtime checkout at $dest (is git installed?)" }
    & $gitBin -C $dest remote add origin $forkUrl
    if ($LASTEXITCODE -ne 0) { Fail "cannot configure the runtime fork remote ($forkUrl)" }
    & $gitBin -C $dest fetch --depth 1 origin $pin
    if ($LASTEXITCODE -ne 0) { Fail "cannot fetch the pinned commit $pin from $forkUrl" }
    & $gitBin -C $dest checkout -q FETCH_HEAD
    if ($LASTEXITCODE -ne 0) { Fail "cannot check out the pinned commit $pin" }
    if ((Get-CheckoutHead $dest) -ne $pin) {
        Fail "expected pin $pin, the fetched checkout reports $(Get-CheckoutHead $dest)"
    }
    # S3: the Demiurgos patch (tool_choice "none" -> empty toolset) must be in
    # the pinned tree, not merely in the fork's history.
    $server = Join-Path $dest "gateway\platforms\api_server.py"
    if (-not (Select-String -LiteralPath $server -Pattern "no_tools" -Quiet)) {
        Fail "the pinned tree at $dest does not carry the Demiurgos no_tools patch (S3)"
    }
}

function Install-PinnedCheckout {
    if (Test-CheckoutAtPin $agentRoot) {
        Write-Log "runtime checkout already at the pinned commit $pin"
        return
    }
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    $staging = Join-Path $root (".provision-hermes-" + $PID)
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $staging | Out-Null
    $tree = Join-Path $staging "tree"
    Invoke-FetchPinnedCheckout $tree
    if (Test-Path -LiteralPath $agentRoot) {
        $backup = Join-Path $root ("hermes-agent.previous-" + (Get-Date -Format "yyyyMMddHHmmss"))
        Move-Item -LiteralPath $agentRoot -Destination $backup
        Write-Warn "previous runtime checkout moved to $backup"
    }
    Move-Item -LiteralPath $tree -Destination $agentRoot
    Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
}

function Invoke-HermesSetup {
    $setup = Join-Path $agentRoot "setup-hermes.ps1"
    if (-not (Test-Path -LiteralPath $setup -PathType Leaf)) {
        Fail "the pinned tree at $agentRoot has no setup-hermes.ps1; fix the pin and re-run"
    }
    $scratch = Join-Path $root (".provision-hermes-home-" + $PID)
    if (Test-Path -LiteralPath $scratch) { Remove-Item -LiteralPath $scratch -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $scratch | Out-Null
    Write-Log "installing the runtime (first run can take 1-5 minutes)"
    # Scratch HOME + uv caches so no user cache or shell profile is touched;
    # the dedicated HERMES_HOME/RUNTIME_DIR keep the install product-owned.
    $env:HOME = $scratch
    $env:UV_CACHE_DIR = Join-Path $scratch "uv-cache"
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $scratch "uv-python"
    $env:HERMES_HOME = $hermesHome
    $env:HERMES_RUNTIME_DIR = $runtimeDir
    $env:HERMES_AGENT_ROOT = $agentRoot
    Push-Location $agentRoot
    try {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $setup
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
    if ($code -ne 0) {
        Fail "setup-hermes.ps1 failed; expected pin $pin at $agentRoot - fix the error above and re-run"
    }
}

function Invoke-Provision {
    Report-PriorInstall
    if (Test-Provisioned) {
        Write-Log "runtime already provisioned at $agentRoot (pin $pin)"
        return
    }
    if (-not (Test-ValidPin $pin)) {
        Fail "invalid pinned commit '$pin' (expected 40 hexadecimal characters)"
    }
    Install-PinnedCheckout
    Invoke-HermesSetup
    if (-not (Test-Runtime)) {
        Fail "post-install verification failed; the assistant runtime is not usable"
    }
    Write-Log "runtime ready at $agentRoot (pin $pin)"
}

if ($env:DEMIURGOS_HERMES_SKIP -eq "1") {
    Write-Log "provisioning skipped (DEMIURGOS_HERMES_SKIP=1)"
    exit 0
}

if ($Check) {
    if (Test-Runtime) { exit 0 }
    exit 1
}

Invoke-Provision
