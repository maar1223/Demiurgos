# Demiurgos — Migrar skills narrativos a formato SKILL.md de Hermes
# Lee src/prompts/narrative/narrative-{fase}.md
# Crea skills/narrative-{fase}/SKILL.md con frontmatter YAML de Hermes

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
$ProjectRoot = Split-Path -Parent $ScriptDir
$SourceDir = Join-Path $ProjectRoot "src\prompts\narrative"
$TargetBase = Join-Path $ProjectRoot "skills"

$Skills = @(
    @{ file="narrative-init.md"; name="narrative-init"; desc="Bootstrap a Demiurgos narrative project. Validates structure, reads constitution, creates state file, detects Engram."; tags="narrative, demiurgos, setup" },
    @{ file="narrative-explore.md"; name="narrative-explore"; desc="Investigate existing lore, context, and characters before proposing a new narrative arc."; tags="narrative, demiurgos, research" },
    @{ file="narrative-propose.md"; name="narrative-propose"; desc="Create a narrative proposal: logline, MICE quotient, and reader promises."; tags="narrative, demiurgos, planning" },
    @{ file="narrative-world-spec.md"; name="narrative-world-spec"; desc="Specify world rules, technical lore, and magic system constraints for a narrative arc."; tags="narrative, demiurgos, worldbuilding" },
    @{ file="narrative-character-spec.md"; name="narrative-character-spec"; desc="Create character sheets, arcs, relationships, and POV assignments."; tags="narrative, demiurgos, characters" },
    @{ file="narrative-design.md"; name="narrative-design"; desc="Design narrative structure with Snyder beats, chapter outline, and scene sequencing."; tags="narrative, demiurgos, planning" },
    @{ file="narrative-tasks.md"; name="narrative-tasks"; desc="Break narrative design into implementable writing tasks with scene goals and context bundles."; tags="narrative, demiurgos, planning" },
    @{ file="narrative-outline.md"; name="narrative-outline"; desc="Compile complete context package (lore, characters, beats) for the writing phase."; tags="narrative, demiurgos, writing" },
    @{ file="narrative-draft.md"; name="narrative-draft"; desc="Write narrative prose in sagas/ following the spec, design, and outline."; tags="narrative, demiurgos, writing" },
    @{ file="narrative-revise.md"; name="narrative-revise"; desc="Perform creative revision on narrative drafts: structural editing, voice, and lore consistency."; tags="narrative, demiurgos, writing" },
    @{ file="narrative-verify.md"; name="narrative-verify"; desc="Verify narrative draft against specs: canon, continuity, and consistency gate."; tags="narrative, demiurgos, validation" },
    @{ file="narrative-archive.md"; name="narrative-archive"; desc="Close a narrative arc: update CHANGELOG, preserve canon discoveries."; tags="narrative, demiurgos, archive" },
    @{ file="narrative-idea.md"; name="narrative-idea"; desc="Manage Banco de Ideas: capture, browse, search, sync, and promote narrative ideas."; tags="narrative, demiurgos, ideas" }
)

Write-Host "Migrando 13 skills narrativos a formato Hermes SKILL.md..."
$Migrados = 0
$Errores = 0

foreach ($Skill in $Skills) {
    $SourceFile = Join-Path $SourceDir $Skill.file
    $TargetDir = Join-Path $TargetBase $Skill.name
    $TargetFile = Join-Path $TargetDir "SKILL.md"

    if (-not (Test-Path -LiteralPath $SourceFile)) {
        Write-Host "  ERROR: $($Skill.file) no existe" -ForegroundColor Red
        $Errores++
        continue
    }

    $Body = Get-Content -LiteralPath $SourceFile -Raw -Encoding UTF8

    $Frontmatter = "---`nname: $($Skill.name)`ndescription: `"$($Skill.desc)`"`nversion: 1.0.0`nplatforms: [windows, macos, linux]`nauthor: Demiurgos`nmetadata:`n  hermes:`n    tags: [$($Skill.tags)]`n    category: narrative`n---`n`n"

    if (-not (Test-Path -LiteralPath $TargetDir)) {
        New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
    }

    $FullContent = $Frontmatter + $Body
    $Utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($TargetFile, $FullContent, $Utf8NoBom)

    $Migrados++
    Write-Host "  OK  $($Skill.name)" -ForegroundColor Green
}

Write-Host ""
Write-Host "Migrados: $Migrados / $($Skills.Count)"
Write-Host "Errores: $Errores"

if ($Errores -gt 0) { exit 1 }
exit 0