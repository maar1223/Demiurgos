"""Metadata-only run journal: stable op IDs, states, retention, atomic writes.

Internal plumbing; authors never see journal rows or retry mechanics."""


import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

MAX_ATTEMPTS = 3
MAX_ENTRIES = 10_000
MAX_AGE_DAYS = 90
STATES = ("planned", "confirmed", "applied", "failed", "recovered", "abandoned")
RESOLVED = frozenset({"applied", "recovered", "abandoned"})


@dataclass(frozen=True)
class JournalEntry:
    """One immutable, deterministic journal row (metadata only)."""

    run_id: str
    operation_id: str
    source_revision: str
    target: str
    state: str
    attempts: int
    result_code: str
    next_retry: str
    created_at: str
    updated_at: str


def operation_id(domain: str, item_key: str, source_revision: str, target: str, action: str) -> str:
    payload = "\x1f".join((domain, item_key, source_revision, target, action))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RunJournal:
    """Journal under .demiurgos-sync/ with deterministic, atomic snapshot writes."""

    def __init__(self, base_dir: Path | str = ".demiurgos-sync",
                 now: Callable[[], str] | None = None) -> None:
        self._dir = Path(base_dir)
        self.path = self._dir / "journal.jsonl"
        self._now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def _rows(self) -> list[JournalEntry]:
        if not self.path.exists():
            return []
        return [JournalEntry(**json.loads(raw)) for raw in
                self.path.read_text(encoding="utf-8").splitlines() if raw]

    def _write(self, entries: list[JournalEntry]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._dir / "journal.jsonl.tmp"
        body = "\n".join(json.dumps(asdict(e), sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")) for e in
                         sorted(entries, key=lambda e: e.operation_id)) + "\n"
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, self.path)

    def find(self, op_id: str) -> JournalEntry | None: return next((e for e in self._rows() if e.operation_id == op_id), None)

    @staticmethod
    def operation_id(domain: str, item_key: str, source_revision: str,
                     target: str, action: str) -> str:
        return operation_id(domain, item_key, source_revision, target, action)

    def plan(self, *, run_id: str, domain: str, item_key: str,
             source_revision: str, target: str, action: str,
             next_retry: str = "") -> JournalEntry:
        op_id = operation_id(domain, item_key, source_revision, target, action)
        if self.find(op_id) is not None:
            raise ValueError(f"operation already planned: {op_id}")
        return self._mark(JournalEntry(run_id=run_id, operation_id=op_id,
                                       source_revision=source_revision,
                                       target=target, state="planned", attempts=0,
                                       result_code="", next_retry=next_retry,
                                       created_at=self._now(),
                                       updated_at=self._now()))

    def mark(self, op_id: str, state: str, result_code: str = "",
             next_retry: str = "") -> JournalEntry:
        if state not in STATES:
            raise ValueError(f"invalid state: {state}")
        current = self.find(op_id)
        if current is None:
            raise KeyError(f"operation not planned: {op_id}")
        return self._mark(JournalEntry(run_id=current.run_id, operation_id=op_id,
                                       source_revision=current.source_revision,
                                       target=current.target, state=state,
                                       attempts=current.attempts + (state == "failed"),
                                       result_code=result_code, next_retry=next_retry,
                                       created_at=current.created_at,
                                       updated_at=self._now()))

    def can_retry(self, op_id: str) -> bool:
        entry = self.find(op_id)
        return bool(entry and entry.state == "failed" and entry.attempts < MAX_ATTEMPTS)

    def is_resolved(self, op_id: str) -> bool:
        return bool((entry := self.find(op_id)) and entry.state in RESOLVED)

    def retain(self):
        entries = self._rows()
        cutoff = datetime.fromisoformat(self._now()) - timedelta(days=MAX_AGE_DAYS)
        kept = [e for e in entries if e.state not in RESOLVED
                or datetime.fromisoformat(e.updated_at) >= cutoff]
        self._write(sorted(kept, key=lambda e: e.updated_at)[-MAX_ENTRIES:])

    def _mark(self, entry: JournalEntry) -> JournalEntry:
        entries = {e.operation_id: e for e in self._rows()}
        entries[entry.operation_id] = entry
        self._write(sorted(entries.values(), key=lambda e: e.operation_id))
        return entry
