# Demiurgos Narrative Engine - Installer for Windows
# Overlay installation: adds narrative agents/skills/commands alongside Gentle-AI
# NON-DESTRUCTIVE: never overwrites existing Gentle-AI files

param(
    [switch]$Force,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# ============================================================
# CONFIGURATION
# ============================================================

$ScriptDir = $PSScriptRoot
$SourceDir = Join-Path $ScriptDir "src"
$ConfigHome = Join-Path $env:USERPROFILE ".config\opencode"

Write-Host @"
████▄ ██████ ██▄ ▄██ ██ ██  ██ █████▄  ██████ ██████ ██████
█   █ █      █ █▄█ █ ██ ██  ██ █    █ █       █    █ █     
█   █ █████  █  ▀  █ ██ ██  ██ █████▀ █   ███ █    █ ██████
█   █ █      █     █ ██ ██  ██ █  ▀▄  █     █ █    █      █
████▀ ██████ █     █ ██ ▀████▀ █   ▀▄  ██████ ██████ ██████
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
