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
- ``clear_skills_system_prompt_cache_safe`` — the ``pre_llm_call``
  cache-invalidation hook. Etapa 1 (T-FU-02) turns it into a **revision-marker
  guard**: the plugin passes the materialization revision marker path and the
  hook clears Hermes' in-process skills system-prompt cache ONLY when that
  marker changed since the last turn (an unchanged turn is a no-op). Called
  without a marker path it keeps the Etapa 0 unconditional-clear behavior, so
  the etape is purely additive. The wrapper returns ``None``, so it never
  collides with guidance-returning hooks.

``revision_marker_signature`` is the non-throwing marker comparison used by the
guard: ``(st_mtime_ns, st_size, sha256(content))``, or ``None`` when the marker
is missing/unreadable.

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
build (``agent/prompt_builder.py`` in Hermes v0.21). When the revision marker is
absent or unreadable the guard treats the revision as changed and attempts a
clear (never raising) — degrade toward coherence rather than a stale prompt.

``skill_manage_veto`` is UNCHANGED by Etapa 1.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

#: Last-seen sentinel for the in-process marker guard. A brand-new process holds
#: ``_UNSEEN``, so the first real signature — or an absent/unreadable marker —
#: never compares equal and always triggers the first clear.
_UNSEEN = object()

#: In-process last-seen marker signature (``_UNSEEN`` until the first guard run).
_LAST_SEEN_MARKER: object = _UNSEEN

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


def revision_marker_signature(marker_path) -> tuple[int, int, str] | None:
    """Non-throwing signature of the materialization revision marker.

    Returns ``(st_mtime_ns, st_size, sha256(content))`` for a readable marker,
    or ``None`` when the path is missing, unreadable, or not a regular file.
    Never raises: any failure degrades to ``None`` (treated as "changed" by the
    guard, so the next turn retries rather than serving a stale prompt).
    """
    try:
        path = Path(marker_path)
        stat = path.stat()
        content = path.read_bytes()
    except Exception:  # noqa: BLE001 — comparison must never raise
        return None
    return (stat.st_mtime_ns, stat.st_size, hashlib.sha256(content).hexdigest())


def _clear_skills_system_prompt_cache() -> bool:
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


def clear_skills_system_prompt_cache_safe(*, marker_path=None) -> bool:
    """Clear Hermes' skills cache, guarded by the revision marker; never raise.

    - ``marker_path is None`` → Etapa 0 unconditional clear (no marker guard),
      preserving the pre-Etapa-1 contract.
    - Otherwise the marker signature is compared against the in-process
      last-seen value:

      * unchanged (and readable) → no-op, return ``True`` (no clear call);
      * changed → attempt a clear, record the new signature, return the clearer
        result;
      * absent/unreadable (``None``) → treat as changed, attempt a clear, record
        ``None`` so the next turn retries (degrade toward coherence).

    The comparison itself never raises and the returned value is always a bool.
    """
    global _LAST_SEEN_MARKER

    if marker_path is None:
        return _clear_skills_system_prompt_cache()

    signature = revision_marker_signature(marker_path)
    if signature is not None and signature == _LAST_SEEN_MARKER:
        return True  # unchanged marker: no-op, no clear call

    result = _clear_skills_system_prompt_cache()
    _LAST_SEEN_MARKER = signature
    return result