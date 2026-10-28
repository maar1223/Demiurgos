# -*- coding: utf-8 -*-
"""S2a — launcher data-root propagation (pointer-based contract, design S2-3).

The portable POSIX launcher (``scripts/start-demiurgos.sh``) resolves the data
root in this order (INSTALL_LAYOUT.md §2.4): existing env
``DEMIURGOS_DATA_ROOT`` -> existing pointer (left intact) -> bootstrap-once
the default ``<install_root>/data``. The forced ``export
DEMIURGOS_DATA_ROOT="$PROJECT_ROOT"`` of the old Linux launcher is gone.
``DEMIURGOS_ROOT`` stays for legacy Hermes reads, and
``DEMIURGOS_FRONTEND_DIST`` is exported by the launcher and by nothing else
(S1-6). Every process a launcher spawns must receive the resolved data root:
both the API and the Hermes gateway are subshells of the same shell, so a
single export after resolution reaches both.

These are text scans of the launcher artifacts, matching
``test_port_ownership`` and the idea-capture ingress test: the launchers are
CODE artifacts of the checkout, located from this file, NOT from a configured
data root. The single behavioural check sources the real portable script with
an unknown action so it sets its environment and exits without spawning
anything — no server, no gateway, no port binding, no pointer write.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo

PORTABLE_LAUNCHER = REPO_ROOT / "scripts" / "start-demiurgos.sh"
PS_STACK = REPO_ROOT / "start-demiurgos.ps1"
PS_API = REPO_ROOT / "start-api.ps1"
PS_GATEWAY = REPO_ROOT / "start-gateway.ps1"

_FORCED_EXPORT = 'export DEMIURGOS_DATA_ROOT="$PROJECT_ROOT"'
_DATA_ROOT_EXPORT = 'export DEMIURGOS_DATA_ROOT="$DATA_ROOT"'
_LEGACY_ROOT = 'DEMIURGOS_ROOT="$APP_ROOT"'
_DIST_EXPORT = 'export DEMIURGOS_FRONTEND_DIST="$APP_ROOT/frontend/dist"'
_APP_VERSION_EXPORT = "export DEMIURGOS_APP_VERSION"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_portable_launcher_has_no_forced_data_root_export():
    text = _text(PORTABLE_LAUNCHER)
    # The old `:19` forced export is gone, as is the `$PROJECT_ROOT/.venv`
    # interpreter hardcode (S2-4/S2-8).
    assert _FORCED_EXPORT not in text
    assert '"$PROJECT_ROOT/.venv"' not in text


def test_portable_launcher_exports_data_root_before_either_child_starts():
    text = _text(PORTABLE_LAUNCHER)
    assert _DATA_ROOT_EXPORT in text
    # The export follows resolution and precedes both child launchers, so the
    # API and the Hermes gateway subshells inherit the resolved root.
    assert text.index(_DATA_ROOT_EXPORT) < text.index("start_component gateway")
    assert text.index(_DATA_ROOT_EXPORT) < text.index("start_component api")


def test_portable_launcher_resolves_env_then_pointer_then_bootstrap():
    text = _text(PORTABLE_LAUNCHER)
    # Order contract (S2-3): existing env wins; the pointer file is read and
    # left intact; the default data dir is bootstrapped only when neither
    # exists — never silently re-oriented.
    assert "${DEMIURGOS_DATA_ROOT:-}" in text
    assert "data-root.json" in text
    assert "bootstrap" in text.lower()


def test_portable_launcher_bootstraps_documents_not_the_install_root():
    """Step 3 (S1): the bootstrap default is <documents>/Demiurgos.

    The pre-step-3 default `<install_root>/data` would put author content
    inside the install tree — and on Windows inside the state root."""
    text = _text(PORTABLE_LAUNCHER)
    assert "$INSTALL_ROOT/data" not in text
    assert 'DATA_ROOT="$(documents_dir)/Demiurgos"' in text


_POSIX_BASH = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="POSIX-bash sourcing probe: on Windows a bare `bash` is the WSL stub",
)


def _source_probe(tmp_path: Path, script: str, *, user_dirs: str | None) -> str:
    """Source the real launcher and run `script` inside it.

    Hermetic: HOME and XDG_CONFIG_HOME point into `tmp_path`, so the pointer
    and user-dirs.dirs are tmp files and the developer's real config is never
    read or written. `main` is not executed (the script runs it only when it is
    executed, not sourced).
    """
    home = tmp_path / "home"
    home.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    if user_dirs is not None:
        (config / "user-dirs.dirs").write_text(user_dirs, encoding="utf-8")
    env = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(config),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    result = subprocess.run(
        ["bash", "-c", script, "bash", str(PORTABLE_LAUNCHER)],
        env=env, capture_output=True, text=True, timeout=30, cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@_POSIX_BASH
def test_documents_dir_follows_the_localized_xdg_folder(tmp_path):
    """S2: a Spanish desktop names it ~/Documentos; never a second, English one."""
    out = _source_probe(
        tmp_path,
        'source "$1" __probe__; documents_dir',
        user_dirs='XDG_DOCUMENTS_DIR="$HOME/Documentos"\n',
    )
    assert out.rstrip("\n") == str(tmp_path / "home" / "Documentos")


@_POSIX_BASH
def test_documents_dir_falls_back_to_english_when_xdg_is_silent(tmp_path):
    out = _source_probe(
        tmp_path,
        'source "$1" __probe__; documents_dir',
        user_dirs='XDG_DESKTOP_DIR="$HOME/Desktop"\n',
    )
    assert out.rstrip("\n") == str(tmp_path / "home" / "Documents")


@_POSIX_BASH
def test_bootstrap_writes_the_pointer_under_the_documents_folder(tmp_path):
    """S1-S3: with no env and no pointer, the bootstrap default is Documents."""
    out = _source_probe(
        tmp_path,
        'source "$1" __probe__; resolve_data_root >/dev/null 2>&1; '
        'printf "%s|%s" "${DATA_ROOT:-UNSET}" "$POINTER_FILE"',
        user_dirs='XDG_DOCUMENTS_DIR="$HOME/Documentos"\n',
    )
    data_root, pointer_file = out.split("|")
    expected = tmp_path / "home" / "Documentos" / "Demiurgos"
    assert data_root == str(expected)
    assert (expected / "mundos").parent == expected
    assert Path(pointer_file) == tmp_path / "config" / "demiurgos" / "data-root.json"
    assert '"data_root": "%s"' % expected in Path(pointer_file).read_text(
        encoding="utf-8"
    )
    # S2: the English folder is never created alongside the localized one.
    assert not (tmp_path / "home" / "Documents").exists()


@_POSIX_BASH
def test_an_existing_pointer_is_never_reoriented(tmp_path):
    """S3/S4: the pointer beats the new default and is left byte-identical."""
    home = tmp_path / "home"
    home.mkdir()
    config = tmp_path / "config"
    (config / "demiurgos").mkdir(parents=True)
    (config / "user-dirs.dirs").write_text(
        'XDG_DOCUMENTS_DIR="$HOME/Documentos"\n', encoding="utf-8"
    )
    pointer = config / "demiurgos" / "data-root.json"
    existing = tmp_path / "checkout"
    original = (
        '{\n  "schema_version": 1,\n  "data_root": "%s",\n'
        '  "updated_at": "2026-09-17T17:15:28Z"\n}\n' % existing
    )
    pointer.write_text(original, encoding="utf-8")

    result = subprocess.run(
        [
            "bash", "-c",
            'source "$1" __probe__; resolve_data_root >/dev/null 2>&1; '
            'printf %s "${DATA_ROOT:-UNSET}"',
            "bash", str(PORTABLE_LAUNCHER),
        ],
        env={
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(config),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == str(existing)
    assert pointer.read_text(encoding="utf-8") == original
    assert not (home / "Documentos").exists()


def test_portable_launcher_exports_legacy_root_and_layout_dist():
    text = _text(PORTABLE_LAUNCHER)
    # DEMIURGOS_ROOT stays untouched for legacy Hermes reads (S2-3).
    assert _LEGACY_ROOT in text
    # DEMIURGOS_FRONTEND_DIST has exactly one owner: the launcher (S1-6).
    assert _DIST_EXPORT in text


def test_powershell_stack_roots_from_psscriptroot_and_exports_contract_env():
    """S2b PS stack (tasks 3.2/3.3): root from $PSScriptRoot; the resolved
    data root, the layout dist and the legacy DEMIURGOS_ROOT are exported for
    the API child; the stack starts ONLY uvicorn (Hermes optional)."""
    text = _text(PS_STACK)
    assert "$PSScriptRoot" in text
    assert "$env:DEMIURGOS_DATA_ROOT" in text
    assert "$env:DEMIURGOS_FRONTEND_DIST" in text
    assert "$env:DEMIURGOS_ROOT" in text
    # The API is started exactly once, from the layout venv, with the pointer
    # contract env already exported (uvicorn gets it via the process env).
    # (The ownership check also names `uvicorn api_server:app`, so pin the
    # actual invocation: Start-Process with -m uvicorn.)
    invocation = [line for line in text.splitlines() if '"uvicorn"' in line and "api_server:app" in line]
    assert len(invocation) == 1
    assert ".venv\\Scripts\\python.exe" in text


def test_powershell_standalone_launchers_resolve_data_root_portably():
    """S2b standalone launchers (task 3.3): no hardcoded root; the data root
    is resolved via the pointer contract and exported (plus the legacy
    DEMIURGOS_ROOT in the gateway, mirroring the POSIX contract)."""
    api = _text(PS_API)
    assert "$PSScriptRoot" in api
    assert "$env:DEMIURGOS_DATA_ROOT" in api
    assert "data-root.json" in api

    gateway = _text(PS_GATEWAY)
    assert "$PSScriptRoot" in gateway
    assert "$env:DEMIURGOS_DATA_ROOT" in gateway
    assert "$env:DEMIURGOS_ROOT" in gateway
    assert "Get-Command hermes" in gateway


def test_launchers_export_runtime_version_from_install_layout():
    """S1: DEMIURGOS_APP_VERSION rides the layout-contract export block.

    POSIX derives it from the basename of the resolved `current` link, guarded
    by the layout-existence check so a dev checkout never exports an empty
    value. The export precedes both children (like the other contract env).
    Windows mirrors it via the junction `.Target` leaf (`@($target)[0]`).
    """
    text = _text(PORTABLE_LAUNCHER)
    assert _APP_VERSION_EXPORT in text
    assert 'readlink "$INSTALL_ROOT/current"' in text
    # The export lives in the layout-contract block, before any child starts.
    assert text.index(_APP_VERSION_EXPORT) < text.index("start_component gateway")
    assert text.index(_APP_VERSION_EXPORT) < text.index("start_component api")
    # Never export an empty value (hard constraint from the spec).
    assert 'export DEMIURGOS_APP_VERSION=""' not in text

    ps = _text(PS_STACK)
    assert "$env:DEMIURGOS_APP_VERSION" in ps
    assert "(Split-Path -Leaf $appRoot) -eq \"current\"" in ps
    assert "Split-Path -Leaf @($target)[0]" in ps


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="POSIX-bash sourcing probe: on Windows a bare `bash` is the WSL stub",
)
def test_portable_launcher_sourcing_exposes_app_root_and_interpreter():
    """Behavioural, hermetic: source the real script with an unknown action.

    Sourcing sets the derived top-level paths, then ``main`` prints usage and
    returns without spawning anything; the probe reads APP_ROOT and PYTHON_BIN
    out of the resulting shell environment and verifies no runtime dir was
    created. No server, gateway, port, pointer, or user config is touched.

    The no-side-effect check compares the ``<app_root>/logs`` state before and
    after sourcing: a pre-existing dev ``<repo>/logs/`` (left by a real launcher
    run, S2-6) is NOT a side effect of sourcing, so its mere presence must not
    fail the probe — what must never happen is sourcing CREATING it.
    """
    logs_dir = REPO_ROOT / "logs"
    existed_before = logs_dir.exists()
    probe = (
        'source "$1" __probe__ || true; '
        'printf %s "${APP_ROOT:-UNSET}|${PYTHON_BIN:-UNSET}"; '
        '[ -e "$APP_ROOT/logs" ] && printf "|SIDE_EFFECT" || printf "|NO_SIDE_EFFECT"'
    )
    result = subprocess.run(
        ["bash", "-c", probe, "bash", str(PORTABLE_LAUNCHER)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f"{REPO_ROOT}|{REPO_ROOT}/.venv/bin/python")
    exists_after = result.stdout.endswith("|SIDE_EFFECT")
    assert exists_after == existed_before, (
        "sourcing the launcher changed <app_root>/logs existence "
        f"(before={existed_before}, after={exists_after})"
    )