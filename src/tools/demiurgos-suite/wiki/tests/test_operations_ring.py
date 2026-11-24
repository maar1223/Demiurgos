# -*- coding: utf-8 -*-
"""Operations ring buffer (Phase 1, S5, task T1.3).

The report needs "what was done and where it failed" without a database: one
append-only JSONL under the state dir, bounded by entries and bytes, written by
a middleware that records failures and mutating requests. The world name is
never stored — only its hash (S6).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import operations_ring  # noqa: E402
from operations_ring import (  # noqa: E402
    MAX_ENTRIES,
    OperationRecorderMiddleware,
    hash_world,
    recent_operations,
    record_operation,
    recording_enabled,
)


def _ring(tmp_path: Path) -> Path:
    return tmp_path / "operations-ring.jsonl"


def _lines(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# --- storage ---------------------------------------------------------------


def test_a_recorded_operation_survives_a_new_process_read(tmp_path):
    ring = _ring(tmp_path)

    assert record_operation(
        {"run_id": "op-1", "method": "POST", "endpoint": "/api/{mundo}/import"},
        path=ring,
    )

    entries = recent_operations(path=ring)
    assert len(entries) == 1
    assert entries[0]["run_id"] == "op-1"
    assert entries[0]["endpoint"] == "/api/{mundo}/import"
    assert entries[0]["ts"]


def test_the_world_is_stored_only_as_a_hash(tmp_path):
    ring = _ring(tmp_path)

    record_operation({"run_id": "op-1", "world": "Vibrantes"}, path=ring)

    raw = ring.read_text(encoding="utf-8")
    assert "Vibrantes" not in raw
    entry = recent_operations(path=ring)[0]
    assert entry["world_hash"] == hash_world("Vibrantes")
    assert len(entry["world_hash"]) == 16


def test_no_world_means_no_hash(tmp_path):
    ring = _ring(tmp_path)
    record_operation({"run_id": "op-1"}, path=ring)
    assert recent_operations(path=ring)[0]["world_hash"] is None
    assert hash_world(None) is None
    assert hash_world("") is None


def test_recent_returns_newest_first_and_honours_the_limit(tmp_path):
    ring = _ring(tmp_path)
    for index in range(5):
        record_operation({"run_id": f"op-{index}"}, path=ring)

    entries = recent_operations(path=ring, limit=2)

    assert [entry["run_id"] for entry in entries] == ["op-4", "op-3"]


def test_malformed_lines_are_skipped_not_fatal(tmp_path):
    ring = _ring(tmp_path)
    record_operation({"run_id": "good-1"}, path=ring)
    with ring.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n\n")
    record_operation({"run_id": "good-2"}, path=ring)

    assert [entry["run_id"] for entry in recent_operations(path=ring)] == [
        "good-2",
        "good-1",
    ]


def test_a_missing_ring_reads_as_empty(tmp_path):
    assert recent_operations(path=_ring(tmp_path)) == []


def test_the_entry_cap_keeps_the_newest_entries(tmp_path):
    ring = _ring(tmp_path)

    for index in range(MAX_ENTRIES + 25):
        record_operation({"run_id": f"op-{index}"}, path=ring)

    stored = _lines(ring)
    assert len(stored) == MAX_ENTRIES
    assert stored[-1]["run_id"] == f"op-{MAX_ENTRIES + 24}"
    assert stored[0]["run_id"] == "op-25"


def test_the_byte_cap_is_enforced(tmp_path):
    ring = _ring(tmp_path)

    for index in range(60):
        record_operation({"run_id": f"op-{index}"}, path=ring, max_bytes=800)

    assert ring.stat().st_size <= 800
    assert recent_operations(path=ring, limit=1)[0]["run_id"] == "op-59"
    assert len(_lines(ring)) < 60


def test_an_unwritable_ring_never_raises(tmp_path):
    ring = tmp_path / "ring-as-a-directory"
    ring.mkdir()

    assert record_operation({"run_id": "op-1"}, path=ring) is False
    assert recent_operations(path=ring) == []


def test_recording_can_be_switched_off(tmp_path):
    assert recording_enabled({"DEMIURGOS_OPERATIONS_RING": "0"}) is False
    assert recording_enabled({}) is True
    assert recording_enabled({"DEMIURGOS_OPERATIONS_RING": "off"}) is False


# --- middleware ------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        self.now += 0.25
        return self.now


def _app(recorded: list[dict], *, status: int = 200, body: dict | None = None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        OperationRecorderMiddleware,
        recorder=lambda entry, **_kwargs: recorded.append(entry) or True,
        clock=_Clock(),
    )

    @app.get("/api/{mundo}/lore")
    def read(mundo: str):
        return {"ok": True}

    @app.post("/api/{mundo}/import")
    def write(mundo: str):
        if status >= 400:
            return JSONResponse(status_code=status, content=body or {"detail": "boom"})
        return {"ok": True}

    @app.get("/api/failing")
    def failing():
        return JSONResponse(status_code=status, content=body or {"detail": "boom", "code": "import.failed"})

    return app


def test_a_successful_read_is_not_recorded():
    recorded: list[dict] = []

    TestClient(_app(recorded)).get("/api/Vibrantes/lore")

    assert recorded == []


def test_a_mutating_request_is_recorded_even_when_it_succeeds():
    recorded: list[dict] = []

    TestClient(_app(recorded)).post("/api/Vibrantes/import")

    assert len(recorded) == 1
    entry = recorded[0]
    assert entry["method"] == "POST"
    assert entry["endpoint"] == "/api/{mundo}/import"
    assert entry["status"] == 200
    assert entry["world_hash"] == hash_world("Vibrantes")
    assert entry["run_id"].startswith("op-")
    assert entry["duration_ms"] >= 0


def test_a_failed_read_is_recorded_with_its_stable_error_code():
    recorded: list[dict] = []

    TestClient(_app(recorded, status=500)).get("/api/failing")

    assert len(recorded) == 1
    assert recorded[0]["status"] == 500
    assert recorded[0]["error_code"] == "import.failed"
    assert recorded[0]["endpoint"] == "/api/failing"


def test_an_unmatched_path_is_recorded_without_the_raw_segments():
    recorded: list[dict] = []

    TestClient(_app(recorded)).post("/api/Vibrantes/does-not-exist")

    assert len(recorded) == 1
    assert recorded[0]["endpoint"] == "unmatched"
    assert "Vibrantes" not in json.dumps(recorded[0])


def test_the_response_body_reaches_the_client_unchanged():
    body = {"detail": "boom", "code": "import.failed"}

    response = TestClient(_app([], status=409, body=body)).get("/api/failing")

    assert response.status_code == 409
    assert response.json() == body


def test_a_non_http_scope_passes_through_untouched():
    recorded: list[dict] = []
    calls: list[str] = []

    async def downstream(scope, receive, send):
        calls.append(scope["type"])

    import asyncio

    asyncio.run(OperationRecorderMiddleware(downstream, recorder=lambda *a, **k: recorded.append(a))( {"type": "lifespan"}, None, None))

    assert calls == ["lifespan"]
    assert recorded == []


def test_the_middleware_can_be_switched_off(monkeypatch):
    recorded: list[dict] = []
    monkeypatch.setenv("DEMIURGOS_OPERATIONS_RING", "0")

    TestClient(_app(recorded)).post("/api/Vibrantes/import")

    assert recorded == []


def test_the_production_app_records_operations():
    # The wiring is one ``add_middleware`` call; this pins it so a silent
    # deletion cannot pass the suite.
    import api_server

    names = {
        getattr(middleware.cls, "__name__", "")
        for middleware in api_server.app.user_middleware
    }
    assert "OperationRecorderMiddleware" in names
