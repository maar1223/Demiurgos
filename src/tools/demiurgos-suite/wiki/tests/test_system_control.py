"""tests/test_system_control.py — tests for the /api/system factory router.

Unit tests exercise the factory with a mocked ``subprocess.Popen``: fail-closed
auth (S-2.1), detached dispatch parameters (S-2.2/S-2.3), immediate non-zero
exit surfacing with stderr/exit code (S-2.4), and spawn failure (bad path).
The integration test drives a REAL detached ``Popen`` against an executable
launcher stub in ``tmp_path`` and verifies the endpoint returns 200 while the
stub is still running (non-blocking dispatch, S-2.2/S-2.3).

Session logout ordering (S-2.5) is enforced by the CLIENT by design — the
backend does not perform logout, so no logout test exists here.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _p in (str(_WIKI),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import system_control  # noqa: E402
from system_control import create_system_control_router  # noqa: E402


class _FakePrincipal:
    def __init__(self, pid: str = "tester"):
        self.id = pid


class _FakeStderr:
    """Bounded in-memory stand-in for ``proc.stderr``."""

    def __init__(self, data: bytes):
        self._data = data

    def read(self, limit: int = -1) -> bytes:
        return self._data[:limit] if limit >= 0 else self._data


class _FakeProc:
    """Minimal ``subprocess.Popen`` stand-in for the unit tests.

    ``poll_result`` mirrors ``Popen.poll()``: None = still running, an int is
    the already-observed exit code.
    """

    def __init__(self, poll_result: int | None, stderr_bytes: bytes = b""):
        self._poll_result = poll_result
        self.stderr = _FakeStderr(stderr_bytes)

    def poll(self) -> int | None:
        return self._poll_result


def _make_app(require_principal, launcher_path: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_system_control_router(
            require_principal=require_principal,
            launcher_path=launcher_path,
        )
    )
    return app


@pytest.fixture()
def launcher_path(tmp_path: Path) -> Path:
    return tmp_path / "start-demiurgos-linux.sh"


# ---------------------------------------------------------------------------
# S-2.1 — fail-closed auth: 401 when the principal resolver returns None
# ---------------------------------------------------------------------------

def test_restart_requires_principal(launcher_path: Path) -> None:
    app = _make_app(require_principal=lambda request: None, launcher_path=launcher_path)
    resp = TestClient(app).post("/api/system/restart")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Autenticación requerida"}


def test_shutdown_requires_principal(launcher_path: Path) -> None:
    app = _make_app(require_principal=lambda request: None, launcher_path=launcher_path)
    resp = TestClient(app).post("/api/system/shutdown")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Autenticación requerida"}


# ---------------------------------------------------------------------------
# S-2.2 / S-2.3 — 200 + detached launcher dispatch (mocked Popen)
# ---------------------------------------------------------------------------

def test_restart_dispatches_detached_launcher(launcher_path: Path, monkeypatch) -> None:
    calls: dict = {}

    def fake_popen(argv, **kwargs):
        calls["argv"] = argv
        calls["kwargs"] = kwargs
        return _FakeProc(poll_result=None)  # still running -> accepted

    monkeypatch.setattr(system_control.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(system_control.time, "sleep", lambda _seconds: None)
    app = _make_app(require_principal=lambda request: _FakePrincipal(),
                    launcher_path=launcher_path)
    resp = TestClient(app).post("/api/system/restart")
    assert resp.status_code == 200
    assert resp.json() == {"action": "restart", "accepted": True}
    # The launcher is dispatched with the action argument and detached.
    assert calls["argv"] == [str(launcher_path), "restart"]
    assert calls["kwargs"]["start_new_session"] is True
    assert calls["kwargs"]["stdout"] == subprocess.DEVNULL
    assert calls["kwargs"]["stderr"] == subprocess.PIPE


def test_shutdown_dispatches_detached_launcher(launcher_path: Path, monkeypatch) -> None:
    calls: dict = {}

    def fake_popen(argv, **kwargs):
        calls["argv"] = argv
        calls["kwargs"] = kwargs
        return _FakeProc(poll_result=None)

    monkeypatch.setattr(system_control.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(system_control.time, "sleep", lambda _seconds: None)
    app = _make_app(require_principal=lambda request: _FakePrincipal(),
                    launcher_path=launcher_path)
    resp = TestClient(app).post("/api/system/shutdown")
    assert resp.status_code == 200
    assert resp.json() == {"action": "shutdown", "accepted": True}
    # Shutdown dispatches the launcher's ``stop`` action (S-2.3).
    assert calls["argv"] == [str(launcher_path), "stop"]
    assert calls["kwargs"]["start_new_session"] is True
    assert calls["kwargs"]["stdout"] == subprocess.DEVNULL
    assert calls["kwargs"]["stderr"] == subprocess.PIPE


def test_launcher_exit_zero_is_accepted(launcher_path: Path, monkeypatch) -> None:
    """A launcher that finishes with exit 0 within the peek window -> 200."""

    def fake_popen(argv, **kwargs):
        return _FakeProc(poll_result=0)

    monkeypatch.setattr(system_control.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(system_control.time, "sleep", lambda _seconds: None)
    app = _make_app(require_principal=lambda request: _FakePrincipal(),
                    launcher_path=launcher_path)
    resp = TestClient(app).post("/api/system/shutdown")
    assert resp.status_code == 200
    assert resp.json() == {"action": "shutdown", "accepted": True}


# ---------------------------------------------------------------------------
# S-2.4 — non-zero launcher exit surfaces stderr/exit code
# ---------------------------------------------------------------------------

def test_nonzero_launcher_exit_returns_500_with_stderr(
    launcher_path: Path, monkeypatch
) -> None:
    def fake_popen(argv, **kwargs):
        return _FakeProc(poll_result=3, stderr_bytes=b"bash: restart: not found\n")

    monkeypatch.setattr(system_control.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(system_control.time, "sleep", lambda _seconds: None)
    app = _make_app(require_principal=lambda request: _FakePrincipal(),
                    launcher_path=launcher_path)
    resp = TestClient(app).post("/api/system/restart")
    assert resp.status_code == 500
    body = resp.json()
    assert body["action"] == "restart"
    assert body["accepted"] is False
    assert "3" in body["error"]
    assert "not found" in body["error"]


def test_spawn_failure_returns_500(launcher_path: Path, monkeypatch) -> None:
    """Bad launcher path (Popen raises) surfaces as a 500, never a 200."""

    def fake_popen(argv, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", str(launcher_path))

    monkeypatch.setattr(system_control.subprocess, "Popen", fake_popen)
    app = _make_app(require_principal=lambda request: _FakePrincipal(),
                    launcher_path=launcher_path)
    resp = TestClient(app).post("/api/system/restart")
    assert resp.status_code == 500
    body = resp.json()
    assert body["accepted"] is False
    assert "launcher" in body["error"]


# ---------------------------------------------------------------------------
# Integration: real detached Popen + launcher stub (S-2.2/S-2.3)
# ---------------------------------------------------------------------------

def _write_launcher_stub(tmp_path: Path) -> Path:
    """Executable stub that records its action+pid, then sleeps 5s."""
    stub = tmp_path / "start-demiurgos-linux.sh"
    marker = tmp_path / "invoked.txt"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s %s\\n' \"$1\" \"$$\" > {marker}\n"
        "sleep 5\n",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode
               | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return stub


def test_integration_dispatches_launcher_detached_and_returns_fast(
    tmp_path: Path,
) -> None:
    """Real Popen: 200 returns BEFORE the stub finishes (non-blocking) and the
    stub runs detached with the right action argument."""
    stub = _write_launcher_stub(tmp_path)
    marker = tmp_path / "invoked.txt"
    app = _make_app(require_principal=lambda request: _FakePrincipal(),
                    launcher_path=stub)
    client = TestClient(app)

    start = time.monotonic()
    resp = client.post("/api/system/restart")
    elapsed = time.monotonic() - start

    assert resp.status_code == 200
    assert resp.json() == {"action": "restart", "accepted": True}
    # Must NOT wait for the stub's `sleep 5` (peek window is 0.5s).
    assert elapsed < 3.0, f"endpoint blocked for {elapsed:.1f}s"

    # The stub was actually invoked with the action argument...
    assert marker.is_file()
    action, pid = marker.read_text(encoding="utf-8").split()
    assert action == "restart"
    # ...and is STILL alive after the response: detached, not waited on.
    os.kill(int(pid), 0)

    # Cleanup: reap the stub so no orphan leaks from the test run.
    try:
        os.kill(int(pid), 15)
    except ProcessLookupError:
        pass
    try:
        os.waitpid(int(pid), 0)
    except ChildProcessError:
        pass


# ---------------------------------------------------------------------------
# Registration smoke: the production app imports cleanly and exposes the routes
# ---------------------------------------------------------------------------

def test_registered_in_api_server_app() -> None:
    """The production ``api_server`` app registers both system routes.

    Importing the real app doubles as the clean-import smoke check for the
    ``include_router`` wiring. The endpoint itself is NOT invoked here (it
    would spawn the real launcher).
    """
    import api_server  # noqa: F401

    # Included routers are nested behind wrapper objects in app.routes, so the
    # OpenAPI schema is the reliable surface to assert registration.
    paths = api_server.app.openapi()["paths"]
    assert "/api/system/restart" in paths
    assert "/api/system/shutdown" in paths