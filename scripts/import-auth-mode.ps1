# Loads the single non-secret startup setting required by the local API.
# Do not replace this with a bulk .env import: the file may contain secrets.

function Set-DemiurgosAuthModeFromDotEnv {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    $envPath = Join-Path -Path $ProjectRoot -ChildPath ".env"
    $mode = $null
    $invalidValue = $false

    if (Test-Path -LiteralPath $envPath -PathType Leaf) {
        $reader = [System.IO.File]::OpenText($envPath)
        try {
            while ($null -ne ($line = $reader.ReadLine())) {
                if ($line -notmatch '^\s*DEMIURGOS_AUTH_MODE\s*=\s*(?<value>.*?)\s*$') {
                    continue
                }

                $candidate = $Matches["value"].Trim()
                if ($candidate.Length -ge 2) {
                    $first = $candidate.Substring(0, 1)
                    $last = $candidate.Substring($candidate.Length - 1, 1)
                    if (($first -eq '"' -and $last -eq '"') -or
                        ($first -eq "'" -and $last -eq "'")) {
                        $candidate = $candidate.Substring(1, $candidate.Length - 2)
                    }
                }

                if ($candidate -in @("local-dev", "disabled")) {
                    $mode = $candidate
                } else {
                    $invalidValue = $true
                }
                break
            }
        } finally {
            $reader.Dispose()
        }
    }

    if ($null -eq $mode) {
        # Missing or invalid configuration must preserve the API fail-closed default,
        # including when the launcher inherited a stale value from its parent shell.
        Remove-Item Env:DEMIURGOS_AUTH_MODE -ErrorAction SilentlyContinue
        if ($invalidValue) {
            Write-Warning "Ignoring unsupported DEMIURGOS_AUTH_MODE; API auth remains disabled."
        }
        return "disabled"
    }

    $env:DEMIURGOS_AUTH_MODE = $mode
    return $mode
}
