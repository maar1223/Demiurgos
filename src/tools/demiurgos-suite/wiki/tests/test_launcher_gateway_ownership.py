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


@_BASH
def test_stop_component_kills_a_supervised_child_that_ignores_term(tmp_path: Path):
    """B1: the supervisor's grace must fit inside the launcher's stop window.

    A gateway that ignores SIGTERM used to outlive the supervisor (the launcher
    SIGKILLs the supervisor after ~6 s and the child is reparented), leaving an
    orphan that holds the port. The supervisor now escalates at 3 s, and the
    launcher also kills the recorded child when the wrapper is still a
    supervisor.
    """
    import json
    import signal
    import sys
    import time

    _HERE = Path(__file__).resolve().parent
    wiki = _HERE.parent
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    status_file = state_dir / "gateway-supervisor.json"
    child_code = (
        "import signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "time.sleep(120)"
    )
    supervisor = subprocess.Popen(
        [
            sys.executable, "-m", "gateway_supervisor",
            "--state-dir", str(state_dir),
            "--max-attempts", "0",
            "--backoff", "0",
            "--", sys.executable, "-c", child_code,
        ],
        cwd=str(tmp_path),
        env={**os.environ, "PYTHONPATH": str(wiki)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    child_pid = None
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                snapshot = json.loads(status_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                time.sleep(0.1)
                continue
            if snapshot.get("state") == "running" and isinstance(
                snapshot.get("gateway_pid"), int
            ):
                child_pid = snapshot["gateway_pid"]
                break
            time.sleep(0.1)
        assert child_pid is not None, "supervisor never reported a running child"

        (state_dir / "gateway.pid").write_text(f"{supervisor.pid}\n", encoding="utf-8")
        probe = (
            'source "$1" __probe__ || true; '
            'STATE_DIR="$2"; '
            'GATEWAY_PORT=65534; '
            'stop_component gateway'
        )
        result = subprocess.run(
            ["bash", "-c", probe, "bash", str(LAUNCHER), str(state_dir)],
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
        exit_code = supervisor.wait(timeout=10)
        # Exit 0 proves the supervisor handled TERM and escalated on its own
        # (3 s grace). A -9 would mean the launcher had to SIGKILL the wrapper,
        # which is the path that orphans a hung child.
        assert exit_code == 0
        assert not (state_dir / "gateway.pid").exists()
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
        snapshot = json.loads(status_file.read_text(encoding="utf-8"))
        assert snapshot["state"] == "stopped"
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@_BASH
def test_stop_component_kills_the_recorded_child_of_a_hung_supervisor(
    tmp_path: Path,
):
    """Defense in depth: even a supervisor that ignores TERM must not orphan.

    The launcher SIGKILLs a wrapper that outlives its window; the recorded
    gateway pid is then killed too, but only after its cmdline proves it is the
    gateway (a stale/reused pid must never be targeted).
    """
    import json
    import signal
    import sys
    import time

    _HERE = Path(__file__).resolve().parent
    wiki = _HERE.parent
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    # A supervisor stand-in that ignores TERM and carries the module marker.
    hung = subprocess.Popen(
        [
            sys.executable, "-c",
            "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "time.sleep(120)",
            "-m", "gateway_supervisor",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    child = subprocess.Popen(
        [
            sys.executable, "-c",
            "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "time.sleep(120)",
            "hermes-agent", "gateway", "run",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        (state_dir / "gateway-supervisor.json").write_text(
            json.dumps({
                "schema": "demiurgos.gateway-supervisor/v1",
                "state": "running",
                "cause": None,
                "attempts": 0,
                "max_attempts": 3,
                "last_exit_code": None,
                "last_restart_at": None,
                "updated_at": "2026-11-23T00:00:00Z",
                "supervisor_pid": hung.pid,
                "gateway_pid": child.pid,
            }),
            encoding="utf-8",
        )
        (state_dir / "gateway.pid").write_text(f"{hung.pid}\n", encoding="utf-8")
        probe = (
            'source "$1" __probe__ || true; '
            'STATE_DIR="$2"; '
            'GATEWAY_PORT=65534; '
            'stop_component gateway'
        )
        result = subprocess.run(
            ["bash", "-c", probe, "bash", str(LAUNCHER), str(state_dir)],
            env={
                "HOME": str(tmp_path / "home"),
                "TMPDIR": str(tmp_path / "tmp"),
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            },
            capture_output=True,
            text=True,
            timeout=40,
        )

        assert result.returncode == 0, result.stderr
        assert hung.wait(timeout=15) is not None
        # poll() reaps the process: a killed direct child otherwise stays a
        # zombie and `kill -0` would keep succeeding.
        deadline = time.time() + 15
        while time.time() < deadline:
            if child.poll() is not None:
                break
            time.sleep(0.1)
        else:
            pytest.fail("the recorded gateway child survived the stop")
    finally:
        for process in (hung, child):
            if process.poll() is None:
                process.kill()
        for process in (hung, child):
            try:
                process.wait(timeout=5)
            except Exception:
                pass
