"""Durable contract tests for the SQLite-backed CoCreationSessionStore.

Covers: create/recover/commit, revision conflicts (409 at the protocol layer),
30-day TTL expiry, principal binding (403 semantics), milestone advancement,
the question ceiling, and ``draft_payload`` accumulation. Mirrors the
``test_guided_session_store`` harness.
"""

from __future__ import annotations

import sqlite3
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
    HISTORY_CAP,
    CoCreationSessionStore,
    SESSION_TTL,
    default_db_path,
)
from methodology_compiler import MethodologyIssue  # noqa: E402


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


# ---------------------------------------------------------------------------
# TW12 canvas data layer — autosave / history / warnings / pending questions
# ---------------------------------------------------------------------------

def test_autosave_payload_merges_and_snapshots_history(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    store.create("s-1", "author-1", "author-1")
    saved = store.autosave_payload("s-1", "author-1", 0, {"purpose": "automatizar importes"})
    assert saved is not None
    assert saved.revision == 1
    assert saved.draft_payload["purpose"] == "automatizar importes"
    assert len(saved.draft_history) == 1
    entry = saved.draft_history[0]
    assert entry.revision == 1
    assert entry.source == "autosave"
    assert entry.payload == {"purpose": "automatizar importes"}
    assert entry.ts
    recovered = store.recover("s-1", "author-1")
    assert recovered is not None
    assert len(recovered.draft_history) == 1
    assert recovered.draft_history[0].payload == {"purpose": "automatizar importes"}
    store.close()


def test_autosave_payload_caps_history_at_50_evicting_oldest(tmp_path: Path) -> None:
    assert HISTORY_CAP == 50
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    store.create("s-1", "author-1", "author-1")
    state = None
    for revision in range(51):
        state = store.autosave_payload(
            "s-1", "author-1", revision, {"purpose": f"edicion-{revision}"},
        )
        assert state is not None
    assert state is not None
    assert len(state.draft_history) == HISTORY_CAP
    # The oldest snapshot (revision 1) is evicted; the newest is present.
    revisions = [entry.revision for entry in state.draft_history]
    assert revisions[0] == 2
    assert revisions[-1] == 51
    assert state.draft_payload["purpose"] == "edicion-50"
    store.close()


def test_autosave_payload_is_revision_guarded_and_principal_bound(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    store.create("s-1", "author-1", "author-1")
    assert store.autosave_payload("s-1", "author-1", 0, {"purpose": "x"}) is not None
    # A stale base revision fails closed.
    assert store.autosave_payload("s-1", "author-1", 0, {"scope": "stale"}) is None
    # A foreign principal fails closed.
    assert store.autosave_payload("s-1", "other", 1, {"scope": "x"}) is None
    recovered = store.recover("s-1", "author-1")
    assert recovered is not None
    assert recovered.draft_payload == {"purpose": "x"}
    assert len(recovered.draft_history) == 1
    store.close()


def test_autosave_payload_never_merges_chat_owned_pending_questions(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    store.create("s-1", "author-1", "author-1")
    store.append_pending_question("s-1", "author-1", 0, "¿Cuál es el propósito?")
    # A canvas autosave carrying pending_questions must NOT overwrite the
    # chat-appended entry (REQ-CC-14: the chat owns the list).
    saved = store.autosave_payload("s-1", "author-1", 1, {
        "purpose": "automatizar",
        "pending_questions": [{"text": "forjada", "state": "resuelta"}],
    })
    assert saved is not None
    assert saved.draft_payload["pending_questions"] == [
        {"text": "¿Cuál es el propósito?", "state": "pendiente"},
    ]
    assert saved.draft_payload["purpose"] == "automatizar"
    store.close()


def test_list_history_returns_immutable_snapshots(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    store.create("s-1", "author-1", "author-1")
    store.autosave_payload("s-1", "author-1", 0, {"purpose": "a"})
    store.autosave_payload("s-1", "author-1", 1, {"purpose": "b"})
    entries = store.list_history("s-1", "author-1")
    assert entries is not None
    assert [entry.revision for entry in entries] == [1, 2]
    assert [entry.source for entry in entries] == ["autosave", "autosave"]
    # Mutating the returned list never touches the store.
    entries.pop()
    recovered = store.recover("s-1", "author-1")
    assert recovered is not None and len(recovered.draft_history) == 2
    # An unknown session fails closed.
    assert store.list_history("ghost", "author-1") is None
    store.close()


def test_restore_payload_is_revision_guarded_and_restores_snapshot(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    store.create("s-1", "author-1", "author-1")
    store.autosave_payload("s-1", "author-1", 0, {"purpose": "v1"})
    store.autosave_payload("s-1", "author-1", 1, {"purpose": "v2", "scope": "s2"})
    # A stale base revision fails closed (REQ-CC-15 revision guard).
    assert store.restore_payload("s-1", "author-1", 1, 1) is None
    restored = store.restore_payload("s-1", "author-1", 2, 1)
    assert restored is not None
    assert restored.revision == 3
    assert restored.draft_payload == {"purpose": "v1"}
    # The restore itself is recorded as an author-originated snapshot.
    assert restored.draft_history[-1].source == "author"
    assert restored.draft_history[-1].payload == {"purpose": "v1"}
    # An unknown target snapshot fails closed.
    assert store.restore_payload("s-1", "author-1", 3, 99) is None
    # A foreign principal fails closed.
    assert store.restore_payload("s-1", "other", 3, 1) is None
    store.close()


def test_set_warning_status_transitions_and_never_auto_clears(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    store.create("s-1", "author-1", "author-1")
    issue = MethodologyIssue("authority-claim", "Source contains an authority marker.", "source")
    saved = store.autosave_payload("s-1", "author-1", 0, {"purpose": "x"}, issues=[issue])
    assert saved is not None
    assert len(saved.warnings) == 1
    assert saved.warnings[0].state == "pendiente"
    # The Author transitions Pendiente -> Resuelta.
    resolved = store.set_warning_status("s-1", "author-1", 1, 0, "resuelta")
    assert resolved is not None
    assert resolved.warnings[0].state == "resuelta"
    # REQ-CC-13: pending warnings NEVER auto-clear and Author decisions are
    # never undone — even when validation reports ZERO issues afterwards.
    after = store.autosave_payload("s-1", "author-1", 2, {"purpose": "limpio"}, issues=[])
    assert after is not None
    assert after.warnings[0].state == "resuelta"
    # Invalid transitions fail closed: no re-open, no invalid state, bad idx,
    # stale revision.
    assert store.set_warning_status("s-1", "author-1", 3, 0, "pendiente") is None
    assert store.set_warning_status("s-1", "author-1", 3, 0, "nonsense") is None
    assert store.set_warning_status("s-1", "author-1", 3, 9, "resuelta") is None
    assert store.set_warning_status("s-1", "author-1", 1, 0, "resuelta") is None
    store.close()


def test_append_pending_question_appends_pendiente_and_dedups_consecutive(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    store.create("s-1", "author-1", "author-1")
    first = store.append_pending_question("s-1", "author-1", 0, "¿Cuál es el propósito?")
    assert first is not None
    assert first.revision == 1
    assert first.draft_payload["pending_questions"] == [
        {"text": "¿Cuál es el propósito?", "state": "pendiente"},
    ]
    # A consecutive duplicate is not re-appended.
    again = store.append_pending_question("s-1", "author-1", 1, "¿Cuál es el propósito?")
    assert again is not None
    assert len(again.draft_payload["pending_questions"]) == 1
    second = store.append_pending_question("s-1", "author-1", 2, "¿Qué alcance tiene?")
    assert second is not None
    assert len(second.draft_payload["pending_questions"]) == 2
    assert second.draft_payload["pending_questions"][1]["state"] == "pendiente"
    # Invalid inputs fail closed.
    assert store.append_pending_question("s-1", "author-1", 3, "  ") is None
    assert store.append_pending_question("s-1", "other", 3, "x") is None
    store.close()


def test_set_pending_question_status_author_only_transitions(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = CoCreationSessionStore(db)
    store.create("s-1", "author-1", "author-1")
    store.append_pending_question("s-1", "author-1", 0, "¿Cuál es el propósito?")
    # Pendiente -> Aceptada_por_Autor is allowed (never re-asked, REQ-CC-14).
    accepted = store.set_pending_question_status("s-1", "author-1", 1, 0, "aceptada_por_autor")
    assert accepted is not None
    assert accepted.draft_payload["pending_questions"][0]["state"] == "aceptada_por_autor"
    # A second entry can still go Pendiente -> Resuelta.
    store.append_pending_question("s-1", "author-1", 2, "¿Qué alcance tiene?")
    resolved = store.set_pending_question_status("s-1", "author-1", 3, 1, "resuelta")
    assert resolved is not None
    assert resolved.draft_payload["pending_questions"][1]["state"] == "resuelta"
    # Non-Pendiente entries cannot be re-opened; bad idx/state/stale fail closed.
    assert store.set_pending_question_status("s-1", "author-1", 4, 0, "pendiente") is None
    assert store.set_pending_question_status("s-1", "author-1", 4, 9, "resuelta") is None
    assert store.set_pending_question_status("s-1", "author-1", 4, 0, "nonsense") is None
    assert store.set_pending_question_status("s-1", "author-1", 1, 0, "resuelta") is None
    store.close()


def test_canvas_state_survives_restart(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    first = CoCreationSessionStore(db)
    first.create("s-1", "author-1", "author-1")
    first.autosave_payload("s-1", "author-1", 0, {"purpose": "sobrevive"})
    first.close()

    restarted = CoCreationSessionStore(db)
    recovered = restarted.recover("s-1", "author-1")
    assert recovered is not None
    assert len(recovered.draft_history) == 1
    assert recovered.draft_history[0].payload == {"purpose": "sobrevive"}
    assert recovered.warnings == []
    assert recovered.derived_from is None
    restarted.close()


def test_additive_columns_migrate_existing_database(tmp_path: Path) -> None:
    """A Fase 4 database without the TW12 columns opens and keeps working."""
    db = tmp_path / "sessions.sqlite3"
    legacy = sqlite3.connect(str(db))
    legacy.execute("""
        CREATE TABLE co_creation_sessions (
            session_id TEXT PRIMARY KEY,
            principal_id TEXT NOT NULL,
            world TEXT,
            revision INTEGER NOT NULL DEFAULT 0,
            authorization_binding TEXT NOT NULL,
            milestone TEXT NOT NULL DEFAULT 'proposito',
            milestone_states_json TEXT NOT NULL,
            question_count INTEGER NOT NULL DEFAULT 0,
            draft_payload_json TEXT NOT NULL DEFAULT '{}',
            messages_json TEXT NOT NULL DEFAULT '[]',
            pending_question TEXT,
            pending_options_json TEXT NOT NULL DEFAULT '[]',
            draft_id TEXT,
            phase TEXT NOT NULL DEFAULT 'conversation',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            revalidation_required INTEGER NOT NULL DEFAULT 0
        )
    """)
    now = datetime.now(timezone.utc).isoformat()
    legacy.execute(
        "INSERT INTO co_creation_sessions ("
        " session_id, principal_id, world, revision, authorization_binding,"
        " milestone, milestone_states_json, question_count, draft_payload_json,"
        " messages_json, created_at, updated_at)"
        " VALUES (?, ?, NULL, 0, ?, 'proposito', '[]', 0, ?, '[]', ?, ?)",
        ("legacy-1", "author-1", "author-1", '{"purpose": "viejo"}', now, now),
    )
    legacy.commit()
    legacy.close()

    store = CoCreationSessionStore(db)
    recovered = store.recover("legacy-1", "author-1")
    assert recovered is not None
    assert recovered.draft_payload == {"purpose": "viejo"}
    assert recovered.draft_history == []
    assert recovered.warnings == []
    assert recovered.derived_from is None
    # The migrated row accepts TW12 mutations (new columns are writable).
    saved = store.autosave_payload("legacy-1", "author-1", 0, {"purpose": "nuevo"})
    assert saved is not None
    assert len(saved.draft_history) == 1
    store.close()