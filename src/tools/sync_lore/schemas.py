"""
schemas.py — Dataclasses for sync-lore Core.

All data structures used across the chunk → analyze → index → persist pipeline.
CLOSED schemas: no extra fields beyond those defined here.
"""

from __future__ import annotations

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
    provider: str = "qwen"
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
    provider: str = "qwen"
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
