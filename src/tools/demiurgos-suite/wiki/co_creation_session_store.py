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
from typing import Any, Mapping

from co_creation_protocol import (
    CoCreationMessage,
    CoCreationRequest,
    CoCreationResponse,
    CoCreationSessionState,
    MilestoneState,
    QUESTION_CEILING,
    initial_milestone_states,
    states_for_milestone,
)


SESSION_TTL = timedelta(days=30)

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
    revalidation_required INTEGER NOT NULL DEFAULT 0
)
"""

_PHASES = frozenset({"conversation", "materialized", "review", "complete"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
        self._conn.execute(_SCHEMA)
        self._conn.commit()
        self._in_process: set[str] = set()
        self.discard_expired()

    # -- public lifecycle ---------------------------------------------------

    def create(
        self,
        session_id: str,
        principal_id: str,
        authorization_binding: str,
        world: str | None = None,
        author_input: str = "",
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
                messages=(
                    [CoCreationMessage("author", author_input, 0)]
                    if author_input.strip() else []
                ),
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
                phase, created_at, updated_at, revalidation_required
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                revalidation_required = excluded.revalidation_required
            """,
            (
                state.session_id, state.principal_id, state.world, state.revision,
                state.authorization_binding, state.milestone, milestone_states_json,
                state.question_count, draft_payload_json, messages_json,
                state.pending_question, pending_options_json, state.draft_id,
                state.phase, now, now, flag,
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
        )