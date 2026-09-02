# -*- coding: utf-8 -*-
"""Per-section import-order manifest helpers (``_order.json``).

Each section (``mundos/{mundo}/{section}/``) may carry a hidden manifest
``_order.json`` — a flat JSON array of section-relative, POSIX-separated
paths in import order (e.g. ``["intro.md", "chapter-1/foundation.md"]``).
The tree endpoint reads it to preserve the source document's narrative
order instead of sorting alphabetically; the import pipeline appends and
replaces entries as fichas are materialized.

All writes are atomic (temp file + ``os.replace``) so concurrent imports
cannot corrupt the manifest. The ``_``-prefix keeps the manifest and its
temp file invisible to the tree filter, Hermes candidate discovery, and
the graph indexer — no extra filtering is needed.

This module is strictly filesystem work and stays importable standalone
(tests never pull ``api_server``).
"""

import json
import os
from pathlib import Path

_MANIFEST_NAME = "_order.json"
_TMP_NAME = "_order.json.tmp"


def read_order(section_dir: Path) -> list[str]:
    """Read the section manifest. Returns ``[]`` if missing or malformed."""
    manifest = section_dir / _MANIFEST_NAME
    if not manifest.is_file():
        return []
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [p for p in data if isinstance(p, str)]


def write_order(section_dir: Path, paths: list[str]) -> None:
    """Atomically write ``paths`` to ``_order.json`` (creates the dir if needed)."""
    section_dir.mkdir(parents=True, exist_ok=True)
    tmp = section_dir / _TMP_NAME
    try:
        tmp.write_text(
            json.dumps(paths, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, section_dir / _MANIFEST_NAME)
    finally:
        if tmp.exists():
            tmp.unlink()


def append_order(section_dir: Path, new_paths: list[str]) -> None:
    """Append ``new_paths`` to the manifest, skipping paths already listed."""
    existing = read_order(section_dir)
    seen = set(existing)
    merged = list(existing)
    for path in new_paths:
        if path not in seen:
            merged.append(path)
            seen.add(path)
    write_order(section_dir, merged)


def remove_from_order(section_dir: Path, path: str) -> None:
    """Remove ``path`` from the manifest. No-op when absent (or no manifest)."""
    existing = read_order(section_dir)
    if path not in existing:
        return
    write_order(section_dir, [p for p in existing if p != path])


def replace_prefix_order(section_dir: Path, prefix: str, new_paths: list[str]) -> None:
    """Replace the subtree under ``prefix`` with ``new_paths``, atomically.

    Entries whose path equals ``prefix`` or starts with ``prefix + "/"`` are
    removed; every other entry keeps its relative position, then ``new_paths``
    are appended. A prefix without a trailing slash behaves as if it had one,
    so ``"reptiles"`` matches ``reptiles/snake.md`` but never ``reptiles.md``
    or ``reptiles2/x.md``. An empty prefix degenerates to full replacement.
    """
    existing = read_order(section_dir)
    if prefix:
        marker = prefix if prefix.endswith("/") else prefix + "/"
        filtered = [p for p in existing if p != prefix and not p.startswith(marker)]
    else:
        filtered = []
    write_order(section_dir, filtered + list(new_paths))