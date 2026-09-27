"""Backend-owned contract for materializing an idea into a world ficha.

This module deliberately stops before routing, graph access, or persistence.
Hermes is treated as an untrusted, bounded proposal provider: every AI-authored
envelope is validated fail-closed by ``MaterializationResponse.from_provider``
before any preview content is assembled.

Boundary note (binding clarification): relation-type VOCABULARY membership is
NOT enforced here. ``from_provider`` validates only the structural envelope —
an out-of-vocabulary ``rel_type`` passes through untouched so the domain
validator can drop that relation and report it in ``discarded_relations``
instead of failing the whole envelope.

Mirrors the guided-character seam (``guided_character_protocol``), re-exporting
its generic error/cancellation utilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from guided_character_protocol import CancellationToken, ErrorCode, StructuredError

PROTOCOL_VERSION = "idea-materialization-v1"

# AD1 — numeric bounds (pinned by the design; violations fail closed).
MAX_BODY_CHARS = 6000
MIN_BODY_CHARS = 1
MAX_RELATIONS = 12
MAX_CANDIDATES = 25
MAX_CANDIDATE_SUMMARY_CHARS = 160
MAX_CANDIDATE_PAYLOAD_CHARS = 4000
MAX_IDEA_BODY_CHARS = 2000
MAX_TITLE_CHARS = 160
MAX_SLUG_LEN = 120
DEADLINE_MS = 60_000

__all__ = [
    "CancellationToken",
    "DEADLINE_MS",
    "ErrorCode",
    "MAX_BODY_CHARS",
    "MAX_CANDIDATE_PAYLOAD_CHARS",
    "MAX_CANDIDATE_SUMMARY_CHARS",
    "MAX_CANDIDATES",
    "MAX_IDEA_BODY_CHARS",
    "MAX_RELATIONS",
    "MAX_SLUG_LEN",
    "MAX_TITLE_CHARS",
    "MIN_BODY_CHARS",
    "MaterializationRequest",
    "MaterializationResponse",
    "PROTOCOL_VERSION",
    "Relation",
    "StructuredError",
]


@dataclass(frozen=True)
class Relation:
    """One AI-proposed relation, validated structurally only at the envelope."""

    target_id: str
    rel_type: str


@dataclass(frozen=True)
class MaterializationRequest:
    """Server-side request for one materialization run (identity + target)."""

    protocol_version: str
    request_id: str
    session_id: str
    world: str
    section: str
    folder: str
    slug: str
    title: str
    idea_type: str
    idea_body: str
    tags: tuple[str, ...] = ()
    candidates: tuple[Mapping[str, Any], ...] = ()
    title_hint: str | None = None
    deadline_ms: int = DEADLINE_MS


@dataclass(frozen=True)
class MaterializationResponse:
    """A validated ``idea-materialization-v1`` delta envelope.

    Only the AI-authored ``body`` and ``relations`` are consumed; any
    ``frontmatter``/``id``/``path`` field in the envelope is ignored
    (R-IM-02) — the server owns frontmatter entirely.
    """

    protocol_version: str
    request_id: str
    session_id: str
    body: str
    relations: tuple[Relation, ...]
    provider_run_id: str | None = None
    provenance: tuple[str, ...] = ()

    @classmethod
    def from_provider(cls, value: object, request: MaterializationRequest) -> "MaterializationResponse | None":
        """Strict envelope validator; returns ``None`` on any envelope failure.

        Fail-closed rules (the caller maps ``None`` to ``MALFORMED_OUTPUT``):
        non-Mapping envelope; ``protocol_version``/``request_id``/``session_id``
        mismatch; ``outcome != "delta"``; ``delta`` not a Mapping; ``body`` not
        a non-empty str, exceeding ``MAX_BODY_CHARS``, or opening a frontmatter
        block (R-IM-08); ``relations`` not a list or longer than
        ``MAX_RELATIONS``; a relation element that is not a Mapping or lacks a
        non-empty str ``target_id``/``rel_type`` (structural shape only).
        """
        if not isinstance(value, Mapping):
            return None
        if value.get("protocol_version") != request.protocol_version:
            return None
        if value.get("request_id") != request.request_id or value.get("session_id") != request.session_id:
            return None
        if value.get("outcome") != "delta":
            return None
        delta = value.get("delta")
        if not isinstance(delta, Mapping):
            return None
        body = delta.get("body")
        if not isinstance(body, str) or len(body.strip()) < MIN_BODY_CHARS or len(body) > MAX_BODY_CHARS:
            return None
        if _has_leading_frontmatter(body):
            return None
        relations = delta.get("relations")
        if not isinstance(relations, list) or len(relations) > MAX_RELATIONS:
            return None
        parsed: list[Relation] = []
        for item in relations:
            if not isinstance(item, Mapping):
                return None
            target_id = item.get("target_id")
            rel_type = item.get("rel_type")
            if not isinstance(target_id, str) or not target_id.strip():
                return None
            if not isinstance(rel_type, str) or not rel_type.strip():
                return None
            # Vocabulary membership is the DOMAIN validator's boundary; an
            # out-of-vocabulary rel_type is preserved here (binding clarification).
            parsed.append(Relation(target_id, rel_type))
        run_id = value.get("provider_run_id")
        provenance = value.get("provenance", ())
        return cls(
            protocol_version=request.protocol_version,
            request_id=request.request_id,
            session_id=request.session_id,
            body=body,
            relations=tuple(parsed),
            provider_run_id=run_id if isinstance(run_id, str) else None,
            provenance=(
                tuple(provenance)
                if isinstance(provenance, (list, tuple)) and all(isinstance(item, str) for item in provenance)
                else ()
            ),
        )


def _has_leading_frontmatter(body: str) -> bool:
    """True when *body* opens with a YAML frontmatter delimiter (R-IM-08).

    Frontmatter is server-owned; an AI body that attempts a leading ``---``
    block must fail closed, even when it is indented.
    """
    return body.lstrip().startswith("---")