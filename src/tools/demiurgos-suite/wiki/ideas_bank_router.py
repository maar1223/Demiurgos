"""Ideas bank REST router — ``/api/ideas`` endpoints.

Exposes the global ``ideas/`` bank over FastAPI: list (with type/status/source
filters), read, create (manual origin), update (incl. type correction),
delete, image attach (``POST /{slug}/media``), and the materialization-link
seam (``POST /{slug}/materialize``).

Auth mirrors the sibling routers (``create_idea_capture_router``): every route
requires a trusted local principal resolved at call time via
``require_principal``; None maps to 401. ``api_server`` passes
``_resolve_principal`` through a lambda so tests can swap it.
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ideas_bank import (
    IDEA_SOURCES,
    IDEA_STATUSES,
    IDEA_TYPES,
    Idea,
    IdeaBankError,
    IdeaConflict,
    IdeaNotFound,
    IdeasBank,
    InvalidIdea,
)


class IdeaCreateRequest(BaseModel):
    """POST /api/ideas payload (R-IB-03)."""

    slug: str = Field(..., min_length=1, max_length=120)
    type: str
    body: str = Field(..., min_length=1)
    tags: list[str] | None = None
    source: str = "manual"
    title: str | None = None


class IdeaUpdateRequest(BaseModel):
    """PATCH /api/ideas/{slug} payload — partial frontmatter update."""

    type: str | None = None
    status: str | None = None
    source: str | None = None
    tags: list[str] | None = None
    used_in: list[str] | None = None
    based_on: str | None = None
    title: str | None = None
    body: str | None = None


class IdeaMaterializeRequest(BaseModel):
    """POST /api/ideas/{slug}/materialize payload (R-CG-04)."""

    world: str
    canon_rel: str | None = None


def create_ideas_bank_router(
    require_principal: Callable[[Request], Any],
    ideas_root: Path | None = None,
    mundos_root: Path | None = None,
) -> APIRouter:
    """Build the /api/ideas router.

    ``require_principal`` must return a trusted principal for the request or
    None; None maps to 401. ``ideas_root``/``mundos_root`` are test seams that
    default to the project roots.
    """
    router = APIRouter(prefix="/api/ideas", tags=["ideas-bank"])
    bank = IdeasBank(ideas_root=ideas_root, mundos_root=mundos_root)

    def _guard(request: Request) -> None:
        if require_principal(request) is None:
            raise HTTPException(status_code=401, detail="Autenticación requerida")

    def _detail(idea: Idea) -> dict[str, Any]:
        return idea.to_dict()

    @router.get("")
    def list_ideas(
        request: Request,
        type: str | None = Query(default=None),
        status: str | None = Query(default=None),
        source: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """List ideas, optionally filtered by type/status/source (R-IB-03)."""
        _guard(request)
        ideas = bank.list(type=type, status=status, source=source)
        return {
            "ideas": [idea.to_summary() for idea in ideas],
            "total": len(ideas),
        }

    @router.get("/media/{filename}")
    def get_idea_media(filename: str, request: Request) -> FileResponse:
        """Serve an image from ``<ideas_root>/media/{filename}`` (R-2, R-3).

        Path-traversal protection: reject ``..``, path separators and absolute
        paths; allowlist image extensions; serve only from ``<ideas_root>/media``
        with a ``resolve()`` parent check as defense-in-depth.
        """
        _guard(request)
        # Reject dangerous filename patterns (S-2.1). A null byte would make
        # ``Path.resolve()`` raise ValueError (unhandled 500) — reject it too.
        if (
            ".." in filename
            or "/" in filename
            or "\\" in filename
            or filename.startswith("/")
            or filename.startswith("\\")
            or "\x00" in filename
        ):
            raise HTTPException(status_code=400, detail="Invalid filename")
        # Allowlist extensions (R-3).
        ext = Path(filename).suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            raise HTTPException(status_code=400, detail="Unsupported file type")
        # Serve only from <ideas_root>/media (defense-in-depth).
        media_dir = bank._ideas_root / "media"
        try:
            file_path = (media_dir / filename).resolve()
        except (OSError, ValueError):
            # A malformed filename that cannot resolve (e.g. an embedded null
            # byte) is a bad request, never a 500.
            raise HTTPException(status_code=400, detail="Invalid filename")
        if file_path.parent != media_dir.resolve():
            raise HTTPException(status_code=403, detail="Access denied")
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        mime_type, _ = mimetypes.guess_type(filename)
        if mime_type is None:
            mime_type = "application/octet-stream"
        return FileResponse(file_path, media_type=mime_type)

    @router.post("/{slug}/media", status_code=201)
    async def attach_idea_media(
        slug: str,
        request: Request,
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        """Attach an image to an existing idea (versioned, R-2 extension).

        Reads the uploaded bytes and delegates to
        ``IdeasBank.attach_media()``: the image is written to
        ``ideas/media/{slug}{ext}``, ``media_path`` is recorded and the embed
        is prepended to the body (current version archived, version bumped).
        Empty uploads are 400; unknown slug is 404.
        """
        _guard(request)
        image_bytes = await file.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="El archivo está vacío.")
        mime = file.content_type or "image/jpeg"
        try:
            idea = bank.attach_media(slug, image_bytes, mime)
        except IdeaNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidIdea as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _detail(idea)

    @router.get("/{slug}")
    def get_idea(slug: str, request: Request) -> dict[str, Any]:
        """Detail of a single idea (R-IB-03)."""
        _guard(request)
        try:
            return _detail(bank.read(slug))
        except IdeaNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.get("/{slug}/versions")
    def get_idea_versions(slug: str, request: Request) -> dict[str, Any]:
        """List an idea's archived versions ascending (R-10, S-10.2).

        Delegates to ``IdeasBank._versions_for()`` — the router never
        re-implements version history itself. Returns
        ``{slug, versions: [{version, path}]}``; an empty list when no
        archive exists for the slug. Unknown slug → 404.
        """
        _guard(request)
        try:
            bank.read(slug)
        except IdeaNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        versions = [
            {"version": int(match.group(1)), "path": str(path)}
            for path in bank._versions_for(slug)
            for match in [re.search(r"-v(\d+)\.md$", path.name)]
            if match
        ]
        return {"slug": slug, "versions": versions}

    @router.post("", status_code=201)
    def create_idea(body: IdeaCreateRequest, request: Request) -> dict[str, Any]:
        """Create a manual idea at ``ideas/{slug}.md`` (R-IB-01, R-IB-03)."""
        _guard(request)
        try:
            idea = bank.create(
                slug=body.slug,
                type=body.type,
                body=body.body,
                tags=body.tags,
                source=body.source,
                title=body.title,
            )
        except (IdeaConflict, InvalidIdea) as exc:
            status_code = 409 if isinstance(exc, IdeaConflict) else 400
            raise HTTPException(status_code=status_code, detail=str(exc))
        return _detail(idea)

    @router.patch("/{slug}")
    def update_idea(slug: str, body: IdeaUpdateRequest, request: Request) -> dict[str, Any]:
        """Partial update — type correction, status, tags, body (R-IB-03).

        Versioned by default (R-10, S-10.1): the current ``ideas/{slug}.md``
        is archived to ``ideas/versions/{slug}-vN.md`` and the live file gets
        the next filesystem-derived version. Delegates to
        ``IdeasBank.update_versioned()`` — the router never re-implements
        versioning logic.
        """
        _guard(request)
        partial = body.model_dump(exclude_unset=True)
        if not partial:
            raise HTTPException(status_code=400, detail="No hay campos para actualizar.")
        try:
            return _detail(bank.update_versioned(slug, partial))
        except IdeaNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidIdea as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.delete("/{slug}")
    def delete_idea(slug: str, request: Request) -> dict[str, Any]:
        """Delete an idea from the global bank (archive/delete surface)."""
        _guard(request)
        try:
            bank.delete(slug)
        except IdeaNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"ok": True, "slug": slug}

    @router.post("/{slug}/materialize")
    def materialize_idea(
        slug: str, body: IdeaMaterializeRequest, request: Request
    ) -> dict[str, Any]:
        """Record that a world used this idea (R-CG-04).

        Appends the world slug to ``used_in[]`` and sets ``status: used``;
        optionally records ``based_on: ideas/{slug}`` on the canon ficha at
        ``mundos/{world}/{canon_rel}``. Inert metadata — no graph impact.
        """
        _guard(request)
        try:
            result = bank.materialize(slug, body.world, canon_rel=body.canon_rel)
        except IdeaNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except (IdeaBankError, InvalidIdea) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return result

    return router


__all__ = [
    "IDEA_SOURCES",
    "IDEA_STATUSES",
    "IDEA_TYPES",
    "IdeaCreateRequest",
    "IdeaMaterializeRequest",
    "IdeaUpdateRequest",
    "create_ideas_bank_router",
]