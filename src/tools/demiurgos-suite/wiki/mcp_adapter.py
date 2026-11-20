"""
MCP Adapter — thin wrapper around EntityGraphIndex for MCP tool consumption.

Task 3.2: GraphMCPAdapter wraps the index methods and returns only
JSON-serializable dicts (no dataclasses), suitable for MCP server tools.

Usage::

    adapter = GraphMCPAdapter(index, mundos_path="mundos",
                              project="vibrantes")
    result = adapter.tool_search("Rhyz")   # → {"matches": [...]}
    entity = adapter.tool_read("personajes/Rhyz_El_Resonante.md")

All methods are pure — no side effects, no I/O beyond what the index already
performs internally. Conflict detection reads the product's own assistant
memory (``AssistantMemoryStore``); nothing here shells out to an external CLI.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .graph_indexer import EntityGraphIndex
from .assistant_memory_store import AssistantMemoryStore
from .narrative_utils import (
    extract_claims,
    compare_claims,
    extract_entities,
    extract_themes,
    scan_ideas_dir,
    search_ideas_bm25,
    format_lore,
)


class GraphMCPAdapter:
    """Adapts EntityGraphIndex queries into MCP-tool-compatible dict shapes.

    Same underlying methods, different output format — always a flat dict
    with JSON-serializable values.
    """

    def __init__(
        self,
        index: EntityGraphIndex,
        mundos_path: str | Path | None = None,
        project: str | None = None,
        memory_store: AssistantMemoryStore | None = None,
    ) -> None:
        self._default_index = index
        self._indexes: dict[str, EntityGraphIndex] = {}
        self._indexes_lock = threading.RLock()
        self._mundos_path: Path | None = (
            Path(mundos_path) if mundos_path else None
        )
        self._project = project or "demiurgos"
        # The product's own memory is the only conflict source after the Engram
        # cutover. ``None`` means "open the default store on first use", which
        # keeps the adapter cheap to construct and hermetic in tests.
        self._memory_store = memory_store
        self._memory_store_lock = threading.Lock()

    # -------------------------------------------------------------------
    # Index resolution (per-world lazy build)
    # -------------------------------------------------------------------

    def _index_for(self, mundo: str) -> EntityGraphIndex:
        """Resolve the index for a world, building it lazily on first use.

        Empty or whitespace-only ``mundo`` returns the injected default index
        (backward-compatible path — never builds a new index).  A named world
        matching the configured project (``self._project``) returns the default
        index too — it was built for that world at startup and already has its
        file watcher running.  Only worlds DIFFERENT from the configured one
        get their own lazily-built ``EntityGraphIndex`` (one watcher per world,
        never two on the same directory).
        """
        mundo = (mundo or "").strip()
        if not mundo or mundo == self._project:
            # The default index may not be built yet when the server starts
            # (lazy-first-build). Build it on first use so the MCP server does
            # not block its stdio handshake with a synchronous index build at
            # startup (which loses the gateway's initial connection).
            with self._indexes_lock:
                if self._default_index.entity_count == 0:
                    self._default_index.build(self._project)
                    try:
                        self._default_index.start_watch(self._project)
                    except ImportError:
                        pass  # watchdog not installed — live updates disabled
            return self._default_index

        with self._indexes_lock:
            cached = self._indexes.get(mundo)
            if cached is not None:
                return cached

            idx = EntityGraphIndex(self._mundos_path)
            idx.build(mundo)
            try:
                idx.start_watch(mundo)
            except ImportError:
                pass  # watchdog not installed — live updates disabled
            self._indexes[mundo] = idx
            return idx

    # -------------------------------------------------------------------
    # Tools
    # -------------------------------------------------------------------

    def tool_search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        mundo: str = "",
    ) -> dict[str, Any]:
        """Search entities by name/title/tags.

        ``mundo`` defaults to the active world; pass another world name to
        search that world. When you return results, tell the user which
        world they came from.  Returns ``{"matches": [...], "query": "..."}``.
        """
        hits = self._index_for(mundo).search(query, filters)
        return {
            "matches": [self._hit_to_dict(h) for h in hits],
            "query": query,
        }

    def tool_read(self, entity_path: str, mundo: str = "") -> dict[str, Any]:
        """Read a full entity by path.

        ``mundo`` defaults to the active world; pass another world name to
        read that world. When you return results, tell the user which world
        they came from.  Returns ``{"entity": {...}, "exists": true|false}``.
        """
        detail = self._index_for(mundo).get_entity(entity_path)
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
        mundo: str = "",
    ) -> dict[str, Any]:
        """Query link graph — same kinds as ``EntityGraphIndex.get_links()``.

        ``mundo`` defaults to the active world; pass another world name to
        query that world. When you return results, tell the user which world
        they came from.  Returns ``{"links": [...], "kind": "...", "entity_path": "..."}``.
        """
        try:
            links = self._index_for(mundo).get_links(entity_path, kind)
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

    def tool_status(self, mundo: str = "") -> dict[str, Any]:
        """Return current index metrics.

        ``mundo`` is the world to query (optional; defaults to the configured
        world).  Returns ``{"entity_count": N, "dirty": bool, "last_build": ISO}``.
        """
        index = self._index_for(mundo)
        return {
            "entity_count": index.entity_count,
            "dirty": index.dirty,
            "last_build": index.last_build,
        }

    def tool_rebuild(self, mundo: str = "") -> dict[str, Any]:
        """Force a full index rebuild from disk.

        ``mundo`` is the world to rebuild (optional; defaults to the configured
        world).  Returns ``{"entity_count": N, "rebuilt": True, "last_build": ISO}``.
        """
        index = self._index_for(mundo)
        count = index.build(mundo if mundo else self._project)
        return {
            "entity_count": count,
            "rebuilt": True,
            "last_build": index.last_build,
        }

    # -------------------------------------------------------------------
    # Narrative tools (TG-01 through TG-05)
    # -------------------------------------------------------------------

    def tool_lore_search(self, query: str, mundo: str = "") -> dict[str, Any]:
        """Search the entity graph for entities matching ``query``.

        ``mundo`` defaults to the active world; pass another world name to
        search that world. When you return results, tell the user which world
        they came from.  Returns ``{"graph_matches": [...], "query": "..."}``;
        every match is tagged with ``"source": "graph"``.
        """
        # Graph search
        graph_hits = self._index_for(mundo).search(query)
        graph_matches: list[dict[str, Any]] = [
            {
                "name": h.name,
                "type": h.type,
                "path": h.path,
                "title": h.title,
                "description": h.description,
                "tags": h.tags,
                "link_count": h.link_count,
                "score": h.score,
                "source": "graph",
            }
            for h in graph_hits
        ]

        return {
            "graph_matches": graph_matches,
            "query": query,
        }

    def tool_lore_conflicts(self, entity_path: str, mundo: str = "") -> dict[str, Any]:
        """Detect contradictions between an entity and the product's own memory.

        ``mundo`` is the world to query (optional; defaults to the configured
        world).  Returns ``{"conflicts": [...], "entity_path": "..."}``.
        Empty conflicts list means no contradictions found.  ``memory_available``
        is ``False`` when the memory store cannot be read, so an empty list is
        never mistaken for a clean bill of health.
        """
        # Get entity from index
        entity = self._index_for(mundo).get_entity(entity_path)
        if entity is None:
            return {"conflicts": [], "entity_path": entity_path, "exists": False}

        # Extract claims from entity content
        entity_claims = extract_claims(entity.content, entity_path)

        memory_available, memory_claims = self._memory_claims(
            entity.name, mundo or self._project,
        )

        # Compare and detect conflicts
        conflicts = compare_claims(entity_claims, memory_claims)

        return {
            "conflicts": conflicts,
            "entity_path": entity_path,
            "exists": True,
            "entity_claims_count": len(entity_claims),
            "memory_claims_count": len(memory_claims),
            "memory_available": memory_available,
        }

    def _memory_claims(
        self, entity_name: str, world: str,
    ) -> tuple[bool, list[dict[str, str]]]:
        """Return ``(available, claims)`` from the product's assistant memory.

        The memory store is an optimization for conflict detection, never a hard
        dependency: an unreadable database (missing, locked, schema-incompatible)
        degrades to ``(False, [])`` so the MCP tool still answers.
        """
        try:
            store = self._memory_store
            if store is None:
                with self._memory_store_lock:
                    if self._memory_store is None:
                        self._memory_store = AssistantMemoryStore()
                    store = self._memory_store
            entries = store.search(
                entity_name, world=world, limit=10, include_proposals=False,
            )
        except Exception:  # noqa: BLE001 - a tool must never fail on memory I/O
            return False, []

        claims: list[dict[str, str]] = []
        for entry in entries:
            entry_id = getattr(entry, "id", None)
            statement = getattr(entry, "statement", "") or ""
            if not statement:
                continue
            for claim in extract_claims(statement, f"assistant-memory#{entry_id}"):
                claim["id"] = str(entry_id)
                claims.append(claim)
        return True, claims

    def tool_auto_tag(self, text: str, mundo: str) -> dict[str, Any]:
        """Analyse text for known entity mentions and themes.

        Returns ``{"entities": [...], "themes": [...], "text": "..."}``.
        Entity names are resolved to canonical graph names.
        """
        # Get known entity names from the index
        known_names = self._index_for(mundo).get_entity_names()

        entities = extract_entities(text, known_names)
        themes = extract_themes(text)

        return {
            "entities": entities,
            "themes": themes,
            "text": text,
            "mundo": mundo,
        }

    def tool_idea_link(self, content: str, mundo: str) -> dict[str, Any]:
        """Search the Idea Bank for similar ideas using BM25.

        Returns ``{"matches": [...], "content": "..."}``.
        Matches include slug, score, and preview (first 80 chars).
        """
        spath = str(self._mundos_path) if self._mundos_path else "mundos"
        ideas = scan_ideas_dir(mundo or self._project, spath)
        matches = search_ideas_bm25(content, ideas)

        return {
            "matches": matches,
            "content": content,
            "mundo": mundo,
            "ideas_scanned": len(ideas),
        }

    def tool_lore_format(self, data: dict[str, Any]) -> str:
        """Format lore into a deterministic markdown string with [[wikilinks]].

        Pure string templating — zero LLM/API calls. Empty sections omitted.
        """
        return format_lore(data)

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
            "shape": hit.shape,
            "canon_state": hit.canon_state,
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
            "shape": detail.shape,
            "canon_state": detail.canon_state,
        }
