# -*- coding: utf-8 -*-
"""Launcher gateway ownership detection for the pinned runtime wrapper.

The pinned Hermes launcher execs a Python wrapper whose argv ends with
``gateway run``; the old direct-build shape was ``hermes gateway run``. The
ownership gates must recognise both, or the launcher refuses to adopt/stop its
own gateway and leaks it on every restart.
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

LAUNCHER = REPO_ROOT / "scripts" / "start-demiurgos.sh"

_BASH = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="POSIX-bash sourcing probe (on Windows `bash` is the WSL stub)",
)


@_BASH
def test_is_gateway_cmdline_matches_wrapper_and_direct_builds(tmp_path: Path):
    probe = (
        'source "$1" __probe__ || true; '
        'is_gateway_cmdline "hermes gateway run" && echo A || echo a; '
        'is_gateway_cmdline "python3 -I -c from hermes_cli.main import main gateway run" '
        '&& echo B || echo b; '
        'is_gateway_cmdline "python3 -c /home/u/.demiurgos/hermes-agent ... gateway run" '
        '&& echo C || echo c; '
        'is_gateway_cmdline "python3 -m http.server" && echo D || echo d; '
        'is_gateway_cmdline "python3 -c gateway run" && echo E || echo e; '
        # S11: the launcher spawns the supervisor instead of the runtime, so the
        # pid-file owner is the supervisor process.
        'is_gateway_cmdline "python3 -m gateway_supervisor -- child gateway run" && echo F || echo f'
    )
    result = subprocess.run(
        ["bash", "-c", probe, "bash", str(LAUNCHER)],
        env={
            "HOME": str(tmp_path / "home"),
            "TMPDIR": str(tmp_path / "tmp"),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["A", "B", "C", "d", "e", "F"]


def test_launcher_uses_the_helper_for_both_ownership_gates():
    text = LAUNCHER.read_text(encoding="utf-8")

    assert text.count("is_gateway_cmdline") >= 3
    assert 'gateway) [[ "$cmdline" == *"hermes gateway run"* ]]' not in text


@_BASH
def test_restart_assistant_touches_only_the_gateway(tmp_path: Path):
    """S11b: the assistant-only restart never stops the API (in-flight work)."""
    probe = (
        'source "$1" __probe__ || true; '
        'GATEWAY_PORT=8642; '
        'calls=""; '
        'stop_component() { calls="$calls stop:$1"; }; '
        'wait_for_port_free() { calls="$calls wait:$1"; return 0; }; '
        'start_services() { calls="$calls start_services"; }; '
        'show_status() { calls="$calls status"; }; '
        'restart_assistant; '
        'printf "%s" "$calls"'
    )
    result = subprocess.run(
        ["bash", "-c", probe, "bash", str(LAUNCHER)],
        env={
            "HOME": str(tmp_path / "home"),
            "TMPDIR": str(tmp_path / "tmp"),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "stop:gateway wait:8642 start_services status"


def test_usage_advertises_the_assistant_restart_action():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "restart-assistant" in text
    assert "restart-assistant) restart_assistant ;;" in text
