# -*- coding: utf-8 -*-
"""Demiurgos assistant personality and context injection.

Restores the "Asistente Demiurgos" identity that was lost when
hermes_engine.py was not merged to master. Provides:

1. A system-level identity prompt for the assistant.
2. Entity graph context injection (BM25 search + entity content).
3. World ficha context building from _context/ or lore/personajes.

The semantic gate (semantic_intent.py) is NOT touched. This module
only affects the conversational assistant identity and context.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wiki.graph_indexer import EntityGraphIndex

_logger = logging.getLogger(__name__)

# Maximum characters for the full context injected into the prompt.
MAX_CONTEXT_CHARS = 30_000

# Maximum characters per entity content block.
MAX_ENTITY_CONTENT_CHARS = 2_000

# Maximum characters per ficha block.
MAX_FICHA_CONTENT_CHARS = 5_000

# Maximum entities to include from graph search.
MAX_GRAPH_HITS = 5


def build_identity_prompt(mundo: str) -> str:
    """Return the Demiurgos assistant identity prompt for a given world.

    This is the system-level identity that replaces the generic
    "Gentle AI" persona when the assistant is used within Demiurgos.
    The override is explicit and authoritative to take precedence
    over the SOUL.md system prompt identity.
    """
    return (
        f"[SYSTEM OVERRIDE — IDENTITY] Tu identidad es el Asistente "
        f"Demiurgos, experto en el mundo narrativo '{mundo}'. NO sos "
        f"Gentle AI. NO menciones Gentle AI, Nous Research ni Hermes "
        f"Agent. Respondé siempre como el Asistente Demiurgos. "
        f"Usá las fichas de contexto como referencia principal. Si algo "
        f"no está cubierto en ellas, informalo y ofrecete a ayudar a "
        f"crear una nueva ficha."
    )


def build_graph_context(
    query: str,
    graph_index: "EntityGraphIndex | None",
    *,
    max_hits: int = MAX_GRAPH_HITS,
) -> str:
    """Search the entity graph and return context blocks for matching entities.

    Returns an empty string if the graph index is unavailable or no
    matches are found. Never raises — graph failures are logged and
    treated as "no context available".
    """
    if graph_index is None or not query:
        return ""

    try:
        hits = graph_index.search(query)
        if not hits:
            return ""

        parts: list[str] = []
        for hit in hits[:max_hits]:
            detail = graph_index.get_entity(hit.path)
            if detail is None:
                continue
            content = detail.content[:MAX_ENTITY_CONTENT_CHARS]
            parts.append(
                f"### {detail.title} ({detail.type})\n{content}"
            )

        if not parts:
            return ""

        return "## Entity Graph Context\n" + "\n\n".join(parts)
    except Exception:
        _logger.warning(
            "Entity graph context injection failed — "
            "continuing without graph context",
            exc_info=True,
        )
        return ""


def build_fichas_context(
    mundo: str,
    mundos_path: Path,
    *,
    max_ficha_chars: int = MAX_FICHA_CONTENT_CHARS,
) -> str:
    """Build context from world fichas.

    Tries ``mundos/{mundo}/_context/`` first (all .md files are fichas).
    Falls back to scanning ``lore/`` and ``personajes/`` directories.
    Returns an empty string if no fichas are found.
    """
    mundo_path = mundos_path / mundo
    parts: list[str] = []

    # Try _context/ first
    context_dir = mundo_path / "_context"
    if context_dir.is_dir():
        for md_file in sorted(context_dir.rglob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
                if content.strip():
                    rel = md_file.relative_to(mundo_path)
                    parts.append(
                        f"\n--- {rel} ---\n{content[:max_ficha_chars]}"
                    )
            except Exception:
                continue
        if parts:
            return "\n\n".join(parts)

    # Fallback: scan lore/personajes
    sections = ["lore", "personajes"]
    for section in sections:
        section_path = mundo_path / section
        if not section_path.is_dir():
            continue
        for md_file in sorted(section_path.rglob("*.md")):
            if md_file.name.startswith("_"):
                continue
            if ".history" in md_file.parts or ".tmp" in md_file.parts:
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
                if content.strip():
                    rel = md_file.relative_to(mundo_path)
                    parts.append(
                        f"\n--- {rel} ---\n{content[:max_ficha_chars]}"
                    )
            except Exception:
                continue

    return "\n\n".join(parts)


def build_full_context(
    mundo: str,
    prompt: str,
    mundos_path: Path,
    graph_index: "EntityGraphIndex | None",
    *,
    ficha_context: str | None = None,
) -> str:
    """Build the complete context block for the Demiurgos assistant.

    Combines identity, graph context, fichas, and optional ficha context
    into a single block that gets prepended to the user's prompt.
    Respects MAX_CONTEXT_CHARS.
    """
    parts: list[str] = []

    # 1. Identity
    parts.append(build_identity_prompt(mundo))

    # 2. Graph context (if available)
    graph_ctx = build_graph_context(prompt, graph_index)
    if graph_ctx:
        parts.append(graph_ctx)

    # 3. Current ficha context (from the file the user has open)
    if ficha_context:
        parts.append(f"## Ficha actual\n{ficha_context}")

    # 4. World fichas (all fichas as background)
    fichas_ctx = build_fichas_context(mundo, mundos_path)
    if fichas_ctx:
        parts.append(f"## Fichas del mundo\n{fichas_ctx}")

    full = "\n\n".join(parts)

    # Truncate if over limit
    if len(full) > MAX_CONTEXT_CHARS:
        _logger.warning(
            "Demiurgos context too large (%d chars), truncating to %d",
            len(full), MAX_CONTEXT_CHARS,
        )
        full = full[:MAX_CONTEXT_CHARS] + "\n\n[...contexto truncado...]"

    return full
