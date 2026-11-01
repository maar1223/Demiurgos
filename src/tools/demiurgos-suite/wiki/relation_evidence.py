"""World-local memory of body-verified relation evidence (S5).

The deterministic matcher can only find what it knows how to match. A model
claim that quoted the source body is real evidence the matcher may have missed,
but it cannot be re-derived from the text alone. This store keeps the quote so
the sync can honour it.

The store is self-invalidating: the sync re-checks the quote against the
CURRENT body on every run. When the text changes and the quote disappears, the
relation is no longer corroborated and the sync may remove it. Nothing here is
an owner decision — that is ``curated.json``; this is machine-verified text.

Stored at ``<world>/.relations/evidenced.json``: atomic, sorted, deduped by the
unordered pair, fail-open (an unreadable store means "no verified evidence").
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from relation_proposing import pair_key, quote_in_body

logger = logging.getLogger(__name__)

STORE_DIR = ".relations"
STORE_NAME = "evidenced.json"
SCHEMA_VERSION = 1

_LOCK = threading.Lock()


@dataclass(frozen=True)
class Evidence:
    """One verified quote backing an unordered pair, stored on one side."""

    pair: tuple[str, str]
    side: str
    quote: str


def store_path(world_dir: Path) -> Path:
    return Path(world_dir) / STORE_DIR / STORE_NAME


def load_evidence(world_dir: Path) -> dict[tuple[str, str], Evidence]:
    path = store_path(world_dir)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        logger.warning("relations: cannot read evidenced pairs at %s: %s", path, exc)
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("relations: corrupt evidenced store at %s; ignoring", path)
        return {}
    entries = data.get("evidenced") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return {}
    stored: dict[tuple[str, str], Evidence] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        pair = entry.get("pair")
        side = entry.get("side")
        quote = entry.get("quote")
        if (
            isinstance(pair, (list, tuple))
            and len(pair) == 2
            and all(isinstance(value, str) and value for value in pair)
            and isinstance(side, str)
            and side
            and isinstance(quote, str)
            and quote.strip()
        ):
            key = pair_key(pair[0], pair[1])
            stored[key] = Evidence(pair=key, side=side, quote=quote.strip())
    return stored


def record(world_dir: Path, *, left: str, right: str, side: str, quote: str) -> bool:
    """Upsert one verified pair. Returns True when the store changed."""
    if not left or not right or left == right or side not in (left, right):
        return False
    if not (quote or "").strip():
        return False
    key = pair_key(left, right)
    evidence = Evidence(pair=key, side=side, quote=quote.strip())
    with _LOCK:
        stored = load_evidence(world_dir)
        if stored.get(key) == evidence:
            return False
        stored[key] = evidence
        _write(world_dir, stored)
        return True


def forget(world_dir: Path, left: str, right: str) -> bool:
    """Drop a pair's evidence. Returns True when it existed."""
    key = pair_key(left, right)
    with _LOCK:
        stored = load_evidence(world_dir)
        if key not in stored:
            return False
        del stored[key]
        _write(world_dir, stored)
        return True


def verified_ids(
    world_dir: Path,
    *,
    source_key: str,
    body: str,
    evidence: dict[tuple[str, str], Evidence] | None = None,
) -> set[str]:
    """Targets this ficha may still declare because its own body quotes them.

    Only pairs stored on THIS side count: the frontmatter entry lives on the
    stored side, so only that body can corroborate it.
    """
    stored = load_evidence(world_dir) if evidence is None else evidence
    found: set[str] = set()
    for item in stored.values():
        if item.side != source_key:
            continue
        other = item.pair[0] if item.pair[1] == source_key else item.pair[1]
        if other and quote_in_body(body, item.quote):
            found.add(other)
    return found


def _write(world_dir: Path, stored: dict[tuple[str, str], Evidence]) -> None:
    path = store_path(world_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": SCHEMA_VERSION,
        "evidenced": [
            {"pair": list(item.pair), "side": item.side, "quote": item.quote}
            for item in sorted(stored.values(), key=lambda item: (item.pair, item.side))
        ],
    }
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def record_many(world_dir: Path, items: Iterable[tuple[str, str, str, str]]) -> int:
    """Record several ``(left, right, side, quote)`` tuples in one write."""
    with _LOCK:
        stored = load_evidence(world_dir)
        before = len(stored)
        for left, right, side, quote in items:
            if not left or not right or left == right or side not in (left, right):
                continue
            if not (quote or "").strip():
                continue
            key = pair_key(left, right)
            stored[key] = Evidence(pair=key, side=side, quote=quote.strip())
        if len(stored) == before:
            return 0
        _write(world_dir, stored)
        return len(stored) - before
