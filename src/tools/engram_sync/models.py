"""Normalized data contracts for domain-neutral reconciliation."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class SourceState(str, Enum):
    """Readability/validity of one source side."""

    PRESENT = "present"
    UNREADABLE = "unreadable"
    INVALID = "invalid"

class Classification(str, Enum):
    """Relation between the two sides."""

    EQUIVALENT = "equivalent"
    LOCAL_ONLY = "local-only"
    ENGRAM_ONLY = "engram-only"
    DIVERGENT = "divergent"
    INVALID = "invalid"
    UNREADABLE = "unreadable"
    AMBIGUOUS = "ambiguous"

    @property
    def label(self) -> str:
        return CLASSIFICATION_LABELS[self]

CLASSIFICATION_LABELS = {
    Classification.EQUIVALENT: "In agreement", Classification.LOCAL_ONLY: "Only in your workspace",
    Classification.ENGRAM_ONLY: "Only in memory", Classification.DIVERGENT: "Differs between sides",
    Classification.INVALID: "Invalid", Classification.UNREADABLE: "Unreadable",
    Classification.AMBIGUOUS: "Needs your choice",
}

class Action(str, Enum):
    """Author-visible resolution actions."""

    KEEP_LOCAL = "keep-local"
    KEEP_ENGRAM = "keep-engram"
    DEFER = "defer"

    @property
    def label(self) -> str:
        return ACTION_LABELS[self]

ACTION_LABELS = {
    Action.KEEP_LOCAL: "Keep my version", Action.KEEP_ENGRAM: "Keep the saved version",
    Action.DEFER: "Decide later",
}

@dataclass(frozen=True)
class SourceRef:
    """One side: stable revision, canonical fields, fingerprint."""

    location: str
    revision: str
    identity: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    content: dict[str, Any] = field(default_factory=dict)
    fingerprint: str = ""
    state: SourceState = SourceState.PRESENT

@dataclass(frozen=True)
class NormalizedItem:
    """One discoverable thing seen across the two sides."""

    domain: str
    item_key: str
    local: SourceRef | None = None
    remote: SourceRef | None = None
    classification: Classification | None = None

@dataclass(frozen=True)
class AuthorizedOperation:
    """Confirmed operation an adapter may apply."""

    domain: str
    item_key: str
    action: Action
    source_revision: str

@dataclass(frozen=True)
class ApplyResult:
    """Outcome of one authorized apply."""

    item_key: str
    status: str
    message: str = ""


class PersistenceBoundaryError(RuntimeError):
    """A source cannot be serialized or reversed without risking data loss."""

@dataclass(frozen=True)
class Preview:
    """Plain-language preview with progressive detail."""

    item_key: str
    action: Action
    label: str
    detail: str = ""
