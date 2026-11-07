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
    "- One focused question per turn.",
    "- Before asking, synthesize in 1-3 lines what you already understood.",
    "- When useful, offer your own reading or proposal, explicitly labeled as a proposal.",
    "- Options are a last resort: at most 3, only when the author is stuck.",
    "- Never ask for information the system can retrieve from the active world.",
    "- Distinguish fact, proposal, hypothesis and unknown; never present invented details as canon.",
    "- Stay within the methodology scope.",
)

_METHOD_HEADER = "**Method (behavioral contract)**:"
# A source excerpt must never leak operational provenance into an injected
# prompt. Whole lines with these prefixes are dropped before truncation.
_FORBIDDEN_EXCERPT_PREFIXES = (
    "digest:", "path:", "revision:", "authorization:", "target:",
    "acceptance:", "accepted_canon:", "reference:",
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
    method: str = "",
) -> str:
    """Render the fixed structured projection with the given variable fields.

    ``method`` is the bounded behavioral excerpt from the methodology source.
    The phases are presented as a guide, never as a rigid script: the previous
    ``Current Phase``/``Next Action`` pair always named the first phase and made
    long sessions believe they were still starting.
    """
    version_suffix = f" (v{version})" if version else ""
    identity = (
        f"**Identity**: {description}" if description
        else "**Identity**: (no description)"
    )
    phases_line = " → ".join(phases) if phases else "(none)"
    lines = [
        f"## Methodology: {name}{version_suffix}",
        identity,
    ]
    if method:
        lines.extend(("", _METHOD_HEADER, method))
    lines.extend((
        "",
        f"**Phases (guide, not a rigid sequence)**: {phases_line}",
        "",
        "**Conversation contract**:",
        *_RULES_LINES,
    ))
    return "\n".join(lines) + "\n"


def _method_excerpt(source: str, max_chars: int) -> str:
    """Return a deterministic, bounded behavioral excerpt from the source.

    Frontmatter and the leading H1 are skipped; the excerpt starts at the first
    H2 (``## Propósito``, ``## Principio 40/60``, ...) so the assistant receives
    the authored behavior instead of only the phase names. The cut is
    char-bounded and always ends on the ellipsis marker when truncated.
    """
    if not source or max_chars <= 0:
        return ""
    text = source.strip()
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4 :].lstrip()
    if text.startswith("# "):
        newline = text.find("\n")
        text = text[newline + 1 :].lstrip() if newline != -1 else ""
    elif text.startswith("## "):
        pass
    else:
        heading = text.find("\n## ")
        if heading != -1:
            text = text[heading + 1 :].lstrip()
    safe_lines = [
        line for line in text.splitlines()
        if not line.strip().casefold().startswith(_FORBIDDEN_EXCERPT_PREFIXES)
    ]
    return _truncate_chars("\n".join(safe_lines), max_chars).strip()


def project_contract_markdown(
    compiled: ProjectionSource | Any,
    *,
    max_tokens: int = 1000,
) -> str:
    """Project a compiled methodology into structured Markdown under budget.

    ``compiled`` may be a ``CompiledMethodology``, a ``PublishedVersion``, or a
    ``CompileResult`` (its ``.compiled`` contract is used). Returns ``""`` for
    ``None`` and for failed results without a compiled contract.

    The projection carries the authored behavior (a bounded source excerpt)
    plus the platform conversation contract, so an injected skill keeps its
    method instead of only its phase names. When the estimated token count
    exceeds ``max_tokens``, the variable description is shortened first, then
    the method excerpt; if the fixed sections alone exceed the budget, the
    whole document is hard-truncated.
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
    source = getattr(contract, "source", "") or ""

    # Reserve room for the method excerpt first: it carries the authored
    # behavior (40/60, synthesis, one-question technique) that the phases alone
    # cannot convey. The fixed skeleton is rendered without the method to size
    # the remaining budget deterministically.
    fixed = _render(name, version, description, phases)
    fixed_chars = len(fixed)
    excerpt_budget = 0
    if fixed_chars < max_chars:
        excerpt_budget = max(0, max_chars - fixed_chars - len(_METHOD_HEADER) - 2)
    method = _method_excerpt(source, excerpt_budget)

    full = _render(name, version, description, phases, method)
    if _estimate_tokens(full) <= budget:
        return full

    # Over budget: shrink the description, then the method excerpt, keeping the
    # fixed conversation contract untouched.
    for _ in range(4):
        fixed = _render(name, version, "", phases)
        fixed_chars = len(fixed)
        if fixed_chars >= max_chars:
            return _truncate_chars(full, max_chars)
        available = max(
            0, max_chars - fixed_chars - len(_METHOD_HEADER) - 2
        )
        description = _truncate_chars(description, available // 2)
        method = _method_excerpt(source, available - len(description))
        full = _render(name, version, description, phases, method)
        if _estimate_tokens(full) <= budget:
            return full
    return _truncate_chars(full, max_chars)
