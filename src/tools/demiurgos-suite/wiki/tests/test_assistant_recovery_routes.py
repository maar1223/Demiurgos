# -*- coding: utf-8 -*-
"""Assistant recovery routes: authenticated status read + gateway-only restart."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import system_control  # noqa: E402
from system_control import create_system_control_router  # noqa: E402


class _FakeProc:
    def __init__(self, poll_result: int | None = None):
        self._poll_result = poll_result

    def poll(self) -> int | None:
        return self._poll_result


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _make_app(
    *,
    require_principal=lambda request: "tester",
    launcher_path: Path,
    assistant_status=None,
    on_assistant_restart=None,
    clock=None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_system_control_router(
            require_principal=require_principal,
            launcher_path=launcher_path,
            launcher_log=launcher_path.parent / "demiurgos-launcher.log",
            assistant_status=assistant_status,
            on_assistant_restart=on_assistant_restart,
            clock=clock,
        )
    )
    return app


@pytest.fixture()
def launcher_path(tmp_path: Path) -> Path:
    return tmp_path / "start-demiurgos.sh"


# --- auth -------------------------------------------------------------------


def test_status_requires_principal(launcher_path: Path) -> None:
    app = _make_app(require_principal=lambda request: None, launcher_path=launcher_path)
    resp = TestClient(app).get("/api/system/assistant")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Autenticación requerida"}


def test_restart_requires_principal(launcher_path: Path) -> None:
    app = _make_app(require_principal=lambda request: None, launcher_path=launcher_path)
    resp = TestClient(app).post("/api/system/assistant/restart")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Autenticación requerida"}


# --- status read model ------------------------------------------------------


def test_status_returns_the_injected_view(launcher_path: Path) -> None:
    view = {
        "gateway_running": False,
        "state": "failed",
        "cause": "exited",
        "attempts": 3,
        "can_restart": True,
        "updated_at": "2026-11-23T20:00:00Z",
    }
    app = _make_app(launcher_path=launcher_path, assistant_status=lambda: view)
    resp = TestClient(app).get("/api/system/assistant")
    assert resp.status_code == 200
    assert resp.json() == view


def test_status_fails_closed_when_unwired(launcher_path: Path) -> None:
    app = _make_app(launcher_path=launcher_path)
    resp = TestClient(app).get("/api/system/assistant")
    assert resp.status_code == 503


# --- restart dispatch -------------------------------------------------------


def _capture_popen(monkeypatch, *, poll_result=None, raises=None):
    calls = []

    def fake_popen(argv, **kwargs):
        calls.append({"argv": argv, "kwargs": kwargs})
        if raises is not None:
            raise raises
        return _FakeProc(poll_result)

    monkeypatch.setattr(system_control.subprocess, "Popen", fake_popen)
    return calls


def test_restart_dispatches_the_assistant_launcher_action(
    monkeypatch, launcher_path: Path
) -> None:
    calls = _capture_popen(monkeypatch)
    app = _make_app(launcher_path=launcher_path)

    resp = TestClient(app).post("/api/system/assistant/restart")

    assert resp.status_code == 200
    assert resp.json() == {"action": "assistant-restart", "accepted": True}
    assert len(calls) == 1
    assert calls[0]["argv"] == [str(launcher_path), "restart-assistant"]
    assert calls[0]["kwargs"]["start_new_session"] is True


def test_platform_restart_still_dispatches_restart(
    monkeypatch, launcher_path: Path
) -> None:
    calls = _capture_popen(monkeypatch)
    app = _make_app(launcher_path=launcher_path)

    resp = TestClient(app).post("/api/system/restart")

    assert resp.status_code == 200
    assert calls[0]["argv"] == [str(launcher_path), "restart"]


def test_restart_runs_the_convergence_hook(monkeypatch, launcher_path: Path) -> None:
    _capture_popen(monkeypatch)
    hooks = []
    app = _make_app(
        launcher_path=launcher_path, on_assistant_restart=lambda: hooks.append(1)
    )

    TestClient(app).post("/api/system/assistant/restart")

    assert hooks == [1]


def test_failed_spawn_does_not_run_the_convergence_hook(
    monkeypatch, launcher_path: Path
) -> None:
    _capture_popen(monkeypatch, raises=OSError("cannot spawn"))
    hooks = []
    app = _make_app(
        launcher_path=launcher_path, on_assistant_restart=lambda: hooks.append(1)
    )

    resp = TestClient(app).post("/api/system/assistant/restart")

    assert resp.status_code == 500
    assert resp.json()["accepted"] is False
    assert hooks == []


def test_missing_launcher_fails_closed_without_spawning(
    monkeypatch, launcher_path: Path
) -> None:
    calls = _capture_popen(monkeypatch)
    hooks = []
    app = FastAPI()
    app.include_router(
        create_system_control_router(
            require_principal=lambda request: "tester",
            launcher_path=launcher_path,
            launcher_log=launcher_path.parent / "demiurgos-launcher.log",
            launcher_available=False,
            on_assistant_restart=lambda: hooks.append(1),
        )
    )

    resp = TestClient(app).post("/api/system/assistant/restart")

    assert resp.status_code == 503
    assert calls == []
    assert hooks == []


def test_restart_is_idempotent_inside_the_window(
    monkeypatch, launcher_path: Path
) -> None:
    calls = _capture_popen(monkeypatch)
    clock = _Clock()
    app = _make_app(launcher_path=launcher_path, clock=clock)
    client = TestClient(app)

    first = client.post("/api/system/assistant/restart")
    clock.advance(1.0)
    second = client.post("/api/system/assistant/restart")
    clock.advance(10.0)
    third = client.post("/api/system/assistant/restart")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == {
        "action": "assistant-restart",
        "accepted": True,
        "coalesced": True,
    }
    assert third.status_code == 200
    assert "coalesced" not in third.json()
    assert len(calls) == 2
