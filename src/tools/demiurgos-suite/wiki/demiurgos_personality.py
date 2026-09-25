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

from demiurgos_language import normalize_language, resolve_domain_language

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


def build_identity_prompt(mundo: str, *, language: str | None = None) -> str:
    """Return the Demiurgos assistant identity prompt for a given world.

    This is the system-level identity that replaces the generic
    "Gentle AI" persona when the assistant is used within Demiurgos.
    The override is explicit and authoritative to take precedence
    over the SOUL.md system prompt identity.

    ``language`` selects the prompt locale (``es`` neutral / ``en``) and
    instructs the assistant to answer in that language. When omitted, the
    persisted conversation domain is resolved (persisted-first, env fallback),
    so the system prompt follows the selected locale rather than the env.
    """
    resolved = (
        normalize_language(language)
        if language is not None
        else resolve_domain_language("conversation")
    )
    template = _IDENTITY_PROMPTS.get(resolved, _IDENTITY_PROMPTS["es"])
    return template.format(mundo=mundo)


# Neutral Spanish and English identity templates (PER-REQ-1/2). The Spanish
# variant is strictly neutral: no voseo, no regionalisms (see
# frontend/src/i18n/forbidden.json, consumed by tests/test_neutral_spanish.py).
_IDENTITY_PROMPTS: dict[str, str] = {
    "es": (
        "[SYSTEM OVERRIDE — IDENTITY] Tu identidad es el Asistente "
        "Demiurgos, experto en el mundo narrativo '{mundo}'. No eres "
        "Gentle AI. No menciones Gentle AI, Nous Research ni Hermes "
        "Agent. Responde siempre como el Asistente Demiurgos. "
        "Usa las fichas de contexto como referencia principal. Si algo "
        "no está cubierto en ellas, comunícalo y ofrécete a ayudar a "
        "crear una nueva ficha. "
        "Transparencia de mundo: siempre indica de qué mundo narrativo "
        "tomaste la información (por ejemplo: 'en el mundo {mundo}', 'según "
        "la ficha X'). Cuando cites datos del grafo o de las fichas, nombra "
        "el mundo para que el usuario sepa de dónde vienen. Si buscas "
        "algo y no aparece en el mundo activo '{mundo}', busca en los "
        "otros mundos (usa el parámetro `mundo` de las herramientas de "
        "búsqueda del grafo) antes de decir que no existe. No concluyas "
        "que no está sin comprobar antes los mundos disponibles. "
        "Responde en español neutro."
    ),
    "en": (
        "[SYSTEM OVERRIDE — IDENTITY] Your identity is the Demiurgos "
        "Assistant, an expert in the narrative world '{mundo}'. You are not "
        "Gentle AI. Do not mention Gentle AI, Nous Research, or Hermes "
        "Agent. Always answer as the Demiurgos Assistant. "
        "Use the context sheets as your primary reference. If something is "
        "not covered there, say so and offer to help create a new sheet. "
        "World transparency: always state which narrative world you took "
        "the information from (for example: 'in the world {mundo}', "
        "'according to sheet X'). When citing graph or sheet data, name the "
        "world so the user knows where it comes from. If you search for "
        "something and it does not appear in the active world '{mundo}', "
        "search the other worlds (use the `mundo` parameter of the graph "
        "search tools) before saying it does not exist. Do not conclude it "
        "is absent without first checking the available worlds. "
        "Answer in English."
    ),
}


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
                    # Canonical display format is POSIX-separated on every
                    # platform (as_posix): the ``--- path ---`` header is the
                    # user-visible ficha path and must not carry Windows
                    # backslashes into the prompt.
                    parts.append(
                        f"\n--- {rel.as_posix()} ---\n{content[:max_ficha_chars]}"
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
                    # POSIX-separated display path (as_posix), same contract
                    # as the _context/ branch above.
                    parts.append(
                        f"\n--- {rel.as_posix()} ---\n{content[:max_ficha_chars]}"
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
    language: str | None = None,
) -> str:
    """Build the complete context block for the Demiurgos assistant.

    Combines identity, graph context, fichas, and optional ficha context
    into a single block that gets prepended to the user's prompt.
    Respects MAX_CONTEXT_CHARS. ``language`` selects the identity prompt
    locale; when omitted the persisted conversation domain is resolved.
    """
    parts: list[str] = []

    # 1. Identity
    parts.append(build_identity_prompt(mundo, language=language))

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
