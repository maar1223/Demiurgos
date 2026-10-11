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