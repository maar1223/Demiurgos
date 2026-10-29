# -*- coding: utf-8 -*-
"""Windows desktop integration: Start Menu automatic, Desktop icon opt-in.

Parity with ``test_launcher_desktop_integration.py`` (the POSIX half). The
Windows rule has a single owner, ``scripts/lib/desktop-shortcut.ps1``, which
both callers dot-source:

- ``scripts/install-demiurgos.ps1`` writes the Start Menu entry (standard
  installer behavior, never fatal);
- ``start-demiurgos.ps1 install [-Desktop]`` is the explicit repair/opt-in
  path and the only writer of the visible Desktop icon.

A Windows shortcut cannot point at a ``.ps1`` (it opens Notepad) and a
default execution policy would block the launcher, so the ``.lnk`` targets
``powershell.exe`` with ``-ExecutionPolicy Bypass``. The icon must be a real
``.ico``: ``WScript.Shell`` does not accept the SVG the Linux entry uses.

The text assertions run everywhere; the behavioural one is Windows-only.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo

SHORTCUT_LIB = REPO_ROOT / "scripts" / "lib" / "desktop-shortcut.ps1"
PS_LAUNCHER = REPO_ROOT / "start-demiurgos.ps1"
PS_INSTALLER = REPO_ROOT / "scripts" / "install-demiurgos.ps1"
ICON = (
    REPO_ROOT
    / "docs"
    / "Logos-Demiurgos"
    / "dorado"
    / "03_ico_dorado"
    / "demiurgos.ico"
)
RELEASE_WF = REPO_ROOT / ".github" / "workflows" / "release.yml"
CI_WF = REPO_ROOT / ".github" / "workflows" / "ci.yml"

LIB_REL = "scripts/lib/desktop-shortcut.ps1"
ICON_REL = "docs/Logos-Demiurgos/dorado/03_ico_dorado/demiurgos.ico"

_NEEDS_WINDOWS = pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows-only: needs powershell.exe and WScript.Shell",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Packaging: both new artifacts must ship, or the feature is dead on arrival
# ---------------------------------------------------------------------------


def test_shortcut_helper_and_icon_exist():
    assert SHORTCUT_LIB.is_file()
    assert ICON.is_file()


def test_release_ships_the_helper_and_the_icon_in_both_jobs():
    text = _text(RELEASE_WF)
    # POSIX extras + POSIX allow-list + Windows extras + Windows allow-list.
    assert text.count(LIB_REL) == 4
    assert text.count(ICON_REL) == 4


def test_ci_parses_the_helper_under_powershell_51():
    text = _text(CI_WF)
    assert LIB_REL in text
    assert "Desktop shortcut contract (real .lnk on Windows)" in text


def test_ci_exercises_a_real_shortcut_and_reads_it_back():
    """A parse check cannot prove a .lnk works; the runner reads it back."""
    text = _text(CI_WF)
    assert "CreateShortcut" in text
    assert "the desktop icon must stay opt-in" in text
    assert "demiurgos.ico" in text


# ---------------------------------------------------------------------------
# The icon is a real multi-size .ico (WScript.Shell cannot use the SVG)
# ---------------------------------------------------------------------------


def test_icon_is_a_valid_multisize_ico():
    data = ICON.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert reserved == 0 and kind == 1, "not an .ico container"
    # 16/24/32/48/64/128/256: small sizes matter for the taskbar and menus.
    assert count >= 5
    assert 10_000 < len(data) < 500_000, "an .ico this small/large is suspect"


# ---------------------------------------------------------------------------
# Single owner: the helper holds the rule
# ---------------------------------------------------------------------------


def test_helper_sets_the_full_shortcut_contract():
    text = _text(SHORTCUT_LIB)
    assert "WScript.Shell" in text
    assert "CreateShortcut" in text
    assert ".Save()" in text
    assert ".TargetPath" in text and ".Arguments" in text
    assert ".WorkingDirectory" in text and ".Description" in text


def test_helper_targets_powershell_51_not_the_script_file():
    """A .lnk to a .ps1 opens Notepad and the policy blocks the launcher."""
    text = _text(SHORTCUT_LIB)
    assert "WindowsPowerShell\\v1.0\\powershell.exe" in text
    assert "-ExecutionPolicy Bypass" in text
    assert '-File `"$launcher`" start' in text


def test_helper_sets_the_icon_with_index_zero():
    text = _text(SHORTCUT_LIB)
    assert "03_ico_dorado" in text
    # IconLocation is "path,index"; without the index Windows shows a blank.
    assert '.IconLocation = "$icon,0"' in text


def test_helper_keeps_the_desktop_icon_opt_in():
    text = _text(SHORTCUT_LIB)
    body = text[text.index("function Install-DemiurgosShortcuts"):]
    guard = body.index("if ($Desktop)")
    desktop_write = body.index(
        "New-DemiurgosShortcut -AppRoot $AppRoot -Directory $DesktopDirectory"
    )
    start_menu_write = body.index(
        "New-DemiurgosShortcut -AppRoot $AppRoot -Directory $ProgramsDirectory"
    )
    # The Start Menu entry is unconditional; the Desktop write is guarded.
    assert start_menu_write < guard < desktop_write


def test_helper_resolves_folders_through_the_shell():
    """OneDrive Known Folder Move and localized names must be followed."""
    text = _text(SHORTCUT_LIB)
    assert "[Environment]::GetFolderPath($Folder)" in text
    assert "'Programs'" in text and "'Desktop'" in text


def test_helper_is_ascii_only():
    """PS 5.1 mis-decodes BOM-less UTF-8; every shipped .ps1 is ASCII."""
    raw = SHORTCUT_LIB.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "must not carry a BOM"
    raw.decode("ascii")


# ---------------------------------------------------------------------------
# Callers
# ---------------------------------------------------------------------------


def test_launcher_offers_the_install_action_with_an_opt_in_desktop_switch():
    text = _text(PS_LAUNCHER)
    assert '[ValidateSet("start", "restart", "stop", "install")]' in text
    assert "[switch]$Desktop" in text


def test_launcher_handles_install_before_any_runtime_work():
    """Registering the menu entry must not load the .env, bootstrap a data
    root, warn about Hermes or touch a port."""
    text = _text(PS_LAUNCHER)
    install_branch = text.index('if ($Action -eq "install")')
    assert install_branch < text.index("Load-DataRootEnv")
    assert install_branch < text.index("switch ($Action)")
    assert "Install-DemiurgosShortcuts -AppRoot $appRoot" in text


def test_installer_writes_the_start_menu_entry_and_survives_failure():
    text = _text(PS_INSTALLER)
    assert "Install-DemiurgosShortcuts -AppRoot $appRoot" in text
    block = text[text.index("function Install-StartMenuShortcut"):]
    body = block[: block.index("\n}\n")]
    # Non-fatal: a missing helper or a failed write degrades to a warning.
    assert "Warn " in body
    assert "catch {" in body


def test_installer_repairs_the_entry_on_a_same_version_rerun():
    text = _text(PS_INSTALLER)
    start = text.index("if ($alreadyCurrent) {")
    end = text.index("\n    }\n", start)
    early_exit = text[start:end]
    assert "nothing to do" in early_exit
    assert "Install-StartMenuShortcut" in early_exit


def test_fresh_install_writes_the_entry_after_the_bootstrap():
    """The path a first install takes must write the entry.

    A count-based assertion passed while this was broken: the definition plus
    two call sites can all sit on the wrong paths. Assert the ordering on the
    real main flow.
    """
    text = _text(PS_INSTALLER)
    main = text[text.index("# --- main"):]
    # Anchor on the fresh-install steps, not on the whole main region: the
    # already-current repair path also mentions the call, and before it.
    fresh = main[main.index("Invoke-CommitStaging"):]
    assert "Install-StartMenuShortcut" in fresh, (
        "a fresh install never writes the Start Menu entry"
    )
    assert fresh.index("Invoke-DataRootBootstrap") < fresh.index(
        "Install-StartMenuShortcut"
    )
    # The helper reads the entry template from <install_root>\current, so the
    # commit that creates the junction must precede the write.
    assert (
        fresh.index("Invoke-CommitStaging")
        < fresh.index("Invoke-DataRootBootstrap")
        < fresh.index("Install-StartMenuShortcut")
    )


def test_seed_only_stays_bootstrap_only():
    """The DEMIURGOS_SEED_ONLY seam is documented as bootstrap + .env only."""
    text = _text(PS_INSTALLER)
    seed = text[
        text.index('if ($env:DEMIURGOS_SEED_ONLY -eq "1")') : text.index("# --- main")
    ]
    assert "Install-StartMenuShortcut" not in seed


def test_helper_is_loaded_from_the_installed_app_root():
    text = _text(PS_INSTALLER)
    body = text[text.index("function Install-StartMenuShortcut"):]
    body = body[: body.index("\n}\n")]
    assert 'Join-Path $installRoot "current"' in body
    assert "scripts\\lib\\desktop-shortcut.ps1" in body


def test_ico_embeds_exactly_the_documented_sizes():
    data = ICON.read_bytes()
    count = struct.unpack("<HHH", data[:6])[2]
    sizes = set()
    for index in range(count):
        width, _height = struct.unpack("<BB", data[6 + index * 16 : 8 + index * 16])
        sizes.add(width or 256)  # 0 means 256 in the ICO directory entry
    assert sizes == {16, 24, 32, 48, 64, 128, 256}


# ---------------------------------------------------------------------------
# Behavioural: the real thing, on Windows
# ---------------------------------------------------------------------------


@_NEEDS_WINDOWS
def test_shortcuts_are_really_written_and_read_back(tmp_path):
    programs = tmp_path / "Programs"
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    harness = tmp_path / "harness.ps1"
    harness.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        f". '{SHORTCUT_LIB}'\n"
        f"$entries = Install-DemiurgosShortcuts -AppRoot '{REPO_ROOT}' -Desktop "
        f"-ProgramsDirectory '{programs}' -DesktopDirectory '{desktop}'\n"
        "foreach ($e in $entries) { Write-Output (\"WROTE=\" + $e) }\n"
        "$shell = New-Object -ComObject WScript.Shell\n"
        f"$sc = $shell.CreateShortcut('{desktop}\\Demiurgos.lnk')\n"
        "Write-Output (\"TARGET=\" + $sc.TargetPath)\n"
        "Write-Output (\"ARGS=\" + $sc.Arguments)\n"
        "Write-Output (\"ICON=\" + $sc.IconLocation)\n",
        encoding="ascii",
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr + result.stdout

    assert (programs / "Demiurgos.lnk").is_file()
    assert (desktop / "Demiurgos.lnk").is_file()
    assert "TARGET=" in result.stdout and "powershell.exe" in result.stdout.lower()
    assert "ARGS=" in result.stdout and "-ExecutionPolicy Bypass" in result.stdout
    assert "ICON=" in result.stdout and "demiurgos.ico" in result.stdout


@_NEEDS_WINDOWS
def test_start_menu_only_by_default(tmp_path):
    programs = tmp_path / "Programs"
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    harness = tmp_path / "harness.ps1"
    harness.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        f". '{SHORTCUT_LIB}'\n"
        f"$entries = Install-DemiurgosShortcuts -AppRoot '{REPO_ROOT}' "
        f"-ProgramsDirectory '{programs}' -DesktopDirectory '{desktop}'\n"
        "Write-Output (\"COUNT=\" + @($entries).Count)\n",
        encoding="ascii",
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "COUNT=1" in result.stdout
    assert (programs / "Demiurgos.lnk").is_file()
    assert not (desktop / "Demiurgos.lnk").exists()
