# -*- coding: utf-8 -*-
"""World importer Phase 3 (importador-auto-frontmatter) — lifecycle tests.

Covers the execute path, graph identity, authority, and lifecycle integration:
  - 3.1  approved-only frontmatter materialization (``atomic_write``) with the
         untouched original body; legacy candidates without frontmatter keep
         the body-only write.
  - 3.2  unresolved reference-style media (``![][key]``) is isolated: it never
         fails the job, is excluded from gallery registration, and surfaces as
         a non-blocking review warning.
  - 3.5  review -> decisions -> approval -> execute, atomic write failure
         (no partial output), and legacy single-candidate import.
"""

import base64
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _p in (str(_WIKI),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from import_models import (  # noqa: E402
    Candidate,
    FrontmatterCandidate,
    FrontmatterState,
    ImportJob,
    ImportJobState,
    MediaDiagnostic,
    Provenance,
    utcnow_iso,
)
from import_store import ImportJobStore  # noqa: E402
from import_service import (  # noqa: E402
    ImportService,
    atomic_write,
    render_frontmatter_document,
)


def _job(world: str = "world1", principal: str = "tester") -> ImportJob:
    return ImportJob(
        job_id="job1", world=world, owner_principal=principal,
        state=ImportJobState.REVIEW, source_kind="loose",
        opaque_token="tok", created_at=utcnow_iso(), updated_at=utcnow_iso(),
    )


def _candidate(**over: object) -> Candidate:
    data = dict(
        candidate_id="cand-A", job_id="job1", world="world1",
        normalized_identity="A", canonical_id="Ayagares",
        source_hash="sha256:A",
        provenance=Provenance(source_path="lore/A.md", source_kind="loose",
                              source_hash="sha256:A"),
        content_preview="Fundada en el 1200 AE por los primeros colonos.",
        images=[], media_diagnostics=[],
        frontmatter=FrontmatterCandidate(
            title="Ayagares", type="lugar", description="Ciudad amurallada",
            relaciones=["Ayagares::Descripción Física"],
            state=FrontmatterState.GENERATED),
    )
    data.update(over)
    return Candidate(**data)


@pytest.fixture
def store():
    return ImportJobStore(":memory:")


@pytest.fixture
def service(store, tmp_path):
    (tmp_path / "world1" / "lore").mkdir(parents=True, exist_ok=True)
    return ImportService(store=store, mundos_dir=tmp_path,
                         spool_dir=tmp_path / "spool")


def _written(service, rel="lore/A.md") -> str:
    return (service.mundos_dir / "world1" / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 3.1 — approved-only frontmatter materialization
# ---------------------------------------------------------------------------

class TestFrontmatterMaterialization:
    def test_approved_materializes_frontmatter_and_body(self, store, service):
        """Task 3.1 — an approved candidate with reviewable frontmatter writes
        the frontmatter + the untouched original body via atomic write."""
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        approval = service.issue_approval(job, "tester", [])
        outcomes = service.execute(job, "tester", approval.digest, approval.token)
        assert outcomes[0].written
        content = _written(service)
        assert content.startswith("---\n")
        assert "id: Ayagares" in content
        assert "title: Ayagares" in content
        assert "type: lugar" in content
        assert "description: Ciudad amurallada" in content
        assert "relaciones:" in content
        assert '  - "[[Ayagares::Descripción Física]]"' in content
        assert content.endswith("Fundada en el 1200 AE por los primeros colonos.")

    def test_legacy_candidate_without_frontmatter_writes_body_as_is(
            self, store, service):
        """Task 3.5 — a legacy candidate (frontmatter None) keeps the
        body-only write, byte-for-byte (unchanged legacy behavior)."""
        job = _job()
        store.create_job(job)
        body = "---\ntype: personaje\nname: A\n---\nA body"
        store.add_candidate(_candidate(frontmatter=None, content_preview=body))
        approval = service.issue_approval(job, "tester", [])
        outcomes = service.execute(job, "tester", approval.digest, approval.token)
        assert outcomes[0].written
        assert _written(service) == body

    def test_manual_fallback_without_type_still_writes(self, store, service):
        """A fallback frontmatter (type None) still materializes a
        reviewable OKF document (no ``type:`` line) and the body."""
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate(
            frontmatter=FrontmatterCandidate(
                title="Ayagares", type=None, description="",
                relaciones=[], state=FrontmatterState.FALLBACK)))
        approval = service.issue_approval(job, "tester", [])
        outcomes = service.execute(job, "tester", approval.digest, approval.token)
        assert outcomes[0].written
        content = _written(service)
        assert "title: Ayagares" in content
        assert "type:" not in content.split("\n---")[0]
        assert content.endswith("Fundada en el 1200 AE por los primeros colonos.")

    def test_empty_canonical_id_omits_id_line(self, store, service):
        """An implicit single-ficha candidate (canonical_id "") emits no
        ``id:`` line yet still materializes title + body (legacy path)."""
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate(
            canonical_id="",
            normalized_identity="Enciclopedia",
            frontmatter=FrontmatterCandidate(
                title="Enciclopedia", type=None, description="",
                relaciones=[], state=FrontmatterState.FALLBACK)))
        approval = service.issue_approval(job, "tester", [])
        outcomes = service.execute(job, "tester", approval.digest, approval.token)
        assert outcomes[0].written
        content = _written(service)
        assert "id:" not in content
        assert "title: Enciclopedia" in content

    def test_render_frontmatter_document_is_pure_and_deterministic(self):
        doc = render_frontmatter_document(
            FrontmatterCandidate(
                title="Ayagares", type="lugar", description="d",
                relaciones=["Ayagares::X"], state=FrontmatterState.GENERATED),
            "\n  Cuerpo\n", canonical_id="Ayagares")
        expected = (
            "---\nid: Ayagares\ntitle: Ayagares\ntype: lugar\ndescription: d\n"
            "relaciones:\n  - \"[[Ayagares::X]]\"\n---\n\n  Cuerpo\n")
        assert doc == expected


# ---------------------------------------------------------------------------
# 3.5 — atomic write failure leaves no partial output
# ---------------------------------------------------------------------------

class TestAtomicWriteFailure:
    def test_atomic_write_cleans_tmp_on_replace_failure(self, tmp_path):
        """A failed rename removes the temp file and never leaves partial
        output; the pre-existing target stays intact."""
        target = tmp_path / "A.md"
        target.write_text("original", encoding="utf-8")

        original_replace = Path.replace

        def _boom(self, *args, **kwargs):
            raise OSError("rename failed")

        import import_service as _svc
        _svc.Path.replace = _boom  # type: ignore[assignment]
        try:
            with pytest.raises(OSError):
                atomic_write(target, "new content")
        finally:
            _svc.Path.replace = original_replace
        assert target.read_text(encoding="utf-8") == "original"
        # No leftover temp file (no partial output exposed).
        assert list(tmp_path.glob(".*.tmp")) == []

    def test_atomic_write_no_partial_target_on_write_failure(self, tmp_path):
        """If the temp write itself fails midway, the target is never
        truncated and no temp file remains."""
        import builtins
        target = tmp_path / "B.md"
        target.write_text("original", encoding="utf-8")

        real_open = builtins.open

        def _fail_write(*args, **kwargs):
            handle = real_open(*args, **kwargs)
            real_write = handle.write

            def _partial(data):
                real_write(data[:3])  # write only a prefix
                raise OSError("disk full")

            handle.write = _partial
            return handle

        builtins.open = _fail_write  # type: ignore[assignment]
        try:
            with pytest.raises(OSError):
                atomic_write(target, "brand new full content")
        finally:
            builtins.open = real_open
        assert target.read_text(encoding="utf-8") == "original"
        assert list(tmp_path.glob(".*.tmp")) == []


# ---------------------------------------------------------------------------
# 3.2 — unresolved reference-media isolation
# ---------------------------------------------------------------------------

class TestMediaIsolation:
    def _svc(self, store, tmp_path, registered):
        from import_models import ImagePlacement
        spool = tmp_path / "spool"
        (spool / "job1").mkdir(parents=True, exist_ok=True)
        (spool / "job1" / "retrato.png").write_bytes(b"img")
        (tmp_path / "world1" / "lore").mkdir(parents=True, exist_ok=True)
        return ImportService(
            store=store, mundos_dir=tmp_path, spool_dir=spool,
            register_gallery=lambda world, src, rel: registered.append(
                (world, str(src), rel)),
        )

    def test_unresolved_media_nonblocking_warns_and_not_in_gallery(
            self, store, tmp_path):
        """An unresolved ``![][key]`` reference never fails the job, is not
        registered in the gallery, and surfaces as a review warning while the
        inline image is still registered and the ficha is written."""
        from import_models import ImagePlacement
        registered = []
        svc = self._svc(store, tmp_path, registered)
        candidate = _candidate(
            content_preview=(
                "Cuerpo.\n\n![retrato](retrato.png)\n\n![][imagen1]\n"),
            images=[ImagePlacement(
                gallery_asset_id="", relative_media_path="retrato.png",
                alt_text="", target_ficha="Ayagares",
                confidence=1.0, placement_status="proposed")],
            media_diagnostics=[MediaDiagnostic(
                reference="![][imagen1]", image_key="imagen1", alt_text="",
                status="unresolved", target_ficha="Ayagares",
                message="unresolved media reference [imagen1]")],
        )
        job = _job()
        store.create_job(job)
        store.add_candidate(candidate)
        approval = svc.issue_approval(job, "tester", [])
        outcomes = svc.execute(job, "tester", approval.digest, approval.token)
        assert outcomes[0].written
        done = store.get_job(job.job_id)
        assert done.state == ImportJobState.COMPLETED
        # The unresolved reference is preserved verbatim in the ficha.
        content = _written(svc)
        assert "![][imagen1]" in content
        # The inline image is registered; the unresolved reference is not.
        assert any(rel == "retrato.png" for _, _, rel in registered)
        # Review warning recorded on the outcome; job still succeeded.
        assert outcomes[0].media_warnings
        assert any("imagen1" in w for w in outcomes[0].media_warnings)

    def test_only_unresolved_media_no_gallery_registration(
            self, store, tmp_path):
        """A candidate whose only media is an unresolved reference registers
        nothing in the gallery and still materializes (non-blocking)."""
        registered = []
        svc = self._svc(store, tmp_path, registered)
        candidate = _candidate(
            content_preview="Cuerpo.\n\n![][imagen1]\n",
            media_diagnostics=[MediaDiagnostic(
                reference="![][imagen1]", image_key="imagen1", alt_text="",
                status="unresolved", target_ficha="Ayagares",
                message="no definition for [imagen1]")],
        )
        job = _job()
        store.create_job(job)
        store.add_candidate(candidate)
        approval = svc.issue_approval(job, "tester", [])
        outcomes = svc.execute(job, "tester", approval.digest, approval.token)
        assert outcomes[0].written
        assert registered == []
        assert outcomes[0].media_warnings
        assert "![][imagen1]" in _written(svc)


# ---------------------------------------------------------------------------
# 3.5 — review -> decisions -> approval -> execute lifecycle
# ---------------------------------------------------------------------------

class TestLifecycleFlow:
    def test_lifecycle_with_decision_approval_execute(self, store, service):
        """Full review -> decisions -> approval -> execute for an approved
        candidate: the decision is persisted, approval binds the suggestion,
        and execute materializes the frontmatter + body."""
        candidate = _candidate()
        candidate.enrichment_json = [{
            "__type__": "relationship", "id": "rel:1",
            "source_candidate_id": "cand-A",
            "target_candidate_id": "cand-B",
            "relationship_type": "aliada_de",
            "confidence": 0.9,
            "evidence": "x",
            "review_state": "pending",
        }]
        candidate.enrichment_status = "ok"
        job = _job()
        store.create_job(job)
        store.add_candidate(candidate)

        # review — the candidate is returned for review.
        assert [c.candidate_id for c in store.candidates_for(job.job_id)] == ["cand-A"]

        # decisions — approve the relationship suggestion.
        assert store.update_suggestion_state("cand-A", "rel:1", "approved")

        # approval — bind the approved suggestion id to the token.
        approval = service.issue_approval(job, "tester", ["rel:1"])

        # execute — gated materialization completes the job.
        outcomes = service.execute(job, "tester", approval.digest, approval.token,
                                   suggestion_ids=["rel:1"])
        assert outcomes[0].written
        done = store.get_job(job.job_id)
        assert done.state == ImportJobState.COMPLETED
        assert "title: Ayagares" in _written(service)


# ---------------------------------------------------------------------------
# Router-level full lifecycle (review -> approve -> execute) + legacy import
# ---------------------------------------------------------------------------

class _FakePrincipal:
    id = "test-principal"

    def __str__(self) -> str:
        return self.id


def _scripted_funnel_runner():
    """Minimal fake Hermes runner covering funnel Steps 2-4 (fail-open)."""

    def runner(prompt: str, _session: str) -> str:
        data = json.loads(prompt)
        cands = data["candidates"]
        if cands and "body" in cands[0]:
            return json.dumps({"summaries": [
                {"candidate_id": c["candidate_id"],
                 "summary": f"Resumen denso de {c['display_title']}."}
                for c in cands]})
        if "rel_vocab" in data:
            return json.dumps({"relationships": []})
        if "entity_vocab" in data:
            return json.dumps({"frontmatter": [
                {"candidate_id": c["candidate_id"], "title": c["display_title"],
                 "type": "lugar", "description": "Ficha importada.",
                 "relaciones": []}
                for c in cands]})
        return "{}"

    return runner


def _funnel_enricher():
    """Enricher that runs the real enrichment funnel (generated frontmatter)."""
    from import_enrichment import analyze_ficha_funnel

    def enricher(candidates):
        return analyze_ficha_funnel(
            candidates, hermes_runner=_scripted_funnel_runner())

    return enricher


def _router_app(tmp_path, *, enricher=None):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from import_router import create_import_router

    store = ImportJobStore(":memory:")
    spool = tmp_path / "spool"
    spool.mkdir()
    mundos = tmp_path / "mundos"
    (mundos / "world1" / "lore").mkdir(parents=True, exist_ok=True)

    service = ImportService(
        store=store, mundos_dir=mundos, spool_dir=spool,
        graph_reconcile=lambda rel, mundo: None,
        register_gallery=lambda world, src, rel: None,
    )
    app = FastAPI()
    app.include_router(create_import_router(
        require_principal=lambda _request: _FakePrincipal(),
        mundos_dir=lambda: mundos,
        spool_dir=lambda: spool,
        store=store,
        service=service,
        enricher=enricher,
    ))
    return TestClient(app), store, spool, mundos


def _import_one(client, spool, source_kind, relative, content, *,
                enrich=False):
    resp = client.post(
        "/api/world1/imports",
        json={"source_kind": source_kind, "files": [relative]})
    job = resp.json()["job"]
    client.post(
        f"/api/world1/imports/{job['job_id']}/stream",
        json={"relative": relative, "offset": 0,
              "data_b64": base64.b64encode(content.encode()).decode()})
    analyze = client.post(
        f"/api/world1/imports/{job['job_id']}/analyze",
        json={"enrich": enrich} if enrich else None)
    assert analyze.status_code == 200, analyze.text
    return job


class TestRouterLifecycle:
    def test_review_approve_execute_materializes_with_unresolved_media(
            self, tmp_path):
        """End-to-end: stream -> analyze (funnel) -> review -> approve ->
        execute. The ficha is materialized with frontmatter + body, the job
        completes, and the unresolved ``![][imagen1]`` reference neither
        blocks nor registers."""
        client, store, spool, mundos = _router_app(
            tmp_path, enricher=_funnel_enricher())
        doc = ("# Ayagares\n\n"
               "Fundada en el 1200 AE por los primeros colonos.\n\n"
               "![][imagen1]\n")
        job = _import_one(client, spool, "loose", "lore/Enciclopedia.md", doc,
                          enrich=True)
        assert store.candidates_for(job["job_id"])  # one ficha in review

        review = client.get(
            f"/api/world1/imports/{job['job_id']}/review").json()
        assert review["candidates"][0]["canonical_id"] == "Ayagares"
        assert review["candidates"][0]["frontmatter"]["state"] == "generated"

        approve = client.post(
            f"/api/world1/imports/{job['job_id']}/approve",
            json={"digest": review["digest"], "group_ids": []})
        assert approve.status_code == 200, approve.text
        body = approve.json()

        execute = client.post(
            f"/api/world1/imports/{job['job_id']}/execute",
            json={"digest": body["digest"], "token": body["token"]})
        assert execute.status_code == 200, execute.text
        assert store.get_job(job["job_id"]).state == ImportJobState.COMPLETED

        ficha = (mundos / "world1" / "lore" / "Enciclopedia.md").read_text(
            encoding="utf-8")
        assert "title: Ayagares" in ficha
        assert "type: lugar" in ficha
        assert "Fundada en el 1200 AE" in ficha
        assert "![][imagen1]" in ficha
        # The unresolved media surfaced as a non-blocking warning on the
        # executed outcome.
        assert any(o["media_warnings"] for o in execute.json()["outcomes"])

    def test_legacy_single_candidate_import_still_works(self, tmp_path):
        """A source with no usable headings yields one implicit ficha; the
        legacy single-candidate import still materializes and completes."""
        client, store, spool, mundos = _router_app(
            tmp_path, enricher=_funnel_enricher())
        doc = "Un documento sin encabezados, un solo ficha implicita."
        job = _import_one(client, spool, "loose", "lore/Libre.md", doc,
                          enrich=True)
        cands = store.candidates_for(job["job_id"])
        assert len(cands) == 1

        review = client.get(
            f"/api/world1/imports/{job['job_id']}/review").json()
        approve = client.post(
            f"/api/world1/imports/{job['job_id']}/approve",
            json={"digest": review["digest"], "group_ids": []}).json()
        execute = client.post(
            f"/api/world1/imports/{job['job_id']}/execute",
            json={"digest": approve["digest"], "token": approve["token"]})
        assert execute.status_code == 200, execute.text
        assert store.get_job(job["job_id"]).state == ImportJobState.COMPLETED
        ficha = (mundos / "world1" / "lore" / "Libre.md").read_text(
            encoding="utf-8")
        assert "title: Libre" in ficha
        assert "Un documento sin encabezados" in ficha
