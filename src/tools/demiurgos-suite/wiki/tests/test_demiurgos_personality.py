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

from demiurgos_personality import (  # noqa: E402
    build_fichas_context,
    build_identity_prompt,
    graph_context_with_sources,
)


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


# ---------------------------------------------------------------------------
# PER-REQ-1 / PER-REQ-2: neutral-Spanish identity prompt and locale selection
# ---------------------------------------------------------------------------

def test_identity_prompt_spanish_is_neutral_without_voseo() -> None:
    prompt = build_identity_prompt("Aurelia", language="es")
    for form in ("NO sos", "Respondé", "Usá", "informalo", "ofrecete",
                 "indicá", "nombrá", "buscá", "usá", "afirmes", "chequear"):
        assert form not in prompt, f"voseo form {form!r} survived de-voseo"


def test_identity_prompt_english_requests_english_output() -> None:
    prompt = build_identity_prompt("Aurelia", language="en")
    assert "Answer in English" in prompt
    assert "You are not Gentle AI" in prompt


def test_identity_prompt_preserves_identity_and_multi_world_search() -> None:
    prompt = build_identity_prompt("Aurelia", language="es")
    assert "Asistente Demiurgos" in prompt
    assert "Transparencia de mundo" in prompt
    assert "otros mundos" in prompt
    assert "'Aurelia'" in prompt

class _FakeHit:
    def __init__(self, path: str, name: str, score: float = 10.0) -> None:
        self.path = path
        self.name = name
        self.score = score


class _FakeDetail:
    def __init__(self, title: str, type_: str, content: str) -> None:
        self.title = title
        self.type = type_
        self.content = content


class _FakeGraph:
    """Minimal EntityGraphIndex surface used by the injection."""

    def __init__(self, hits, details) -> None:
        self._hits = hits
        self._details = details

    def search(self, _query):
        return list(self._hits)

    def get_entity(self, path):
        return self._details.get(path)


def test_context_injection_requires_the_query_to_name_an_entity() -> None:
    """A vague question must not inject fichas (S10).

    The measured failure: "estuvimos creando la ficha de Hesia..." scored five
    unrelated fichas above a legitimate hit, so the prompt carried noise the
    model had to discard.
    """
    hit = _FakeHit("lore/dvex.md", "Dvex del Stal 6")
    detail = _FakeDetail("Dvex del Stal 6", "criatura", "Contenido.")
    graph = _FakeGraph([hit], {"lore/dvex.md": detail})

    block, sources = graph_context_with_sources(
        "estuvimos creando la ficha de Hesia pero no la terminamos", graph,
    )

    assert block == ""
    assert sources == []


def test_context_injection_includes_the_entity_the_query_names() -> None:
    hit = _FakeHit("personajes/ganic.md", "Ganic")
    detail = _FakeDetail("Ganic", "personaje", "Ganic llego de fuera.")
    graph = _FakeGraph([hit], {"personajes/ganic.md": detail})

    block, sources = graph_context_with_sources("\u00bfQui\u00e9n es Ganic?", graph)

    assert "Ganic llego de fuera." in block
    assert sources == ["personajes/ganic.md"]
