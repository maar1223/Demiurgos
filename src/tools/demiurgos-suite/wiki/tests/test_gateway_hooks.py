# -*- coding: utf-8 -*-
"""hermes-gateway-hooks (WU 0.3) — veto + cache invalidation + registration.

``hermes_gateway_hooks`` is the pure, non-throwing hook logic behind the
Demiurgos gateway plugin (design Decision 2, spec ``hermes-gateway-hooks``):

- ``skill_manage_veto`` is a ``pre_tool_call`` filter: it blocks the native
  ``skill_manage`` tool (fail-closed) with a non-empty message and allows
  every read/unrelated tool (``None``), never raising.
- ``clear_skills_system_prompt_cache_safe`` invalidates Hermes' in-process
  skills system-prompt cache every turn, degrading to ``False`` (no-op) when
  the hook point is absent or raises (version fallback ``agent.prompt_builder``
  then ``prompt_builder``).

The registration half scans the plugin source: ``register()`` must register
``pre_tool_call`` and an UNCONDITIONAL ``pre_llm_call`` cache invalidation
outside the ``if _CAPTURE_MODE == "ai":`` block, while ``capture_guidance_hook``
and ``pre_gateway_dispatch`` stay unchanged.

Covered scenarios (spec ``hermes-gateway-hooks``):
- pre_tool_call vetoes skill_manage (both scenarios).
- pre_tool_call allows read and unrelated tools (all three scenarios).
- pre_llm_call cache invalidation is registered unconditionally (both).
- Cache invalidation degrades safely (all three scenarios).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_gateway_hooks import (
    SKILL_MANAGE_BLOCK_MESSAGE,
    clear_skills_system_prompt_cache_safe,
    skill_manage_veto,
)

_REPO_ROOT = Path(__file__).resolve().parents[1].parents[3]
_PLUGIN = (
    _REPO_ROOT
    / ".hermes"
    / "plugins"
    / "demiurgos-idea-capture"
    / "__init__.py"
)

# register() body sits at 4 spaces; the ai-mode branch content sits at 8.
_REGISTER_BODY_INDENT = "    "
_AI_BLOCK_INDENT = "        "


# -- Veto half (spec: pre_tool_call vetoes skill_manage) ----------------------


def test_veto_blocks_skill_manage_with_message():
    """Spec 'skill_manage is blocked with a message': the veto returns a block
    directive whose message is a non-empty string."""
    result = skill_manage_veto("skill_manage")
    assert isinstance(result, dict)
    assert result["action"] == "block"
    message = result.get("message")
    assert isinstance(message, str) and message


def test_veto_block_message_constant_is_non_empty():
    """The module-level message is a non-empty string: Hermes ignores a block
    directive without a message (plugins.py:1806-1810), so emptiness here
    would silently re-enable the tool."""
    assert isinstance(SKILL_MANAGE_BLOCK_MESSAGE, str)
    assert SKILL_MANAGE_BLOCK_MESSAGE


def test_veto_allows_skills_list():
    """Spec 'skills_list is allowed': a read-only skills tool returns None."""
    assert skill_manage_veto("skills_list") is None


def test_veto_allows_skill_view():
    """Spec 'skill_view is allowed': a read-only skills tool returns None."""
    assert skill_manage_veto("skill_view") is None


@pytest.mark.parametrize(
    "tool_name",
    ["capture_idea", "update_idea", "read", "bash", "terminal", "graph_search"],
)
def test_veto_allows_unrelated_tools(tool_name):
    """Spec 'Unrelated tool is allowed': every tool other than skill_manage
    returns None."""
    assert skill_manage_veto(tool_name) is None


@pytest.mark.parametrize(
    "tool_name",
    ["skill_manage", "skills_list", "skill_view", "capture_idea", "", None],
)
def test_veto_never_raises(tool_name):
    """Spec 'Veto callback never raises': any tool name yields a directive or
    None, never an exception."""
    result = skill_manage_veto(tool_name)  # must not raise
    assert result is None or result.get("action") == "block"


# -- Cache half (spec: Cache invalidation degrades safely) ---------------------


def _fake_module(clearer=None):
    return SimpleNamespace(clear_skills_system_prompt_cache=clearer)


def test_cache_safe_returns_false_when_modules_absent():
    """Spec 'Hook point absent degrades to no-op': with neither Hermes module
    importable the hook reports False and does not raise."""
    assert clear_skills_system_prompt_cache_safe() is False


def test_cache_safe_returns_true_with_agent_prompt_builder_fake(monkeypatch):
    """Spec 'Hook point present and healthy': a fake sys.modules entry for
    ``agent.prompt_builder`` exposing the clearer yields True and the clearer
    is called."""
    calls = []

    def clearer():
        calls.append(True)

    monkeypatch.setitem(sys.modules, "agent.prompt_builder", _fake_module(clearer))
    assert clear_skills_system_prompt_cache_safe() is True
    assert calls == [True]


def test_cache_safe_version_fallback_to_plain_prompt_builder(monkeypatch):
    """Version fallback: when only ``prompt_builder`` (the second candidate)
    exists, the hook still clears and reports True."""
    calls = []

    def clearer():
        calls.append(True)

    monkeypatch.setitem(sys.modules, "prompt_builder", _fake_module(clearer))
    assert clear_skills_system_prompt_cache_safe() is True
    assert calls == [True]


def test_cache_safe_returns_false_when_clearer_raises(monkeypatch):
    """Spec 'Clearing function raising is contained': an exception inside the
    clearer is caught and reported as False, never propagated."""
    def clearer():
        raise RuntimeError("boom")

    monkeypatch.setitem(sys.modules, "agent.prompt_builder", _fake_module(clearer))
    assert clear_skills_system_prompt_cache_safe() is False


def test_cache_safe_falls_through_when_module_lacks_clearer(monkeypatch):
    """A module present without the clearer is skipped; with no second
    candidate the hook degrades to False without raising."""
    monkeypatch.setitem(sys.modules, "agent.prompt_builder", _fake_module(clearer=None))
    assert clear_skills_system_prompt_cache_safe() is False


def test_cache_safe_first_candidate_wins_over_second(monkeypatch):
    """The ``agent.prompt_builder`` candidate is tried first: its clearer runs
    and the second candidate is never consulted."""
    calls = []

    def first():
        calls.append("first")

    def second():
        calls.append("second")

    monkeypatch.setitem(sys.modules, "agent.prompt_builder", _fake_module(first))
    monkeypatch.setitem(sys.modules, "prompt_builder", _fake_module(second))
    assert clear_skills_system_prompt_cache_safe() is True
    assert calls == ["first"]


# -- Registration text-scan (spec: pre_llm_call registered unconditionally) ---


def _plugin_lines() -> list[str]:
    assert _PLUGIN.is_file(), f"plugin not found: {_PLUGIN}"
    return _PLUGIN.read_text(encoding="utf-8").splitlines()


def _single_line(lines: list[str], marker: str) -> str:
    hits = [line for line in lines if marker in line]
    assert len(hits) == 1, f"expected exactly one line with {marker!r}, got {len(hits)}"
    return hits[0]


def test_plugin_registers_pre_tool_call_veto():
    """The plugin registers the veto callback for ``pre_tool_call``."""
    lines = _plugin_lines()
    _single_line(lines, 'ctx.register_hook("pre_tool_call", _veto_skill_manage_hook)')


def test_plugin_registers_pre_llm_call_invalidation_unconditionally():
    """Spec 'Registration is not gated on capture mode': the cache-invalidation
    ``pre_llm_call`` registration sits at register()-body indentation (4
    spaces), OUTSIDE the ``if _CAPTURE_MODE == "ai":`` block (8 spaces)."""
    lines = _plugin_lines()
    line = _single_line(
        lines, 'ctx.register_hook("pre_llm_call", _invalidate_skills_cache_hook)'
    )
    assert line.startswith(
        _REGISTER_BODY_INDENT + "ctx.register_hook("
    ), f"invalidation registration must be outside the ai-mode block: {line!r}"


def test_plugin_keeps_guidance_hook_inside_ai_block():
    """The pre-existing ai-mode guidance registration is untouched: still
    present and still indented inside the capture-mode branch."""
    lines = _plugin_lines()
    line = _single_line(lines, 'ctx.register_hook("pre_llm_call", capture_guidance_hook)')
    assert line.startswith(_AI_BLOCK_INDENT + "ctx.register_hook(")


def test_plugin_keeps_pre_gateway_dispatch_intake():
    """The pre-existing intake hook registration is untouched."""
    lines = _plugin_lines()
    _single_line(lines, 'ctx.register_hook("pre_gateway_dispatch", capture_intake_hook)')


def test_plugin_defines_thin_wrappers():
    """The two thin wrappers exist as module-level functions."""
    lines = _plugin_lines()
    _single_line(lines, "def _veto_skill_manage_hook(")
    _single_line(lines, "def _invalidate_skills_cache_hook(")