"""World importer — store-level coverage for the list_jobs / JobPage contract
(world-importer slice 2, IM-2.2 + IM-2.7).

The listing contract is the foundation of ``GET /api/{mundo}/imports``: it must
be principal-scoped (foreign jobs never leak), ordered deterministically under
ties, redact sensitive fields, and paginate with an opaque cursor that
survives concurrent inserts. These tests pin the store-level guarantees; the
router-level authorization + 400-on-malformed-cursor behavior is exercised in
``test_import_integration.py``.
"""

from __future__ import annotations

import base64
import json
import sqlite3
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
    Provenance,
    utcnow_iso,
)
from import_store import (  # noqa: E402
    ImportJobStore,
    _decode_cursor,
    _encode_cursor,
)
from import_vision import VisionResult  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _job(
    *,
    job_id: str,
    world: str = "demo",
    principal: str = "alice",
    state: ImportJobState = ImportJobState.PENDING,
    created_at: str | None = None,
    source_kind: str = "loose",
) -> ImportJob:
    now = created_at or utcnow_iso()
    return ImportJob(
        job_id=job_id,
        world=world,
        owner_principal=principal,
        state=state,
        source_kind=source_kind,
        opaque_token=f"tok-{job_id}",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def store() -> ImportJobStore:
    return ImportJobStore(":memory:")


# ---------------------------------------------------------------------------
# list_jobs — ordering, filtering, redacting
# ---------------------------------------------------------------------------


class TestListJobsOrdering:
    """Newest-first ordering, with deterministic ties on shared created_at."""

    def test_returns_jobs_newest_first(self, store: ImportJobStore) -> None:
        store.create_job(_job(job_id="a", created_at="2026-01-01T10:00:00"))
        store.create_job(_job(job_id="b", created_at="2026-01-02T10:00:00"))
        store.create_job(_job(job_id="c", created_at="2026-01-03T10:00:00"))

        jobs, next_cursor = store.list_jobs(
            principal="alice", world="demo", limit=10,
        )

        ids = [j.job_id for j in jobs]
        assert ids == ["c", "b", "a"]
        assert next_cursor is None

    def test_ties_break_on_job_id_desc(self, store: ImportJobStore) -> None:
        # Three jobs sharing created_at — job_id DESC is the tiebreaker.
        ts = "2026-02-01T00:00:00+00:00"
        store.create_job(_job(job_id="aa", created_at=ts))
        store.create_job(_job(job_id="bb", created_at=ts))
        store.create_job(_job(job_id="cc", created_at=ts))

        jobs, _ = store.list_jobs(principal="alice", world="demo", limit=10)
        assert [j.job_id for j in jobs] == ["cc", "bb", "aa"]


class TestListJobsFiltering:
    """Authorization + world isolation are enforced inside the query."""

    def test_filters_by_principal(self, store: ImportJobStore) -> None:
        store.create_job(_job(job_id="a1", principal="alice"))
        store.create_job(_job(job_id="a2", principal="alice"))
        store.create_job(_job(job_id="b1", principal="bob"))

        jobs, _ = store.list_jobs(principal="alice", world="demo", limit=10)
        ids = sorted(j.job_id for j in jobs)
        assert ids == ["a1", "a2"]

    def test_foreign_principal_sees_no_jobs(self, store: ImportJobStore) -> None:
        store.create_job(_job(job_id="a1", principal="alice"))

        jobs, next_cursor = store.list_jobs(
            principal="mallory", world="demo", limit=10,
        )
        assert jobs == []
        assert next_cursor is None

    def test_filters_by_world(self, store: ImportJobStore) -> None:
        store.create_job(_job(job_id="d1", world="demo"))
        store.create_job(_job(job_id="s1", world="staging"))

        jobs, _ = store.list_jobs(principal="alice", world="demo", limit=10)
        ids = [j.job_id for j in jobs]
        assert ids == ["d1"]

    def test_principal_and_world_must_both_match(
        self, store: ImportJobStore,
    ) -> None:
        store.create_job(_job(job_id="d1", world="demo", principal="alice"))
        store.create_job(_job(job_id="s1", world="staging", principal="alice"))
        store.create_job(_job(job_id="d2", world="demo", principal="bob"))

        jobs, _ = store.list_jobs(principal="alice", world="demo", limit=10)
        assert [j.job_id for j in jobs] == ["d1"]


class TestListJobsEmpty:
    """An empty history must return an empty page, not raise."""

    def test_empty_history_returns_empty_page(
        self, store: ImportJobStore,
    ) -> None:
        jobs, next_cursor = store.list_jobs(
            principal="alice", world="demo", limit=10,
        )
        assert jobs == []
        assert next_cursor is None

    def test_empty_for_unknown_world(self, store: ImportJobStore) -> None:
        store.create_job(_job(job_id="d1", world="demo"))
        jobs, next_cursor = store.list_jobs(
            principal="alice", world="ghost-world", limit=10,
        )
        assert jobs == []
        assert next_cursor is None


# ---------------------------------------------------------------------------
# Cursor pagination — opaque, stable across inserts
# ---------------------------------------------------------------------------


class TestCursorPagination:
    """The opaque cursor must page through the entire history without
    duplication or loss, even when new rows are inserted mid-pagination."""

    def test_limit_clamped_to_max_100(self, store: ImportJobStore) -> None:
        # 105 rows; limit=200 must clamp and return only 100, with cursor.
        for i in range(105):
            store.create_job(_job(
                job_id=f"j{i:03d}",
                created_at=f"2026-03-01T{i // 60:02d}:{i % 60:02d}:00",
            ))
        jobs, next_cursor = store.list_jobs(
            principal="alice", world="demo", limit=200,
        )
        assert len(jobs) == 100
        assert next_cursor is not None  # more pages available

    def test_invalid_limit_falls_back_to_default(
        self, store: ImportJobStore,
    ) -> None:
        """A non-positive or unparseable limit must not be accepted as "give me
        zero rows" — the store falls back to the default page size instead of
        silently returning an empty page (which would mask a client bug)."""
        store.create_job(_job(job_id="a"))
        store.create_job(_job(job_id="b"))
        # limit=0 is invalid; the store falls back to the default (50),
        # returning both rows rather than silently returning nothing.
        jobs_zero, _ = store.list_jobs(
            principal="alice", world="demo", limit=0,
        )
        assert len(jobs_zero) == 2
        # Same defensive fallback for negative limits.
        jobs_neg, _ = store.list_jobs(
            principal="alice", world="demo", limit=-7,
        )
        assert len(jobs_neg) == 2
        # And for unparseable values (the FastAPI router guards against this
        # too, but the store stays defensible in isolation).
        jobs_bad, _ = store.list_jobs(
            principal="alice", world="demo", limit="abc",  # type: ignore[arg-type]
        )
        assert len(jobs_bad) == 2

    def test_cursor_advances_to_next_page(self, store: ImportJobStore) -> None:
        for i in range(5):
            store.create_job(_job(
                job_id=f"j{i}",
                created_at=f"2026-04-01T00:0{i}:00",
            ))
        page1, cursor1 = store.list_jobs(
            principal="alice", world="demo", limit=2,
        )
        assert [j.job_id for j in page1] == ["j4", "j3"]
        assert cursor1 is not None

        page2, cursor2 = store.list_jobs(
            principal="alice", world="demo", limit=2, cursor=cursor1,
        )
        assert [j.job_id for j in page2] == ["j2", "j1"]
        assert cursor2 is not None

        page3, cursor3 = store.list_jobs(
            principal="alice", world="demo", limit=2, cursor=cursor2,
        )
        assert [j.job_id for j in page3] == ["j0"]
        assert cursor3 is None  # exhausted

    def test_cursor_pagination_with_concurrent_insert(
        self, store: ImportJobStore,
    ) -> None:
        """Newer jobs inserted mid-pagination must NOT appear in earlier
        pages — the cursor encodes the seek position, not a timestamp."""
        store.create_job(_job(
            job_id="old1", created_at="2026-05-01T00:00:00",
        ))
        store.create_job(_job(
            job_id="old2", created_at="2026-05-02T00:00:00",
        ))
        store.create_job(_job(
            job_id="old3", created_at="2026-05-03T00:00:00",
        ))

        # First page reads the top 2 (newest 2 of the current set).
        page1, cursor1 = store.list_jobs(
            principal="alice", world="demo", limit=2,
        )
        assert [j.job_id for j in page1] == ["old3", "old2"]

        # A new, newer job arrives between pages.
        store.create_job(_job(
            job_id="newer", created_at="2026-05-04T00:00:00",
        ))

        # The next page continues strictly past the cursor — newer is NOT
        # retroactively added (DESC, tuple key seek).
        page2, cursor2 = store.list_jobs(
            principal="alice", world="demo", limit=2, cursor=cursor1,
        )
        assert [j.job_id for j in page2] == ["old1"]
        assert cursor2 is None

    def test_cursor_is_opaque_base64(self, store: ImportJobStore) -> None:
        store.create_job(_job(job_id="a"))
        store.create_job(_job(job_id="b"))
        _, cursor = store.list_jobs(principal="alice", world="demo", limit=1)
        assert cursor is not None
        # base64.urlsafe_b64decode round-trips and decodes to the {c,j} shape.
        pad = "=" * (-len(cursor) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(cursor + pad).decode("utf-8")
        )
        assert set(payload.keys()) == {"c", "j"}
        assert payload["j"] == "b"


class TestCursorMalformed:
    """A malformed cursor must raise — never silently serve the wrong page."""

    def test_malformed_cursor_raises(self, store: ImportJobStore) -> None:
        with pytest.raises(ValueError):
            store.list_jobs(
                principal="alice", world="demo", limit=10,
                cursor="not-base64-or-json!!",
            )

    def test_cursor_missing_keys_raises(self, store: ImportJobStore) -> None:
        # Valid base64 + JSON, but the wrong shape: only one key.
        bad = base64.urlsafe_b64encode(
            json.dumps({"x": 1}).encode("utf-8"),
        ).decode("ascii").rstrip("=")
        with pytest.raises(ValueError):
            store.list_jobs(
                principal="alice", world="demo", limit=10, cursor=bad,
            )

    def test_cursor_codec_roundtrip(self) -> None:
        c = _encode_cursor("2026-06-01T12:00:00+00:00", "abc-123")
        ca, jid = _decode_cursor(c)
        assert ca == "2026-06-01T12:00:00+00:00"
        assert jid == "abc-123"


# ---------------------------------------------------------------------------
# Redaction — the listing path must never leak the observability token.
# (The router serializes via ``model_dump_redacted``; the store returns the
# model so callers can choose their serialization. The integration tests in
# ``test_import_integration.py`` verify the over-the-wire redaction. Here we
# pin the model's own redaction helper as a defensive contract.)
# ---------------------------------------------------------------------------


class TestRedaction:
    def test_model_dump_redacted_strips_opaque_token(self) -> None:
        job = ImportJob(
            job_id="x", world="w", owner_principal="alice",
            state=ImportJobState.REVIEW, opaque_token="secret",
            created_at="2026-01-01", updated_at="2026-01-01",
        )
        redacted = job.model_dump_redacted()
        assert "opaque_token" not in redacted
        assert redacted["job_id"] == "x"
        assert redacted["state"] == "review"


# ---------------------------------------------------------------------------
# Vision cache (PR2 — sync-lore-in-importer, Phase 4: tasks 4.1-4.5)
# ---------------------------------------------------------------------------


class TestVisionCacheStore:
    """vision_cache: idempotent bootstrap, SHA-256 keys, round trips, fail-open."""

    def test_cache_table_bootstrapped_idempotently(self, store: ImportJobStore) -> None:
        """Task 4.1/4.2 — the table exists on every open (CREATE IF NOT EXISTS)."""
        cols = [r[1] for r in store._conn.execute(
            "PRAGMA table_info(vision_cache)")]
        assert cols == ["hash", "result_json", "created_at"]

    def test_cache_is_global_world_agnostic(self, store: ImportJobStore) -> None:
        """Task 4.5 — the schema carries no world/job scoping: the key is the
        content hash and the result describes image content, not canon."""
        cols = [r[1] for r in store._conn.execute(
            "PRAGMA table_info(vision_cache)")]
        assert "world" not in cols
        assert "job_id" not in cols

    def test_lookup_miss_returns_none(self, store: ImportJobStore) -> None:
        assert store.vision_cache_lookup("no-such-hash") is None

    def test_store_and_lookup_roundtrip(self, store: ImportJobStore) -> None:
        result = VisionResult(
            image_hash="h1", description="Retrato sombrío",
            verdict="confirma", analysis="Coincide con el texto",
            tags=["retrato", "claroscuro"],
        )
        store.vision_cache_store("h1", result)

        got = store.vision_cache_lookup("h1")
        assert got is not None
        assert got.image_hash == "h1"
        assert got.description == "Retrato sombrío"
        assert got.verdict == "confirma"
        assert got.analysis == "Coincide con el texto"
        assert got.tags == ["retrato", "claroscuro"]

    def test_store_overwrites_existing_hash(self, store: ImportJobStore) -> None:
        store.vision_cache_store("h1", VisionResult(
            image_hash="h1", description="old", verdict="no_aplica",
            analysis="", tags=[]))
        store.vision_cache_store("h1", VisionResult(
            image_hash="h1", description="new", verdict="contradice",
            analysis="x", tags=["t"]))

        got = store.vision_cache_lookup("h1")
        assert got is not None
        assert got.description == "new"
        assert got.verdict == "contradice"
        assert got.tags == ["t"]

    def test_lookup_corrupt_json_returns_none(self, store: ImportJobStore) -> None:
        store._conn.execute(
            "INSERT INTO vision_cache (hash, result_json, created_at)"
            " VALUES (?,?,?)", ("h1", "{not json", "2026-01-01T00:00:00"))
        store._conn.commit()
        assert store.vision_cache_lookup("h1") is None

    def test_lookup_non_dict_json_returns_none(self, store: ImportJobStore) -> None:
        store._conn.execute(
            "INSERT INTO vision_cache (hash, result_json, created_at)"
            " VALUES (?,?,?)", ("h1", "[]", "2026-01-01T00:00:00"))
        store._conn.commit()
        assert store.vision_cache_lookup("h1") is None

    def test_lookup_normalizes_verdict(self, store: ImportJobStore) -> None:
        """A stored verdict outside the closed vocabulary degrades to no_aplica."""
        import json as _json
        payload = _json.dumps({"image_hash": "h1", "description": "d",
                               "verdict": "quizas", "analysis": "a", "tags": []})
        store._conn.execute(
            "INSERT INTO vision_cache (hash, result_json, created_at)"
            " VALUES (?,?,?)", ("h1", payload, "2026-01-01T00:00:00"))
        store._conn.commit()
        got = store.vision_cache_lookup("h1")
        assert got is not None
        assert got.verdict == "no_aplica"


# ---------------------------------------------------------------------------
# delete_job — Opción A terminal reaping (job + full cascade)
# ---------------------------------------------------------------------------


class TestDeleteJob:
    """delete_job must remove the job and every cascade-associated row."""

    def _completed_job_with_cascade(self, store) -> None:
        from import_models import (  # noqa: PLC0415
            Approval,
            Candidate,
            ItemOutcome,
            Provenance,
        )
        store.create_job(_job(job_id="jobx", state=ImportJobState.COMPLETED))
        store.add_candidate(Candidate(
            candidate_id="cand1", job_id="jobx", world="demo",
            normalized_identity="A", source_hash="sha256:a",
            provenance=Provenance(source_path="lore/A.md", source_kind="loose",
                                  source_hash="sha256:a"),
            content_preview="body"))
        store.add_item(ItemOutcome(item_id="i1", candidate_id="cand1",
                                   outcome="inserted", detail=""))
        store.add_event("jobx", "created")
        store.save_approval(Approval(
            approval_id="ap1", job_id="jobx", principal="alice", revision=1,
            digest="d", token="t", group_ids=[], issued_at="",
            expires_at="", consumed=False))

    def test_delete_removes_job_and_cascade(self, store) -> None:
        self._completed_job_with_cascade(store)
        assert store.get_job("jobx") is not None
        assert len(store.candidates_for("jobx")) == 1

        store.delete_job("jobx")

        assert store.get_job("jobx") is None
        assert store.candidates_for("jobx") == []
        # Cascade: items (via candidates), events, approvals all gone.
        n_items = store._conn.execute(
            "SELECT COUNT(*) FROM items WHERE candidate_id='cand1'").fetchone()[0]
        n_events = store._conn.execute(
            "SELECT COUNT(*) FROM events WHERE job_id='jobx'").fetchone()[0]
        n_approvals = store._conn.execute(
            "SELECT COUNT(*) FROM approvals WHERE job_id='jobx'").fetchone()[0]
        assert n_items == 0
        assert n_events == 0
        assert n_approvals == 0

    def test_delete_leaves_other_jobs_intact(self, store) -> None:
        from import_models import Candidate, Provenance  # noqa: PLC0415
        store.create_job(_job(job_id="keep", state=ImportJobState.COMPLETED))
        store.create_job(_job(job_id="drop", state=ImportJobState.FAILED))
        store.add_candidate(Candidate(
            candidate_id="c-keep", job_id="keep", world="demo",
            normalized_identity="B", source_hash="sha256:b",
            provenance=Provenance(source_path="lore/B.md", source_kind="loose",
                                  source_hash="sha256:b"),
            content_preview="body"))

        store.delete_job("drop")

        assert store.get_job("drop") is None
        assert store.get_job("keep") is not None
        assert len(store.candidates_for("keep")) == 1

    def test_delete_unknown_job_is_noop(self, store) -> None:
        store.delete_job("no-such-job")  # must not raise


# ---------------------------------------------------------------------------
# created_by_job — source_hash cache ownership survives reassignment/delete
# ---------------------------------------------------------------------------


class TestCreatedByJobCacheOwnership:
    """``created_by_job`` pins a candidate row to the job that INSERTED it.

    The candidates table doubles as the world's ``source_hash`` enrichment
    cache. ``reassign_candidate_to_job`` moves the review surface (``job_id``)
    on a cache-hit re-import but must never touch the origin; ``delete_job``
    then reaps only rows the deleted job created (``job_id=? AND
    created_by_job=?``), preserving adopted cache rows so a later import of
    the same docx does not re-run Hermes.
    """

    @staticmethod
    def _candidate(candidate_id: str, job_id: str,
                   identity: str, source_hash: str) -> Candidate:
        return Candidate(
            candidate_id=candidate_id, job_id=job_id, world="demo",
            normalized_identity=identity, source_hash=source_hash,
            provenance=Provenance(
                source_path=f"lore/{identity}.md", source_kind="loose",
                source_hash=source_hash),
            content_preview="body")

    @staticmethod
    def _created_by(store: ImportJobStore, candidate_id: str) -> str:
        return store._conn.execute(
            "SELECT created_by_job FROM candidates WHERE candidate_id=?",
            (candidate_id,)).fetchone()[0]

    def test_add_candidate_records_creating_job(self, store: ImportJobStore) -> None:
        store.create_job(_job(job_id="job-a", state=ImportJobState.COMPLETED))
        store.add_candidate(self._candidate(
            "cand1", "job-a", "Enciclopedia", "sha256:enc"))

        assert self._created_by(store, "cand1") == "job-a"

    def test_reassign_keeps_created_by_job(self, store: ImportJobStore) -> None:
        store.create_job(_job(job_id="job-a", state=ImportJobState.COMPLETED))
        store.create_job(_job(job_id="job-b", state=ImportJobState.REVIEW))
        store.add_candidate(self._candidate(
            "cand1", "job-a", "Enciclopedia", "sha256:enc"))

        store.reassign_candidate_to_job("cand1", "job-b")

        # Origin pinned to the creating job; review surface moved.
        assert self._created_by(store, "cand1") == "job-a"
        row = store.find_candidate("demo", "sha256:enc", "Enciclopedia")
        assert row is not None
        assert row.job_id == "job-b"

    def test_delete_job_preserves_adopted_cache_row(self, store: ImportJobStore) -> None:
        store.create_job(_job(job_id="job-a", state=ImportJobState.COMPLETED))
        store.create_job(_job(job_id="job-b", state=ImportJobState.REVIEW))
        store.add_candidate(self._candidate(
            "cand1", "job-a", "Enciclopedia", "sha256:enc"))
        store.reassign_candidate_to_job("cand1", "job-b")

        # Re-import job reaped: the adopted cache row must survive.
        store.delete_job("job-b")
        row = store.find_candidate("demo", "sha256:enc", "Enciclopedia")
        assert row is not None
        assert self._created_by(store, "cand1") == "job-a"

        # Deleting the creator job does NOT reap it either: the row's job_id
        # now points at the deleted re-import job, so the ``job_id=? AND
        # created_by_job=?`` predicate matches nothing. The row stays as the
        # world's cache (find_candidate keys on world+source_hash+identity,
        # not job_id) until the world itself is deleted.
        store.delete_job("job-a")
        assert store.find_candidate(
            "demo", "sha256:enc", "Enciclopedia") is not None

    def test_delete_jobs_for_world_still_removes_every_candidate(
            self, store: ImportJobStore) -> None:
        store.create_job(_job(job_id="job-a", state=ImportJobState.COMPLETED))
        store.create_job(_job(job_id="job-b", state=ImportJobState.REVIEW))
        store.add_candidate(self._candidate(
            "cand1", "job-a", "Enciclopedia", "sha256:enc"))
        store.reassign_candidate_to_job("cand1", "job-b")
        store.add_candidate(self._candidate(
            "cand2", "job-b", "Origen", "sha256:origen"))

        removed = store.delete_jobs_for_world("demo")

        assert removed == 2
        assert store.find_candidate("demo", "sha256:enc", "Enciclopedia") is None
        assert store.find_candidate("demo", "sha256:origen", "Origen") is None


# ---------------------------------------------------------------------------
# update_candidate_images — media backfill on re-import
# ---------------------------------------------------------------------------


class TestUpdateCandidateImages:
    """A candidate persisted while media extraction was unavailable (empty
    images_json) must be backfillable from a fresh analysis."""

    def test_backfills_images_on_existing_candidate(self, store) -> None:
        from import_models import Candidate, ImagePlacement, Provenance  # noqa: PLC0415
        store.create_job(_job(job_id="job1", state=ImportJobState.REVIEW))
        store.add_candidate(Candidate(
            candidate_id="cand1", job_id="job1", world="demo",
            normalized_identity="Enciclopedia", source_hash="sha256:same",
            provenance=Provenance(source_path="Lore/Enciclopedia.docx",
                                  source_kind="loose",
                                  source_hash="sha256:same"),
            content_preview="body"))

        # Initially no image placements.
        existing = store.find_candidate("demo", "sha256:same", "Enciclopedia")
        assert existing is not None
        assert existing.images == []

        store.update_candidate_images("cand1", [
            ImagePlacement(gallery_asset_id="",
                           relative_media_path="media/Enciclopedia/img1.png",
                           target_ficha="El Origen"),
        ])

        updated = store.find_candidate("demo", "sha256:same", "Enciclopedia")
        assert updated is not None
        assert len(updated.images) == 1
        assert updated.images[0].relative_media_path == (
            "media/Enciclopedia/img1.png")

    def test_empty_list_is_noop(self, store) -> None:
        from import_models import Candidate, Provenance  # noqa: PLC0415
        store.create_job(_job(job_id="job1", state=ImportJobState.REVIEW))
        store.add_candidate(Candidate(
            candidate_id="cand1", job_id="job1", world="demo",
            normalized_identity="Enciclopedia", source_hash="sha256:same",
            provenance=Provenance(source_path="Lore/Enciclopedia.docx",
                                  source_kind="loose",
                                  source_hash="sha256:same"),
            content_preview="body"))

        store.update_candidate_images("cand1", [])

        existing = store.find_candidate("demo", "sha256:same", "Enciclopedia")
        assert existing is not None
        assert existing.images == []


class TestJobProgressContract:
    """Analysis-progress persistence (long-import live-monitoring fix).

    ``progress_stage``/``progress_pct`` are server-owned, survive round-trips,
    and ``update_progress`` writes them without bumping the optimistic
    revision (so a long synchronous analyze can keep reporting while the
    lease is held).
    """

    def test_round_trip_defaults_empty(self, store: ImportJobStore) -> None:
        store.create_job(_job(job_id="p1"))
        job = store.get_job("p1")
        assert job is not None
        assert job.progress_stage == ""
        assert job.progress_pct is None

    def test_update_progress_persists_without_revision_bump(
            self, store: ImportJobStore) -> None:
        store.create_job(_job(job_id="p2", state=ImportJobState.ANALYZING))
        before = store.get_job("p2")
        assert before is not None

        store.update_progress("p2", "Analizando fuentes", 30)

        after = store.get_job("p2")
        assert after is not None
        assert after.progress_stage == "Analizando fuentes"
        assert after.progress_pct == 30
        # No optimistic-guard bump: the analysis thread can keep reporting
        # while the terminal transition still owns the revision.
        assert after.revision == before.revision

    def test_update_progress_indeterminate(self, store: ImportJobStore) -> None:
        store.create_job(_job(job_id="p3", state=ImportJobState.ANALYZING))
        store.update_progress("p3", "Consultando asistente", None)
        job = store.get_job("p3")
        assert job is not None
        assert job.progress_stage == "Consultando asistente"
        assert job.progress_pct is None

    def test_update_job_accepts_progress_fields(
            self, store: ImportJobStore) -> None:
        store.create_job(_job(job_id="p4", state=ImportJobState.ANALYZING))
        job = store.get_job("p4")
        assert job is not None
        store.update_job(
            "p4", expected_revision=job.revision,
            progress_stage="Construyendo fichas", progress_pct=60)
        after = store.get_job("p4")
        assert after is not None
        assert after.progress_stage == "Construyendo fichas"
        assert after.progress_pct == 60
        assert after.revision == job.revision + 1


# ---------------------------------------------------------------------------
# update_candidate_funnel — persistence of generated frontmatter/summary
# even when enrichment_json is None (zero relationships)
# ---------------------------------------------------------------------------


class TestUpdateCandidateFunnelNoSuggestions:
    """Regression: when Hermes returns summary + frontmatter but zero
    relationships, enrichment_json is None and enrichment_status is
    ``no_suggestions``.  The router must still persist the funnel metadata
    (summary, frontmatter) onto the existing row.  Prior to the fix, the
    ``and candidate.enrichment_json is not None`` gate caused these fields
    to be silently discarded — the row kept its old fallback frontmatter.
    """

    @staticmethod
    def _make_candidate(
        job_id: str = "job-old",
        summary: str = "",
        frontmatter: FrontmatterCandidate | None = None,
        enrichment_json: list | None = None,
        enrichment_status: str = "disabled",
    ) -> Candidate:
        return Candidate(
            candidate_id="cand-v1",
            job_id=job_id,
            world="demo",
            normalized_identity="Seccion/Test",
            source_hash="sha256:test",
            provenance=Provenance(
                source_path="Lore/Test.md",
                source_kind="loose",
                source_hash="sha256:test",
            ),
            content_preview="body",
            summary=summary,
            frontmatter=frontmatter,
            enrichment_json=enrichment_json,
            enrichment_status=enrichment_status,
        )

    def test_update_candidate_funnel_persists_generated_frontmatter(
            self, store: ImportJobStore) -> None:
        """update_candidate_funnel writes the new frontmatter/summary even
        when enrichment_json is None."""
        job = _job(job_id="job-old")
        store.create_job(job)

        # Simulate a row from a prior import with fallback frontmatter.
        old = self._make_candidate(
            summary="",
            frontmatter=FrontmatterCandidate(
                title="Old", state=FrontmatterState.FALLBACK),
            enrichment_status="no_suggestions",
        )
        store.add_candidate(old)
        row_old = store.find_candidate(
            "demo", "sha256:test", "Seccion/Test")
        assert row_old is not None
        assert row_old.summary == ""
        assert row_old.frontmatter is not None
        assert row_old.frontmatter.state == FrontmatterState.FALLBACK

        # New in-memory candidate: summary + generated frontmatter, but
        # enrichment_json=None (zero relationships). This is exactly the
        # funnel output for a card where Hermes returned useful metadata
        # but no link suggestions.
        new = self._make_candidate(
            job_id="job-new",
            summary="Some summary from Hermes",
            frontmatter=FrontmatterCandidate(
                title="Sección Test", type=None,
                state=FrontmatterState.GENERATED),
            enrichment_json=None,
            enrichment_status="no_suggestions",
        )

        # The router's fixed path: always persist enrichment + funnel
        # when (enrich or vision is not None).
        store.update_candidate_enrichment(
            row_old.candidate_id, new.enrichment_json, new.enrichment_status)
        store.update_candidate_funnel(row_old.candidate_id, new)
        store.reassign_candidate_to_job(row_old.candidate_id, "job-new")

        row_after = store.find_candidate("demo", "sha256:test", "Seccion/Test")
        assert row_after is not None
        # Summary must be updated to the new value.
        assert row_after.summary == "Some summary from Hermes"
        # Frontmatter must be the GENERATED one, not the old FALLBACK.
        assert row_after.frontmatter is not None
        assert row_after.frontmatter.state == FrontmatterState.GENERATED
        assert row_after.frontmatter.title == "Sección Test"
        # enrichment_json stays None (no relationships), but status is
        # persisted as no_suggestions.
        assert row_after.enrichment_json is None
        assert row_after.enrichment_status == "no_suggestions"
        # Row must be reassigned to the new job.
        assert row_after.job_id == "job-new"

    def test_update_candidate_enrichment_persists_none_status(
            self, store: ImportJobStore) -> None:
        """update_candidate_enrichment must persist enrichment_status
        (e.g. ``no_suggestions``) even when enrichment_json is None."""
        job = _job(job_id="job-a")
        store.create_job(job)

        old = self._make_candidate(enrichment_status="disabled")
        store.add_candidate(old)
        row = store.find_candidate("demo", "sha256:test", "Seccion/Test")
        assert row is not None
        assert row.enrichment_status == "disabled"

        # Persist enrichment with None JSON but no_suggestions status.
        store.update_candidate_enrichment(
            row.candidate_id, None, "no_suggestions")

        row_after = store.find_candidate("demo", "sha256:test", "Seccion/Test")
        assert row_after is not None
        assert row_after.enrichment_json is None
        assert row_after.enrichment_status == "no_suggestions"


# ---------------------------------------------------------------------------
# BLOQUE 1 piece 1 — per-document classifier persistence (sections_json on the
# job, section on the candidate)
# ---------------------------------------------------------------------------


class TestClassifierSectionsPersistence:
    """Classifier sections survive store round-trips and legacy rows default
    to ``{}``/``""`` (→ the legacy resolve_target branch, zero regression)."""

    def test_job_sections_json_roundtrip(self, store: ImportJobStore) -> None:
        job = _job(job_id="cls-1")
        job.sections = {"a.md": "personajes", "b.md": "referencias"}
        store.create_job(job)
        loaded = store.get_job("cls-1")
        assert loaded is not None
        assert loaded.sections == {"a.md": "personajes", "b.md": "referencias"}

    def test_job_sections_default_empty(self, store: ImportJobStore) -> None:
        store.create_job(_job(job_id="cls-2"))
        loaded = store.get_job("cls-2")
        assert loaded is not None
        assert loaded.sections == {}

    def test_candidate_section_roundtrip(self, store: ImportJobStore) -> None:
        store.create_job(_job(job_id="cls-3"))
        cand = Candidate(
            candidate_id="cand-cls", job_id="cls-3", world="demo",
            normalized_identity="Enciclopedia",
            source_hash="sha256:enc",
            provenance=Provenance(
                source_path="Enciclopedia.md", source_kind="loose",
                source_hash="sha256:enc"),
            content_preview="body",
            section="personajes",
        )
        store.add_candidate(cand)
        row = store.find_candidate("demo", "sha256:enc", "Enciclopedia")
        assert row is not None
        assert row.section == "personajes"

    def test_candidate_section_default_empty(self, store: ImportJobStore) -> None:
        store.create_job(_job(job_id="cls-4"))
        cand = Candidate(
            candidate_id="cand-cls4", job_id="cls-4", world="demo",
            normalized_identity="Origen",
            source_hash="sha256:origen",
            provenance=Provenance(
                source_path="Lore/Origen.md", source_kind="loose",
                source_hash="sha256:origen"),
            content_preview="body",
        )
        store.add_candidate(cand)
        row = store.find_candidate("demo", "sha256:origen", "Origen")
        assert row is not None
        assert row.section == ""

    def test_update_candidate_section_overwrites_stale_empty_on_reimport(
            self, store: ImportJobStore) -> None:
        """Regression (re-import of already-existing content): the existing row
        was created before the section classifier (section=''), and a re-import
        of the SAME content must persist the author's fresh section choice.
        Without ``update_candidate_section`` the stale ``section=''`` row
        survives and every ficha falls into "requires your decision"
        (unknown section), so the section never applies on re-import."""
        store.create_job(_job(job_id="cls-reimport"))
        # First import: section empty (pre-classifier row).
        first = Candidate(
            candidate_id="cand-first", job_id="cls-reimport", world="demo",
            normalized_identity="Enciclopedia",
            source_hash="sha256:enc",
            provenance=Provenance(
                source_path="Enciclopedia.md", source_kind="loose",
                source_hash="sha256:enc"),
            content_preview="body",
            section="",
        )
        store.add_candidate(first)
        # Re-import: the author chose ``lore`` this time.
        reimport = Candidate(
            candidate_id="cand-first", job_id="cls-reimport", world="demo",
            normalized_identity="Enciclopedia",
            source_hash="sha256:enc",
            provenance=Provenance(
                source_path="Enciclopedia.md", source_kind="loose",
                source_hash="sha256:enc"),
            content_preview="body",
            section="lore",
            target_resolution={"canonical_path": "lore/Enciclopedia.md",
                               "status": "resolved"},
        )
        store.update_candidate_section(reimport.candidate_id, reimport)

        row = store.find_candidate("demo", "sha256:enc", "Enciclopedia")
        assert row is not None
        assert row.section == "lore", (
            f"re-import must persist the fresh section, got {row.section!r}")
        assert row.target_resolution is not None
        assert row.target_resolution.get("status") == "resolved"

    def test_legacy_db_bootstraps_classifier_columns(self, tmp_path) -> None:
        """Legacy databases (no ``sections_json``/``section`` columns) get
        both columns via idempotent bootstrap; legacy rows read back as
        ``{}``/``""`` and reopening stays idempotent."""
        db_path = tmp_path / "legacy.sqlite3"
        conn = sqlite3.connect(db_path)
        conn.executescript(_LEGACY_SCHEMA)
        conn.execute(
            "INSERT INTO jobs (job_id, world, owner_principal, state,"
            " created_at, updated_at)"
            " VALUES ('legacy-job', 'demo', 'alice', 'pending', 't', 't')")
        conn.execute(
            "INSERT INTO candidates (candidate_id, job_id, world,"
            " normalized_identity, source_hash, provenance_json, content_preview)"
            " VALUES ('legacy-cand', 'legacy-job', 'demo', 'Origen',"
            " 'sha256:abc',"
            " '{\"source_path\": \"lore/Origen.md\", \"source_kind\": \"loose\","
            " \"source_hash\": \"sha256:abc\"}', 'body')")
        conn.commit()
        conn.close()

        store = ImportJobStore(db_path)  # bootstrap runs on open
        job_cols = {
            row[1] for row in store._conn.execute(
                "PRAGMA table_info(jobs)").fetchall()
        }
        cand_cols = {
            row[1] for row in store._conn.execute(
                "PRAGMA table_info(candidates)").fetchall()
        }
        assert "sections_json" in job_cols
        assert "section" in cand_cols

        # Legacy rows deserialize defensively (fail-open defaults).
        job = store.get_job("legacy-job")
        assert job is not None
        assert job.sections == {}
        cand = store.find_candidate("demo", "sha256:abc", "Origen")
        assert cand is not None
        assert cand.section == ""

        # Reopening is idempotent (no duplicate-column crash).
        store2 = ImportJobStore(db_path)
        assert {
            row[1] for row in store2._conn.execute(
                "PRAGMA table_info(jobs)").fetchall()
        } == job_cols


_LEGACY_SCHEMA = """
CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY, world TEXT NOT NULL, owner_principal TEXT NOT NULL,
    state TEXT NOT NULL, source_kind TEXT NOT NULL DEFAULT 'loose',
    aggregate_uncompressed_bytes INTEGER NOT NULL DEFAULT 0,
    aggregate_compressed_bytes INTEGER NOT NULL DEFAULT 0,
    file_count INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '', opaque_token TEXT NOT NULL DEFAULT '',
    lease_owner TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE candidates (
    candidate_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, world TEXT NOT NULL,
    normalized_identity TEXT NOT NULL, source_hash TEXT NOT NULL,
    provenance_json TEXT NOT NULL, content_preview TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending', okf_issues_json TEXT NOT NULL DEFAULT '[]',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    UNIQUE (world, source_hash, normalized_identity));
CREATE TABLE items (
    item_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'pending', detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL);
CREATE TABLE events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
    event TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE approvals (
    approval_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, principal TEXT NOT NULL,
    revision INTEGER NOT NULL, digest TEXT NOT NULL, token TEXT NOT NULL,
    group_ids_json TEXT NOT NULL DEFAULT '[]', issued_at TEXT NOT NULL DEFAULT '',
    expires_at TEXT NOT NULL DEFAULT '', consumed INTEGER NOT NULL DEFAULT 0,
    UNIQUE (job_id, token));
"""
