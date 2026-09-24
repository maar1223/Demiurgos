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

import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

try:  # imported as ``wiki.ideas_bank`` (package) …
    from . import data_root
except ImportError:  # … and flat, with ``wiki/`` anchored on sys.path
    import data_root

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

# Reserved world names, mirrored from ``api_server._RESERVED_WORLD_NAMES``
# (api_server.py:405). Mirrored locally on purpose: importing api_server from
# ideas_bank would drag in the whole FastAPI app (heavy, package-relative).
# Keep this set in sync with api_server.py when it changes.
_RESERVED_WORLD_NAMES = frozenset({"Ideas", "trash"})


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
    """Resolve the data root, lazily on every call (WU-2).

    Never resolved at import time: the resolver fails loudly when no root is
    configured, which would break pytest collection. Tests keep replacing this
    function (``monkeypatch.setattr(module, "_project_root", ...)``).
    """
    return data_root.resolve_data_root()


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
    # ``updated_at`` sits with ``timestamp`` in to_dict()/frontmatter; here it
    # must follow the required fields (dataclass: default after non-default).
    updated_at: str = ""
    tags: list[str] = field(default_factory=list)
    status: str = "fresh"
    used_in: list[str] = field(default_factory=list)
    based_on: str | None = None
    media_path: str | None = None
    version: int = 1  # NEW — default 1 for backward compat (R-1)
    title: str = ""
    body: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "version": self.version,
            "timestamp": self.timestamp,
            "updated_at": self.updated_at,
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

    ``ideas_root`` defaults to ``<data root>/ideas``; ``mundos_root`` defaults to
    ``<data root>/mundos`` and is only used by ``materialize`` to record the
    inert ``based_on`` link on a canon ficha. Both defaults are resolved LAZILY
    on first access (WU-2): the API module builds one of these at import time,
    and resolving the data root there would break pytest collection.
    """

    def __init__(
        self,
        ideas_root: Path | None = None,
        mundos_root: Path | None = None,
    ) -> None:
        # Default ideas_root is ``<data root>/ideas`` (the global Taller de Ideas
        # bank), NOT the data root itself — scanning the root only finds *.md
        # docs with no idea frontmatter and the bank appears empty.
        self._ideas_root_value: Path | None = (
            Path(ideas_root) if ideas_root is not None else None
        )
        self._mundos_root_value: Path | None = (
            Path(mundos_root) if mundos_root is not None else None
        )

    @property
    def _ideas_root(self) -> Path:
        """``<data root>/ideas``, resolved on first access (WU-2)."""
        if self._ideas_root_value is None:
            self._ideas_root_value = _project_root() / "ideas"
        return self._ideas_root_value

    @property
    def _mundos_root(self) -> Path:
        """``<data root>/mundos``, resolved on first access (WU-2)."""
        if self._mundos_root_value is None:
            self._mundos_root_value = _project_root() / "mundos"
        return self._mundos_root_value

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
        """Resolve a canon ficha under ``mundos/{world}/{rel}`` safely.

        World names resolve CASE-SENSITIVELY against the on-disk ``mundos/``
        directory — a valid mixed-case world such as ``Vibrantes`` must not be
        rejected by a lowercase-only gate (R-CG-04). Mirrors
        ``_resolve_mundo_dir`` (api_server.py:456-482) without importing
        api_server: non-str/empty world, separators/absolute/dot segments,
        leading ``.``/``_``, reserved names, a missing directory and root
        escape are all rejected. ``canon_rel`` must stay relative and its
        resolved path must remain inside the world directory.
        """
        if not isinstance(world_slug, str) or not world_slug:
            raise InvalidIdea(f"El mundo '{world_slug}' no es un nombre seguro.")
        if world_slug != Path(world_slug).name:  # separators / absolute / dot segments
            raise InvalidIdea(f"El mundo '{world_slug}' no es un nombre seguro.")
        if world_slug.startswith((".", "_")) or world_slug in _RESERVED_WORLD_NAMES:
            raise InvalidIdea(f"El mundo '{world_slug}' no es un nombre seguro.")
        world_dir = (self._mundos_root / world_slug).resolve()
        if not world_dir.is_dir() or world_dir.parent != self._mundos_root.resolve():
            raise InvalidIdea(f"El mundo '{world_slug}' no es un nombre seguro.")
        rel = Path(canon_rel)
        if rel.is_absolute() or ".." in rel.parts:
            raise InvalidIdea("La ruta canónica debe ser relativa dentro del mundo.")
        path = (world_dir / rel).resolve()
        if not str(path).startswith(str(world_dir) + os.sep):
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
        # Lenient version parse: absent/non-numeric frontmatter defaults to 1
        # so pre-versioning files keep working (R-1, S-1.1).
        raw_version = data.get("version", 1)
        try:
            version = int(raw_version) if raw_version is not None else 1
        except (TypeError, ValueError):
            version = 1
        return Idea(
            id=str(data.get("id") or ""),
            slug=str(data.get("slug") or slug),
            timestamp=str(data.get("timestamp") or ""),
            updated_at=str(data.get("updated_at") or data.get("timestamp") or ""),
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
            version=version,
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
            updated_at=now,
            source=source,
            type=type,
            tags=tags,
            status="fresh",
            used_in=[],
            based_on=None,
            media_path=None,
            version=1,  # every new idea starts at version 1 (R-11, S-11.1)
            title=title or "",
            body=body.strip(),
        )
        self._write(idea)
        return idea

    def update(self, slug: str, partial: dict[str, Any]) -> Idea:
        """Update idea fields (type correction, status, tags, body, ...).

        NON-versioned: the current file is overwritten in place and no
        archive is created. ``materialize()`` routes here on purpose (R-5,
        S-5.1); content edits go through ``update_versioned()`` (R-2).
        """
        _, updated = self._prepare_update(slug, partial)
        self._write(updated)
        return updated

    def update_versioned(self, slug: str, partial: dict[str, Any]) -> Idea:
        """Update idea fields with file-level versioning (R-2).

        The current ``ideas/{slug}.md`` is archived to
        ``ideas/versions/{slug}-v{N}.md`` BEFORE the new file is written —
        both writes are atomic tmp+replace via ``_write_to`` — then
        ``version`` is bumped in the new frontmatter. The new version is
        derived from the filesystem (``max(archived vN) + 1``), never from
        an in-memory counter (S-2.3, S-2.6). Payload validation matches
        ``update()`` and runs before any disk write, so an invalid payload
        fails closed without touching existing files (S-2.5).
        """
        current, updated = self._prepare_update(slug, partial)
        # Archive FIRST: a failure in the new-file write must never lose the
        # archived version (S-2.4).
        self._write_to(current, self._archive_path(slug, current.version))
        updated.version = self._next_version(slug)
        self._write(updated)
        return updated

    def _prepare_update(self, slug: str, partial: dict[str, Any]) -> tuple[Idea, Idea]:
        """Validate ``partial`` and merge it into the current idea.

        Shared by ``update()`` and ``update_versioned()`` so both enforce
        exactly the same payload contract. Returns ``(current, merged)``.
        Raises ``InvalidIdea`` before any disk write.
        """
        if not isinstance(partial, dict):
            raise InvalidIdea("La actualización debe ser un objeto.")
        allowed = {"type", "status", "source", "tags", "used_in", "based_on", "media_path", "title", "body"}
        unknown = set(partial) - allowed
        if unknown:
            raise InvalidIdea(
                f"Campos desconocidos: {', '.join(sorted(unknown))}."
            )
        current = self.read(slug)
        merged = current.to_dict()
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
            id=current.id,
            slug=slug,
            timestamp=current.timestamp,
            updated_at=utcnow_iso(),  # server-managed: every update is a change
            source=merged["source"],
            type=merged["type"],
            tags=list(merged["tags"]),
            status=merged["status"],
            used_in=list(merged["used_in"]),
            based_on=merged.get("based_on"),
            media_path=merged.get("media_path"),
            version=merged["version"],
            title=merged.get("title", current.title),
            body=merged.get("body", current.body),
        )
        return current, updated

    @staticmethod
    def _ext_for_mime(mime: str) -> str:
        """Map a MIME type to its file extension; unknown image MIMEs default
        to ``.jpg`` so the media endpoint's allowlist still serves them."""
        return {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
        }.get(mime, ".jpg")

    def attach_media(
        self,
        slug: str,
        image_bytes: bytes,
        mime: str,
        partial: dict[str, Any] | None = None,
    ) -> Idea:
        """Attach an image to an existing idea (versioned, R-2 extension).

        Writes ``image_bytes`` to ``ideas/media/{slug}{ext}`` (ext derived
        from ``mime`` via ``_ext_for_mime``) and records it as the idea's
        ``media_path``. The body gets the canonical embed
        ``![idea image](/api/ideas/media/{slug}{ext})`` prepended — never
        duplicated when the embed is already present. Content changes go
        through ``update_versioned()``, so the current version is archived
        and the version bumps. Raises ``IdeaNotFound`` when the slug does not
        exist and ``InvalidIdea`` when ``image_bytes`` is empty.
        """
        if not image_bytes:
            raise InvalidIdea("No se puede adjuntar una imagen vacía.")
        current = self.read(slug)
        ext = self._ext_for_mime(mime)
        media_dir = self._ideas_root / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        target = media_dir / f"{slug}{ext}"
        target.write_bytes(image_bytes)
        embed = f"![idea image](/api/ideas/media/{slug}{ext})"
        body = (partial or {}).get("body", current.body)
        if embed not in body:
            body = f"{embed}\n\n{body}" if body.strip() else embed
        merged_partial = dict(partial or {})
        # media_path/body are authoritative — the embed must never be lost.
        merged_partial["media_path"] = f"media/{slug}{ext}"
        merged_partial["body"] = body
        return self.update_versioned(slug, merged_partial)

    def _archive_path(self, slug: str, version: int) -> Path:
        """Resolve ``ideas/versions/<slug>-v<version>.md`` (R-2)."""
        if not _valid_slug(slug):
            raise InvalidIdea(f"El slug '{slug}' no es válido (solo minúsculas, dígitos, guiones y guiones bajos).")
        versions_dir = (self._ideas_root / "versions").resolve()
        path = (versions_dir / f"{slug}-v{version}.md").resolve()
        if path.parent != versions_dir:
            raise InvalidIdea(f"El slug '{slug}' no es un nombre de archivo seguro.")
        return path

    def _versions_for(self, slug: str) -> list[Path]:
        """Archived versions for slug, ascending by version number (R-3).

        Returns an empty list when no ``ideas/versions/`` archive exists
        for the slug (S-3.2). Numeric ordering keeps ``v10`` after ``v9``.
        """
        versions_dir = self._ideas_root / "versions"
        if not versions_dir.is_dir():
            return []
        pattern = re.compile(rf"^{re.escape(slug)}-v(\d+)\.md$")
        found: list[tuple[int, Path]] = []
        for path in versions_dir.iterdir():
            match = pattern.fullmatch(path.name)
            if match:
                found.append((int(match.group(1)), path))
        found.sort(key=lambda item: item[0])
        return [path for _, path in found]

    def _next_version(self, slug: str) -> int:
        """``max(archived vN on disk) + 1`` — filesystem-derived (S-2.3).

        The version number is read from disk at write time, never kept in
        memory, so it survives restarts and stays deterministic for a
        single user (S-2.6).
        """
        versions = self._versions_for(slug)
        if not versions:
            return 1
        pattern = re.compile(rf"^{re.escape(slug)}-v(\d+)\.md$")
        numbers = [int(pattern.match(path.name).group(1)) for path in versions]
        return max(numbers) + 1

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
        """Persist an idea to ``ideas/{slug}.md`` atomically (tmp+replace)."""
        self._write_to(idea, self._path_for(idea.slug))

    def _write_to(self, idea: Idea, path: Path) -> None:
        """Persist an idea file atomically (tmp+replace) at an explicit path.

        Shared by the live ``ideas/{slug}.md`` write and the version-archive
        write ``ideas/versions/{slug}-vN.md`` (R-2). The archive write
        happens BEFORE the new live file is written, so a failure in the
        new-file write never loses the archived version (S-2.4).
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        data = idea.to_dict()
        data.pop("body", None)  # body is the free-text section, not frontmatter
        data["_body"] = idea.body
        content = self._render_frontmatter(data)
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)