# Demiurgos - CLI-stack overlay installer for Windows (opt-in)
#
# S4 follow-up: this is the historical install.ps1 preserved as an EXPLICIT
# OPT-IN path, mirroring `install.sh --with-cli-stack` on POSIX. It overlays the
# narrative agents/commands/prompts/skills/plugins into the OpenCode config home
# and prepares the dev-checkout Python environment; it does NOT install the web
# app (that is the public bootstrap + scripts\install-demiurgos.ps1).
#
# Always run it with a FILE context:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\install-cli-stack.ps1
# It must NOT be piped to iex: it relies on the script-file location.
#
# ASCII-only on purpose: Windows PowerShell 5.1 mis-decodes BOM-less UTF-8.

# Demiurgos Narrative Engine - Installer for Windows
# Overlay installation: adds narrative agents/skills/commands alongside Gentle-AI
# NON-DESTRUCTIVE: never overwrites existing Gentle-AI files
# Also prepares the checkout Python environment (.venv) and the data-root pointer

param(
    [switch]$Force,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# ============================================================
# CONFIGURATION
# ============================================================

# This overlay lives in scripts\ of the checkout, so the project root is the
# PARENT of this script's directory (historically the file sat at the root).
$ScriptDir = Split-Path -Parent $PSScriptRoot
$SourceDir = Join-Path $ScriptDir "src"
$ConfigHome = Join-Path $env:USERPROFILE ".config\opencode"

Write-Host @"
##### ###### ### ### ## ##  ## ######  ###### ###### ######
#   # #      # ### # ## ##  ## #    # #       #    # #     
#   # #####  #  #  # ## ##  ## ###### #   ### #    # ######
#   # #      #     # ## ##  ## #  ##  #     # #    #      #
##### ###### #     # ## ###### #   ##  ###### ###### ######
"@ -ForegroundColor Cyan
Write-Host ""
Write-Host "Config home: $ConfigHome"
Write-Host "Source dir:  $SourceDir"
Write-Host ""

# ============================================================
# FUNCTIONS
# ============================================================

function step { Write-Host ":: $args" -ForegroundColor Yellow }
function ok { Write-Host "   OK  $args" -ForegroundColor Green }
function skip { Write-Host "  SKIP $args" -ForegroundColor DarkGray }
function warn { Write-Host "  WARN $args" -ForegroundColor Magenta }

# ============================================================
# PRECHECKS
# ============================================================

step "Verifying source..."
if (-not (Test-Path $SourceDir)) {
    Write-Host "ERROR: Source directory not found: $SourceDir" -ForegroundColor Red
    exit 1
}
ok "Source found"

step "Verifying Gentle-AI..."
$OpenCodeJson = Join-Path $ConfigHome "opencode.json"
if (-not (Test-Path $OpenCodeJson)) {
    Write-Host "ERROR: opencode.json not found. Gentle-AI must be installed first." -ForegroundColor Red
    if (-not $Force) { exit 1 }
}
ok "Gentle-AI detected"

if ($DryRun) {
    warn "DRY RUN MODE - no files will be modified"
    Write-Host ""
}

# ============================================================
# 1. MERGE AGENTS INTO opencode.json
# ============================================================

step "1/8 Merging narrative agents..."

$FragmentPath = Join-Path $SourceDir "opencode.json"
$Fragment = Get-Content -Raw $FragmentPath | ConvertFrom-Json
$Existing = Get-Content -Raw $OpenCodeJson | ConvertFrom-Json

# Backup
$BackupPath = $OpenCodeJson + ".demiurgos-backup"
Copy-Item $OpenCodeJson $BackupPath -Force
ok "Backup saved"

# Merge agent keys
$addedAgents = 0
foreach ($key in $Fragment.agent.PSObject.Properties.Name) {
    if ($key -like "_comment*" -or $key -like '$comment*' -or $key -like "_installer*") { continue }
    if (-not $Existing.agent.$key) {
        $agentDef = $Fragment.agent.$key
        if ($agentDef.prompt) {
            $agentDef.prompt = ($agentDef.prompt -replace "__NARRATIVE_CONFIG__", $ConfigHome) -replace '\\', '/'
        }
        $Existing.agent | Add-Member -MemberType NoteProperty -Name $key -Value $agentDef -Force
        $addedAgents++
        ok "Added agent: $key"
    } else {
        skip "Agent exists: $key"
    }
}

if ($addedAgents -gt 0) {
    if (-not $DryRun) {
        $Existing | ConvertTo-Json -Depth 10 | Set-Content $OpenCodeJson -Encoding UTF8
    }
    ok "Merged $addedAgents agents"
} else {
    skip "No new agents to add"
}

# ============================================================
# 2. COPY COMMANDS
# ============================================================

step "2/8 Copying commands..."
$CommandsSource = Join-Path $SourceDir "commands"
$CommandsTarget = Join-Path $ConfigHome "commands"
if (-not (Test-Path $CommandsTarget)) { New-Item -ItemType Directory -Path $CommandsTarget -Force | Out-Null }

$copied = 0
Get-ChildItem -Path $CommandsSource -Filter "*.md" | ForEach-Object {
    $target = Join-Path $CommandsTarget $_.Name
    if (-not (Test-Path $target) -or $Force) {
        if (-not $DryRun) { Copy-Item $_.FullName $target -Force }
        $copied++
        ok "Copied: $($_.Name)"
    } else { skip "Exists: $($_.Name)" }
}
ok "$copied commands installed"

# ============================================================
# 3. COPY PROMPTS
# ============================================================

step "3/8 Copying prompts..."
$PromptsSource = Join-Path $SourceDir "prompts\narrative"
$PromptsTarget = Join-Path $ConfigHome "prompts\narrative"
if (-not (Test-Path $PromptsTarget)) { New-Item -ItemType Directory -Path $PromptsTarget -Force | Out-Null }

$copied = 0
Get-ChildItem -Path $PromptsSource -Filter "*.md" | ForEach-Object {
    $target = Join-Path $PromptsTarget $_.Name
    if (-not (Test-Path $target) -or $Force) {
        if (-not $DryRun) { Copy-Item $_.FullName $target -Force }
        $copied++
        ok "Copied: $($_.Name)"
    } else { skip "Exists: $($_.Name)" }
}
ok "$copied prompts installed"

# ============================================================
# 4. COPY SKILLS
# ============================================================

step "4/8 Copying skills..."
$SkillsSource = Join-Path $SourceDir "skills"
$SkillsTarget = Join-Path $ConfigHome "skills"
if (-not (Test-Path $SkillsTarget)) { New-Item -ItemType Directory -Path $SkillsTarget -Force | Out-Null }

$installed = 0
$skipped = 0

Get-ChildItem -Path $SkillsSource -Directory | ForEach-Object {
    $targetDir = Join-Path $SkillsTarget $_.Name
    $skillSourceDir = $_.FullName

    if ($_.Name -eq "_shared") {
        if (-not (Test-Path $targetDir)) { New-Item -ItemType Directory -Path $targetDir -Force | Out-Null }
        Get-ChildItem -Path $skillSourceDir -Filter "*.md" | ForEach-Object {
            $sharedTarget = Join-Path $targetDir $_.Name
            if (-not (Test-Path $sharedTarget) -or $Force) {
                if (-not $DryRun) { Copy-Item $_.FullName $sharedTarget -Force }
                ok "Copied shared: $($_.Name)"
            } else { skip "Exists: $($_.Name)" }
        }
    } else {
        if (-not (Test-Path $targetDir) -or $Force) {
            if (-not $DryRun) { Copy-Item $skillSourceDir $targetDir -Recurse -Force }
            $installed++
            ok "Copied skill: $($_.Name)"
        } else {
            $skipped++
            skip "Exists: $($_.Name)"
        }
    }
}

$skillMsg = "{0} skills installed, {1} skipped" -f $installed, $skipped
ok $skillMsg

# ============================================================
# 4.5. CONFIGURE HERMES MCP SERVE PROFILE
# ============================================================

step "4.5/8 Configuring demiurgos-mcp profile..."

$profileCheck = hermes profile list 2>$null | Select-String "demiurgos-mcp"
if ($profileCheck) {
    skip "demiurgos-mcp profile already exists"
} else {
    # Check if demiurgos-core exists to clone from
    $coreCheck = hermes profile list 2>$null | Select-String "demiurgos-core"
    $cloneArgs = @("profile", "create", "demiurgos-mcp", "--no-alias",
                   "--description", "Demiurgos MCP serve - narrative agent with file, terminal, clarify, skills, mcp toolsets")
    if ($coreCheck) { $cloneArgs += "--clone-from"; $cloneArgs += "demiurgos-core" }
    
    $result = & hermes $cloneArgs 2>&1
    if ($LASTEXITCODE -eq 0) {
        ok "demiurgos-mcp profile created"
    } else {
        warn "Could not create demiurgos-mcp profile. Create manually: hermes profile create demiurgos-mcp"
    }
}

ok "MCP profile configured"

# ============================================================
# 5. COPY TUI PLUGINS
# ============================================================

step "5/8 Copying TUI plugins..."
$TuiPluginsSource = Join-Path $SourceDir "tui-plugins"
$TuiPluginsTarget = Join-Path $ConfigHome "tui-plugins"
if (-not (Test-Path $TuiPluginsTarget)) { New-Item -ItemType Directory -Path $TuiPluginsTarget -Force | Out-Null }

$copied = 0
Get-ChildItem -Path $TuiPluginsSource -Filter "*.tsx" | ForEach-Object {
    $target = Join-Path $TuiPluginsTarget $_.Name
    if (-not (Test-Path $target) -or $Force) {
        if (-not $DryRun) { Copy-Item $_.FullName $target -Force }
        $copied++
        ok "Copied: $($_.Name)"
    } else { skip "Exists: $($_.Name)" }
}
ok "$copied TUI plugins installed"

# ============================================================
# 6. COPY PLUGINS
# ============================================================

step "6/8 Copying plugins..."
$PluginsSource = Join-Path $SourceDir "plugins"
$PluginsTarget = Join-Path $ConfigHome "plugins"
if (-not (Test-Path $PluginsTarget)) { New-Item -ItemType Directory -Path $PluginsTarget -Force | Out-Null }

if (Test-Path $PluginsSource) {
    $copied = 0
    Get-ChildItem -Path $PluginsSource | ForEach-Object {
        $target = Join-Path $PluginsTarget $_.Name
        if (-not (Test-Path $target) -or $Force) {
            if (-not $DryRun) { Copy-Item $_.FullName $target -Force }
            $copied++
            ok "Copied: $($_.Name)"
        } else { skip "Exists: $($_.Name)" }
    }
    ok "$copied plugins installed"
} else {
    skip "No plugins directory (optional)"
}

# ============================================================
# 7. MERGE tui.json
# ============================================================

step "7/8 Merging TUI config..."
$TuiJsonSource = Join-Path $SourceDir "tui.json"
$TuiJsonTarget = Join-Path $ConfigHome "tui.json"

if (Test-Path $TuiJsonSource) {
    $TuiSrc = Get-Content -Raw $TuiJsonSource | ConvertFrom-Json
    if (Test-Path $TuiJsonTarget) {
        $TuiExisting = Get-Content -Raw $TuiJsonTarget | ConvertFrom-Json
        Copy-Item $TuiJsonTarget ($TuiJsonTarget + ".demiurgos-backup") -Force
    } else {
        $TuiExisting = [PSCustomObject]@{ plugin = @() }
    }

    # Remove OpenCode logo if present (Demiurgos replaces it)
    $opencodeLogoPattern = "opencode-logo"
    $originalCount = $TuiExisting.plugin.Count
    $TuiExisting.plugin = $TuiExisting.plugin | Where-Object { $_ -notmatch $opencodeLogoPattern }
    if ($TuiExisting.plugin.Count -lt $originalCount) {
        ok "Removed OpenCode logo plugin"
    }

    $addedTui = 0
    foreach ($plugin in $TuiSrc.plugin) {
        $resolved = ($plugin -replace "__DEMIURGOS_CONFIG__", $ConfigHome) -replace '/', '\'
        if ($TuiExisting.plugin -notcontains $resolved) {
            $TuiExisting.plugin += $resolved
            $addedTui++
            ok "Added TUI plugin"
        } else { skip "TUI plugin exists" }
    }

    if ($addedTui -gt 0 -or $TuiExisting.plugin.Count -lt $originalCount) {
        if (-not $DryRun) {
            $TuiExisting | ConvertTo-Json -Depth 5 | Set-Content $TuiJsonTarget -Encoding UTF8
        }
        ok "Merged/Cleaned TUI config"
    }
} else {
    skip "No tui.json (optional)"
}

# ============================================================
# 7.5. PREPARE THE CHECKOUT PYTHON ENVIRONMENT
# ============================================================
# The launchers run the API with the checkout's own interpreter. Everything
# here is best-effort: a missing interpreter warns and the installer continues.

step "7.5/8 Preparing the checkout Python environment..."
$ProjectRoot = $ScriptDir
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$RequirementsFile = Join-Path $ProjectRoot "src\tools\demiurgos-suite\requirements.txt"

$SystemPython = Get-Command python -ErrorAction SilentlyContinue
if (-not $SystemPython) {
    warn "Python was not found on PATH. Skipping the virtual environment and the Python dependencies."
    warn "Install Python 3.11+ from https://www.python.org/downloads/ and re-run this script."
    warn "Without it the launchers cannot start: they expect $VenvPython."
} elseif (-not (Test-Path $RequirementsFile)) {
    warn "Requirements file not found: $RequirementsFile. Skipping the Python dependencies."
} elseif ($DryRun) {
    warn "DRY RUN: would create or refresh $VenvDir and install $RequirementsFile"
} else {
    try {
        # Idempotent: an existing environment is reused as-is, never recreated,
        # so re-running the installer cannot break a working venv.
        if (Test-Path $VenvPython) {
            ok "Virtual environment already present: $VenvDir"
        } else {
            & python -m venv $VenvDir
            if ($LASTEXITCODE -ne 0) { throw "python -m venv exited with code $LASTEXITCODE" }
            ok "Virtual environment created: $VenvDir"
        }

        & $VenvPython -m pip install -r $RequirementsFile
        if ($LASTEXITCODE -ne 0) { throw "pip install exited with code $LASTEXITCODE" }
        ok "Python dependencies installed"
    } catch {
        warn "Python environment setup failed: $_"
        warn "The remaining install steps are unaffected. Retry manually with:"
        warn "  $VenvPython -m pip install -r $RequirementsFile"
    }
}

# ============================================================
# 7.6. WRITE THE DATA-ROOT BOOTSTRAP POINTER
# ============================================================
# The launchers export DEMIURGOS_DATA_ROOT, but a process started by hand
# (hermes, a scheduled task, a directly started API) has no launcher and
# resolves the data root from the bootstrap pointer written here. The project's
# own write_pointer() owns the record schema and its location
# (platformdirs.user_config_dir("demiurgos")), so it is the single source of
# truth; the record is read back to prove the resolver accepts it.

step "7.6/8 Configuring the data root pointer..."
$WikiDir = Join-Path $ProjectRoot "src\tools\demiurgos-suite\wiki"

if (-not (Test-Path $VenvPython)) {
    warn "No usable interpreter at $VenvPython. Skipping the data-root pointer."
    warn "Processes started outside a launcher resolve the data root from that pointer only."
} elseif (-not (Test-Path (Join-Path $WikiDir "data_root.py"))) {
    warn "Resolver module not found at $WikiDir\data_root.py. Skipping the data-root pointer."
} elseif ($DryRun) {
    warn "DRY RUN: would write the data-root pointer for $ProjectRoot"
} else {
    try {
        # Single-quoted here-string: the payload is Python and must not be
        # expanded by PowerShell. argv carries both paths, so quoting is safe.
        $PointerScript = @'
import sys
from pathlib import Path

# Import the project's own resolver: one source of truth for the pointer path
# (platformdirs.user_config_dir("demiurgos")) and the record schema.
sys.path.insert(0, sys.argv[1])
from data_root import pointer_path, read_pointer, write_pointer

checkout = Path(sys.argv[2]).resolve()
existing = read_pointer()

# Bootstrap only: never silently repoint a data root the user already chose.
if existing is not None and existing != checkout:
    print(
        f"data root already configured at {existing}; left untouched "
        f"(bootstrap only). Repoint it by editing {pointer_path()}."
    )
    raise SystemExit(3)

write_pointer(checkout)

# Read the file back so the installer proves the resolver accepts the record.
recorded = read_pointer()
if recorded != checkout:
    raise SystemExit(f"read-back mismatch: wrote {checkout} but read {recorded}")
print(pointer_path())
'@

        $PointerScriptPath = Join-Path ([System.IO.Path]::GetTempPath()) "demiurgos-data-root-bootstrap.py"
        Set-Content -Path $PointerScriptPath -Value $PointerScript -Encoding UTF8

        $PointerOutput = & $VenvPython $PointerScriptPath $WikiDir $ProjectRoot
        $PointerStatus = $LASTEXITCODE
        Remove-Item $PointerScriptPath -ErrorAction SilentlyContinue

        if ($PointerStatus -eq 0) {
            ok "Data root pointer written and verified: $($PointerOutput -join ' ')"
            ok "Data root: $ProjectRoot"
        } elseif ($PointerStatus -eq 3) {
            warn "$($PointerOutput -join ' ')"
        } else {
            warn "Could not write the data-root pointer through the resolver's write_pointer()."
            warn "Processes started outside a launcher will not resolve a data root until it is written."
        }
    } catch {
        warn "Could not write the data-root pointer: $_"
        warn "Processes started outside a launcher will not resolve a data root until it is written."
    }
}

# ============================================================
# 8. VERIFY
# ============================================================

step "8/8 Verifying installation..."
$allGood = $true

$expectedAgents = @(
    "Demiurgos-Orchestrator", "narrative-explore", "narrative-propose",
    "narrative-world-spec", "narrative-character-spec", "narrative-design",
    "narrative-tasks", "narrative-outline", "narrative-draft",
    "narrative-revise", "narrative-verify", "narrative-archive"
)

$finalConfig = Get-Content -Raw $OpenCodeJson | ConvertFrom-Json
foreach ($agent in $expectedAgents) {
    if ($finalConfig.agent.$agent) {
        ok "Agent: $agent"
    } else {
        warn "Missing: $agent"
        $allGood = $false
    }
}

$cmdCount = (Get-ChildItem -Path (Join-Path $ConfigHome "commands") -Filter "narrative-*.md" -ErrorAction SilentlyContinue).Count
if ($cmdCount -ge 8) { ok "Commands: $cmdCount" } else { warn "Commands: $cmdCount (expected 8+)" }

$promptsDir = Join-Path $ConfigHome "prompts\narrative"
if (Test-Path $promptsDir) {
    $prCount = (Get-ChildItem -Path $promptsDir -Filter "*.md").Count
    if ($prCount -eq 11) { ok "Prompts: $prCount/11" } else { warn "Prompts: $prCount/11" }
}

$skCount = (Get-ChildItem -Path (Join-Path $ConfigHome "skills") -Directory -Filter "narrative-*" -ErrorAction SilentlyContinue).Count
if ($skCount -eq 11) { ok "Skills: $skCount/11" } else { warn "Skills: $skCount/11" }

# ============================================================
# DONE
# ============================================================

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
if ($allGood) {
    Write-Host "   DEMIURGOS INSTALLATION COMPLETE" -ForegroundColor Green
} else {
    Write-Host "  DEMIURGOS INSTALLED - check warnings" -ForegroundColor Yellow
}
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Restart OpenCode"
Write-Host "  2. Open your narrative project"
Write-Host "  3. Run: /narrative-init"
Write-Host "  4. Then: /narrative-onboard"
Write-Host ""

if ($DryRun) {
    Write-Host "NOTE: Dry run. No files modified." -ForegroundColor Magenta
}
