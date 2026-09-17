# -*- coding: utf-8 -*-
"""Persisted backup destination + the honest readiness derivation (WU-14, task 14.1).

The chosen folder is AUTHOR CONFIG, not a secret: it lives at
``config/backup.json`` under the **data root**, and ``config/`` is itself part of
the backed-up tree (REQ-BE-2). That is exactly why this record MUST hold no
secret — no token, no credential, no provider account state — only the folder
and the provenance of the choice.

**One derivation, real evidence only.** :func:`backup_state` is the backend half
of the backup card's DEDICATED CONTRACT (REQ-CC-1). A bare registry or
capability claim can never configure the card: the verdict comes from the
persisted folder plus ``meta/last-write.json`` in the destination, so only a
recorded local write proves the flow works. The precedence is deliberate:

1. no persisted destination            → ``pending``
2. a verified streaming destination    → ``error`` (no run may publish)
3. no ``last-write.json`` record       → ``pending``
4. the last run recorded ``failed``    → ``error``
5. the last run recorded a successful local write → ``configured``

``last-write.json`` is read through :class:`FolderTransport` (the same transport
the engine writes with), so the tree layout is never duplicated here and the
write-side and read-side cannot drift apart.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import data_root as _data_root

from backup.manifest import LastWriteRecord
from backup.snapshotter import LAST_WRITE_META_NAME
from backup.sync_folder import Candidate, MODE_STREAMING
from backup.transport.folder import FolderTransport

#: Schema version of ``config/backup.json``; a future shape change is gated.
BACKUP_CONFIG_SCHEMA_VERSION = 1

#: ``config/backup.json`` relative to the data root. A plain relative literal —
#: never derived from this file's location (REQ-DR-3, REQ-CDL-1).
BACKUP_CONFIG_RELPATH = Path("config") / "backup.json"

#: ``last-write.json`` statuses that count as a recorded successful local write.
SUCCESSFUL_WRITE_STATUSES: frozenset[str] = frozenset({"ok", "ok_with_warnings"})


class BackupStateError(RuntimeError):
    """``config/backup.json`` exists but cannot be used as a destination record."""


@dataclass(frozen=True)
class BackupDestination:
    """The persisted destination folder and the provenance of the choice.

    ``mode_hint``/``confidence``/``source`` are the candidate record (REQ-SF-2,
    REQ-SF-4) plus the sync-folder mode verdict (REQ-SF-3). None of it is a
    secret, and none of it claims cloud delivery — it describes a LOCAL folder.
    """

    path: str
    provider: str
    source: str
    confidence: str
    mode_hint: str
    schema_version: int = BACKUP_CONFIG_SCHEMA_VERSION
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """The persistence record (author config; no secrets, no delivery claim)."""
        return {
            "schema_version": self.schema_version,
            "path": self.path,
            "provider": self.provider,
            "source": self.source,
            "confidence": self.confidence,
            "mode_hint": self.mode_hint,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> BackupDestination:
        """Rebuild the record, refusing a document this module cannot trust."""
        try:
            version = int(payload["schema_version"])
            path = str(payload["path"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BackupStateError(f"backup config is not usable: {exc}") from exc
        if version != BACKUP_CONFIG_SCHEMA_VERSION:
            raise BackupStateError(
                f"unsupported backup config schema_version {version}"
            )
        if not path.strip():
            raise BackupStateError("backup config records an empty destination path")
        return cls(
            path=path,
            provider=str(payload.get("provider", "unknown")),
            source=str(payload.get("source", "user")),
            confidence=str(payload.get("confidence", "heuristic")),
            mode_hint=str(payload.get("mode_hint", "unknown")),
            schema_version=version,
            updated_at=payload.get("updated_at"),
        )

    def with_mode(self, mode_hint: str) -> BackupDestination:
        """A copy carrying a fresh mode verdict (the selection re-classifies)."""
        return replace(self, mode_hint=mode_hint)


def config_path(data_root: Path) -> Path:
    """``<data_root>/config/backup.json`` — the persisted destination record."""
    return Path(data_root) / BACKUP_CONFIG_RELPATH


def _utc_now() -> str:
    """The record's ``updated_at`` stamp (UTC, seconds precision)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_destination(data_root: Path) -> BackupDestination | None:
    """Read ``config/backup.json``, or ``None`` when no destination is chosen.

    A corrupt record raises :class:`BackupStateError`: silently treating a
    damaged record as "nothing chosen" would hide a real configuration problem,
    and the card derivation catches the error to stay honestly ``pending``.
    """
    path = config_path(data_root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupStateError(f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise BackupStateError(f"{path} is not a JSON object")
    return BackupDestination.from_dict(payload)


def write_destination(
    data_root: Path, destination: BackupDestination
) -> BackupDestination:
    """Persist the destination atomically (temp ``.tmp-<uuid>`` then ``os.replace``).

    Same discipline as the data-root pointer: an interrupted write leaves the
    previous complete record, never a partial one, and no temp residue.
    """
    path = config_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = (
        destination
        if destination.updated_at
        else replace(destination, updated_at=_utc_now())
    )
    temp = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temp.write_text(
            json.dumps(record.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temp, path)
    except BaseException:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return record


def destination_from_candidate(
    candidate: Candidate,
    *,
    mode_hint: str,
    updated_at: str | None = None,
) -> BackupDestination:
    """Build the persistence record from a candidate plus its mode verdict."""
    return BackupDestination(
        path=str(candidate.path),
        provider=candidate.provider,
        source=candidate.source,
        confidence=candidate.confidence,
        mode_hint=mode_hint,
        updated_at=updated_at,
    )


def read_last_write(destination: BackupDestination) -> LastWriteRecord | None:
    """Read the destination's ``meta/last-write.json``, or ``None`` when absent.

    The read reuses :class:`FolderTransport`, so ``Demiurgos/meta/`` is located
    by the same code the engine published with. An unreadable record counts as
    no evidence (``None``), which keeps the card honestly ``pending`` instead of
    trusting a document that cannot be parsed.
    """
    transport = FolderTransport(Path(destination.path))
    try:
        payload = transport.read_meta(LAST_WRITE_META_NAME)
    except Exception:  # noqa: BLE001 — no evidence is not a crash
        return None
    if payload is None:
        return None
    try:
        return LastWriteRecord.from_dict(payload)
    except Exception:  # noqa: BLE001 — a damaged record proves nothing
        return None


def backup_state(
    state: Mapping[str, Any] | None = None,
    *,
    data_root: Path | None = None,
    destination: BackupDestination | None = None,
    last_write: LastWriteRecord | None = None,
    last_write_reader: Callable[[BackupDestination], LastWriteRecord | None] | None = None,
) -> str:
    """Derive the backup card state from real local evidence only (REQ-CC-1).

    ``state`` is accepted for the ``project_cards`` seam shape (the caller
    already has the registry snapshot in hand) and is deliberately NOT consulted
    for the verdict: a bare ``backup: configured`` claim MUST stay ``pending``
    until a folder is persisted AND a successful local write is recorded
    (SC-CC-1.1/1.2).

    ``destination``/``last_write`` are test seams; production callers pass only
    the root (or nothing) and this function reads the real records. Any failure
    to resolve or read them degrades to ``pending`` — never to a false
    ``configured``.
    """
    if destination is None:
        try:
            root = Path(data_root) if data_root is not None else _data_root.resolve_data_root()
            destination = read_destination(root)
        except Exception:  # noqa: BLE001 — unresolved root/record is not evidence
            return "pending"
    if destination is None:
        return "pending"

    # A verified streaming target blocks every run: the honest state is `error`,
    # not a success claim (REQ-SF-3, SC-BUI-2.1).
    if destination.mode_hint == MODE_STREAMING:
        return "error"

    record = last_write
    if record is None:
        reader = last_write_reader or read_last_write
        try:
            record = reader(destination)
        except Exception:  # noqa: BLE001 — no readable record, no evidence
            record = None
    if record is None:
        return "pending"
    if record.status in SUCCESSFUL_WRITE_STATUSES:
        return "configured"
    return "error"
