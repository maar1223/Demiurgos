"""Methodology library — managed lifecycle for compiled methodologies.

Server-owned lifecycle store for author methodology:

- **Drafts** are editable (create/update/compile) and never enter runtime.
- **Publishing** compiles a draft into an immutable ``PublishedVersion`` that
  cannot be edited; republishing the same skill/version with a different
  content digest is rejected.
- **Activation** pins one published version per world. Deactivation clears
  the pin; rollback restores the previously active version.
- **Soft deletion** marks a published version as deleted without erasing it;
  restore brings it back.

The library is a plain JSON file behind a ``root`` path. It never touches the
kernel, canon files, or any path outside its own store file.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from methodology_compiler import (
    CompileResult,
    CompiledMethodology,
    MethodologyIssue,
    compile_methodology,
)


class MethodologyLibraryError(Exception):
    """Base error for the methodology library."""


class ValidationError(MethodologyLibraryError):
    """A draft failed compiler validation."""


class AlreadyPublishedError(MethodologyLibraryError):
    """The skill/version is already published with different content."""


class NotPublishedError(MethodologyLibraryError):
    """The skill/version is not published (or was deleted)."""


@dataclass
class Draft:
    """An editable methodology draft. Never reaches runtime until published."""

    draft_id: str
    skill_id: str
    version: str
    name: str
    source: str
    description: str = ""
    phases: tuple[str, ...] = ()
    language: str | None = None
    created_at: str = ""
    updated_at: str = ""
    # Inventory metadata (Taller de Herramientas, Fase 1). Optional with
    # defaults so old records deserialize safely.
    taller: str | None = None
    talleres_compatibles: tuple[str, ...] = ()
    categoria_funcional: str | None = None
    etiquetas: tuple[str, ...] = ()
    clasificacion: str | None = None
    trust_attributes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublishedVersion:
    """An immutable, compiled, published methodology version."""

    skill_id: str
    version: str
    name: str
    description: str
    phases: tuple[str, ...]
    language: str | None
    source: str
    digest: str
    published_at: str
    # Inventory metadata + system-derived classification/trust attributes
    # (Taller de Herramientas, Fase 1). Optional with defaults for
    # backward-compatible deserialization of old records.
    taller: str | None = None
    talleres_compatibles: tuple[str, ...] = ()
    categoria_funcional: str | None = None
    etiquetas: tuple[str, ...] = ()
    clasificacion: str | None = None
    trust_attributes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Activation:
    """The compiled methodology/version pinned to one world."""

    world: str
    skill_id: str
    version: str
    digest: str
    activated_at: str


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class MethodologyLibrary:
    """JSON-file-backed methodology lifecycle store.

    All mutations are serialized under a lock and written atomically (temp
    file + rename) so a crash cannot leave a half-written store.
    """

    def __init__(self, root: str | Path) -> None:
        self._path = Path(root)
        self._lock = threading.Lock()
        self._drafts: dict[str, dict[str, Any]] = {}
        self._published: dict[str, dict[str, Any]] = {}
        self._activations: dict[str, dict[str, Any]] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._load()

    # ------------------------------------------------------------------ #
    # Drafts
    # ------------------------------------------------------------------ #

    def create_draft(
        self,
        skill_id: str,
        version: str,
        name: str,
        source: str,
        description: str = "",
        phases: tuple[str, ...] = (),
        language: str | None = None,
        taller: str | None = None,
        talleres_compatibles: tuple[str, ...] = (),
        categoria_funcional: str | None = None,
        etiquetas: tuple[str, ...] = (),
        clasificacion: str | None = None,
        trust_attributes: tuple[str, ...] = (),
    ) -> str:
        draft_id = uuid.uuid4().hex[:12]
        now = _utcnow()
        with self._lock:
            self._drafts[draft_id] = {
                "draft_id": draft_id,
                "skill_id": skill_id,
                "version": version,
                "name": name,
                "source": source,
                "description": description,
                "phases": list(phases),
                "language": language,
                "taller": taller,
                "talleres_compatibles": list(talleres_compatibles),
                "categoria_funcional": categoria_funcional,
                "etiquetas": list(etiquetas),
                "clasificacion": clasificacion,
                "trust_attributes": list(trust_attributes),
                "created_at": now,
                "updated_at": now,
            }
            self._save_locked()
        return draft_id

    def get_draft(self, draft_id: str) -> Draft | None:
        with self._lock:
            record = self._drafts.get(draft_id)
            return self._draft_from(record) if record else None

    def list_drafts(self) -> list[Draft]:
        with self._lock:
            return [self._draft_from(r) for r in self._drafts.values()]

    def update_draft(
        self,
        draft_id: str,
        *,
        source: str | None = None,
        description: str | None = None,
        name: str | None = None,
        phases: tuple[str, ...] | None = None,
        language: str | None = None,
    ) -> Draft:
        with self._lock:
            record = self._drafts.get(draft_id)
            if record is None:
                raise KeyError(f"draft {draft_id!r} not found")
            if source is not None:
                record["source"] = source
            if description is not None:
                record["description"] = description
            if name is not None:
                record["name"] = name
            if phases is not None:
                record["phases"] = list(phases)
            if language is not None:
                record["language"] = language
            record["updated_at"] = _utcnow()
            self._save_locked()
            return self._draft_from(record)

    def compile_draft(self, draft_id: str) -> CompileResult:
        draft = self.get_draft(draft_id)
        if draft is None:
            return CompileResult(False, (
                MethodologyIssue("malformed-manifest", f"draft {draft_id!r} not found"),
            ))
        manifest = {
            "skill_id": draft.skill_id,
            "version": draft.version,
            "name": draft.name,
            "description": draft.description,
            "phases": list(draft.phases),
            "language": draft.language,
            "taller": draft.taller,
            "talleres_compatibles": list(draft.talleres_compatibles),
            "categoria_funcional": draft.categoria_funcional,
            "etiquetas": list(draft.etiquetas),
        }
        return compile_methodology(manifest, draft.source)

    def manifest_for(self, draft: Draft) -> dict[str, Any]:
        """The bounded manifest a draft would compile under."""
        return {
            "skill_id": draft.skill_id,
            "version": draft.version,
            "name": draft.name,
            "description": draft.description,
            "phases": list(draft.phases),
            "language": draft.language,
            "taller": draft.taller,
            "talleres_compatibles": list(draft.talleres_compatibles),
            "categoria_funcional": draft.categoria_funcional,
            "etiquetas": list(draft.etiquetas),
        }

    # ------------------------------------------------------------------ #
    # Publishing (immutable)
    # ------------------------------------------------------------------ #

    def publish(self, draft_id: str) -> PublishedVersion:
        result = self.compile_draft(draft_id)
        if not result.ok or result.compiled is None:
            raise ValidationError(
                "draft failed compiler validation: "
                + "; ".join(issue.message for issue in result.issues)
            )
        compiled = result.compiled
        key = self._key(compiled.skill_id, compiled.version)
        now = _utcnow()
        with self._lock:
            existing = self._published.get(key)
            if existing is not None:
                if existing["digest"] == compiled.digest:
                    return self._published_from(existing)
                raise AlreadyPublishedError(
                    f"{compiled.skill_id}@{compiled.version} is already published "
                    "with different content; published versions are immutable."
                )
            draft_record = self._drafts.get(draft_id) or {}
            record = {
                "skill_id": compiled.skill_id,
                "version": compiled.version,
                "name": compiled.name,
                "description": compiled.description,
                "phases": list(compiled.phases),
                "language": compiled.language,
                "source": compiled.source,
                "digest": compiled.digest,
                "published_at": now,
                "deleted_at": None,
                "taller": compiled.taller,
                "talleres_compatibles": list(compiled.talleres_compatibles),
                "categoria_funcional": compiled.categoria_funcional,
                "etiquetas": list(compiled.etiquetas),
                "clasificacion": draft_record.get("clasificacion"),
                "trust_attributes": list(draft_record.get("trust_attributes") or ()),
            }
            self._published[key] = record
            self._save_locked()
            return self._published_from(record)

    def get_published(self, skill_id: str, version: str) -> PublishedVersion | None:
        with self._lock:
            record = self._published.get(self._key(skill_id, version))
            return self._published_from(record) if record and not record.get("deleted_at") else None

    def list_published(self) -> list[PublishedVersion]:
        with self._lock:
            return [
                self._published_from(r)
                for r in self._published.values()
                if not r.get("deleted_at")
            ]

    def soft_delete(self, skill_id: str, version: str) -> None:
        key = self._key(skill_id, version)
        with self._lock:
            record = self._published.get(key)
            if record is None:
                raise NotPublishedError(f"{skill_id}@{version} is not published")
            record["deleted_at"] = _utcnow()
            # A deleted version cannot stay active anywhere.
            for world, active in list(self._activations.items()):
                if active.get("skill_id") == skill_id and active.get("version") == version:
                    self._activations.pop(world, None)
            self._save_locked()

    def restore(self, skill_id: str, version: str) -> None:
        key = self._key(skill_id, version)
        with self._lock:
            record = self._published.get(key)
            if record is None:
                raise NotPublishedError(f"{skill_id}@{version} is not published")
            record["deleted_at"] = None
            self._save_locked()

    # ------------------------------------------------------------------ #
    # Activation by world
    # ------------------------------------------------------------------ #

    def activate(self, world: str, skill_id: str, version: str) -> Activation:
        with self._lock:
            record = self._published.get(self._key(skill_id, version))
            if record is None or record.get("deleted_at"):
                raise NotPublishedError(f"{skill_id}@{version} is not published")
            digest = str(record["digest"])
            now = _utcnow()
            previous = self._activations.get(world)
            if previous is not None:
                self._history.setdefault(world, []).append(dict(previous))
            self._activations[world] = {
                "world": world,
                "skill_id": skill_id,
                "version": version,
                "digest": digest,
                "activated_at": now,
            }
            self._save_locked()
            return self._activation_from(self._activations[world])

    def active_for(self, world: str) -> Activation | None:
        with self._lock:
            record = self._activations.get(world)
            return self._activation_from(record) if record else None

    def deactivate(self, world: str) -> None:
        with self._lock:
            self._activations.pop(world, None)
            self._save_locked()

    def rollback(self, world: str) -> Activation | None:
        with self._lock:
            history = self._history.get(world) or []
            if not history:
                self._activations.pop(world, None)
                self._save_locked()
                return None
            restored = history.pop()
            self._activations[world] = restored
            self._save_locked()
            return self._activation_from(restored)

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    @staticmethod
    def _key(skill_id: str, version: str) -> str:
        return f"{skill_id}@{version}"

    def _load(self) -> None:
        if not self._path.exists():
            return
        with open(self._path, encoding="utf-8") as handle:
            payload = json.load(handle)
        self._drafts = dict(payload.get("drafts", {}))
        self._published = dict(payload.get("published", {}))
        self._activations = dict(payload.get("activations", {}))
        self._history = {
            world: list(stack)
            for world, stack in (payload.get("history") or {}).items()
        }

    def _save_locked(self) -> None:
        payload = {
            "drafts": self._drafts,
            "published": self._published,
            "activations": self._activations,
            "history": self._history,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, tmp_path = tempfile.mkstemp(
            prefix=".library-", suffix=".tmp", dir=str(self._path.parent),
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp_path, self._path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    @staticmethod
    def _draft_from(record: Mapping[str, Any]) -> Draft:
        return Draft(
            draft_id=record["draft_id"],
            skill_id=record["skill_id"],
            version=record["version"],
            name=record["name"],
            source=record["source"],
            description=record.get("description", ""),
            phases=tuple(record.get("phases", ())),
            language=record.get("language"),
            created_at=record.get("created_at", ""),
            updated_at=record.get("updated_at", ""),
            taller=record.get("taller"),
            talleres_compatibles=tuple(record.get("talleres_compatibles") or ()),
            categoria_funcional=record.get("categoria_funcional"),
            etiquetas=tuple(record.get("etiquetas") or ()),
            clasificacion=record.get("clasificacion"),
            trust_attributes=tuple(record.get("trust_attributes") or ()),
        )

    @staticmethod
    def _published_from(record: Mapping[str, Any]) -> PublishedVersion:
        return PublishedVersion(
            skill_id=record["skill_id"],
            version=record["version"],
            name=record["name"],
            description=record.get("description", ""),
            phases=tuple(record.get("phases", ())),
            language=record.get("language"),
            source=record["source"],
            digest=record["digest"],
            published_at=record.get("published_at", ""),
            taller=record.get("taller"),
            talleres_compatibles=tuple(record.get("talleres_compatibles") or ()),
            categoria_funcional=record.get("categoria_funcional"),
            etiquetas=tuple(record.get("etiquetas") or ()),
            clasificacion=record.get("clasificacion"),
            trust_attributes=tuple(record.get("trust_attributes") or ()),
        )

    @staticmethod
    def _activation_from(record: Mapping[str, Any]) -> Activation:
        return Activation(
            world=record["world"],
            skill_id=record["skill_id"],
            version=record["version"],
            digest=record["digest"],
            activated_at=record.get("activated_at", ""),
        )
