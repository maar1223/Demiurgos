"""Ideas bank REST router — ``/api/ideas`` endpoints.

Exposes the global ``ideas/`` bank over FastAPI: list (with type/status/source
filters), read, create (manual origin), update (incl. type correction),
delete, and the materialization-link seam (``POST /{slug}/materialize``).

Auth mirrors the sibling routers (``create_idea_capture_router``): every route
requires a trusted local principal resolved at call time via
``require_principal``; None maps to 401. ``api_server`` passes
``_resolve_principal`` through a lambda so tests can swap it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request
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


class IdeaUpdateRequest(BaseModel):
    """PATCH /api/ideas/{slug} payload — partial frontmatter update."""

    type: str | None = None
    status: str | None = None
    source: str | None = None
    tags: list[str] | None = None
    used_in: list[str] | None = None
    based_on: str | None = None
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

    @router.get("/{slug}")
    def get_idea(slug: str, request: Request) -> dict[str, Any]:
        """Detail of a single idea (R-IB-03)."""
        _guard(request)
        try:
            return _detail(bank.read(slug))
        except IdeaNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))

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
            )
        except (IdeaConflict, InvalidIdea) as exc:
            status_code = 409 if isinstance(exc, IdeaConflict) else 400
            raise HTTPException(status_code=status_code, detail=str(exc))
        return _detail(idea)

    @router.patch("/{slug}")
    def update_idea(slug: str, body: IdeaUpdateRequest, request: Request) -> dict[str, Any]:
        """Partial update — type correction, status, tags, body (R-IB-03)."""
        _guard(request)
        partial = body.model_dump(exclude_unset=True)
        if not partial:
            raise HTTPException(status_code=400, detail="No hay campos para actualizar.")
        try:
            return _detail(bank.update(slug, partial))
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