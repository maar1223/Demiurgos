# payload_audit.ps1 - default-DENY payload audit (design v2 S5-3 / tasks 8.1-8.2)
#
# Windows parity of scripts/payload_audit.sh: the release packaging gate for
# the Windows package cell. Only the files named by payload_manifest.json (the
# derived allow-list, S0-D / PR 0) may ship, plus the explicit packaging extras
# passed via -Allow. Every other file in the audited tree is denied, and each
# allowed file is additionally content-scanned with the SAME rules as
# scripts/secret_scan.sh (the single source of truth on POSIX; the parity test
# test_payload_audit.py asserts the rule and deny lists cannot diverge).
#
# Explicit DENY additions (fail the audit wherever they appear):
#   config/idea-capture.yaml  config/hermes-mcp-profile.yaml.example
#   docs/MARCA.md  src/tools/dev_diary.py  engram-export.json
#   .env  .env.backup  .secrets/  mundos/  .git/
#   src/tools/opencode-bridge.py  start-opencode-*.ps1  sync-ideas.py.bak-*
#
# -Allow FILE (task 8.5): extra shippable paths beyond the manifest - the
# explicit artifact extras (bootstraps, cores, launchers, requirements,
# LICENSE) and the shared dist tree. One path per line; '#' comments and blank
# lines allowed; an entry ending in '/' allows everything under that prefix
# (the content-hashed frontend/dist tree). Deny rules still win over -Allow.
#
# -ContentScanSkip PREFIX (S5b): files under the prefix are still path-checked
# (deny / manifest / allow) but are NOT content-scanned. Used for the derived
# frontend/dist tree: a BUILT artifact whose sources (frontend/src) are covered
# by the tree scan and whose baked origins are guarded by the S1-7 same-origin
# check; minified CSS/JS utility names (e.g. Tailwind/xyflow "sk-*" classes)
# false-positive the openai-key heuristic. No rule is weakened - only the
# scanned file set is scoped. Repeatable.
#
# Output: one "deny: <path> (<reason>)" line per denied path, plus one
# "<path>:<line>: <rule-name>" line per content-scan hit. Matched values are
# NEVER printed.
#
# Exit codes: 0 = clean, 1 = deny or content-scan finding, 2 = usage/manifest
# error. Run with powershell.exe -NoProfile -File (PS 5.1) or pwsh.
# ASCII-only on purpose: Windows PowerShell 5.1 mis-decodes BOM-less UTF-8.

param(
    [string]$Root,          # tree to audit (default: the repository root)
    [string]$Manifest,      # payload allow-list JSON (default: <root>\payload_manifest.json)
    [string]$Allow,         # extra shippable paths file (one per line)
    [string[]]$ContentScanSkip,  # prefixes excluded from the content scan only
    [switch]$WalkFs,        # force a full filesystem walk (default with -Root)
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

if ($Help) {
    Write-Host @'
Usage: powershell.exe -NoProfile -File payload_audit.ps1 [-Root DIR] [-Manifest FILE] [-Allow FILE] [-ContentScanSkip PREFIX] [-WalkFs]

  -Root DIR            tree to audit (default: the repository root)
  -Manifest FILE       payload allow-list JSON (default: <root>\payload_manifest.json)
  -Allow FILE          extra shippable paths (one per line; trailing '/' allows a
                       whole prefix; '#' comments allowed)
  -ContentScanSkip PREFIX
                       path-check files under PREFIX but do NOT content-scan them
                       (the derived frontend/dist tree; repeatable)
  -WalkFs              force a full filesystem walk
  -Help                show this help

Exit codes: 0 clean, 1 findings, 2 usage/manifest error.
'@
    exit 0
}

# --- explicit deny lists (parity with payload_audit.sh) ----------------------
$denyExact = @(
    'config/idea-capture.yaml',
    'config/hermes-mcp-profile.yaml.example',
    'docs/MARCA.md',
    'src/tools/dev_diary.py',
    'src/tools/opencode-bridge.py',
    'engram-export.json',
    '.env',
    '.env.backup'
)
$denyDirs  = @('.secrets', 'mundos', '.git')
$denyGlobs = @('start-opencode-*.ps1', 'sync-ideas.py.bak-*')

# --- content-scan rules (parity with scripts/secret_scan.sh RULES_SRC) -------
# Single-quoted so the pattern bytes match the bash source exactly; the parity
# test asserts every rule name and pattern below appears in both files.
$rules = @(
    @{ Name = 'bot-token';      Pattern = '[0-9]{8,10}:[A-Za-z0-9_-]{35}' },
    @{ Name = 'openai-key';     Pattern = 'sk-[A-Za-z0-9_-]{20,}' },
    @{ Name = 'google-api-key'; Pattern = 'AIza[0-9A-Za-z_-]{35}' },
    @{ Name = 'author-path';    Pattern = 'H:\\|/home/|C:\\Users|spreadsheetId' }
)

function Test-DenyExact([string]$rel) {
    foreach ($entry in $denyExact) {
        if ($rel -eq $entry -or $rel.EndsWith('/' + $entry)) { return $true }
    }
    return $false
}

function Test-DenyDir([string]$rel) {
    foreach ($dir in $denyDirs) {
        if ($rel -eq $dir -or $rel.StartsWith($dir + '/')) { return $true }
    }
    return $false
}

function Test-DenyGlob([string]$rel) {
    $base = Split-Path -Leaf $rel
    foreach ($glob in $denyGlobs) {
        if ($base -like $glob) { return $true }
    }
    return $false
}

function Test-Allowed([string]$rel) {
    if ($payload -contains $rel) { return $true }
    foreach ($entry in $allowEntries) {
        if ($entry.EndsWith('/')) {
            if ($rel.StartsWith($entry)) { return $true }
        } elseif ($rel -eq $entry -or $rel.EndsWith('/' + $entry)) {
            return $true
        }
    }
    return $false
}

function Invoke-ContentScan([string]$root, [string[]]$allowed) {
    foreach ($rel in $allowed) {
        $skipped = $false
        foreach ($prefix in $ContentScanSkip) {
            if ($rel.StartsWith($prefix)) { $skipped = $true; break }
        }
        if ($skipped) { continue }  # path-checked only (derived dist tree)
        $file = Join-Path $root $rel
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { continue }
        foreach ($rule in $rules) {
            try {
                $hits = Select-String -LiteralPath $file -Pattern $rule.Pattern -AllMatches
            } catch {
                continue  # binary/unreadable file: skip (POSIX grep parity)
            }
            foreach ($h in $hits) {
                # NEVER the matched value: path:line: rule-name only.
                Write-Output ("{0}:{1}: {2}" -f $rel, $h.LineNumber, $rule.Name)
                $script:findings++
            }
        }
    }
}

# --- resolve root and manifest defaults ---------------------------------------
if (-not $Root) {
    $Root = Split-Path -Parent $PSScriptRoot
}
if (-not $Manifest) {
    $Manifest = Join-Path $Root 'payload_manifest.json'
}
if (-not (Test-Path -LiteralPath $Manifest -PathType Leaf)) {
    Write-Host "payload_audit: manifest not found: $Manifest" -ForegroundColor Red
    Write-Host 'payload_audit: derive it with scripts/derive_payload_manifest.py (S0-D)' -ForegroundColor Red
    exit 2
}
$data = Get-Content -Raw -LiteralPath $Manifest | ConvertFrom-Json
$payload = @($data.payload)

# --- load the extra shippable paths -------------------------------------------
$allowEntries = @()
if ($Allow) {
    if (-not (Test-Path -LiteralPath $Allow -PathType Leaf)) {
        Write-Host "payload_audit: cannot read allow file: $Allow" -ForegroundColor Red
        exit 2
    }
    foreach ($line in Get-Content -LiteralPath $Allow) {
        $trimmed = $line.Trim()
        if ($trimmed -eq '' -or $trimmed.StartsWith('#')) { continue }
        $allowEntries += $trimmed
    }
}

# --- candidate enumeration -----------------------------------------------------
# -Root given or no git repo at root: full filesystem walk (a packaging/staging
# tree or a test fixture; catches any .git/ that landed in the tree).
# -WalkFs: force the walk. Otherwise: git-tracked surface (repo-root semantics).
$candidates = @()
if ($WalkFs -or $Root -or -not (Test-Path -LiteralPath (Join-Path $Root '.git'))) {
    $prefix = $Root
    if (-not $prefix.EndsWith('/') -and -not $prefix.EndsWith('\')) {
        $prefix = $prefix + '/'
    }
    $candidates = @(Get-ChildItem -LiteralPath $Root -Recurse -File -ErrorAction SilentlyContinue |
        ForEach-Object { $_.FullName.Substring($prefix.Length).Replace('\', '/') })
} else {
    $candidates = @(& git -C $Root ls-files -co --exclude-standard)
}

# --- default-DENY decision + content scan --------------------------------------
$denyCount = 0
$script:findings = 0
$allowedList = @()
foreach ($rel in $candidates) {
    $rel = $rel.TrimStart('./')
    $reason = ''
    if (Test-DenyExact $rel) { $reason = 'explicit deny path' }
    elseif (Test-DenyDir $rel) { $reason = 'explicit deny directory' }
    elseif (Test-DenyGlob $rel) { $reason = 'explicit deny glob' }
    elseif (-not (Test-Allowed $rel)) { $reason = 'not in manifest allow-list' }
    if ($reason) {
        Write-Output ("deny: {0} ({1})" -f $rel, $reason)
        $denyCount++
    } else {
        $allowedList += $rel
    }
}

if ($allowedList.Count -gt 0) {
    Invoke-ContentScan $Root $allowedList
}

if ($denyCount -gt 0 -or $script:findings -gt 0) {
    Write-Host ("payload_audit: {0} deny findings, {1} content-scan hits" -f $denyCount, $script:findings) -ForegroundColor Red
    exit 1
}
Write-Host ("payload_audit: clean ({0} files allowed, no findings)" -f $allowedList.Count) -ForegroundColor Green
exit 0