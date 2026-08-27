"""Global idea bank — storage/service for the top-level ``ideas/`` OKF bank.

Ideas are reusable, world-agnostic archetypes (personajes, relaciones,
ambientaciones, tramas, conceptos) that belong to no world and can be
materialized into many. Each idea is a Markdown file with YAML frontmatter
carrying ``id``, ``slug``, ``timestamp``, ``source``, ``type``, ``tags``,
``status``, ``used_in`` and ``based_on``, plus a free-text body.

Canon safety is STRUCTURAL: ``ideas/`` lives at the project root as a sibling
of ``mundos/``, so the graph indexer (scoped to ``mundos/{mundo}/``), the world
listing and the wiki file tree never see it. ``IdeasBank`` parses frontmatter
leniently (identity-only) and NEVER validates an idea against a world graph.

Materialization is inert metadata: appending a world slug to ``used_in`` on the
idea and recording ``based_on: ideas/{slug}`` on a canon ficha never triggers
graph indexing or OKF validation.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# --- OKF idea model contract (R-IB-01) --------------------------------------
IDEA_TYPES: tuple[str, ...] = (
    "personaje",
    "relacion",
    "ambientacion",
    "trama",
    "concepto",
    "sin_clasificar",
)
IDEA_SOURCES: tuple[str, ...] = ("telegram", "manual", "assistant")
IDEA_STATUSES: tuple[str, ...] = ("fresh", "used")

# URL-safe slug: lowercase letters/digits, hyphens and underscores.
_RE_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class IdeaBankError(Exception):
    """Base error for the global idea bank."""


class IdeaNotFound(IdeaBankError):
    """Raised when an idea slug does not exist."""


class IdeaConflict(IdeaBankError):
    """Raised when creating an idea whose slug already exists."""


class InvalidIdea(IdeaBankError):
    """Raised when an idea payload violates the OKF model contract."""


def utcnow_iso() -> str:
    """ISO-8601 UTC timestamp for idea frontmatter."""
    return datetime.now(timezone.utc).isoformat()


def _project_root() -> Path:
    """Auto-detect the project root from this file's location."""
    return Path(__file__).resolve().parents[4]


def _valid_slug(slug: Any) -> bool:
    return isinstance(slug, str) and bool(_RE_SLUG.fullmatch(slug))


@dataclass
class Idea:
    """Parsed idea (OKF frontmatter + free-text body)."""

    id: str
    slug: str
    timestamp: str
    source: str
    type: str
    tags: list[str] = field(default_factory=list)
    status: str = "fresh"
    used_in: list[str] = field(default_factory=list)
    based_on: str | None = None
    media_path: str | None = None
    title: str = ""
    body: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "timestamp": self.timestamp,
            "source": self.source,
            "type": self.type,
            "title": self.title,
            "tags": list(self.tags),
            "status": self.status,
            "used_in": list(self.used_in),
            "based_on": self.based_on,
            "media_path": self.media_path,
            "body": self.body,
        }

    def to_summary(self) -> dict[str, Any]:
        """IdeaSummary for list endpoints (no body)."""
        data = self.to_dict()
        data.pop("body", None)
        return data


class IdeasBank:
    """CRUD + materialization seam over the top-level ``ideas/`` bank.

    ``ideas_root`` defaults to ``<project>/ideas``; ``mundos_root`` defaults to
    ``<project>/mundos`` and is only used by ``materialize`` to record the
    inert ``based_on`` link on a canon ficha.
    """

    def __init__(
        self,
        ideas_root: Path | None = None,
        mundos_root: Path | None = None,
    ) -> None:
        # Default ideas_root is ``<project>/ideas`` (the global Taller de Ideas
        # bank), NOT ``<project>`` — scanning the repo root only finds *.md
        # docs with no idea frontmatter and the bank appears empty.
        root = (_project_root() / "ideas" if ideas_root is None else Path(ideas_root))
        self._ideas_root: Path = root
        self._mundos_root: Path = (
            _project_root() / "mundos" if mundos_root is None else Path(mundos_root)
        )

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def _path_for(self, slug: str) -> Path:
        """Resolve ``ideas/{slug}.md`` with traversal safety."""
        if not _valid_slug(slug):
            raise InvalidIdea(f"El slug '{slug}' no es válido (solo minúsculas, dígitos, guiones y guiones bajos).")
        path = (self._ideas_root / f"{slug}.md").resolve()
        if path.parent != self._ideas_root.resolve():
            raise InvalidIdea(f"El slug '{slug}' no es un nombre de archivo seguro.")
        return path

    def _canon_path_for(self, world_slug: str, canon_rel: str) -> Path:
        """Resolve a canon ficha under ``mundos/{world}/{rel}`` safely."""
        if not _valid_slug(world_slug) or world_slug.startswith((".", "_")):
            raise InvalidIdea(f"El mundo '{world_slug}' no es un nombre seguro.")
        rel = Path(canon_rel)
        if rel.is_absolute() or ".." in rel.parts:
            raise InvalidIdea("La ruta canónica debe ser relativa dentro del mundo.")
        path = (self._mundos_root / world_slug / rel).resolve()
        if path.parent != (self._mundos_root / world_slug / rel.parent).resolve():
            raise InvalidIdea("La ruta canónica escapa del mundo.")
        return path

    # ------------------------------------------------------------------
    # Frontmatter helpers (lenient, identity-only — never world-graph OKF)
    # ------------------------------------------------------------------

    @staticmethod
    def _split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
        """Lenient frontmatter split -> (data, body). Empty dict if none."""
        lines = content.split("\n")
        if not lines or lines[0].strip() != "---":
            return {}, content
        end_idx: int | None = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break
        if end_idx is None:
            return {}, content
        raw = "\n".join(lines[1:end_idx])
        try:
            parsed = yaml.safe_load(raw)
        except yaml.YAMLError:
            parsed = None
        data = parsed if isinstance(parsed, dict) else {}
        body = "\n".join(lines[end_idx + 1 :]).lstrip("\n")
        return data, body

    @staticmethod
    def _render_frontmatter(data: dict[str, Any]) -> str:
        """Render an idea file (frontmatter + body) deterministically.

        The ``_body`` marker carries the free-text section and is never dumped
        into the YAML block — body is NOT a frontmatter field (R-IB-01).
        """
        body = str(data.pop("_body", ""))
        block = yaml.safe_dump(
            data,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        ).strip()
        return f"---\n{block}\n---\n\n{body}".rstrip() + "\n"

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _idea_from_file(self, path: Path) -> Idea | None:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        data, body = self._split_frontmatter(content)
        slug = path.stem
        if not data:
            return None
        return Idea(
            id=str(data.get("id") or ""),
            slug=str(data.get("slug") or slug),
            timestamp=str(data.get("timestamp") or ""),
            source=str(data.get("source") or ""),
            type=str(data.get("type") or "sin_clasificar"),
            tags=[t for t in data.get("tags", []) if isinstance(t, str)]
            if isinstance(data.get("tags"), list)
            else [],
            status=str(data.get("status") or "fresh"),
            used_in=[w for w in data.get("used_in", []) if isinstance(w, str)]
            if isinstance(data.get("used_in"), list)
            else [],
            based_on=data.get("based_on"),
            media_path=data.get("media_path"),
            title=str(data.get("title") or ""),
            body=body.strip(),
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list(
        self,
        type: str | None = None,
        status: str | None = None,
        source: str | None = None,
    ) -> list[Idea]:
        """List ideas, optionally filtered by type/status/source (R-IB-03)."""
        if not self._ideas_root.is_dir():
            return []
        ideas: list[Idea] = []
        for path in sorted(self._ideas_root.glob("*.md")):
            idea = self._idea_from_file(path)
            if idea is None:
                continue
            if type and idea.type != type:
                continue
            if status and idea.status != status:
                continue
            if source and idea.source != source:
                continue
            ideas.append(idea)
        return ideas

    def read(self, slug: str) -> Idea:
        """Read a single idea by slug (404 on missing/traversal)."""
        path = self._path_for(slug)
        if not path.is_file():
            raise IdeaNotFound(f"No existe la idea '{slug}'.")
        idea = self._idea_from_file(path)
        if idea is None:
            raise IdeaNotFound(f"No existe la idea '{slug}'.")
        return idea

    def create(
        self,
        slug: str,
        type: str,
        body: str,
        tags: list[str] | None = None,
        source: str = "manual",
        title: str | None = None,
    ) -> Idea:
        """Create a well-formed idea file (R-IB-01, R-IB-03).

        ``slug`` must be unique; ``type`` must be in the taxonomy; ``source``
        must be one of telegram|manual|assistant; ``title`` must be a string
        when provided (empty/None allowed — the UI falls back to the slug).
        The file is written with all required frontmatter fields plus the
        free-text body.
        """
        path = self._path_for(slug)
        if path.exists():
            raise IdeaConflict(f"Ya existe una idea con el slug '{slug}'.")
        if type not in IDEA_TYPES:
            raise InvalidIdea(
                f"El tipo '{type}' no es válido. Tipos: {', '.join(IDEA_TYPES)}."
            )
        if source not in IDEA_SOURCES:
            raise InvalidIdea(
                f"El origen '{source}' no es válido. Orígenes: {', '.join(IDEA_SOURCES)}."
            )
        if not isinstance(body, str) or not body.strip():
            raise InvalidIdea("El cuerpo de la idea no puede estar vacío.")
        if title is not None and not isinstance(title, str):
            raise InvalidIdea("El título de la idea debe ser un string.")
        tags = [t for t in (tags or []) if isinstance(t, str) and t.strip()]
        now = utcnow_iso()
        idea = Idea(
            id=str(uuid.uuid4()),
            slug=slug,
            timestamp=now,
            source=source,
            type=type,
            tags=tags,
            status="fresh",
            used_in=[],
            based_on=None,
            media_path=None,
            title=title or "",
            body=body.strip(),
        )
        self._write(idea)
        return idea

    def update(self, slug: str, partial: dict[str, Any]) -> Idea:
        """Update idea fields (type correction, status, tags, body, ...).

        ``partial`` keys must be a known subset of the frontmatter model; the
        taxonomy/status/source invariants are re-validated on the merged
        result. ``slug`` itself cannot be renamed through update.
        """
        if not isinstance(partial, dict):
            raise InvalidIdea("La actualización debe ser un objeto.")
        allowed = {"type", "status", "source", "tags", "used_in", "based_on", "media_path", "title", "body"}
        unknown = set(partial) - allowed
        if unknown:
            raise InvalidIdea(
                f"Campos desconocidos: {', '.join(sorted(unknown))}."
            )
        idea = self.read(slug)
        merged = idea.to_dict()
        merged.update(partial)
        # Re-validate invariants on the merged payload.
        if merged["type"] not in IDEA_TYPES:
            raise InvalidIdea(
                f"El tipo '{merged['type']}' no es válido. Tipos: {', '.join(IDEA_TYPES)}."
            )
        if merged["status"] not in IDEA_STATUSES:
            raise InvalidIdea(
                f"El estado '{merged['status']}' no es válido. Estados: {', '.join(IDEA_STATUSES)}."
            )
        if merged["source"] not in IDEA_SOURCES:
            raise InvalidIdea(
                f"El origen '{merged['source']}' no es válido. Orígenes: {', '.join(IDEA_SOURCES)}."
            )
        if not isinstance(merged["tags"], list) or not all(
            isinstance(t, str) for t in merged["tags"]
        ):
            raise InvalidIdea("tags debe ser una lista de strings.")
        if not isinstance(merged["used_in"], list) or not all(
            isinstance(w, str) for w in merged["used_in"]
        ):
            raise InvalidIdea("used_in debe ser una lista de slugs de mundo.")
        if not isinstance(merged["title"], str):
            raise InvalidIdea("El título de la idea debe ser un string.")
        updated = Idea(
            id=idea.id,
            slug=slug,
            timestamp=idea.timestamp,
            source=merged["source"],
            type=merged["type"],
            tags=list(merged["tags"]),
            status=merged["status"],
            used_in=list(merged["used_in"]),
            based_on=merged.get("based_on"),
            media_path=merged.get("media_path"),
            title=merged.get("title", idea.title),
            body=merged.get("body", idea.body),
        )
        self._write(updated)
        return updated

    def delete(self, slug: str) -> None:
        """Delete an idea file (archive/delete surface, R-IB-03 extension)."""
        path = self._path_for(slug)
        if not path.is_file():
            raise IdeaNotFound(f"No existe la idea '{slug}'.")
        path.unlink()

    # ------------------------------------------------------------------
    # Materialization seam (R-CG-04) — inert metadata, no graph impact
    # ------------------------------------------------------------------

    def materialize(
        self, slug: str, world_slug: str, canon_rel: str | None = None
    ) -> dict[str, Any]:
        """Record that *world_slug* used this idea.

        Appends the world slug to ``used_in[]`` (deduped) and transitions the
        idea to ``status: used``. When *canon_rel* is given, records the inert
        ``based_on: ideas/{slug}`` field on the canon ficha
        ``mundos/{world_slug}/{canon_rel}`` (skipped silently if the ficha is
        missing — the idea-side link is authoritative).
        """
        idea = self.read(slug)
        used = idea.used_in[:]
        if world_slug not in used:
            used.append(world_slug)
        idea = self.update(slug, {"used_in": used, "status": "used"})
        canon_path: str | None = None
        if canon_rel:
            canon_path = self._record_based_on(world_slug, canon_rel, slug)
        return {"ok": True, "used_in": list(idea.used_in), "canon_path": canon_path}

    def _record_based_on(self, world_slug: str, canon_rel: str, idea_slug: str) -> str | None:
        """Write ``based_on: ideas/{slug}`` into a canon ficha's frontmatter."""
        try:
            target = self._canon_path_for(world_slug, canon_rel)
        except InvalidIdea:
            return None
        if not target.is_file():
            return None
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        data, body = self._split_frontmatter(content)
        if not data:
            return None
        data["based_on"] = f"ideas/{idea_slug}"
        try:
            target.write_text(
                self._render_frontmatter({**data, "_body": body}),
                encoding="utf-8",
            )
        except OSError:
            return None
        return str(target)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def _write(self, idea: Idea) -> None:
        """Persist an idea to ``ideas/{slug}.md`` atomically."""
        self._ideas_root.mkdir(parents=True, exist_ok=True)
        data = idea.to_dict()
        data.pop("body", None)  # body is the free-text section, not frontmatter
        data["_body"] = idea.body
        content = self._render_frontmatter(data)
        path = self._path_for(idea.slug)
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)