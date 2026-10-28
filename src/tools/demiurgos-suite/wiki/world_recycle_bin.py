# -*- coding: utf-8 -*-
"""World-level recycle bin — move worlds to trash, restore, and purge.

Layout (spec REQ-003)::

    data/world-trash/{world}/{deleted_at}/            # moved world directory
    data/world-trash/{world}/{deleted_at}/meta.json   # metadata snapshot

A world is moved whole (``shutil.move``) so restore is a directory move back
to ``mundos/{world}``. ``meta.json`` records provenance and entity counts so
the trash can be listed and purged without touching the original tree.

This module is strictly filesystem work: it never touches API-server state.
Cleaning the in-process associations of a purged world (graph cache, guided
sessions, idea-capture rows) is the API server's responsibility, so this
module stays importable standalone (tests never pull ``api_server``).

Injection seams: ``TRASH_ROOT`` and ``MUNDOS_DIR`` are module-level attributes
resolved lazily from the data root (WU-2) — never at import time, because the
resolver fails loudly when no root is configured. Every function accepts
optional ``trash_root``/``mundos_dir`` keyword arguments that override them, so
pytest can point them at ``tmp_path`` either by monkeypatching the constants
(they stay plain writable module attributes) or by passing explicit paths.
"""

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from state_paths import resolve_state_dir

# Fallback seam: ``None`` means "resolve from the data root on use". Tests keep
# replacing these attributes directly; the accessors below read them at call time.
TRASH_ROOT: Path | None = None
MUNDOS_DIR: Path | None = None
RETENTION_DAYS = 30


def default_world_trash_root() -> Path:
    """``<data root>/data/world-trash`` (WU-2); never resolved at import time."""
    return resolve_state_dir() / "world-trash"


def default_mundos_dir() -> Path:
    """``<data root>/mundos`` (WU-2); never resolved at import time."""
    return resolve_data_root() / "mundos"


def _trash_root() -> Path:
    return TRASH_ROOT if TRASH_ROOT is not None else default_world_trash_root()


def _mundos_dir() -> Path:
    return MUNDOS_DIR if MUNDOS_DIR is not None else default_mundos_dir()

_META_NOTE = "associated data hidden; cleaned on purge"
_ENTITY_SECTIONS = ("lore", "personajes")


@dataclass(frozen=True)
class TrashEntry:
    """One trash entry (spec REQ-004 response shape, minus computed fields)."""

    world_name: str
    deleted_at: datetime
    size_bytes: int
    lore_count: int
    character_count: int
    days_remaining: int

    def as_dict(self) -> dict:
        """Serialize to the API response shape (ISO-8601 UTC with Z suffix)."""
        out = asdict(self)
        out["deleted_at"] = (
            self.deleted_at.astimezone(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        return out


def _validate_world_name(world_name: str) -> str:
    """Reject empty, separator-bearing, or dot-segment world names."""
    if not isinstance(world_name, str) or not world_name:
        raise ValueError("world name is empty")
    if Path(world_name).name != world_name or world_name in {".", ".."}:
        raise ValueError(f"invalid world name: {world_name!r}")
    return world_name


def _entity_counts(world_dir: Path) -> dict:
    counts = {"lore_count": 0, "character_count": 0}
    for section, key in (
        ("lore", "lore_count"),
        ("personajes", "character_count"),
    ):
        section_dir = world_dir / section
        if section_dir.is_dir():
            counts[key] = len(list(section_dir.rglob("*.md")))
    return counts


def _dir_size_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(value: datetime) -> str:
    """ISO-8601 UTC string with 'Z' suffix (matches spec meta.json schema)."""
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _stamp(value: datetime) -> str:
    """Filesystem-safe, sortable timestamp for the entry directory name."""
    return _iso_z(value).replace(":", "-")


def _world_entries(root: Path, world_name: str) -> list[Path]:
    """Trash entry directories for *world_name*, newest first."""
    world_root = root / world_name
    if not world_root.is_dir():
        return []
    return sorted((p for p in world_root.iterdir() if p.is_dir()), reverse=True)


def _prune_empty_world_dir(root: Path, world_name: str) -> None:
    world_root = root / world_name
    try:
        if world_root.is_dir() and not any(world_root.iterdir()):
            world_root.rmdir()
    except OSError:
        pass


def move_to_trash(
    world_name: str,
    *,
    trash_root: Path | None = None,
    mundos_dir: Path | None = None,
) -> TrashEntry:
    """Move a world directory into the recycle bin and write ``meta.json``.

    Raises ``ValueError`` when the world does not exist in ``mundos_dir`` or
    the name is invalid. Returns the created ``TrashEntry``.
    """
    _validate_world_name(world_name)
    root = Path(trash_root) if trash_root is not None else _trash_root()
    mundos = Path(mundos_dir) if mundos_dir is not None else _mundos_dir()
    source = mundos / world_name
    if not source.is_dir():
        raise ValueError(f"world not found: {world_name}")

    deleted_at = _now_utc()
    target = root / world_name / _stamp(deleted_at)
    target.parent.mkdir(parents=True, exist_ok=True)

    size_bytes = _dir_size_bytes(source)
    counts = _entity_counts(source)

    shutil.move(str(source), str(target))
    meta = {
        "world_name": world_name,
        "deleted_at": _iso_z(deleted_at),
        "size_bytes": size_bytes,
        "lore_count": counts["lore_count"],
        "character_count": counts["character_count"],
        "note": _META_NOTE,
    }
    (target / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    return TrashEntry(
        world_name=world_name,
        deleted_at=deleted_at,
        size_bytes=size_bytes,
        lore_count=counts["lore_count"],
        character_count=counts["character_count"],
        days_remaining=RETENTION_DAYS,
    )


def _unique_restore_name(mundos: Path, base: str) -> str:
    """Return a name derived from *base* that does not exist under *mundos*.

    Auto-naming (conflict resolution): ``<base> (restaurado)``, then
    ``<base> (restaurado) 2``, ``3``, ... until a free name is found.
    """
    candidate = f"{base} (restaurado)"
    n = 2
    while (mundos / candidate).exists():
        candidate = f"{base} (restaurado) {n}"
        n += 1
    return candidate


def restore_from_trash(
    world_name: str,
    *,
    new_name: str | None = None,
    trash_root: Path | None = None,
    mundos_dir: Path | None = None,
) -> str:
    """Move the most recent trash entry for *world_name* back to ``mundos_dir``.

    Returns the name it was restored under. ``new_name`` (optional) restores
    under a DIFFERENT name. When the destination name already exists AND no
    explicit ``new_name`` is given, an AUTO-NAME is generated so a conflict with
    an active world never blocks the restore. Raises ``FileNotFoundError`` when
    the world is not in the trash, and ``ValueError`` when an explicit
    ``new_name`` collides (the caller asked for an exact name).
    """
    _validate_world_name(world_name)
    root = Path(trash_root) if trash_root is not None else _trash_root()
    mundos = Path(mundos_dir) if mundos_dir is not None else _mundos_dir()
    entries = _world_entries(root, world_name)
    if not entries:
        raise FileNotFoundError(world_name)
    dest_name = new_name if new_name else world_name
    _validate_world_name(dest_name)
    target = mundos / dest_name
    if target.exists():
        if new_name:
            raise ValueError(f"world already exists: {dest_name}")
        dest_name = _unique_restore_name(mundos, world_name)
        target = mundos / dest_name
    shutil.move(str(entries[0]), str(target))
    _prune_empty_world_dir(root, world_name)
    return dest_name


def list_trash(*, trash_root: Path | None = None) -> list[TrashEntry]:
    """List trash entries sorted by ``deleted_at`` descending.

    Entries with a missing or corrupt ``meta.json`` are skipped and KEPT: a
    corrupt entry never crashes the listing nor gets silently destroyed
    (same policy as the per-ficha ``.papelera`` TTL purge).
    """
    root = Path(trash_root) if trash_root is not None else _trash_root()
    if not root.is_dir():
        return []
    now = _now_utc()
    entries = []
    for world_dir in sorted(root.iterdir()):
        if not world_dir.is_dir():
            continue
        for entry_dir in world_dir.iterdir():
            if not entry_dir.is_dir():
                continue
            meta_file = entry_dir / "meta.json"
            if not meta_file.is_file():
                continue
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                raw = meta["deleted_at"]
                if not isinstance(raw, str):
                    raise ValueError("deleted_at is not text")
                deleted_at = datetime.fromisoformat(
                    raw[:-1] + "+00:00" if raw.endswith("Z") else raw
                )
                if deleted_at.tzinfo is None:
                    raise ValueError("deleted_at is naive")
            except Exception:
                continue
            age_days = (now - deleted_at).days
            entries.append(
                TrashEntry(
                    world_name=str(meta.get("world_name") or world_dir.name),
                    deleted_at=deleted_at,
                    size_bytes=int(meta.get("size_bytes", 0)),
                    lore_count=int(meta.get("lore_count", 0)),
                    character_count=int(meta.get("character_count", 0)),
                    days_remaining=max(0, RETENTION_DAYS - age_days),
                )
            )
    entries.sort(key=lambda entry: entry.deleted_at, reverse=True)
    return entries


def _entry_is_expired(entry_dir: Path, threshold: datetime) -> bool:
    """True when the entry's ``deleted_at`` is strictly older than threshold."""
    meta_file = entry_dir / "meta.json"
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        raw = meta["deleted_at"]
        if not isinstance(raw, str):
            return False
        deleted_at = datetime.fromisoformat(
            raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        )
        return deleted_at.tzinfo is not None and deleted_at < threshold
    except Exception:
        return False


def purge_expired(
    *,
    trash_root: Path | None = None,
    on_purge: "Callable[[str], None] | None" = None,
) -> int:
    """Permanently delete trash entries older than ``RETENTION_DAYS``.

    Returns the number of entries purged. Malformed entries (unreadable
    ``meta.json``) are kept, matching the ``.papelera`` house policy.

    ``on_purge`` is an optional callback invoked once per world that had at
    least one expired entry removed. The API server uses it to re-assert
    associated-data cleanup (graph cache, guided sessions) without this
    filesystem module ever touching server state.
    """
    root = Path(trash_root) if trash_root is not None else _trash_root()
    if not root.is_dir():
        return 0
    threshold = _now_utc() - timedelta(days=RETENTION_DAYS)
    purged = 0
    for world_dir in list(root.iterdir()):
        if not world_dir.is_dir():
            continue
        world_purged = 0
        for entry_dir in list(world_dir.iterdir()):
            if not entry_dir.is_dir():
                continue
            if _entry_is_expired(entry_dir, threshold):
                shutil.rmtree(entry_dir, ignore_errors=True)
                world_purged += 1
        if world_purged:
            purged += world_purged
            if on_purge is not None:
                on_purge(world_dir.name)
        _prune_empty_world_dir(root, world_dir.name)
    return purged


def purge_world(world_name: str, *, trash_root: Path | None = None) -> None:
    """Permanently delete every trash entry for *world_name*.

    Raises ``FileNotFoundError`` when the world has no trash entry.
    """
    _validate_world_name(world_name)
    root = Path(trash_root) if trash_root is not None else _trash_root()
    world_dir = root / world_name
    if not world_dir.is_dir() or not _world_entries(root, world_name):
        raise FileNotFoundError(world_name)
    shutil.rmtree(world_dir, ignore_errors=True)