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
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _p in (str(_WIKI),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from import_models import (  # noqa: E402
    ImportJob,
    ImportJobState,
    utcnow_iso,
)
from import_store import (  # noqa: E402
    ImportJobStore,
    _decode_cursor,
    _encode_cursor,
)


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
