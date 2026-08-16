"""Compatibility package: ``sync-lore`` is an alias for ``sync_lore``.

The tool was renamed ``sync-lore`` -> ``sync_lore`` for Python module
compatibility (Python rejects hyphens in ``import`` names).  Existing tests
and external references still import via ``importlib.import_module("sync-lore.…")``,
so this package maps every ``sync-lore.<submodule>`` name onto the real
``sync_lore`` package.  No duplicate implementation lives here.
"""

from __future__ import annotations

import importlib
import sys

import sync_lore  # noqa: E402  (real package is co-located)

_SUBMODULES = (
    "cli",
    "image_indexer",
    "index_builder",
    "lore_indexer",
    "persistence",
    "publisher",
    "schemas",
    "utils.chunker",
    "utils.converter",
    "utils.parallel",
    "utils.world",
    "providers.base",
)

for _name in _SUBMODULES:
    # Best-effort: a pre-existing broken submodule (e.g. a mangled encoding in
    # providers/llm.py) must not prevent the other aliases from loading.
    try:
        sys.modules.setdefault(f"sync-lore.{_name}", importlib.import_module(f"sync_lore.{_name}"))
    except Exception:
        continue

sys.modules.setdefault("sync-lore.utils", importlib.import_module("sync_lore.utils"))
sys.modules.setdefault("sync-lore.providers", importlib.import_module("sync_lore.providers"))
sys.modules.setdefault("sync-lore", sync_lore)
