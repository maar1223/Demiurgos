"""Durable guided-session store backed by stdlib SQLite.

The hybrid persistence contract from the session-durability slice: persist
messages, candidate, phase, revision, references, and the methodology/version
snapshot for recovery up to ``SESSION_TTL`` (30 days); discard expired sessions;
fail closed for stale or legacy authority. Operational tokens, proposal digests,
and one-time authorizations are NEVER serialized: they stay ephemeral in the
server's in-memory confirmation/proposal stores, so a restart invalidates them
(non-inheritable). Pending proposals recovered from durable storage are marked
for revalidation and must be re-requested/revalidated before they can be
serialized again.

Mechanism choice: stdlib ``sqlite3`` with a single file-backed database.
``db_path`` selects the location; when it is ``None`` the store resolves the
durable repo-local default ``<repo>/data/guided-sessions.sqlite3`` (the same
``data/`` convention as ``idea-capture.sqlite3``), so sessions survive a
restart without any environment override. ``db_path=":memory:"`` remains
available explicitly for hermetic use. SQLite is the smallest
repository-compatible local durable store: zero new dependencies, atomic row
writes, and a single-file snapshot that survives restart. A thread lock guards
the single connection; ``check_same_thread=False`` lets the FastAPI thread pool
and event loop share it.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from data_root import resolve_data_root
from guided_character_domain import (
    accept_proposal as domain_accept_proposal,
    apply_delta,
    reject_proposal as domain_reject_proposal,
)
from guided_character_protocol import (
    CandidateState,
    GuidedRequest,
    GuidedResponse,
    MessageType,
    MethodologySnapshot,
    Outcome,
    SessionState,
    TypedMessage,
)


SESSION_TTL = timedelta(days=30)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS guided_sessions (
    session_id TEXT PRIMARY KEY,
    world TEXT NOT NULL,
    phase TEXT NOT NULL,
    revision INTEGER NOT NULL,
    owner_binding TEXT NOT NULL,
    messages_json TEXT NOT NULL,
    pending_question TEXT,
    candidate_json TEXT NOT NULL,
    reference_context TEXT NOT NULL DEFAULT '',
    reference_name TEXT,
    relation_goal TEXT NOT NULL DEFAULT '',
    confirmation_input TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL,
    depth TEXT NOT NULL,
    methodology_snapshot_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revalidation_required INTEGER NOT NULL DEFAULT 0
)
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def default_db_path() -> Path:
    """Durable default for the guided-sessions database.

    Resolved from the data root on every call (WU-2), never at import time, so
    the store recovers across a restart without requiring the optional
    ``DEMIURGOS_GUIDED_SESSIONS_DB`` override while the suite stays hermetic.
    """
    return resolve_data_root() / "data" / "guided-sessions.sqlite3"


class GuidedSessionStore:
    """Durable SQLite implementation of the guided-session store contract.

    Mirrors the revision/authorization checks of the protocol's in-memory store
    but persists every mutation. ``recover`` marks sessions that hold
    unconfirmed proposals AND were not created/updated by this process as
    requiring revalidation (a durable restart), so stale pending proposals can
    never be trusted without fresh validation.
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
        # Session ids created or mutated by THIS process. A session absent from
        # this set at recovery time came from durable storage (a restart).
        self._in_process: set[str] = set()
        self.discard_expired()

    # -- public lifecycle ---------------------------------------------------

    def create(
        self,
        session_id: str,
        world: str,
        authorization_binding: str,
        reference_context: str = "",
        reference_name: str | None = None,
        relation_goal: str = "",
        mode: str = "full",
        depth: str = "standard",
        methodology_snapshot: MethodologySnapshot | None = None,
    ) -> SessionState:
        if len(reference_context) > 4_000 or len(relation_goal) > 4_000:
            raise ValueError("reference context exceeds the bounded budget")
        if mode not in {"full", "fast"} or depth not in {"standard", "fundamental"}:
            raise ValueError("invalid guided mode")
        with self._lock:
            if self._read_row(session_id, authorization_binding) is not None:
                raise ValueError("session already exists")
            state = SessionState(
                session_id=session_id,
                world=world,
                phase="conversation",
                revision=0,
                authorization_binding=authorization_binding,
                reference_context=reference_context,
                reference_name=reference_name,
                relation_goal=relation_goal,
                mode=mode,
                depth=depth,
                methodology_snapshot=methodology_snapshot,
            )
            self._write_state(state, revalidation_required=0)
            self._in_process.add(session_id)
        return deepcopy(state)

    def recover(
        self,
        session_id: str,
        authorization_binding: str,
        now: datetime | None = None,
    ) -> SessionState | None:
        now = now or _utcnow()
        with self._lock:
            self._discard_expired(now)
            row = self._read_row(session_id, authorization_binding)
            if row is None:
                return None
            state = self._deserialize_row(row)
            if (
                session_id not in self._in_process
                and bool(state.candidate.proposals)
                and state.phase != "complete"
            ):
                self._set_revalidation(session_id, True)
            return deepcopy(state)

    def revalidate_pending(
        self,
        session_id: str,
        authorization_binding: str,
        base_revision: int,
        now: datetime | None = None,
    ) -> SessionState | None:
        """Mark an unconfirmed pending proposal for revalidation after a restart.

        Fails closed (returns None) for unknown sessions, wrong principal,
        expired TTL, stale revision, or a completed session. When the session
        holds unconfirmed proposals that were not produced in this process, the
        durable record is flagged so serialization requires a fresh re-request.
        """
        now = now or _utcnow()
        with self._lock:
            self._discard_expired(now)
            row = self._read_row(session_id, authorization_binding)
            if row is None:
                return None
            state = self._deserialize_row(row)
            if state.revision != base_revision or state.phase == "complete":
                return None
            if session_id not in self._in_process and bool(state.candidate.proposals):
                self._set_revalidation(session_id, True)
            return deepcopy(state)

    def requires_revalidation(self, session_id: str, authorization_binding: str) -> bool:
        with self._lock:
            row = self._read_row(session_id, authorization_binding)
            return bool(row["revalidation_required"]) if row is not None else False

    def methodology_snapshot(
        self, session_id: str, authorization_binding: str
    ) -> MethodologySnapshot | None:
        with self._lock:
            row = self._read_row(session_id, authorization_binding)
            if row is None:
                return None
            return self._deserialize_snapshot(row["methodology_snapshot_json"])

    def discard_expired(self, now: datetime | None = None) -> int:
        now = now or _utcnow()
        with self._lock:
            return self._discard_expired(now)

    def delete_for_world(self, world: str) -> int:
        """Drop every durable session bound to *world*; returns the number removed.

        Used when a world is deleted or purged so its guided sessions stop
        resolving (associated data hidden/cleaned per world-delete spec). The
        matching in-process ids are cleared too so recovery cannot resurrect
        them.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id FROM guided_sessions WHERE world = ?",
                (world,),
            ).fetchall()
            doomed = [row["session_id"] for row in rows]
            if doomed:
                self._conn.execute(
                    "DELETE FROM guided_sessions WHERE world = ?", (world,),
                )
                self._conn.commit()
                self._in_process.difference_update(doomed)
            return len(doomed)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- state mutations (protocol-compatible) ------------------------------

    def begin_confirmation(
        self, session_id: str, authorization_binding: str,
        author_input: str, question: str,
    ) -> SessionState | None:
        with self._lock:
            row = self._read_row(session_id, authorization_binding)
            if row is None:
                return None
            state = self._deserialize_row(row)
            if state.revision != 0:
                return None
            next_state = deepcopy(state)
            next_state.phase = "confirmation"
            next_state.revision = 1
            next_state.confirmation_input = author_input
            next_state.pending_question = question
            next_state.messages.extend((
                TypedMessage(MessageType.AUTHOR_INPUT, {"text": author_input}, next_state.revision),
                TypedMessage(MessageType.ASSISTANT_RESPONSE, {"text": question}, next_state.revision),
            ))
            self._write_state(next_state)
            self._in_process.add(session_id)
            return deepcopy(next_state)

    def resolve_confirmation(
        self, session_id: str, authorization_binding: str, base_revision: int,
        accepted: bool | None, clarification: str,
    ) -> SessionState | None:
        with self._lock:
            row = self._read_row(session_id, authorization_binding)
            if row is None:
                return None
            state = self._deserialize_row(row)
            if state.revision != base_revision:
                return None
            next_state = deepcopy(state)
            next_state.revision += 1
            if accepted is True:
                next_state.phase = "conversation"
                next_state.pending_question = None
                next_state.messages.append(TypedMessage(MessageType.AUTHOR_INPUT, {"text": "confirmed"}, next_state.revision))
            elif accepted is False:
                next_state.phase = "complete"
                next_state.pending_question = None
                next_state.confirmation_input = ""
                next_state.messages.append(TypedMessage(MessageType.ASSISTANT_RESPONSE, {"text": clarification}, next_state.revision))
            else:
                next_state.pending_question = clarification
                next_state.messages.append(TypedMessage(MessageType.ASSISTANT_RESPONSE, {"text": clarification}, next_state.revision))
            self._write_state(next_state)
            self._in_process.add(session_id)
            return deepcopy(next_state)

    def commit(self, request: GuidedRequest, response: GuidedResponse) -> SessionState | None:
        with self._lock:
            row = self._read_row(request.session_id, request.authorization_binding)
            if row is None:
                return None
            state = self._deserialize_row(row)
            if state.revision != request.base_revision:
                return None
            next_state = deepcopy(state)
            if not next_state.reference_context and request.reference_context:
                next_state.reference_context = request.reference_context[:request.context_budget]
                next_state.reference_name = request.reference_name
                next_state.relation_goal = request.relation_goal
            next_state.revision += 1
            next_state.messages.append(TypedMessage(
                MessageType.ASSISTANT_RESPONSE if response.outcome is Outcome.QUESTION else MessageType.PROPOSAL,
                {"question": response.question} if response.question else dict(response.delta or {}),
                next_state.revision,
            ))
            next_state.pending_question = response.question
            if response.outcome is Outcome.DELTA and response.delta:
                apply_delta(next_state.candidate, response.delta, response.provenance)
            elif response.provenance:
                next_state.candidate.provenance.extend(response.provenance)
            # A fresh committed proposal supersedes any pending revalidation.
            self._write_state(next_state, revalidation_required=0)
            self._in_process.add(request.session_id)
            return deepcopy(next_state)

    def accept_proposal(
        self, session_id: str, authorization_binding: str,
        base_revision: int, key: str,
    ) -> SessionState | None:
        with self._lock:
            row = self._read_row(session_id, authorization_binding)
            if row is None:
                return None
            state = self._deserialize_row(row)
            if state.revision != base_revision:
                return None
            next_state = deepcopy(state)
            domain_accept_proposal(next_state.candidate, key)
            next_state.revision += 1
            next_state.messages.append(TypedMessage(MessageType.ACCEPTANCE, {"key": key}, next_state.revision))
            self._write_state(next_state)
            self._in_process.add(session_id)
            return deepcopy(next_state)

    def reject_proposal(
        self, session_id: str, authorization_binding: str,
        base_revision: int, key: str,
    ) -> SessionState | None:
        with self._lock:
            row = self._read_row(session_id, authorization_binding)
            if row is None:
                return None
            state = self._deserialize_row(row)
            if state.revision != base_revision:
                return None
            next_state = deepcopy(state)
            domain_reject_proposal(next_state.candidate, key)
            next_state.revision += 1
            next_state.messages.append(TypedMessage(MessageType.REJECTION, {"key": key}, next_state.revision))
            self._write_state(next_state)
            self._in_process.add(session_id)
            return deepcopy(next_state)

    # -- low-level persistence helpers (call under self._lock) --------------

    def _read_row(self, session_id: str, authorization_binding: str) -> sqlite3.Row | None:
        row = self._conn.execute(
            "SELECT * FROM guided_sessions WHERE session_id = ?", (session_id,),
        ).fetchone()
        if row is None or row["owner_binding"] != authorization_binding:
            return None
        return row

    def _discard_expired(self, now: datetime) -> int:
        cutoff = (now - SESSION_TTL).isoformat()
        cursor = self._conn.execute(
            "DELETE FROM guided_sessions WHERE updated_at < ?", (cutoff,),
        )
        self._conn.commit()
        return max(0, cursor.rowcount)

    def _set_revalidation(self, session_id: str, flag: bool) -> None:
        self._conn.execute(
            "UPDATE guided_sessions SET revalidation_required = ?, updated_at = ? "
            "WHERE session_id = ?",
            (1 if flag else 0, _utcnow().isoformat(), session_id),
        )
        self._conn.commit()

    def _write_state(
        self, state: SessionState, revalidation_required: bool | None = None,
    ) -> None:
        now = _utcnow().isoformat()
        messages_json = json.dumps([
            {
                "message_type": message.message_type.value,
                "content": dict(message.content),
                "revision": message.revision,
            }
            for message in state.messages
        ], ensure_ascii=False, separators=(",", ":"))
        candidate_json = json.dumps({
            "accepted_canon": state.candidate.accepted_canon,
            "proposals": state.candidate.proposals,
            "unknowns": state.candidate.unknowns,
            "rumors": state.candidate.rumors,
            "conflicts": state.candidate.conflicts,
            "unresolved_references": state.candidate.unresolved_references,
            "provenance": state.candidate.provenance,
        }, ensure_ascii=False, separators=(",", ":"))
        snapshot_json = (
            json.dumps(state.methodology_snapshot.as_dict(), separators=(",", ":"))
            if state.methodology_snapshot is not None else None
        )
        if revalidation_required is None:
            current = self._conn.execute(
                "SELECT revalidation_required FROM guided_sessions WHERE session_id = ?",
                (state.session_id,),
            ).fetchone()
            flag = current["revalidation_required"] if current is not None else 0
        else:
            flag = 1 if revalidation_required else 0
        self._conn.execute(
            """
            INSERT INTO guided_sessions (
                session_id, world, phase, revision, owner_binding,
                messages_json, pending_question, candidate_json,
                reference_context, reference_name, relation_goal,
                confirmation_input, mode, depth, methodology_snapshot_json,
                created_at, updated_at, revalidation_required
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                world = excluded.world,
                phase = excluded.phase,
                revision = excluded.revision,
                owner_binding = excluded.owner_binding,
                messages_json = excluded.messages_json,
                pending_question = excluded.pending_question,
                candidate_json = excluded.candidate_json,
                reference_context = excluded.reference_context,
                reference_name = excluded.reference_name,
                relation_goal = excluded.relation_goal,
                confirmation_input = excluded.confirmation_input,
                mode = excluded.mode,
                depth = excluded.depth,
                methodology_snapshot_json = excluded.methodology_snapshot_json,
                updated_at = excluded.updated_at,
                revalidation_required = excluded.revalidation_required
            """,
            (
                state.session_id, state.world, state.phase, state.revision,
                state.authorization_binding, messages_json, state.pending_question,
                candidate_json, state.reference_context, state.reference_name,
                state.relation_goal, state.confirmation_input, state.mode,
                state.depth, snapshot_json, now, now, flag,
            ),
        )
        self._conn.commit()

    def _deserialize_snapshot(self, raw: str | None) -> MethodologySnapshot | None:
        if not raw:
            return None
        payload = json.loads(raw)
        return MethodologySnapshot(
            skill_id=payload.get("skill_id"),
            skill_version=payload.get("skill_version"),
            compiled_contract_digest=payload.get("compiled_contract_digest"),
            flow_type=payload.get("flow_type"),
        )

    def _deserialize_row(self, row: sqlite3.Row) -> SessionState:
        messages = [
            TypedMessage(
                MessageType(item["message_type"]),
                dict(item["content"]),
                item["revision"],
            )
            for item in json.loads(row["messages_json"])
        ]
        candidate = json.loads(row["candidate_json"])
        return SessionState(
            session_id=row["session_id"],
            world=row["world"],
            phase=row["phase"],
            revision=row["revision"],
            authorization_binding=row["owner_binding"],
            messages=messages,
            pending_question=row["pending_question"],
            candidate=CandidateState(
                accepted_canon=candidate.get("accepted_canon", {}),
                proposals=candidate.get("proposals", {}),
                unknowns=candidate.get("unknowns", []),
                rumors=candidate.get("rumors", []),
                conflicts=candidate.get("conflicts", []),
                unresolved_references=candidate.get("unresolved_references", []),
                provenance=candidate.get("provenance", []),
            ),
            reference_context=row["reference_context"],
            reference_name=row["reference_name"],
            relation_goal=row["relation_goal"],
            confirmation_input=row["confirmation_input"],
            mode=row["mode"],
            depth=row["depth"],
            methodology_snapshot=self._deserialize_snapshot(row["methodology_snapshot_json"]),
        )
