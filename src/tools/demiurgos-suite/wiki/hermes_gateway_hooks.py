# -*- coding: utf-8 -*-
"""Pure, non-throwing gateway hook logic for the Demiurgos-Hermes skills cut.

Etapa 0 (additive) delivers two hooks through the already-loaded in-process
plugin (``.hermes/plugins/demiurgos-idea-capture/__init__.py``, design
Decision 2):

- ``skill_manage_veto`` — a ``pre_tool_call`` filter. Native skills are
  read-only for the Demiurgos product, so ``skill_manage`` is blocked with a
  non-empty message (fail-closed at the hook layer: Hermes bounds
  ``pre_tool_call`` and treats a timed-out/still-running callback as a block,
  and our callback must never rely on that). Every read or unrelated tool
  returns ``None`` (allow).
- ``clear_skills_system_prompt_cache_safe`` — a ``pre_llm_call`` hook that
  invalidates Hermes' in-process skills system-prompt cache on every turn so
  external writes to ``skills.external_dirs`` are picked up. It returns
  ``None`` from the wrapper, so it never collides with guidance-returning
  hooks. In Etapa 0 the external folder is empty, so the per-turn call is
  effectively free; the materializer (Etapa 1) owns choosing a finer trigger
  (e.g. an mtime guard) when it starts writing.

Both functions are pure and NEVER raise: they live outside the Hermes process
so they are directly unit-testable, and their wrapper registrations are thin.

Fail-open fallback (registration miss): a ``pre_tool_call`` veto can only fire
through a REGISTERED callback. If the plugin is not loaded (project plugins
disabled), Hermes cannot veto ``skill_manage`` through this hook — that gap is
fail-open by design. The documented mitigation is the shell-hook fallback:
write a ``hooks.pre_tool_call`` entry in the dedicated product profile's
``config.yaml`` that executes a small script calling
``skill_manage_veto("$TOOL_NAME")`` and prints the block directive (shell
hooks are the only registration surface with a per-tool matcher). Boot
observability: registration status is observable through the plugin manager's
registered hook events and the gateway plugin-load logs (the ``hermes hooks
list`` CLI lists config-owned shell hooks only, not plugin callbacks); the
integration probe for this change asserts the two hooks are live before the
skills cut (Etapa 3) is allowed to enable the toolset.

Cache invalidation degrades safely: when the installed Hermes build lacks
``clear_skills_system_prompt_cache`` (or it raises), the hook reports ``False``
and the turn proceeds normally. The version fallback tries ``agent.prompt_builder``
first, then ``prompt_builder``, matching the import shape of the installed
build (``agent/prompt_builder.py`` in Hermes v0.21).
"""

from __future__ import annotations

SKILL_MANAGE_BLOCK_MESSAGE = (
    "skill_manage is disabled in the Demiurgos product profile: native skills are read-only."
)


def skill_manage_veto(tool_name: str) -> dict | None:
    """Block the native ``skill_manage`` tool; allow everything else.

    Returns ``{"action": "block", "message": <non-empty>}`` for ``skill_manage``
    and ``None`` for every other tool name. Hermes requires a non-empty
    ``message`` for a block directive (plugins.py ``_get_pre_tool_call_directive_details``),
    so the message constant is never empty. Never raises.
    """
    if tool_name != "skill_manage":
        return None
    return {"action": "block", "message": SKILL_MANAGE_BLOCK_MESSAGE}


def clear_skills_system_prompt_cache_safe() -> bool:
    """Clear Hermes' in-process skills cache; never raise.

    Version fallback: try ``agent.prompt_builder``, then ``prompt_builder``.
    Returns ``False`` (degrade to no-op) when the hook point is unavailable or
    when the available clearer raises — the LLM turn proceeds normally either
    way.
    """
    import importlib

    for module_name in ("agent.prompt_builder", "prompt_builder"):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        clearer = getattr(module, "clear_skills_system_prompt_cache", None)
        if callable(clearer):
            try:
                clearer()
                return True
            except Exception:
                return False
    return False