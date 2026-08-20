# -*- coding: utf-8 -*-
"""World importer slice 4 — cumulative integration tests (task 4.4).

Covers the full lifecycle through the real router + ImportService
(upload/source selection -> analyze -> review -> approve -> execute -> result)
and dependency-outage fail-closed (no false success, no regenerated legacy
lore-index.json). Also proves a pre-existing legacy ``lore-index.json`` is
ignored and never regenerated (task 4.1).

Slice 1 regression tests (task 1.6) cover the bounded-ZIP wiring, legacy
``Lore/``/``Personajes/`` canonical mapping, and ambiguous-candidate
review/rejection through the real router + ImportService.
"""

import base64
import json
import sys
import zipfile
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


# ---------------------------------------------------------------------------
# Slice 1 regression — bounded ZIP, legacy mapping, ambiguous candidates (1.6)
# ---------------------------------------------------------------------------


def _stream_zip(client: TestClient, job_id: str, archive: Path) -> None:
    data = archive.read_bytes()
    resp = client.post(
        f"/api/world1/imports/{job_id}/stream",
        json=StreamChunkRequest(
            relative="world.zip", offset=0,
            data_b64=base64.b64encode(data).decode()).model_dump(),
    )
    assert resp.status_code == 200, resp.text


def _okf_bytes(name: str, body: str = "A") -> bytes:
    return (f"---\ntype: personaje\nname: {name}\n---\n# {name}\n{body}\n").encode()


def test_zip_source_extracts_and_produces_candidates(tmp_path):
    """Valid ZIP -> bounded extraction -> analysis -> review candidates."""
    client, store, spool, mundos = _full_app(tmp_path)
    archive = tmp_path / "world.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("lore/A.md", _okf_bytes("A"))
        zf.writestr("personajes/B.md", _okf_bytes("B"))
    resp = client.post("/api/world1/imports",
                       json={"source_kind": "zip", "files": ["world.zip"]})
    assert resp.status_code == 201, resp.text
    job = resp.json()["job"]
    _stream_zip(client, job["job_id"], archive)
    resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
    assert resp.status_code == 200, resp.text
    # The bounded extraction produced two candidates.
    assert resp.json()["candidates"] == 2
    assert store.get_job(job["job_id"]).state == ImportJobState.REVIEW
    # The ZIP archive and the extracted entries are both on disk.
    assert (spool / job["job_id"] / "world.zip").exists()
    assert (spool / job["job_id"] / "extracted" / "lore" / "A.md").exists()
    assert (spool / job["job_id"] / "extracted" / "personajes" / "B.md").exists()


def test_zip_bomb_fails_job_before_candidate_generation(tmp_path):
    """A ratio-bomb ZIP fails the job at analyze, before any candidate writes."""
    client, store, spool, mundos = _full_app(tmp_path)
    archive = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("lore/bomb.md", b"\x00" * (4 * 1024 * 1024),
                    compress_type=zipfile.ZIP_DEFLATED)
    resp = client.post("/api/world1/imports",
                       json={"source_kind": "zip", "files": ["world.zip"]})
    job = resp.json()["job"]
    _stream_zip(client, job["job_id"], archive)
    resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
    assert resp.status_code == 200, resp.text
    assert resp.json()["job"]["state"] == "failed"
    # No candidates were generated and no canon mutation occurred.
    assert store.candidates_for(job["job_id"]) == []
    assert list((mundos / "world1").rglob("*.md")) == []


def test_zip_with_unsafe_path_fails_closed(tmp_path):
    """A ZIP containing a traversal path is rejected before extraction."""
    client, store, spool, mundos = _full_app(tmp_path)
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../etc/passwd", "pwn")
    resp = client.post("/api/world1/imports",
                       json={"source_kind": "zip", "files": ["world.zip"]})
    job = resp.json()["job"]
    _stream_zip(client, job["job_id"], archive)
    resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
    assert resp.json()["job"]["state"] == "failed"
    assert store.candidates_for(job["job_id"]) == []


def test_legacy_lore_places_writes_to_canonical_lugares(tmp_path):
    """Legacy ``Lore/Places/A.md`` -> canonical ``lore/lugares/A.md`` on disk."""
    client, store, spool, mundos = _full_app(tmp_path)
    # Use loose source with a legacy source path: the analyzer builds the
    # candidate from a streamed file whose *relative path* carries the legacy
    # layout (the router does not rewrite it). resolve_target then maps it
    # to the canonical OKF target on execute.
    (mundos / "world1" / "lore" / "lugares").mkdir(parents=True, exist_ok=True)
    resp = client.post("/api/world1/imports",
                       json={"source_kind": "loose",
                             "files": ["Lore/Places/A.md"]})
    assert resp.status_code == 201, resp.text
    job = resp.json()["job"]
    # Stream the markdown under the legacy relative path so the candidate's
    # provenance preserves the legacy source for resolution.
    resp = client.post(
        f"/api/world1/imports/{job['job_id']}/stream",
        json=StreamChunkRequest(
            relative="Lore/Places/A.md", offset=0,
            data_b64=base64.b64encode(_okf_bytes("A")).decode()).model_dump())
    assert resp.status_code == 200, resp.text
    resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
    assert resp.status_code == 200, resp.text
    candidates = store.candidates_for(job["job_id"])
    assert len(candidates) == 1
    # The candidate carries the target resolution (canonical OKF + alias).
    resolution = candidates[0].target_resolution
    assert resolution is not None
    assert resolution["status"] == "resolved"
    assert resolution["canonical_path"] == "lore/lugares/A.md"
    assert resolution["alias_used"] == "Lore/Places"

    # Execute end-to-end: the ficha lands at the canonical path, not the
    # legacy one (no ``Lore/`` directory is created in the world tree).
    review = client.get(f"/api/world1/imports/{job['job_id']}/review")
    digest = review.json()["digest"]
    approve = client.post(
        f"/api/world1/imports/{job['job_id']}/approve", json={})
    token = approve.json()["token"]
    execute = client.post(
        f"/api/world1/imports/{job['job_id']}/execute",
        json={"digest": digest, "token": token})
    assert execute.status_code == 200, execute.text
    canonical = mundos / "world1" / "lore" / "lugares" / "A.md"
    legacy = mundos / "world1" / "Lore" / "Places" / "A.md"
    assert canonical.exists(), "canonical OKF target must receive the ficha"
    assert not legacy.exists(), "legacy path must never be written"
    assert store.get_job(job["job_id"]).state == ImportJobState.COMPLETED


def test_unknown_subfolder_under_lore_marks_review_no_write(tmp_path):
    """A candidate with an unknown subfolder resolves to ``review`` and is
    not written to canon. The diagnostic surfaces the original subfolder
    name so the reviewer can override or relabel."""
    client, store, spool, mundos = _full_app(tmp_path)
    resp = client.post("/api/world1/imports",
                       json={"source_kind": "loose",
                             "files": ["Lore/Random/X.md"]})
    assert resp.status_code == 201, resp.text
    job = resp.json()["job"]
    # Stream the markdown under the legacy unknown-subfolder path so the
    # analyzer sees the legacy provenance on the candidate.
    resp = client.post(
        f"/api/world1/imports/{job['job_id']}/stream",
        json=StreamChunkRequest(
            relative="Lore/Random/X.md", offset=0,
            data_b64=base64.b64encode(_okf_bytes("X")).decode()).model_dump())
    assert resp.status_code == 200, resp.text
    # Analyze: candidate is created with target_resolution in review status.
    resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
    assert resp.status_code == 200, resp.text
    candidates = store.candidates_for(job["job_id"])
    assert len(candidates) == 1
    resolution = candidates[0].target_resolution
    assert resolution is not None
    assert resolution["status"] == "review"
    assert "Random" in resolution["diagnostic"]
    # Approve and execute: the review status prevents the write.
    review = client.get(f"/api/world1/imports/{job['job_id']}/review")
    digest = review.json()["digest"]
    approve = client.post(
        f"/api/world1/imports/{job['job_id']}/approve", json={})
    assert approve.status_code == 200, approve.text
    token = approve.json()["token"]
    execute = client.post(
        f"/api/world1/imports/{job['job_id']}/execute",
        json={"digest": digest, "token": token})
    # The unknown subfolder produces a review outcome; canon is untouched.
    assert execute.status_code == 200, execute.text
    outcomes = execute.json()["outcomes"]
    assert any(o["action"] == "review" and "Random" in o["detail"] for o in outcomes)
    assert not (mundos / "world1" / "lore" / "Random" / "X.md").exists()


# ---------------------------------------------------------------------------
# Slice 2 — History endpoint (IM-2.3 + IM-2.7)
#
# The store-level contract is pinned in ``test_import_store.py``. Here we
# cover what only the HTTP layer can prove: authentication, principal
# isolation across HTTP calls, 400-on-malformed-cursor, opaque_token never
# leaks over the wire, and cursor-driven pagination through the real
# router.
# ---------------------------------------------------------------------------


def _app_with_principal(tmp_path, *, principal_id: str = "tester"):
    """Build a hermetic app whose auth returns a chosen principal id."""
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
        store=store, mundos_dir=mundos, spool_dir=spool, read_file=read_file,
        graph_reconcile=lambda rel, mundo: None,
        register_gallery=lambda world, src, rel: None,
    )

    def require_principal(request):
        # Read the override from a module-global; tests set it per-case.
        return _FakePrincipal(pid=_PRINCIPAL_OVERRIDE["id"])

    app = FastAPI()
    app.include_router(create_import_router(
        require_principal=require_principal,
        mundos_dir=lambda: mundos,
        spool_dir=lambda: spool,
        store=store,
        service=service,
    ))
    return TestClient(app), store


_PRINCIPAL_OVERRIDE: dict[str, str] = {"id": "tester"}


def test_list_jobs_requires_authentication(tmp_path) -> None:
    """No principal → 401 (the router's guard fails closed)."""
    store = ImportJobStore(":memory:")
    mundos = tmp_path / "mundos"
    (mundos / "world1" / "lore").mkdir(parents=True, exist_ok=True)

    app = FastAPI()
    app.include_router(create_import_router(
        require_principal=lambda request: None,  # no principal
        mundos_dir=lambda: mundos,
        spool_dir=lambda: tmp_path / "spool",
        store=store,
        service=None,
    ))
    client = TestClient(app)

    resp = client.get("/api/world1/imports")
    assert resp.status_code == 401, resp.text


def test_list_jobs_returns_principal_scoped_history(tmp_path) -> None:
    _PRINCIPAL_OVERRIDE["id"] = "tester"
    client, _ = _app_with_principal(tmp_path)
    # Create two jobs as "tester".
    client.post("/api/world1/imports",
                json={"source_kind": "loose", "files": ["a.md"]})
    client.post("/api/world1/imports",
                json={"source_kind": "loose", "files": ["b.md"]})

    resp = client.get("/api/world1/imports")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "jobs" in body and "next_cursor" in body
    assert len(body["jobs"]) == 2
    # Newest first.
    assert body["jobs"][0]["created_at"] >= body["jobs"][1]["created_at"]
    assert body["next_cursor"] is None


def test_list_jobs_isolates_foreign_principal(tmp_path) -> None:
    """A job created by 'alice' must be invisible to 'bob'."""
    _PRINCIPAL_OVERRIDE["id"] = "alice"
    client, store = _app_with_principal(tmp_path)
    resp = client.post("/api/world1/imports",
                       json={"source_kind": "loose", "files": ["a.md"]})
    assert resp.status_code == 201
    alice_job_id = resp.json()["job"]["job_id"]

    # Switch identity and list: alice's job must not appear.
    _PRINCIPAL_OVERRIDE["id"] = "bob"
    resp = client.get("/api/world1/imports")
    assert resp.status_code == 200
    body = resp.json()
    assert body["jobs"] == []
    assert body["next_cursor"] is None
    # And direct GET as bob still returns 403 (foreign job).
    resp = client.get(f"/api/world1/imports/{alice_job_id}")
    assert resp.status_code == 403


def test_list_jobs_empty_history_returns_empty_page(tmp_path) -> None:
    _PRINCIPAL_OVERRIDE["id"] = "tester"
    client, _ = _app_with_principal(tmp_path)

    resp = client.get("/api/world1/imports")
    assert resp.status_code == 200
    assert resp.json() == {"jobs": [], "next_cursor": None}


def test_list_jobs_paginates_with_cursor(tmp_path) -> None:
    """Five jobs, page size 2 → 3 pages, no duplicates, no losses."""
    _PRINCIPAL_OVERRIDE["id"] = "tester"
    client, store = _app_with_principal(tmp_path)
    for _ in range(5):
        client.post("/api/world1/imports",
                    json={"source_kind": "loose", "files": ["a.md"]})

    page1 = client.get("/api/world1/imports?limit=2").json()
    assert len(page1["jobs"]) == 2
    cursor1 = page1["next_cursor"]
    assert cursor1 is not None

    page2 = client.get(f"/api/world1/imports?limit=2&cursor={cursor1}").json()
    assert len(page2["jobs"]) == 2
    cursor2 = page2["next_cursor"]
    assert cursor2 is not None

    page3 = client.get(f"/api/world1/imports?limit=2&cursor={cursor2}").json()
    assert len(page3["jobs"]) == 1
    assert page3["next_cursor"] is None

    # Concatenated job_ids must be unique and exhaust the 5 created jobs.
    seen: list[str] = []
    for page in (page1, page2, page3):
        for j in page["jobs"]:
            seen.append(j["job_id"])
    assert len(seen) == 5
    assert len(set(seen)) == 5


def test_list_jobs_malformed_cursor_returns_400(tmp_path) -> None:
    _PRINCIPAL_OVERRIDE["id"] = "tester"
    client, _ = _app_with_principal(tmp_path)

    resp = client.get("/api/world1/imports?cursor=not-a-valid-cursor!!")
    assert resp.status_code == 400, resp.text
    assert "cursor" in resp.json()["detail"].lower()


def test_list_jobs_redacts_opaque_token_over_wire(tmp_path) -> None:
    """The opaque observability token never reaches the client."""
    _PRINCIPAL_OVERRIDE["id"] = "tester"
    client, store = _app_with_principal(tmp_path)
    client.post("/api/world1/imports",
                json={"source_kind": "loose", "files": ["a.md"]})

    resp = client.get("/api/world1/imports")
    body = resp.json()
    assert len(body["jobs"]) == 1
    assert "opaque_token" not in body["jobs"][0]
    # And the per-job endpoint agrees.
    job_id = body["jobs"][0]["job_id"]
    single = client.get(f"/api/world1/imports/{job_id}")
    assert "opaque_token" not in single.json()["job"]


def test_list_jobs_unknown_world_returns_404(tmp_path) -> None:
    """The world path is canonicalized server-side; an unknown world → 404."""
    _PRINCIPAL_OVERRIDE["id"] = "tester"
    client, _ = _app_with_principal(tmp_path)
    resp = client.get("/api/does-not-exist/imports")
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Spool cleanup — analyze FAILED paths + direct cancel reclaim the spool
# ---------------------------------------------------------------------------

class TestSpoolCleanup:
    """Every analyze FAILED path and the direct-cancel fallback must remove the
    job spool, while REVIEW (success) retains it (best-effort cleanup)."""

    def _app(self, tmp_path, *, provider=None, enricher=None, service=True):
        store = ImportJobStore(":memory:")
        spool = tmp_path / "spool"
        mundos = tmp_path / "mundos"
        (mundos / "world1" / "lore").mkdir(parents=True, exist_ok=True)
        svc = None
        if service:
            svc = ImportService(
                store=store, mundos_dir=mundos, spool_dir=spool,
                read_file=lambda rel: (spool / rel).read_text(encoding="utf-8")
                if (spool / rel).exists() else "",
                graph_reconcile=lambda rel, mundo: None,
                register_gallery=lambda world, src, rel: None,
            )
        app = FastAPI()
        app.include_router(create_import_router(
            require_principal=lambda request: _FakePrincipal(),
            mundos_dir=lambda: mundos,
            spool_dir=lambda: spool,
            store=store,
            provider=provider,
            enricher=enricher,
            service=svc,
        ))
        return TestClient(app), store, spool, mundos

    def _loose_job(self, client) -> dict:
        resp = client.post("/api/world1/imports",
                           json={"source_kind": "loose", "files": ["lore/A.md"]})
        assert resp.status_code == 201, resp.text
        job = resp.json()["job"]
        _stream(client, job["job_id"], _OKF)
        return job

    def test_analyze_malformed_provider_removes_spool(self, tmp_path):
        from import_intake import MalformedProviderError

        def bad_provider(job, files):
            raise MalformedProviderError("garbage")

        client, _, spool, _ = self._app(tmp_path, provider=bad_provider,
                                        service=False)
        job = self._loose_job(client)
        job_dir = spool / job["job_id"]
        assert job_dir.exists()
        resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
        assert resp.json()["job"]["state"] == "failed"
        assert not job_dir.exists()

    def test_analyze_provider_error_removes_spool(self, tmp_path):
        def bad_provider(job, files):
            raise RuntimeError("boom")

        client, _, spool, _ = self._app(tmp_path, provider=bad_provider,
                                        service=False)
        job = self._loose_job(client)
        job_dir = spool / job["job_id"]
        resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
        assert resp.json()["job"]["state"] == "failed"
        assert not job_dir.exists()

    def test_analyze_missing_zip_removes_spool(self, tmp_path):
        client, _, spool, _ = self._app(tmp_path, service=False)
        resp = client.post("/api/world1/imports",
                           json={"source_kind": "zip", "files": ["world.zip"]})
        job = resp.json()["job"]
        job_dir = spool / job["job_id"]
        # Simulate a pre-existing spool (e.g. a prior partial stream) that the
        # failed analyze must reclaim.
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "stale.md").write_bytes(b"x")
        resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
        assert resp.json()["job"]["state"] == "failed"
        assert not job_dir.exists()

    def test_analyze_zip_safety_removes_spool(self, tmp_path):
        client, _, spool, _ = self._app(tmp_path, service=False)
        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../etc/passwd", "pwn")
        resp = client.post("/api/world1/imports",
                           json={"source_kind": "zip", "files": ["world.zip"]})
        job = resp.json()["job"]
        _stream_zip(client, job["job_id"], archive)
        job_dir = spool / job["job_id"]
        resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
        assert resp.json()["job"]["state"] == "failed"
        assert not job_dir.exists()

    def test_analyze_malformed_enricher_removes_spool(self, tmp_path):
        from import_intake import MalformedProviderError

        def bad_enricher(candidates):
            raise MalformedProviderError("garbage")

        client, _, spool, _ = self._app(tmp_path, enricher=bad_enricher,
                                        service=True)
        job = self._loose_job(client)
        job_dir = spool / job["job_id"]
        resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze",
                           json={"enrich": True})
        assert resp.json()["job"]["state"] == "failed"
        assert not job_dir.exists()

    def test_analyze_review_retains_spool(self, tmp_path):
        """A successful analyze -> REVIEW must NOT clean up the spool (the
        job is not terminal; review/execute still need the bytes)."""
        client, _, spool, _ = self._app(tmp_path, service=True)
        job = self._loose_job(client)
        job_dir = spool / job["job_id"]
        resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
        assert resp.json()["job"]["state"] == "review"
        assert (job_dir / "lore" / "A.md").exists()

    def test_direct_cancel_fallback_removes_spool(self, tmp_path):
        """No-service branch: router cancel transitions to CANCELLED, reclaims
        the job spool, and reaps the DB row (Opción A)."""
        client, store, spool, _ = self._app(tmp_path, service=False)
        job = self._loose_job(client)
        job_dir = spool / job["job_id"]
        assert job_dir.exists()
        resp = client.post(f"/api/world1/imports/{job['job_id']}/cancel")
        assert resp.status_code == 200, resp.text
        assert resp.json()["job"]["state"] == "cancelled"
        assert not job_dir.exists()
        assert store.get_job(job["job_id"]) is None

    def test_service_cancel_deletes_job(self, tmp_path):
        """Service-branch cancel cleans once and reaps the DB row (Opción A);
        a second cancel then 404s because the job no longer exists."""
        client, store, spool, _ = self._app(tmp_path, service=True)
        job = self._loose_job(client)
        job_dir = spool / job["job_id"]
        assert job_dir.exists()
        r1 = client.post(f"/api/world1/imports/{job['job_id']}/cancel")
        assert r1.status_code == 200, r1.text
        assert r1.json()["job"]["state"] == "cancelled"
        assert not job_dir.exists()
        assert store.get_job(job["job_id"]) is None
        # Second cancel: the job was reaped — 404, not a silent no-op.
        r2 = client.post(f"/api/world1/imports/{job['job_id']}/cancel")
        assert r2.status_code == 404, r2.text
