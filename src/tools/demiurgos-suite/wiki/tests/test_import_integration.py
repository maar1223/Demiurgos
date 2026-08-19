# -*- coding: utf-8 -*-
"""World importer slice 4 — cumulative integration tests (task 4.4).

Covers the full lifecycle through the real router + ImportService
(upload/source selection -> analyze -> review -> approve -> execute -> result)
and dependency-outage fail-closed (no false success, no regenerated legacy
lore-index.json). Also proves a pre-existing legacy ``lore-index.json`` is
ignored and never regenerated (task 4.1).
"""

import base64
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _p in (str(_WIKI),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from import_models import ImportJobState  # noqa: E402
from import_store import ImportJobStore  # noqa: E402
from import_service import ImportService  # noqa: E402
from import_router import create_import_router, StreamChunkRequest  # noqa: E402


class _FakePrincipal:
    def __init__(self, pid: str = "tester"):
        self.id = pid


def _full_app(tmp_path, *, graph_reconcile=None, register_gallery=None):
    """Real router + ImportService on a hermetic store/spool/world."""
    store = ImportJobStore(":memory:")
    spool = tmp_path / "spool"
    mundos = tmp_path / "mundos"
    (mundos / "world1" / "lore").mkdir(parents=True, exist_ok=True)

    def read_file(rel):
        p = spool / rel
        try:
            return p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    service = ImportService(
        store=store, mundos_dir=mundos, spool_dir=spool,
        read_file=read_file,
        graph_reconcile=graph_reconcile
        or (lambda rel, mundo: None),
        register_gallery=register_gallery
        or (lambda world, src, rel: None),
    )

    def require_principal(request):
        return _FakePrincipal()

    app = FastAPI()
    app.include_router(
        create_import_router(
            require_principal=require_principal,
            mundos_dir=lambda: mundos,
            spool_dir=lambda: spool,
            store=store,
            service=service,
        )
    )
    return TestClient(app), store, spool, mundos


def _create_job(client: TestClient) -> dict:
    resp = client.post("/api/world1/imports",
                       json={"source_kind": "loose", "files": ["lore/A.md"]})
    assert resp.status_code == 201, resp.text
    return resp.json()["job"]


def _stream(client: TestClient, job_id: str, data: bytes) -> None:
    resp = client.post(
        f"/api/world1/imports/{job_id}/stream",
        json=StreamChunkRequest(relative="lore/A.md", offset=0,
                                data_b64=base64.b64encode(data).decode()).model_dump(),
    )
    assert resp.status_code == 200, resp.text


_OKF = b"---\ntype: personaje\nname: A\n---\n# Origen\nA body with context"


def test_full_lifecycle_upload_to_result(tmp_path):
    client, store, spool, mundos = _full_app(tmp_path)
    job = _create_job(client)
    _stream(client, job["job_id"], _OKF)

    analyze = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
    assert analyze.status_code == 200, analyze.text
    assert analyze.json()["candidates"] == 1

    review = client.get(f"/api/world1/imports/{job['job_id']}/review")
    assert review.status_code == 200
    digest = review.json()["digest"]
    assert digest

    approve = client.post(f"/api/world1/imports/{job['job_id']}/approve", json={})
    assert approve.status_code == 200, approve.text
    token = approve.json()["token"]
    assert token

    execute = client.post(
        f"/api/world1/imports/{job['job_id']}/execute",
        json={"digest": digest, "token": token},
    )
    assert execute.status_code == 200, execute.text
    assert execute.json()["job"]["state"] == "completed"
    outcomes = execute.json()["outcomes"]
    assert any(o["written"] for o in outcomes)

    # Ficha persisted and graph reconcile ran.
    target = mundos / "world1" / "lore" / "A.md"
    assert target.exists()
    assert "A body with context" in target.read_text(encoding="utf-8")
    done = store.get_job(job["job_id"])
    assert done.state == ImportJobState.COMPLETED


def test_legacy_lore_index_ignored_and_not_regenerated(tmp_path):
    client, store, spool, mundos = _full_app(tmp_path)
    # A pre-existing legacy index must be IGNORED and never regenerated (4.1).
    legacy = mundos / "world1" / "lore-index.json"
    legacy.write_text(json.dumps({"meta": {"entities_extracted": 99}}), encoding="utf-8")

    job = _create_job(client)
    _stream(client, job["job_id"], _OKF)
    client.post(f"/api/world1/imports/{job['job_id']}/analyze")
    review = client.get(f"/api/world1/imports/{job['job_id']}/review")
    digest = review.json()["digest"]
    approve = client.post(f"/api/world1/imports/{job['job_id']}/approve", json={})
    token = approve.json()["token"]
    resp = client.post(
        f"/api/world1/imports/{job['job_id']}/execute",
        json={"digest": digest, "token": token},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["job"]["state"] == "completed"

    # The pre-existing legacy index content is unchanged (ignored) and no NEW
    # lore-index.json appeared anywhere in the world tree as a result of the
    # import (the only one present is the file we planted).
    assert legacy.read_text(encoding="utf-8") == json.dumps(
        {"meta": {"entities_extracted": 99}})
    found = list((mundos / "world1").rglob("lore-index.json"))
    assert found == [legacy]


def test_dependency_outage_fails_closed_no_false_success(tmp_path):
    calls = []

    def failing_reconcile(rel, mundo):
        calls.append(rel)
        raise RuntimeError("graph index unavailable")

    client, store, spool, mundos = _full_app(tmp_path, graph_reconcile=failing_reconcile)
    job = _create_job(client)
    _stream(client, job["job_id"], _OKF)
    client.post(f"/api/world1/imports/{job['job_id']}/analyze")
    review = client.get(f"/api/world1/imports/{job['job_id']}/review")
    digest = review.json()["digest"]
    approve = client.post(f"/api/world1/imports/{job['job_id']}/approve", json={})
    token = approve.json()["token"]

    resp = client.post(
        f"/api/world1/imports/{job['job_id']}/execute",
        json={"digest": digest, "token": token},
    )
    # Actionable failure surfaced; no false success.
    assert resp.status_code == 409
    assert "failed closed" in resp.json()["detail"]
    assert calls, "graph reconcile must be invoked during execute"
    done = store.get_job(job["job_id"])
    assert done.state == ImportJobState.FAILED
    # Actionable, redacted error: the dependency exception type is recorded
    # (raw exception messages are not leaked).
    assert "RuntimeError" in done.error
    assert "execution dependency failed" in done.error
    # The failed candidate is tracked (no untracked write).
    items = [i for c in store.candidates_for(job["job_id"])
             for i in store.items_for(c.candidate_id)]
    assert any(i.outcome == "failed" for i in items)


def test_dependency_outage_does_not_regenerate_lore_index(tmp_path):
    calls = []

    def failing_gallery(world, src, rel):
        calls.append(rel)
        raise RuntimeError("media service down")

    client, store, spool, mundos = _full_app(tmp_path, register_gallery=failing_gallery)
    job = _create_job(client)
    # Source markdown references a contextual image; the image is streamed into
    # the job spool so the gallery registration dependency is genuinely hit.
    _stream(client, job["job_id"],
            b"---\ntype: personaje\nname: B\n---\n# Origen\n![retrato](retrato.png)\nB body")
    resp = client.post(f"/api/world1/imports/{job['job_id']}/stream",
                       json=StreamChunkRequest(
                           relative="retrato.png", offset=0,
                           data_b64=base64.b64encode(b"png-bytes").decode()).model_dump())
    assert resp.status_code == 200, resp.text

    client.post(f"/api/world1/imports/{job['job_id']}/analyze")
    review = client.get(f"/api/world1/imports/{job['job_id']}/review")
    digest = review.json()["digest"]
    approve = client.post(f"/api/world1/imports/{job['job_id']}/approve", json={})
    token = approve.json()["token"]
    resp = client.post(
        f"/api/world1/imports/{job['job_id']}/execute",
        json={"digest": digest, "token": token},
    )
    assert resp.status_code == 409
    assert store.get_job(job["job_id"]).state == ImportJobState.FAILED
    assert calls, "gallery registration must be invoked for the contextual image"
    # No legacy lore-index.json is regenerated anywhere during the failed job.
    assert list((mundos / "world1").rglob("lore-index.json")) == []
