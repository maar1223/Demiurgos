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


class _FakeProc:
    """Minimal ``subprocess.Popen`` stand-in for the unit tests.

    ``poll_result`` mirrors ``Popen.poll()``: None = still running, an int is
    the already-observed exit code.
    """

    def __init__(self, poll_result: int | None):
        self._poll_result = poll_result

    def poll(self) -> int | None:
        return self._poll_result


def _make_app(require_principal, launcher_path: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_system_control_router(
            require_principal=require_principal,
            launcher_path=launcher_path,
            # Keep the launcher stderr log inside the test's tmp_path instead
            # of the real /tmp/demiurgos-launcher.log.
            launcher_log=launcher_path.parent / "demiurgos-launcher.log",
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
    # The launcher OUTLIVES this API (on restart it stops the stack, this
    # process included). Its stderr must therefore be a file, never a pipe: a
    # pipe whose reader died kills the launcher with SIGPIPE after the stack is
    # already stopped, so the API never comes back.
    assert calls["kwargs"]["stderr"] is not subprocess.PIPE
    assert calls["kwargs"]["stderr"] is not subprocess.DEVNULL
    assert Path(calls["kwargs"]["stderr"].name).name == "demiurgos-launcher.log"


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
    # The launcher OUTLIVES this API (on restart it stops the stack, this
    # process included). Its stderr must therefore be a file, never a pipe: a
    # pipe whose reader died kills the launcher with SIGPIPE after the stack is
    # already stopped, so the API never comes back.
    assert calls["kwargs"]["stderr"] is not subprocess.PIPE
    assert calls["kwargs"]["stderr"] is not subprocess.DEVNULL
    assert Path(calls["kwargs"]["stderr"].name).name == "demiurgos-launcher.log"


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
        # The launcher's stderr is the injected log file; write what a failing
        # launcher would have written there.
        kwargs["stderr"].write(b"bash: restart: not found\n")
        return _FakeProc(poll_result=3)

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


def test_unavailable_log_never_reports_a_previous_runs_stderr(
    launcher_path: Path, monkeypatch
) -> None:
    """A leftover log from an earlier run must never be attributed to this one.

    If this run cannot open its log, the excerpt must report "no stderr output"
    rather than whatever a previous launcher left at the same path.
    """
    stale = launcher_path.parent / "demiurgos-launcher.log"
    stale.write_bytes(b"OLD STALE OUTPUT FROM A PREVIOUS RUN\n")

    def fake_popen(argv, **kwargs):
        return _FakeProc(poll_result=7)

    def failing_open(path, *args, **kwargs):
        if Path(path) == stale:
            raise OSError(24, "Too many open files")
        return open(path, *args, **kwargs)

    monkeypatch.setattr(system_control.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(system_control.time, "sleep", lambda _seconds: None)
    # Patch the router module's `open` only: the rest of the process keeps the
    # real builtin, so TestClient and pytest are unaffected.
    monkeypatch.setattr(system_control, "open", failing_open, raising=False)
    app = _make_app(require_principal=lambda request: _FakePrincipal(),
                    launcher_path=launcher_path)
    resp = TestClient(app).post("/api/system/restart")

    assert resp.status_code == 500
    body = resp.json()
    assert "OLD STALE OUTPUT" not in body["error"]
    assert "no stderr output" in body["error"]


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


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="detached POSIX launcher stub (bash + os.waitpid/os.kill) is POSIX-only",
)
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
# Regression: the launcher OUTLIVES the API that spawned it
# ---------------------------------------------------------------------------

#: Driver that dispatches the launcher through the REAL router and then exits —
#: which is what the API does when ``stop_all`` kills it mid-restart.
_DRIVER = """
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from system_control import create_system_control_router

app = FastAPI()
app.include_router(create_system_control_router(
    require_principal=lambda request: object(),
    launcher_path=Path(sys.argv[1]),
    launcher_log=Path(sys.argv[2]),
))
resp = TestClient(app).post("/api/system/restart")
print(resp.status_code, flush=True)
"""


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="detached POSIX launcher stub (bash + signals) is POSIX-only",
)
def test_launcher_survives_its_stderr_write_after_the_api_dies(
    tmp_path: Path,
) -> None:
    """The launcher must still be able to write to stderr once the API is gone.

    ``restart`` stops the stack BEFORE it starts it again, and stopping the API
    is what takes the launcher's stderr reader away when ``stderr`` is a
    ``subprocess.PIPE``. The launcher's next stderr write then raises EPIPE and
    SIGPIPE kills it — after the stack is already down and before the API is
    started back, which is how "Reiniciar Demiurgos" left Demiurgos half down.

    The driver reproduces the real sequence in a child process: dispatch, then
    die. A launcher whose stderr is a pipe cannot survive that.
    """
    marker = tmp_path / "survived.txt"
    stub = tmp_path / "start-demiurgos-linux.sh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        # Outlive the 0.5s peek window AND the driver, then write to stderr.
        "sleep 2\n"
        "printf 'launcher diagnostic\\n' >&2\n"
        f"printf 'survived\\n' > {marker}\n",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode
               | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    env = {**os.environ, "PYTHONPATH": str(_WIKI)}
    driver = subprocess.run(
        [sys.executable, "-c", _DRIVER, str(stub),
         str(tmp_path / "demiurgos-launcher.log")],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert driver.returncode == 0, driver.stderr
    assert driver.stdout.strip() == "200"

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and not marker.is_file():
        time.sleep(0.1)
    assert marker.is_file(), (
        "the detached launcher died on its stderr write after the API it was "
        "spawned by exited: a PIPE stderr cannot outlive the API"
    )


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