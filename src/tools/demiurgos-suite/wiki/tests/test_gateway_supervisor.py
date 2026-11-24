# -*- coding: utf-8 -*-
"""Gateway supervisor: bounded restart loop, status transitions, kill switch."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from assistant_recovery import read_supervisor_status  # noqa: E402
from gateway_supervisor import (  # noqa: E402
    GatewaySupervisor,
    supervisor_enabled,
    validate_runtime_config,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Child:
    def __init__(self, pid: int, code: int, *, clock: _Clock, lifetime: float = 0.0):
        self.pid = pid
        self._code = code
        self._clock = clock
        self._lifetime = lifetime
        self.terminated = False
        self.killed = False

    def wait(self, timeout=None):
        self._clock.advance(self._lifetime)
        return self._code

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def _build(tmp_path, *, codes, max_attempts=3, backoff=(5.0, 15.0, 45.0),
           reset_after=60.0, lifetimes=None, validate=None, clock=None,
           stop_on_spawn_index=None, sleep_callback=None):
    clock = clock or _Clock()
    lifetimes = lifetimes or [0.0] * len(codes)
    spawns = []
    sleeps = []
    supervisor = None

    def spawn():
        index = len(spawns)
        if index >= len(codes):
            raise AssertionError("supervisor spawned more times than the test allows")
        spawns.append(index)
        if stop_on_spawn_index is not None and index == stop_on_spawn_index:
            supervisor.request_stop()
        return _Child(1000 + index, codes[index], clock=clock, lifetime=lifetimes[index])

    supervisor = GatewaySupervisor(
        command=["fake-gateway"],
        child_cwd=tmp_path,
        status_path=tmp_path / "gateway-supervisor.json",
        max_attempts=max_attempts,
        backoff=backoff,
        reset_after=reset_after,
        spawn=spawn,
        sleep=sleep_callback or sleeps.append,
        clock=clock,
        validate_config=validate,
    )
    return supervisor, spawns, sleeps


def _status(tmp_path):
    return read_supervisor_status(tmp_path / "gateway-supervisor.json")


def test_restarts_until_the_cap_then_fails(tmp_path):
    supervisor, spawns, sleeps = _build(
        tmp_path, codes=[1, 1, 1], max_attempts=2, backoff=(5.0, 15.0)
    )

    assert supervisor.run() == 1

    assert len(spawns) == 3  # initial start + 2 bounded restarts
    assert sleeps == [5.0, 15.0]
    status = _status(tmp_path)
    assert status is not None
    assert status["state"] == "failed"
    assert status["cause"] == "exited"
    assert status["attempts"] == 2
    assert status["last_exit_code"] == 1


def test_a_started_gateway_that_survives_past_the_threshold_resets_attempts(tmp_path):
    clock = _Clock()
    supervisor, spawns, _ = _build(
        tmp_path,
        codes=[1, 1, 1],
        max_attempts=1,
        backoff=(0.0,),
        reset_after=60.0,
        lifetimes=[70.0, 70.0, 0.0],
        clock=clock,
        # The third child asks for a stop, so the loop ends without inventing a
        # fourth spawn; two healthy runs must not have capped it at one.
        stop_on_spawn_index=2,
    )

    assert supervisor.run() == 0
    assert len(spawns) == 3
    status = _status(tmp_path)
    assert status is not None
    assert status["state"] == "stopped"


def test_config_invalid_never_spawns(tmp_path):
    supervisor, spawns, _ = _build(
        tmp_path, codes=[1], validate=lambda: "config_invalid"
    )

    assert supervisor.run() == 2

    assert spawns == []
    status = _status(tmp_path)
    assert status is not None
    assert status["state"] == "failed"
    assert status["cause"] == "config_invalid"


def test_spawn_failure_reports_not_started_without_retrying(tmp_path):
    calls = []

    def spawn():
        calls.append(1)
        raise FileNotFoundError("hermes runtime missing")

    supervisor = GatewaySupervisor(
        command=["missing"],
        child_cwd=tmp_path,
        status_path=tmp_path / "gateway-supervisor.json",
        spawn=spawn,
        sleep=lambda _seconds: None,
        clock=_Clock(),
    )

    assert supervisor.run() == 2
    assert len(calls) == 1
    status = _status(tmp_path)
    assert status is not None
    assert status["cause"] == "not_started"


def test_sleep_is_interruptible_by_a_stop_request(tmp_path):
    sleeps = []
    holder = {}

    def stopping_sleep(seconds):
        sleeps.append(seconds)
        holder["supervisor"].request_stop()

    supervisor, spawns, _ = _build(
        tmp_path, codes=[1, 1], max_attempts=3, sleep_callback=stopping_sleep
    )
    holder["supervisor"] = supervisor

    assert supervisor.run() == 0
    assert len(spawns) == 1
    status = _status(tmp_path)
    assert status is not None
    assert status["state"] == "stopped"


def test_status_transitions_carry_the_schema(tmp_path):
    supervisor, _, _ = _build(tmp_path, codes=[1], max_attempts=0)
    assert supervisor.run() == 1
    status = _status(tmp_path)
    assert status is not None
    assert status["schema"] == "demiurgos.gateway-supervisor/v1"
    assert status["max_attempts"] == 0


# --- kill switch -----------------------------------------------------------


@pytest.mark.parametrize("value", ["0", "false", "NO", "off"])
def test_supervisor_disabled_by_kill_switch(value):
    assert supervisor_enabled({"DEMIURGOS_GATEWAY_SUPERVISOR": value}) is False


@pytest.mark.parametrize("value", [None, "", " ", "1", "true", "yes"])
def test_supervisor_enabled_by_default(value):
    environ = {} if value is None else {"DEMIURGOS_GATEWAY_SUPERVISOR": value}
    assert supervisor_enabled(environ) is True


# --- config validation ------------------------------------------------------


def test_missing_profile_is_not_invalid(tmp_path):
    assert validate_runtime_config(None) is None
    assert validate_runtime_config(tmp_path) is None


def test_valid_config_passes(tmp_path):
    (tmp_path / "config.yaml").write_text("model:\n  default: gpt-4o\n", encoding="utf-8")
    assert validate_runtime_config(tmp_path) is None


def test_broken_yaml_is_config_invalid(tmp_path):
    (tmp_path / "config.yaml").write_text("model: [unclosed\n", encoding="utf-8")
    assert validate_runtime_config(tmp_path) == "config_invalid"


def test_non_mapping_config_is_config_invalid(tmp_path):
    (tmp_path / "config.yaml").write_text("- just\n- a list\n", encoding="utf-8")
    assert validate_runtime_config(tmp_path) == "config_invalid"


# --- end-to-end process test ------------------------------------------------


def _run_supervisor(tmp_path, child_code, *, extra_env=None, args=None):
    command = [
        sys.executable,
        "-m",
        "gateway_supervisor",
        "--state-dir",
        str(tmp_path),
        "--child-cwd",
        str(tmp_path),
        "--max-attempts",
        "1",
        "--backoff",
        "0",
        "--",
        sys.executable,
        "-c",
        f"import sys; sys.exit({child_code})",
    ]
    if args:
        command[3:3] = []
    env = {**os.environ, "PYTHONPATH": str(_WIKI), **(extra_env or {})}
    return subprocess.run(
        command,
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_process_bounded_retry_then_status_file(tmp_path):
    result = _run_supervisor(tmp_path, 3)

    assert result.returncode == 1
    status = read_supervisor_status(tmp_path / "gateway-supervisor.json")
    assert status is not None
    assert status["state"] == "failed"
    assert status["cause"] == "exited"
    assert status["attempts"] == 1


def test_process_kill_switch_runs_once_and_writes_no_status(tmp_path):
    result = _run_supervisor(
        tmp_path, 0, extra_env={"DEMIURGOS_GATEWAY_SUPERVISOR": "0"}
    )

    assert result.returncode == 0
    assert not (tmp_path / "gateway-supervisor.json").exists()


def test_process_sigterm_stops_the_child(tmp_path):
    if os.name == "nt":  # pragma: no cover - signal semantics differ
        pytest.skip("POSIX signal test")
    command = [
        sys.executable,
        "-m",
        "gateway_supervisor",
        "--state-dir",
        str(tmp_path),
        "--child-cwd",
        str(tmp_path),
        "--max-attempts",
        "3",
        "--backoff",
        "0",
        "--",
        sys.executable,
        "-c",
        "import time; time.sleep(60)",
    ]
    env = {**os.environ, "PYTHONPATH": str(_WIKI)}
    process = subprocess.Popen(
        command, cwd=str(tmp_path), env=env, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            status = read_supervisor_status(tmp_path / "gateway-supervisor.json")
            if status is not None and status["state"] == "running":
                break
            time.sleep(0.1)
        else:
            pytest.fail("supervisor never reached running")
        process.terminate()
        assert process.wait(timeout=15) == 0
    finally:
        if process.poll() is None:
            process.kill()
    status = read_supervisor_status(tmp_path / "gateway-supervisor.json")
    assert status is not None
    assert status["state"] == "stopped"
