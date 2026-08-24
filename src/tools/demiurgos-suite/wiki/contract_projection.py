"""Project a compiled methodology contract into bounded structured Markdown.

The assistant prompt carries a hard token budget (~1000 tokens). Raw
methodology sources can reach 200K chars, so the projection extracts only the
stable, LLM-friendly sections — identity, phases, current phase, rules and
next action — and truncates the variable source-derived content (the
description) when the estimated size exceeds ``max_tokens``.

The input accepts a ``CompiledMethodology`` (the compiler's runtime contract),
a ``PublishedVersion`` (the library's immutable published record — a strict
superset of the compiled contract) or a ``CompileResult`` (unwrapped to its
``.compiled`` contract). The projection is a pure function: it reads the
contract and returns a string, never touching the filesystem or runtime.
"""

from __future__ import annotations

from typing import Any, Union

from methodology_compiler import CompiledMethodology
from methodology_library import PublishedVersion

_CHARS_PER_TOKEN = 4
"""Rough chars-per-token heuristic used for the token budget estimate."""

_ELLIPSIS = "…"

_DEFAULT_NAME = "Untitled methodology"

_RULES_LINES = (
    "- Follow phases in order",
    "- One question per turn",
    "- Stay within methodology scope",
)

ProjectionSource = Union[CompiledMethodology, PublishedVersion]
"""Accepted contract inputs (``CompileResult`` is unwrapped at runtime)."""


def _unwrap(compiled: Any) -> ProjectionSource | None:
    """Resolve the projection input to a compiled contract.

    Accepts a ``CompiledMethodology``, a ``PublishedVersion``, or a
    ``CompileResult`` (which carries ``.compiled``). Returns ``None`` for
    ``None`` inputs and for failed results that hold no compiled contract.
    """
    if compiled is None:
        return None
    if not hasattr(compiled, "skill_id") and hasattr(compiled, "compiled"):
        compiled = compiled.compiled
    return compiled


def _estimate_tokens(text: str) -> int:
    """Rough token estimate using the ~4 chars/token heuristic (ceil)."""
    if not text:
        return 0
    return (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN


def _truncate_chars(text: str, max_chars: int) -> str:
    """Char-bounded truncation that always ends on the ellipsis marker."""
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return _ELLIPSIS
    return text[: max_chars - 1].rstrip() + _ELLIPSIS


def _render(
    name: str, version: str, description: str, phases: tuple[str, ...],
) -> str:
    """Render the fixed structured projection with the given variable fields."""
    version_suffix = f" (v{version})" if version else ""
    identity = (
        f"**Identity**: {description}" if description
        else "**Identity**: (no description)"
    )
    if phases:
        phases_line = " → ".join(phases)
        current_phase = phases[0]
        next_action = f"Begin with {phases[0]} phase."
    else:
        phases_line = "(none)"
        current_phase = "unknown"
        next_action = "Begin the first phase."
    lines = [
        f"## Methodology: {name}{version_suffix}",
        identity,
        f"**Phases**: {phases_line}",
        f"**Current Phase**: {current_phase}",
        "**Rules**:",
        *_RULES_LINES,
        f"**Next Action**: {next_action}",
    ]
    return "\n".join(lines) + "\n"


def project_contract_markdown(
    compiled: ProjectionSource | Any,
    *,
    max_tokens: int = 1000,
) -> str:
    """Project a compiled methodology into structured Markdown under budget.

    ``compiled`` may be a ``CompiledMethodology``, a ``PublishedVersion``, or a
    ``CompileResult`` (its ``.compiled`` contract is used). Returns ``""`` for
    ``None`` and for failed results without a compiled contract.

    When the estimated token count of the full projection exceeds
    ``max_tokens``, the variable description (Identity) is shortened first; if
    the fixed sections alone still exceed the budget, the whole document is
    hard-truncated.
    """
    contract = _unwrap(compiled)
    if contract is None:
        return ""
    name = getattr(contract, "name", "") or _DEFAULT_NAME
    version = getattr(contract, "version", "") or ""
    description = getattr(contract, "description", "") or ""
    phases = tuple(getattr(contract, "phases", ()) or ())
    budget = max(1, max_tokens)
    max_chars = budget * _CHARS_PER_TOKEN

    full = _render(name, version, description, phases)
    if _estimate_tokens(full) <= budget:
        return full

    # Over budget: shrink the source-derived description until the fixed
    # sections plus the shortened description fit the char-equivalent budget.
    fixed = _render(name, version, "", phases)
    fixed_chars = len(fixed)
    if fixed_chars >= max_chars:
        return _truncate_chars(full, max_chars)
    shortened = _truncate_chars(description, max_chars - fixed_chars)
    return _render(name, version, shortened, phases)
