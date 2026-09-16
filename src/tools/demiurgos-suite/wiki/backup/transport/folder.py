# -*- coding: utf-8 -*-
"""``FolderTransport`` — the MVP local-folder transport (WU-5 write, WU-6 history).

Implements :class:`backup.transport.base.BackupTransport`: the REQ-BE-1 tree
layout, the non-destructive ``current/`` publisher (REQ-BE-3, REQ-BE-10.1), the
``meta/`` store (REQ-BE-8), the name-exact listing (SC-BE-1.2) and the three
HISTORY verbs — the immutable ``publish_snapshot`` (REQ-BE-4), the policy
``prune`` (REQ-BE-7) and the restore ``fetch`` (REQ-RS-1) — so all nine verbs
exist and ``isinstance(transport, BackupTransport)`` is ``True``.

**Atomicity (SC-BE-3.3).** Every document is written to ``<name>.tmp-<uuid>`` in
its own destination directory then ``os.replace``, so a temp name is never a final
name. A snapshot is filled in a sibling ``snapshots/.<id>.tmp-<uuid>/`` directory
and moved in with a SINGLE ``os.rename``; because the final name must not already
exist, immutability is enforced by the filesystem, not by a caller's promise
(REQ-BE-4, SC-BE-4.1).
**Non-destructiveness (REQ-BE-10.1).** ``publish_current`` only writes or
overwrites, so a locally deleted file stays recoverable in ``current/`` (SC-BE-3.2);
the only unlink is cleanup of this module's OWN failed temp file, and ``prune`` —
the one allowed deletion verb — removes only the snapshot ids it is given.
**Name safety (REQ-BE-9, WU-6b).** Every caller-supplied relative path is
NFC-normalized and validated BEFORE anything is published: a traversal
component, an absolute path, a Windows reserved name (with or without an
extension), a trailing dot/space, an over-long component (>200) or path (>240),
and a collision between two distinct sources that normalize to one path are all
rejected with :class:`TransportError` naming the offender — so a rejected batch
publishes nothing and never leaves a partial tree.
**Payload typing.** ``publish_current``/``publish_snapshot`` take
``Mapping[str, bytes]``; WU-8 may tighten the seam's opaque ``Any``.
"""

from __future__ import annotations

import errno
import json
import os
import re
import shutil
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from backup.transport.base import (
    FetchResult,
    PruneResult,
    PublishResult,
    SnapshotInfo,
    SnapshotRef,
    TargetCapabilities,
    TransportError,
)

#: The only snapshot names ``list_snapshots()`` accepts (SC-BE-1.2).
SNAPSHOT_ID_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{6}Z$")
#: Backoff before each lock retry — three retries after the first attempt (REQ-BE-3).
LOCK_RETRY_DELAYS: tuple[float, ...] = (0.2, 0.5, 1.0)
_BACKUP_DIR = "Demiurgos"
_SUBDIRS = ("current", "snapshots", "meta", "world-trash-index")

#: Windows device names reserved in every directory, case-insensitively and with
#: or without an extension (REQ-BE-9).
_WINDOWS_RESERVED_NAMES = frozenset(
    ("CON", "PRN", "AUX", "NUL")
    + tuple(f"COM{n}" for n in range(1, 10))
    + tuple(f"LPT{n}" for n in range(1, 10))
)
#: A Windows drive-qualified path ("C:", "C:\\x") — an absolute staged path.
_WINDOWS_ABSOLUTE_PATTERN = re.compile(r"^[A-Za-z]:")
#: Name-safety bounds (REQ-BE-9).
_MAX_COMPONENT_LENGTH = 200
_MAX_RELATIVE_PATH_LENGTH = 240


def _normalize_staged_path(source: Any) -> str:
    """NFC-normalize one staged relative path, rejecting an unsafe name.

    Raises :class:`TransportError` here, BEFORE any byte is written, so a
    rejected name can never leave a partial tree behind. Rejections cover an
    absolute path, a ``..``/``.``/empty component (path traversal that would
    escape the target root), a Windows reserved name with or without an
    extension, a trailing dot or space, a component over
    :data:`_MAX_COMPONENT_LENGTH`, and a full path over
    :data:`_MAX_RELATIVE_PATH_LENGTH`.
    """
    if not isinstance(source, str) or not source:
        raise TransportError(f"staged path {source!r} is empty or not a string")
    if source.startswith(("/", "\\")) or _WINDOWS_ABSOLUTE_PATTERN.match(source):
        raise TransportError(
            f"staged path {source!r} is absolute; only relative paths are allowed"
        )
    normalized = unicodedata.normalize("NFC", source)
    for component in re.split(r"[\\/]", normalized):
        if component in ("", ".", ".."):
            raise TransportError(
                f"staged path {source!r} has an unsafe path component {component!r}"
            )
        if len(component) > _MAX_COMPONENT_LENGTH:
            raise TransportError(
                f"staged path {source!r} has a component longer than "
                f"{_MAX_COMPONENT_LENGTH} characters: {component!r}"
            )
        if component.endswith((".", " ")):
            raise TransportError(
                f"staged path {source!r} has a component ending in a dot or "
                f"space: {component!r}"
            )
        if component.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
            raise TransportError(
                f"staged path {source!r} uses the Windows reserved name "
                f"{component!r}"
            )
    if len(normalized) > _MAX_RELATIVE_PATH_LENGTH:
        raise TransportError(
            f"staged path {source!r} is longer than "
            f"{_MAX_RELATIVE_PATH_LENGTH} characters"
        )
    return normalized


def _nfc_staged_set(staged: Mapping[str, Any]) -> dict[str, Any]:
    """NFC-normalize every staged path and reject collisions BEFORE any write.

    A collision is two DISTINCT source paths that normalize to the SAME NFC
    path: the run fails loudly naming BOTH original sources, so no entry is ever
    silently dropped or overwritten (SC-BE-9.1). The whole set is validated
    before the first write, so a collision never produces a half-published tree.
    """
    normalized: dict[str, Any] = {}
    origin: dict[str, str] = {}
    for source, payload in staged.items():
        name = _normalize_staged_path(source)
        if name in origin and origin[name] != source:
            raise TransportError(
                f"staged paths {origin[name]!r} and {source!r} collide after NFC "
                f"normalization to {name!r}"
            )
        origin[name] = source
        normalized[name] = payload
    return normalized


def _temp_path(dest: Path) -> Path:
    """``<name>.tmp-<uuid>`` beside *dest*, so ``os.replace`` stays same-volume."""
    return dest.with_name(f"{dest.name}.tmp-{uuid.uuid4().hex}")


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _is_lock_error(exc: OSError) -> bool:
    """True for a sharing/access failure a sync client can cause by holding a handle."""
    if isinstance(exc, PermissionError):
        return True
    if getattr(exc, "winerror", None) == 32:  # Windows ERROR_SHARING_VIOLATION
        return True
    return getattr(exc, "errno", None) == errno.EBUSY


def _measure(directory: Path) -> tuple[int, int]:
    """``(file count, total bytes)`` under *directory*, from the real listing."""
    count = total = 0
    for root, _dirs, names in os.walk(directory):
        for name in names:
            count += 1
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return count, total


class FolderTransport:
    """Write-side transport over a local (optionally cloud-synced) folder.

    ``root`` is the user-chosen destination folder; the tree lives under
    ``root/Demiurgos/``. ``data_root`` is optional and only sharpens
    ``probe().same_volume_as_data_root``. ``sleep`` is injected so the retry
    backoff is exercised without real waiting in tests.
    """

    def __init__(
        self,
        root: Path,
        *,
        data_root: Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.root = Path(root)
        self._tree = self.root / _BACKUP_DIR
        self._data_root = Path(data_root) if data_root is not None else None
        self._sleep = sleep

    def ensure_layout(self) -> None:
        """Create ``Demiurgos/{current,snapshots,meta,world-trash-index}``, idempotently."""
        for name in _SUBDIRS:
            (self._tree / name).mkdir(parents=True, exist_ok=True)

    def probe(self) -> TargetCapabilities:
        """Report destination capabilities without writing a byte.

        ``mode_hint`` is ``"unknown"``: the verified classification is WU-12's
        ``sync_folder.classify_target``, and a guess must never say "streaming".
        """
        same_volume = False
        if self._data_root is not None:
            try:
                same_volume = self.root.stat().st_dev == self._data_root.stat().st_dev
            except OSError:
                pass
        return TargetCapabilities(
            kind="folder",
            path=str(self.root),
            writable=self._target_is_writable(),
            same_volume_as_data_root=same_volume,
            mode_hint="unknown",
        )

    def publish_current(
        self, staged: Any, *, manifest: Mapping[str, Any]
    ) -> PublishResult:
        """Add or overwrite ``current/`` entries. Never deletes, never mirrors.

        Name safety runs FIRST over the WHOLE staged set (REQ-BE-9): every path
        is NFC-normalized, a collision between two distinct sources fails loudly
        naming both, and an unsafe name is rejected BEFORE the destination is
        touched — a rejected batch publishes nothing and cannot leave a partial
        tree.

        ``manifest`` is part of the seam shape but is not consulted yet; the
        incremental "changed files only" decision belongs to the caller (WU-9),
        so ``skipped`` stays 0 and the transport never drops an entry.
        """
        normalized = _nfc_staged_set(staged)
        current_dir = self._tree / "current"
        current_dir.mkdir(parents=True, exist_ok=True)
        published = total = 0
        for name, payload in normalized.items():
            data = payload if isinstance(payload, bytes) else bytes(payload)
            dest = self._destination_under(current_dir, name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            self._write_atomic(dest, data)
            published += 1
            total += len(data)
        return PublishResult(published=published, skipped=0, bytes=total)

    def publish_snapshot(self, snapshot_id: str, staged: Any) -> PublishResult:
        """Publish an immutable snapshot atomically, or fail if the id exists.

        The staged payload is filled into ``snapshots/.<id>.tmp-<uuid>/`` and then
        moved into place with ONE ``os.rename``. The final directory must not
        already exist, so immutability is enforced by the filesystem — a second
        publish of the same id raises :class:`TransportError` and leaves the
        existing snapshot byte-identical (REQ-BE-4, SC-BE-4.1). On any failure the
        temp directory is removed, so no partial snapshot is ever visible.

        The caller-supplied ``snapshot_id`` and every staged path pass the same
        NFC/name-safety gate as ``publish_current`` BEFORE the destination is
        touched, so a traversal id or an unsafe entry publishes nothing
        (REQ-BE-9).
        """
        safe_id = _normalize_staged_path(snapshot_id)
        normalized = _nfc_staged_set(staged)
        snapshots_dir = self._tree / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        target = snapshots_dir / safe_id
        if target.exists():
            raise TransportError(
                f"snapshot {safe_id} already exists at {target}; "
                "snapshots are immutable"
            )
        temp = snapshots_dir / f".{safe_id}.tmp-{uuid.uuid4().hex}"
        published = total = 0
        try:
            temp.mkdir()
            for name, payload in normalized.items():
                data = payload if isinstance(payload, bytes) else bytes(payload)
                dest = self._destination_under(temp, name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                self._write_atomic(dest, data)
                published += 1
                total += len(data)
            os.rename(temp, target)
        except BaseException:
            shutil.rmtree(temp, ignore_errors=True)
            raise
        return PublishResult(published=published, skipped=0, bytes=total)

    def prune(self, snapshot_ids: Sequence[str]) -> PruneResult:
        """Delete the given snapshots, collecting failures instead of raising.

        Each id is removed with ``shutil.rmtree`` under the shared 3x backoff retry
        (a sync client can hold a handle). A failed id is recorded as an
        ``(id, error)`` pair in :attr:`PruneResult.failed`, NEVER reported as
        deleted, and its snapshot is left on the destination (REQ-BE-7). The
        candidates come only from *snapshot_ids* — this verb invents no retention
        policy (that is WU-10) and never touches ``current/``.
        """
        snapshots_dir = self._tree / "snapshots"
        deleted: list[str] = []
        failed: list[tuple[str, str]] = []
        for snapshot_id in snapshot_ids:
            target = snapshots_dir / snapshot_id

            def attempt(target: Path = target) -> None:
                shutil.rmtree(target)

            try:
                self._with_lock_retry(target, attempt)
            except (TransportError, OSError) as exc:
                failed.append((snapshot_id, str(exc)))
            else:
                deleted.append(snapshot_id)
        return PruneResult(deleted=tuple(deleted), failed=tuple(failed))

    def read_meta(self, name: str) -> Mapping[str, Any] | None:
        """Read a ``meta/`` JSON document, or ``None`` when it does not exist yet.

        A caller-supplied ``name`` is NFC-normalized and gated by the same
        name-safety rules as a staged path (REQ-BE-9), so a traversal read is
        refused instead of reached.
        """
        path = self._tree / "meta" / _normalize_staged_path(name)
        if not path.is_file():
            return None
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise TransportError(f"cannot read backup meta {path}: {exc}") from exc
        if not isinstance(document, dict):
            raise TransportError(f"backup meta {path} is not a JSON object")
        return document

    def write_meta(self, name: str, payload: Mapping[str, Any]) -> None:
        """Write a ``meta/`` document atomically (temp name then ``os.replace``).

        The caller-supplied ``name`` is NFC-normalized and rejected when unsafe
        BEFORE the destination is touched (REQ-BE-9).
        """
        safe_name = _normalize_staged_path(name)
        meta_dir = self._tree / "meta"
        meta_dir.mkdir(parents=True, exist_ok=True)
        data = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self._write_atomic(self._destination_under(meta_dir, safe_name), data)

    def list_snapshots(self) -> list[SnapshotInfo]:
        """List the snapshots actually present under ``snapshots/``.

        Only :data:`SNAPSHOT_ID_PATTERN` names are visible, so ``.tmp-*`` and
        unparsable names are invisible (SC-BE-1.2). Completeness is listing-derived
        — no ``meta/manifest.json`` means ``complete=False`` (checksums: WU-13).
        """
        snapshots_dir = self._tree / "snapshots"
        if not snapshots_dir.is_dir():
            return []
        infos: list[SnapshotInfo] = []
        for entry in sorted(snapshots_dir.iterdir()):
            if not entry.is_dir() or not SNAPSHOT_ID_PATTERN.match(entry.name):
                continue
            entries, size = _measure(entry)
            infos.append(SnapshotInfo(
                snapshot_id=entry.name,
                complete=(entry / "meta" / "manifest.json").is_file(),
                entries=entries,
                bytes=size,
            ))
        return infos

    def fetch(self, snapshot_ref: SnapshotRef, dest_dir: Path) -> FetchResult:
        """Copy a snapshot's tree into *dest_dir*, creating it as needed.

        Restaging a snapshot out to a destination for restore (REQ-RS-1). The
        data root is never touched here — whole-root restore is WU-13; this verb
        only copies one snapshot out and reports what it copied.
        """
        source = self._tree / "snapshots" / snapshot_ref.snapshot_id
        if not source.is_dir():
            raise TransportError(
                f"snapshot {snapshot_ref.snapshot_id} not found under {source.parent}"
            )
        destination = Path(dest_dir)
        destination.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(source, destination, dirs_exist_ok=True)
        except OSError as exc:
            raise TransportError(
                f"cannot fetch snapshot {snapshot_ref.snapshot_id} into "
                f"{destination}: {exc}"
            ) from exc
        entries, size = _measure(destination)
        return FetchResult(dest_dir=destination, entries=entries, bytes=size)

    def _target_is_writable(self) -> bool:
        """Writability of the destination, tolerating a not-yet-created root."""
        path = self.root
        if path.exists():
            return path.is_dir() and os.access(path, os.W_OK)
        while not path.exists() and path.parent != path:
            path = path.parent
        return os.access(path, os.W_OK)

    def _destination_under(self, base: Path, name: str) -> Path:
        """Join *name* under *base*, proving the result cannot escape *base*.

        Belt-and-suspenders alongside the ``..`` component rejection in
        :func:`_normalize_staged_path`: even if a normalized path somehow
        contained a traversal, the resolved destination must still sit under
        *base* or the publish is refused (REQ-BE-9, SC-BE-9.2).
        """
        destination = base / name
        if not Path(os.path.normpath(destination)).is_relative_to(
            Path(os.path.normpath(base))
        ):
            raise TransportError(f"staged path {name!r} escapes {base}")
        return destination

    def _write_atomic(self, dest: Path, data: bytes) -> None:
        """Write *data* to *dest* via a same-directory temp file and ``os.replace``."""
        temp = _temp_path(dest)

        def attempt() -> None:
            with open(temp, "wb") as handle:
                handle.write(data)
            os.replace(temp, dest)

        try:
            self._with_lock_retry(dest, attempt)
        except BaseException:
            _unlink_quietly(temp)
            raise

    def _with_lock_retry(self, path: Path, operation: Callable[[], None]) -> None:
        """Run *operation*; retry a locked destination, then fail naming *path*."""
        last: OSError | None = None
        for attempt_index in range(len(LOCK_RETRY_DELAYS) + 1):
            try:
                operation()
                return
            except OSError as exc:
                if not _is_lock_error(exc):
                    raise
                last = exc
                if attempt_index < len(LOCK_RETRY_DELAYS):
                    self._sleep(LOCK_RETRY_DELAYS[attempt_index])
        raise TransportError(
            f"destination locked after {len(LOCK_RETRY_DELAYS)} retries: {path}"
        ) from last
