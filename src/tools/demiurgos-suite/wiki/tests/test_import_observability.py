# -*- coding: utf-8 -*-
"""World importer slice 4 — structured, redacted observability keyed by the
opaque job ID (task 4.3). The public REST surface never reveals the opaque
token; operators correlate observability out-of-band by the token, and the
observability payload is redacted (no content previews, no candidate internals,
no approval tokens/digests)."""

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
from import_store import ImportJobStore  # noqa: E402


def _job(job_id: str = "job1", token: str = "opaque-secret") -> ImportJob:
    return ImportJob(
        job_id=job_id, world="world1", owner_principal="tester",
        state=ImportJobState.PENDING, source_kind="loose",
        opaque_token=token, created_at=utcnow_iso(), updated_at=utcnow_iso(),
    )


@pytest.fixture
def store():
    return ImportJobStore(":memory:")


def test_observability_keyed_by_opaque_token_unknown_is_none(store):
    # An unknown opaque token yields no observability (fail closed).
    assert store.observability("nope") is None


def test_observability_redacts_sensitive_fields(store):
    store.create_job(_job())
    obs = store.observability("opaque-secret")
    assert obs is not None
    assert obs["job_id"] == "job1"
    # The opaque token itself must never leak through observability.
    assert "opaque_token" not in obs
    assert "opaque-secret" not in obs
    # No candidate content or approval secrets.
    assert "content_preview" not in obs
    assert "approval" not in obs
    assert "digest" not in obs
    assert "token" not in obs


def test_observability_tracks_state_and_accounting(store):
    job = _job()
    store.create_job(job)
    job = store.update_job(job.job_id, expected_revision=0,
                           state=ImportJobState.REVIEW, file_count=2,
                           aggregate_uncompressed_bytes=1234)
    obs = store.observability("opaque-secret")
    assert obs["state"] == "review"
    assert obs["file_count"] == 2
    assert obs["aggregate_uncompressed_bytes"] == 1234
    assert obs["revision"] >= 1


def test_observability_events_and_item_outcomes(store):
    from import_models import Candidate, ItemOutcome, Provenance

    store.create_job(_job())
    store.add_event("job1", "created")
    store.add_event("job1", "analysis_complete")
    store.add_candidate(Candidate(
        candidate_id="c1", job_id="job1", world="world1",
        normalized_identity="A", source_hash="sha256:A",
        provenance=Provenance(source_path="lore/A.md", source_kind="loose",
                               source_hash="sha256:A"),
    ))
    store.add_item(ItemOutcome(item_id="i1", candidate_id="c1",
                               outcome="completed", detail=""))
    obs = store.observability("opaque-secret")
    events = [e["event"] for e in obs["events"]]
    assert "created" in events
    assert "analysis_complete" in events
    assert obs["item_outcomes"] == {"completed": 1}


def test_observability_counts_approvals(store):
    from import_models import Approval

    store.create_job(_job())
    store.save_approval(Approval(
        approval_id="a1", job_id="job1", principal="tester", revision=0,
        digest="d", token="tok"))
    obs = store.observability("opaque-secret")
    assert obs["approval_count"] == 1


def test_public_redacted_dump_never_leaks_opaque_token(store):
    # The REST view (model_dump_redacted) must never contain the opaque token
    # that keys observability.
    job = _job()
    store.create_job(job)
    redacted = store.get_job("job1").model_dump_redacted()
    assert "opaque_token" not in redacted
    assert "opaque-secret" not in str(redacted)
