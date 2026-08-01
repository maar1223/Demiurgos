"""
tests/test_graph_mcp_server.py — Unit and integration tests for graph MCP tools.

Covers: graph_search, graph_read, graph_links, graph_status output shapes,
missing entity handling, empty index state, and end-to-end tool invocation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure the wiki package is importable (go up from tests/ → wiki/ → demiurgos-suite/)
_SRC_DIR = Path(__file__).resolve().parent.parent.parent  # demiurgos-suite/
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from wiki.graph_indexer import EntityGraphIndex    # noqa: E402
from wiki.mcp_adapter import GraphMCPAdapter        # noqa: E402
from wiki.graph_models import EntityDetail, EntityHit  # noqa: E402


# =============================================================================
# Helpers
# =============================================================================


def _make_hit(name: str = "Rhyz", type_: str = "Ficha", path: str = "personajes/rhyz.md") -> EntityHit:
    """Create a minimal EntityHit for mock returns."""
    return EntityHit(
        name=name,
        type=type_,
        path=path,
        title=name,
        description=f"Description of {name}",
        tags=["importante"],
        link_count=2,
        score=12.5,
    )


def _make_detail(name: str = "Rhyz", path: str = "personajes/rhyz.md") -> EntityDetail:
    """Create a minimal EntityDetail for mock returns."""
    return EntityDetail(
        name=name,
        type="Ficha",
        path=path,
        title=name,
        description=f"Full detail of {name}",
        tags=["importante"],
        content=f"# {name}\n\nContenido de ejemplo.\n",
        forward_links=["Vael La Silenciadora", "Ekkor"],
        backlinks=["sagas/ascension.md"],
        relaciones=[],
        word_count=5,
    )


def _mock_index(entity_count: int = 1, dirty: bool = False, last_build: str | None = "2026-08-01T00:00:00+00:00") -> MagicMock:
    """Return a MagicMock simulating an EntityGraphIndex instance."""
    mock = MagicMock(spec=EntityGraphIndex)
    mock.entity_count = entity_count
    mock.dirty = dirty
    mock.last_build = last_build
    return mock


# =============================================================================
# Unit tests — graph_search
# =============================================================================


class TestGraphSearch:
    def test_search_returns_matches_shape(self) -> None:
        """graph_search returns {matches: [...], query} with correct keys."""
        index = _mock_index()
        hit = _make_hit("Rhyz")
        index.search.return_value = [hit]
        adapter = GraphMCPAdapter(index)

        result = adapter.tool_search("Rhyz")

        assert isinstance(result, dict)
        assert "matches" in result
        assert "query" in result
        assert result["query"] == "Rhyz"
        assert len(result["matches"]) == 1

        match = result["matches"][0]
        assert match["name"] == "Rhyz"
        assert match["type"] == "Ficha"
        assert "path" in match
        assert "score" in match
        assert isinstance(match["score"], float)
        assert "tags" in match
        assert "link_count" in match
        assert "title" in match
        assert "description" in match

    def test_search_empty_results(self) -> None:
        """Empty search returns empty matches list."""
        index = _mock_index()
        index.search.return_value = []
        adapter = GraphMCPAdapter(index)

        result = adapter.tool_search("NoExiste")

        assert result["matches"] == []
        assert result["query"] == "NoExiste"

    def test_search_with_filters(self) -> None:
        """Filters are passed through to index.search()."""
        index = _mock_index()
        index.search.return_value = []
        adapter = GraphMCPAdapter(index)

        adapter.tool_search("test", filters={"type": "Ficha", "tag": "importante"})

        index.search.assert_called_once_with("test", {"type": "Ficha", "tag": "importante"})


# =============================================================================
# Unit tests — graph_read
# =============================================================================


class TestGraphRead:
    def test_read_existing_entity(self) -> None:
        """graph_read returns {entity: {...}, exists: true, path} for existing entity."""
        index = _mock_index()
        detail = _make_detail("Rhyz", "personajes/rhyz.md")
        index.get_entity.return_value = detail
        adapter = GraphMCPAdapter(index)

        result = adapter.tool_read("personajes/rhyz.md")

        assert result["exists"] is True
        assert result["path"] == "personajes/rhyz.md"
        entity = result["entity"]
        assert entity is not None
        assert entity["name"] == "Rhyz"
        assert entity["type"] == "Ficha"
        assert "content" in entity
        assert "forward_links" in entity
        assert "backlinks" in entity
        assert "relaciones" in entity
        assert "word_count" in entity
        assert entity["forward_links"] == ["Vael La Silenciadora", "Ekkor"]
        assert entity["backlinks"] == ["sagas/ascension.md"]

    def test_read_missing_entity_graceful(self) -> None:
        """graph_read for missing entity returns {exists: false} — NO exception."""
        index = _mock_index()
        index.get_entity.return_value = None  # entity not found
        adapter = GraphMCPAdapter(index)

        result = adapter.tool_read("no-existe")

        assert result["exists"] is False
        assert result["entity"] is None
        assert result["path"] == "no-existe"


# =============================================================================
# Unit tests — graph_links
# =============================================================================


class TestGraphLinks:
    def test_backlinks_shape(self) -> None:
        """graph_links with kind=backlinks returns {links: [...], kind, entity_path}."""
        index = _mock_index()
        index.get_links.return_value = [
            {"name": "Vael", "type": "Ficha", "path": "personajes/vael.md"}
        ]
        adapter = GraphMCPAdapter(index)

        result = adapter.tool_links("personajes/rhyz.md", "backlinks")

        assert result["kind"] == "backlinks"
        assert result["entity_path"] == "personajes/rhyz.md"
        assert len(result["links"]) == 1
        assert result["links"][0]["name"] == "Vael"

    def test_links_error_handling(self) -> None:
        """Invalid kind raises ValueError — adapter catches and returns error dict."""
        index = _mock_index()
        index.get_links.side_effect = ValueError("Unknown link kind: 'bogus'")
        adapter = GraphMCPAdapter(index)

        result = adapter.tool_links("personajes/rhyz.md", "bogus")

        assert result["links"] == []
        assert "error" in result
        assert "Unknown link kind" in result["error"]


# =============================================================================
# Unit tests — graph_status
# =============================================================================


class TestGraphStatus:
    def test_status_populated_index(self) -> None:
        """graph_status returns {entity_count, dirty, last_build} for populated index."""
        index = _mock_index(entity_count=42, dirty=True, last_build="2026-07-31T12:00:00Z")
        adapter = GraphMCPAdapter(index)

        result = adapter.tool_status()

        assert result["entity_count"] == 42
        assert result["dirty"] is True
        assert result["last_build"] == "2026-07-31T12:00:00Z"

    def test_status_empty_index(self) -> None:
        """Empty index: entity_count=0, dirty=false."""
        index = _mock_index(entity_count=0, dirty=False, last_build=None)
        adapter = GraphMCPAdapter(index)

        result = adapter.tool_status()

        assert result["entity_count"] == 0
        assert result["dirty"] is False
        assert result["last_build"] is None


# =============================================================================
# Integration tests — server instantiation and tool wiring
# =============================================================================


class TestServerIntegration:
    """End-to-end integration: import server module, verify tool signatures, end-to-end flow."""

    def test_server_module_imports(self) -> None:
        """Server module is importable without triggering argparse."""
        from wiki import graph_mcp_server  # noqa: F811

        assert hasattr(graph_mcp_server, "mcp")
        assert hasattr(graph_mcp_server, "graph_search")
        assert hasattr(graph_mcp_server, "graph_read")
        assert hasattr(graph_mcp_server, "graph_links")
        assert hasattr(graph_mcp_server, "graph_status")
        assert hasattr(graph_mcp_server, "init")
        assert hasattr(graph_mcp_server, "main")

    def test_tools_accept_correct_signatures(self) -> None:
        """All 4 tools accept the spec-defined parameter signatures."""
        from wiki.graph_mcp_server import (  # noqa: F811
            graph_links,
            graph_read,
            graph_search,
            graph_status,
        )

        import inspect

        # graph_search(query: str, type: str = "", tag: str = "")
        sig_search = inspect.signature(graph_search)
        assert list(sig_search.parameters.keys()) == ["query", "type", "tag"]

        # graph_read(entity_path: str)
        sig_read = inspect.signature(graph_read)
        assert list(sig_read.parameters.keys()) == ["entity_path"]

        # graph_links(entity_path: str = "", kind: str = "backlinks")
        sig_links = inspect.signature(graph_links)
        assert list(sig_links.parameters.keys()) == ["entity_path", "kind"]

        # graph_status() — no parameters
        sig_status = inspect.signature(graph_status)
        assert list(sig_status.parameters.keys()) == []

    def test_full_tool_chain_with_mocked_index(self) -> None:
        """All four tools work together with a mocked index — no I/O needed."""
        index = _mock_index(entity_count=1)
        hit = _make_hit("Rhyz", path="personajes/rhyz.md")
        detail = _make_detail("Rhyz", "personajes/rhyz.md")
        index.search.return_value = [hit]
        index.get_entity.return_value = detail
        index.get_links.return_value = [
            {"name": "Vael La Silenciadora", "type": "Ficha", "path": "personajes/vael.md"}
        ]
        adapter = GraphMCPAdapter(index)

        # Simulate the search-read-links flow
        search_result = adapter.tool_search("Rhyz")
        assert len(search_result["matches"]) == 1
        entity_path = search_result["matches"][0]["path"]

        read_result = adapter.tool_read(entity_path)
        assert read_result["exists"] is True
        assert read_result["entity"]["name"] == "Rhyz"

        links_result = adapter.tool_links(entity_path, "forward")
        assert links_result["kind"] == "forward"

        status_result = adapter.tool_status()
        assert status_result["entity_count"] == 1
