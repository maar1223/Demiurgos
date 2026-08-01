"""
MCP Adapter â€” thin wrapper around EntityGraphIndex for MCP tool consumption.

Task 3.2: GraphMCPAdapter wraps the index methods and returns only
JSON-serializable dicts (no dataclasses), suitable for MCP server tools.

Usage::

    adapter = GraphMCPAdapter(index)
    result = adapter.tool_search("Rhyz")   # â†’ {"matches": [...]}
    entity = adapter.tool_read("personajes/Rhyz_El_Resonante.md")

All methods are pure â€” no side effects, no I/O beyond what the index already
performs internally.
"""

from __future__ import annotations

from typing import Any

from .graph_indexer import EntityGraphIndex


class GraphMCPAdapter:
    """Adapts EntityGraphIndex queries into MCP-tool-compatible dict shapes.

    Same underlying methods, different output format â€” always a flat dict
    with JSON-serializable values.
    """

    def __init__(self, index: EntityGraphIndex) -> None:
        self._index = index

    # -------------------------------------------------------------------
    # Tools
    # -------------------------------------------------------------------

    def tool_search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Search entities by name/title/tags.

        Returns ``{"matches": [...], "query": "..."}``.
        """
        hits = self._index.search(query, filters)
        return {
            "matches": [self._hit_to_dict(h) for h in hits],
            "query": query,
        }

    def tool_read(self, entity_path: str) -> dict[str, Any]:
        """Read a full entity by path.

        Returns ``{"entity": {...}, "exists": true|false}``.
        """
        detail = self._index.get_entity(entity_path)
        if detail is None:
            return {"entity": None, "exists": False, "path": entity_path}
        return {
            "entity": self._detail_to_dict(detail),
            "exists": True,
            "path": entity_path,
        }

    def tool_links(
        self,
        entity_path: str | None = None,
        kind: str = "backlinks",
    ) -> dict[str, Any]:
        """Query link graph â€” same kinds as ``EntityGraphIndex.get_links()``.

        Returns ``{"links": [...], "kind": "...", "entity_path": "..."}``.
        """
        try:
            links = self._index.get_links(entity_path, kind)
        except ValueError as exc:
            return {
                "links": [],
                "kind": kind,
                "entity_path": entity_path,
                "error": str(exc),
            }
        return {
            "links": links,
            "kind": kind,
            "entity_path": entity_path,
        }

    def tool_status(self) -> dict[str, Any]:
        """Return current index metrics.

        Returns ``{"entity_count": N, "dirty": bool, "last_build": ISO}``.
        """
        return {
            "entity_count": self._index.entity_count,
            "dirty": self._index.dirty,
            "last_build": self._index.last_build,
        }

    # -------------------------------------------------------------------
    # Serialization helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _hit_to_dict(hit) -> dict[str, Any]:
        """Convert an EntityHit to a plain dict."""
        return {
            "name": hit.name,
            "type": hit.type,
            "path": hit.path,
            "title": hit.title,
            "description": hit.description,
            "tags": hit.tags,
            "link_count": hit.link_count,
            "score": hit.score,
        }

    @staticmethod
    def _detail_to_dict(detail) -> dict[str, Any]:
        """Convert an EntityDetail to a plain dict."""
        return {
            "name": detail.name,
            "type": detail.type,
            "path": detail.path,
            "title": detail.title,
            "description": detail.description,
            "tags": detail.tags,
            "content": detail.content,
            "forward_links": detail.forward_links,
            "backlinks": detail.backlinks,
            "relaciones": detail.relaciones,
            "word_count": detail.word_count,
        }
