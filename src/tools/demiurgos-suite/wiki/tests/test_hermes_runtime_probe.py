# -*- coding: utf-8 -*-
"""Read-only Hermes gateway liveness probe tests."""

import json
import os
from pathlib import Path
import sys
import types

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _path in (str(_WIKI), str(_SUITE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from hermes_runtime_probe import (  # noqa: E402
    HermesGatewayProbe,
    _pid_alive,
    _windows_pid_alive,
)


def _record(home: Path, state="running", pid=4242, recorded_home=None):
    return {
        "gateway_state": state,
        "pid": pid,
        "hermes_home": str(recorded_home if recorded_home is not None else home),
    }


def test_running_record_with_live_pid(tmp_path: Path):
    home = tmp_path / "hermes"
    home.mkdir()
    probe = HermesGatewayProbe(
        home, record_reader=lambda path: _record(home), pid_probe=lambda pid: pid == 4242
    )
    assert probe.is_running() is True


def test_down_states_are_not_running(tmp_path: Path):
    home = tmp_path / "hermes"
    home.mkdir()
    for state in ("stopped", "startup_failed", None):
        probe = HermesGatewayProbe(
            home,
            record_reader=lambda path, state=state: _record(home, state=state),
            pid_probe=lambda pid: True,
        )
        assert probe.is_running() is False, state


def test_dead_pid_is_not_running(tmp_path: Path):
    home = tmp_path / "hermes"
    home.mkdir()
    probe = HermesGatewayProbe(
        home, record_reader=lambda path: _record(home), pid_probe=lambda pid: False
    )
    assert probe.is_running() is False


def test_missing_or_corrupt_record_is_not_running(tmp_path: Path):
    home = tmp_path / "hermes"
    home.mkdir()
    assert HermesGatewayProbe(home).is_running() is False

    (home / "gateway_state.json").write_text("{ not json", encoding="utf-8")
    assert HermesGatewayProbe(home).is_running() is False

    (home / "gateway_state.json").write_text("[1, 2]", encoding="utf-8")
    assert HermesGatewayProbe(home).is_running() is False


def test_mismatched_home_is_not_running(tmp_path: Path):
    home = tmp_path / "hermes"
    other = tmp_path / "other"
    home.mkdir()
    other.mkdir()
    probe = HermesGatewayProbe(
        home,
        record_reader=lambda path: _record(home, recorded_home=other),
        pid_probe=lambda pid: True,
    )
    assert probe.is_running() is False


def test_reader_failure_fails_closed(tmp_path: Path):
    home = tmp_path / "hermes"
    home.mkdir()

    def _boom(path):
        raise OSError("unreadable")

    probe = HermesGatewayProbe(home, record_reader=_boom, pid_probe=lambda pid: True)
    assert probe.is_running() is False


def test_real_record_for_current_process_is_running(tmp_path: Path):
    home = tmp_path / "hermes"
    home.mkdir()
    (home / "gateway_state.json").write_text(
        json.dumps(_record(home, pid=os.getpid())), encoding="utf-8"
    )
    assert HermesGatewayProbe(home).is_running() is True


def test_real_record_for_dead_pid_is_not_running(tmp_path: Path):
    home = tmp_path / "hermes"
    home.mkdir()
    (home / "gateway_state.json").write_text(
        json.dumps(_record(home, pid=2_000_000_000)), encoding="utf-8"
    )
    assert HermesGatewayProbe(home).is_running() is False


def test_pid_alive_rejects_non_positive():
    assert _pid_alive(0) is False
    assert _pid_alive(-1) is False
    assert _pid_alive(True) is False


# ---------------------------------------------------------------------------
# Windows branch (F-1): exercised without Windows by faking the ctypes surface.
# ---------------------------------------------------------------------------


class _FakeCtypesFunction:
    """Callable that tolerates the ``argtypes``/``restype`` ctypes assignment."""

    def __init__(self, func):
        self._func = func
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self._func(*args)


class _FakeKernel32:
    def __init__(self, handle, wait_result=0x00000102, close_result=1, raise_on=None):
        self.handle = handle
        self.wait_result = wait_result
        self.close_result = close_result
        self.raise_on = raise_on
        self.open_calls: list[tuple] = []
        self.wait_calls: list[tuple] = []
        self.close_calls: list[int] = []
        self.OpenProcess = _FakeCtypesFunction(self._open)
        self.WaitForSingleObject = _FakeCtypesFunction(self._wait)
        self.CloseHandle = _FakeCtypesFunction(self._close)

    def _open(self, access, inherit, pid):
        self.open_calls.append((access, inherit, pid))
        if self.raise_on == "open":
            raise OSError("OpenProcess failed")
        return self.handle

    def _wait(self, handle, milliseconds):
        self.wait_calls.append((handle, milliseconds))
        if self.raise_on == "wait":
            raise OSError("WaitForSingleObject failed")
        return self.wait_result

    def _close(self, handle):
        self.close_calls.append(handle)
        if self.raise_on == "close":
            raise OSError("CloseHandle failed")
        return self.close_result


def _install_fake_windll(monkeypatch, kernel32) -> None:
    import ctypes

    monkeypatch.setattr(
        ctypes, "windll", types.SimpleNamespace(kernel32=kernel32), raising=False
    )


def test_windows_pid_probe_signatures_live_process_and_never_signals(monkeypatch):
    """A live process reports true, the HANDLE is full-width, and os.kill is
    never called (on Windows it would terminate the gateway)."""
    import ctypes.wintypes as wintypes

    kernel32 = _FakeKernel32(handle=0x1234)
    _install_fake_windll(monkeypatch, kernel32)
    signals: list[int] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: signals.append(pid))

    assert _windows_pid_alive(4242) is True

    assert kernel32.open_calls == [(0x00100000, False, 4242)]
    assert kernel32.wait_calls == [(0x1234, 0)]
    assert kernel32.close_calls == [0x1234]
    # (i) the Windows branch never signals the target.
    assert signals == []
    # The explicit signatures are the fix: the default c_int would truncate the
    # 64-bit HANDLE and leak the handle.
    assert kernel32.OpenProcess.argtypes == [
        wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
    ]
    assert kernel32.OpenProcess.restype is wintypes.HANDLE
    assert kernel32.WaitForSingleObject.argtypes == [wintypes.HANDLE, wintypes.DWORD]
    assert kernel32.WaitForSingleObject.restype is wintypes.DWORD
    assert kernel32.CloseHandle.argtypes == [wintypes.HANDLE]
    assert kernel32.CloseHandle.restype is wintypes.BOOL


def test_windows_pid_probe_null_handle_fails_closed(monkeypatch):
    kernel32 = _FakeKernel32(handle=0)
    _install_fake_windll(monkeypatch, kernel32)

    assert _windows_pid_alive(4242) is False
    assert kernel32.wait_calls == []
    assert kernel32.close_calls == []


def test_windows_pid_probe_exception_fails_closed(monkeypatch):
    kernel32 = _FakeKernel32(handle=0x1234, raise_on="wait")
    _install_fake_windll(monkeypatch, kernel32)

    assert _windows_pid_alive(4242) is False
    # Even on the failure path the handle is released (no leak per GET).
    assert kernel32.close_calls == [0x1234]
