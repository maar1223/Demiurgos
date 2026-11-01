"""World-local memory of relations the Author explicitly wanted.

P4 removes declared relations no text backs; P3 can propose a relation whose
target the text does not name. Without this memory, accepting a proposal and
later running the sync would delete it. Recording the pair here makes the
Author's explicit choice win over the literal check.

Stored at ``<world>/.relations/curated.json``: atomic, sorted, deduped and
fail-open (an unreadable store means "nothing curated").
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
STORE_NAME = "curated.json"
SCHEMA_VERSION = 1

_LOCK = threading.Lock()

Pair = tuple[str, str]


def store_path(world_dir: Path) -> Path:
    return Path(world_dir) / STORE_DIR / STORE_NAME


def load_curated(world_dir: Path) -> set[Pair]:
    path = store_path(world_dir)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return set()
    except OSError as exc:
        logger.warning("relations: cannot read curated pairs at %s: %s", path, exc)
        return set()
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("relations: corrupt curated store at %s; ignoring", path)
        return set()
    entries = data.get("curated") if isinstance(data, dict) else None
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


def pin(world_dir: Path, source_key: str, target_id: str) -> bool:
    """Remember that the Author explicitly wants this pair."""
    return _mutate(world_dir, add={(source_key, target_id)})


def unpin(world_dir: Path, source_key: str, target_id: str) -> bool:
    """Forget the curation: the Author removed the relation."""
    return _mutate(world_dir, remove={(source_key, target_id)})


def _mutate(
    world_dir: Path,
    *,
    add: Iterable[Pair] = (),
    remove: Iterable[Pair] = (),
) -> bool:
    if not world_dir:
        return False
    with _LOCK:
        pairs = load_curated(world_dir)
        updated = (pairs | set(add)) - set(remove)
        if updated == pairs:
            return False
        try:
            _write(world_dir, updated)
        except OSError as exc:
            logger.warning("relations: cannot persist curation for %s: %s", world_dir, exc)
            return False
    return True


def _write(world_dir: Path, pairs: set[Pair]) -> None:
    path = store_path(world_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": SCHEMA_VERSION,
        "curated": [list(pair) for pair in sorted(pairs)],
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
