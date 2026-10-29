# -*- coding: utf-8 -*-
"""The content-move job: one move at a time, with progress and a record.

A copy of gigabytes cannot be a request, so the route validates the plan
synchronously and hands the work to a background thread. The job record of the
LAST run is persisted in the machine-state directory (never in the content root),
because two things depend on it: the UI showing a pending cleanup, and the
cleanup itself, which may only delete the exact folder a verified move left
behind.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import content_mover
from content_mover import MoveError, MovePlan

#: The persisted record: the only thing that authorises deleting the old copy.
RECORD_NAME = "content-move-last.json"
RECORD_SCHEMA_VERSION = 1

STATE_QUEUED = "queued"
STATE_COPYING = "copying"
STATE_DONE = "done"
STATE_FAILED = "failed"
STATE_CANCELLED = "cancelled"

TERMINAL_STATES = frozenset({STATE_DONE, STATE_FAILED, STATE_CANCELLED})


def read_last_move(record_dir: Path) -> dict[str, Any] | None:
    """The persisted record of the last COMPLETED move, or ``None``."""
    path = Path(record_dir) / RECORD_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != RECORD_SCHEMA_VERSION:
        return None
    return payload


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class MoveJob:
    """One move, as the UI polls it."""

    id: str
    state: str
    source: str
    target: str
    total_files: int
    total_bytes: int
    copied_files: int = 0
    copied_bytes: int = 0
    skipped: tuple[tuple[str, str], ...] = ()
    error: str | None = None
    pointer_written: bool = False
    cancel_requested: bool = False
    started_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None

    @property
    def done(self) -> bool:
        return self.state in TERMINAL_STATES

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "state": self.state,
            "source": self.source,
            "target": self.target,
            "total_files": self.total_files,
            "total_bytes": self.total_bytes,
            "copied_files": self.copied_files,
            "copied_bytes": self.copied_bytes,
            "skipped": [
                {"name": name, "reason": reason} for name, reason in self.skipped
            ],
            "error": self.error,
            "pointer_written": self.pointer_written,
            "cancel_requested": self.cancel_requested,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class ContentMoveService:
    """Runs at most one move at a time and remembers the last outcome."""

    def __init__(
        self,
        *,
        record_dir: Path,
        publish: Callable[[Path], None] | None = None,
        pointer: Callable[[], Path | None] | None = None,
        run_inline: bool = False,
    ) -> None:
        #: Where the record lives. This is NOT ``resolve_state_dir()``: policy (ii)
        #: may answer ``<content root>/data``, and a record written there would
        #: modify the source of the very move it describes and disappear with it.
        self._record_dir = Path(record_dir)
        self._publish = publish
        self._pointer = pointer
        self._run_inline = run_inline
        self._lock = threading.Lock()
        self._jobs: dict[str, MoveJob] = {}
        self._active: str | None = None

    # -- record ------------------------------------------------------------
    def record_path(self) -> Path:
        return self._record_dir / RECORD_NAME

    def last_move(self) -> dict[str, Any] | None:
        """The persisted record of the last terminal move, or ``None``."""
        return read_last_move(self._record_dir)

    def _write_record(self, job: MoveJob) -> None:
        """Persist a COMPLETED move only.

        A failed or cancelled attempt must not overwrite the record of a previous
        good move: the record is what authorises deleting the old copy, and losing
        it would leave the author with two full trees and no way to remove one.
        """
        if job.state != STATE_DONE or not job.pointer_written:
            return
        path = self.record_path()
        if path.is_relative_to(Path(job.source)):
            # Defensive: a record inside the folder it describes would violate the
            # promise that a move never touches the source.
            return
        payload = {
            "schema_version": RECORD_SCHEMA_VERSION,
            "source": job.source,
            "target": job.target,
            "state": job.state,
            "pointer_written": job.pointer_written,
            "finished_at": job.finished_at or _utc_now(),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex}")
            temp.write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8"
            )
            os.replace(temp, path)
        except OSError:
            # The record only gates the cleanup: losing it is safe, it just makes
            # the app not offer the delete.
            pass

    # -- jobs --------------------------------------------------------------
    def get(self, job_id: str) -> MoveJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def active(self) -> MoveJob | None:
        with self._lock:
            return None if self._active is None else self._jobs.get(self._active)

    def start(
        self,
        *,
        source: str | Path,
        target: str | Path,
        forbidden: Sequence[Path] = (),
    ) -> MoveJob:
        """Validate and start. Refusals raise :class:`MoveError` before any write."""
        with self._lock:
            if self._active is not None:
                raise MoveError("another move is already running")
        plan = content_mover.plan_move(source, target, forbidden=forbidden)
        job = MoveJob(
            id=uuid.uuid4().hex[:12],
            state=STATE_QUEUED,
            source=str(plan.source),
            target=str(plan.target),
            total_files=plan.total_files,
            total_bytes=plan.total_bytes,
            skipped=plan.skipped,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._active = job.id
        if self._run_inline:
            self._run(job, plan)
        else:
            threading.Thread(
                target=self._run,
                args=(job, plan),
                name="demiurgos-content-move",
                daemon=True,
            ).start()
        return job

    def cancel(self, job_id: str) -> MoveJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if not job.done:
                job.cancel_requested = True
            return job

    def _run(self, job: MoveJob, plan: MovePlan) -> None:
        job.state = STATE_COPYING

        def progress(files: int, total: int, size: int) -> None:
            job.copied_files = files
            job.copied_bytes = size
            job.total_files = total

        try:
            outcome = content_mover.execute_move(
                plan,
                publish=self._publish,
                on_progress=progress,
                should_cancel=lambda: job.cancel_requested,
            )
        except MoveError as exc:
            job.state = STATE_FAILED
            job.error = str(exc)
        except Exception as exc:  # noqa: BLE001 — the job reports, never crashes the app
            job.state = STATE_FAILED
            job.error = str(exc) or exc.__class__.__name__
        else:
            job.copied_files = outcome.copied_files
            job.copied_bytes = outcome.copied_bytes
            if outcome.cancelled:
                job.state = STATE_CANCELLED
            else:
                job.state = STATE_DONE
                job.pointer_written = outcome.published
        finally:
            job.finished_at = _utc_now()
            with self._lock:
                self._active = None
            self._write_record(job)

    # -- cleanup -----------------------------------------------------------
    def delete_source(
        self,
        *,
        typed: str,
        forbidden: Sequence[Path] = (),
    ) -> str:
        """Delete the old copy, only for a verified move, only with the typed path."""
        record = self.last_move()
        if record is None:
            raise MoveError("there is no completed move to clean up")
        if record.get("state") != STATE_DONE or not record.get("pointer_written"):
            raise MoveError(
                "the last move did not finish with the content pointer on the new "
                "folder, so the old copy is not deleted"
            )
        if self._pointer is not None:
            current = self._pointer()
            if current is None or Path(current) != Path(str(record.get("target"))):
                raise MoveError(
                    "the content pointer no longer points at the folder that move "
                    "created, so the old copy is not deleted"
                )
        removed = content_mover.delete_source(
            record.get("source"), typed, forbidden=forbidden
        )
        cleared = dict(record)
        cleared["source"] = ""
        cleared["state"] = "cleaned"
        try:
            self.record_path().write_text(
                json.dumps({**cleared, "schema_version": RECORD_SCHEMA_VERSION}, indent=2)
                + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass
        return removed
