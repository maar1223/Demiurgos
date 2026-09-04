"""Durable Skill Madre co-creation session store backed by stdlib SQLite.

Mirrors the proven ``guided_session_store`` durability contract: sessions are
principal-bound (``authorization_binding``), carry a server-owned revision, and
expire after ``SESSION_TTL`` (30 days). The milestone state machine (6
milestones) and the question ceiling are server-owned; the accumulated
structured answers live in ``draft_payload_json`` and are never materialized
into a library draft until the Author confirms at ``borrador_listo``.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from co_creation_protocol import (
    CoCreationMessage,
    CoCreationRequest,
    CoCreationResponse,
    CoCreationSessionState,
    DerivedFrom,
    DraftHistoryEntry,
    DraftWarning,
    MilestoneState,
    QUESTION_CEILING,
    HistorySource,
    initial_milestone_states,
    states_for_milestone,
)
from methodology_compiler import MethodologyIssue


SESSION_TTL = timedelta(days=30)

# Immutable autosave snapshot cap per session (REQ-CC-15: ~50, oldest evicted).
HISTORY_CAP = 50

# Author-only warning/pending-question transitions (REQ-CC-13 / REQ-CC-14):
# Pendiente -> Resuelta | Aceptada_por_Autor. Nothing else is allowed; pending
# warnings never auto-correct and only the Author moves them out of Pendiente.
_AUTHOR_TRANSITIONS = frozenset({
    ("pendiente", "resuelta"),
    ("pendiente", "aceptada_por_autor"),
})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS co_creation_sessions (
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
    revalidation_required INTEGER NOT NULL DEFAULT 0,
    draft_history_json TEXT NOT NULL DEFAULT '[]',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    derived_from_json TEXT
)
"""

# Additive TW12 columns (design: no data migration; nullable/empty default).
_ADDITIVE_COLUMNS = (
    ("draft_history_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("warnings_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("derived_from_json", "TEXT"),
)

_PHASES = frozenset({"conversation", "materialized", "review", "complete"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _append_pending_question(draft_payload: dict[str, Any], text: str) -> None:
    """Chat-owned pending-question append (REQ-CC-14).

    The question enters with state ``pendiente``; consecutive duplicates are
    not re-appended. Entries may already exist as legacy plain strings.
    """
    questions = draft_payload.setdefault("pending_questions", [])
    if questions:
        last = questions[-1]
        if (isinstance(last, Mapping) and last.get("text") == text) or last == text:
            return
    questions.append({"text": text, "state": "pendiente"})


def _reconcile_warnings(
    warnings: list[DraftWarning],
    issues: Sequence[MethodologyIssue],
) -> None:
    """Keep-or-append warning reconciliation (REQ-CC-13).

    A warning is identified by ``(code, field)``. Existing warnings keep their
    state — pending warnings NEVER auto-correct and Author decisions are never
    undone — while issues without a matching warning append a new Pendiente
    entry. Stale warnings (issue no longer present) remain untouched.
    """
    known = {(warning.code, warning.field) for warning in warnings}
    for issue in issues:
        key = (issue.code, issue.field)
        if key in known:
            continue
        warnings.append(DraftWarning(
            code=issue.code, message=issue.message, field=issue.field,
            state="pendiente",
        ))
        known.add(key)


def default_db_path() -> Path:
    """Durable repo-local default for the co-creation sessions database.

    Follows the project convention of storing local SQLite state under the
    repository ``data/`` directory (see ``data/guided-sessions.sqlite3``).
    """
    return Path(__file__).resolve().parents[4] / "data" / "co-creation-sessions.sqlite3"


class CoCreationSessionStore:
    """Durable SQLite implementation of the co-creation session contract.

    Every mutation runs under a thread lock and bumps the revision, so stale
    writers fail closed instead of silently overwriting newer state.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = default_db_path()
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self._db_path, check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()
        self._in_process: set[str] = set()
        self.discard_expired()

    def _ensure_schema(self) -> None:
        """Create the table and apply additive TW12 columns idempotently.

        ``CREATE TABLE IF NOT EXISTS`` never alters an existing table, so a
        Fase 4 database file gets the new columns via guarded ``ALTER TABLE``
        (additive, nullable/empty default — design: no data migration).
        """
        self._conn.execute(_SCHEMA)
        existing = {
            row[1] for row in self._conn.execute(
                "PRAGMA table_info(co_creation_sessions)"
            )
        }
        for name, ddl in _ADDITIVE_COLUMNS:
            if name not in existing:
                self._conn.execute(
                    f"ALTER TABLE co_creation_sessions ADD COLUMN {name} {ddl}"
                )
        self._conn.commit()

    # -- public lifecycle ---------------------------------------------------

    def create(
        self,
        session_id: str,
        principal_id: str,
        authorization_binding: str,
        world: str | None = None,
        author_input: str = "",
        *,
        seed_payload: Mapping[str, Any] | None = None,
        draft_id: str | None = None,
        derived_from: DerivedFrom | None = None,
    ) -> CoCreationSessionState:
        if world is not None and (not isinstance(world, str) or not world.strip()):
            raise ValueError("world must be a non-empty string or None")
        with self._lock:
            if self._read_row(session_id, authorization_binding) is not None:
                raise ValueError("session already exists")
            state = CoCreationSessionState(
                session_id=session_id,
                principal_id=principal_id,
                world=world,
                revision=0,
                authorization_binding=authorization_binding,
                milestone="proposito",
                milestone_states=initial_milestone_states(),
                question_count=0,
                draft_payload=dict(seed_payload) if seed_payload else {},
                messages=(
                    [CoCreationMessage("author", author_input, 0)]
                    if author_input.strip() else []
                ),
                draft_id=draft_id,
                derived_from=derived_from,
            )
            self._write_state(state, revalidation_required=0)
            self._in_process.add(session_id)
        return deepcopy(state)

    def recover(
        self,
        session_id: str,
        authorization_binding: str,
        now: datetime | None = None,
    ) -> CoCreationSessionState | None:
        now = now or _utcnow()
        with self._lock:
            self._discard_expired(now)
            row = self._read_row(session_id, authorization_binding)
            if row is None:
                return None
            return deepcopy(self._deserialize_row(row))

    def commit(
        self,
        request: CoCreationRequest,
        response: CoCreationResponse,
    ) -> CoCreationSessionState | None:
        """One turn: append messages, advance milestone/count, persist."""
        with self._lock:
            row = self._read_row(request.session_id, request.authorization_binding)
            if row is None:
                return None
            state = self._deserialize_row(row)
            if state.revision != request.base_revision:
                return None
            next_state = deepcopy(state)
            next_state.revision += 1
            next_state.messages.append(
                CoCreationMessage("author", request.author_input, next_state.revision)
            )
            assistant_content = response.question or response.milestone or "turn"
            next_state.messages.append(
                CoCreationMessage("assistant", assistant_content, next_state.revision)
            )
            next_state.pending_question = response.question
            next_state.pending_options = response.options
            next_state.question_count += 1
            if response.question:
                # REQ-CC-14: the chat owns ``pending_questions`` — every asked
                # question lands on the canvas read-only list (state Pendiente).
                _append_pending_question(next_state.draft_payload, response.question)
            if response.milestone:
                next_state.milestone = response.milestone
                next_state.milestone_states = states_for_milestone(response.milestone)
            self._write_state(next_state)
            self._in_process.add(request.session_id)
            return deepcopy(next_state)

    def merge_draft_payload(
        self,
        session_id: str,
        authorization_binding: str,
        base_revision: int,
        payload: Mapping[str, Any],
    ) -> CoCreationSessionState | None:
        """Accumulate structured answers into the draft payload (no mutation of
        the library until the Author confirms at ``borrador_listo``)."""
        with self._lock:
            row = self._read_row(session_id, authorization_binding)
            if row is None:
                return None
            state = self._deserialize_row(row)
            if state.revision != base_revision:
                return None
            next_state = deepcopy(state)
            next_state.revision += 1
            next_state.draft_payload.update(dict(payload))
            self._write_state(next_state)
            self._in_process.add(session_id)
            return deepcopy(next_state)

    # -- TW12 canvas data layer --------------------------------------------

    def autosave_payload(
        self,
        session_id: str,
        authorization_binding: str,
        base_revision: int,
        payload: Mapping[str, Any],
        source: str = "autosave",
        issues: Sequence[MethodologyIssue] | None = None,
    ) -> CoCreationSessionState | None:
        """Debounced canvas autosave: revision-guarded merge + snapshot.

        REQ-CC-11/REQ-CC-15: merges the Author's canvas edit under the
        session's current revision (the same guarded path chat turns use —
        bidirectional sync, one authority boundary), then appends an immutable
        ``{revision, payload, source, ts}`` snapshot to ``draft_history``
        (cap ``HISTORY_CAP``, oldest evicted). ``pending_questions`` is
        chat-owned (REQ-CC-14) and is never merged here. When ``issues`` is
        provided (the post-merge validation projection), warnings reconcile
        keep-or-append: pending warnings never auto-correct (REQ-CC-13).
        """
        if source not in ("author", "chat", "autosave"):
            return None
        with self._lock:
            row = self._read_row(session_id, authorization_binding)
            if row is None:
                return None
            state = self._deserialize_row(row)
            if state.revision != base_revision:
                return None
            next_state = deepcopy(state)
            next_state.revision += 1
            merged = {
                key: deepcopy(value)
                for key, value in payload.items()
                if key != "pending_questions"
            }
            next_state.draft_payload.update(merged)
            if issues is not None:
                _reconcile_warnings(next_state.warnings, issues)
            next_state.draft_history.append(DraftHistoryEntry(
                revision=next_state.revision,
                payload=deepcopy(next_state.draft_payload),
                source=source,  # type: ignore[arg-type]
                ts=_utcnow().isoformat(),
            ))
            if len(next_state.draft_history) > HISTORY_CAP:
                del next_state.draft_history[: len(next_state.draft_history) - HISTORY_CAP]
            self._write_state(next_state)
            self._in_process.add(session_id)
            return deepcopy(next_state)

    def list_history(
        self,
        session_id: str,
        authorization_binding: str,
    ) -> list[DraftHistoryEntry] | None:
        """Immutable autosave snapshot list (REQ-CC-15)."""
        with self._lock:
            row = self._read_row(session_id, authorization_binding)
            if row is None:
                return None
            return deepcopy(self._deserialize_row(row).draft_history)

    def restore_payload(
        self,
        session_id: str,
        authorization_binding: str,
        base_revision: int,
        target_revision: int,
    ) -> CoCreationSessionState | None:
        """Restore a persisted snapshot, revision-guarded (REQ-CC-15).

        The session's current revision must equal ``base_revision`` and the
        target snapshot must exist in ``draft_history``; otherwise ``None``
        (fail closed, zero mutations). On success the payload is replaced and
        a new author-originated snapshot records the restore.
        """
        with self._lock:
            row = self._read_row(session_id, authorization_binding)
            if row is None:
                return None
            state = self._deserialize_row(row)
            if state.revision != base_revision:
                return None
            snapshot = next(
                (entry for entry in state.draft_history
                 if entry.revision == target_revision),
                None,
            )
            if snapshot is None:
                return None
            next_state = deepcopy(state)
            next_state.revision += 1
            next_state.draft_payload = deepcopy(snapshot.payload)
            next_state.draft_history.append(DraftHistoryEntry(
                revision=next_state.revision,
                payload=deepcopy(next_state.draft_payload),
                source=HistorySource.AUTHOR.value,
                ts=_utcnow().isoformat(),
            ))
            if len(next_state.draft_history) > HISTORY_CAP:
                del next_state.draft_history[: len(next_state.draft_history) - HISTORY_CAP]
            self._write_state(next_state)
            self._in_process.add(session_id)
            return deepcopy(next_state)

    def set_warning_status(
        self,
        session_id: str,
        authorization_binding: str,
        base_revision: int,
        idx: int,
        state: str,
    ) -> CoCreationSessionState | None:
        """Author-only warning transition (REQ-CC-13).

        Only ``Pendiente -> Resuelta | Aceptada_por_Autor`` is allowed. Any
        other transition, a stale revision, an out-of-range index, or an
        invalid state fails closed with zero mutations. Warnings never
        auto-clear: validation reconciles issues keep-or-append and never
        touches an existing warning's state.
        """
        with self._lock:
            row = self._read_row(session_id, authorization_binding)
            if row is None:
                return None
            state_obj = self._deserialize_row(row)
            if state_obj.revision != base_revision:
                return None
            if state not in ("pendiente", "resuelta", "aceptada_por_autor"):
                return None
            if idx < 0 or idx >= len(state_obj.warnings):
                return None
            current = state_obj.warnings[idx].state
            if (current, state) not in _AUTHOR_TRANSITIONS:
                return None
            next_state = deepcopy(state_obj)
            next_state.revision += 1
            next_state.warnings[idx].state = state
            self._write_state(next_state)
            self._in_process.add(session_id)
            return deepcopy(next_state)

    def append_pending_question(
        self,
        session_id: str,
        authorization_binding: str,
        base_revision: int,
        text: str,
    ) -> CoCreationSessionState | None:
        """Chat-only append to ``pending_questions`` (REQ-CC-14).

        The question enters with state ``pendiente``; consecutive duplicate
        texts are not re-appended. The Author never edits or deletes entries
        directly — they only transition state via
        ``set_pending_question_status``.
        """
        if not isinstance(text, str) or not text.strip():
            return None
        with self._lock:
            row = self._read_row(session_id, authorization_binding)
            if row is None:
                return None
            state = self._deserialize_row(row)
            if state.revision != base_revision:
                return None
            next_state = deepcopy(state)
            next_state.revision += 1
            _append_pending_question(next_state.draft_payload, text)
            self._write_state(next_state)
            self._in_process.add(session_id)
            return deepcopy(next_state)

    def set_pending_question_status(
        self,
        session_id: str,
        authorization_binding: str,
        base_revision: int,
        idx: int,
        state: str,
    ) -> CoCreationSessionState | None:
        """Author-only pending-question transition (REQ-CC-14).

        Only ``Pendiente -> Resuelta | Aceptada_por_Autor`` is allowed; the
        chat never changes state. A stale revision, an out-of-range index, an
        invalid state, or a non-Pendiente entry fails closed.
        """
        with self._lock:
            row = self._read_row(session_id, authorization_binding)
            if row is None:
                return None
            state_obj = self._deserialize_row(row)
            if state_obj.revision != base_revision:
                return None
            if state not in ("pendiente", "resuelta", "aceptada_por_autor"):
                return None
            questions = state_obj.draft_payload.get("pending_questions")
            if not isinstance(questions, list):
                return None
            if idx < 0 or idx >= len(questions):
                return None
            entry = questions[idx]
            if not isinstance(entry, Mapping) or entry.get("state") != "pendiente":
                return None
            if (entry["state"], state) not in _AUTHOR_TRANSITIONS:
                return None
            next_state = deepcopy(state_obj)
            next_state.revision += 1
            next_questions = next_state.draft_payload.get("pending_questions")
            next_questions[idx] = {**next_questions[idx], "state": state}
            self._write_state(next_state)
            self._in_process.add(session_id)
            return deepcopy(next_state)

    def record_draft(
        self,
        session_id: str,
        authorization_binding: str,
        base_revision: int,
        draft_id: str,
    ) -> CoCreationSessionState | None:
        """Persist the materialized draft id and move to the ``materialized`` phase."""
        with self._lock:
            row = self._read_row(session_id, authorization_binding)
            if row is None:
                return None
            state = self._deserialize_row(row)
            if state.revision != base_revision:
                return None
            next_state = deepcopy(state)
            next_state.revision += 1
            next_state.draft_id = draft_id
            next_state.phase = "materialized"
            self._write_state(next_state)
            self._in_process.add(session_id)
            return deepcopy(next_state)

    def set_phase(
        self,
        session_id: str,
        authorization_binding: str,
        base_revision: int,
        phase: str,
    ) -> CoCreationSessionState | None:
        if phase not in _PHASES:
            return None
        with self._lock:
            row = self._read_row(session_id, authorization_binding)
            if row is None:
                return None
            state = self._deserialize_row(row)
            if state.revision != base_revision:
                return None
            next_state = deepcopy(state)
            next_state.revision += 1
            next_state.phase = phase
            self._write_state(next_state)
            self._in_process.add(session_id)
            return deepcopy(next_state)

    def at_ceiling(self, session_id: str, authorization_binding: str) -> bool:
        with self._lock:
            row = self._read_row(session_id, authorization_binding)
            return row is not None and row["question_count"] >= QUESTION_CEILING

    def discard_expired(self, now: datetime | None = None) -> int:
        now = now or _utcnow()
        with self._lock:
            return self._discard_expired(now)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- low-level persistence helpers (call under self._lock) --------------

    def _read_row(self, session_id: str, authorization_binding: str) -> sqlite3.Row | None:
        row = self._conn.execute(
            "SELECT * FROM co_creation_sessions WHERE session_id = ?", (session_id,),
        ).fetchone()
        if row is None or row["authorization_binding"] != authorization_binding:
            return None
        return row

    def _discard_expired(self, now: datetime) -> int:
        cutoff = (now - SESSION_TTL).isoformat()
        cursor = self._conn.execute(
            "DELETE FROM co_creation_sessions WHERE updated_at < ?", (cutoff,),
        )
        self._conn.commit()
        return max(0, cursor.rowcount)

    def _write_state(
        self, state: CoCreationSessionState, revalidation_required: bool | None = None,
    ) -> None:
        now = _utcnow().isoformat()
        milestone_states_json = json.dumps(
            [{"name": item.name, "state": item.state} for item in state.milestone_states],
            ensure_ascii=False, separators=(",", ":"),
        )
        messages_json = json.dumps(
            [
                {"role": message.role, "content": message.content, "revision": message.revision}
                for message in state.messages
            ],
            ensure_ascii=False, separators=(",", ":"),
        )
        draft_payload_json = json.dumps(
            state.draft_payload, ensure_ascii=False, separators=(",", ":"),
        )
        pending_options_json = json.dumps(
            list(state.pending_options), ensure_ascii=False, separators=(",", ":"),
        )
        draft_history_json = json.dumps(
            [
                {
                    "revision": entry.revision,
                    "payload": entry.payload,
                    "source": entry.source,
                    "ts": entry.ts,
                }
                for entry in state.draft_history
            ],
            ensure_ascii=False, separators=(",", ":"),
        )
        warnings_json = json.dumps(
            [
                {
                    "code": warning.code,
                    "message": warning.message,
                    "field": warning.field,
                    "state": warning.state,
                }
                for warning in state.warnings
            ],
            ensure_ascii=False, separators=(",", ":"),
        )
        derived_from_json = (
            json.dumps(
                {
                    "skill_id": state.derived_from.skill_id,
                    "version": state.derived_from.version,
                },
                ensure_ascii=False, separators=(",", ":"),
            )
            if state.derived_from is not None else None
        )
        if revalidation_required is None:
            current = self._conn.execute(
                "SELECT revalidation_required FROM co_creation_sessions WHERE session_id = ?",
                (state.session_id,),
            ).fetchone()
            flag = current["revalidation_required"] if current is not None else 0
        else:
            flag = 1 if revalidation_required else 0
        self._conn.execute(
            """
            INSERT INTO co_creation_sessions (
                session_id, principal_id, world, revision, authorization_binding,
                milestone, milestone_states_json, question_count, draft_payload_json,
                messages_json, pending_question, pending_options_json, draft_id,
                phase, created_at, updated_at, revalidation_required,
                draft_history_json, warnings_json, derived_from_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                principal_id = excluded.principal_id,
                world = excluded.world,
                revision = excluded.revision,
                authorization_binding = excluded.authorization_binding,
                milestone = excluded.milestone,
                milestone_states_json = excluded.milestone_states_json,
                question_count = excluded.question_count,
                draft_payload_json = excluded.draft_payload_json,
                messages_json = excluded.messages_json,
                pending_question = excluded.pending_question,
                pending_options_json = excluded.pending_options_json,
                draft_id = excluded.draft_id,
                phase = excluded.phase,
                updated_at = excluded.updated_at,
                revalidation_required = excluded.revalidation_required,
                draft_history_json = excluded.draft_history_json,
                warnings_json = excluded.warnings_json,
                derived_from_json = excluded.derived_from_json
            """,
            (
                state.session_id, state.principal_id, state.world, state.revision,
                state.authorization_binding, state.milestone, milestone_states_json,
                state.question_count, draft_payload_json, messages_json,
                state.pending_question, pending_options_json, state.draft_id,
                state.phase, now, now, flag,
                draft_history_json, warnings_json, derived_from_json,
            ),
        )
        self._conn.commit()

    def _deserialize_row(self, row: sqlite3.Row) -> CoCreationSessionState:
        messages = [
            CoCreationMessage(item["role"], item["content"], item["revision"])
            for item in json.loads(row["messages_json"])
        ]
        milestone_states = tuple(
            MilestoneState(item["name"], item["state"])
            for item in json.loads(row["milestone_states_json"])
        )
        draft_history = [
            DraftHistoryEntry(
                revision=item["revision"],
                payload=dict(item["payload"]),
                source=item["source"],  # type: ignore[arg-type]
                ts=item["ts"],
            )
            for item in json.loads(row["draft_history_json"] or "[]")
        ]
        warnings = [
            DraftWarning(
                code=item["code"],
                message=item["message"],
                field=item.get("field"),
                state=item["state"],  # type: ignore[arg-type]
            )
            for item in json.loads(row["warnings_json"] or "[]")
        ]
        derived_from: DerivedFrom | None = None
        if row["derived_from_json"]:
            raw = json.loads(row["derived_from_json"])
            if isinstance(raw, dict) and raw.get("skill_id") and raw.get("version"):
                derived_from = DerivedFrom(skill_id=raw["skill_id"], version=raw["version"])
        return CoCreationSessionState(
            session_id=row["session_id"],
            principal_id=row["principal_id"],
            world=row["world"],
            revision=row["revision"],
            authorization_binding=row["authorization_binding"],
            milestone=row["milestone"],
            milestone_states=milestone_states,
            question_count=row["question_count"],
            draft_payload=json.loads(row["draft_payload_json"]),
            messages=messages,
            pending_question=row["pending_question"],
            pending_options=tuple(json.loads(row["pending_options_json"])),
            draft_id=row["draft_id"],
            phase=row["phase"],
            draft_history=draft_history,
            warnings=warnings,
            derived_from=derived_from,
        )