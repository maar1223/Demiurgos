"""
schemas.py — Dataclasses for sync-lore Core.

All data structures used across the chunk → analyze → index → persist pipeline.
CLOSED schemas: no extra fields beyond those defined here.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EntityType(str, Enum):
    """CLOSED enum for lore entity types."""
    PERSONAJE = "personaje"
    CRIATURA = "criatura"
    OBJETO = "objeto"
    LUGAR = "lugar"
    CONCEPTO = "concepto"
    EVENTO = "evento"
    ORGANIZACION = "organizacion"
    ESPECIE = "especie"


class StalTier(str, Enum):
    """Staler immutability tiers from Vibrantes lore system."""
    T1 = "T1"   # Immutable — never suggest corrections
    T2 = "T2"   # Soft-immutable
    T3 = "T3"   # Mutable with audit


class Veredicto(str, Enum):
    """Image-text consistency veredicts."""
    CONFIRMA = "confirma"
    CONTRADICE = "contradice"
    NO_APLICA = "no_aplica"


# ---------------------------------------------------------------------------
# Provider (dual config: text + optional vision)
# ---------------------------------------------------------------------------

@dataclass
class ProviderConfig:
    """LLM provider configuration for text analysis.
    
    The optional `vision` field allows separate provider config for image
    analysis (different model, endpoint, or API key).
    If `vision` is None, image analysis is skipped.
    """
    provider: str = "opencode-go"
    endpoint: str = "https://opencode.ai/zen/go/v1"
    model: str = "deepseek-v4-flash"
    timeout: int = 60
    api_key_env: str = "OPENCODE_GO_API_KEY"
    vision: VisionConfig | None = None


@dataclass
class VisionConfig:
    """Separate provider configuration for image/vision analysis.
    
    Every field mirrors ProviderConfig. When set, image analysis uses
    these values instead of the base config. Allows different providers,
    endpoints, models, and API keys for text vs vision.
    """
    provider: str = "opencode-go"
    endpoint: str = "https://opencode.ai/zen/go/v1"
    model: str = "qwen3.6-plus"
    timeout: int = 120
    api_key_env: str = "OPENCODE_GO_API_KEY"


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

@dataclass
class ImageRef:
    """Reference to an image found in a chunk."""
    ref: str            # "![alt](path)" or index in docx/pdf
    alt_text: str
    source_type: str    # "md_ref" | "docx_embedded" | "pdf_page"


@dataclass
class Chunk:
    """A heading-delimited section of a lore document."""
    id: str                          # uuid-v4
    source_file: str                 # relative path
    heading_path: str                # hierarchical: "## Raiders > ### Origen"
    content: str                     # chunk markdown text
    token_count: int                 # estimated tokens (len//4 for Spanish)
    images: list[ImageRef] = field(default_factory=list)

    def full_context(self) -> str:
        """Return heading_path + content for LLM context."""
        return f"{self.heading_path}\n\n{self.content}"


@dataclass
class ChunkResult:
    """LLM extraction result for one chunk."""
    entities: list[dict] = field(default_factory=list)
    terms: list[dict] = field(default_factory=list)
    contradictions: list[dict] = field(default_factory=list)
    raw_response: str | None = None


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

@dataclass
class ImageAnalysis:
    """Vision LLM analysis of an image."""
    descripcion: str = ""
    veredicto: str = "no_aplica"   # "confirma" | "contradice" | "no_aplica"
    tags: list[str] = field(default_factory=list)
    analisis: str = ""


@dataclass
class ImageEntry:
    """An extracted image with its context and (after processing) analysis."""
    id: str                          # uuid-v4
    source_file: str                 # relative path to source
    page: int | None = None          # page number (PDF/DOCX)
    chunk_ref: str = ""              # heading_path of associated chunk
    context_text: str = ""           # text of associated chunk
    filename: str = ""               # original filename or generated
    image_bytes: bytes = field(default=b"", repr=False)  # NOT persisted to JSON
    analysis: ImageAnalysis | None = None


# ---------------------------------------------------------------------------
# Lore Entity (CLOSED schema — 14 fields)
# ---------------------------------------------------------------------------

@dataclass
class LoreEntity:
    """A single lore entity extracted and indexed."""
    id: str                          # uuid-v4
    name: str                        # entity name
    type: str                        # EntityType value
    world: str | None = None         # world name or None (generic)
    source_file: str = ""            # relative path to source file
    chunk_ref: str = ""              # heading_path ref
    description: str = ""            # 1-3 line summary
    relations: list[dict] = field(default_factory=list)
    # relations: [{target: str, type: str, strength: float}]
    terms: list[str] = field(default_factory=list)
    stal_tier: str | None = None     # "T1" | "T2" | "T3" | None
    immutable: bool = False          # derived from stal_tier
    quotes: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)  # contradiction IDs

    def __post_init__(self):
        if self.stal_tier == StalTier.T1:
            self.immutable = True


# ---------------------------------------------------------------------------
# Contradiction
# ---------------------------------------------------------------------------

@dataclass
class ContradictionEntry:
    """A detected contradiction between two chunks."""
    id: str                          # uuid-v4
    entity: str                      # entity name
    entity_id: str = ""              # uuid of the entity
    chunk_a: dict = field(default_factory=lambda: {"file": "", "heading": "", "claim": ""})
    chunk_b: dict = field(default_factory=lambda: {"file": "", "heading": "", "claim": ""})
    reason: str = ""
    stal_conflict: bool = False      # True if entity is Staler T1


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

@dataclass
class LoreIndexMeta:
    """Metadata for the lore index."""
    tool: str = "sync-lore"
    version: str = "0.1.0"
    generated_at: str = ""           # ISO-8601
    world: str | None = None
    mode: str = "text"               # "text" | "images" | "both"
    chunks_processed: int = 0
    entities_extracted: int = 0
    contradictions_found: int = 0


@dataclass
class LoreIndex:
    """Complete lore index — the output of sync-lore."""
    meta: LoreIndexMeta = field(default_factory=LoreIndexMeta)
    entities: list[LoreEntity] = field(default_factory=list)
    terms: list[dict] = field(default_factory=list)
    images: list[ImageEntry] = field(default_factory=list)
    contradictions: list[ContradictionEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# OKF v1 normalization (identity, minimums, relationship conventions)
# ---------------------------------------------------------------------------
#
# World-agnostic contract conventions shared with the wiki OKF layer.  These
# helpers are pure: they derive a normalized payload from frontmatter/body and
# never write to canon.  Per-entity minimums are extensible, characters first.

OKF_VERSION = "1"
RELACIONES_FIELD = "relaciones"

# Relationship convention: a relationship is a [[Name]] wikilink.
_RE_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")

MINIMUM_IDENTITY_FIELDS = frozenset({"name", "nombre", "title"})
MINIMUM_DESIRE_FIELDS = frozenset({
    "desire", "deseo", "motivacion", "motivations", "motivation", "motivaciones",
})

# Extensible per-entity minimums: entity type -> groups of alternative fields.
OKF_MINIMUM_GROUPS_BY_TYPE: dict[str, tuple[frozenset[str], ...]] = {
    "personaje": (MINIMUM_IDENTITY_FIELDS, MINIMUM_DESIRE_FIELDS),
}


def register_okf_minimums(entity_type: str, *groups: Any) -> None:
    """Extend the per-entity OKF minimum registry (mutually tolerant)."""
    normalized = entity_type.strip().lower()
    if not normalized:
        raise ValueError("entity_type is required")
    combined = list(OKF_MINIMUM_GROUPS_BY_TYPE.get(normalized, ()))
    for group in groups:
        fields = frozenset(group)
        if fields and fields not in combined:
            combined.append(fields)
    OKF_MINIMUM_GROUPS_BY_TYPE[normalized] = tuple(combined)


@dataclass(frozen=True)
class OkfNormalized:
    """OKF v1 identity and relationship conventions, normalized for indexing."""

    name: str
    type: str
    title: str
    forward_links: tuple[str, ...]
    missing_minimum_groups: tuple[frozenset[str], ...]


def normalize_okf_v1(frontmatter: dict, body: str = "") -> OkfNormalized | None:
    """Return OKF v1 identity/links from frontmatter, or None when not OKF.

    A document is OKF v1 when its frontmatter declares a non-empty ``type``.
    Minimum groups are surfaced (never silently assumed) and ``[[Name]]``
    links from the body plus ``relaciones`` frontmatter are collected in
    document order.  Pure: writes nothing.
    """
    if not isinstance(frontmatter, dict):
        return None
    entity_type = str(frontmatter.get("type", "")).strip()
    if not entity_type:
        return None

    name = str(
        frontmatter.get("name")
        or frontmatter.get("nombre")
        or frontmatter.get("title")
        or ""
    ).strip()
    title = str(frontmatter.get("title", "")).strip()

    links: list[str] = []
    for match in _RE_WIKILINK.finditer(body or ""):
        link = match.group(1).strip()
        if link not in links:
            links.append(link)
    raw_relations = frontmatter.get(RELACIONES_FIELD)
    if isinstance(raw_relations, list):
        for rel in raw_relations:
            if isinstance(rel, str):
                m = _RE_WIKILINK.search(rel)
                if m:
                    link = m.group(1).strip()
                    if link not in links:
                        links.append(link)

    groups = OKF_MINIMUM_GROUPS_BY_TYPE.get(entity_type.lower(), ())
    missing = tuple(
        group for group in groups
        if not any(_field_present(frontmatter, f) for f in group)
    )

    return OkfNormalized(
        name=name,
        type=entity_type,
        title=title,
        forward_links=tuple(links),
        missing_minimum_groups=missing,
    )


def normalize_okf_content(content: str) -> OkfNormalized | None:
    """Parse OKF v1 frontmatter/body from raw markdown and normalize.

    Tolerant: unparseable frontmatter or missing ``type`` yields None rather
    than an error.  Requires PyYAML; returns None when it is unavailable.

    Delegates to the server-owned ``okf_contract`` authority when it is
    importable in this runtime (sole OKF authority, 2.8); falls back to the
    local implementation when the wiki module is not on the path.
    """
    delegate = _delegate_okf_validate()
    if delegate is not None:
        parsed = delegate(content)
        if parsed is None:
            return None
        doc = parsed.document
        if doc is None:
            return None
        return OkfNormalized(
            name=str(doc.frontmatter.get("name")
                      or doc.frontmatter.get("nombre")
                      or doc.frontmatter.get("title") or "").strip(),
            type=doc.entity_type,
            title=str(doc.frontmatter.get("title", "")).strip(),
            forward_links=doc.forward_links,
            missing_minimum_groups=parsed.missing_minimums,
        )
    return _normalize_okf_content_local(content)


def _normalize_okf_content_local(content: str) -> OkfNormalized | None:
    try:
        import yaml
    except ImportError:
        return None
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None
    try:
        frontmatter = yaml.safe_load("\n".join(lines[1:end_idx]))
    except yaml.YAMLError:
        return None
    if not isinstance(frontmatter, dict):
        return None
    body = "\n".join(lines[end_idx + 1:])
    return normalize_okf_v1(frontmatter, body)


_delegate_okf = None


def _delegate_okf_validate():
    """Best-effort resolve the server-owned okf_contract.validate authority.

    Resolves once and caches the successful reference; a failed attempt is
    NOT cached, so the delegation recovers if the wiki module later becomes
    importable in this runtime. Falls back to the local implementation.
    """
    global _delegate_okf
    if _delegate_okf is not None:
        return _delegate_okf
    try:
        from okf_contract import validate as _validate  # type: ignore
        _delegate_okf = _validate
    except Exception:
        _delegate_okf = None
    return _delegate_okf


@dataclass(frozen=True)
class ApprovedCharacterWrite:
    """A character write payload that has passed the approval gate.

    Construction is only possible through ``approve``, which binds the payload
    to an authorization digest and restricts the target to ``personajes/``.
    The dataclass itself never touches the filesystem: a caller submits it to
    a gated write endpoint, preserving graph authority and approval-gated
    writes.  Tokens and digests stay ephemeral and non-inheritable.
    """

    content: str
    target: str
    world: str
    content_digest: str

    @staticmethod
    def approve(
        content: str,
        target: str,
        *,
        world: str = "",
        edit_id: str,
        confirmation_token: str,
        confirmation_digest: str,
    ) -> "ApprovedCharacterWrite":
        """Digest-gate a character payload for a gated write.

        Raises ValueError when authorization data is missing, the target is
        outside ``personajes/``, or the digest does not match the content.
        """
        if not edit_id.strip() or not confirmation_token.strip():
            raise ValueError("edit_id and confirmation token are required")
        if not target.startswith("personajes/") or not target.endswith(".md"):
            raise ValueError("approved character target must be under personajes/")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if digest != confirmation_digest:
            raise ValueError("confirmation digest does not match content")
        return ApprovedCharacterWrite(
            content=content,
            target=target,
            world=world,
            content_digest=digest,
        )


def _field_present(frontmatter: dict, field: str) -> bool:
    value = frontmatter.get(field)
    return value not in (None, "")
