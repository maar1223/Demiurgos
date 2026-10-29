# ---------------------------------------------------------------------------
# Demiurgos Windows shortcut helper (Windows PowerShell 5.1).
#
# One owner for the desktop-integration rule on Windows: where the shortcuts
# live, what they point at, and which of them is opt-in. Both callers dot-
# source this file instead of re-deriving the paths:
#   - scripts/install-demiurgos.ps1 writes the Start Menu entry, automatic
#     (parity with the Linux applications-menu entry);
#   - start-demiurgos.ps1 install [-Desktop] is the explicit repair/opt-in
#     path, and the only writer of the visible Desktop icon.
#
# Shortcuts target powershell.exe with -ExecutionPolicy Bypass rather than the
# .ps1 file itself: a .lnk pointing at a .ps1 opens Notepad on a default
# install, and the execution policy would block the launcher otherwise.
#
# ASCII-only on purpose: Windows PowerShell 5.1 mis-decodes BOM-less UTF-8.
# ---------------------------------------------------------------------------

function Get-DemiurgosShellFolder {
    # The shell's own resolution for a known folder, never a literal path: it
    # follows a redirection (OneDrive Known Folder Move) and the user's
    # localized folder name. Pure .NET, no extra module (parity with
    # Get-DocumentsDir in the launcher and the installer).
    param(
        [Parameter(Mandatory = $true)][string]$Folder,
        [Parameter(Mandatory = $true)][string]$Fallback
    )
    $path = [Environment]::GetFolderPath($Folder)
    if ([string]::IsNullOrWhiteSpace($path)) { $path = $Fallback }
    return $path
}

function Get-DemiurgosLauncherPath {
    # Installed layout: <current>\start-demiurgos.ps1 (the release extras copy
    # it to the app root). The scripts\ form is accepted for a layout that
    # keeps it there.
    param([Parameter(Mandatory = $true)][string]$AppRoot)
    $candidates = @(
        (Join-Path $AppRoot "start-demiurgos.ps1"),
        (Join-Path $AppRoot "scripts\start-demiurgos.ps1")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return $candidates[0]
}

function Get-DemiurgosIconPath {
    param([Parameter(Mandatory = $true)][string]$AppRoot)
    return (Join-Path $AppRoot "docs\Logos-Demiurgos\dorado\03_ico_dorado\demiurgos.ico")
}

function Get-DemiurgosPowerShellPath {
    # Always the 5.1 host the launcher is written for, even when this helper
    # runs under a newer PowerShell that happened to load it.
    $path = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $path = Join-Path $PSHOME "powershell.exe"
    }
    return $path
}

function New-DemiurgosShortcut {
    # Write ONE .lnk and return its path. Throws on failure, so the caller
    # decides whether that is fatal (the installer warns; `install` fails).
    param(
        [Parameter(Mandatory = $true)][string]$AppRoot,
        [Parameter(Mandatory = $true)][string]$Directory,
        [string]$Name = "Demiurgos"
    )
    $launcher = Get-DemiurgosLauncherPath -AppRoot $AppRoot
    if (-not (Test-Path -LiteralPath $Directory -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $Directory | Out-Null
    }
    $shortcutPath = Join-Path $Directory "$Name.lnk"
    $shell = New-Object -ComObject WScript.Shell
    try {
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = Get-DemiurgosPowerShellPath
        $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$launcher`" start"
        $shortcut.WorkingDirectory = $AppRoot
        $shortcut.Description = "Demiurgos"
        $icon = Get-DemiurgosIconPath -AppRoot $AppRoot
        if (Test-Path -LiteralPath $icon -PathType Leaf) {
            # IconLocation is "path,index"; index 0 is the first image.
            $shortcut.IconLocation = "$icon,0"
        }
        $shortcut.Save()
    } finally {
        # Release the COM object deterministically: a leaked RCW keeps the
        # .lnk handle busy on some Windows builds.
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
    }
    return $shortcutPath
}

function Install-DemiurgosShortcuts {
    # The Start Menu entry is written always: that is standard installer
    # behavior and the parity of the Linux applications-menu entry. The
    # visible Desktop icon is written ONLY with -Desktop, because a shortcut
    # dropped in the user's own Desktop folder behind their back is intrusive.
    #
    # -ProgramsDirectory / -DesktopDirectory are a hermetic-test seam; the
    # defaults come from the shell's own known folders.
    param(
        [Parameter(Mandatory = $true)][string]$AppRoot,
        [switch]$Desktop,
        [string]$ProgramsDirectory,
        [string]$DesktopDirectory
    )
    if (-not $ProgramsDirectory) {
        $ProgramsDirectory = Get-DemiurgosShellFolder -Folder 'Programs' `
            -Fallback (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs")
    }
    if (-not $DesktopDirectory) {
        $DesktopDirectory = Get-DemiurgosShellFolder -Folder 'Desktop' `
            -Fallback (Join-Path $env:USERPROFILE "Desktop")
    }

    $written = New-Object System.Collections.Generic.List[string]
    $written.Add((New-DemiurgosShortcut -AppRoot $AppRoot -Directory $ProgramsDirectory))

    if ($Desktop) {
        if (Test-Path -LiteralPath $DesktopDirectory -PathType Container) {
            $written.Add((New-DemiurgosShortcut -AppRoot $AppRoot -Directory $DesktopDirectory))
        } else {
            Write-Host "Desktop folder not found ($DesktopDirectory); skipped the desktop icon." -ForegroundColor Yellow
        }
    }
    return $written.ToArray()
}
