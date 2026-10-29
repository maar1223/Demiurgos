# -*- coding: utf-8 -*-
"""Move the author's content to another folder or disk (step 5).

The whole operation is: PLAN (what travels, is there room, may we?), COPY,
VERIFY, PUBLISH the pointer — in that order and never partially:

* the pointer is written ONLY after the copy verified, so a cancelled, failed or
  interrupted move leaves the install exactly as it was;
* the source is never modified (no delete, no rename, no truncate), not even on
  success — deleting it is a separate, explicitly confirmed action;
* machine state never travels: what moves is the author content, classified by
  the same rules the backup already uses, plus the content-root ``.env``.

The author content set comes from :func:`backup.inventory.build_inventory`, which
is exactly the right classification and already has its own cells: it INCLUDES
every unrecognised top-level member by default (a new folder is never silently
dropped) and EXCLUDES machine state, VCS metadata, caches and the project's own
source tree. That last part matters: the content root may legitimately be a code
checkout, and copying a repository is not moving the author's worlds.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

from backup.inventory import build_inventory

#: Carried with the content on purpose: without it the new root boots without
#: ``DEMIURGOS_AUTH_MODE`` and the app fails closed. The backup excludes it as
#: secret material; a move is not a backup.
CONTENT_ENV_FILE = ".env"

#: How much a copy reads at a time while hashing.
_CHUNK = 1024 * 1024

#: Names a MOVE leaves behind that the backup's table classifies as content.
#: They are not: a tool cache and the legacy machine-state files at the checkout
#: root. The backup's table owns content classification, so the move carries its
#: own narrow deny list rather than changing what a snapshot captures.
MOVE_EXTRA_EXCLUSIONS: tuple[tuple[str, str], ...] = (
    (".wrangler", "excluded:tool-cache"),
    (".demiurgos-estado*.json", "excluded:local-machine-state"),
)

#: What a move may not overlap: the machine-state folder and the backup
#: destination (a copy stored inside what it copies is one copy and one failure).
Forbidden = Sequence[Path]


class MoveError(RuntimeError):
    """A move that must not start, or did not complete, with its reason."""


@dataclass(frozen=True)
class MovePlan:
    """What will travel and whether it may travel at all."""

    source: Path
    target: Path
    #: Top-level names that travel, for display.
    members: tuple[str, ...]
    #: Every relative path to copy, in order. Dirs are created, files copied:
    #: this is the inventory's own member list, so a per-FILE exclusion (the
    #: machine state that may sit under ``data/``) is honoured, not just a
    #: per-folder one.
    entries: tuple[str, ...]
    total_files: int
    total_bytes: int
    free_bytes: int
    #: Top-level members deliberately left behind: ``(name, reason)``.
    skipped: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "source": str(self.source),
            "target": str(self.target),
            "members": list(self.members),
            "entries": len(self.entries),
            "total_files": self.total_files,
            "total_bytes": self.total_bytes,
            "free_bytes": self.free_bytes,
            "skipped": [{"name": name, "reason": reason} for name, reason in self.skipped],
        }


@dataclass
class MoveOutcome:
    """What a completed move did. ``published`` is the only thing that matters."""

    copied_files: int = 0
    copied_bytes: int = 0
    published: bool = False
    cancelled: bool = False
    cleanup: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "copied_files": self.copied_files,
            "copied_bytes": self.copied_bytes,
            "published": self.published,
            "cancelled": self.cancelled,
        }


def _absolute(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _overlaps(first: Path, second: Path) -> bool:
    return (
        first == second
        or first.is_relative_to(second)
        or second.is_relative_to(first)
    )


def _extra_reason(name: str) -> str | None:
    for pattern, reason in MOVE_EXTRA_EXCLUSIONS:
        if fnmatch.fnmatch(name, pattern):
            return reason
    return None


def _entries(root: Path) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """``(entries, top-level names)`` of the author content, in a stable order.

    The entries are the inventory's OWN member list — that is what makes a
    per-file exclusion such as the machine state under ``data/`` effective. The
    content-root ``.env`` is added by hand because the backup excludes it as
    secret material and a move is not a backup.
    """
    inventory = build_inventory(root)
    entries = set(inventory.included)
    if (root / CONTENT_ENV_FILE).is_file():
        entries.add(CONTENT_ENV_FILE)
    extra: list[tuple[str, str]] = []
    for name in sorted({entry.split("/", 1)[0] for entry in entries}):
        reason = _extra_reason(name)
        if reason is not None:
            extra.append((name, reason))
            entries = {entry for entry in entries if entry.split("/", 1)[0] != name}
    ordered = sorted(entries)
    tops = sorted({entry.split("/", 1)[0] for entry in ordered})
    # Everything the inventory refused is reported at the path it refused, so
    # the author can see that a machine-state file under data/ stays behind.
    skipped = sorted({(item.path, item.reason) for item in inventory.excluded})
    skipped.extend(extra)
    return ordered, tops, sorted(set(skipped))


def _measure(root: Path, entries: Iterable[str]) -> tuple[int, int]:
    """``(files, bytes)`` of the regular files the move will copy."""
    files = 0
    size = 0
    for entry in entries:
        path = root / entry
        if path.is_dir() and not path.is_symlink():
            continue
        files += 1
        size += path.lstat().st_size
    return files, size


def plan_move(
    source: str | Path,
    target: str | Path,
    *,
    forbidden: Forbidden = (),
    free_bytes: int | None = None,
) -> MovePlan:
    """Validate the move and describe it, or raise :class:`MoveError`.

    Every refusal names what to change. Nothing is written here — not even the
    target directory.
    """
    if not Path(target).expanduser().is_absolute():
        raise MoveError("the destination folder must be an absolute path")
    src = _absolute(source)
    dst = _absolute(target)
    if not src.is_dir():
        raise MoveError(f"the content folder does not exist: {src}")
    if not dst.is_dir():
        raise MoveError(f"the destination folder must be an existing directory: {dst}")
    if _overlaps(src, dst):
        raise MoveError(
            f"the destination must be a different folder from the content root: "
            f"{dst} overlaps {src}"
        )
    for path in forbidden:
        other = _absolute(path)
        if _overlaps(dst, other):
            raise MoveError(f"the destination overlaps {other}")
    try:
        next(dst.iterdir())
    except StopIteration:
        pass
    else:
        raise MoveError(
            f"the destination folder must be empty: {dst} already holds content"
        )

    entries, members, skipped = _entries(src)
    if not members:
        raise MoveError(f"there is no author content to move in {src}")
    files, size = _measure(src, entries)
    if files == 0:
        raise MoveError(f"there are no files to move in {src}")

    available = (
        free_bytes
        if free_bytes is not None
        else shutil.disk_usage(dst).free
    )
    if available < size:
        raise MoveError(
            f"the destination has no room: {size} bytes are needed and "
            f"{available} are free in {dst}"
        )
    return MovePlan(
        source=src,
        target=dst,
        members=tuple(members),
        entries=tuple(entries),
        total_files=files,
        total_bytes=size,
        free_bytes=available,
        skipped=tuple(skipped),
    )


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _fingerprint(root: Path, entries: Iterable[str]) -> dict[str, tuple[str, str]]:
    """``relpath -> (kind, value)`` for the copied files.

    Regular files carry their sha256 and symlinks their target, so a copy that
    silently turned one into the other is caught too.
    """
    print_ = {}
    for entry in entries:
        path = root / entry
        if path.is_dir() and not path.is_symlink():
            continue
        if path.is_symlink():
            print_[entry] = ("link", os.readlink(path))
        elif path.is_file():
            print_[entry] = ("file", _digest(path))
    return print_


def _remove_partial(target: Path) -> None:
    """Empty the destination a failed or cancelled move created.

    The plan requires an empty destination, so everything inside it belongs to
    this attempt: leaving a half tree there would let a later start mistake it
    for content.
    """
    for entry in target.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)


def execute_move(
    plan: MovePlan,
    *,
    publish: Callable[[Path], None] | None = None,
    on_progress: Callable[[int, int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> MoveOutcome:
    """Copy, verify, and only then publish *plan.target* as the content root.

    ``publish`` is the pointer write (injected so the suite never touches the
    real config dir). A cancelled or failed move empties the destination and
    leaves the pointer alone.
    """
    outcome = MoveOutcome()
    cancelled = should_cancel or (lambda: False)
    progress = on_progress or (lambda files, total, size: None)

    for entry in plan.entries:
        if cancelled():
            _remove_partial(plan.target)
            outcome.cancelled = True
            return outcome
        origin = plan.source / entry
        destination = plan.target / entry
        try:
            if origin.is_dir() and not origin.is_symlink():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if origin.is_symlink():
                os.symlink(os.readlink(origin), destination)
            else:
                shutil.copy2(origin, destination)
        except OSError as exc:  # noqa: BLE001 — reported, never a traceback to the author
            _remove_partial(plan.target)
            raise MoveError(f"copying {entry} failed: {exc}") from exc
        outcome.copied_files += 1
        outcome.copied_bytes += origin.lstat().st_size
        progress(outcome.copied_files, plan.total_files, outcome.copied_bytes)

    if cancelled():
        _remove_partial(plan.target)
        outcome.cancelled = True
        return outcome

    # A cancel that arrives while hashing must still win: verification can take
    # minutes on a slow disk, and publishing after it would ignore the author.
    if cancelled():
        _remove_partial(plan.target)
        outcome.cancelled = True
        return outcome

    before = _fingerprint(plan.source, plan.entries)
    after = _fingerprint(plan.target, plan.entries)
    if before != after:
        _remove_partial(plan.target)
        missing = sorted(set(before) - set(after))
        differing = sorted(
            path for path in set(before) & set(after) if before[path] != after[path]
        )
        raise MoveError(
            "the copy did not verify, so nothing changed: "
            f"{len(missing)} missing, {len(differing)} different"
        )

    if cancelled():
        _remove_partial(plan.target)
        outcome.cancelled = True
        return outcome

    writer = publish or _default_publish
    writer(plan.target)
    outcome.published = True
    return outcome


def _default_publish(target: Path) -> None:
    import data_root  # flat sibling module

    data_root.write_pointer(target)


def delete_source(
    recorded: str | Path | None, typed: str, *, forbidden: Forbidden = ()
) -> str:
    """Delete the OLD copy of a completed move, or refuse and say why.

    Bound to the record: only the exact folder the last verified move left
    behind may be removed, and only when the author typed it back. ``forbidden``
    carries the paths a delete must never touch (the content root in use now and
    the machine-state folder).
    """
    if recorded is None:
        raise MoveError("there is no completed move to clean up")
    source = _absolute(recorded)
    if typed.strip() != str(source):
        raise MoveError(
            f"type the folder exactly to confirm: {source}"
        )
    if not source.is_dir():
        raise MoveError(f"the old folder is gone already: {source}")
    for path in forbidden:
        other = _absolute(path)
        if source == other or source.is_relative_to(other) or other.is_relative_to(source):
            raise MoveError(f"refusing to delete {source}: it overlaps {other}")
    if (source / ".git").exists():
        raise MoveError(
            f"refusing to delete {source}: it is a code checkout, not a content folder"
        )
    shutil.rmtree(source)
    return str(source)


# ---------------------------------------------------------------------------
# Destination candidates — the web-native answer to "I cannot browse the disk"
# ---------------------------------------------------------------------------

#: How many suggestions are useful before the list becomes noise.
MAX_CANDIDATES = 12


#: Filesystems that can never hold an author's content: snap/loop images, the
#: kernel's own trees, container overlays. Offering them was noise in the list.
DENIED_FILESYSTEMS = frozenset(
    {
        "squashfs",
        "proc",
        "sysfs",
        "devtmpfs",
        "devpts",
        "cgroup",
        "cgroup2",
        "overlay",
        "tmpfs",
        "ramfs",
        "nsfs",
        "tracefs",
        "debugfs",
        "securityfs",
        "pstore",
        "bpf",
        "configfs",
        "fusectl",
        "mqueue",
        "hugetlbfs",
        "autofs",
    }
)

#: Mount points that are never a destination even on a real filesystem.
DENIED_MOUNT_PREFIXES = (
    "/boot",
    "/snap",
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/var/lib/docker",
    "/var/lib/snapd",
)


def _mount_roots(mounts: str) -> list[Path]:
    """Real, writable block-device mount points from ``/proc/mounts``-shaped text.

    Only ``/dev/*`` devices, and never a filesystem from
    :data:`DENIED_FILESYSTEMS`, a kernel tree, or a snap/loop image: those showed
    up as "0 B" entries that no move could use.
    """
    roots: list[Path] = []
    for line in mounts.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        device, mount, fstype = fields[0], fields[1].replace("\\040", " "), fields[2]
        if not device.startswith("/dev/") or fstype in DENIED_FILESYSTEMS:
            continue
        if any(mount == prefix or mount.startswith(prefix + "/") for prefix in DENIED_MOUNT_PREFIXES):
            continue
        roots.append(Path(mount))
    return roots


def _default_mounts_text() -> str:
    if os.name == "nt":
        return ""
    try:
        return Path("/proc/mounts").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _documents_dir(home: Path) -> Path:
    try:
        import platformdirs  # optional dependency, same as data_root

        return Path(platformdirs.user_documents_dir())
    except Exception:  # noqa: BLE001 — a suggestion is never worth a failure
        return home / "Documents"


def _windows_drives() -> list[Path]:
    import string

    return [Path(f"{letter}:\\") for letter in string.ascii_uppercase if Path(f"{letter}:\\").exists()]


def destination_candidates(
    *,
    home: Path | None = None,
    mounts: str | None = None,
    current: Path | None = None,
    extra: Sequence[Path] = (),
    max_items: int = MAX_CANDIDATES,
) -> list[dict[str, object]]:
    """Folders worth offering as a destination, best first.

    The browser cannot browse the server's disk, so the honest equivalent is a
    list of the places a destination usually is: real mounted disks, the home
    folder, Documents, siblings of the current folder (and whatever the caller
    adds). Every entry is a click, and the manual path stays as the fallback.
    """
    resolved_home = (
        Path(home).expanduser()
        if home is not None
        else Path.home()
    )
    text = _default_mounts_text() if mounts is None else mounts

    roots: list[Path] = []
    if os.name == "nt" and mounts is None:
        roots.extend(_windows_drives())
    roots.extend(_mount_roots(text))
    # The well-known mount roots are a production convenience; a caller that
    # injects its own mounts text wants a deterministic list (tests, and any
    # future caller that knows better than our guess).
    scan_dirs = mounts is None
    for base in (
        [Path("/media"), Path("/mnt"), Path("/run/media")] if scan_dirs else []
    ):
        if base.is_dir():
            try:
                roots.extend(entry for entry in base.iterdir() if entry.is_dir())
            except OSError:
                continue
    roots.extend([resolved_home, _documents_dir(resolved_home)])
    if current is not None:
        roots.append(Path(current).parent)
    roots.extend(Path(path) for path in extra)

    seen: set[str] = set()
    candidates: list[dict[str, object]] = []
    current_root = None if current is None else _absolute(current)
    for root in roots:
        try:
            path = _absolute(root)
        except OSError:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if not path.is_dir():
            continue
        if current_root is not None and _overlaps(path, current_root):
            continue
        if not os.access(path, os.W_OK):
            # A destination the app cannot write into is not a destination.
            continue
        try:
            empty = next(path.iterdir(), None) is None
        except OSError:
            continue
        try:
            free = shutil.disk_usage(path).free
        except OSError:
            continue
        if free <= 0:
            continue
        candidates.append(
            {"path": key, "free_bytes": free, "is_empty": empty, "writable": True}
        )

    # An empty, writable folder is what a move needs: those come first, then the
    # ones with the most room.
    candidates.sort(
        key=lambda item: (
            not (item["is_empty"] and item["writable"]),
            -(item["free_bytes"] or 0),
            str(item["path"]),
        )
    )
    return candidates[:max_items]
