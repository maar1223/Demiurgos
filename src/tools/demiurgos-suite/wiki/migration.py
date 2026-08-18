"""Transactional legacy-layout migration engine (ONB-4.3).

Moves the legacy uppercase top-level folders (``Lore``, ``Personajes``) of an
Author-approved world to their canonical lowercase names (``lore``,
``personajes``) so the case-sensitive runtime can read them (OC7). This module
is the PURE engine: it never decides what to migrate and never exposes routes —
explicit approval arrives at call time as the folder list (WU-4c wires the
approval UI on top). It NEVER auto-renames anything.

Contract (design: "migration records plan, source/destination hashes,
transaction id and rollback evidence, then atomically moves only approved
folders; failure restores originals"):

- ``build_migration_plan`` records the plan BEFORE any mutation: transaction
  id, approved folders, source paths, and a content hash of every source tree.
  Unsafe input (missing world, unknown/unsafe folder, destination collision,
  symlink escape, empty approval) raises ``MigrationError`` without mutating
  anything.
- ``execute_migration`` moves ONLY the approved folders, one atomic
  same-filesystem rename each (``os.replace``), re-verifying destination
  availability immediately before each move (TOCTOU guard). After each move it
  recomputes the destination hash and requires it to equal the recorded source
  hash (content-intact proof). Any mid-transaction failure rolls every
  already-moved folder back to its original location and re-verifies the
  source hashes.
- Every execution (completed or rolled back) persists a JSON evidence record
  — plan identity (transaction id), world, per-folder source/destination
  hashes, restore flags, and outcome — under ``evidence_dir`` via an atomic
  tmp+rename write.

Filesystem scope: this module writes ONLY under the given ``mundos_dir``
(approved folder moves) and ``evidence_dir`` (evidence records). It never
touches the local-state registry, ``.demiurgos-estado.json``, or any
unapproved folder.

Canonical tree hash (documented contract, used by source and destination
evidence): for every entry in the tree with relative POSIX path ``rel``
(directories get a trailing ``/``), globally sorted lexicographically,
update the digest with ``rel + "\\0" + kind + "\\0" + payload + "\\n"`` where
``kind`` is ``dir``/``file``/``link`` and ``payload`` is the file bytes, the
symlink target, or empty for directories.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable

from wiki.world_authority import LEGACY_FOLDERS, normalize_world_name

logger = logging.getLogger("demiurgos-migration")

EVIDENCE_SCHEMA_VERSION = 1
_HASH_CHUNK = 65536


class MigrationErrorKind(Enum):
    """Machine-readable failure class. No mutation happens on any of these."""

    INVALID_WORLD = "invalid_world"
    EMPTY_APPROVAL = "empty_approval"
    UNKNOWN_FOLDER = "unknown_folder"
    COLLISION = "collision"
    SYMLINK_ESCAPE = "symlink_escape"
    IO_ERROR = "io_error"


class MigrationError(RuntimeError):
    """Raised for pre-flight failures; the filesystem is left untouched.

    ``transaction_id`` is set when the failure is bound to an already-built
    plan (e.g. a destination that became occupied after planning).
    """

    def __init__(
        self,
        kind: MigrationErrorKind,
        message: str,
        transaction_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.transaction_id = transaction_id


class MigrationOutcome(Enum):
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class MigrationStep:
    """One approved folder move inside a plan/evidence."""

    folder: str  # legacy name, e.g. "Lore"
    source: Path  # e.g. mundos/legacy-x/Lore
    destination: Path  # e.g. mundos/legacy-x/lore
    source_hash: str  # sha256 of the source tree at plan time
    destination_hash: str | None = None  # sha256 of the moved tree, after move
    restored: bool = False  # True when a rolled-back step was hash-verified


@dataclass(frozen=True)
class MigrationPlan:
    """The approved migration, recorded before any mutation (ONB-4.3)."""

    transaction_id: str
    world: str
    steps: tuple[MigrationStep, ...]
    created_at: str  # UTC ISO-8601


@dataclass(frozen=True)
class MigrationEvidence:
    """Persisted outcome record: plan identity + hashes + rollback truth."""

    transaction_id: str
    world: str
    outcome: MigrationOutcome
    steps: tuple[MigrationStep, ...]
    restore_verified: bool  # True for completed; for rolled_back = source hashes re-verified
    started_at: str
    finished_at: str
    error: str = ""


# ---------------------------------------------------------------------------
# Tree hashing (canonical contract — see module docstring)
# ---------------------------------------------------------------------------


def _tree_entries(root: Path) -> list[tuple[str, str, Path]]:
    """Sorted ``(rel, kind, path)`` entries; dirs get a trailing ``/`` rel."""
    entries: list[tuple[str, str, Path]] = []

    def walk(directory: Path) -> None:
        for child in sorted(directory.iterdir(), key=lambda p: p.name):
            rel = child.relative_to(root).as_posix()
            if child.is_symlink():
                entries.append((rel, "link", child))
            elif child.is_dir():
                entries.append((rel + "/", "dir", child))
                walk(child)
            else:
                entries.append((rel, "file", child))

    walk(root)
    return entries


def _tree_sha256(root: Path) -> str:
    """Canonical content hash over a directory tree (see module docstring)."""
    digest = hashlib.sha256()
    for rel, kind, path in sorted(_tree_entries(root), key=lambda e: e[0]):
        digest.update(rel.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        digest.update(kind.encode("ascii"))
        digest.update(b"\0")
        if kind == "file":
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
                    digest.update(chunk)
        elif kind == "link":
            digest.update(os.readlink(path).encode("utf-8", "surrogateescape"))
        digest.update(b"\n")
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _destination_collision(destination: Path) -> bool:
    """True when *destination* is occupied by something other than an empty dir.

    An empty directory is safe to replace (no content loss); a file, a
    symlink, or a non-empty directory would destroy or hide content, so those
    count as collisions.
    """
    if not destination.exists() and not destination.is_symlink():
        return False
    if destination.is_dir() and not destination.is_symlink():
        try:
            return any(destination.iterdir())
        except OSError:
            return True
    return True


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


def build_migration_plan(
    mundos_dir: Path,
    world_name: str | None,
    approved_folders: Iterable[str],
) -> MigrationPlan:
    """Record the approved migration BEFORE any mutation.

    Validates that the world exists and is not a symlink escape, that the
    approved folders are exactly legacy folders present as real directories
    (never symlinks), and that no destination is already occupied by content.
    Returns a ``MigrationPlan`` with source hashes + transaction id, or raises
    ``MigrationError`` with the filesystem untouched.
    """
    normalized = normalize_world_name(world_name)
    if normalized is None:
        raise MigrationError(
            MigrationErrorKind.INVALID_WORLD,
            "El nombre del mundo no es válido.",
        )

    root = Path(mundos_dir).resolve()
    world_root = (root / normalized).resolve()
    if world_root.parent != root or world_root.is_symlink() or not world_root.is_dir():
        raise MigrationError(
            MigrationErrorKind.INVALID_WORLD,
            "El mundo no existe o no está dentro del árbol de mundos.",
        )

    approved = list(approved_folders)
    if not approved:
        raise MigrationError(
            MigrationErrorKind.EMPTY_APPROVAL,
            "No se aprobó ninguna carpeta para migrar.",
        )

    steps: list[MigrationStep] = []
    for folder in approved:
        if folder not in LEGACY_FOLDERS:
            raise MigrationError(
                MigrationErrorKind.UNKNOWN_FOLDER,
                f"'{folder}' no es una carpeta legacy migrable.",
            )
        source = world_root / folder
        if source.is_symlink():
            raise MigrationError(
                MigrationErrorKind.SYMLINK_ESCAPE,
                f"'{folder}' es un enlace simbólico; no se migra.",
            )
        if not source.is_dir():
            raise MigrationError(
                MigrationErrorKind.UNKNOWN_FOLDER,
                f"La carpeta '{folder}' no existe en '{normalized}'.",
            )
        destination = world_root / folder.lower()
        if _destination_collision(destination):
            raise MigrationError(
                MigrationErrorKind.COLLISION,
                f"El destino '{destination.name}' ya contiene contenido; no se migra.",
            )
        try:
            source_hash = _tree_sha256(source)
        except OSError as exc:
            raise MigrationError(
                MigrationErrorKind.IO_ERROR,
                f"No se pudo leer '{folder}' para calcular el hash: {exc}",
            ) from exc
        steps.append(
            MigrationStep(
                folder=folder,
                source=source,
                destination=destination,
                source_hash=source_hash,
            )
        )

    transaction_id = f"mig-{uuid.uuid4().hex}"
    logger.info("migration plan %s: %d folder(s) approved for world '%s'",
                transaction_id, len(steps), normalized)
    return MigrationPlan(
        transaction_id=transaction_id,
        world=normalized,
        steps=tuple(steps),
        created_at=_iso_now(),
    )


# ---------------------------------------------------------------------------
# Execution (atomic moves + failure restore)
# ---------------------------------------------------------------------------


def _atomic_move(source: Path, destination: Path) -> None:
    """Same-filesystem atomic rename. Isolated so tests can inject failures."""
    os.replace(source, destination)


def execute_migration(plan: MigrationPlan, evidence_dir: Path) -> MigrationEvidence:
    """Execute the approved plan atomically; failure restores originals.

    Re-validates every destination before ANY move (TOCTOU guard), then moves
    the approved folders one atomic rename at a time, verifying the destination
    hash equals the planned source hash after each move. Any OSError (move
    failure, hash mismatch, raced destination) rolls back every already-moved
    folder to its original location and re-verifies the source hashes.

    The outcome evidence (``completed`` or ``rolled_back``) is ALWAYS persisted
    under ``evidence_dir/{transaction_id}.json``. If the evidence itself cannot
    be persisted, a ``MigrationError(IO_ERROR)`` is raised naming the
    transaction id so the caller can audit the filesystem state.
    """
    started_at = _iso_now()
    for step in plan.steps:
        if _destination_collision(step.destination):
            raise MigrationError(
                MigrationErrorKind.COLLISION,
                f"El destino '{step.destination.name}' se ocupó antes de migrar; "
                "no se movió nada.",
                plan.transaction_id,
            )

    moved: list[MigrationStep] = []
    try:
        for step in plan.steps:
            # Per-move re-check: another process could race in between moves.
            if _destination_collision(step.destination):
                raise OSError(
                    f"destination '{step.destination.name}' became occupied "
                    "before the move"
                )
            if step.destination.is_dir():
                # Empty dir (allowed at plan time): remove before the rename.
                step.destination.rmdir()  # OSError if it raced non-empty
            _atomic_move(step.source, step.destination)
            destination_hash = _tree_sha256(step.destination)
            if destination_hash != step.source_hash:
                raise OSError(
                    f"content hash mismatch after moving '{step.folder}'"
                )
            moved.append(
                MigrationStep(
                    folder=step.folder,
                    source=step.source,
                    destination=step.destination,
                    source_hash=step.source_hash,
                    destination_hash=destination_hash,
                )
            )
        evidence = MigrationEvidence(
            transaction_id=plan.transaction_id,
            world=plan.world,
            outcome=MigrationOutcome.COMPLETED,
            steps=tuple(moved),
            restore_verified=True,
            started_at=started_at,
            finished_at=_iso_now(),
        )
    except OSError as exc:
        evidence = _rollback(plan, moved, started_at, exc)

    _persist_evidence(evidence, evidence_dir)
    return evidence


def _rollback(
    plan: MigrationPlan,
    moved: list[MigrationStep],
    started_at: str,
    cause: OSError,
) -> MigrationEvidence:
    """Restore every already-moved folder and re-verify the source hashes."""
    restored_steps: list[MigrationStep] = []
    restore_failures: list[str] = []
    verified = True
    for step in reversed(moved):
        try:
            if _destination_collision(step.source):
                raise OSError(f"source '{step.source.name}' is occupied")
            if step.source.is_dir():
                step.source.rmdir()
            _atomic_move(step.destination, step.source)
            restored = _tree_sha256(step.source) == step.source_hash
            verified = verified and restored
            restored_steps.append(
                MigrationStep(
                    folder=step.folder,
                    source=step.source,
                    destination=step.destination,
                    source_hash=step.source_hash,
                    destination_hash=step.destination_hash,
                    restored=restored,
                )
            )
        except OSError as restore_exc:
            verified = False
            restore_failures.append(f"{step.folder} ({restore_exc})")
            restored_steps.append(
                MigrationStep(
                    folder=step.folder,
                    source=step.source,
                    destination=step.destination,
                    source_hash=step.source_hash,
                    destination_hash=step.destination_hash,
                    restored=False,
                )
            )
    error = f"migration rolled back after failure: {cause}"
    if restore_failures:
        error += "; restore failed for: " + ", ".join(restore_failures)
    logger.warning("migration %s rolled back: %s", plan.transaction_id, cause)
    return MigrationEvidence(
        transaction_id=plan.transaction_id,
        world=plan.world,
        outcome=MigrationOutcome.ROLLED_BACK,
        steps=tuple(restored_steps),
        restore_verified=verified,
        started_at=started_at,
        finished_at=_iso_now(),
        error=error,
    )


# ---------------------------------------------------------------------------
# Evidence persistence
# ---------------------------------------------------------------------------


def _step_to_dict(step: MigrationStep) -> dict:
    return {
        "folder": step.folder,
        "source": str(step.source),
        "destination": str(step.destination),
        "source_hash": step.source_hash,
        "destination_hash": step.destination_hash,
        "restored": step.restored,
    }


def _evidence_to_dict(evidence: MigrationEvidence) -> dict:
    return {
        "schema": EVIDENCE_SCHEMA_VERSION,
        "transaction_id": evidence.transaction_id,
        "world": evidence.world,
        "outcome": evidence.outcome.value,
        "restore_verified": evidence.restore_verified,
        "started_at": evidence.started_at,
        "finished_at": evidence.finished_at,
        "error": evidence.error,
        "steps": [_step_to_dict(step) for step in evidence.steps],
    }


def _persist_evidence(evidence: MigrationEvidence, evidence_dir: Path) -> None:
    """Atomic tmp+rename JSON write of the outcome evidence record."""
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            _evidence_to_dict(evidence), ensure_ascii=False, indent=2
        ) + "\n"
        target = evidence_dir / f"{evidence.transaction_id}.json"
        tmp = evidence_dir / f"{evidence.transaction_id}.json.tmp"
        tmp.write_text(payload, encoding="utf-8", newline="\n")
        json.loads(tmp.read_text(encoding="utf-8"))  # validate before rename
        os.replace(tmp, target)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationError(
            MigrationErrorKind.IO_ERROR,
            f"migration {evidence.outcome.value} but evidence could not be "
            f"persisted for transaction {evidence.transaction_id}: {exc}",
            evidence.transaction_id,
        ) from exc
