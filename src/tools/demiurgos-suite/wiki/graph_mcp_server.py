"""
Demiurgos MCP Server — standalone stdio MCP server wrapping GraphMCPAdapter.

Usage::

    python graph_mcp_server.py --mundo vibrantes --mundos-path mundos
    python graph_mcp_server.py --mundo vibrantes --mundos-path mundos --no-engram

Hermes connects via the demiurgos-mcp profile and gains 13 tools.
Every tool accepts an optional ``mundo`` parameter (defaults to the world
configured at launch) so the UI can query whichever world is active:
  - graph_search(query, type?, tag?, mundo?)  → {matches: [...], query}
  - graph_read(entity_path, mundo?)           → {entity: {...}, exists: bool}
  - graph_links(entity_path?, kind, mundo?)   → {links: [...], kind}
  - graph_status(mundo?)                      → {entity_count, dirty, last_build}
  - graph_rebuild(mundo?)                     → {entity_count, rebuilt}
  - lore_search(query, mundo?)                → {graph_matches, engram_matches}
  - lore_conflicts(entity_path, mundo?)       → {conflicts, entity_path}
  - lore_format(data)                         → str (markdown with [[wikilinks]])
  - auto_tag(text, mundo)                     → {entities, themes}
  - idea_link(content, mundo)                 → {matches, content}

Idea-bank tools (world-agnostic, global ``ideas/`` bank — no mundo needed):
  - ideas_list(tag?, status?)                 → {ideas: [IdeaSummary, ...]}
  - ideas_read(slug)                          → {idea: {...}, exists: bool}
  - ideas_search(query)                       → {matches: [IdeaSummary, ...], query}
  - update_idea(slug, body?, title?, tags?, type?, media_path?) → {slug, version, previous_version, archived_at}
  - idea_history(slug)                        → {slug, versions: [{version, path}]}
  - pending_list()                            → {captures: [...], count: int}
"""

from __future__ import annotations

import argparse
import mimetypes
import re
import signal
import sqlite3
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
from wiki.ideas_bank import IdeaNotFound, IdeasBank, InvalidIdea  # noqa: E402
from wiki import data_root                         # noqa: E402

from mcp.server.fastmcp import FastMCP             # noqa: E402

# ---------------------------------------------------------------------------
# Module-level MCP server instance — tools are registered on this object.
# Initialisation (index build, adapter wiring) happens in init().
# ---------------------------------------------------------------------------
mcp = FastMCP("demiurgos-mcp")
_adapter: GraphMCPAdapter | None = None
_index: EntityGraphIndex | None = None
_engram_enabled: bool = True
_engram_cmd: str = "engram"


def init(
    mundo: str,
    mundos_path: str | Path,
    engram_enabled: bool = True,
    engram_cmd: str = "engram",
) -> tuple[int, str | None]:
    """Initialise the entity graph index and wire the adapter.

    The index build is deliberately LAZY: it runs on first tool use (via
    ``GraphMCPAdapter._index_for``), not here. Building synchronously at
    startup delays the stdio handshake by ~1s, which makes Hermes' gateway
    lose the initial MCP connection ("connection closed"). An empty
    ``entity_count`` is expected until the first query.

    Returns (entity_count, error_message).  error_message is None on success.
    Must be called before the MCP server starts accepting connections.
    """
    global _adapter, _index, _engram_enabled, _engram_cmd

    _mundos_path = Path(mundos_path).resolve()
    _engram_enabled = engram_enabled
    _engram_cmd = engram_cmd
    _index = EntityGraphIndex(_mundos_path)

    _adapter = GraphMCPAdapter(
        _index,
        mundos_path=mundos_path,
        project=mundo,
        engram_enabled=_engram_enabled,
        engram_cmd=_engram_cmd,
    )
    if _engram_enabled:
        print("[demiurgos-mcp] Engram integration enabled", file=sys.stderr)
    else:
        print("[demiurgos-mcp] Engram integration disabled", file=sys.stderr)

    return _index.entity_count, None


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def graph_search(query: str, type: str = "", tag: str = "", mundo: str = "") -> dict:
    """Search the entity graph by name, title, description, and tags.

    Returns matches sorted by relevance score.  Use this tool first to
    locate entities before calling graph_read for full content.
    ``mundo`` defaults to the active world; pass another world name to
    search that world. When you return results, tell the user which world
    they came from.
    """
    filters: dict = {}
    if type:
        filters["type"] = type
    if tag:
        filters["tag"] = tag
    assert _adapter is not None, "graph_mcp_server.init() must be called before tools"
    return _adapter.tool_search(query, filters, mundo)


@mcp.tool()
def graph_read(entity_path: str, mundo: str = "") -> dict:
    """Read a full entity by its exact filesystem path.

    The required argument ``entity_path`` must be the ``path`` field returned
    by graph_search (e.g. "lore/ayagars-reptiles-vibrantes/entity.md").  Do
    NOT pass the display title, the name, or a "Parent::Name" reference — they
    will not resolve.  Returns the entity with content, forward_links,
    backlinks, relaciones, and word count; {exists: false} when not found.
    ``mundo`` defaults to the active world; pass another world to read that
    world.  When you return results, tell the user which world they came from.
    """
    assert _adapter is not None, "graph_mcp_server.init() must be called before tools"
    return _adapter.tool_read(entity_path, mundo)


@mcp.tool()
def graph_links(entity_path: str = "", kind: str = "backlinks", mundo: str = "") -> dict:
    """Query the link graph for an entity.

    kind values:
      - backlinks   — entities that link TO entity_path (default)
      - forward     — entities that entity_path links TO
      - dead        — wikilinks that do not resolve to any entity
      - orphans     — entities with no incoming AND no outgoing links
      - hubs        — top 20 entities with the most total links
      - suggest     — entities sharing tags with entity_path but NOT linked

    ``mundo`` defaults to the active world; pass another world name to
    query that world. When you return results, tell the user which world
    they came from.
    """
    ep: str | None = entity_path if entity_path else None
    assert _adapter is not None, "graph_mcp_server.init() must be called before tools"
    return _adapter.tool_links(ep, kind, mundo)


@mcp.tool()
def graph_status(mundo: str = "") -> dict:
    """Return current index health metrics.

    Includes entity_count, dirty flag (unsaved changes since last build),
    and last_build timestamp (ISO 8601).
    ``mundo`` is the world to query (optional; defaults to the configured world).
    """
    assert _adapter is not None, "graph_mcp_server.init() must be called before tools"
    return _adapter.tool_status(mundo)


@mcp.tool()
def graph_rebuild(mundo: str = "") -> dict:
    """Force a full index rebuild from disk. Use when graph_status reports dirty=true
    or when files have been modified externally and the file watcher missed them.

    Returns the new entity count and build timestamp.
    ``mundo`` is the world to rebuild (optional; defaults to the configured world).
    """
    assert _adapter is not None, "graph_mcp_server.init() must be called before tools"
    return _adapter.tool_rebuild(mundo)


# ---------------------------------------------------------------------------
# Narrative tools (TG-01 through TG-05)
# ---------------------------------------------------------------------------


@mcp.tool()
def lore_search(query: str, mundo: str = "") -> dict:
    """Search both the entity graph and Engram persistent memory.

    Returns graph_matches (from the entity index) and engram_matches
    (from Engram memory), each tagged with a source field.
    Use this to find entities and related memories in one call.
    ``mundo`` defaults to the active world; pass another world name to
    search that world. When you return results, tell the user which world
    they came from.
    """
    assert _adapter is not None, "graph_mcp_server.init() must be called before tools"
    return _adapter.tool_lore_search(query, mundo)


@mcp.tool()
def lore_conflicts(entity_path: str, mundo: str = "") -> dict:
    """Detect contradictions between an entity's content and Engram memory.

    Compares structured claims (dates, status, names, relationships)
    from the entity file against Engram observations. Returns a list of
    conflicts with claim_a, source_a, claim_b, source_b, and conflict_type.
    Empty conflicts list = no contradictions found.
    ``mundo`` is the world to query (optional; defaults to the configured world).
    """
    assert _adapter is not None, "graph_mcp_server.init() must be called before tools"
    return _adapter.tool_lore_conflicts(entity_path, mundo)


@mcp.tool()
def lore_format(data: dict) -> str:
    """Format lore data into clean markdown with [[wikilinks]].

    Accepts a dict with optional entity, engram, and conflicts keys.
    Returns a deterministic markdown string. Empty sections omitted.
    Pure string templating — zero LLM/API calls.
    """
    assert _adapter is not None, "graph_mcp_server.init() must be called before tools"
    return _adapter.tool_lore_format(data)


@mcp.tool()
def auto_tag(text: str, mundo: str) -> dict:
    """Analyse text for known entity mentions and themes.

    Entity names are resolved to canonical names from the entity graph.
    Themes are extracted via keyword matching against a curated taxonomy
    of 30 narrative themes (entrenamiento, batalla, traicion, etc.).
    """
    assert _adapter is not None, "graph_mcp_server.init() must be called before tools"
    return _adapter.tool_auto_tag(text, mundo)


@mcp.tool()
def idea_link(content: str, mundo: str) -> dict:
    """Search the Idea Bank for similar ideas using BM25.

    Scans mundos/{mundo}/Ideas/ for YAML frontmatter + body files and
    ranks by BM25Okapi similarity. Returns matches with slug, score,
    and a preview of the first 80 characters. Minimum score threshold: 0.3.
    """
    assert _adapter is not None, "graph_mcp_server.init() must be called before tools"
    return _adapter.tool_idea_link(content, mundo)


# ---------------------------------------------------------------------------
# Idea-bank tools (R-5) — world-agnostic access to the global `ideas/` bank.
# Each instantiates IdeasBank() (defaults to `<project>/ideas` via
# `_project_root()`); no `mundo` parameter is needed. List/search return
# IdeaSummary objects (body omitted, S-3.1/S-3.3); read returns the full
# idea including body (S-3.2). Frontmatter is never leaked: to_dict() only
# exposes parsed fields, never raw YAML (S-4.1).
# ---------------------------------------------------------------------------


@mcp.tool()
def ideas_list(tag: str = "", status: str = "") -> dict:
    """List ideas from the global bank, optionally filtered by tag/status.

    Returns {ideas: [IdeaSummary, ...]} where IdeaSummary has no body field.
    ``tag`` matches an exact tag in the idea's tag list; ``status`` filters
    by idea status (fresh|used).
    """
    bank = IdeasBank()
    ideas = bank.list(status=status or None)
    if tag:
        ideas = [idea for idea in ideas if tag in idea.tags]
    return {"ideas": [idea.to_summary() for idea in ideas]}


@mcp.tool()
def ideas_read(slug: str) -> dict:
    """Read a full idea by slug from the global bank.

    Returns {idea: Idea, exists: true} or {exists: false} when the slug does
    not exist. The idea dict includes the body field (S-3.2) but never the
    raw YAML frontmatter (S-4.1).
    """
    bank = IdeasBank()
    try:
        idea = bank.read(slug)
    except IdeaNotFound:
        return {"exists": False}
    return {"idea": idea.to_dict(), "exists": True}


@mcp.tool()
def ideas_search(query: str) -> dict:
    """Search ideas by substring match in body and tags (case-insensitive).

    Returns {matches: [IdeaSummary, ...], query}. Matches an idea when the
    lowercased query appears in its lowercased body or in any of its tags.
    Summaries omit the body field (S-3.3).
    """
    bank = IdeasBank()
    lowered = query.lower()
    matches = [
        idea
        for idea in bank.list()
        if lowered in idea.body.lower()
        or any(lowered in tag.lower() for tag in idea.tags)
    ]
    return {"matches": [idea.to_summary() for idea in matches], "query": query}


@mcp.tool()
def update_idea(slug: str, body: str = "", title: str = "", tags: list[str] = [], type: str = "", media_path: str = "") -> dict:
    """Update an existing idea, creating a new version (S-6.1, R-6).

    Text updates delegate to ``IdeasBank.update_versioned()``: the current
    ``ideas/{slug}.md`` is archived to ``ideas/versions/{slug}-vN.md`` and the
    live file gets the next filesystem-derived version. When ``media_path`` is
    given, the local image is attached via ``IdeasBank.attach_media()`` — the
    bytes are copied to ``ideas/media/``, ``media_path`` is recorded and the
    embed is prepended (still versioned). The tool never deletes; the
    ``version`` is derived from the core, never passed by the caller. Returns
    ``{slug, version, previous_version, archived_at}``.
    """
    bank = IdeasBank()
    partial: dict = {}
    if body:
        partial["body"] = body
    if title:
        partial["title"] = title
    if tags:
        partial["tags"] = tags
    if type:
        partial["type"] = type
    try:
        if media_path:
            try:
                image_bytes = Path(media_path).read_bytes()
            except OSError as exc:
                return {"error": f"cannot read media {media_path}: {exc}"}
            ext = Path(media_path).suffix.lower()
            mime = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }.get(ext)
            if mime is None:
                mime, _ = mimetypes.guess_type(media_path)
                if mime is None:
                    mime = "image/jpeg"
            updated = bank.attach_media(slug, image_bytes, mime, partial or None)
        else:
            updated = bank.update_versioned(slug, partial)
    except IdeaNotFound:
        return {"error": f"idea '{slug}' not found"}
    except InvalidIdea as exc:
        return {"error": str(exc)}
    previous_version = updated.version - 1
    return {
        "slug": slug,
        "version": updated.version,
        "previous_version": previous_version,
        "archived_at": bank._archive_path(slug, previous_version).as_posix(),
    }


@mcp.tool()
def idea_history(slug: str) -> dict:
    """List an idea's archived versions ascending by version number (R-3).

    Delegates to ``IdeasBank._versions_for()``. Returns
    ``{slug, versions: [{version, path}]}``; an empty list when no archive
    exists for the slug.
    """
    bank = IdeasBank()
    versions = [
        {"version": int(match.group(1)), "path": path.as_posix()}
        for path in bank._versions_for(slug)
        for match in [re.search(r"-v(\d+)\.md$", path.name)]
        if match
    ]
    return {"slug": slug, "versions": versions}


# ---------------------------------------------------------------------------
# Pending-capture queue — read-only view of the shared idea-capture SQLite.
# The parked-capture queue is owned by the idea_capture runtime (Telegram
# keyboard / web panel). This server reads the SQLite directly instead of
# importing the heavy idea_capture package (its __init__ pulls the whole
# adapter/runtime/service chain).
# ---------------------------------------------------------------------------

# Mirrors idea_capture.models.CaptureState.AWAITING_CONFIRM; kept as a literal
# so this server does not import the heavy idea_capture package.
_PENDING_STATE = "AWAITING_CONFIRM"


def _pending_state_path() -> Path:
    """Resolve the shared idea-capture SQLite path from the data root.

    Uses the same resolver ``IdeasBank`` relies on in this process, so the MCP
    server and the capture runtime agree on ``<data root>/data/...``.
    """
    return data_root.resolve_data_root() / "data" / "idea-capture.sqlite3"


@mcp.tool()
def pending_list() -> dict:
    """List captures parked in AWAITING_CONFIRM (the Taller de Ideas review queue).

    Read-only view of the shared idea-capture SQLite state. Returns
    {captures: [{capture_id, slug, raw_text, created_at, event_ts, media_kind}],
    count: N} ordered oldest-first. An absent database returns an empty list;
    a read failure returns an empty list plus an ``error`` field (never raises).
    """
    conn: sqlite3.Connection | None = None
    try:
        # Resolve inside the guard: an unconfigured data root raises
        # DataRootNotConfigured, which must degrade to the empty payload
        # instead of breaking the "never raises" contract.
        path = _pending_state_path()
        if not path.is_file():
            return {"captures": [], "count": 0}
        # Read-only URI so this server never writes the schema nor contends
        # with the capture runtime's writer. ``Path.as_uri()`` percent-encodes
        # metacharacters (``#``, ``%``, ``?``) that a naive f-string URI would
        # misparse.
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT capture_id, slug, raw_text, created_at, event_ts, media_kind "
            "FROM captures WHERE state=? ORDER BY created_at",
            (_PENDING_STATE,),
        ).fetchall()
        captures = [dict(row) for row in rows]
        return {"captures": captures, "count": len(captures)}
    except (data_root.DataRootNotConfigured, OSError, sqlite3.Error) as exc:
        return {"captures": [], "count": 0, "error": str(exc)}
    finally:
        if conn is not None:
            conn.close()


# ---------------------------------------------------------------------------
# CLI entry point (only invoked when run as a script, never on import)
# ---------------------------------------------------------------------------


def _shutdown(signum: int, frame: object) -> None:
    print("\n[demiurgos-mcp] Shutting down...", file=sys.stderr)
    if _index is not None:
        _index.stop_watch()
    sys.exit(0)


def main() -> None:
    """Parse CLI args, initialise the index, and start the MCP stdio server."""
    parser = argparse.ArgumentParser(
        description="Demiurgos MCP Server — exposes entity graph + narrative tools via MCP stdio",
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
    parser.add_argument(
        "--engram",
        action="store_true",
        default=True,
        dest="engram_enabled",
        help="Enable Engram integration (default: enabled)",
    )
    parser.add_argument(
        "--no-engram",
        action="store_false",
        dest="engram_enabled",
        help="Disable Engram integration — tools return empty Engram arrays",
    )
    parser.add_argument(
        "--engram-cmd",
        default="engram",
        help="Path or name of the Engram CLI binary (default: engram)",
    )
    args = parser.parse_args()

    init(args.mundo, args.mundos_path,
         engram_enabled=args.engram_enabled,
         engram_cmd=args.engram_cmd)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
