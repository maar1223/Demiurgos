# -*- coding: utf-8 -*-
"""Focused tests for Demiurgos assistant ficha context building.

Covers REQ-5 (Manifest Invisibility, scenario S10): ``_order.json`` must not
be eligible as a Hermes conversation candidate. ``build_fichas_context``
scans ``*.md`` files only and skips any ``_``-prefixed file
(``demiurgos_personality.py:147``), so the manifest is doubly excluded.
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from demiurgos_personality import build_fichas_context  # noqa: E402


def test_fichas_context_excludes_order_manifest(tmp_path) -> None:
    """REQ-5 S10: _order.json is never a ficha context candidate.

    A section with a manifest and a regular ficha surfaces only the ficha:
    the manifest path marker and its JSON content never leak into the
    assistant context.
    """
    mundo = tmp_path / "mundo1"
    (mundo / "lore").mkdir(parents=True)
    (mundo / "lore" / "_order.json").write_text(
        '["alpha.md"]', encoding="utf-8"
    )
    (mundo / "lore" / "intro.md").write_text(
        "# Intro\n\nIntro ficha body\n", encoding="utf-8"
    )

    context = build_fichas_context("mundo1", tmp_path)

    assert "--- lore/intro.md ---" in context
    assert "Intro ficha body" in context
    assert "_order.json" not in context
    assert '["alpha.md"]' not in context


def test_fichas_context_excludes_underscore_prefixed_md(tmp_path) -> None:
    """The ``_``-prefix filter that protects the manifest convention also
    excludes any underscore-prefixed ficha (e.g. ``_draft.md``), so a
    manifest-like file renamed to ``.md`` would still stay invisible.
    """
    mundo = tmp_path / "mundo1"
    (mundo / "lore").mkdir(parents=True)
    (mundo / "lore" / "_draft.md").write_text(
        "HIDDEN_DRAFT_BODY", encoding="utf-8"
    )
    (mundo / "lore" / "visible.md").write_text(
        "VISIBLE_FICHA_BODY", encoding="utf-8"
    )

    context = build_fichas_context("mundo1", tmp_path)

    assert "VISIBLE_FICHA_BODY" in context
    assert "HIDDEN_DRAFT_BODY" not in context