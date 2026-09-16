# -*- coding: utf-8 -*-
"""SC-DR-3.4 — launcher root propagation (WU-3, slice 3b-1).

The data-root resolver reads ``DEMIURGOS_DATA_ROOT`` first (then the user-config
pointer, else it raises), so every process a launcher spawns must receive that
variable. The Linux launcher exports it ONCE at the top level — both the API
and the Hermes gateway are subshells of the same shell, so a single export
reaches both. Each PowerShell launcher sets ``$env:DEMIURGOS_DATA_ROOT`` in the
process (or child command string) that starts the API and the gateway.

These are text scans of the launcher artifacts, matching ``test_port_ownership``
and the idea-capture ingress test: the launchers are CODE artifacts of the
checkout, located from this file, NOT from a configured data root. The single
behavioural check sources the real Linux script with an unknown action so it
sets its environment and exits without spawning anything — no server, no
gateway, no port binding.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo

LINUX_LAUNCHER = REPO_ROOT / "scripts" / "start-demiurgos-linux.sh"
MVP_LAUNCHER = REPO_ROOT / "scripts" / "start-demiurgos-mvp-linux.sh"
PS_STACK = REPO_ROOT / "start-demiurgos.ps1"
PS_API = REPO_ROOT / "start-api.ps1"
PS_GATEWAY = REPO_ROOT / "start-gateway.ps1"

_LINUX_EXPORT = 'export DEMIURGOS_DATA_ROOT="$PROJECT_ROOT"'
_API_CMD = '(cd "$API_DIR" && exec nohup "$PYTHON_BIN" -m uvicorn'
_GATEWAY_CMD = '(cd "$PROJECT_ROOT" && exec nohup env'


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_linux_launcher_exports_data_root_before_either_child_is_defined():
    text = _text(LINUX_LAUNCHER)
    assert _LINUX_EXPORT in text
    export_at = text.index(_LINUX_EXPORT)
    # The export precedes start_component(), so both the API and the gateway
    # subshells inherit it. It also precedes each rendered child command.
    assert export_at < text.index("start_component()")
    assert export_at < text.index(_API_CMD)
    assert export_at < text.index(_GATEWAY_CMD)


def test_linux_launcher_keeps_the_legacy_root_and_does_not_clear_env():
    text = _text(LINUX_LAUNCHER)
    # Rule: DEMIURGOS_ROOT stays untouched (Hermes may still read it).
    assert 'DEMIURGOS_ROOT="$PROJECT_ROOT"' in text
    # The gateway launches through `env` AFTER the export; it must not ignore
    # the inherited environment, or DEMIURGOS_DATA_ROOT would be dropped.
    gateway_tail = text[text.index(_GATEWAY_CMD):]
    assert "env -i" not in gateway_tail
    assert "--ignore-environment" not in gateway_tail


def test_mvp_alias_delegates_to_the_main_launcher():
    # The MVP script is a thin alias that `exec`s the main launcher, which sets
    # the export itself; it needs no export of its own.
    text = _text(MVP_LAUNCHER)
    assert 'exec "$SCRIPT_DIR/start-demiurgos-linux.sh"' in text


def test_powershell_stack_sets_data_root_for_gateway_and_both_api_paths():
    lines = _text(PS_STACK).splitlines()
    gateway_lines = [line for line in lines if "gateway run" in line]
    assert len(gateway_lines) == 1
    gateway = gateway_lines[0]
    assert "$env:DEMIURGOS_DATA_ROOT='$root'" in gateway
    assert "$env:DEMIURGOS_ROOT='$root'" in gateway  # legacy kept

    api_lines = [line for line in lines if "uvicorn api_server:app" in line]
    assert len(api_lines) == 2  # restart branch + fresh-start branch
    for line in api_lines:
        assert "$env:DEMIURGOS_DATA_ROOT='$root'" in line


def test_powershell_standalone_launchers_set_data_root():
    api = _text(PS_API)
    assert "$env:DEMIURGOS_DATA_ROOT = $root" in api
    assert "$env:PYTHONPATH" in api  # existing wiring kept

    gateway = _text(PS_GATEWAY)
    assert "$env:DEMIURGOS_DATA_ROOT" in gateway
    assert "$env:DEMIURGOS_ROOT" in gateway  # legacy kept


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_linux_launcher_env_really_carries_the_project_root():
    """Behavioural, hermetic: source the real script with an unknown action.

    Sourcing sets the top-level export, then ``main`` prints usage and returns
    without spawning anything; the probe reads DEMIURGOS_DATA_ROOT out of the
    resulting shell environment. No server, gateway, or port is touched.
    """
    probe = (
        'source "$1" __wu3_probe__ || true; '
        'printf %s "${DEMIURGOS_DATA_ROOT:-UNSET}"'
    )
    result = subprocess.run(
        ["bash", "-c", probe, "bash", str(LINUX_LAUNCHER)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == str(REPO_ROOT)
