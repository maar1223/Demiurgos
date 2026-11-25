# -*- coding: utf-8 -*-
"""World-fact citations for the assistant (assistant-citation S1-S4).

A level-C answer must carry its source: the assistant ends a world-grounded
answer with a `Fuentes:` (es) / `Sources:` (en) line listing the ficha paths it
actually read. The world-agnostic `ideas-global` assistant has no graph and must
never emit that line.

Contract: `odd/tasks/assistant-citation.md`.
"""

from __future__ import annotations


def _prompt(mundo: str = "test_mundo", **kwargs) -> str:
    import api_server

    return api_server._build_ai_ask_prompt(
        mundo,
        api_server.AskRequest(prompt="¿Cómo termina Ganic?"),
        **kwargs,
    )


def test_citation_clause_defines_both_labels_and_the_path_source():
    import api_server

    es = api_server._CITATION_GUIDANCE["es"]
    en = api_server._CITATION_GUIDANCE["en"]
    assert "Fuentes:" in es
    assert "graph_read" in es or "graph_search" in es
    assert "lore/" in es
    assert "Sources:" in en
    assert "graph_read" in en or "graph_search" in en


def test_real_world_prompt_carries_the_citation_clause_for_the_conversation_language():
    import api_server

    language = api_server._resolve_language("conversation")
    prompt = _prompt()
    assert api_server._CITATION_GUIDANCE.get(language), language
    assert api_server._CITATION_GUIDANCE[language] in prompt


def test_citation_clause_is_after_the_style_block_and_before_the_author_prompt():
    import api_server

    language = api_server._resolve_language("conversation")
    clause = api_server._CITATION_GUIDANCE[language]
    prompt = _prompt()
    style_at = prompt.index(api_server._RESPONSE_STYLE_GUIDANCE)
    citation_at = prompt.index(clause)
    author_at = prompt.index("¿Cómo termina Ganic?")
    assert style_at < citation_at < author_at


def test_global_context_never_emits_a_citation_clause():
    import api_server

    prompt = _prompt(mundo=api_server.GLOBAL_ASSISTANT_CONTEXT)
    for clause in api_server._CITATION_GUIDANCE.values():
        assert clause not in prompt
    assert "Fuentes:" not in prompt
    assert "Sources:" not in prompt
