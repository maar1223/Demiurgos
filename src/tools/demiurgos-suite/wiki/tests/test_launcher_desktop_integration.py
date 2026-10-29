# -*- coding: utf-8 -*-
"""Desktop integration contract: menu entry automatic, Desktop icon opt-in.

Two separate contracts, deliberately not one:

- the **applications-menu** entry is standard installer behavior. The
  installer writes it on Linux from the shipped template, read as DATA — the
  installer never executes payload files (``test_installer_never_executes_
  payload_files``), so it may not call ``start-demiurgos.sh install``.
- the visible **Desktop icon** is the user's own space: it is only written on
  explicit request (``start-demiurgos.sh install --desktop``). A copied-down
  ``.desktop`` shows up as an "Untrusted application launcher" on
  GNOME/Nautilus until it is marked ``metadata::trusted``, so creating it
  behind the user's back looks broken instead of helpful.

Both locations follow the freedesktop contract: a localized desktop keeps its
folder in ``user-dirs.dirs`` (``~/Escritorio``, ``~/Documenti``, ...), so the
literal ``~/Desktop`` would miss the folder the user actually sees — the same
bug ``documents_dir`` already avoids for author content.

Every behavioural test is hermetic: HOME, XDG_CONFIG_HOME and XDG_DATA_HOME
point into ``tmp_path``, so no real menu entry, desktop icon or user config is
read or written.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo

PORTABLE_LAUNCHER = REPO_ROOT / "scripts" / "start-demiurgos.sh"
INSTALLER = REPO_ROOT / "scripts" / "install-demiurgos.sh"
RELEASE_WF = REPO_ROOT / ".github" / "workflows" / "release.yml"
DESKTOP_TEMPLATE = REPO_ROOT / "desktop" / "Demiurgos.desktop"
ICON = (
    REPO_ROOT
    / "docs"
    / "Logos-Demiurgos"
    / "dorado"
    / "01_svg_dorado"
    / "letra-D-6tonos.svg"
)

MENU_NAME = "Demiurgos.desktop"

_POSIX_BASH = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="POSIX-bash probe: on Windows a bare `bash` is the WSL stub",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _env(tmp_path: Path) -> dict[str, str]:
    """Hermetic HOME + XDG roots: every write lands under tmp_path."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    return {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(config),
        "XDG_DATA_HOME": str(data),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }


def _write_user_dirs(tmp_path: Path, *lines: str) -> None:
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "user-dirs.dirs").write_text(
        "".join(f"{line}\n" for line in lines), encoding="utf-8"
    )


def _probe(tmp_path: Path, script: str) -> subprocess.CompletedProcess[str]:
    """Source the real launcher and run `script` inside it (no side effects)."""
    return subprocess.run(
        ["bash", "-c", script, "bash", str(PORTABLE_LAUNCHER)],
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(tmp_path),
    )


def _run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Execute the real launcher (main runs, unlike the sourcing probe)."""
    return subprocess.run(
        ["bash", str(PORTABLE_LAUNCHER), *args],
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(tmp_path),
    )


# ---------------------------------------------------------------------------
# freedesktop resolution for the Desktop folder
# ---------------------------------------------------------------------------


@_POSIX_BASH
def test_desktop_dir_follows_the_localized_xdg_folder(tmp_path):
    """A Spanish desktop names it ~/Escritorio; never a second, English one."""
    _write_user_dirs(tmp_path, 'XDG_DESKTOP_DIR="$HOME/Escritorio"')
    result = _probe(tmp_path, 'source "$1" __probe__; desktop_dir')
    assert result.returncode == 0, result.stderr
    assert result.stdout.rstrip("\n") == str(tmp_path / "home" / "Escritorio")


@_POSIX_BASH
def test_desktop_dir_falls_back_to_english_when_xdg_is_silent(tmp_path):
    _write_user_dirs(tmp_path, 'XDG_DOCUMENTS_DIR="$HOME/Documentos"')
    result = _probe(tmp_path, 'source "$1" __probe__; desktop_dir')
    assert result.returncode == 0, result.stderr
    assert result.stdout.rstrip("\n") == str(tmp_path / "home" / "Desktop")


@_POSIX_BASH
def test_each_xdg_user_dir_reads_its_own_key(tmp_path):
    """Guard against wiring the shared resolver to the wrong key."""
    _write_user_dirs(
        tmp_path,
        'XDG_DOCUMENTS_DIR="$HOME/Documentos"',
        'XDG_DESKTOP_DIR="$HOME/Escritorio"',
    )
    result = _probe(
        tmp_path,
        'source "$1" __probe__; printf "%s|%s" "$(documents_dir)" "$(desktop_dir)"',
    )
    assert result.returncode == 0, result.stderr
    documents, desktop = result.stdout.split("|")
    assert documents == str(tmp_path / "home" / "Documentos")
    assert desktop == str(tmp_path / "home" / "Escritorio")


# ---------------------------------------------------------------------------
# `install` = menu entry; `install --desktop` = menu entry + Desktop icon
# ---------------------------------------------------------------------------


@_POSIX_BASH
def test_install_writes_the_menu_entry_and_no_desktop_icon(tmp_path):
    """The menu entry is standard; the Desktop stays untouched without the flag."""
    (tmp_path / "home" / "Escritorio").mkdir(parents=True, exist_ok=True)
    _write_user_dirs(tmp_path, 'XDG_DESKTOP_DIR="$HOME/Escritorio"')

    result = _run_cli(tmp_path, "install")
    assert result.returncode == 0, result.stderr

    menu = tmp_path / "data" / "applications" / MENU_NAME
    assert menu.is_file(), result.stdout + result.stderr
    assert stat.S_IMODE(menu.stat().st_mode) == 0o644
    # The placeholder is substituted so the entry survives moves and upgrades.
    entry = menu.read_text(encoding="utf-8")
    assert "@PROJECT_ROOT@" not in entry
    exec_line = next(ln for ln in entry.splitlines() if ln.startswith("Exec="))
    assert exec_line.endswith("/scripts/start-demiurgos.sh start")
    assert not (tmp_path / "home" / "Escritorio" / MENU_NAME).exists()


@_POSIX_BASH
def test_install_desktop_writes_the_icon_into_the_localized_folder(tmp_path):
    desktop = tmp_path / "home" / "Escritorio"
    desktop.mkdir(parents=True, exist_ok=True)
    _write_user_dirs(tmp_path, 'XDG_DESKTOP_DIR="$HOME/Escritorio"')

    result = _run_cli(tmp_path, "install", "--desktop")
    assert result.returncode == 0, result.stderr

    menu = tmp_path / "data" / "applications" / MENU_NAME
    icon = desktop / MENU_NAME
    assert menu.is_file()
    assert icon.is_file(), result.stdout + result.stderr
    assert stat.S_IMODE(icon.stat().st_mode) == 0o755
    assert icon.read_text(encoding="utf-8") == menu.read_text(encoding="utf-8")
    # Never the literal ~/Desktop alongside the localized folder.
    assert not (tmp_path / "home" / "Desktop").exists()


@_POSIX_BASH
def test_install_desktop_skips_the_icon_without_failing_when_folder_is_missing(tmp_path):
    _write_user_dirs(tmp_path, 'XDG_DESKTOP_DIR="$HOME/NoExiste"')

    result = _run_cli(tmp_path, "install", "--desktop")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "data" / "applications" / MENU_NAME).is_file()
    assert "NoExiste" in result.stderr


@_POSIX_BASH
def test_install_desktop_skips_the_icon_when_the_folder_is_read_only(tmp_path):
    """An unwritable Desktop must not fail `install`: the menu entry is enough."""
    if os.geteuid() == 0:
        pytest.skip("root ignores directory permissions")
    desktop = tmp_path / "home" / "Escritorio"
    desktop.mkdir(parents=True, exist_ok=True)
    _write_user_dirs(tmp_path, 'XDG_DESKTOP_DIR="$HOME/Escritorio"')
    desktop.chmod(0o555)
    try:
        result = _run_cli(tmp_path, "install", "--desktop")
    finally:
        desktop.chmod(0o755)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "data" / "applications" / MENU_NAME).is_file()
    assert not (desktop / MENU_NAME).exists()
    assert "skipped the desktop icon" in result.stderr


@_POSIX_BASH
def test_usage_documents_the_desktop_flag(tmp_path):
    result = _run_cli(tmp_path, "__not_an_action__")
    assert result.returncode == 2
    assert "--desktop" in result.stderr


@_POSIX_BASH
def test_desktop_dir_falls_back_when_user_dirs_is_unreadable(tmp_path):
    _write_user_dirs(tmp_path, 'XDG_DESKTOP_DIR="$HOME/Escritorio"')
    user_dirs = tmp_path / "config" / "user-dirs.dirs"
    user_dirs.chmod(0)
    try:
        unreadable = not os.access(user_dirs, os.R_OK)
        result = _probe(tmp_path, 'source "$1" __probe__; desktop_dir')
    finally:
        user_dirs.chmod(0o644)
    if unreadable:  # root ignores mode bits; assert only where the read failed
        assert result.returncode == 0, result.stderr
        assert result.stdout.rstrip("\n") == str(tmp_path / "home" / "Desktop")


@_POSIX_BASH
def test_install_falls_back_to_local_share_without_xdg_data_home(tmp_path):
    env = _env(tmp_path)
    env.pop("XDG_DATA_HOME")
    result = subprocess.run(
        ["bash", str(PORTABLE_LAUNCHER), "install"],
        env=env, capture_output=True, text=True, timeout=60, cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "home" / ".local" / "share" / "applications" / MENU_NAME).is_file()


@_POSIX_BASH
def test_install_is_idempotent(tmp_path):
    desktop = tmp_path / "home" / "Escritorio"
    desktop.mkdir(parents=True, exist_ok=True)
    _write_user_dirs(tmp_path, 'XDG_DESKTOP_DIR="$HOME/Escritorio"')

    def snapshot():
        menu = tmp_path / "data" / "applications" / MENU_NAME
        icon = desktop / MENU_NAME
        return (
            menu.read_bytes(),
            icon.read_bytes(),
            stat.S_IMODE(menu.stat().st_mode),
            stat.S_IMODE(icon.stat().st_mode),
        )

    _run_cli(tmp_path, "install", "--desktop")
    first = snapshot()
    _run_cli(tmp_path, "install", "--desktop")
    assert snapshot() == first


# ---------------------------------------------------------------------------
# The installer writes the menu entry as DATA (never executes payload files)
# ---------------------------------------------------------------------------


def test_installer_writes_the_menu_entry_from_the_shipped_template():
    text = _text(INSTALLER)
    assert "desktop/Demiurgos.desktop" in text
    # The substitution contract is the template's placeholder, byte-identical
    # to the launcher's.
    assert "@PROJECT_ROOT@" in text
    assert "Demiurgos.desktop" in text


def test_installer_menu_entry_is_linux_only():
    text = _text(INSTALLER)
    block = text[text.index("install_desktop_entry()") :]
    guard = block.index('"$OS" = "Linux"')
    write = block.index("Demiurgos.desktop")
    assert guard < write, "the Linux guard must precede the write"


def test_installer_never_runs_the_launcher_to_install_the_entry():
    """Documented threat-matrix decision: the installer never executes
    extracted payload files, so it may not delegate to `start-demiurgos.sh
    install` either — it writes the entry itself."""
    text = _text(INSTALLER)
    assert "start-demiurgos.sh\" install" not in text
    assert "current/scripts/start-demiurgos.sh\" install" not in text


def test_installer_repairs_the_entry_on_a_same_version_rerun():
    """The idempotent early exit must still refresh the menu entry: re-running
    the installer is the user's natural repair action."""
    text = _text(INSTALLER)
    start = text.index("# Idempotent re-run")
    end = text.index("\nfi\n", start) + len("\nfi\n")
    early_exit = text[start:end]
    assert "nothing to do" in early_exit
    assert "install_desktop_entry" in early_exit


def test_installer_keeps_its_hard_constraints():
    """The new block must not introduce the forbidden substrings."""
    text = _text(INSTALLER)
    assert "git" not in text
    assert "npm" not in text
    assert "sudo" not in text


def test_installer_failure_to_write_the_entry_is_not_fatal():
    """A read-only or missing applications dir must not abort an install."""
    text = _text(INSTALLER)
    block = text[text.index("install_desktop_entry()") :]
    body = block[: block.index("\n}\n")]
    assert "||" in body or "warn " in body


def _installer_entry_harness() -> str:
    """The real installer functions, extracted so no full install is needed."""
    text = _text(INSTALLER)

    def grab(name: str) -> str:
        start = text.index(f"{name}() {{")
        end = text.index("\n}\n", start) + len("\n}\n")
        return text[start:end]

    return (
        'DESKTOP_TEMPLATE_REL="desktop/Demiurgos.desktop"\n'
        + grab("applications_dir")
        + "\n"
        + grab("install_desktop_entry")
        + "\ninstall_desktop_entry\n"
    )


def _run_installer_entry(
    tmp_path: Path, os_name: str, *, with_template: bool = True
) -> subprocess.CompletedProcess[str]:
    root = tmp_path / "install"
    if with_template:
        (root / "current" / "desktop").mkdir(parents=True, exist_ok=True)
        (root / "current" / "desktop" / MENU_NAME).write_text(
            "[Desktop Entry]\n"
            "Exec=@PROJECT_ROOT@/scripts/start-demiurgos.sh start\n"
            "Icon=@PROJECT_ROOT@/icon.svg\n",
            encoding="utf-8",
        )
    harness = 'set -u\nwarn() { printf "WARN: %s\\n" "$*" >&2; }\n' + _installer_entry_harness()
    env = _env(tmp_path)
    env["INSTALL_ROOT"] = str(root)
    env["OS"] = os_name
    return subprocess.run(
        ["bash", "-c", harness],
        env=env, capture_output=True, text=True, timeout=30, cwd=str(tmp_path),
    )


@_POSIX_BASH
def test_installer_entry_writes_the_menu_on_linux(tmp_path):
    result = _run_installer_entry(tmp_path, "Linux")
    assert result.returncode == 0, result.stderr
    menu = tmp_path / "data" / "applications" / MENU_NAME
    assert menu.is_file()
    assert stat.S_IMODE(menu.stat().st_mode) == 0o644
    entry = menu.read_text(encoding="utf-8")
    assert "@PROJECT_ROOT@" not in entry
    assert f"Exec={tmp_path / 'install'}/current/scripts/start-demiurgos.sh start" in entry


@_POSIX_BASH
def test_installer_entry_is_a_noop_off_linux(tmp_path):
    result = _run_installer_entry(tmp_path, "Darwin")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "data" / "applications" / MENU_NAME).exists()


@_POSIX_BASH
def test_installer_entry_skips_without_the_shipped_template(tmp_path):
    result = _run_installer_entry(tmp_path, "Linux", with_template=False)
    assert result.returncode == 0, result.stderr
    assert "skipped" in result.stderr
    assert not (tmp_path / "data" / "applications" / MENU_NAME).exists()


# ---------------------------------------------------------------------------
# Release packaging: the template and its icon must actually ship
# ---------------------------------------------------------------------------


def test_release_payload_ships_the_desktop_template_and_icon():
    text = _text(RELEASE_WF)
    assert "desktop/Demiurgos.desktop" in text
    assert "docs/Logos-Demiurgos/dorado/01_svg_dorado/letra-D-6tonos.svg" in text


def test_release_allow_list_declares_the_desktop_artifacts():
    """payload_audit.sh is default-DENY: an unlisted stage file fails the build.

    Both assembly jobs (POSIX shell and Windows PowerShell) copy the extras and
    both declare them in their own allow-list, so each artifact is named four
    times; fewer means one parity path lost it.
    """
    text = _text(RELEASE_WF)
    assert text.count("desktop/Demiurgos.desktop") >= 4
    assert text.count("letra-D-6tonos.svg") >= 4


def test_icon_referenced_by_the_template_exists_and_ships():
    entry = _text(DESKTOP_TEMPLATE)
    assert f"Icon=@PROJECT_ROOT@/docs/Logos-Demiurgos/dorado/01_svg_dorado/letra-D-6tonos.svg" in entry
    assert ICON.is_file()
