"""Durable contract tests for the SQLite-backed CoCreationSessionStore.

Covers: create/recover/commit, revision conflicts (409 at the protocol layer),
30-day TTL expiry, principal binding (403 semantics), milestone advancement,
the question ceiling, and ``draft_payload`` accumulation. Mirrors the
``test_guided_session_store`` harness.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from co_creation_protocol import (  # noqa: E402
    CoCreationRequest,
    CoCreationResponse,
    CoCreationOutcome,
    PROTOCOL_VERSION,
    QUESTION_CEILING,
)
import co_creation_session_store  # noqa: E402
from co_creation_session_store import (  # noqa: E402
    CoCreationSessionStore,
    SESSION_TTL,
    default_db_path,
)


def _request(
    session_id: str, auth: str, revision: int = 0, author_input: str = "I want a skill",
) -> CoCreationRequest:
    return CoCreationRequest(
        PROTOCOL_VERSION, "req-1", session_id, "author-1", revision, auth, author_input,
    )


def _question_response(request: CoCreationRequest, question: str = "What is the purpose?") -> CoCreationResponse:
    return CoCreationResponse(
        PROTOCOL_VERSION, request.request_id, request.session_id,
        request.base_revision, CoCreationOutcome.QUESTION,
        question=question, options=("A", "B"), provenance=("hermes:run:r1",),
    )


def _delta_response(request: CoCreationRequest, milestone: str = "alcance") -> CoCreationResponse:
    return CoCreationResponse(
        PROTOCOL_VERSION, request.request_id, request.session_id,
        request.base_revision, CoCreationOutcome.MILESTONE_DELTA,
        milestone=milestone, provenance=("hermes:run:r1",),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_create_recover_commit_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    state = store.create("s-1", "author-1", "author-1", world="nec")
    assert state.revision == 0
    assert state.milestone == "proposito"
    assert state.question_count == 0
    assert state.world == "nec"

    request = _request("s-1", "author-1")
    committed = store.commit(request, _question_response(request))
    assert committed is not None
    assert committed.revision == 1
    assert committed.question_count == 1
    assert committed.pending_question == "What is the purpose?"
    assert committed.pending_options == ("A", "B")
    assert committed.messages[-1].role == "assistant"

    recovered = store.recover("s-1", "author-1")
    assert recovered is not None
    assert recovered.revision == 1
    assert recovered.pending_question == "What is the purpose?"
    store.close()


def test_revision_conflict_fails_closed(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    store.create("s-1", "author-1", "author-1")
    request = _request("s-1", "author-1")
    assert store.commit(request, _question_response(request)) is not None
    # A stale writer (base_revision 0 against revision 1) must fail closed.
    assert store.commit(request, _question_response(request)) is None
    assert store.recover("s-1", "author-1").revision == 1  # type: ignore[union-attr]
    store.close()


def test_ttl_expiry_discards_sessions(tmp_path: Path) -> None:
    assert SESSION_TTL == timedelta(days=30)
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    store.create("s-1", "author-1", "author-1")

    far_future = _now() + timedelta(days=31)
    assert store.discard_expired(now=far_future) == 1
    assert store.recover("s-1", "author-1") is None
    store.close()


def test_principal_binding_returns_none_for_wrong_principal(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    store.create("s-1", "author-1", "author-1")
    assert store.recover("s-1", "other") is None
    request = _request("s-1", "other")
    assert store.commit(request, _question_response(request)) is None
    assert store.merge_draft_payload("s-1", "other", 0, {"purpose": "x"}) is None
    assert store.recover("s-1", "author-1") is not None
    store.close()


def test_milestone_advancement_via_milestone_delta(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    store.create("s-1", "author-1", "author-1")
    request = _request("s-1", "author-1")
    committed = store.commit(request, _delta_response(request, milestone="alcance"))
    assert committed is not None
    assert committed.milestone == "alcance"
    names = [item.name for item in committed.milestone_states]
    states = [item.state for item in committed.milestone_states]
    assert names == [
        "proposito", "alcance", "flujo_principal", "ramas_reglas",
        "borrador_listo", "revision_publicacion",
    ]
    assert states[:2] == ["completado", "actual"]
    assert states[2:] == ["pendiente"] * 4
    store.close()


def test_question_ceiling_is_tracked_and_detected(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    store.create("s-1", "author-1", "author-1")
    for revision in range(QUESTION_CEILING):
        request = _request("s-1", "author-1", revision=revision)
        assert store.commit(request, _question_response(request)) is not None
    assert store.at_ceiling("s-1", "author-1") is True
    recovered = store.recover("s-1", "author-1")
    assert recovered is not None and recovered.question_count == QUESTION_CEILING
    # A further turn is still gated at the store level by the stale revision
    # guard, and at the protocol level by the ceiling (covered there).
    store.close()


def test_draft_payload_accumulates_across_merges(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    store.create("s-1", "author-1", "author-1")
    first = store.merge_draft_payload("s-1", "author-1", 0, {"purpose": "automate imports"})
    assert first is not None
    second = store.merge_draft_payload("s-1", "author-1", 1, {"scope": "mundo específico", "world": "nec"})
    assert second is not None
    assert second.draft_payload == {
        "purpose": "automate imports",
        "scope": "mundo específico",
        "world": "nec",
    }
    recovered = store.recover("s-1", "author-1")
    assert recovered is not None and recovered.draft_payload["scope"] == "mundo específico"
    store.close()


def test_world_binding_null_for_transversal(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    store.create("s-global", "author-1", "author-1", world=None)
    recovered = store.recover("s-global", "author-1")
    assert recovered is not None and recovered.world is None
    store.close()


def test_record_draft_sets_draft_id_and_materialized_phase(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    store.create("s-1", "author-1", "author-1")
    state = store.record_draft("s-1", "author-1", 0, "draft-abc")
    assert state is not None
    assert state.draft_id == "draft-abc"
    assert state.phase == "materialized"
    recovered = store.recover("s-1", "author-1")
    assert recovered is not None and recovered.phase == "materialized"
    store.close()


def test_set_phase_validates_and_guards_revision(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    store.create("s-1", "author-1", "author-1")
    assert store.set_phase("s-1", "author-1", 0, "review") is not None
    # Unknown phase rejected.
    assert store.set_phase("s-1", "author-1", 1, "nonsense") is None
    # Stale revision rejected.
    assert store.set_phase("s-1", "author-1", 0, "complete") is None
    store.close()


def test_durable_restart_survival(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    first = CoCreationSessionStore(db)
    first.create("s-1", "author-1", "author-1", world="nec")
    request = _request("s-1", "author-1")
    first.commit(request, _question_response(request))
    first.close()

    restarted = CoCreationSessionStore(db)
    state = restarted.recover("s-1", "author-1")
    assert state is not None
    assert state.revision == 1
    assert state.question_count == 1
    assert state.world == "nec"
    restarted.close()


def test_default_configuration_resolves_to_durable_local_path(monkeypatch, tmp_path: Path) -> None:
    default = tmp_path / "data" / "co-creation-sessions.sqlite3"
    monkeypatch.setattr(co_creation_session_store, "default_db_path", lambda: default)

    resolved = default_db_path()
    assert resolved.parent.name == "data"
    assert resolved.name == "co-creation-sessions.sqlite3"
    assert ":memory:" not in str(resolved)

    store = CoCreationSessionStore()
    assert store._db_path == str(default)  # noqa: SLF001
    assert default.exists()
    store.close()


def test_explicit_memory_path_still_supported(monkeypatch, tmp_path: Path) -> None:
    default = tmp_path / "data" / "co-creation-sessions.sqlite3"
    monkeypatch.setattr(co_creation_session_store, "default_db_path", lambda: default)

    first = CoCreationSessionStore(":memory:")
    assert first._db_path == ":memory:"  # noqa: SLF001
    first.create("s-mem-1", "author-1", "author-1")
    first.close()

    second = CoCreationSessionStore(":memory:")
    assert second.recover("s-mem-1", "author-1") is None
    second.close()


def test_unknown_session_fails_closed(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    assert store.recover("legacy-session-1", "author-1") is None
    assert store.at_ceiling("legacy-session-1", "author-1") is False
    store.close()