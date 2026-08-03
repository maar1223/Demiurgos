# -*- coding: utf-8 -*-
"""Minimal Demiurgos Wiki API server - serves world list, files, and entity graph."""
import asyncio
import logging
import os
import sys
from pathlib import Path

import httpx

# Ensure wiki package is importable
_HERE = Path(__file__).resolve().parent
_SUITE = _HERE.parent
if str(_SUITE) not in sys.path:
    sys.path.insert(0, str(_SUITE))

import uvicorn
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger("demiurgos-api")

app = FastAPI(title="Demiurgos Wiki API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[4]  # Demiurgos/ (wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> root)
MUNDOS_DIR = PROJECT_ROOT / "mundos"


def _list_worlds() -> list[dict]:
    """List available worlds in mundos/ (skip Ideas, hidden dirs)."""
    worlds = []
    if not MUNDOS_DIR.is_dir():
        return worlds
    for entry in sorted(MUNDOS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith(".") or entry.name.startswith("_"):
            continue
        if entry.name == "Ideas":
            continue
        # Count files in lore + personajes
        lore_count = len(list((entry / "lore").rglob("*.md"))) if (entry / "lore").is_dir() else 0
        char_count = len(list((entry / "personajes").rglob("*.md"))) if (entry / "personajes").is_dir() else 0
        sagas_count = len(list((entry / "sagas").rglob("*.md"))) if (entry / "sagas").is_dir() else 0
        worlds.append({
            "name": entry.name,
            "path": str(entry),
            "lore_count": lore_count,
            "character_count": char_count,
            "saga_count": sagas_count,
        })
    return worlds


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/worlds")
async def get_worlds():
    """List all available narrative worlds."""
    worlds = _list_worlds()
    logger.info("GET /api/worlds -> %d worlds", len(worlds))
    return worlds


@app.get("/health")
async def health():
    return {"status": "ok", "worlds_available": bool(_list_worlds())}


# ---------------------------------------------------------------------------
# File tree & content endpoints
# ---------------------------------------------------------------------------

VALID_SECTIONS = {"lore", "personajes", "sagas", "referencias"}


def _resolve_path(mundo: str, section: str, path: str) -> Path | None:
    """Resolve a file path safely (prevent path traversal)."""
    mundo_dir = MUNDOS_DIR / mundo
    if not mundo_dir.is_dir():
        return None
    if section not in VALID_SECTIONS:
        return None
    # Prevent path traversal
    try:
        full = (mundo_dir / section / path).resolve()
        if not str(full).startswith(str(mundo_dir.resolve())):
            return None
    except Exception:
        return None
    return full if full.exists() else None


@app.get("/api/{mundo}/{section}/tree")
async def get_tree(mundo: str, section: str):
    """List files in a section as a tree structure."""
    if section not in VALID_SECTIONS:
        return []
    mundo_dir = MUNDOS_DIR / mundo
    if not mundo_dir.is_dir():
        return []
    section_dir = mundo_dir / section
    if not section_dir.is_dir():
        return []
    
    def _build_tree(dir_path: Path, base: Path) -> list[dict]:
        items = []
        try:
            for entry in sorted(dir_path.iterdir()):
                if entry.name.startswith(".") or entry.name.startswith("_"):
                    continue
                rel = entry.relative_to(base)
                if entry.is_file() and entry.suffix.lower() in (
                    ".md", ".txt", ".json",
                    ".jpg", ".jpeg", ".png", ".gif", ".webp",
                ):
                    items.append({
                        "name": entry.name,
                        "path": str(rel),
                        "is_dir": False,
                    })
                elif entry.is_dir():
                    children = _build_tree(entry, base)
                    if children:  # Only include dirs with files
                        items.append({
                            "name": entry.name,
                            "path": str(rel),
                            "is_dir": True,
                            "children": children,
                        })
        except PermissionError:
            pass
        return items
    
    tree = _build_tree(section_dir, section_dir)
    logger.info("GET /api/%s/%s/tree -> %d items", mundo, section, len(tree))
    return tree


@app.get("/api/{mundo}/{section}/file")
async def get_file(mundo: str, section: str, path: str):
    """Read a file's content."""
    full = _resolve_path(mundo, section, path)
    if full is None:
        return {"error": "Archivo no encontrado", "path": path}
    try:
        content = full.read_text(encoding="utf-8")
        return {
            "path": path,
            "content": content,
            "size": len(content),
        }
    except Exception as e:
        return {"error": str(e), "path": path}


@app.post("/api/{mundo}/{section}/file")
async def save_file(mundo: str, section: str, path: str, body: dict):
    """Save file content."""
    if section not in VALID_SECTIONS:
        return {"error": "SecciÃƒÂ³n invÃƒÂ¡lida"}
    mundo_dir = MUNDOS_DIR / mundo
    if not mundo_dir.is_dir():
        return {"error": "Mundo no encontrado"}
    full = (mundo_dir / section / path).resolve()
    if not str(full).startswith(str(mundo_dir.resolve())):
        return {"error": "Path traversal detectado"}
    try:
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(body.get("content", ""), encoding="utf-8")
        return {"success": True, "path": path}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/{mundo}/{section}/create")
async def create_file(mundo: str, section: str, path: str, body: dict):
    """Create a new file."""
    if section not in VALID_SECTIONS:
        return {"error": "SecciÃƒÂ³n invÃƒÂ¡lida"}
    mundo_dir = MUNDOS_DIR / mundo
    if not mundo_dir.is_dir():
        return {"error": "Mundo no encontrado"}
    full = (mundo_dir / section / path).resolve()
    if not str(full).startswith(str(mundo_dir.resolve())):
        return {"error": "Path traversal detectado"}
    if full.exists():
        return {"error": "El archivo ya existe"}
    try:
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(body.get("content", ""), encoding="utf-8")
        return {"success": True, "path": path}
    except Exception as e:
        return {"error": str(e)}


@app.delete("/api/{mundo}/{section}/file")
async def delete_file(mundo: str, section: str, path: str):
    """Delete a file."""
    full = _resolve_path(mundo, section, path)
    if full is None:
        return {"error": "Archivo no encontrado"}
    try:
        full.unlink()
        return {"success": True, "path": path}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Graph endpoints
# ---------------------------------------------------------------------------

# Lazy-initialized graph index per world (built on first request)
_graph_indices: dict[str, "EntityGraphIndex"] = {}


def _get_graph(mundo: str) -> "EntityGraphIndex | None":
    """Get or build the entity graph index for a world. Returns None if world missing."""
    mundo_dir = MUNDOS_DIR / mundo
    if not mundo_dir.is_dir():
        return None

    if mundo not in _graph_indices:
        # Lazy import to avoid relative-import issues when running as __main__
        from wiki.graph_indexer import EntityGraphIndex  # type: ignore[import-untyped]

        idx = EntityGraphIndex(MUNDOS_DIR)
        count = idx.build(mundo)
        logger.info("Graph built for '%s': %d entities", mundo, count)
        _graph_indices[mundo] = idx

    return _graph_indices[mundo]


def _resolve_entity_path(idx: "EntityGraphIndex", name: str) -> str | None:
    """Resolve an entity display name to its graph path. Returns None if not found."""
    hits = idx.search(name)
    for hit in hits:
        if hit.name.lower() == name.lower():
            return hit.path
    # Fallback: return first hit if name is a prefix match
    if hits:
        return hits[0].path
    return None


@app.get("/api/{mundo}/graph/search")
async def graph_search(
    mundo: str,
    q: str = Query(default="", description="Search query"),
    type: str | None = Query(default=None, description="Filter by entity type"),
):
    """Fuzzy search entities in the knowledge graph."""
    idx = _get_graph(mundo)
    if idx is None:
        return []

    filters: dict = {}
    if type:
        filters["type"] = type

    hits = idx.search(q, filters) if q.strip() or filters else idx.search("*") or []
    return [
        {
            "name": h.name,
            "type": h.type,
            "path": h.path,
            "title": h.title,
            "description": h.description,
            "tags": h.tags,
            "link_count": h.link_count,
            "score": h.score,
        }
        for h in hits
    ]


@app.get("/api/{mundo}/graph/entity")
async def graph_entity(
    mundo: str,
    name: str = Query(..., description="Entity display name"),
):
    """Get full entity detail by name."""
    idx = _get_graph(mundo)
    if idx is None:
        return {"error": "Mundo no encontrado"}

    path = _resolve_entity_path(idx, name)
    if path is None:
        return {"error": "Entidad no encontrada", "name": name}

    detail = idx.get_entity(path)
    if detail is None:
        return {"error": "Entidad no encontrada", "name": name}

    return {
        "name": detail.name,
        "type": detail.type,
        "path": detail.path,
        "content": detail.content,
        "forward_links": detail.forward_links,
        "backlinks": detail.backlinks,
        "relaciones": detail.relaciones,
    }


@app.get("/api/{mundo}/graph/links")
async def graph_links(
    mundo: str,
    name: str | None = Query(default=None, description="Entity display name"),
    kind: str = Query(default="forward", description="Link kind: forward, backlinks, hubs, etc."),
):
    """Get entity connections from the knowledge graph."""
    idx = _get_graph(mundo)
    if idx is None:
        return []

    entity_path: str | None = None
    if name:
        entity_path = _resolve_entity_path(idx, name)

    # For kinds that require an entity but it wasn't found
    if kind in ("backlinks", "forward", "suggest") and entity_path is None and name:
        return []

    try:
        links = idx.get_links(entity_path, kind)
    except ValueError:
        return []

    return links


@app.get("/api/{mundo}/graph/status")
async def graph_status(mundo: str):
    """Get graph indexing status and stats."""
    idx = _get_graph(mundo)
    if idx is None:
        return {"node_count": 0, "link_count": 0, "indexed": False}

    with idx._lock:
        entities = idx._cache.get("entities", {})
        node_count = len(entities)
        link_count = sum(
            len(e.get("forward_links", [])) + len(e.get("backlinks", []))
            for e in entities.values()
        )

    return {
        "node_count": node_count,
        "link_count": link_count,
        "indexed": node_count > 0,
    }


# ---------------------------------------------------------------------------
# AI Assistant — delegates to Hermes Agent Gateway (persistent daemon)
# ---------------------------------------------------------------------------

def _load_project_env(name: str) -> str:
    """Read a value from the project .env (gitignored) — secrets never live in code."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.is_file():
        return ""
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


_GATEWAY_URL = os.getenv("HERMES_GATEWAY_URL", "http://127.0.0.1:8642/v1/chat/completions")
_GATEWAY_KEY = os.getenv("HERMES_GATEWAY_KEY") or _load_project_env("HERMES_GATEWAY_KEY")
_GATEWAY_TIMEOUT = int(os.getenv("HERMES_GATEWAY_TIMEOUT", "300"))

_hermes_client: httpx.AsyncClient | None = None


def _get_hermes_client() -> httpx.AsyncClient:
    global _hermes_client
    if _hermes_client is None:
        _hermes_client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {_GATEWAY_KEY}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(_GATEWAY_TIMEOUT, connect=10.0),
        )
    return _hermes_client

class ChatRequest(BaseModel):
    messages: list[dict]
    mundo: str = ""
    session_id: str = ""

class AskRequest(BaseModel):
    prompt: str
    session_id: str = ""

@app.post("/api/chat")
async def chat_endpoint(body: ChatRequest):
    """Send messages to Hermes Agent and return the response."""
    # Send ONLY the latest user message. Session continuity is handled by the
    # gateway via X-Hermes-Session-Id (opt-in), so we never re-send history
    # as prompt text — that bloats the context window every turn.
    user_msg = body.messages[-1]["content"] if body.messages else ""
    if body.mundo:
        user_msg = f"[Mundo: {body.mundo}]\n\n{user_msg}"
    result = await _run_hermes(user_msg, session_id=body.session_id)
    return {"content": result}

@app.post("/api/{mundo}/ai/ask")
async def ai_ask_endpoint(mundo: str, body: AskRequest):
    """Endpoint for the AI Assistant sidebar."""
    prompt = f"[Mundo: {mundo}]\n\n{body.prompt}" if mundo else body.prompt
    response = await _run_hermes(prompt, session_id=body.session_id)
    logger.info("ai_ask: %s", response[:120])
    return {"response": response}

async def _run_hermes(prompt: str, session_id: str = "") -> str:
    """Send prompt to Hermes Gateway via HTTP (OpenAI-compatible chat completions)."""
    import time
    t0 = time.monotonic()
    logger.info("Hermes GW START len=%d session=%s preview=%r", len(prompt), session_id or "-", prompt[:120].replace("\n", " "))
    try:
        client = _get_hermes_client()
        payload = {
            "model": "hermes-agent",
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {}
        if session_id:
            # Opt-in session continuity: gateway keeps the conversation state.
            headers["X-Hermes-Session-Id"] = session_id
        resp = await client.post(_GATEWAY_URL, json=payload, headers=headers)
        elapsed = time.monotonic() - t0
        if resp.status_code != 200:
            logger.error("Hermes GW HTTP %d %.1fs: %s", resp.status_code, elapsed, resp.text[:500])
            return f"Error: HTTP {resp.status_code}"
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "") if "choices" in data else str(data)
        logger.info("Hermes GW DONE %.1fs len=%d preview=%r", elapsed, len(content), content[:200].replace("\n", " "))
        return content or "Error: empty response"
    except httpx.ConnectError:
        logger.error("Hermes GW UNREACHABLE — is gateway running on %s?", _GATEWAY_URL)
        return "Error: Hermes Gateway no responde. ¿Está corriendo `hermes gateway run`?"
    except httpx.TimeoutException:
        logger.error("Hermes GW TIMEOUT after %.1fs", time.monotonic() - t0)
        return f"Error: timeout ({_GATEWAY_TIMEOUT}s)"
    except Exception as exc:
        logger.exception("Hermes GW CRASH: %s", exc)
        return f"Error: {exc}"

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    logger.info("Starting Demiurgos Wiki API on port %d", port)
    logger.info("Mundos dir: %s (exists=%s)", MUNDOS_DIR, MUNDOS_DIR.is_dir())
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
