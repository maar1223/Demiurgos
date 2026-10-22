"""
OKF v1 contract — identity, relationship conventions, and per-entity minimums.

Server-owned validation layer for OKF v1 world files.  Pure and read-only:
nothing in this module writes to the filesystem or to canon.  It decides what
an OKF v1 file IS (identity), how relationships are expressed (``[[Name]]``
wikilinks and ``relaciones`` frontmatter), and what a complete entity needs
(extensible per-type minimums, with characters first).

Callers (graph index, sync-lore normalization, guidance) use ``validate`` to
surface missing minimums and ambiguous/unresolved references instead of
silently writing incomplete canon.  World-agnostic by design: no entity type,
field, or directory is coupled to a specific fictional universe.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import yaml

OKF_VERSION = "1"

# Relationship conventions: a relationship is a [[Name]] wikilink, either in
# the body or inside the `relaciones` frontmatter list.
RELACIONES_FIELD = "relaciones"
VERSION_FIELD = "okf_version"

# Canonical identity convention (importer): a parent-qualified ``id`` built
# from NFC-normalized, whitespace-collapsed heading segments joined by ``::``,
# with ``#N`` ordinals for duplicate same-title siblings. Simple single-
# segment ids (a lone H1 root) are valid canonical ids too.
CANONICAL_ID_SEPARATOR = "::"

_RE_FRONTMATTER_START = re.compile(r"^---\s*$")
_RE_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")

# Server-owned minimum identity anchors, aligned with the guided character
# contract (guided_character_domain.MINIMUM_IDENTITY_FIELDS /
# MINIMUM_DESIRE_FIELDS).  A group is satisfied when at least one of its
# alternative fields is present in frontmatter.  ``id`` is the canonical
# importer identity (``::``-qualified); the guided ficha writer already emits
# ``id: <slug>``, so ``id`` participates in identity as a first-class anchor.
MINIMUM_IDENTITY_FIELDS = frozenset({"name", "nombre", "title", "id"})
# The guided conversation must elicit a human title, not only the server-owned
# slug: ``id`` alone would let an unnamed entity pass the completion gate.
MINIMUM_NAME_FIELDS = frozenset({"name", "nombre", "title"})
MINIMUM_DESIRE_FIELDS = frozenset({
    "desire", "deseo", "motivacion", "motivations", "motivation", "motivaciones",
})

# Extensible per-entity minimums, characters first.
OKF_MINIMUM_GROUPS_BY_TYPE: dict[str, tuple[frozenset[str], ...]] = {
    "personaje": (MINIMUM_IDENTITY_FIELDS, MINIMUM_DESIRE_FIELDS),
}

# ---------------------------------------------------------------------------
# Shape vocabulary (kernel-owned, world-agnostic)
# ---------------------------------------------------------------------------
# A "shape" is the kernel's coarse structural class for an entity: it decides
# which base minimums apply, independently of the world-owned ``type`` label.
# ``RESERVED_SHAPES`` names a shape the MVP deliberately does NOT activate yet;
# it is documented here so the vocabulary stays closed and auditable.
SHAPES = ("entidad", "sistema", "cronologia")
RESERVED_SHAPES = ("relacion",)  # documented, not active in the MVP
DEFAULT_SHAPE = "entidad"

# Legacy and casing variants collapse onto a canonical type label. Keys are
# already whitespace-stripped/lowercased by ``normalize_type``; entries map to
# themselves today, and this dict is the seam where future synonyms are added.
_TYPE_ALIASES: dict[str, str] = {
    "criatura": "criatura",
    "personaje": "personaje",
    "lugar": "lugar",
    "faccion": "faccion",
    "artefacto": "artefacto",
    "cultura": "cultura",
    "objeto": "objeto",
    "especie": "especie",
    "concepto": "concepto",
    "sistema": "sistema",
    "evento": "evento",
    "historia": "historia",
}

# Kernel-owned type -> shape map. Auditable and extensible: a world may extend
# it later through a declarative seam (not built in the MVP).
SHAPE_BY_TYPE: dict[str, str] = {
    # entidad
    "personaje": "entidad",
    "lugar": "entidad",
    "criatura": "entidad",
    "faccion": "entidad",
    "artefacto": "entidad",
    "cultura": "entidad",
    "objeto": "entidad",
    "especie": "entidad",
    "concepto": "entidad",
    "ficha": "entidad",
    "referencia_visual": "entidad",
    # sistema
    "sistema": "sistema",
    "magia": "sistema",
    "tecnologia": "sistema",
    "economia": "sistema",
    "ley": "sistema",
    "religion": "sistema",
    # cronologia
    "cronologia": "cronologia",
    "historia": "cronologia",
    "evento": "cronologia",
    "era": "cronologia",
}

# Shape base minimums: every entity of a shape must satisfy these groups,
# independently of its world-owned type.  A group is satisfied when any of its
# alternative fields is present in frontmatter.  ``entidad`` reuses the
# identity anchors; ``sistema``/``cronologia`` define their own base fields.
MINIMUM_SISTEMA_FIELDS = frozenset({
    "origen", "fuente", "source", "principio", "premisa",
})
# The locked System method rail: "el límite no se evade" (foundational §4.3).
# It stays a semantic question in the method, but the envelope also requires a
# persisted limit so an accepted system can never be written complete without
# one. Accepted alternatives cover singular/plural and the English label.
MINIMUM_SISTEMA_LIMIT_FIELDS = frozenset({
    "limite", "limites", "limitacion", "limitaciones", "limit", "limits",
})
MINIMUM_CRONOLOGIA_FIELDS = frozenset({
    "evento", "event", "fecha", "date", "era", "periodo",
})
MINIMUM_GROUPS_BY_SHAPE: dict[str, tuple[frozenset[str], ...]] = {
    "entidad": (MINIMUM_IDENTITY_FIELDS,),
    "sistema": (
        MINIMUM_IDENTITY_FIELDS,
        MINIMUM_SISTEMA_FIELDS,
        MINIMUM_SISTEMA_LIMIT_FIELDS,
    ),
    "cronologia": (MINIMUM_CRONOLOGIA_FIELDS,),
}


def normalize_type(raw: str) -> str:
    """Normalize a world-owned ``type`` label (strip + lowercase + alias).

    Pure and deterministic.  The result is the canonical label used as the
    registry key; unknown labels are returned lowercased unchanged so the
    mapping layer can default them.
    """
    if raw is None:
        return ""
    normalized = str(raw).strip().lower()
    return _TYPE_ALIASES.get(normalized, normalized)


def shape_for_type(entity_type: str) -> str:
    """Map a world-owned ``type`` label to its kernel shape.

    Unknown and empty labels default to ``DEFAULT_SHAPE``.
    """
    return SHAPE_BY_TYPE.get(normalize_type(entity_type), DEFAULT_SHAPE)


def minimums_for_shape(shape: str) -> tuple[frozenset[str], ...]:
    """Return the base minimum groups for a kernel shape (empty when unknown)."""
    if not isinstance(shape, str):
        return ()
    return MINIMUM_GROUPS_BY_SHAPE.get(shape.strip().lower(), ())


# Completion (conversation) groups per shape: what the guided flow must elicit
# before a provider delta may become a proposal.  Deliberately narrower than the
# file-envelope minimums: the server writes ``id`` itself, so identity here
# means a human title (``MINIMUM_NAME_FIELDS``).  Type extras still compose in
# through ``prompt_minimums_for``.
PROMPT_MINIMUM_GROUPS_BY_SHAPE: dict[str, tuple[frozenset[str], ...]] = {
    "entidad": (MINIMUM_NAME_FIELDS,),
    "sistema": (
        MINIMUM_NAME_FIELDS,
        MINIMUM_SISTEMA_FIELDS,
        MINIMUM_SISTEMA_LIMIT_FIELDS,
    ),
    "cronologia": (MINIMUM_NAME_FIELDS, MINIMUM_CRONOLOGIA_FIELDS),
}


def prompt_minimums_for(entity_type: str) -> tuple[frozenset[str], ...]:
    """Return the groups the guided conversation must elicit for a type.

    Shape base groups come first, then registered type-specific extras
    (deduplicated), mirroring ``minimums_for`` but with the completion
    identity group instead of the file-envelope one.
    """
    groups: list[frozenset[str]] = list(
        PROMPT_MINIMUM_GROUPS_BY_SHAPE.get(shape_for_type(entity_type), ())
    )
    for group in OKF_MINIMUM_GROUPS_BY_TYPE.get(normalize_type(entity_type), ()):
        # The shape's completion identity is already ``MINIMUM_NAME_FIELDS``;
        # the file-envelope identity group (which also accepts ``id``) must not
        # add a third group and shift the question order.
        if group == MINIMUM_IDENTITY_FIELDS:
            continue
        if group not in groups:
            groups.append(group)
    return tuple(groups)


# ---------------------------------------------------------------------------
# Canon state (world truth)
# ---------------------------------------------------------------------------
CANON_STATES = (
    "canon",
    "creencia",
    "leyenda",
    "hipotesis",
    "perdido",
    "prohibido",
    "propuesta",
)


def default_canon_state(status: str | None) -> str:
    """Derive the canon state from the legacy ficha ``status`` field.

    ``draft`` means the entity is still a proposal; everything else (including
    ``stable``, missing, or unrecognized values) is treated as canon.
    """
    if isinstance(status, str) and status.strip().lower() == "draft":
        return "propuesta"
    return "canon"


def normalize_canon_state(raw: str | None) -> str | None:
    """Return ``raw`` as a canonical lowercased state, or None when invalid."""
    if not isinstance(raw, str):
        return None
    normalized = raw.strip().lower()
    return normalized if normalized in CANON_STATES else None


def register_minimums(entity_type: str, *groups: Iterable[str]) -> None:
    """Extend the per-entity minimum registry.

    Later calls append groups; an identical group is not duplicated.  This is
    the extensibility seam the contract promises: new entity types (or richer
    minimums for existing ones) are added by the Author's world without
    editing the server kernel.
    """
    normalized = entity_type.strip().lower()
    if not normalized:
        raise ValueError("entity_type is required")
    combined = list(OKF_MINIMUM_GROUPS_BY_TYPE.get(normalized, ()))
    for group in groups:
        fields = frozenset(group)
        if fields and fields not in combined:
            combined.append(fields)
    OKF_MINIMUM_GROUPS_BY_TYPE[normalized] = tuple(combined)


def minimums_for(entity_type: str) -> tuple[frozenset[str], ...]:
    """Return the minimum groups for an entity type.

    Shape base groups come first, then the registered type-specific extras
    (deduplicated, so a group shared by both is reported once).  Empty when the
    type has no shape base and no registered extras.
    """
    groups: list[frozenset[str]] = list(
        minimums_for_shape(shape_for_type(entity_type))
    )
    for group in OKF_MINIMUM_GROUPS_BY_TYPE.get(normalize_type(entity_type), ()):
        if group not in groups:
            groups.append(group)
    return tuple(groups)


def is_canonical_id(value: str) -> bool:
    """True when ``value`` is a valid canonical importer identity.

    A canonical id is one or more non-empty segments joined by ``::``. Each
    segment must already be NFC-normalized and whitespace-collapsed (no
    leading/trailing whitespace, no internal whitespace runs). Recognition is
    conservative: anything else (empty, decomposed, or un-collapsed input) is
    not a canonical id.
    """
    if not isinstance(value, str) or not value:
        return False
    for segment in value.split(CANONICAL_ID_SEPARATOR):
        if not segment:
            return False
        if segment != segment.strip() or re.search(r"\s{2,}", segment):
            return False
        if unicodedata.normalize("NFC", segment) != segment:
            return False
    return True


def safe_slug_from_id(canonical_id: str) -> str:
    """Deterministic safe-slug target derived from a canonical id.

    Uses the project-wide slug alphabet (the same transform as the guided
    character/API convention): ASCII lowercase alphanumerics joined by ``-``;
    any other run of characters collapses to a single ``-``, trimmed of
    leading/trailing ``-``. ``::`` separators and ``#N`` ordinals collapse
    into the same runs — ``Ayagares::Descripción Física#2`` becomes
    ``ayagares-descripcion-fisica-2``. Distinct canonical ids that slug
    identically are disambiguated by target authority during execution; the
    canonical id itself remains the unique identity key.
    """
    return re.sub(r"[^a-z0-9]+", "-", canonical_id.strip().lower()).strip("-")


# ---------------------------------------------------------------------------
# Parsed document
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OkfDocument:
    """An OKF v1 document: identity, frontmatter, body, and relationship links.

    ``entity_type`` is the raw frontmatter ``type`` value.  ``shape`` and
    ``canon_state`` are derived kernel classifications: the coarse structural
    class and the world-truth state respectively.
    """

    entity_type: str
    frontmatter: dict[str, Any]
    body: str
    forward_links: tuple[str, ...]
    version: str | None
    shape: str
    canon_state: str


@dataclass(frozen=True)
class OkfIssue:
    """A surfaced contract problem.  Codes: identity|version|missing-minimum|ambiguous-reference|unresolved-reference."""

    code: str
    message: str
    field: str | None = None
    reference: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "reference": self.reference,
        }


@dataclass(frozen=True)
class OkfValidation:
    """Result of validating one OKF v1 document.  Never performs writes."""

    ok: bool
    entity_type: str | None
    issues: tuple[OkfIssue, ...]
    minimums: tuple[frozenset[str], ...]
    document: OkfDocument | None = None

    @property
    def missing_minimums(self) -> tuple[tuple[str, ...], ...]:
        """Alternative-field groups that are entirely absent from frontmatter."""
        return tuple(tuple(g) for g in self.minimums)


def parse_document(content: str) -> OkfDocument | None:
    """Identity: frontmatter with a non-empty ``type``.  Returns None otherwise."""
    parsed = _parse_frontmatter(content)
    if parsed is None:
        return None
    frontmatter, body = parsed
    entity_type = str(frontmatter.get("type", "")).strip()
    if not entity_type:
        return None

    forward_links: list[str] = []
    for link in _extract_wikilinks(body):
        if link not in forward_links:
            forward_links.append(link)
    for link in _frontmatter_links(frontmatter):
        if link not in forward_links:
            forward_links.append(link)

    version_raw = frontmatter.get(VERSION_FIELD)
    version = str(version_raw).strip() if version_raw is not None else None

    return OkfDocument(
        entity_type=entity_type,
        frontmatter=frontmatter,
        body=body,
        forward_links=tuple(forward_links),
        version=version,
        shape=shape_for_type(frontmatter.get("type")),
        canon_state=(
            normalize_canon_state(frontmatter.get("canon_state"))
            or default_canon_state(frontmatter.get("status"))
        ),
    )


def validate(
    content: str,
    *,
    resolve: Callable[[str], Iterable[str]] | None = None,
) -> OkfValidation:
    """Validate identity, version, minimums, and reference resolvability.

    ``resolve`` maps a wikilink name to the candidate entity paths it can
    match.  When provided, references resolve against it: zero candidates is
    ``unresolved-reference``, more than one is ``ambiguous-reference``.  When
    omitted, references are collected but not judged, so the function works
    without a graph index.

    Pure: reads the string, returns a result, writes nothing.
    """
    document = parse_document(content)
    if document is None:
        return OkfValidation(
            ok=False,
            entity_type=None,
            issues=(OkfIssue("identity", "Not an OKF v1 document: missing frontmatter `type`."),),
            minimums=(),
        )

    issues: list[OkfIssue] = []
    if document.version is not None and document.version != OKF_VERSION:
        issues.append(OkfIssue(
            "version",
            f"OKF version {document.version!r} is not supported (expected {OKF_VERSION!r}).",
            field=VERSION_FIELD,
        ))

    groups = minimums_for(document.entity_type)
    for group in groups:
        if not any(_present(document.frontmatter, field) for field in group):
            alternatives = ", ".join(sorted(group))
            issues.append(OkfIssue(
                "missing-minimum",
                f"Entity of type {document.entity_type!r} is missing a required minimum; "
                f"expected one of: {alternatives}.",
                field=alternatives,
            ))

    if resolve is not None:
        for link in document.forward_links:
            candidates = list(resolve(link))
            if not candidates:
                issues.append(OkfIssue(
                    "unresolved-reference",
                    f"Wikilink [[{link}]] does not resolve to any entity.",
                    reference=link,
                ))
            elif len(candidates) > 1:
                issues.append(OkfIssue(
                    "ambiguous-reference",
                    f"Wikilink [[{link}]] is ambiguous: it resolves to {len(candidates)} entities.",
                    reference=link,
                ))

    return OkfValidation(
        ok=not issues,
        entity_type=document.entity_type,
        issues=tuple(issues),
        minimums=groups,
        document=document,
    )


# ---------------------------------------------------------------------------
# Internal parsing (mirrors graph_indexer frontmatter semantics)
# ---------------------------------------------------------------------------


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str] | None:
    lines = content.split("\n")
    if not lines or not _RE_FRONTMATTER_START.match(lines[0]):
        return None

    end_idx: int | None = None
    for i in range(1, len(lines)):
        if _RE_FRONTMATTER_START.match(lines[i]):
            end_idx = i
            break
    if end_idx is None:
        return None

    yaml_block = "\n".join(lines[1:end_idx])
    try:
        parsed = yaml.safe_load(yaml_block)
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, dict):
        return None

    body = "\n".join(lines[end_idx + 1:])
    return parsed, body


def _extract_wikilinks(text: str) -> list[str]:
    """Extract [[Name]] links from body text, in document order."""
    return [m.group(1).strip() for m in _RE_WIKILINK.finditer(text)]


def _frontmatter_links(frontmatter: dict[str, Any]) -> list[str]:
    """Extract [[Name]] links from the ``relaciones`` frontmatter list."""
    links: list[str] = []
    raw = frontmatter.get(RELACIONES_FIELD, [])
    if isinstance(raw, list):
        for rel in raw:
            if isinstance(rel, str):
                m = _RE_WIKILINK.search(rel)
                if m:
                    links.append(m.group(1).strip())
    return links


def _present(frontmatter: dict[str, Any], field: str) -> bool:
    value = frontmatter.get(field)
    return value not in (None, "")
