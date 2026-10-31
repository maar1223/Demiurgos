"""World-local memory of rejected relation pairs (P2).

P1 merges relations additively, so a relation the Author removes from a ficha
would come back on the next save: the deterministic pass cannot tell "this text
mentions it" from "the Author does not want it". This module stores that
curation decision next to the world it belongs to, so it travels with the world
on move, copy and backup.

Storage: ``<world>/.relations/rejected.json`` — a hidden directory outside the
content sections, so no content route can reach it and the Assistant never sees
it. The file is a deterministic, sorted list of ``[source_id, target_id]``
canonical-id pairs.

Fail-open by design: a missing, corrupt or unreadable store means "no
rejections". A bookkeeping failure must never break a save or a manual relation
edit.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

STORE_DIR = ".relations"
STORE_NAME = "rejected.json"
SCHEMA_VERSION = 1

# Serializes read-modify-write on the store inside this process.
_LOCK = threading.Lock()

Pair = tuple[str, str]


def store_path(world_dir: Path) -> Path:
    """Return the rejection store path for one world directory."""
    return Path(world_dir) / STORE_DIR / STORE_NAME


def load_rejected(world_dir: Path) -> set[Pair]:
    """Return every rejected ``(source_id, target_id)`` pair for the world."""
    path = store_path(world_dir)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return set()
    except OSError as exc:
        logger.warning("relations: cannot read rejections at %s: %s", path, exc)
        return set()
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("relations: corrupt rejections at %s; ignoring", path)
        return set()
    entries = data.get("rejected") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return set()
    pairs: set[Pair] = set()
    for entry in entries:
        if (
            isinstance(entry, (list, tuple))
            and len(entry) == 2
            and all(isinstance(value, str) and value for value in entry)
        ):
            pairs.add((entry[0], entry[1]))
    return pairs


def record_rejection(world_dir: Path, source_id: str, target_id: str) -> bool:
    """Remember that this pair must never be proposed again."""
    return _mutate(world_dir, add={(source_id, target_id)})


def clear_rejection(world_dir: Path, source_id: str, target_id: str) -> bool:
    """Forget a rejection: the Author asked for the relation explicitly."""
    return _mutate(world_dir, remove={(source_id, target_id)})


def _mutate(
    world_dir: Path,
    *,
    add: Iterable[Pair] = (),
    remove: Iterable[Pair] = (),
) -> bool:
    """Apply one change to the store. Returns True when the file changed."""
    if not world_dir:
        return False
    with _LOCK:
        pairs = load_rejected(world_dir)
        updated = (pairs | set(add)) - set(remove)
        if updated == pairs:
            return False
        try:
            _write(world_dir, updated)
        except OSError as exc:
            logger.warning(
                "relations: cannot persist rejections for %s: %s", world_dir, exc
            )
            return False
    return True


def _write(world_dir: Path, pairs: set[Pair]) -> None:
    path = store_path(world_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": SCHEMA_VERSION,
        "rejected": [list(pair) for pair in sorted(pairs)],
    }
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
