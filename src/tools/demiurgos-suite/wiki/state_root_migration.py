# -*- coding: utf-8 -*-
"""One-time adoption of an existing ``<data root>/data`` into the state root.

Why this exists
---------------
Machine state (the SQLite stores, the world recycle bin, migration evidence,
``local-state.json``, the auth-session registry and the import spool) used to
live at ``<data root>/data``, inside the folder the
author backs up with a cloud client. That folder is now meant to hold ONLY
author content: a cloud client syncing live SQLite across two machines corrupts
it, and ``backup.inventory`` already refuses that material. ``data_root``'s
``resolve_state_root`` names the machine-local replacement.

Installs created before the split still have their state at
``<data root>/data``. This module copies it once into the state root, proves the
copy is byte-identical, and only then publishes it atomically. Nothing is ever
deleted: the source tree is left in place (inert — no consumer reads it after
adoption) and the evidence record names it, so a later cleanup step can offer to
remove it.

Contract
--------
- **Dry by default**: a source without any known state artifact is a no-op
  (``reason="no_source"``), and an existing target is a no-op
  (``reason="already_present"``). Nothing is ever overwritten.
- **Copy, never move**: the copy is staged at ``<state root>/data.tmp-<uuid>``,
  on the target filesystem (the source may be a different device — an
  ``os.replace`` across devices fails with ``EXDEV``, so the stage-then-swap is
  what makes the publish atomic).
- **Content-intact proof**: the source tree hash is recorded BEFORE copying and
  the staged tree must hash to the same value. A source that changed mid-copy,
  or a truncated copy, aborts with the stage removed and the source untouched.
- **Complete-or-absent target**: a ``.adoption-complete`` marker is written
  inside the staged tree last, then the staged directory is published with one
  ``os.replace``. A reader therefore never observes a partial ``data``.
- **Single writer, without a lock file**: two processes booting at once may
  both stage a copy, but only one can publish — ``os.replace`` onto an existing
  non-empty directory fails (``ENOTEMPTY``), so the loser removes its stage and
  reports ``reason="failed"`` while the winner's target is untouched. A lock
  file was rejected on purpose: a crash would leave it behind forever and make
  adoption permanently impossible, which is a worse failure than the race.
- **Evidence**: one JSON record per attempt under ``<state root>/migration-evidence``,
  written atomically (tmp + rename), carrying the transaction id, the source and
  target paths, both tree hashes, the file count and the outcome.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

#: Directory name under both roots (``<data root>/data``, ``<state root>/data``).
STATE_DIR_NAME = "data"
#: Written INSIDE the staged tree last; its presence means "this tree is whole".
COMPLETE_MARKER = ".adoption-complete"
#: Evidence directory under the state root (also a legacy state artifact name).
EVIDENCE_DIR = "migration-evidence"

#: Any one of these under the source marks it as Demiurgos machine state. Without
#: one, the source is not ours and is left alone. ``state_paths.resolve_state_dir``
#: consults the SAME tuple, so the layer and the adoption always agree about
#: whether a legacy tree still needs migrating.
STATE_ARTIFACTS = (
    "idea-capture.sqlite3",
    "guided-sessions.sqlite3",
    "co-creation-sessions.sqlite3",
    "conversation-memory.sqlite3",
    "import-jobs.sqlite3",
    "world-checkpoints.sqlite3",
    "local-state.json",
    "sessions.json",
    "world-trash",
    "import-spool",
    "migration-evidence",
)


@dataclass(frozen=True)
class AdoptionResult:
    """Outcome of one adoption attempt. ``reason`` is the stable contract."""

    adopted: bool
    reason: str  # no_source | already_present | adopted | failed
    source: Path
    target: Path
    transaction_id: str = ""
    source_hash: str = ""
    target_hash: str = ""
    files: int = 0
    evidence_path: Path | None = None
    detail: str = ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _feed(digest, *fields: bytes) -> None:
    """Feed length-prefixed fields, so no two trees can collide by concatenation."""
    for field in fields:
        digest.update(str(len(field)).encode("ascii"))
        digest.update(b":")
        digest.update(field)
    digest.update(b"\n")


def _tree_sha256(root: Path, *, skip: frozenset[str] = frozenset()) -> str:
    """Digest of every entry under ``root`` (relative path, kind, content).

    Fields are length-prefixed (injective: two structurally different trees
    cannot share a digest by concatenation), names are encoded with
    ``surrogateescape`` (a non-UTF-8 filename must never crash the hash), and
    only REGULAR files are opened — a FIFO or socket in the tree is recorded by
    kind and never read, so it cannot hang the adoption.

    SQLite side files (``-wal``/``-shm``) are ordinary entries here: copying them
    together with the database is what lets SQLite replay the journal at the new
    location instead of starting from a torn file.
    """
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if rel in skip:
            continue
        name = rel.encode("utf-8", "surrogateescape")
        if path.is_symlink():
            target = os.readlink(path).encode("utf-8", "surrogateescape")
            _feed(digest, name, b"link", target)
        elif path.is_dir():
            _feed(digest, name, b"dir")
        elif path.is_file():
            size = path.stat().st_size
            _feed(digest, name, b"file", str(size).encode("ascii"))
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
        else:
            _feed(digest, name, b"other")
    return digest.hexdigest()


def _count_files(root: Path) -> int:
    return sum(1 for path in root.rglob("*") if path.is_file())


def _write_evidence(
    evidence_dir: Path,
    *,
    transaction_id: str,
    source: Path,
    target: Path,
    source_hash: str,
    target_hash: str,
    files: int,
    outcome: str,
    detail: str,
) -> Path:
    """Atomically record one attempt. Never raises: evidence must not mask the outcome."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "kind": "state-root-adoption",
        "outcome": outcome,
        "source": str(source),
        "target": str(target),
        "source_hash": source_hash,
        "target_hash": target_hash,
        "files": files,
        "detail": detail,
        "recorded_at": _utc_now(),
    }
    destination = evidence_dir / f"state-root-{transaction_id}.json"
    tmp = destination.with_name(f"{destination.name}.tmp-{uuid.uuid4().hex}")
    try:
        tmp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, destination)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return destination


def adopt_existing_state(
    *,
    data_root: Path,
    state_root: Path,
) -> AdoptionResult:
    """Copy ``<data root>/data`` into ``<state root>/data`` exactly once.

    Idempotent and already-adopted-safe: callable on every boot. Returns an
    :class:`AdoptionResult`; it never raises for an ordinary filesystem error,
    because a failed adoption must leave the application booting from the old
    location rather than refusing to start.
    """
    source = Path(data_root) / STATE_DIR_NAME
    target = Path(state_root) / STATE_DIR_NAME
    transaction_id = uuid.uuid4().hex[:12]
    evidence_dir = Path(state_root) / EVIDENCE_DIR

    if target.exists():
        return AdoptionResult(
            adopted=False,
            reason="already_present",
            source=source,
            target=target,
        )

    if not source.is_dir() or not any(
        (source / name).exists() for name in STATE_ARTIFACTS
    ):
        return AdoptionResult(
            adopted=False,
            reason="no_source",
            source=source,
            target=target,
        )

    state_root = Path(state_root)
    resolved_source = source.resolve()
    resolved_state = state_root.resolve()
    if resolved_state == resolved_source or resolved_source in resolved_state.parents:
        return AdoptionResult(
            adopted=False,
            reason="failed",
            source=source,
            target=target,
            transaction_id=transaction_id,
            detail=(
                "the state root must not live inside the directory being adopted: "
                f"{state_root} is under {source}"
            ),
        )
    try:
        state_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return AdoptionResult(
            adopted=False,
            reason="failed",
            source=source,
            target=target,
            transaction_id=transaction_id,
            detail=f"cannot create the state root: {exc}",
        )

    staged = state_root / f"{STATE_DIR_NAME}{'.tmp-'}{uuid.uuid4().hex}"
    source_hash = ""
    target_hash = ""
    files = 0
    try:
        # Skip the marker on BOTH sides: a source that already carries a stale
        # one (restored from another state root) must stay adoptable.
        source_hash = _tree_sha256(source, skip=frozenset({COMPLETE_MARKER}))
        # Refuse special files BEFORE copying: shutil would block opening a
        # FIFO (and cannot represent a socket). Demiurgos state is SQLite, JSON
        # and the recycle bin, so a special file here means the directory is not
        # ours — fail loudly instead of hanging or inventing an entry.
        for path in source.rglob("*"):
            if path.is_symlink() or path.is_dir() or path.is_file():
                continue
            raise OSError(
                f"unsupported special file in the source tree: {path.relative_to(source)}"
            )
        shutil.copytree(source, staged, symlinks=True)
        files = _count_files(staged)
        (staged / COMPLETE_MARKER).write_text(
            json.dumps(
                {
                    "transaction_id": transaction_id,
                    "source": str(source),
                    "source_hash": source_hash,
                    "recorded_at": _utc_now(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        target_hash = _tree_sha256(staged, skip=frozenset({COMPLETE_MARKER}))
        if target_hash != source_hash:
            raise OSError(
                "content-intact check failed: the copy does not hash to the source "
                "(the source changed during the copy, or the copy is truncated)"
            )
        os.replace(staged, target)
    except (OSError, shutil.Error) as exc:
        shutil.rmtree(staged, ignore_errors=True)
        try:
            evidence = _write_evidence(
                evidence_dir,
                transaction_id=transaction_id,
                source=source,
                target=target,
                source_hash=source_hash,
                target_hash=target_hash,
                files=files,
                outcome="failed",
                detail=str(exc),
            )
        except OSError:
            evidence = None
        return AdoptionResult(
            adopted=False,
            reason="failed",
            source=source,
            target=target,
            transaction_id=transaction_id,
            source_hash=source_hash,
            target_hash=target_hash,
            files=files,
            evidence_path=evidence,
            detail=str(exc),
        )

    # The target is already published: evidence must never turn a successful
    # adoption into an exception, or the caller would retry against a target
    # that is genuinely in place.
    try:
        evidence = _write_evidence(
            evidence_dir,
            transaction_id=transaction_id,
            source=source,
            target=target,
            source_hash=source_hash,
            target_hash=target_hash,
            files=files,
            outcome="adopted",
            detail=(
                "source left in place on purpose: no consumer reads it after "
                "adoption and nothing is ever deleted by this migration"
            ),
        )
    except OSError:
        evidence = None
    return AdoptionResult(
        adopted=True,
        reason="adopted",
        source=source,
        target=target,
        transaction_id=transaction_id,
        source_hash=source_hash,
        target_hash=target_hash,
        files=files,
        evidence_path=evidence,
    )
