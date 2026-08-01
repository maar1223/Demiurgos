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
