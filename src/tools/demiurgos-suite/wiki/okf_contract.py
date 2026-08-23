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
MINIMUM_DESIRE_FIELDS = frozenset({
    "desire", "deseo", "motivacion", "motivations", "motivation", "motivaciones",
})

# Extensible per-entity minimums, characters first.
OKF_MINIMUM_GROUPS_BY_TYPE: dict[str, tuple[frozenset[str], ...]] = {
    "personaje": (MINIMUM_IDENTITY_FIELDS, MINIMUM_DESIRE_FIELDS),
}


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
    """Return the minimum groups for an entity type (empty when unregistered)."""
    return OKF_MINIMUM_GROUPS_BY_TYPE.get(entity_type.strip().lower(), ())


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
    """An OKF v1 document: identity, frontmatter, body, and relationship links."""

    entity_type: str
    frontmatter: dict[str, Any]
    body: str
    forward_links: tuple[str, ...]
    version: str | None


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
