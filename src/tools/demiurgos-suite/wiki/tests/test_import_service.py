# -*- coding: utf-8 -*-
"""World importer slice 2 — Phase 2 RED tests (approval integrity, merge,
contextual image placement, replacement snapshots, idempotent lifecycle)."""

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _p in (str(_WIKI),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from import_models import (  # noqa: E402
    Approval,
    Candidate,
    ImportJob,
    ImportJobState,
    Provenance,
    utcnow_iso,
)
from import_store import ImportJobStore  # noqa: E402
from import_service import (  # noqa: E402
    ImportService,
    atomic_write,
    digest_of,
    plan_merge,
    plan_placements,
    snapshot_to_papelera,
)
from import_analysis import analyze_markdown, analyze_source  # noqa: E402


def _job(world: str = "world1", principal: str = "tester") -> ImportJob:
    return ImportJob(
        job_id="job1", world=world, owner_principal=principal,
        state=ImportJobState.REVIEW, source_kind="loose",
        opaque_token="tok", created_at=utcnow_iso(), updated_at=utcnow_iso(),
    )


def _candidate(job_id: str = "job1", ident: str = "A",
               content: str = "---\ntype: personaje\nname: A\n---\nA body",
               images=None, replacement=None) -> Candidate:
    return Candidate(
        candidate_id=f"cand-{ident}", job_id=job_id, world="world1",
        normalized_identity=ident, source_hash=f"sha256:{ident}",
        provenance=Provenance(source_path=f"lore/{ident}.md",
                              source_kind="loose", source_hash=f"sha256:{ident}"),
        content_preview=content, images=images or [], replacement=replacement,
    )


@pytest.fixture
def store():
    return ImportJobStore(":memory:")


@pytest.fixture
def service(store, tmp_path):
    (tmp_path / "world1" / "lore").mkdir(parents=True, exist_ok=True)
    return ImportService(
        store=store, mundos_dir=tmp_path, spool_dir=tmp_path / "spool")


# ---------------------------------------------------------------------------
# 2.1 Approval / digest / token integrity
# ---------------------------------------------------------------------------

class TestApprovalIntegrity:
    def test_stale_digest_denied_zero_writes(self, store, service, tmp_path):
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        approval = service.issue_approval(job, "tester", [])
        # A new candidate lands after review -> aggregate digest changes, so
        # the approval (bound to the reviewed digest) must fail closed.
        store.add_candidate(_candidate(ident="B",
                                       content="---\ntype: personaje\nname: B\n---\nB body"))
        new_digest = service.candidate_digest(job)
        with pytest.raises(ValueError):
            service.validate_approval(job, "tester", new_digest, approval.token)
        assert not (tmp_path / "world1" / "lore" / "A.md").exists()

    def test_expired_token_denied(self, store, service, tmp_path):
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        from datetime import datetime, timedelta, timezone
        approval = Approval(
            approval_id="a", job_id=job.job_id, principal="tester",
            revision=job.revision, digest=service.candidate_digest(job),
            token="tok", issued_at=utcnow_iso(),
            expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        )
        store.save_approval(approval)
        with pytest.raises(ValueError):
            service.validate_approval(job, "tester", approval.digest, "tok")
        assert not (tmp_path / "world1" / "lore" / "A.md").exists()

    def test_replayed_token_denied(self, store, service, tmp_path):
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        approval = service.issue_approval(job, "tester", [])
        store.mark_approval_consumed(job.job_id, approval.token)
        with pytest.raises(ValueError):
            service.validate_approval(job, "tester", approval.digest, approval.token)
        assert not (tmp_path / "world1" / "lore" / "A.md").exists()

    def test_approval_succeeds_only_with_matching_digest(self, store, service, tmp_path):
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        approval = service.issue_approval(job, "tester", [])
        validated = service.validate_approval(job, "tester", approval.digest,
                                              approval.token)
        assert validated.token == approval.token


# ---------------------------------------------------------------------------
# 2.2 Preservation-first merge
# ---------------------------------------------------------------------------

class TestPreservationMerge:
    def test_new_ficha_added(self):
        decision = plan_merge("", "---\ntype: personaje\nname: A\n---\nbody")
        assert decision.action == "add"

    def test_edited_ficha_kept_unchanged(self):
        decision = plan_merge("same", "same")
        assert decision.action == "keep"

    def test_image_only_additions_are_added(self):
        current = "---\ntype: personaje\nname: A\n---\n# Origen\ntexto"
        incoming = ("---\ntype: personaje\nname: A\n---\n# Origen\n"
                    "texto\n\n![retrato](retrato.jpg)")
        decision = plan_merge(current, incoming)
        assert decision.action == "add"

    def test_modified_text_requires_review(self):
        current = "---\ntype: personaje\nname: A\n---\n# Origen\ntexto original"
        incoming = "---\ntype: personaje\nname: A\n---\n# Origen\ntexto CAMBIADO"
        decision = plan_merge(current, incoming)
        assert decision.action == "review"


# ---------------------------------------------------------------------------
# 2.3 Contextual image placement (no silent reorder/append/detach)
# ---------------------------------------------------------------------------

class TestContextualPlacement:
    def test_already_present_image_skipped(self):
        results = plan_placements(["a.jpg"], [{"relative_media_path": "a.jpg",
                                               "target_ficha": "X"}])
        assert results[0]["placement_status"] == "skip"

    def test_missing_target_is_ambiguous_review(self):
        results = plan_placements([], [{"relative_media_path": "a.jpg",
                                        "target_ficha": ""}])
        assert results[0]["placement_status"] == "ambiguous"

    def test_unambiguous_target_approved(self):
        results = plan_placements([], [{"relative_media_path": "a.jpg",
                                        "target_ficha": "Origen"}])
        assert results[0]["placement_status"] == "approved"

    def test_align_size_suffix_dedups_on_clean_base(self):
        # `img.png#left` resolves to the same gallery file as an existing
        # `img.png#right`: the second placement is skipped, never re-added.
        results = plan_placements(
            ["img.png#right"],
            [{"relative_media_path": "img.png#left", "target_ficha": "X"}])
        assert results[0]["placement_status"] == "skip"

    def test_align_size_suffix_dedups_against_bare_path(self):
        # Existing bare `img.png` vs incoming `img.png#left` -> same file.
        results = plan_placements(
            ["img.png"],
            [{"relative_media_path": "img.png#left", "target_ficha": "X"}])
        assert results[0]["placement_status"] == "skip"

    def test_align_size_suffix_preserved_on_approved_placement(self):
        # A new `#align-size` reference stays intact (markdown keeps the
        # suffix) while being admitted.
        results = plan_placements(
            [], [{"relative_media_path": "img.png#left", "target_ficha": "X"}])
        assert results[0]["placement_status"] == "approved"
        assert results[0]["relative_media_path"] == "img.png#left"

    def test_analysis_preserves_source_order_and_anchors(self):
        text = ("# Origen\nprimera linea de contexto\n\n"
                "## Llegada\nsegundo bloque ![img](pic.png)")
        file = analyze_markdown(text, "lore/A.md", "h", 10)
        assert len(file.chunks) == 2
        assert file.chunks[0].source_sequence == 0
        assert file.chunks[0].heading_path == "Origen"
        assert "primera linea" in file.chunks[0].nearby_text_anchor
        assert file.chunks[1].source_sequence == 1
        assert file.chunks[1].images[0].relative_media_path == "pic.png"

    def test_gallery_registration_uses_job_spool_and_clean_path(self, store, tmp_path):
        # A candidate carrying an approved `#align-size` placement registers the
        # clean base file from the job-scoped spool via the media contract.
        from import_models import ImagePlacement
        spool = tmp_path / "spool"
        (spool / "job1").mkdir(parents=True, exist_ok=True)
        (spool / "job1" / "img.png").write_bytes(b"img-bytes")
        registered = []
        svc = ImportService(
            store=store, mundos_dir=tmp_path, spool_dir=spool,
            register_gallery=lambda world, src, rel: registered.append(
                (world, str(src), rel)),
        )
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate(
            images=[ImagePlacement(gallery_asset_id="", relative_media_path="img.png#left",
                                   alt_text="r", target_ficha="X",
                                   confidence=1.0, placement_status="proposed")]))
        approval = svc.issue_approval(job, "tester", [])
        svc.execute(job, "tester", approval.digest, approval.token)
        assert registered, "gallery registration should have been invoked"
        _, src, rel = registered[0]
        assert rel == "img.png"                       # clean path, no suffix
        assert src == str(spool / "job1" / "img.png")  # job-scoped spool file


# ---------------------------------------------------------------------------
# 2.4 Replacement snapshot via .papelera (30-day recovery)
# ---------------------------------------------------------------------------

class TestReplacementSnapshot:
    def test_replacement_snapshots_prior_ficha(self, tmp_path):
        (tmp_path / "lore").mkdir(parents=True, exist_ok=True)
        prior = "---\ntype: personaje\nname: A\n---\nold body"
        rec = snapshot_to_papelera(tmp_path, "lore", "A.md", prior, "world1")
        assert rec.papelera_entry
        assert rec.recovery_status == "available"
        meta = (tmp_path / ".papelera" / "lore" / rec.papelera_entry
                / "meta.json").read_text(encoding="utf-8")
        assert '"original_path": "A.md"' in meta
        assert rec.expiry > "2000"

    def test_import_surfaces_papelera_entry_on_replacement(self, store, service, tmp_path):
        job = _job()
        store.create_job(job)
        target = tmp_path / "world1" / "lore" / "A.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("old ficha", encoding="utf-8")
        candidate = _candidate(
            content="new ficha",
            replacement=__import__("import_models", fromlist=["ReplacementRecord"])
            .ReplacementRecord(prior_snapshot="A.md", recovery_status="replace"))
        store.add_candidate(candidate)
        approval = service.issue_approval(job, "tester", [])
        outcomes = service.execute(job, "tester", approval.digest, approval.token)
        assert outcomes[0].written
        assert outcomes[0].papelera_entry


# ---------------------------------------------------------------------------
# 2.5 Idempotent cancel / resume / rollback
# ---------------------------------------------------------------------------

class TestIdempotentLifecycle:
    def test_cancel_then_resume_keeps_completed_and_revalidates(self, store, service):
        job = _job()
        store.create_job(job)
        job = service.cancel(job, "tester")
        assert job.state == ImportJobState.CANCELLED
        job = store.get_job(job.job_id)
        job2 = service.resume(job, "tester")
        assert job2.state == ImportJobState.REVIEW

    def test_cancel_is_idempotent(self, store, service):
        job = _job()
        store.create_job(job)
        job = service.cancel(job, "tester")
        job2 = service.cancel(job, "tester")  # already cancelled -> no-op
        assert job2.state == ImportJobState.CANCELLED

    def test_rollback_compensates_importer_changes(self, store, service):
        job = _job()
        store.create_job(job)
        job = store.update_job(job.job_id, expected_revision=job.revision,
                               state=ImportJobState.EXECUTING)
        rolled = service.rollback(job, "tester")
        assert rolled.state == ImportJobState.ROLLED_BACK

    def test_execute_marks_completed_and_records_items(self, store, service, tmp_path):
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        approval = service.issue_approval(job, "tester", [])
        service.execute(job, "tester", approval.digest, approval.token)
        done = store.get_job(job.job_id)
        assert done.state == ImportJobState.COMPLETED
        assert (tmp_path / "world1" / "lore" / "A.md").exists()


# ---------------------------------------------------------------------------
# 2.9 Graph reconciliation before success
# ---------------------------------------------------------------------------

class TestGraphReconciliation:
    def test_execute_reconciles_graph_before_success(self, store, tmp_path):
        # The graph index must be reconciled for each written ficha *before*
        # the job is reported complete (entities queryable before success).
        spool = tmp_path / "spool"
        (spool / "job1").mkdir(parents=True, exist_ok=True)
        reconciled = []
        svc = ImportService(
            store=store, mundos_dir=tmp_path, spool_dir=spool,
            graph_reconcile=lambda rel, mundo: reconciled.append((rel, mundo)),
        )
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        approval = svc.issue_approval(job, "tester", [])
        svc.execute(job, "tester", approval.digest, approval.token)
        assert reconciled, "graph reconcile must run during execute"
        rel, mundo = reconciled[0]
        assert mundo == "world1"
        assert rel.endswith("lore/A.md")
        done = store.get_job(job.job_id)
        assert done.state == ImportJobState.COMPLETED
