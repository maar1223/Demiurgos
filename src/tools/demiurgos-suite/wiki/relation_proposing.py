"""Batch-safe relation proposals, shared by the sweep and the world importer.

The one truth criterion is the SOURCE BODY: a model claim survives only when it
can quote a fragment that actually appears in the body of the ficha it talks
about. Batch membership is never evidence, so how many fichas travel in one
call cannot change the resulting graph — it only decides how many calls you
pay for.

Two invariants make batching irrelevant:

* sources are batched, but the target universe is the whole world catalog
  (a claim never needs its target to be in the same batch);
* a claim is directional and anchored on its source, and its evidence is
  verified per pair, without knowing who else was in the batch.

Symmetry is normalized on the queue/memory side: ``A -> B`` and ``B -> A`` are
the same pair, stored once on a deterministic side.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from import_relations import normalize_mention

#: Minimum normalized length of a quote before it counts as evidence. A two
#: character fragment ("de", "la") matches half the corpus and proves nothing.
_MIN_QUOTE_CHARS = 4

ModelRunner = Callable[[str, str], str]


@dataclass(frozen=True)
class Source:
    """One ficha offered to the model as a possible relation source."""

    key: str
    path: str = ""
    name: str = ""
    #: Full body: the only source of truth for evidence verification.
    body: str = ""
    #: Optional bounded copy sent to the model. Verification always uses
    #: ``body``, so truncating the prompt loses recall, never correctness.
    prompt_body: str = ""


@dataclass(frozen=True)
class CatalogEntry:
    """One valid target. The catalog is world-wide, never batch-scoped."""

    canonical_id: str
    display_title: str = ""


@dataclass(frozen=True)
class Claim:
    """A directional relation proposal justified by a quote in the source body."""

    source_key: str
    target_id: str
    quote: str
    relationship_type: str = ""
    confidence: float = 0.0
    source_path: str = ""

    @property
    def pair(self) -> tuple[str, str]:
        return pair_key(self.source_key, self.target_id)

    @property
    def anchor(self) -> str:
        """Deterministic side that stores the pair, so order cannot matter."""
        return self.pair[0]


def pair_key(left: str, right: str) -> tuple[str, str]:
    """Unordered identity of a relation: ``(a, b)`` and ``(b, a)`` collapse."""
    return (left, right) if left <= right else (right, left)


def quote_in_body(body: str, quote: str) -> bool:
    """True when ``quote`` can be found in ``body`` after normalization.

    Normalization folds case, accents, dashes and punctuation, matching the
    matcher used by the deterministic extractor, so an honest quote survives
    typographic differences. An elided quote (``...``) is accepted when every
    non-empty fragment appears, because trimming a long sentence is not
    inventing evidence.
    """
    normalized_body = normalize_mention(body)
    if not normalized_body:
        return False
    fragments = [part for part in re.split(r"\.{3,}|…", quote or "") if part.strip()]
    if not fragments:
        return False
    for fragment in fragments:
        normalized_quote = normalize_mention(fragment)
        if len(normalized_quote.replace(" ", "")) < _MIN_QUOTE_CHARS:
            return False
        if normalized_quote not in normalized_body:
            return False
    return True


def build_proposal_prompt(
    sources: Sequence[Source],
    catalog: Sequence[CatalogEntry],
    *,
    rel_vocab: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build the JSON prompt: one INDEPENDENT claim per source, targets global.

    The instructions explicitly forbid reading the batch as a group. The batch
    exists to save calls, not to suggest that its members relate to each other.
    """
    instructions = (
        "You propose relations for ONE ficha at a time. Each entry in "
        "'sources' is examined on its OWN: a relation may only be claimed when "
        "the source's own body states or clearly implies it. The other sources "
        "in this request are unrelated work shipped in the same call; they are "
        "NOT context and they do NOT relate to each other by being together. "
        "Return a JSON object with a 'relationships' array. Each relationship "
        "must use 'source_canonical_id' (exactly one of the supplied source "
        "canonical_ids), 'target_canonical_id' (EXACTLY one canonical_id from "
        "'catalog'; never a bare title), 'relationship_type' from the "
        "vocabulary, 'confidence' in [0,1], and 'evidence', a short VERBATIM "
        "quote copied from that source's own body. If no sentence in the body "
        "supports the relation, do not return it: an unquoted claim is "
        "discarded. NEVER invent canonical ids outside the catalog."
    )
    payload: dict[str, Any] = {
        "instructions": instructions,
        "catalog": [
            {
                "canonical_id": entry.canonical_id,
                "display_title": entry.display_title or entry.canonical_id,
            }
            for entry in catalog
        ],
        "sources": [
            {
                "canonical_id": source.key,
                "display_title": source.name or source.key,
                "body": source.prompt_body or source.body,
            }
            for source in sources
        ],
    }
    if rel_vocab is not None:
        payload["rel_vocab"] = sorted({str(item) for item in rel_vocab if item})
    return payload


def parse_proposal_response(raw: str) -> list[dict[str, Any]]:
    """Extract the ``relationships`` array from a model reply, fail-open."""
    data = _parse_json_object(raw)
    entries = data.get("relationships") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def verify_claims(
    raw_claims: Iterable[dict[str, Any]],
    sources: Sequence[Source],
    catalog: Sequence[CatalogEntry],
    *,
    known_pairs: Iterable[tuple[str, str]] | None = None,
) -> list[Claim]:
    """Keep only claims that quote their own source body.

    Every rejection below is a claim that would have corrupted the graph: an
    unknown source, a target outside the world, a self-link, an already
    declared pair, or — the important one — a claim with no quote in the body.
    """
    by_key = {source.key: source for source in sources}
    catalog_ids = {entry.canonical_id for entry in catalog}
    known = set(known_pairs or ())
    kept: dict[tuple[str, str, str], Claim] = {}
    for entry in raw_claims:
        source_key = str(
            entry.get("source_canonical_id")
            or entry.get("source_candidate_id")
            or entry.get("source_key")
            or ""
        )
        target_id = str(
            entry.get("target_canonical_id")
            or entry.get("target_id")
            or entry.get("target_candidate_id")
            or ""
        )
        source = by_key.get(source_key)
        if source is None or not target_id or target_id == source_key:
            continue
        if target_id not in catalog_ids:
            continue
        pair = pair_key(source_key, target_id)
        if pair in known:
            continue
        quote = str(entry.get("evidence") or entry.get("quote") or "").strip()
        if not quote_in_body(source.body, quote):
            continue
        claim = Claim(
            source_key=source_key,
            target_id=target_id,
            quote=quote,
            relationship_type=str(entry.get("relationship_type") or ""),
            confidence=_confidence(entry.get("confidence")),
            source_path=source.path,
        )
        slot = (pair[0], pair[1], claim.relationship_type)
        current = kept.get(slot)
        if current is None or claim.confidence > current.confidence:
            kept[slot] = claim
    return sorted(
        kept.values(),
        key=lambda claim: (claim.pair, claim.relationship_type, -claim.confidence),
    )


@dataclass(frozen=True)
class ProposalOutcome:
    """Claims plus whether the provider actually answered.

    ``provider_ok`` separates "the model found nothing" (a legitimate result
    that may mark a ficha as swept) from "the model never answered" (an outage
    that must NOT hide reviewable work).
    """

    claims: tuple[Claim, ...] = ()
    provider_ok: bool = False


def propose_relations_outcome(
    *,
    sources: Sequence[Source],
    catalog: Sequence[CatalogEntry],
    runner: ModelRunner,
    rel_vocab: Iterable[str] | None = None,
    known_pairs: Iterable[tuple[str, str]] | None = None,
    session_id: str = "",
) -> ProposalOutcome:
    """Ask the model once, then keep only quote-backed claims."""
    if not sources or not catalog:
        return ProposalOutcome()
    prompt = json.dumps(
        build_proposal_prompt(sources, catalog, rel_vocab=rel_vocab),
        ensure_ascii=False,
    )
    try:
        raw = runner(prompt, session_id)
    except Exception:  # noqa: BLE001 — a provider outage is not a crash
        return ProposalOutcome()
    if _parse_json_object(raw) is None:
        return ProposalOutcome()
    claims = verify_claims(
        parse_proposal_response(raw),
        sources,
        catalog,
        known_pairs=known_pairs,
    )
    return ProposalOutcome(claims=tuple(claims), provider_ok=True)


def propose_relations(
    *,
    sources: Sequence[Source],
    catalog: Sequence[CatalogEntry],
    runner: ModelRunner,
    rel_vocab: Iterable[str] | None = None,
    known_pairs: Iterable[tuple[str, str]] | None = None,
    session_id: str = "",
) -> list[Claim]:
    """Ask the model once, then keep only quote-backed claims.

    Fail-open: a provider that raises or answers with garbage yields no
    proposals, so an outage can never invent a relation either.
    """
    return list(
        propose_relations_outcome(
            sources=sources,
            catalog=catalog,
            runner=runner,
            rel_vocab=rel_vocab,
            known_pairs=known_pairs,
            session_id=session_id,
        ).claims
    )


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return min(1.0, max(0.0, float(value)))


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None
