# -*- coding: utf-8 -*-
"""Platform-owned response style for the assistant chat (S1-S3).

The style contract must reach every skill route and must be the LAST
instruction before the author's message: a style rule placed before the routed
skill contract loses to it.
"""

from __future__ import annotations


def _prompt(**kwargs) -> str:
    import api_server

    return api_server._build_ai_ask_prompt(
        "test_mundo",
        api_server.AskRequest(prompt="¿Cómo termina Ganic?"),
        **kwargs,
    )


def test_style_block_is_the_last_instruction_before_the_author_prompt():
    import api_server

    prompt = _prompt(skill_contract="[Skill contract: method body]")
    style_at = prompt.index(api_server._RESPONSE_STYLE_GUIDANCE)
    contract_at = prompt.index("[Skill contract: method body]")
    author_at = prompt.index("¿Cómo termina Ganic?")

    assert contract_at < style_at < author_at


def test_style_block_carries_length_markdown_and_one_question():
    import api_server

    style = api_server._RESPONSE_STYLE_GUIDANCE
    assert "3-6 sentences" in style
    assert "120 words" in style
    assert "exactly ONE question" in style
    assert "GitHub-flavored Markdown" in style
    assert "**bold**" in style


def test_style_block_applies_even_without_a_routed_skill():
    import api_server

    prompt = _prompt()
    assert api_server._RESPONSE_STYLE_GUIDANCE in prompt


def test_old_plain_guidance_is_gone():
    import api_server

    prompt = _prompt()
    assert "Visible response guidance" not in prompt
