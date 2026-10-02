# ---------------------------------------------------------------------------
# Demiurgos shared checksum verifier for Windows (design S3-2 / task 5.2).
# PS 5.1 parity of scripts/lib/verify_checksum.sh.
#
# Verification order - NEVER system Python:
#   1. Get-FileHash          (native PowerShell 4+/5.1, always present)
#   2. certutil -hashfile    (legacy Windows tool, ships with every Windows)
#   3. bundled-Python hashlib via `uv run python -c` (the installer's own
#      verified uv; UV_BIN env override for hermetic tests)
#
# The library is dot-sourced by scripts/install-demiurgos.ps1 and also usable
# standalone:  powershell.exe -NoProfile -File verify_checksum.ps1 <file>
#              <expected-sha256>
# Exit codes: 0 = match, 1 = mismatch or unusable, 2 = usage error.
#
# ASCII-only on purpose: Windows PowerShell 5.1 mis-decodes BOM-less UTF-8.
# ---------------------------------------------------------------------------

function Verify-Sha256 {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string]$Expected
    )
    $actual = ""
    try {
        $actual = (Get-FileHash -LiteralPath $FilePath -Algorithm SHA256 -ErrorAction Stop).Hash
    } catch {
        $actual = ""
    }
    if (-not $actual) {
        $certutilCmd = Get-Command certutil -ErrorAction SilentlyContinue
        if ($certutilCmd) {
            $lines = @(& $certutilCmd.Source -hashfile $FilePath SHA256 2>$null)
            if ($lines.Count -ge 2) { $actual = ($lines[1]).Trim() }
        }
    }
    if (-not $actual) {
        # Bundled-Python hashlib via the installer's verified uv - the last
        # resort. Never a system Python.
        $uvBin = if ($env:UV_BIN) { $env:UV_BIN } else { "uv" }
        $actual = (& $uvBin run python -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' $FilePath 2>$null)
    }
    if (-not $actual) {
        Write-Host "verify_checksum: no verifier produced a hash for $FilePath"
        return $false
    }
    if ($actual.Trim().ToLowerInvariant() -eq $Expected.Trim().ToLowerInvariant()) {
        return $true
    }
    Write-Host "verify_checksum: MISMATCH for $FilePath"
    Write-Host "  expected: $Expected"
    Write-Host ("  actual:   " + $actual.Trim())
    return $false
}

if ($MyInvocation.InvocationName -ne ".") {
    # Standalone CLI: positional <file> <expected-sha256>.
    if ($args.Count -ne 2) {
        Write-Host "usage: verify_checksum.ps1 <file> <expected-sha256>"
        exit 2
    }
    if (Verify-Sha256 -FilePath $args[0] -Expected $args[1]) {
        exit 0
    }
    exit 1
}