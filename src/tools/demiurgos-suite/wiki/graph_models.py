"""
Graph models â€” dataclasses for the entity graph index.

Task 2.1: EntityHit and EntityDetail used by EntityGraphIndex.
Plain dataclasses (not Pydantic) â€” internal data structures only.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EntityHit:
    """Lightweight search result â€” enough for listing, not full content."""

    name: str
    type: str
    path: str  # relative from mundo root, e.g. "personajes/Rhyz_El_Resonante.md"
    title: str
    description: str
    tags: list[str]
    link_count: int
    score: float = 0.0


@dataclass
class EntityDetail:
    """Full entity with content, links, and backlinks."""

    name: str
    type: str
    path: str
    title: str
    description: str
    tags: list[str]
    content: str  # full body text
    forward_links: list[str] = field(default_factory=list)
    backlinks: list[str] = field(default_factory=list)
    relaciones: list[dict] = field(default_factory=list)
    word_count: int = 0


@dataclass
class EngramMatch:
    """A single result from Engram memory search.

    Used by lore_search to tag each source as ``engram``.
    """

    id: int
    title: str
    preview: str = ""


@dataclass
class LoreConflict:
    """A detected contradiction between entity content and Engram memory.

    conflict_type is one of the CONFLICT_TYPES taxonomy:
    date_contradiction | status_contradiction | name_mismatch |
    relationship_conflict | unknown
    """

    claim_a: str
    source_a: str
    claim_b: str
    source_b: str
    conflict_type: str = "unknown"


@dataclass
class TagResult:
    """Result of auto-tagging text with entities and themes.

    entities: resolved canonical entity names.
    themes: lowercase theme names from the keyword map.
    """

    entities: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)


@dataclass
class IdeaLinkResult:
    """A matched idea from the Idea Bank BM25 search.

    preview_80chars: first 80 characters of the idea body.
    """

    slug: str
    score: float
    preview_80chars: str = ""
