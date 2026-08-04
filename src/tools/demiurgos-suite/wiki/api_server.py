# -*- coding: utf-8 -*-
"""Minimal Demiurgos Wiki API server - serves world list, files, and entity graph."""
import asyncio
import io
import logging
import mimetypes
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Ensure wiki package is importable
_HERE = Path(__file__).resolve().parent
_SUITE = _HERE.parent
if str(_SUITE) not in sys.path:
    sys.path.insert(0, str(_SUITE))

import uvicorn
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from PIL import Image

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


def _resolve_mundo_path(mundo: str, path: str) -> Path | None:
    """Resolve a mundo-relative path safely (prevent path traversal).

    The first path segment must be a valid section (lore/personajes/sagas/
    referencias) and the resolved path must stay under ``mundos/{mundo}``.
    Returns the resolved Path even when it does not exist yet (so callers
    can distinguish 400 invalid-path from 404 not-found), or None when the
    path is invalid (traversal, bad section, empty).
    """
    mundo_dir = MUNDOS_DIR / mundo
    if not mundo_dir.is_dir():
        return None
    if not path or not path.strip():
        return None
    parts = [p for p in Path(path).parts if p not in ("", ".")]
    if not parts or parts[0] not in VALID_SECTIONS:
        return None
    try:
        full = (mundo_dir / path).resolve()
    except Exception:
        return None
    root = str(mundo_dir.resolve())
    if not (str(full) == root or str(full).startswith(root + os.sep)):
        return None
    return full


def _trash_path(mundo: str, section: str, rel_path: str) -> Path:
    """Build the trash destination for a deleted item.

    Layout: ``mundos/{mundo}/.papelera/{section}/{ts}_{rel_path}`` where
    ``ts`` is ISO 8601 with milliseconds (anti-collision for rapid
    same-name deletes), with ``:`` replaced by ``-`` and ``+`` by ``_`` so
    the name is valid on Windows. Subfolders of *rel_path* are preserved.
    """
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    ts_safe = ts.replace(":", "-").replace("+", "_")
    return MUNDOS_DIR / mundo / ".papelera" / section / f"{ts_safe}_{rel_path}"


_RE_PORTADA = re.compile(r"^portada:\s*(.+)$", re.MULTILINE)
_RE_BODY_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _resolve_cover(mundo: str, full: Path) -> str | None:
    """Resolve a cover for a markdown file.

    Reads only the first 8KB of the file (bounded cost). Prefers the
    ``portada:`` frontmatter value; soft-validates existence through the
    same media resolver as /media and falls back to the first body image
    ``![alt](ruta)`` (suffix ``#...`` stripped). Returns the value as
    written (mundo-relative) or None when no valid image is found.
    """
    try:
        with open(full, "rb") as fh:
            head = fh.read(8192)
    except OSError:
        return None
    text = head.decode("utf-8", errors="replace")

    m = _RE_PORTADA.search(text)
    if m:
        val = m.group(1).strip().strip('"').strip("'")
        if val:
            r = _resolve_media_path(mundo, val)
            if r is not None and r.is_file():
                return val

    m = _RE_BODY_IMAGE.search(text)
    if m:
        val = m.group(1).strip().split("#", 1)[0].strip()
        if val:
            r = _resolve_media_path(mundo, val)
            if r is not None and r.is_file():
                return val
    return None


def _next_duplicate_name(full: Path) -> Path:
    """Find the next free duplicate name in *full*'s directory.

    Sequence: ``{stem}-copia{ext}``, then ``{stem}-2{ext}``, ``{stem}-3{ext}``…
    until a name that does not exist yet.
    """
    stem = full.stem
    ext = full.suffix
    candidate = full.with_name(f"{stem}-copia{ext}")
    n = 2
    while candidate.exists():
        candidate = full.with_name(f"{stem}-{n}{ext}")
        n += 1
    return candidate


@app.get("/api/{mundo}/{section}/tree")
async def get_tree(mundo: str, section: str, covers: bool = Query(False)):
    """List files in a section as a tree structure.

    With ``?covers=true`` every file node carries a ``portada`` field
    (mundo-relative cover path or null); without it the field is absent
    (S29). Covers are resolved in a single sweep — no per-card requests.
    """
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
            # Directories first, then files; each group sorted
            # alphabetically, case-insensitively (e.g. "alpha" before "Zeta").
            entries = sorted(
                (
                    e for e in dir_path.iterdir()
                    if not e.name.startswith(".") and not e.name.startswith("_")
                ),
                key=lambda e: e.name.lower(),
            )
            for entry in entries:
                if not entry.is_dir():
                    continue
                rel = entry.relative_to(base)
                children = _build_tree(entry, base)
                if children:  # Only include dirs with files
                    node = {
                        "name": entry.name,
                        "path": str(rel),
                        "is_dir": True,
                        "children": children,
                    }
                    if covers:
                        node["portada"] = None
                    items.append(node)
            for entry in entries:
                if not entry.is_file():
                    continue
                if entry.suffix.lower() not in (
                    ".md", ".txt", ".json",
                    ".jpg", ".jpeg", ".png", ".gif", ".webp",
                ):
                    continue
                rel = entry.relative_to(base)
                node = {
                    "name": entry.name,
                    "path": str(rel),
                    "is_dir": False,
                }
                if covers:
                    node["portada"] = _resolve_cover(mundo, entry)
                items.append(node)
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
        raise HTTPException(status_code=400, detail="Sección inválida")
    mundo_dir = MUNDOS_DIR / mundo
    if not mundo_dir.is_dir():
        raise HTTPException(status_code=404, detail="Mundo no encontrado")
    full = (mundo_dir / section / path).resolve()
    if not str(full).startswith(str(mundo_dir.resolve())):
        raise HTTPException(status_code=400, detail="Path traversal detectado")
    try:
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(body.get("content", ""), encoding="utf-8")
        return {"success": True, "path": path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al guardar: {e}")


@app.post("/api/{mundo}/{section}/save")
async def save_file_via_save(mundo: str, section: str, path: str, body: dict):
    """Save file content — contract-compatible alias for the frontend.

    The frontend calls POST /{mundo}/{section}/save?path=... (wiki.ts
    saveFile), which was lost with the router.py backend. Same behavior
    as POST /file; kept as a distinct route so both callers work.
    """
    return await save_file(mundo, section, path, body)


@app.post("/api/{mundo}/{section}/diff")
async def diff_preview(mundo: str, section: str, path: str, body: dict):
    """Line-by-line diff between current file content and proposed content."""
    full = _resolve_path(mundo, section, path)
    original_content = ""
    if full is not None:
        try:
            original_content = full.read_text(encoding="utf-8")
        except Exception:
            original_content = ""

    new_content = body.get("content", "")
    diff_lines = _compute_diff(original_content, new_content)

    return {
        "original_path": path,
        "original_content": original_content,
        "new_content": new_content,
        "diff": diff_lines,
    }


def _compute_diff(original: str, nuevo: str) -> list[dict]:
    """Line-by-line diff between two texts (same contract as the old
    storage.compute_diff): entries {type: same|added|removed, text}."""
    import difflib

    orig_lines = original.splitlines(keepends=True)
    new_lines = nuevo.splitlines(keepends=True)

    diff_lines: list[dict] = []
    for line in difflib.unified_diff(orig_lines, new_lines, n=9999):
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("@@"):
            continue
        if line.startswith("-"):
            text = line[1:].rstrip("\n")
            diff_lines.append({"type": "removed", "text": text})
        elif line.startswith("+"):
            text = line[1:].rstrip("\n")
            diff_lines.append({"type": "added", "text": text})
        else:
            text = line.rstrip("\n")
            diff_lines.append({"type": "same", "text": text})

    # Edge case: unified_diff returns empty when files are identical.
    # Spec S22 requires all lines as type="same" for unchanged files.
    if not diff_lines and orig_lines:
        for line in orig_lines:
            diff_lines.append({"type": "same", "text": line.rstrip("\n")})

    return diff_lines


@app.post("/api/{mundo}/{section}/create")
async def create_file(mundo: str, section: str, path: str, body: dict):
    """Create a new file."""
    if section not in VALID_SECTIONS:
        raise HTTPException(status_code=400, detail="Sección inválida")
    mundo_dir = MUNDOS_DIR / mundo
    if not mundo_dir.is_dir():
        raise HTTPException(status_code=404, detail="Mundo no encontrado")
    full = (mundo_dir / section / path).resolve()
    if not str(full).startswith(str(mundo_dir.resolve())):
        raise HTTPException(status_code=400, detail="Path traversal detectado")
    if full.exists():
        raise HTTPException(status_code=409, detail="El archivo ya existe")
    try:
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(body.get("content", ""), encoding="utf-8")
        return {"success": True, "path": path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al crear: {e}")


@app.delete("/api/{mundo}/{section}/file")
async def delete_file(mundo: str, section: str, path: str):
    """Move a file or folder to the trash (``mundos/{mundo}/.papelera``).

    Never permanently deletes: ``shutil.move`` (recursive for folders)
    to ``.papelera/{section}/{ts}_{path}`` preserving relative subfolders.
    Invalidate the graph cache so the trashed entity disappears from
    graph/search. No restore in v1.
    """
    if section not in VALID_SECTIONS:
        raise HTTPException(status_code=400, detail="Sección inválida")
    if not path or not path.strip():
        raise HTTPException(status_code=400, detail="Ruta vacía")
    full = _resolve_mundo_path(mundo, f"{section}/{path}")
    if full is None:
        raise HTTPException(status_code=400, detail="Path traversal detectado")
    if not full.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    try:
        dest = _trash_path(mundo, section, path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(full), str(dest))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al mover a la papelera: {e}")
    _graph_indices.pop(mundo, None)
    return {"success": True, "path": path}


@app.post("/api/{mundo}/move")
async def move_path(mundo: str, body: dict):
    """Move or rename a file or folder to a new mundo-relative path.

    Validates ``from`` and ``to`` independently (S16), requires ``from``
    to exist (S17) and ``to`` to be free (S18), rejects moving a folder
    into itself (S19), creates parent dirs and moves recursively (S20).
    """
    from_path = body.get("from")
    to_path = body.get("to")
    if (
        not isinstance(from_path, str)
        or not isinstance(to_path, str)
        or not from_path.strip()
        or not to_path.strip()
    ):
        raise HTTPException(status_code=400, detail="Se requieren los campos 'from' y 'to'")

    full_from = _resolve_mundo_path(mundo, from_path)
    if full_from is None:
        raise HTTPException(status_code=400, detail="Ruta de origen inválida")
    if not full_from.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    full_to = _resolve_mundo_path(mundo, to_path)
    if full_to is None:
        raise HTTPException(status_code=400, detail="Ruta de destino inválida")
    if full_to.exists():
        raise HTTPException(status_code=409, detail="Ya existe un archivo o carpeta en esa ubicación")
    if str(full_to).startswith(str(full_from) + os.sep):
        raise HTTPException(status_code=400, detail="No se puede mover una carpeta dentro de sí misma")

    try:
        full_to.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(full_from), str(full_to))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al mover: {e}")

    _graph_indices.pop(mundo, None)
    return {"success": True, "path": to_path}


@app.post("/api/{mundo}/duplicate")
async def duplicate_path(mundo: str, body: dict):
    """Duplicate a file with an auto-resolved non-colliding name.

    Files only (S21); the copy name is ``{stem}-copia{ext}`` and then
    ``{stem}-2{ext}``, ``{stem}-3{ext}``… until free (S22); content is
    byte-identical via ``shutil.copy2`` (S23).
    """
    from_path = body.get("from")
    if not isinstance(from_path, str) or not from_path.strip():
        raise HTTPException(status_code=400, detail="Se requiere el campo 'from'")

    full = _resolve_mundo_path(mundo, from_path)
    if full is None:
        raise HTTPException(status_code=400, detail="Ruta inválida")
    if not full.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    if full.is_dir():
        raise HTTPException(status_code=422, detail="Solo se pueden duplicar archivos")

    try:
        new_full = _next_duplicate_name(full)
        shutil.copy2(str(full), str(new_full))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al duplicar: {e}")

    _graph_indices.pop(mundo, None)
    return {"success": True, "path": _rel_path(new_full, mundo)}


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
# Media endpoints — serve, upload, list, and delete wiki media (images)
# ---------------------------------------------------------------------------

# Allowed MIME types for upload validation
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}

# Allowed file extensions
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# Max upload size: 10 MB
MAX_UPLOAD_SIZE = 10 * 1024 * 1024


class ImageInfo(BaseModel):
    """Info about a single image file."""
    path: str
    name: str
    size_bytes: int
    extension: str
    thumbnail_path: str | None = None


class MediaList(BaseModel):
    """List of all images available in a world."""
    images: list[ImageInfo]
    total: int


class UploadResponse(BaseModel):
    """Response after uploading an image."""
    success: bool
    path: str
    size_bytes: int
    thumbnail_path: str | None = None


def _get_media_bases(mundo: str) -> list[Path]:
    """Return the two allowed media base directories for *mundo*."""
    mundo_base = MUNDOS_DIR / mundo
    return [
        mundo_base / "wiki" / "media",
        mundo_base / "referencias" / "visuales" / "imagenes",
    ]


def _resolve_media_path(mundo: str, path: str) -> Path | None:
    """Resolve a media file path with path-traversal protection.

    Accepts *path* in two formats:
      1. Relative to *mundo* root:   ``wiki/media/foto.jpg``
      2. Relative to a media base:   ``foto.jpg``

    Checks against both allowed base directories:

        mundos/{mundo}/wiki/media/
        mundos/{mundo}/referencias/visuales/imagenes/

    Returns the resolved *Path* if valid, or *None* if the path tries to
    escape the allowed directories.

    The resolver prefers existing files. If no file exists at any valid
    path it still returns the first structurally valid path so the caller
    can return a 404 instead of a 400.
    """
    mundo_base = MUNDOS_DIR / mundo
    if not mundo_base.is_dir():
        return None

    bases = _get_media_bases(mundo)

    # Collect all candidate paths (deduplicated)
    seen: set[str] = set()
    candidates: list[Path] = []
    for base in bases:
        for p in (mundo_base / path, base / path):
            resolved = p.resolve()
            key = str(resolved)
            if key not in seen:
                seen.add(key)
                candidates.append(resolved)

    # Pass 1 — return existing file first (prefer correct base)
    for full in candidates:
        for base in bases:
            base_str = str(base.resolve()) + os.sep
            if str(full).startswith(base_str) and full.is_file():
                return full

    # Pass 2 — if no existing file, return first structurally valid path
    #          (so the caller can raise 404 vs 400)
    for full in candidates:
        for base in bases:
            base_str = str(base.resolve()) + os.sep
            if str(full).startswith(base_str):
                return full

    return None


def _rel_path(full_path: Path, mundo: str) -> str:
    """Return a forward-slash path relative to mundos/{mundo}/."""
    mundo_base = MUNDOS_DIR / mundo
    return str(full_path.relative_to(mundo_base)).replace("\\", "/")


def _validate_image_file(filename: str, content_type: str) -> None:
    """Validate MIME type and extension. Raises 422 on failure."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Tipo de archivo no permitido: '{ext}'. "
                f"Permitidos: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            ),
        )
    # Only reject content_type when it is present and invalid
    if content_type and content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Tipo MIME no permitido: '{content_type}'",
        )


def _sanitize_filename(filename: str) -> str:
    """Strip path separators and truncate to 255 characters maximum."""
    name = Path(filename).name  # discards any directory components
    if not name:
        name = "uploaded_image"
    if len(name) > 255:
        stem = Path(name).stem[:250]
        ext = Path(name).suffix
        name = f"{stem}{ext}"
    return name


def compress_image(image_bytes: bytes, quality: int = 85) -> tuple[bytes, str]:
    """Compress image to JPEG. Never preserves the original format.

    Returns (compressed_bytes, extension) where extension is always '.jpg'.
    """
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue(), ".jpg"


def generate_thumbnail(image_bytes: bytes, width: int = 300) -> bytes:
    """Generate a JPEG thumbnail with the given max width (aspect ratio kept)."""
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    ratio = width / img.width
    height = int(img.height * ratio)
    img = img.resize((width, height), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75, optimize=True)
    return buf.getvalue()


@app.get("/api/{mundo}/media")
async def get_media(mundo: str, path: str = Query(..., description="Ruta relativa del archivo")):
    """Serve an image file from wiki/media/ or referencias/visuales/imagenes/."""
    full_path = _resolve_media_path(mundo, path)
    if full_path is None:
        raise HTTPException(status_code=400, detail="Path traversal detectado")
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    media_type, _ = mimetypes.guess_type(str(full_path))
    if media_type is None:
        media_type = "application/octet-stream"

    return FileResponse(path=str(full_path), media_type=media_type)


@app.post("/api/{mundo}/media/upload", response_model=UploadResponse, status_code=201)
async def upload_media(
    mundo: str,
    file: UploadFile = File(...),
    overwrite: bool = Query(False, description="Sobrescribir si el archivo ya existe"),
):
    """Upload an image file. Compresses to JPEG and generates a thumbnail."""
    # 1. Read file bytes
    image_bytes = await file.read()

    # 2. Size cap
    if len(image_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Archivo demasiado grande ({len(image_bytes)} bytes). "
                "Máximo: 10 MB"
            ),
        )

    # 3. MIME / extension validation
    _validate_image_file(file.filename or "unknown", file.content_type or "")

    # 4. Sanitise filename
    safe_name = _sanitize_filename(file.filename or "image")
    stem = Path(safe_name).stem

    # 5. Compress — NEVER save the original
    compressed_bytes, compressed_ext = compress_image(image_bytes)
    compressed_name = f"{stem}{compressed_ext}"  # e.g. photo.jpg
    thumb_name = f"{stem}_thumb{compressed_ext}"  # e.g. photo_thumb.jpg

    # 6. Build target paths
    save_dir = MUNDOS_DIR / mundo / "wiki" / "media"
    save_path = save_dir / compressed_name
    thumb_path = save_dir / thumb_name

    # 7. Conflict check
    if save_path.exists() and not overwrite:
        raise HTTPException(
            status_code=409,
            detail=(
                f"El archivo '{compressed_name}' ya existe. "
                "Usa ?overwrite=true para sobrescribir."
            ),
        )

    # 8. Write compressed image
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(compressed_bytes)

    # 9. Generate and write thumbnail
    thumb_bytes = generate_thumbnail(image_bytes)
    thumb_path.write_bytes(thumb_bytes)

    return UploadResponse(
        success=True,
        path=_rel_path(save_path, mundo),
        size_bytes=len(compressed_bytes),
        thumbnail_path=_rel_path(thumb_path, mundo),
    )


@app.get("/api/{mundo}/media/list", response_model=MediaList)
async def list_media(mundo: str):
    """List ALL images from wiki/media/ and referencias/visuales/imagenes/."""
    bases = _get_media_bases(mundo)
    images: list[ImageInfo] = []

    for base in bases:
        if not base.is_dir():
            continue
        for entry in sorted(base.rglob("*")):
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            stat = entry.stat()
            images.append(ImageInfo(
                path=_rel_path(entry, mundo),
                name=entry.name,
                size_bytes=stat.st_size,
                extension=entry.suffix.lower(),
            ))

    return MediaList(images=images, total=len(images))


@app.delete("/api/{mundo}/media")
async def delete_media(
    mundo: str,
    path: str = Query(..., description="Ruta relativa del archivo (desde raíz de mundo o relativa a wiki/media/)"),
):
    """Delete an image from wiki/media/ only (referencias is read-only)."""
    mundo_base = MUNDOS_DIR / mundo
    wiki_base = (mundo_base / "wiki" / "media").resolve()
    wiki_str = str(wiki_base) + os.sep
    ref_base = (mundo_base / "referencias" / "visuales" / "imagenes").resolve()
    ref_str = str(ref_base) + os.sep

    # Try mundo-relative first, then base-relative
    candidates = [
        (mundo_base / path).resolve(),
        (wiki_base / path).resolve(),
    ]

    resolved = None
    for full in candidates:
        if str(full).startswith(wiki_str):
            resolved = full
            break

    if resolved is None:
        # Check if it points to referencias (→ 403)
        if any(str(c).startswith(ref_str) for c in candidates):
            raise HTTPException(
                status_code=403,
                detail="No se puede eliminar archivos de referencias/",
            )
        raise HTTPException(status_code=400, detail="Path traversal detectado")

    # File existence
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    # Delete the file
    resolved.unlink()

    # Also delete the associated thumbnail if it exists
    thumb = resolved.parent / f"{resolved.stem}_thumb{resolved.suffix}"
    if thumb.is_file():
        thumb.unlink()

    response_path = _rel_path(resolved, mundo)
    return {"success": True, "path": response_path}


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
    section: str = ""
    file_path: str = ""

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
    parts = [f"[Mundo: {mundo}]"] if mundo else []
    if body.file_path:
        title = None
        resolved = _resolve_path(mundo, body.section, body.file_path)
        if resolved is not None:
            try:
                content = resolved.read_text(encoding="utf-8")
            except Exception:
                content = None
            if content is not None:
                fm = re.match(r"\A---\r?\n(.*?)\r?\n---", content, re.DOTALL)
                if fm:
                    m = re.search(r"(?m)^title:\s*(.+?)\s*$", fm.group(1))
                    if m:
                        title = m.group(1).strip().strip('"').strip("'")
                if not title:
                    title = Path(body.file_path).stem.replace("_", " ")
        if title:
            parts.append(f"[Ficha actual: [[{title}]] — ruta: {body.section}/{body.file_path}]")
        else:
            parts.append(f"[Ficha actual: {body.section}/{body.file_path}]")
    if parts:
        joined = "\n".join(parts)
        prompt = f"{joined}\n\n{body.prompt}"
    else:
        prompt = body.prompt
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
