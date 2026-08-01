"""
Demiurgos Graph MCP Server — standalone stdio MCP server wrapping GraphMCPAdapter.

Usage::

    python graph_mcp_server.py --mundo vibrantes --mundos-path mundos

Hermes connects via the demiurgos-mcp profile and gains 4 graph tools:
  - graph_search(query, type?, tag?)  → {matches: [...], query}
  - graph_read(entity_path)           → {entity: {...}, exists: bool}
  - graph_links(entity_path?, kind)   → {links: [...], kind}
  - graph_status()                    → {entity_count, dirty, last_build}
"""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the wiki package is importable from its parent directory.
# graph_indexer.py and mcp_adapter.py use relative imports (e.g.
# "from .graph_models import ...") which require the "wiki" package context.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PARENT_DIR = _SCRIPT_DIR.parent  # demiurgos-suite/
if str(_PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(_PARENT_DIR))

from wiki.graph_indexer import EntityGraphIndex   # noqa: E402
from wiki.mcp_adapter import GraphMCPAdapter      # noqa: E402

from mcp.server.fastmcp import FastMCP             # noqa: E402

# ---------------------------------------------------------------------------
# Module-level MCP server instance — tools are registered on this object.
# Initialisation (index build, adapter wiring) happens in init().
# ---------------------------------------------------------------------------
mcp = FastMCP("demiurgos-graph")
_adapter: GraphMCPAdapter | None = None
_index: EntityGraphIndex | None = None


def init(mundo: str, mundos_path: str | Path) -> tuple[int, str | None]:
    """Initialise the entity graph index, build it, and wire the adapter.

    Returns (entity_count, error_message).  error_message is None on success.
    Must be called before the MCP server starts accepting connections.
    """
    global _adapter, _index

    _mundos_path = Path(mundos_path).resolve()
    _index = EntityGraphIndex(_mundos_path)
    _count = _index.build(mundo)
    print(
        f"[demiurgos-graph] Indexed {_count} entities from mundo '{mundo}'",
        file=sys.stderr,
    )

    # Start file watcher for live updates (non-critical — continues if watchdog missing)
    try:
        _index.start_watch(mundo)
        print("[demiurgos-graph] File watcher started", file=sys.stderr)
    except ImportError:
        print("[demiurgos-graph] watchdog not installed — file watching disabled", file=sys.stderr)

    _adapter = GraphMCPAdapter(_index)
    return _count, None


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def graph_search(query: str, type: str = "", tag: str = "") -> dict:
    """Search the entity graph by name, title, description, and tags.

    Returns matches sorted by relevance score.  Use this tool first to
    locate entities before calling graph_read for full content.
    """
    filters: dict = {}
    if type:
        filters["type"] = type
    if tag:
        filters["tag"] = tag
    assert _adapter is not None, "graph_mcp_server.init() must be called before tools"
    return _adapter.tool_search(query, filters)


@mcp.tool()
def graph_read(entity_path: str) -> dict:
    """Read a full entity by its path, including content and all links.

    Returns the entity with content, forward_links, backlinks, relaciones,
    and word count.  If the entity does not exist, returns {exists: false}.
    """
    assert _adapter is not None, "graph_mcp_server.init() must be called before tools"
    return _adapter.tool_read(entity_path)


@mcp.tool()
def graph_links(entity_path: str = "", kind: str = "backlinks") -> dict:
    """Query the link graph for an entity.

    kind values:
      - backlinks   — entities that link TO entity_path (default)
      - forward     — entities that entity_path links TO
      - dead        — wikilinks that do not resolve to any entity
      - orphans     — entities with no incoming AND no outgoing links
      - hubs        — top 20 entities with the most total links
      - suggest     — entities sharing tags with entity_path but NOT linked
    """
    ep: str | None = entity_path if entity_path else None
    assert _adapter is not None, "graph_mcp_server.init() must be called before tools"
    return _adapter.tool_links(ep, kind)


@mcp.tool()
def graph_status() -> dict:
    """Return current index health metrics.

    Includes entity_count, dirty flag (unsaved changes since last build),
    and last_build timestamp (ISO 8601).
    """
    assert _adapter is not None, "graph_mcp_server.init() must be called before tools"
    return _adapter.tool_status()


# ---------------------------------------------------------------------------
# CLI entry point (only invoked when run as a script, never on import)
# ---------------------------------------------------------------------------


def _shutdown(signum: int, frame: object) -> None:
    print("\n[demiurgos-graph] Shutting down...", file=sys.stderr)
    if _index is not None:
        _index.stop_watch()
    sys.exit(0)


def main() -> None:
    """Parse CLI args, initialise the index, and start the MCP stdio server."""
    parser = argparse.ArgumentParser(
        description="Demiurgos Graph MCP Server — exposes entity graph tools via MCP stdio",
    )
    parser.add_argument(
        "--mundo",
        required=True,
        help="World name to index (e.g. vibrantes)",
    )
    parser.add_argument(
        "--mundos-path",
        required=True,
        help="Path to the mundos/ directory (relative or absolute)",
    )
    args = parser.parse_args()

    init(args.mundo, args.mundos_path)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
