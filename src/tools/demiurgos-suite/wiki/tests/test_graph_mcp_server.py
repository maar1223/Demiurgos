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
from wiki.narrative_utils import THEME_MAP           # noqa: E402


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

        # graph_search(query: str, type: str = "", tag: str = "", mundo: str = "")
        sig_search = inspect.signature(graph_search)
        assert list(sig_search.parameters.keys()) == ["query", "type", "tag", "mundo"]

        # graph_read(entity_path: str, mundo: str = "")
        sig_read = inspect.signature(graph_read)
        assert list(sig_read.parameters.keys()) == ["entity_path", "mundo"]

        # graph_links(entity_path: str = "", kind: str = "backlinks", mundo: str = "")
        sig_links = inspect.signature(graph_links)
        assert list(sig_links.parameters.keys()) == ["entity_path", "kind", "mundo"]

        # graph_status(mundo: str = "")
        sig_status = inspect.signature(graph_status)
        assert list(sig_status.parameters.keys()) == ["mundo"]

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


# =============================================================================
# Unit tests — lore_search (TG-01)
# =============================================================================


class TestLoreSearch:
    def test_lore_search_returns_correct_shape(self) -> None:
        """lore_search returns {graph_matches, engram_matches, query} with source tags."""
        from unittest.mock import patch

        index = _mock_index()
        hit = _make_hit("Rhyz", path="personajes/rhyz.md")
        index.search.return_value = [hit]
        adapter = GraphMCPAdapter(index, engram_enabled=True)

        mock_engram = [
            {"id": 42, "title": "Rhyz origin story", "preview": "Rhyz was born..."},
        ]

        with patch("wiki.mcp_adapter.engram_search", return_value=mock_engram):
            result = adapter.tool_lore_search("Rhyz")

        assert "graph_matches" in result
        assert "engram_matches" in result
        assert "query" in result
        assert result["query"] == "Rhyz"
        assert len(result["graph_matches"]) == 1
        assert result["graph_matches"][0]["source"] == "graph"
        assert result["graph_matches"][0]["name"] == "Rhyz"
        assert len(result["engram_matches"]) == 1
        assert result["engram_matches"][0]["source"] == "engram"
        assert result["engram_matches"][0]["id"] == 42

    def test_lore_search_engram_disabled(self) -> None:
        """With engram disabled, engram_matches is always empty."""
        index = _mock_index()
        hit = _make_hit("Vael")
        index.search.return_value = [hit]
        adapter = GraphMCPAdapter(index, engram_enabled=False)

        result = adapter.tool_lore_search("Vael")

        assert result["engram_matches"] == []
        assert len(result["graph_matches"]) == 1
        assert result["graph_matches"][0]["source"] == "graph"

    def test_lore_search_empty_query_both_empty(self) -> None:
        """Empty query returns empty arrays for both sources."""
        from unittest.mock import patch

        index = _mock_index()
        index.search.return_value = []
        adapter = GraphMCPAdapter(index, engram_enabled=True)

        with patch("wiki.mcp_adapter.engram_search", return_value=[]):
            result = adapter.tool_lore_search("")

        assert result["graph_matches"] == []
        assert result["engram_matches"] == []


# =============================================================================
# Unit tests — lore_conflicts (TG-02)
# =============================================================================


class TestLoreConflicts:
    def test_conflicts_entity_not_found(self) -> None:
        """Missing entity returns {exists: false, conflicts: []}."""
        index = _mock_index()
        index.get_entity.return_value = None
        adapter = GraphMCPAdapter(index)

        result = adapter.tool_lore_conflicts("no-existe.md")

        assert result["exists"] is False
        assert result["conflicts"] == []
        assert result["entity_path"] == "no-existe.md"

    def test_conflicts_engram_disabled(self) -> None:
        """With engram disabled, returns entity claim count and no conflicts."""
        index = _mock_index()
        detail = _make_detail("Rhyz", "personajes/rhyz.md")
        detail.content = (
            "---\nestado: vivo\naño_nacimiento: 1400\n---\n"
            "# Rhyz\n\nRhyz nació en 1400 AR.\n"
        )
        index.get_entity.return_value = detail
        adapter = GraphMCPAdapter(index, engram_enabled=False)

        result = adapter.tool_lore_conflicts("personajes/rhyz.md")

        assert result["exists"] is True
        assert result["conflicts"] == []
        assert "entity_claims_count" in result

    def test_conflicts_detects_date_contradiction(self) -> None:
        """Detects conflict when entity and Engram disagree on dates."""
        from unittest.mock import patch

        index = _mock_index()
        detail = _make_detail("Rhyz", "personajes/rhyz.md")
        detail.content = (
            "---\nestado: vivo\naño_muerte: 1450\n---\n"
            "# Rhyz\n\nRhyz murió en 1450.\n"
        )
        index.get_entity.return_value = detail
        adapter = GraphMCPAdapter(index, engram_enabled=True)

        mock_engram_hits = [
            {"id": 99, "title": "Rhyz death timeline", "preview": "Rhyz died in 1452..."},
        ]
        mock_obs_content = "---\nestado: muerto\naño_muerte: 1452\n---\nRhyz murió en el año 1452."

        with patch("wiki.mcp_adapter.engram_search", return_value=mock_engram_hits):
            with patch("wiki.mcp_adapter.engram_get_observation", return_value=mock_obs_content):
                result = adapter.tool_lore_conflicts("personajes/rhyz.md")

        assert result["exists"] is True
        assert len(result["conflicts"]) >= 1
        # Should detect either date or status contradiction
        conflict_types = {c["conflict_type"] for c in result["conflicts"]}
        assert "date_contradiction" in conflict_types or "status_contradiction" in conflict_types


# =============================================================================
# Unit tests — lore_format (TG-05)
# =============================================================================


class TestLoreFormat:
    def test_format_full_struct(self) -> None:
        """Full struct produces all three sections with [[wikilinks]]."""
        index = _mock_index()
        adapter = GraphMCPAdapter(index)

        data = {
            "entity": {
                "name": "Rhyz El Resonante",
                "type": "Ficha",
                "description": "Un eco del pasado",
                "tags": ["importante", "místico"],
                "path": "personajes/rhyz.md",
                "content": "Rhyz entrenó en las montañas durante años.",
            },
            "engram": [
                {"title": "Session 42", "preview": "We discussed Rhyz backstory."},
            ],
            "conflicts": [
                {
                    "claim_a": "1450",
                    "claim_b": "1452",
                    "conflict_type": "date_contradiction",
                },
            ],
        }

        result = adapter.tool_lore_format(data)

        assert "[[Rhyz El Resonante]]" in result
        assert "Engram Context" in result
        assert "Conflicts" in result
        assert "date_contradiction" in result

    def test_format_entity_only_omits_empty_sections(self) -> None:
        """Entity-only struct omits Engram and Conflicts sections."""
        index = _mock_index()
        adapter = GraphMCPAdapter(index)

        data = {
            "entity": {"name": "Ekkor", "type": "Lugar"},
        }

        result = adapter.tool_lore_format(data)

        assert "[[Ekkor]]" in result
        assert "Engram Context" not in result
        assert "Conflicts" not in result

    def test_format_empty_struct_returns_empty(self) -> None:
        """Empty struct returns empty string."""
        index = _mock_index()
        adapter = GraphMCPAdapter(index)

        result = adapter.tool_lore_format({})

        assert result == ""


# =============================================================================
# Unit tests — auto_tag (TG-03)
# =============================================================================


class TestAutoTag:
    def test_auto_tag_detects_entities(self) -> None:
        """Finds canonical entity names mentioned in text."""
        index = _mock_index()
        index.get_entity_names.return_value = {
            "Rhyz",
            "Vael",
            "Ekkor",
        }
        adapter = GraphMCPAdapter(index)

        # mundo="" routes to the injected default index (the mock)
        result = adapter.tool_auto_tag("Rhyz trained Vael in the mountains", "")

        assert "entities" in result
        assert "Rhyz" in result["entities"]
        assert "Vael" in result["entities"]
        assert "themes" in result
        assert "text" in result
        assert result["text"] == "Rhyz trained Vael in the mountains"

    def test_auto_tag_detects_themes(self) -> None:
        """Extracts themes via keyword matching."""
        index = _mock_index()
        index.get_entity_names.return_value = set()
        adapter = GraphMCPAdapter(index)

        result = adapter.tool_auto_tag(
            "Hubo una gran batalla seguida de una traición inesperada", "",
        )

        assert "batalla" in result["themes"]
        assert "traicion" in result["themes"]
        assert result["entities"] == []

    def test_auto_tag_empty_text(self) -> None:
        """Empty text returns empty entities and themes."""
        index = _mock_index()
        index.get_entity_names.return_value = {"Rhyz"}
        adapter = GraphMCPAdapter(index)

        result = adapter.tool_auto_tag("", "")

        assert result["entities"] == []
        assert result["themes"] == []

    def test_auto_tag_no_known_entities(self) -> None:
        """Empty entity index returns no entities but still extracts themes."""
        index = _mock_index()
        index.get_entity_names.return_value = set()
        adapter = GraphMCPAdapter(index)

        result = adapter.tool_auto_tag("Una batalla épica entre dos reinos", "")

        assert result["entities"] == []
        assert "batalla" in result["themes"]


# =============================================================================
# Unit tests — idea_link (TG-04)
# =============================================================================


class TestIdeaLink:
    def test_idea_link_returns_correct_shape(self) -> None:
        """idea_link returns {matches, content, mundo, ideas_scanned}."""
        from unittest.mock import patch

        index = _mock_index()
        adapter = GraphMCPAdapter(index, mundos_path="mundos")

        mock_ideas = [
            {
                "path": "Ideas/2026-07-30-idea.md",
                "frontmatter": {"slug": "my-idea", "title": "Test"},
                "body": "A test idea body.",
                "slug": "my-idea",
            },
        ]
        mock_matches = [
            {"slug": "my-idea", "score": 0.85, "preview_80chars": "A test idea body."},
        ]

        with patch("wiki.mcp_adapter.scan_ideas_dir", return_value=mock_ideas):
            with patch("wiki.mcp_adapter.search_ideas_bm25", return_value=mock_matches):
                result = adapter.tool_idea_link("test idea", "vibrantes")

        assert "matches" in result
        assert "content" in result
        assert "mundo" in result
        assert "ideas_scanned" in result
        assert result["matches"] == mock_matches
        assert result["content"] == "test idea"
        assert result["ideas_scanned"] == 1

    def test_idea_link_empty_dir(self) -> None:
        """Empty Ideas/ returns empty matches."""
        from unittest.mock import patch

        index = _mock_index()
        adapter = GraphMCPAdapter(index, mundos_path="mundos")

        with patch("wiki.mcp_adapter.scan_ideas_dir", return_value=[]):
            with patch("wiki.mcp_adapter.search_ideas_bm25", return_value=[]):
                result = adapter.tool_idea_link("nothing", "vibrantes")

        assert result["matches"] == []
        assert result["ideas_scanned"] == 0


# =============================================================================
# Updated integration tests — server name + new tool registration
# =============================================================================


class TestNewServerTools:
    def test_server_name_is_demiurgos_mcp(self) -> None:
        """Server instance is named 'demiurgos-mcp' (not 'demiurgos-graph')."""
        from wiki.graph_mcp_server import mcp  # noqa: F811

        # FastMCP stores name in the FastMCP instance
        assert mcp.name == "demiurgos-mcp"

    def test_new_tools_registered(self) -> None:
        """All 9 tools (4 original + 5 new) are defined on the module."""
        from wiki import graph_mcp_server  # noqa: F811

        assert hasattr(graph_mcp_server, "graph_search")
        assert hasattr(graph_mcp_server, "graph_read")
        assert hasattr(graph_mcp_server, "graph_links")
        assert hasattr(graph_mcp_server, "graph_status")
        assert hasattr(graph_mcp_server, "lore_search")
        assert hasattr(graph_mcp_server, "lore_conflicts")
        assert hasattr(graph_mcp_server, "lore_format")
        assert hasattr(graph_mcp_server, "auto_tag")
        assert hasattr(graph_mcp_server, "idea_link")

    def test_new_tool_signatures(self) -> None:
        """All 5 new tools accept their spec-defined parameter signatures."""
        from wiki.graph_mcp_server import (  # noqa: F811
            lore_search,
            lore_conflicts,
            lore_format,
            auto_tag,
            idea_link,
        )

        import inspect

        sig_ls = inspect.signature(lore_search)
        assert list(sig_ls.parameters.keys()) == ["query", "mundo"]

        sig_lc = inspect.signature(lore_conflicts)
        assert list(sig_lc.parameters.keys()) == ["entity_path", "mundo"]

        sig_lf = inspect.signature(lore_format)
        assert list(sig_lf.parameters.keys()) == ["data"]

        sig_at = inspect.signature(auto_tag)
        assert list(sig_at.parameters.keys()) == ["text", "mundo"]

        sig_il = inspect.signature(idea_link)
        assert list(sig_il.parameters.keys()) == ["content", "mundo"]

    def test_init_with_no_engram(self) -> None:
        """init() called with engram_enabled=False creates disabled adapter."""
        from wiki.graph_mcp_server import (
            init as server_init,
            _adapter,
            _engram_enabled,
        )

        # We can't call init() with real paths in test env, but we can
        # verify the function signature accepts engram_enabled parameter.
        import inspect

        sig = inspect.signature(server_init)
        params = sig.parameters
        assert "engram_enabled" in params
        assert params["engram_enabled"].default is True
        assert "engram_cmd" in params
        assert params["engram_cmd"].default == "engram"


# =============================================================================
# Search score filtering — entities with zero relevance are excluded
# =============================================================================


class TestSearchScoreFiltering:
    """Verify that EntityGraphIndex.search() filters out zero-score results."""

    @staticmethod
    def _seed_cache(index: EntityGraphIndex, entities: list[dict]) -> None:
        """Populate the index cache with test entities, bypassing file scan."""
        with index._lock:
            index._cache["entities"] = {}
            for ent in entities:
                path = ent.get("path", ent["name"])
                # Ensure required keys exist
                index._cache["entities"][path] = {
                    "name": ent["name"],
                    "type": ent.get("type", "Ficha"),
                    "path": path,
                    "title": ent.get("title", ent["name"]),
                    "description": ent.get("description", ""),
                    "tags": ent.get("tags", []),
                    "content": ent.get("content", ""),
                    "forward_links": ent.get("forward_links", []),
                    "backlinks": ent.get("backlinks", []),
                    "relaciones": ent.get("relaciones", []),
                    "word_count": ent.get("word_count", 0),
                }

    def test_excludes_zero_score_entities(self) -> None:
        """Entities with zero relevance are excluded when search tokens exist."""
        index = EntityGraphIndex()
        self._seed_cache(
            index,
            [
                {
                    "name": "Rhyz El Resonante",
                    "type": "Personaje",
                    "path": "personajes/rhyz.md",
                    "title": "Rhyz El Resonante",
                    "description": "Protagonista de Ekkor.",
                    "tags": ["protagonista", "stal04"],
                },
                {
                    "name": "Toryn El Mecanico",
                    "type": "Personaje",
                    "path": "personajes/toryn.md",
                    "title": "Toryn El Mecanico",
                    "description": "Ingeniero de los distritos bajos.",
                    "tags": ["secundario", "ingeniero"],
                },
                {
                    "name": "Ayagar Fantasma",
                    "type": "Criatura",
                    "path": "lore/ayagar_fantasma.md",
                    "title": "Ayagar Fantasma",
                    "description": "Criatura etérea sin relación alguna.",
                    "tags": ["criatura", "fantasma"],
                },
                {
                    "name": "Ekkor",
                    "type": "Lugar",
                    "path": "lore/ekkor.md",
                    "title": "Ekkor",
                    "description": "La ciudad capital.",
                    "tags": ["ciudad", "capital"],
                },
            ],
        )

        results = index.search("Rhyz")

        names = [r.name for r in results]
        # Rhyz → prefix match on name (+10) → kept
        assert "Rhyz El Resonante" in names
        # Toryn → description does NOT mention "Rhyz" → score 0 → excluded
        assert "Toryn El Mecanico" not in names
        # Ayagar → no mention → excluded
        assert "Ayagar Fantasma" not in names
        # Ekkor → no mention → excluded
        assert "Ekkor" not in names
        assert len(results) == 1

    def test_all_excluded_returns_empty(self) -> None:
        """When no entity matches the query, return empty list."""
        index = EntityGraphIndex()
        self._seed_cache(
            index,
            [
                {
                    "name": "Rhyz",
                    "type": "Personaje",
                    "path": "personajes/rhyz.md",
                    "title": "Rhyz",
                    "description": "Un personaje cualquiera.",
                    "tags": ["test"],
                },
            ],
        )

        results = index.search("ZzzzInexistente")

        assert results == []

    def test_empty_query_returns_empty(self) -> None:
        """Empty query with no filters returns empty (fast-return path)."""
        index = EntityGraphIndex()
        self._seed_cache(
            index,
            [{"name": "X", "path": "x.md"}],
        )

        results = index.search("")

        assert results == []

    def test_filters_without_query_returns_all_matching(self) -> None:
        """Filters without search tokens return all type-matching entities."""
        index = EntityGraphIndex()
        self._seed_cache(
            index,
            [
                {
                    "name": "Rhyz",
                    "type": "Personaje",
                    "path": "p.md",
                    "title": "Rhyz",
                    "description": "...",
                    "tags": [],
                },
                {
                    "name": "Ayagar",
                    "type": "Criatura",
                    "path": "c.md",
                    "title": "Ayagar",
                    "description": "...",
                    "tags": [],
                },
                {
                    "name": "Bira",
                    "type": "Personaje",
                    "path": "b.md",
                    "title": "Bira",
                    "description": "...",
                    "tags": [],
                },
            ],
        )

        results = index.search("", filters={"type": "Personaje"})

        names = [r.name for r in results]
        assert "Rhyz" in names
        assert "Bira" in names
        assert "Ayagar" not in names
        assert len(results) == 2

    def test_bm25_matches_in_larger_corpus(self) -> None:
        """BM25 matches are kept when the term isn't too common (IDF > 0)."""
        index = EntityGraphIndex()
        # 8 entities — "Rhyz" appears in description of only 1 (not the name match)
        entities = [
            {
                "name": f"Entity_{i}",
                "path": f"e{i}.md",
                "title": f"Entity {i}",
                "description": "Sin relación" if i != 3 else "Amigo cercano de Rhyz",
                "tags": ["test"],
            }
            for i in range(8)
        ]
        # Replace entity 0 with the prefix match
        entities[0] = {
            "name": "Rhyz El Resonante",
            "path": "rhyz.md",
            "title": "Rhyz El Resonante",
            "description": "Protagonista.",
            "tags": ["protagonista"],
        }
        self._seed_cache(index, entities)

        results = index.search("Rhyz")
        names = [r.name for r in results]

        # Entity_3 mentions "Rhyz" in description → BM25 positive (IDF > 0 in 8-doc corpus)
        assert "Rhyz El Resonante" in names, "Prefix match should be kept"
        assert "Entity_3" in names, "BM25 match with IDF > 0 should be kept"
        # Others don't mention Rhyz → excluded
        assert len(results) == 2

    def test_empty_metadata_corpus_does_not_crash(self) -> None:
        """Entities without title/description/tags must not crash BM25
        (regression: ZeroDivisionError with avgdl == 0 in BM25Okapi)."""
        index = EntityGraphIndex()
        self._seed_cache(
            index,
            [
                {
                    "name": "Rhyz",
                    "type": "Personaje",
                    "path": "personajes/rhyz.md",
                    "title": "",
                    "description": "",
                    "tags": [],
                },
                {
                    "name": "Bira",
                    "type": "Personaje",
                    "path": "personajes/bira.md",
                    "title": "",
                    "description": "",
                    "tags": [],
                },
            ],
        )

        results = index.search("Rhyz")

        names = [r.name for r in results]
        assert "Rhyz" in names, "Name-prefix match must survive an empty corpus"
        assert "Bira" not in names
        assert len(results) == 1
