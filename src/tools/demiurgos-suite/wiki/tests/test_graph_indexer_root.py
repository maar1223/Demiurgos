# -*- coding: utf-8 -*-
"""Graph-index data root (WU-2, REQ-DR-3 / SC-DR-3.2).

``EntityGraphIndex()`` with no explicit path used to derive ``mundos/`` from
``Path(__file__).resolve().parents[5]`` — one level ABOVE the repository, so the
auto-detected corpus was always a missing directory and the index silently came
up empty. It now resolves through ``data_root.resolve_data_root()``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
if str(_SUITE) not in sys.path:
    sys.path.insert(0, str(_SUITE))

from wiki.graph_indexer import EntityGraphIndex  # noqa: E402


def _data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data-root"
    (root / "mundos" / "ekkor").mkdir(parents=True)
    return root


def test_auto_detect_resolves_mundos_from_the_data_root(monkeypatch, tmp_path) -> None:
    """``mundos_path=None`` + injected env → ``<data root>/mundos``."""
    root = _data_root(tmp_path)
    monkeypatch.setenv("DEMIURGOS_DATA_ROOT", str(root))
    assert EntityGraphIndex()._mundos_path == root / "mundos"


def test_auto_detect_never_escapes_above_the_data_root(monkeypatch, tmp_path) -> None:
    """Regression for the off-by-one: the old ``parents[5]`` pointed here."""
    root = _data_root(tmp_path)
    monkeypatch.setenv("DEMIURGOS_DATA_ROOT", str(root))
    detected = EntityGraphIndex()._mundos_path
    assert detected != root.parent / "mundos"
    assert root in detected.parents


def test_explicit_mundos_path_is_never_rewritten(monkeypatch, tmp_path) -> None:
    """An explicit path wins: the resolver is not consulted for it."""
    root = _data_root(tmp_path)
    monkeypatch.setenv("DEMIURGOS_DATA_ROOT", str(root))
    explicit = tmp_path / "elsewhere" / "mundos"
    assert EntityGraphIndex(explicit)._mundos_path == explicit
