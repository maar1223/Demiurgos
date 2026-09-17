# -*- coding: utf-8 -*-
"""ASGI middleware tests for WU-11 (REQ-BE-6, SC-BE-6.1; REQ-RS-3, SC-RS-3.2).

Two behaviours are asserted through a real ASGI test client:

* the engine is signalled ONLY on a successful mutating ``/api/*`` request —
  never on a read, never on a rejected write, never on a backup or system route;
* while quiesced, a mutating ``/api/*`` request is answered with ``503`` and a
  ``Retry-After`` header BEFORE the handler runs, while reads still pass.

The notifier and the quiesce probe are injected, so no engine, no clock and no
thread is involved.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from backup.engine import RETRY_AFTER_SECONDS  # noqa: E402
from backup.middleware import (  # noqa: E402
    DataChangeNotifierMiddleware,
    is_signalled,
)


class Recorder:
    """Captures the paths the middleware signalled."""

    def __init__(self) -> None:
        self.paths: list[str | None] = []

    def __call__(self, path: str | None = None) -> None:
        self.paths.append(path)

    @property
    def count(self) -> int:
        return len(self.paths)


def _build_app(recorder: Recorder, *, quiesced: bool = False) -> Starlette:
    """A tiny API-shaped app wrapped in the middleware under test."""
    async def mutate(request):
        return JSONResponse({"ok": True})

    async def rejected(request):
        return JSONResponse({"detail": "invalid"}, status_code=422)

    async def broken(request):
        return JSONResponse({"detail": "boom"}, status_code=500)

    async def read(request):
        return JSONResponse({"ok": True})

    routes = [
        Route("/api/worlds", mutate, methods=["POST", "PUT", "PATCH", "DELETE", "GET"]),
        Route("/api/ideas", mutate, methods=["POST"]),
        Route("/api/things/{thing_id}", rejected, methods=["POST"]),
        Route("/api/broken", broken, methods=["POST"]),
        Route("/api/backup/run", mutate, methods=["POST"]),
        Route("/api/system", mutate, methods=["POST"]),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(
        DataChangeNotifierMiddleware,
        notifier=recorder,
        quiesce_check=lambda: quiesced,
    )
    return app


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_successful_write_signals_the_engine(method) -> None:
    recorder = Recorder()
    with TestClient(_build_app(recorder)) as client:
        response = client.request(method, "/api/worlds")

    assert response.status_code == 200
    assert recorder.paths == ["/api/worlds"]


def test_a_created_write_signals_the_engine() -> None:
    recorder = Recorder()
    with TestClient(_build_app(recorder)) as client:
        response = client.post("/api/ideas")

    assert response.status_code == 200
    assert recorder.count == 1


def test_a_get_never_signals_the_engine() -> None:
    recorder = Recorder()
    with TestClient(_build_app(recorder)) as client:
        response = client.get("/api/worlds")

    assert response.status_code == 200
    assert recorder.count == 0


def test_a_rejected_write_never_signals_the_engine() -> None:
    recorder = Recorder()
    with TestClient(_build_app(recorder)) as client:
        response = client.post("/api/things/1")

    assert response.status_code == 422
    assert recorder.count == 0


def test_a_failed_write_never_signals_the_engine() -> None:
    recorder = Recorder()
    with TestClient(_build_app(recorder), raise_server_exceptions=False) as client:
        response = client.post("/api/broken")

    assert response.status_code == 500
    assert recorder.count == 0


def test_a_backup_route_never_signals_itself() -> None:
    recorder = Recorder()
    with TestClient(_build_app(recorder)) as client:
        response = client.post("/api/backup/run")

    assert response.status_code == 200
    assert recorder.count == 0, "a run must never schedule a run"


def test_a_system_route_never_signals_the_engine() -> None:
    recorder = Recorder()
    with TestClient(_build_app(recorder)) as client:
        response = client.post("/api/system")

    assert response.status_code == 200
    assert recorder.count == 0


def test_a_non_api_write_never_signals_the_engine() -> None:
    recorder = Recorder()
    with TestClient(_build_app(recorder)) as client:
        response = client.post("/static/upload")

    assert response.status_code in (404, 405)
    assert recorder.count == 0


def test_a_quiesced_write_is_rejected_with_503_and_retry_after() -> None:
    recorder = Recorder()
    with TestClient(_build_app(recorder, quiesced=True)) as client:
        response = client.post("/api/worlds")

    assert response.status_code == 503
    assert response.headers["retry-after"] == str(RETRY_AFTER_SECONDS)
    assert recorder.count == 0, "a rejected write changed nothing, so it never signals"


def test_a_read_still_passes_while_quiesced() -> None:
    recorder = Recorder()
    with TestClient(_build_app(recorder, quiesced=True)) as client:
        response = client.get("/api/worlds")

    assert response.status_code == 200
    assert recorder.count == 0


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/worlds", True),
        ("/api/ideas/1", True),
        ("/api/backup/run", False),
        ("/api/backup/restore", False),
        ("/api/system", False),
        ("/api/system/control", False),
        ("/health", False),
        ("/static/app.js", False),
    ],
)
def test_signalled_path_classification(path, expected) -> None:
    assert is_signalled(path) is expected
