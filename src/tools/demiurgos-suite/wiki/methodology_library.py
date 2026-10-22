"""Methodology library — managed lifecycle for compiled methodologies.

Server-owned lifecycle store for author methodology:

- **Drafts** are editable (create/update/compile) and never enter runtime.
- **Publishing** compiles a draft into an immutable ``PublishedVersion`` that
  cannot be edited; republishing the same skill/version with a different
  content digest is rejected.
- **Activation** pins one published version per world per guided-flow type
  (SR1). Deactivation clears the pin; rollback restores the previously active
  version.
- **Soft deletion** marks a published version as deleted without erasing it;
  restore brings it back.

The library is a plain JSON file behind a ``root`` path. It never touches the
kernel, canon files, or any path outside its own store file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping

from methodology_compiler import (
    AttachmentEntry,
    CompileResult,
    CompiledMethodology,
    MethodologyIssue,
    compile_methodology,
)
from methodology_trust import FOUNDATIONAL, OFFICIAL, PERSONALIZADAS, scrub_foundational

logger = logging.getLogger("demiurgos-api")


# The id of the author-created foundational character-creation skill.
# Reserved against import-derived publishing (REQ-IMP-6); single source of
# truth shared with the skill router and the API trust boundary.
FOUNDATIONAL_CHARACTER_SKILL_ID = "narrative-character-creation"

# Root ids of the character-creation method family: the guided-character
# assistant only consumes methods declared by this lineage. ``guided-character-v1``
# is the builtin contract id (also honored as a legacy activation); every
# Author skill derived from the foundational one inherits eligibility through
# its ``parent_skill_id`` chain.
GUIDED_CHARACTER_METHOD_ROOTS: frozenset[str] = frozenset({
    FOUNDATIONAL_CHARACTER_SKILL_ID,
    "guided-character-v1",
})

# Guided flow types (SR1 — one activation slot per guided-flow type per world;
# contract §2). ``guided-character`` is the shipped guided flow; ``co-creation``
# is the Author-facing skill-creation flow. The set is the enumeration for the
# per-flow slot mechanism: adding a guided flow costs one constant + one set
# entry + its fallback branch (design D2 — no registry object).
GUIDED_CHARACTER_FLOW = "guided-character"
# RESERVED (WARNING-1 resolution, PR ②): ``co-creation`` is documented and
# kept but deliberately NOT bound as an activation slot. Co-created skills
# activate into the guided-character slot (``activate_co_creation`` calls
# ``activate`` without a flow arg), so binding this constant would orphan them
# from the guided flow they govern and from the skill-router candidate pool
# (which reads GUIDED_CHARACTER_FLOW only). It stays as the spec R1 "slots are
# independent" flow-B test vehicle and the API-reachable generic flow. Do not
# remove it; do not bind it without also unioning co-creation slots into the
# router pool.
CO_CREATION_FLOW = "co-creation"
SUPPORTED_FLOW_TYPES: frozenset[str] = frozenset({
    GUIDED_CHARACTER_FLOW,
    CO_CREATION_FLOW,
})
DEFAULT_FLOW_TYPE = GUIDED_CHARACTER_FLOW


# Authored intake bound for a skill trigger (the ``description`` the Author
# edits/approves). Mirrors ``skill_renderer.DESCRIPTION_INTAKE_LIMIT`` so the
# client mirror, the approval surface, and the renderer agree on one value;
# the server re-validates against this bound, which is authoritative over the
# client (see ``approve_trigger``).
TRIGGER_INTAKE_LIMIT = 60


class MethodologyLibraryError(Exception):
    """Base error for the methodology library."""


class ValidationError(MethodologyLibraryError):
    """A draft failed compiler validation."""


class AlreadyPublishedError(MethodologyLibraryError):
    """The skill/version is already published with different content."""


class NotPublishedError(MethodologyLibraryError):
    """The skill/version is not published (or was deleted)."""


class FoundationalImmutableError(MethodologyLibraryError):
    """A foundational (``fundacional``) record cannot be soft-deleted.

    The guard keys on the ``fundacional`` trust attribute, not the visible
    category: a signed non-``fundacional`` ``Oficiales`` record stays
    deletable (S10/S11).
    """


class CompanionLimitError(ValidationError):
    """The per-world companion cap (MAX_COMPANIONS_PER_WORLD) was reached."""


class AttachmentLimitError(ValidationError):
    """Compile issues on the ``adjuntos`` field (overflow/oversize, R2).

    Raised by ``publish()`` when the compiler rejects attachment entries
    (code ``invalid-value``/``oversized``, field ``adjuntos``); the API maps
    it to 422 ``attachment_limit_reached`` before the generic
    ``ValidationError`` handler.
    """


class TriggerInvalidError(ValidationError):
    """``approve_trigger()`` refused an empty/whitespace-only or over-bound trigger.

    Subclasses ``ValidationError`` so the API maps it to a dedicated
    ``trigger_invalid`` code without changing the existing ``validation_error``
    behavior of the compiler gate.
    """


class TriggerNotApprovedError(MethodologyLibraryError):
    """``publish()`` refused: no valid, matching trigger approval (fail-closed).

    Subclasses ``MethodologyLibraryError`` so it inherits the base publish
    boundary; the API MUST catch it BEFORE the generic
    ``MethodologyLibraryError`` handler so a gate refusal is never mislabeled
    as ``reserved_skill_id``.
    """


@dataclass(frozen=True)
class TriggerApproval:
    """An Author's explicit approval of a skill trigger (auditable record).

    ``text`` is the normalized (whitespace-collapsed) trigger, ``digest`` is
    ``normalized_trigger_digest(text)``, and ``approved_by``/``approved_at``
    record the attributable act. Persisted as a plain dict on the draft (and
    echoed onto the immutable published record); excluded from the manifest and
    compile digest (metadata, not identity).
    """

    text: str
    digest: str
    approved_by: str
    approved_at: str


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
    # TW14 provenance (TW13 adaptation): server-injected parent identity of a
    # derived draft, read from the PUBLISHED record by ``create_derived_draft``.
    # Optional with defaults so old records deserialize safely; EXCLUDED from
    # the manifest and digest (metadata, not identity — REQ-CC-22).
    parent_skill_id: str | None = None
    parent_version: str | None = None
    # Attachment entries (contract §4, SR4): metadata only, excluded from the
    # digest canonical (per-attachment sha256 IS the pin, D1). Optional with
    # defaults so old records deserialize safely.
    adjuntos: tuple[AttachmentEntry, ...] = ()
    # Trigger approval (Etapa 2): the Author's explicit, auditable approval of
    # this draft's trigger. Optional with a default so old records deserialize
    # safely; EXCLUDED from the manifest and compile digest (metadata, not
    # identity — like ``parent_skill_id``/``adjuntos``).
    trigger_approval: TriggerApproval | None = None


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
    # TW14 provenance: copied from the draft record at publish (server-injected
    # only; EXCLUDED from manifest/digest — REQ-CC-22).
    parent_skill_id: str | None = None
    parent_version: str | None = None
    # Attachment entries (contract §4, SR4): metadata only; excluded from the
    # digest canonical (per-attachment sha256 IS the pin, D1).
    adjuntos: tuple[AttachmentEntry, ...] = ()
    # Trigger approval provenance (Etapa 2): echoed from the draft's approval
    # at publish, immutable thereafter. Optional so old published records
    # deserialize safely; EXCLUDED from the manifest/digest (metadata, not
    # identity — like ``parent_skill_id``/``adjuntos``).
    trigger_approval: TriggerApproval | None = None


@dataclass(frozen=True)
class Activation:
    """The compiled methodology/version pinned to one world's flow slot."""

    world: str
    skill_id: str
    version: str
    digest: str
    activated_at: str
    # The guided-flow type this slot belongs to (SR1). None only for
    # companion entries, which are flow-less by design.
    flow_type: str | None = None


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_trigger(text: str) -> str:
    """Collapse all whitespace runs to single spaces and strip the ends.

    The single normalization used by approval, the publish gate, and the
    renderer, so insignificant whitespace differences never change the
    recorded approval or invalidate a matching one.
    """
    return " ".join(text.split())


def normalized_trigger_digest(text: str) -> str:
    """SHA-256 (hex) of the normalized trigger text, utf-8 encoded."""
    return hashlib.sha256(normalize_trigger(text).encode("utf-8")).hexdigest()


def _bump_version(version: str) -> str:
    """Deterministic ``version+1`` for derived publishes (REQ-CC-19).

    Increments the last numeric dot-segment of a bounded identifier:
    ``1.2.0 -> 1.2.1``, ``1.0 -> 1.1``, ``9 -> 10``. A non-numeric trailing
    segment (e.g. ``v1``) appends ``.1`` so the policy never fails closed on
    an unexpected shape; the compiler's ``MAX_VERSION_LEN`` bound still
    applies at publish.
    """
    parts = version.split(".")
    for index in range(len(parts) - 1, -1, -1):
        if parts[index].isdigit():
            parts[index] = str(int(parts[index]) + 1)
            return ".".join(parts[: index + 1])
    return f"{version}.1"


def _version_key(version: str) -> tuple[tuple[int, int | str], ...]:
    """Dependency-free version comparison key (dot-segment split).

    Each dot-segment maps to ``(0, int)`` when numeric, else ``(1, str)``, so
    ``1.2.0 > 1.1.9`` and ``1.0 < 1.0.1`` compare correctly without any
    packaging/semver dependency (design decision). Seed reconciliation uses it
    to decide "newer than all stored versions" for insert-only installs.
    """
    return tuple(
        (0, int(segment)) if segment.isdigit() else (1, segment)
        for segment in version.split(".")
    )


# Per-draft snapshot-on-update history cap (TW13 post-materialize edits).
# Mirrors the session history cap (REQ-CC-15 spirit): append-only, oldest
# evicted, so the file-backed store cannot grow without bound.
DRAFT_HISTORY_CAP = 50

# Per-world companion cap (skill-runtime-bridge): one companion slot per
# skill_id per world; adding a NEW skill beyond this many fails closed.
MAX_COMPANIONS_PER_WORLD = 8


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
        # Per-flow activation slots (SR1): {world: {flow_type: record}}.
        self._activations: dict[str, dict[str, dict[str, Any]]] = {}
        # Per-flow history stacks (SR1): {world: {flow_type: [records]}}.
        self._history: dict[str, dict[str, list[dict[str, Any]]]] = {}
        # TW13/TW14: per-draft snapshot-on-update history (post-materialize
        # edits). Append-only; capped at DRAFT_HISTORY_CAP per draft.
        self._draft_history: dict[str, list[dict[str, Any]]] = {}
        # Per-world companion skills (skill-runtime-bridge): many published
        # versions per world, one slot per skill_id; slot ops never touch it.
        self._companions: dict[str, list[dict[str, Any]]] = {}
        # Per-world native-channel flag (hermes-native-channel): {world: True}
        # for opted-in worlds; absent => OFF (design Q1).
        self._native_channel: dict[str, bool] = {}
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
        adjuntos: tuple[AttachmentEntry, ...] = (),
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
                "adjuntos": [entry.as_dict() for entry in adjuntos],
                "created_at": now,
                "updated_at": now,
            }
            self._save_locked()
        return draft_id

    def create_derived_draft(
        self,
        original_skill_id: str,
        original_version: str,
        seed_source: str,
        *,
        name: str,
        version: str | None = None,
        description: str | None = None,
        phases: tuple[str, ...] | None = None,
        language: str | None = None,
        taller: str | None = None,
        talleres_compatibles: tuple[str, ...] | None = None,
        categoria_funcional: str | None = None,
        etiquetas: tuple[str, ...] | None = None,
        clasificacion: str | None = None,
        trust_attributes: tuple[str, ...] | None = None,
    ) -> str:
        """Create a derived draft of a PUBLISHED skill (TW13/TW14).

        The parent identity is read from the PUBLISHED record server-side
        (REQ-CC-20): ``parent_skill_id``/``parent_version`` are injected from
        ``get_published(original_skill_id, original_version)`` and the client
        never supplies them. The version follows the ``version+1`` policy
        (REQ-CC-19): the draft is created as ``_bump_version(parent_version)``
        and any caller-supplied ``version`` must equal that value or the
        request fails closed. ``seed_source`` seeds the draft's source from
        the original; metadata fields default to the original's published
        values. The original stays intact until the derived draft is
        explicitly published AND activated.

        Trust semantics (S9): a derived fork is local authorship, so
        ``clasificacion`` is FORCED to ``Personalizadas`` (any caller-supplied
        value is ignored) and ``trust_attributes`` are scrubbed of
        ``fundacional`` while other inherited attributes (e.g. ``verified``)
        are kept. TW14 provenance is injected below and survives to publish.
        """
        original = self.get_published(original_skill_id, original_version)
        if original is None:
            raise NotPublishedError(
                f"{original_skill_id}@{original_version} is not published"
            )
        expected = _bump_version(original.version)
        if version is not None and version != expected:
            raise ValidationError(
                f"derived draft of {original_skill_id}@{original.version} "
                f"must be version {expected!r}, got {version!r}"
            )
        draft_id = uuid.uuid4().hex[:12]
        now = _utcnow()
        with self._lock:
            self._drafts[draft_id] = {
                "draft_id": draft_id,
                "skill_id": original.skill_id,
                "version": expected,
                "name": name,
                "source": seed_source,
                "description": (
                    description if description is not None else original.description
                ),
                "phases": list(phases if phases is not None else original.phases),
                "language": language if language is not None else original.language,
                "taller": taller if taller is not None else original.taller,
                "talleres_compatibles": list(
                    talleres_compatibles
                    if talleres_compatibles is not None
                    else original.talleres_compatibles
                ),
                "categoria_funcional": (
                    categoria_funcional
                    if categoria_funcional is not None
                    else original.categoria_funcional
                ),
                "etiquetas": list(
                    etiquetas if etiquetas is not None else original.etiquetas
                ),
                # S9: a derived fork is local authorship — classification is
                # forced to Personalizadas unconditionally and the
                # ``fundacional`` marker is scrubbed from the inherited trust
                # attributes (other attributes like ``verified`` are kept).
                # TW14 provenance (parent_skill_id/parent_version) is
                # injected below and stays intact.
                "clasificacion": PERSONALIZADAS,
                "trust_attributes": list(scrub_foundational(
                    tuple(trust_attributes)
                    if trust_attributes is not None
                    else original.trust_attributes
                )),
                "parent_skill_id": original.skill_id,
                "parent_version": original.version,
                # EP-1/DP-1: the derived fork preserves the parent's exemplar
                # pins. Server-injected from the PUBLISHED record exactly like
                # the provenance above (never a client parameter), so adapting
                # an N-exemplar skill yields an N-exemplar draft. An original
                # with no pins writes an empty list (no regression).
                "adjuntos": [entry.as_dict() for entry in original.adjuntos],
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
        taller: str | None = None,
        talleres_compatibles: tuple[str, ...] | None = None,
        categoria_funcional: str | None = None,
        etiquetas: tuple[str, ...] | None = None,
        clasificacion: str | None = None,
        trust_attributes: tuple[str, ...] | None = None,
        provenance: tuple[str, str] | None = None,
        adjuntos: tuple[AttachmentEntry, ...] | None = None,
    ) -> Draft:
        """Update a draft, snapshotting the previous state (TW13/TW14).

        Extends the Fase 4 field set with the inventory metadata
        (``taller``/``talleres_compatibles``/``categoria_funcional``/
        ``etiquetas``/``clasificacion``/``trust_attributes``). Every update
        appends an immutable ``{ts, record}`` snapshot of the PRE-update
        record to the per-draft history (``_draft_history``, cap
        ``DRAFT_HISTORY_CAP``) — the post-materialize edit trace.

        ``provenance`` is SERVER-INTERNAL only: it accepts ``(skill_id,
        version)`` and is never wired to any client route (REQ-CC-20 —
        provenance is server-injected; a client can never forge or mutate it).
        ``skill_id``/``version`` themselves are immutable after creation.

        ``adjuntos`` (S2) writes the metadata-only attachment pins when
        provided; ``None`` (the default) leaves the existing pins untouched so
        a metadata edit can never silently drop carriers. The pre-update pins
        are captured in the history snapshot for free.
        """
        with self._lock:
            record = self._drafts.get(draft_id)
            if record is None:
                raise KeyError(f"draft {draft_id!r} not found")
            before = deepcopy(record)
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
            if taller is not None:
                record["taller"] = taller
            if talleres_compatibles is not None:
                record["talleres_compatibles"] = list(talleres_compatibles)
            if categoria_funcional is not None:
                record["categoria_funcional"] = categoria_funcional
            if etiquetas is not None:
                record["etiquetas"] = list(etiquetas)
            if clasificacion is not None:
                record["clasificacion"] = clasificacion
            if trust_attributes is not None:
                record["trust_attributes"] = list(trust_attributes)
            if provenance is not None:
                record["parent_skill_id"], record["parent_version"] = provenance
            if adjuntos is not None:
                record["adjuntos"] = [entry.as_dict() for entry in adjuntos]
            now = _utcnow()
            history = self._draft_history.setdefault(draft_id, [])
            history.append({"ts": now, "record": before})
            if len(history) > DRAFT_HISTORY_CAP:
                del history[: len(history) - DRAFT_HISTORY_CAP]
            record["updated_at"] = now
            self._save_locked()
            return self._draft_from(record)

    def approve_trigger(
        self, draft_id: str, text: str, approved_by: str
    ) -> TriggerApproval:
        """Record an explicit Author approval of a draft's trigger.

        Normalizes ``text`` (whitespace-collapsed) and refuses an empty result
        or one longer than ``TRIGGER_INTAKE_LIMIT`` with ``TriggerInvalidError``
        (the server bound is authoritative over the client). Then, under ONE
        lock, writes the normalized value as the draft's ``description`` AND the
        auditable ``trigger_approval`` sub-record in a single atomic save
        (TD-B), so the approved value equals the draft description by
        construction. The approval stays bound to the value it was granted for:
        a later ``update_draft(description=...)`` does not mutate it
        (distinctness — REQ ``skill-trigger-approval``). Raises ``KeyError`` for
        an unknown draft.
        """
        normalized = normalize_trigger(text)
        if not normalized or len(normalized) > TRIGGER_INTAKE_LIMIT:
            raise TriggerInvalidError(
                "trigger must be non-empty and at most "
                f"{TRIGGER_INTAKE_LIMIT} characters after normalization"
            )
        approval = TriggerApproval(
            text=normalized,
            digest=normalized_trigger_digest(normalized),
            approved_by=approved_by,
            approved_at=_utcnow(),
        )
        with self._lock:
            record = self._drafts.get(draft_id)
            if record is None:
                raise KeyError(f"draft {draft_id!r} not found")
            record["description"] = normalized
            record["trigger_approval"] = asdict(approval)
            self._save_locked()
        return approval

    def list_draft_history(self, draft_id: str) -> list[dict[str, Any]]:
        """Immutable per-draft snapshot-on-update history (TW13).

        Each entry is ``{ts, record}`` where ``record`` is the draft record
        BEFORE the update that appended it (append-only, oldest first).
        """
        with self._lock:
            return [deepcopy(entry) for entry in self._draft_history.get(draft_id, [])]

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
            "adjuntos": [entry.as_dict() for entry in draft.adjuntos],
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
            "adjuntos": [entry.as_dict() for entry in draft.adjuntos],
        }

    # ------------------------------------------------------------------ #
    # Publishing (immutable)
    # ------------------------------------------------------------------ #

    def publish(self, draft_id: str) -> PublishedVersion:
        result = self.compile_draft(draft_id)
        if not result.ok or result.compiled is None:
            # R2: attachment-limit compile failures (field ``adjuntos`` with
            # code ``invalid-value``/``oversized``) surface as a distinct
            # error so the API maps them to 422 ``attachment_limit_reached``
            # BEFORE the generic ValidationError handler.
            if any(
                issue.field == "adjuntos"
                and issue.code in ("invalid-value", "oversized")
                for issue in result.issues
            ):
                raise AttachmentLimitError(
                    "draft failed compiler validation: "
                    + "; ".join(issue.message for issue in result.issues)
                )
            raise ValidationError(
                "draft failed compiler validation: "
                + "; ".join(issue.message for issue in result.issues)
            )
        compiled = result.compiled
        key = self._key(compiled.skill_id, compiled.version)
        now = _utcnow()
        with self._lock:
            draft_record = self._drafts.get(draft_id) or {}
            # REQ-IMP-6: this id belongs to the author-created foundational
            # character-creation skill and is never publishable from an import-derived
            # draft (server-injected ``parent_skill_id``). The Skill Madre is a core
            # co-creation capability outside this library (G13) — no guard needed here.
            if (
                compiled.skill_id == FOUNDATIONAL_CHARACTER_SKILL_ID
                and draft_record.get("parent_skill_id")
            ):
                raise MethodologyLibraryError("reserved_skill_id")
            parent_version = draft_record.get("parent_version")
            if parent_version is not None:
                # REQ-CC-19: a derived draft publishes as parent_version+1.
                # Enforced here, at the publish boundary, BEFORE any immutability
                # lookup, so even a tampered draft record cannot publish at the
                # wrong version.
                expected = _bump_version(str(parent_version))
                if compiled.version != expected:
                    raise ValidationError(
                        f"derived draft of {compiled.skill_id}@{parent_version} "
                        f"must publish as version {expected!r}, got {compiled.version!r}"
                    )
            existing = self._published.get(key)
            if existing is not None:
                if existing["digest"] == compiled.digest:
                    return self._published_from(existing)
                raise AlreadyPublishedError(
                    f"{compiled.skill_id}@{compiled.version} is already published "
                    "with different content; published versions are immutable."
                )
            # Trigger approval gate (Etapa 2, TD-A). It sits AFTER the
            # idempotent early-return above so an identical re-publish is never
            # newly refused (forward-only grandfathering, D5), and it validates
            # the digest of ``compiled.description`` — the exact value
            # ``_published_record`` writes — so any change between approval and
            # publish (including a last-moment ``draft_payload["description"]``
            # sync) fails closed by construction. No immutable version is
            # created on refusal and no publish-side state advances.
            approval_record = draft_record.get("trigger_approval")
            if (
                not approval_record
                or approval_record.get("digest")
                != normalized_trigger_digest(compiled.description)
            ):
                raise TriggerNotApprovedError("trigger_not_approved")
            record = self._published_record(
                compiled,
                now=now,
                # Local-author semantics (G14): a plain draft publishes as
                # Personalizadas with no trust attributes — the server never
                # carries a client-claimed value. Server-derived values
                # (Oficiales/Comunitarias from the import trust path) pass
                # through untouched.
                clasificacion=draft_record.get("clasificacion") or PERSONALIZADAS,
                trust_attributes=tuple(draft_record.get("trust_attributes") or ()),
                # TW14: provenance threads through to the published record so
                # it stays visible across the lifecycle (REQ-CC-21).
                parent_skill_id=draft_record.get("parent_skill_id"),
                parent_version=parent_version,
                # Etapa 2: echo the validated approval onto the immutable
                # published record so downstream consumes an approved trigger
                # by construction; the record is never rewritten afterwards.
                trigger_approval=TriggerApproval(**approval_record),
            )
            self._published[key] = record
            self._save_locked()
            return self._published_from(record)

    def published_versions_for(self, skill_id: str) -> list[dict[str, str]]:
        """Version + digest records of the published (non-deleted) versions of a skill.

        The input to seed reconciliation: only live versions gate installs, so
        soft-deleted records are excluded. Sorted ascending by version key for
        deterministic output.
        """
        with self._lock:
            records = [
                {
                    "skill_id": record["skill_id"],
                    "version": record["version"],
                    "digest": record["digest"],
                }
                for record in self._published.values()
                if record.get("skill_id") == skill_id and not record.get("deleted_at")
            ]
        records.sort(key=lambda record: _version_key(record["version"]))
        return records

    @staticmethod
    def _published_record(
        compiled: CompiledMethodology,
        *,
        now: str,
        clasificacion: str | None,
        trust_attributes: tuple[str, ...],
        parent_skill_id: str | None = None,
        parent_version: str | None = None,
        trigger_approval: TriggerApproval | None = None,
    ) -> dict[str, Any]:
        """Build the immutable published record dict shared by publish paths.

        Single source of truth for the record shape: ``publish()`` and
        ``install_published_version()`` both land here, so a seeded record and
        a draft-published record carry the same fields. Classification and
        trust attributes arrive server-derived (never client-claimed).
        ``trigger_approval`` is the approved-trigger echo; the seed path passes
        ``None`` (it bypasses the publish gate — forward-only grandfathering).
        """
        return {
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
            "clasificacion": clasificacion,
            "trust_attributes": list(trust_attributes),
            "parent_skill_id": parent_skill_id,
            "parent_version": parent_version,
            "adjuntos": [entry.as_dict() for entry in compiled.adjuntos],
            # Etapa 2: approved-trigger provenance. ``None`` for a seeded record
            # (no draft, no approval) and for pre-Etapa-2 records; tolerant read.
            "trigger_approval": (
                asdict(trigger_approval) if trigger_approval is not None else None
            ),
        }

    def install_published_version(
        self,
        compiled: CompiledMethodology,
        *,
        clasificacion: str,
        trust_attributes: tuple[str, ...],
    ) -> Literal["installed", "existing", "stale", "conflict"]:
        """Install a compiled methodology version as an immutable published record.

        The server-side install path for repo-bundled foundational seeds (no
        draft is created). Serialized under the same store lock as every other
        mutation; insert-only — activations and companions are never touched
        (TW15) and an existing record is never overwritten.

        Two-axis invariant (G14): the ``fundacional`` trust attribute may only
        accompany the ``Oficiales`` classification — enforced by assertion,
        since only server install paths may set these values.

        Outcomes:
        - ``installed`` — the key was absent and no stored version is newer.
        - ``existing`` — the exact same version+digest is already published
          (idempotent rerun; skipped, not re-written — except the R8
          ``adjuntos`` upsert: a digest-equal seed whose attachment pins are
          non-empty and differ backfills them onto the stored record).
        - ``stale`` — a newer non-deleted version of the skill is already
          stored; insert-only reconciliation skips older seeds.
        - ``conflict`` — the same version is stored with a DIFFERENT digest:
          logged and PERMANENTLY skipped. Immutability over auto-heal: the
          stored bytes win and the conflicting seed version is never
          re-installed (by design).
        """
        assert not (
            FOUNDATIONAL in trust_attributes and clasificacion != OFFICIAL
        ), "fundacional trust may only accompany Oficiales classification"
        key = self._key(compiled.skill_id, compiled.version)
        with self._lock:
            existing = self._published.get(key)
            if existing is not None:
                if existing["digest"] == compiled.digest:
                    desired = [entry.as_dict() for entry in compiled.adjuntos]
                    if desired and list(existing.get("adjuntos") or []) != desired:
                        existing["adjuntos"] = desired
                        self._save_locked()
                    return "existing"
                logger.warning(
                    "seed install conflict: %s@%s is already published with a "
                    "different digest; skipping (immutability over auto-heal)",
                    compiled.skill_id, compiled.version,
                )
                return "conflict"
            # Insert-only reconciliation: never install when a newer live
            # version of the skill is already stored (soft-deleted versions
            # do not gate — they are not published).
            for record in self._published.values():
                if (
                    record.get("skill_id") == compiled.skill_id
                    and not record.get("deleted_at")
                    and _version_key(record["version"]) > _version_key(compiled.version)
                ):
                    return "stale"
            record = self._published_record(
                compiled,
                now=_utcnow(),
                clasificacion=clasificacion,
                trust_attributes=trust_attributes,
                # Seed path: no draft and no approval — it deliberately bypasses
                # the publish gate, so the installed record carries no trigger
                # approval (forward-only grandfathering, D5).
                trigger_approval=None,
            )
            self._published[key] = record
            self._save_locked()
            return "installed"

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

    def is_deleted(self, skill_id: str, version: str) -> bool:
        """True when the exact version exists but has been soft-deleted."""
        with self._lock:
            record = self._published.get(self._key(skill_id, version))
            return bool(record is not None and record.get("deleted_at"))

    def soft_delete(self, skill_id: str, version: str) -> None:
        key = self._key(skill_id, version)
        with self._lock:
            record = self._published.get(key)
            if record is None:
                raise NotPublishedError(f"{skill_id}@{version} is not published")
            # S10: a foundational record is immutable — reject BEFORE any
            # mutation (record, activations, and companions stay untouched).
            # Guard keys on the ``fundacional`` attribute, not the category.
            if FOUNDATIONAL in (record.get("trust_attributes") or ()):
                raise FoundationalImmutableError(
                    f"{skill_id}@{version} is a foundational skill and cannot be deleted"
                )
            record["deleted_at"] = _utcnow()
            # A deleted version cannot stay active in any flow slot.
            for world, flows in list(self._activations.items()):
                for flow in list(flows):
                    active = flows[flow]
                    if active.get("skill_id") == skill_id and active.get("version") == version:
                        del flows[flow]
                if not flows:
                    self._activations.pop(world, None)
            # ...nor can it stay a companion anywhere.
            for world, companions in list(self._companions.items()):
                remaining = [
                    entry for entry in companions
                    if not (entry.get("skill_id") == skill_id
                            and entry.get("version") == version)
                ]
                if remaining:
                    self._companions[world] = remaining
                else:
                    self._companions.pop(world, None)
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
    # Guided-character method eligibility
    # ------------------------------------------------------------------ #

    def is_guided_character_method(self, skill_id: str) -> bool:
        """True when ``skill_id`` belongs to the character-creation family.

        The guided-character assistant may only consume methods that produce
        characters. Membership is declared by lineage, never by catalog
        metadata: the foundational character skill, the builtin contract id,
        and every skill derived from the foundational one (``parent_skill_id``
        chain). Cronología, Sistemas and unrelated skills are excluded.
        """
        with self._lock:
            return self._is_guided_character_method_locked(skill_id)

    def _is_guided_character_method_locked(self, skill_id: str) -> bool:
        current = skill_id
        seen: set[str] = set()
        for _ in range(32):
            if current in GUIDED_CHARACTER_METHOD_ROOTS:
                return True
            if not current or current in seen:
                return False
            seen.add(current)
            parent = self._parent_skill_id_locked(current)
            if parent is None:
                return False
            current = parent
        return False

    def _parent_skill_id_locked(self, skill_id: str) -> str | None:
        records = sorted(
            (
                record
                for record in self._published.values()
                if record.get("skill_id") == skill_id
                and not record.get("deleted_at")
                and record.get("parent_skill_id")
            ),
            key=lambda record: _version_key(record["version"]),
        )
        if not records:
            return None
        return str(records[-1]["parent_skill_id"])

    def list_guided_methods(self) -> list[PublishedVersion]:
        """Latest published version of every eligible guided-character method."""
        with self._lock:
            latest: dict[str, dict[str, Any]] = {}
            for record in self._published.values():
                if record.get("deleted_at"):
                    continue
                skill_id = str(record["skill_id"])
                if not self._is_guided_character_method_locked(skill_id):
                    continue
                current = latest.get(skill_id)
                if current is None or _version_key(record["version"]) > _version_key(
                    current["version"]
                ):
                    latest[skill_id] = record
            ordered = sorted(
                latest.values(),
                key=lambda record: (
                    str(record.get("name") or record["skill_id"]).lower(),
                    str(record["skill_id"]),
                ),
            )
            return [self._published_from(record) for record in ordered]

    # ------------------------------------------------------------------ #
    # Activation by world and flow type
    # ------------------------------------------------------------------ #

    def activate(
        self,
        world: str,
        skill_id: str,
        version: str,
        flow_type: str = DEFAULT_FLOW_TYPE,
    ) -> Activation:
        """Pin a published version to ``world``'s ``flow_type`` slot (SR1).

        One activation slot per guided-flow type per world: activating a flow
        moves that flow's previous pin onto its history stack; other flows'
        slots are untouched. Unsupported flow types fail closed BEFORE any
        mutation.
        """
        if flow_type not in SUPPORTED_FLOW_TYPES:
            raise ValidationError(f"unsupported flow type {flow_type!r}")
        with self._lock:
            record = self._published.get(self._key(skill_id, version))
            if record is None or record.get("deleted_at"):
                raise NotPublishedError(f"{skill_id}@{version} is not published")
            digest = str(record["digest"])
            now = _utcnow()
            flows = self._activations.setdefault(world, {})
            previous = flows.get(flow_type)
            if previous is not None:
                self._history.setdefault(world, {}).setdefault(flow_type, []).append(
                    dict(previous)
                )
            flows[flow_type] = {
                "world": world,
                "skill_id": skill_id,
                "version": version,
                "digest": digest,
                "activated_at": now,
                "flow_type": flow_type,
            }
            self._save_locked()
            return self._activation_from(flows[flow_type])

    def active_for(
        self,
        world: str,
        flow_type: str = DEFAULT_FLOW_TYPE,
    ) -> Activation | None:
        with self._lock:
            record = (self._activations.get(world) or {}).get(flow_type)
            return self._activation_from(record) if record else None

    def deactivate(self, world: str, flow_type: str = DEFAULT_FLOW_TYPE) -> None:
        with self._lock:
            flows = self._activations.get(world)
            if flows is not None:
                flows.pop(flow_type, None)
                if not flows:
                    self._activations.pop(world, None)
            self._save_locked()

    def next_rollback(
        self,
        world: str,
        flow_type: str = DEFAULT_FLOW_TYPE,
    ) -> dict[str, Any] | None:
        """Read-only peek at the record a ``rollback`` would restore.

        Used by the API boundary to refuse restoring an ineligible guided
        method before any mutation (S4).
        """
        with self._lock:
            history = (self._history.get(world) or {}).get(flow_type) or []
            return dict(history[-1]) if history else None

    def rollback(
        self,
        world: str,
        flow_type: str = DEFAULT_FLOW_TYPE,
    ) -> Activation | None:
        with self._lock:
            history = (self._history.get(world) or {}).get(flow_type) or []
            flows = self._activations.get(world)
            if not history:
                if flows is not None:
                    flows.pop(flow_type, None)
                    if not flows:
                        self._activations.pop(world, None)
                self._save_locked()
                return None
            restored = history.pop()
            if flows is None:
                flows = self._activations.setdefault(world, {})
            flows[flow_type] = restored
            self._save_locked()
            return self._activation_from(restored)

    # ------------------------------------------------------------------ #
    # Companions by world
    # ------------------------------------------------------------------ #

    def add_companion(self, world: str, skill_id: str, version: str) -> Activation:
        """Pin a PUBLISHED version as a companion skill of ``world``.

        One companion slot per skill_id per world: re-adding the same
        skill_id replaces its version (a same-version re-add is a no-op that
        returns the existing entry untouched). Adding a NEW skill past
        ``MAX_COMPANIONS_PER_WORLD`` fails closed. Companion state is fully
        independent of the activation slot (``activate``/``active_for``/
        ``rollback`` never read or write it).
        """
        with self._lock:
            record = self._published.get(self._key(skill_id, version))
            if record is None or record.get("deleted_at"):
                raise NotPublishedError(f"{skill_id}@{version} is not published")
            companions = self._companions.setdefault(world, [])
            existing = next(
                (entry for entry in companions if entry.get("skill_id") == skill_id),
                None,
            )
            if existing is not None:
                if existing.get("version") == version:
                    return self._activation_from(existing)
                existing["version"] = version
                existing["digest"] = str(record["digest"])
                existing["activated_at"] = _utcnow()
                self._save_locked()
                return self._activation_from(existing)
            if len(companions) >= MAX_COMPANIONS_PER_WORLD:
                raise CompanionLimitError(
                    f"world {world!r} already has {MAX_COMPANIONS_PER_WORLD} companions"
                )
            now = _utcnow()
            entry = {
                "world": world,
                "skill_id": skill_id,
                "version": version,
                "digest": str(record["digest"]),
                "activated_at": now,
            }
            companions.append(entry)
            self._save_locked()
            return self._activation_from(entry)

    def remove_companion(self, world: str, skill_id: str) -> bool:
        """Remove ``skill_id`` from ``world``'s companions (idempotent)."""
        with self._lock:
            companions = self._companions.get(world)
            if not companions:
                return False
            remaining = [
                entry for entry in companions if entry.get("skill_id") != skill_id
            ]
            removed = len(remaining) != len(companions)
            if remaining:
                self._companions[world] = remaining
            else:
                self._companions.pop(world, None)
            if removed:
                self._save_locked()
            return removed

    def list_companions(self, world: str) -> list[Activation]:
        """Companion skills of ``world`` in storage (insertion) order."""
        with self._lock:
            return [
                self._activation_from(entry)
                for entry in self._companions.get(world, [])
            ]

    # ------------------------------------------------------------------ #
    # Native channel flag by world
    # ------------------------------------------------------------------ #

    def native_channel_enabled(self, world: str) -> bool:
        """Whether ``world`` has opted into the native Hermes channel.

        Tolerant read (design Q1 / REQ-NC-2): an absent, unset, or invalid
        flag is OFF, so a legacy world is never auto-enabled. Thread-safe.
        """
        with self._lock:
            return self._native_channel.get(str(world), False)

    def set_native_channel(self, world: str, enabled: bool) -> None:
        """Set (or clear) ``world``'s native-channel opt-in, persisted atomically.

        Enabling stores ``True``; disabling removes the key so the store stays
        minimal and an absent flag reads OFF. Mirrors ``deactivate``'s
        pop-if-empty pattern.
        """
        with self._lock:
            key = str(world)
            if enabled:
                self._native_channel[key] = True
            else:
                self._native_channel.pop(key, None)
            self._save_locked()

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
        # Read-only coercion (design D3): memory is ALWAYS per-flow nested;
        # the file is never rewritten at load — the first mutating save
        # persists the nested shape under the stable keys.
        self._activations = self._coerce_activations(payload.get("activations") or {})
        self._history = self._coerce_history(payload.get("history") or {})
        self._draft_history = {
            draft_id: list(stack)
            for draft_id, stack in (payload.get("draft_history") or {}).items()
        }
        self._companions = dict(payload.get("companions") or {})
        self._native_channel = self._coerce_native_channel(
            payload.get("native_channel") or {}
        )

    @staticmethod
    def _coerce_activations(
        raw: Mapping[str, Any],
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Normalize on-disk activations to the per-flow shape (design D1/D3).

        Legacy world-keyed records (the value has a ``skill_id`` key) map into
        the ``guided-character`` slot preserving every field; nested per-flow
        maps pass through. Read-only — no mutation of the raw payload.
        """
        coerced: dict[str, dict[str, dict[str, Any]]] = {}
        for world, value in raw.items():
            if not isinstance(value, dict):
                continue
            if "skill_id" in value:
                coerced[world] = {DEFAULT_FLOW_TYPE: dict(value)}
            else:
                coerced[world] = {
                    flow: dict(record)
                    for flow, record in value.items()
                    if isinstance(record, dict)
                }
        return coerced

    @staticmethod
    def _coerce_history(
        raw: Mapping[str, Any],
    ) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """Normalize on-disk history to the per-flow shape (design D1/D3).

        Legacy world-keyed stacks (the value is a ``list``) map into the
        ``guided-character`` slot; per-flow maps pass through. Read-only.
        """
        coerced: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for world, value in raw.items():
            if isinstance(value, list):
                coerced[world] = {
                    DEFAULT_FLOW_TYPE: [dict(entry) for entry in value],
                }
            elif isinstance(value, dict):
                coerced[world] = {
                    flow: [dict(entry) for entry in stack]
                    for flow, stack in value.items()
                    if isinstance(stack, list)
                }
            else:
                coerced[world] = {}
        return coerced

    @staticmethod
    def _coerce_native_channel(raw: Mapping[str, Any]) -> dict[str, bool]:
        """Normalize the on-disk ``native_channel`` map to ``{world: True}``.

        Tolerant read (design Q1 / spec REQ-NC-2): absent, non-mapping, or
        non-bool values are dropped — only an explicit boolean ``True`` opts a
        world in, so every other value degrades to OFF. Read-only.
        """
        if not isinstance(raw, Mapping):
            return {}
        return {
            str(world): True
            for world, value in raw.items()
            if isinstance(value, bool) and value is True
        }

    def _save_locked(self) -> None:
        # ``activations``/``history`` are written in the per-flow nested shape
        # (memory is always nested post-coercion) under the stable keys.
        payload = {
            "drafts": self._drafts,
            "published": self._published,
            "activations": self._activations,
            "companions": self._companions,
            "history": self._history,
            "draft_history": self._draft_history,
            "native_channel": self._native_channel,
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
            parent_skill_id=record.get("parent_skill_id"),
            parent_version=record.get("parent_version"),
            adjuntos=tuple(
                AttachmentEntry(**entry) for entry in (record.get("adjuntos") or ())
            ),
            # Tolerant read (Etapa 2): records predating the field (or drafts
            # never approved) deserialize to None without error.
            trigger_approval=(
                TriggerApproval(**record["trigger_approval"])
                if record.get("trigger_approval")
                else None
            ),
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
            parent_skill_id=record.get("parent_skill_id"),
            parent_version=record.get("parent_version"),
            adjuntos=tuple(
                AttachmentEntry(**entry) for entry in (record.get("adjuntos") or ())
            ),
            # Tolerant read (Etapa 2): published records predating the field
            # deserialize to None without error (no read path crashes).
            trigger_approval=(
                TriggerApproval(**record["trigger_approval"])
                if record.get("trigger_approval")
                else None
            ),
        )

    @staticmethod
    def _activation_from(record: Mapping[str, Any]) -> Activation:
        return Activation(
            world=record["world"],
            skill_id=record["skill_id"],
            version=record["version"],
            digest=record["digest"],
            activated_at=record.get("activated_at", ""),
            # Per-flow slots carry ``flow_type``; companion entries (which are
            # flow-less by design) read it as None.
            flow_type=record.get("flow_type"),
        )
