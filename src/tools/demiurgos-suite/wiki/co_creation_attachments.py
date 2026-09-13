"""Co-creation exemplar attachment staging (S2 — author-example-attachments).

The canvas uploads one exemplar at a time into a session-scoped staging dir.
Ownership is the session principal (enforced by the API session store, not
here): a foreign principal never reaches this module. Bytes move only at
materialize time (``move_staged``, D3) so a rejected upload or an abandoned
session can never leave a partial ``attachments/`` tree.

Validation lives here so the API route can run every check BEFORE any write
(zero mutation on rejection). ``store_staged`` publishes one file atomically
(per-file ``.tmp`` + ``os.replace``); ``move_staged`` copies the pinned files
into ``attachments/{skill_id}/`` and rolls back every file it already moved if
any single move fails.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from methodology_compiler import (
    MAX_ADJUNTO_BYTES,
    MAX_ADJUNTOS,
    MAX_NIVEL_LEN,
    _RESERVED_ATTACHMENT_PREFIXES,
)

STAGING_SUBDIR = Path("data") / "methodology" / "staging"
"""Per-session staging root, relative to the project root (runtime data)."""

ATTACHMENTS_SUBDIR = Path("data") / "methodology" / "attachments"
"""Author carrier root, relative to the project root (runtime data)."""


class AttachmentUploadError(Exception):
    """A rejected exemplar upload: HTTP status + stable wire code + message.

    The API maps this to a structured JSON error (``{detail, code, message,
    retryable}``) WITHOUT mutating any staged bytes — every guard runs before
    the first write.
    """

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def staging_dir_for(project_root: Path, session_id: str) -> Path:
    """The session-scoped staging directory (never created here).

    Pure resolver: resolving a path has no filesystem side effect, so callers
    that write materialize it lazily via ``store_staged``.
    """
    return Path(project_root) / STAGING_SUBDIR / session_id


def staged_names(staging_dir: Path) -> list[str]:
    """Sorted basenames of the ``.md`` files already staged (empty if absent).

    A transient ``*.tmp`` publish artifact is never counted: the count the
    upload guard enforces is the number of committed exemplars.
    """
    directory = Path(staging_dir)
    if not directory.is_dir():
        return []
    return sorted(
        item.name
        for item in directory.iterdir()
        if item.is_file() and item.name.endswith(".md")
    )


def _validated_basename(filename: str) -> str:
    """Guard 4: a safe ``.md`` basename, or a typed 422 ``invalid_input``."""
    if (
        not filename
        or filename != os.path.basename(filename)
        or "/" in filename
        or "\\" in filename
        or ".." in filename
        or not filename.endswith(".md")
        or filename.startswith(_RESERVED_ATTACHMENT_PREFIXES)
    ):
        raise AttachmentUploadError(
            422, "invalid_input",
            "The attachment name must be a plain Markdown basename outside "
            "mundos/** and referencias/**.",
        )
    return filename


def _validated_nivel(nivel: str) -> None:
    """Guard 5: a non-empty bounded narrative-density label (422 otherwise)."""
    if not isinstance(nivel, str) or not nivel.strip():
        raise AttachmentUploadError(
            422, "invalid_input", "The attachment nivel label is required.",
        )
    if len(nivel.strip()) > MAX_NIVEL_LEN:
        raise AttachmentUploadError(
            422, "invalid_input",
            f"The attachment nivel label exceeds {MAX_NIVEL_LEN} characters.",
        )


def validate_staged_upload(
    staging_dir: Path,
    filename: str,
    data: bytes,
    nivel: str,
) -> str:
    """Run guards 3–8 in order and return the normalized basename.

    Order (fail-closed, every check BEFORE any write):
    3. empty bytes -> 400 ``invalid_input``
    4. unsafe filename -> 422 ``invalid_input``
    5. bad ``nivel`` -> 422 ``invalid_input``
    6. bytes > ``MAX_ADJUNTO_BYTES`` -> 422 ``attachment_limit_reached``
    7. staged count >= ``MAX_ADJUNTOS`` -> 422 ``attachment_limit_reached``
    8. duplicate basename -> 409 ``attachment_conflict``
    """
    if not data:
        raise AttachmentUploadError(
            400, "invalid_input", "The attachment is empty.",
        )
    basename = _validated_basename(filename)
    _validated_nivel(nivel)
    if len(data) > MAX_ADJUNTO_BYTES:
        raise AttachmentUploadError(
            422, "attachment_limit_reached",
            f"The attachment exceeds {MAX_ADJUNTO_BYTES} bytes.",
        )
    existing = staged_names(staging_dir)
    if len(existing) >= MAX_ADJUNTOS:
        raise AttachmentUploadError(
            422, "attachment_limit_reached",
            f"A skill accepts at most {MAX_ADJUNTOS} attachments.",
        )
    if basename in existing:
        raise AttachmentUploadError(
            409, "attachment_conflict",
            f"The attachment {basename!r} is already staged.",
        )
    return basename


def store_staged(dest_dir: Path, path: str, data: bytes) -> None:
    """Write one staged exemplar atomically (per-file ``.tmp`` + ``os.replace``).

    A crash or a failed write can never expose a half-written ``.md``: the
    bytes land in a sibling ``.tmp`` first and only the successful ``os.replace``
    publishes them.
    """
    directory = Path(dest_dir)
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / path
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _rmdir_if_empty(path: Path) -> None:
    try:
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    except OSError:
        pass


def move_staged(
    staging_dir: Path,
    attachments_root: Path,
    skill_id: str,
    pins: tuple,
) -> list[Path]:
    """Move pinned staged exemplars into ``attachments/{skill_id}/`` (D3).

    Each file is published atomically (``.tmp`` + ``os.replace``). If ANY move
    fails, every file already moved by this call is removed and the skill dir is
    removed when it is left empty — so a failed materialize never leaves a
    partial ``attachments/`` tree. Pre-existing files in the skill dir are never
    touched by the rollback. Returns the moved destination paths in pin order.
    """
    staging = Path(staging_dir)
    dest_dir = Path(attachments_root) / skill_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    moved: list[Path] = []
    temps: list[Path] = []
    try:
        for pin in pins:
            name = pin.path
            dest = dest_dir / name
            tmp = dest.with_name(dest.name + ".tmp")
            tmp.write_bytes((staging / name).read_bytes())
            temps.append(tmp)
            os.replace(tmp, dest)
            temps.remove(tmp)
            moved.append(dest)
    except Exception:
        for tmp in temps:
            try:
                tmp.unlink()
            except OSError:
                pass
        for dest in moved:
            try:
                dest.unlink()
            except OSError:
                pass
        _rmdir_if_empty(dest_dir)
        raise
    return moved


def sweep_staging(project_root: Path, older_than_days: float) -> int:
    """Best-effort removal of abandoned session staging dirs (AE-2).

    Removes every direct child of ``data/methodology/staging/`` whose mtime is
    older than ``older_than_days`` and returns how many were removed. Only the
    staging root is ever walked: ``attachments/`` is never touched. Every
    filesystem error is swallowed so a cleanup sweep can never fail a request.
    """
    staging_root = Path(project_root) / STAGING_SUBDIR
    if not staging_root.is_dir():
        return 0
    cutoff = time.time() - older_than_days * 86_400
    removed = 0
    for entry in staging_root.iterdir():
        try:
            if not entry.is_dir() or entry.stat().st_mtime >= cutoff:
                continue
            shutil.rmtree(entry)
            removed += 1
        except OSError:
            continue
    return removed
