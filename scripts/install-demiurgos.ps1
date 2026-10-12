# ---------------------------------------------------------------------------
# Demiurgos Windows installer core (S3b - design S3-1..S3-7 parity, tasks
# 5.1-5.5). Windows PowerShell 5.1.
#
# Parity implementation of scripts/install-demiurgos.sh. Provisions a runnable
# Demiurgos under %LOCALAPPDATA%\Demiurgos with NO pre-installed
# Python/Node/compiler, NO admin rights and NO source clone:
#
#   1. floors preflight      Windows 10/11 x86_64 ONLY (decision #3579),
#                            LongPathsEnabled, free disk; unsupported
#                            Windows/arch fail fast with the documented
#                            manual-install alternative
#   2. version resolve       DEMIURGOS_VERSION else `latest`
#   3. download+verify       version.json, SHA256SUMS (+ .minisig when
#                            present), payload from DEMIURGOS_URL_BASE
#                            (https:// or file:// for hermetic harnesses)
#   4. uv provisioning       pinned UV_VERSION, verified against the baked
#                            checksum (DEMIURGOS_UV_SHA256 override for tests)
#   5. runtime               UV_PYTHON_INSTALL_DIR uv python install 3.12,
#                            uv venv --python 3.12 <stage>\.venv,
#                            uv pip install --require-hashes
#                            --only-binary=:all: -r requirements.lock
#                            (mandatory; optional extras best-effort)
#   6. atomic staging        <install_root>\.staging\<version>-<rand> on the
#                            SAME filesystem -> Move-Item -> app\<version> ->
#                            flip `current` JUNCTION (S0-C); failure leaves NO
#                            runnable state
#   7. data root             bootstrap-once pointer + .env seed (S0-A):
#                            only when neither env nor pointer exists
#
# The core NEVER runs a package manager other than the verified uv, NEVER
# executes files from the payload (only the launcher the user starts runs),
# and NEVER requests elevation.
#
# ASCII-only on purpose: Windows PowerShell 5.1 mis-decodes BOM-less UTF-8.
#
# Env contract (frozen layout, docs/architecture/INSTALL_LAYOUT.md):
#   DEMIURGOS_URL_BASE   channel base (REQUIRED; https:// or file://)
#   DEMIURGOS_VERSION    pin; default `latest`
#   DEMIURGOS_HOME       install root; default %LOCALAPPDATA%\Demiurgos
#   DEMIURGOS_DATA_ROOT  data root override (wins); default pointer/bootstrap
#   DEMIURGOS_UV_SHA256  expected uv archive sha256 (test seam; release
#                        pipeline bakes the real value at publish time)
#   UV_VERSION           pinned uv version
#   DEMIURGOS_LANGUAGE   seeded data-root locale (default es)
#   DEMIURGOS_WORLD      optional seeded world
#   DEMIURGOS_SEED_ONLY  "1" -> seed-only entry point: run ONLY the
#                        data-root bootstrap-once + .env seed (design S3-7)
#                        and exit 0. No download, no uv, no staging, no
#                        DEMIURGOS_URL_BASE required. Resolution order is the
#                        installer's own (DEMIURGOS_DATA_ROOT env -> existing
#                        pointer -> bootstrap-once). Idempotent: an existing
#                        pointer and .env are preserved byte-for-byte.
#   DEMIURGOS_FAKE_OS / DEMIURGOS_FAKE_ARCH / DEMIURGOS_FAKE_WINDOWS_VERSION /
#   DEMIURGOS_FAKE_LONGPATHS
#                        detection TEST SEAMS (same pattern as
#                        DEMIURGOS_UV_SHA256): default to real detection;
#                        hermetic harnesses simulate supported/unsupported
#                        platforms without editing this script at runtime.
#
# Decision #3579 NARROWS the declared matrix: the .docx importer must be
# uniform (present) on every supported system, so Windows on ARM/32-bit,
# Windows below the floor and disabled long paths are NOT supported and fail
# fast in the floors preflight with the documented manual-install alternative.
# The closure proof (D3) confirms the exact minimum Windows version; the
# mandatory/optional split stays as a safety net.
# ---------------------------------------------------------------------------

$ErrorActionPreference = "Stop"

# --- defaults ---------------------------------------------------------------
$urlBase = $env:DEMIURGOS_URL_BASE
$installRoot = if ($env:DEMIURGOS_HOME) { $env:DEMIURGOS_HOME } else { Join-Path $env:LOCALAPPDATA "Demiurgos" }
$version = if ($env:DEMIURGOS_VERSION) { $env:DEMIURGOS_VERSION } else { "latest" }
$uvVersion = if ($env:UV_VERSION) { $env:UV_VERSION } else { "0.5.24" }
$uvPythonInstallDir = Join-Path $installRoot "python"
$stagingRoot = Join-Path $installRoot ".staging"
# platformdirs user_config_dir("demiurgos") on Windows -> %APPDATA%\demiurgos
# (the same config dir the S2b launcher and data_root.py resolve).
$configDir = Join-Path $env:APPDATA "demiurgos"
$pointerFile = Join-Path $configDir "data-root.json"
# Single documented Windows floor (decision #3579). The closure proof (D3)
# confirms the exact minimum Windows version for the wheels-only mandatory
# closure; the floors preflight enforces exactly this constant and the fail
# message names it verbatim.
$windowsMinMajor = 10
$minFreeBytes = 2147483648   # 2 GiB

# Detection with test seams (see the env contract above): DEMIURGOS_FAKE_*
# default to the real values; hermetic harnesses override them to simulate
# platforms without editing this script at runtime.
$fakeOs = $env:DEMIURGOS_FAKE_OS
$arch = if ($env:DEMIURGOS_FAKE_ARCH) { $env:DEMIURGOS_FAKE_ARCH } else { $env:PROCESSOR_ARCHITECTURE }

# Work dirs created under the staging root (same filesystem, never a temp dir
# on another FS). Removed on failure so a failed install leaves no debris and
# no runnable state; the committed app/<version> is never touched.
$workDirs = New-Object System.Collections.Generic.List[string]
$script:stageDir = $null
$script:payloadFile = $null
$script:uvBin = $null
$script:dataRoot = $null
$script:envFile = $null

# Dot-source the shared checksum verifier (design S3-2).
. (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "lib\verify_checksum.ps1")

function Fail([string]$message) {
    throw "install-demiurgos: error: $message"
}

function Warn([string]$message) {
    Write-Host "install-demiurgos: warning: $message" -ForegroundColor Yellow
}

function Remove-WorkDirs {
    foreach ($d in $workDirs) {
        Remove-Item -LiteralPath $d -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($script:stageDir -and (Test-Path -LiteralPath $script:stageDir)) {
        Remove-Item -LiteralPath $script:stageDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# --- OS / arch --------------------------------------------------------------

function Get-UvArch {
    switch ($arch) {
        "AMD64" { return "x86_64" }
        "x86_64" { return "x86_64" }
        default {
            Fail "Windows on $arch is not supported: Demiurgos requires Windows 10/11 on x86_64. Manual install alternative: run Demiurgos from source on this machine - see the installation guide"
        }
    }
}

function Get-UvTarget {
    return "$(Get-UvArch)-pc-windows-msvc"
}

# --- floors preflight (5.3, decision #3579) ---------------------------------

function Get-WindowsMajorVersion {
    if ($env:DEMIURGOS_FAKE_WINDOWS_VERSION) {
        return [int](($env:DEMIURGOS_FAKE_WINDOWS_VERSION -split "\.")[0])
    }
    $os = Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion" -Name "CurrentMajorVersionNumber" -ErrorAction SilentlyContinue
    if ($os -and $os.CurrentMajorVersionNumber) {
        return [int]$os.CurrentMajorVersionNumber
    }
    return [int][System.Environment]::OSVersion.Version.Major
}

function Get-LongPathsEnabled {
    if ($env:DEMIURGOS_FAKE_LONGPATHS) {
        return ($env:DEMIURGOS_FAKE_LONGPATHS -eq "1")
    }
    $fs = Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -ErrorAction SilentlyContinue
    if ($fs -and $null -ne $fs.LongPathsEnabled) {
        return ($fs.LongPathsEnabled -eq 1)
    }
    return $false
}

function Invoke-FloorsCheck {
    # Decision #3579: Windows 10/11 x86_64 ONLY.
    if ($fakeOs -and $fakeOs -ne "Windows") {
        Fail "unsupported OS: $fakeOs (this core covers Windows; Linux/macOS is the POSIX core)"
    }
    Get-UvArch | Out-Null   # fails fast on ARM/32-bit with the manual alternative
    $major = Get-WindowsMajorVersion
    if ($major -lt $windowsMinMajor) {
        Fail "Windows 10 or newer is required (found $major); upgrade Windows and re-run - or use the manual install alternative from the installation guide"
    }
    if (-not (Get-LongPathsEnabled)) {
        Fail "Windows long paths (LongPathsEnabled) are disabled; enable the registry value HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled=1 and re-run - or use the manual install alternative from the installation guide"
    }
    $driveLetter = $installRoot.Substring(0, 1).ToUpper()
    $drive = Get-PSDrive -Name $driveLetter -ErrorAction SilentlyContinue
    if (-not $drive -or $drive.Free -lt $minFreeBytes) {
        Fail "at least 2 GiB of free disk space is required at $installRoot (found $($drive.Free)); free space and re-run"
    }
}

# --- download helpers (https + file:// test seam) ---------------------------

function Invoke-Download([string]$url, [string]$dest) {
    if ($url -like "file://*") {
        Copy-Item -LiteralPath $url.Substring(7) -Destination $dest -Force
    } elseif ($url -like "https://*") {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    } else {
        Fail "unsupported URL scheme in $url (use https:// or file://)"
    }
}

function Get-DownloadStdout([string]$url) {
    if ($url -like "file://*") {
        return Get-Content -LiteralPath $url.Substring(7) -Raw
    } elseif ($url -like "https://*") {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        return (Invoke-WebRequest -Uri $url -UseBasicParsing).Content
    } else {
        Fail "unsupported URL scheme in $url (use https:// or file://)"
    }
}

function Get-PayloadName([string]$file, [string]$version) {
    $json = Get-Content -LiteralPath $file -Raw | ConvertFrom-Json
    if ($json.artifacts -and $json.artifacts.windows) {
        return [string]$json.artifacts.windows
    }
    return "demiurgos-app-$version.zip"
}

function Get-ShaFor([string]$sumsFile, [string]$name) {
    foreach ($line in Get-Content -LiteralPath $sumsFile) {
        $parts = $line.Trim() -split "\s+"
        if ($parts.Count -ge 2 -and $parts[1] -eq $name) { return $parts[0] }
    }
    return $null
}

# --- version resolve + release download (5.3) -------------------------------

function Resolve-Version {
    if ($script:version -eq "latest") {
        $script:version = (Get-DownloadStdout "$urlBase/latest").Trim()
    }
    if (-not $script:version) {
        Fail "could not resolve a version from $urlBase/latest; set DEMIURGOS_VERSION explicitly and re-run"
    }
    Write-Host "install-demiurgos: resolved version $script:version"
}

function Invoke-FetchAndVerifyPayload {
    $workdir = Join-Path $stagingRoot ".work-$version-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
    $workDirs.Add($workdir)
    New-Item -ItemType Directory -Force -Path $workdir | Out-Null
    Invoke-Download "$urlBase/version.json" (Join-Path $workdir "version.json")
    Invoke-Download "$urlBase/SHA256SUMS" (Join-Path $workdir "SHA256SUMS")
    # Signature file is downloaded when present; verification is S5b's gate.
    try { Invoke-Download "$urlBase/SHA256SUMS.minisig" (Join-Path $workdir "SHA256SUMS.minisig") } catch { }

    # S5b (task 8.4): the manifest signature MUST be verified BEFORE any
    # checksum is trusted - the exact ordering of the POSIX core. Fail-closed:
    # a missing or invalid signature aborts the install, because a same-channel
    # unsigned manifest is tamper-together.
    if (-not (Test-Minisig -SumsFile (Join-Path $workdir "SHA256SUMS") -SignatureFile (Join-Path $workdir "SHA256SUMS.minisig"))) {
        Fail "signed-manifest verification failed; the channel manifest is tampered or unsigned - fix the channel and re-run"
    }

    $payloadName = Get-PayloadName (Join-Path $workdir "version.json") $version
    $script:payloadFile = Join-Path $workdir $payloadName
    Invoke-Download "$urlBase/$payloadName" $payloadFile

    $expected = Get-ShaFor (Join-Path $workdir "SHA256SUMS") $payloadName
    if (-not $expected) {
        Fail "no checksum entry for $payloadName in SHA256SUMS; fix the channel and re-run"
    }
    if (-not (Verify-Sha256 -FilePath $payloadFile -Expected $expected)) {
        Fail "checksum mismatch for $payloadName; the download is corrupt or tampered - fix the channel and re-run"
    }
}

# --- uv provisioning (5.3) ---------------------------------------------------

function Get-UvExpectedSha256 {
    if ($env:DEMIURGOS_UV_SHA256) { return $env:DEMIURGOS_UV_SHA256 }
    # Baked per-target checksums live here in the release build (S5a fills the
    # real values for the pinned UV_VERSION at publish time). Empty table with
    # no override -> refuse to install an unverified toolchain.
    $t = Get-UvTarget
    switch ($t) {
        "x86_64-pc-windows-msvc" { return $env:UV_SHA_X86_64_WINDOWS_MSVC }
        default { Fail "unsupported uv target: $t" }
    }
}

function Invoke-ProvisionUv {
    $target = Get-UvTarget
    $expected = Get-UvExpectedSha256
    if (-not $expected) {
        Fail "no uv checksum available for $target; set DEMIURGOS_UV_SHA256 or rebuild with baked checksums - refusing an unverified toolchain"
    }
    $url = "$urlBase/uv/uv-$target-$uvVersion.zip"
    $workdir = Join-Path $stagingRoot ".uv-$version-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
    $workDirs.Add($workdir)
    New-Item -ItemType Directory -Force -Path $workdir | Out-Null
    $archive = Join-Path $workdir "uv.zip"
    Invoke-Download $url $archive
    if (-not (Verify-Sha256 -FilePath $archive -Expected $expected)) {
        Fail "checksum mismatch for the uv archive $url; refusing to install an unverified toolchain - fix the channel and re-run"
    }
    Expand-Archive -LiteralPath $archive -DestinationPath $workdir -Force
    $uvFile = Get-ChildItem -Path $workdir -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @("uv.exe", "uv.ps1") } | Select-Object -First 1
    if (-not $uvFile) {
        Fail "the uv archive contains no uv binary; fix the channel and re-run"
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $installRoot "bin") | Out-Null
    # Nested Join-Path: PS 5.1 accepts only -Path/-ChildPath (a third positional
    # child path is PS 6+ / -AdditionalChildPath) and would fail binding with
    # "A positional parameter cannot be found that accepts argument 'uv.ps1'".
    $script:uvBin = Join-Path (Join-Path $installRoot "bin") $uvFile.Name
    Copy-Item -LiteralPath $uvFile.FullName -Destination $script:uvBin -Force
    Write-Host "install-demiurgos: uv $uvVersion installed at $script:uvBin"
}

# --- stage, venv, install (5.3) ----------------------------------------------

function Find-ReqFile([string]$name) {
    foreach ($cand in @(
        (Join-Path $script:stageDir $name),
        (Join-Path $script:stageDir "src\tools\demiurgos-suite\$name")
    )) {
        if (Test-Path -LiteralPath $cand -PathType Leaf) { return $cand }
    }
    return $null
}

function Invoke-StageAndInstall {
    $script:stageDir = Join-Path $stagingRoot "$version-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
    $workDirs.Add($script:stageDir)
    New-Item -ItemType Directory -Force -Path $script:stageDir | Out-Null
    try {
        Expand-Archive -LiteralPath $payloadFile -DestinationPath $script:stageDir -Force
    } catch {
        Fail "cannot extract the payload; it may be corrupt - re-run"
    }

    $env:UV_PYTHON_INSTALL_DIR = $uvPythonInstallDir
    & $script:uvBin python install 3.12
    if ($LASTEXITCODE -ne 0) {
        Fail "uv python install failed (uv unreachable or broken); no runnable state was left - re-run"
    }
    & $script:uvBin venv --python 3.12 (Join-Path $script:stageDir ".venv")
    if ($LASTEXITCODE -ne 0) {
        Fail "uv venv creation failed; no runnable state was left - re-run"
    }

    $venvPython = Join-Path $script:stageDir ".venv\Scripts\python.exe"
    $req = Find-ReqFile "requirements.lock"
    if (-not $req) { $req = Find-ReqFile "requirements.txt" }
    if (-not $req) {
        Fail "no hash-locked requirements file (requirements.lock) in the payload; refusing a non-locked install - fix the channel and re-run"
    }

    & $script:uvBin pip install --python $venvPython --require-hashes --only-binary=:all: -r $req
    if ($LASTEXITCODE -ne 0) {
        Fail "the mandatory wheel-only install failed; aborting with no runnable half-install - see the error above and re-run"
    }

    $opt = Find-ReqFile "requirements-optional.txt"
    if ($opt) {
        & $script:uvBin pip install --python $venvPython --only-binary=:all: -r $opt
        if ($LASTEXITCODE -ne 0) {
            Warn "optional extras failed to install; the app runs with degraded optional features (document conversion / live watching unavailable)"
        }
    } else {
        Warn "no requirements-optional.txt in the payload; optional extras are skipped"
    }
}

function Invoke-CommitStaging {
    $target = Join-Path $installRoot "app\$version"
    New-Item -ItemType Directory -Force -Path (Join-Path $installRoot "app") | Out-Null
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
    # Same-FS rename (staging lives under <install_root>\.staging).
    Move-Item -LiteralPath $stageDir -Destination $target
    $script:stageDir = $null
    # Flip `current` as a JUNCTION (S0-C: junction, not symlink). Deleting a
    # junction removes the link only, never the target app/<version>.
    $current = Join-Path $installRoot "current"
    $currentItem = Get-Item -LiteralPath $current -Force -ErrorAction SilentlyContinue
    if ($currentItem) {
        if ($currentItem.LinkType) {
            $currentItem.Delete()
        } else {
            Fail "current exists and is not a junction; refusing to clobber it"
        }
    }
    New-Item -ItemType Junction -Path $current -Target $target | Out-Null
    Write-Host "install-demiurgos: installed $version at $installRoot\current"
}

function Write-ChannelConfig {
    # Persist the channel base URL this install validated (https:// or
    # file:// - `Invoke-Download` fails on any other scheme) so the runtime
    # updater resolves it WITHOUT the env override (design S2-b). Written next
    # to Invoke-CommitStaging because it records the channel this install
    # trusts. Backslashes (file://C:\...) are JSON-escaped like the data-root
    # record; UTF-8 without BOM.
    $escapedBase = $urlBase.Replace("\", "\\")
    $record = @"
{
  "schema_version": 1,
  "url_base": "$escapedBase"
}
"@
    [System.IO.File]::WriteAllText(
        (Join-Path $installRoot "channel.json"), $record,
        (New-Object System.Text.UTF8Encoding($false))
    )
    Write-Host "install-demiurgos: persisted channel config at $installRoot\channel.json"
}

# --- data-root bootstrap-once + .env seed (5.3, S0-A) ------------------------

function Invoke-SeedEnvFile {
    $script:envFile = Join-Path $script:dataRoot ".env"
    if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        $locale = if ($env:DEMIURGOS_LANGUAGE) { $env:DEMIURGOS_LANGUAGE } else { "es" }
        $lines = @("DEMIURGOS_AUTH_MODE=local-dev", "DEMIURGOS_LANGUAGE=$locale")
        if ($env:DEMIURGOS_WORLD) { $lines += "DEMIURGOS_WORLD=$($env:DEMIURGOS_WORLD)" }
        Set-Content -LiteralPath $envFile -Value $lines -Encoding ASCII
        Write-Host "install-demiurgos: seeded $envFile (DEMIURGOS_AUTH_MODE=local-dev)"
    }
}

function Invoke-DataRootBootstrap {
    if ($env:DEMIURGOS_DATA_ROOT) {
        $script:dataRoot = $env:DEMIURGOS_DATA_ROOT
        Write-Host "install-demiurgos: using DEMIURGOS_DATA_ROOT=$script:dataRoot (env override; pointer untouched)"
        return
    }
    if (Test-Path -LiteralPath $pointerFile -PathType Leaf) {
        try {
            $record = Get-Content -LiteralPath $pointerFile -Raw | ConvertFrom-Json
            if ($record.data_root) {
                $script:dataRoot = [string]$record.data_root
                Write-Host "install-demiurgos: preserving existing data-root pointer -> $script:dataRoot"
                return
            }
        } catch {
            Fail "data-root pointer $pointerFile is unreadable; refusing to guess"
        }
    }
    # Bootstrap-once: pointer + .env seed, only when neither env nor pointer
    # exists. Format is byte-compatible with data_root.py write_pointer
    # (schema_version 1, json.dumps indent 2, trailing newline) so Python's
    # read_pointer reads it back. UTF-8 without BOM: a Windows username may
    # legally contain non-ASCII characters.
    $script:dataRoot = Join-Path $installRoot "data"
    New-Item -ItemType Directory -Force -Path $configDir, $script:dataRoot,
        (Join-Path $script:dataRoot "mundos"), (Join-Path $script:dataRoot "ideas"),
        (Join-Path $script:dataRoot "data"), (Join-Path $script:dataRoot "config") | Out-Null
    $escaped = $script:dataRoot.Replace("\", "\\")
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $record = @"
{
  "schema_version": 1,
  "data_root": "$escaped",
  "updated_at": "$stamp"
}
"@
    [System.IO.File]::WriteAllText(
        $pointerFile, $record,
        (New-Object System.Text.UTF8Encoding($false))
    )
    Write-Host "install-demiurgos: bootstrapped data root at $script:dataRoot"
    Invoke-SeedEnvFile
}

# --- seed-only entry point (S0-A; test/ops seam) -----------------------------
# DEMIURGOS_SEED_ONLY=1 performs ONLY the data-root bootstrap-once + .env seed
# (design S3-7) and exits 0 - the exact code path the full install runs at the
# end (Invoke-DataRootBootstrap), so a Windows gated-write regression harness
# can exercise the REAL shipping seed against a tmp APPDATA/DEMIURGOS_HOME.
# Never downloads, never touches uv, never requires DEMIURGOS_URL_BASE.
# Idempotence is preserved: an existing pointer and an existing .env are left
# byte-for-byte untouched.
if ($env:DEMIURGOS_SEED_ONLY -eq "1") {
    try {
        Invoke-DataRootBootstrap
        Write-Host "install-demiurgos: seed-only done; data root is $script:dataRoot"
    } catch {
        Write-Host $_.Exception.Message -ForegroundColor Red
        exit 1
    }
    exit 0
}

# --- main --------------------------------------------------------------------

try {
    if (-not $urlBase) {
        Fail "DEMIURGOS_URL_BASE is not set; it is required (https:// or file:// channel base)"
    }

    New-Item -ItemType Directory -Force -Path $installRoot | Out-Null
    Invoke-FloorsCheck
    Resolve-Version

    # Idempotent re-run: same version already current -> exit 0, nothing to do.
    $current = Join-Path $installRoot "current"
    $currentItem = Get-Item -LiteralPath $current -Force -ErrorAction SilentlyContinue
    $alreadyCurrent = $false
    if ($currentItem -and $currentItem.LinkType) {
        $targetExpected = Join-Path $installRoot "app\$version"
        if ([string]$currentItem.Target -eq $targetExpected -and (Test-Path -LiteralPath $targetExpected)) {
            $alreadyCurrent = $true
        }
    }
    if ($alreadyCurrent) {
        Write-Host "install-demiurgos: $version is already installed and current; nothing to do"
        exit 0
    }

    New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null
    Invoke-FetchAndVerifyPayload
    Invoke-ProvisionUv
    Invoke-StageAndInstall
    Invoke-CommitStaging
    Write-ChannelConfig
    Invoke-DataRootBootstrap

    Write-Host "install-demiurgos: done. Start Demiurgos with:"
    Write-Host "  $installRoot\current\scripts\start-demiurgos.ps1 start"
} catch {
    Remove-WorkDirs
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}