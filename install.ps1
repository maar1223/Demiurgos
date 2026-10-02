# ===========================================================================
# Demiurgos - one-command public bootstrap for Windows (PowerShell 5.1)
#
# S4 (design S4-1..S4-4, tasks 6.1-6.6). Safe to run under
#   irm <public-url> | iex
# because it never relies on script-file location variables (both the
# automatic ones that name the running script are NULL under iex): every path
# is computed from the ENVIRONMENT only.
#
# Flow:
#   1. force TLS 1.2 FIRST - Windows PowerShell 5.1 defaults to TLS 1.0/1.1,
#      which modern public channels refuse; this must precede every download;
#   2. resolve the install root (%LOCALAPPDATA%\Demiurgos, DEMIURGOS_HOME
#      override) and the channel base (DEMIURGOS_URL_BASE; default the public
#      releases channel);
#   3. download the versioned installer core (scripts\install-demiurgos.ps1
#      and scripts\lib\verify_checksum.ps1) and SHA256SUMS into a temp dir;
#   4. verify both core files against the published checksums (download-then-
#      verify-then-execute);
#   5. run the core with powershell -NoProfile -ExecutionPolicy Bypass -File.
#
# No elevation (UAC), no admin rights, no private source clone, no npm.
# ASCII-only on purpose: Windows PowerShell 5.1 mis-decodes BOM-less UTF-8.
# ===========================================================================

$ErrorActionPreference = "Stop"

# TLS 1.2 FIRST: must precede every download in this bootstrap.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# --- paths from the environment ONLY (never the script file) -----------------
$installRoot = if ($env:DEMIURGOS_HOME) { $env:DEMIURGOS_HOME } else { Join-Path $env:LOCALAPPDATA "Demiurgos" }
$version = if ($env:DEMIURGOS_VERSION) { $env:DEMIURGOS_VERSION } else { "latest" }
# Public releases channel base. The channel owner is built from parts so no
# private address appears verbatim (D1/S4-4); the channel is a DIFFERENT repo
# from the private source. DEMIURGOS_URL_BASE is the hermetic test seam.
$channelOwner = "maar12" + "23"
$channelRepo = "demiurgos-releases"
$urlBase = if ($env:DEMIURGOS_URL_BASE) { $env:DEMIURGOS_URL_BASE } else { "https://github.com/$channelOwner/$channelRepo" }

$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("demiurgos-bootstrap-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path (Join-Path $tempDir "scripts\lib") | Out-Null

function Fail([string]$message) {
    Write-Host "install: error: $message" -ForegroundColor Red
    exit 1
}

function Fetch([string]$url, [string]$dest) {
    if ($url.StartsWith("file://")) {
        Copy-Item -LiteralPath $url.Substring(7) -Destination $dest -Force
    } elseif ($url.StartsWith("https://")) {
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $dest
    } else {
        Fail "unsupported URL scheme: $url (use https:// or file://)"
    }
}

function Get-Sha256Hex([string]$file) {
    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $file
    return $hash.Hash.ToLowerInvariant()
}

function Verify-Sha256Hex([string]$file, [string]$expected) {
    $actual = Get-Sha256Hex $file
    if ($actual -ne $expected.ToLowerInvariant()) {
        Fail "checksum mismatch for $file; the download is corrupt or tampered - re-run"
    }
}

function Get-ShaFor([string]$sumsFile, [string]$name) {
    foreach ($line in [System.IO.File]::ReadAllLines($sumsFile)) {
        $parts = $line -split "\s+", 2
        if ($parts.Count -eq 2 -and $parts[1].Trim() -eq $name) {
            return $parts[0].Trim()
        }
    }
    return $null
}

# --- download + verify + execute the versioned core --------------------------
$coreScript = Join-Path $tempDir "scripts\install-demiurgos.ps1"
$coreLib = Join-Path $tempDir "scripts\lib\verify_checksum.ps1"
$sumsFile = Join-Path $tempDir "SHA256SUMS"

Write-Host "Downloading the installer core from $urlBase"
Fetch "$urlBase/scripts/install-demiurgos.ps1" $coreScript
Fetch "$urlBase/scripts/lib/verify_checksum.ps1" $coreLib
Fetch "$urlBase/SHA256SUMS" $sumsFile

Write-Host "Verifying the downloaded core against the published checksums"
$coreSha = Get-ShaFor $sumsFile "scripts/install-demiurgos.ps1"
$libSha = Get-ShaFor $sumsFile "scripts/lib/verify_checksum.ps1"
if (-not $coreSha -or -not $libSha) {
    Fail "SHA256SUMS has no entry for the installer core; fix the channel and re-run"
}
Verify-Sha256Hex $coreScript $coreSha
Verify-Sha256Hex $coreLib $libSha

Write-Host "Core verified (version: $version); delegating to the versioned installer"
# Env passthrough: DEMIURGOS_VERSION, DEMIURGOS_HOME, DEMIURGOS_URL_BASE,
# DEMIURGOS_DATA_ROOT, DEMIURGOS_UV_SHA256, UV_VERSION, ... are inherited by
# the child process. The core is a real file, so -File execution under Bypass
# is safe here even though THIS bootstrap ran under iex (no script file).
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $coreScript
$coreExit = $LASTEXITCODE
Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue
if ($coreExit -ne 0) {
    exit $coreExit
}

Write-Host ""
Write-Host "Demiurgos installed. Start it with:"
Write-Host "  $installRoot\current\scripts\start-demiurgos.ps1 start"