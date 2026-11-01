"""Semantic ficha-vs-ficha contradiction proposals (S3).

The model compares ONE ficha with a bounded list of related fichas and reports
contradictions of world truth. The one truth criterion is the TEXT: a claim
survives only when it quotes a fragment that actually appears in the source
body AND a fragment that appears in the target body. Batch membership is never
evidence, and an unquoted claim is discarded.

Different perspectives, legends, beliefs and deliberate ambiguity are not
contradictions: the prompt says so, and the Author decides what to do with
whatever survives.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from relation_proposing import pair_key, quote_in_body

ModelRunner = Callable[[str, str], str]

#: Conflict types the prompt asks for. Anything else is normalized but kept.
CONFLICT_TYPES = ("date", "status", "name", "relationship", "other")

_MAX_TYPE_CHARS = 32


@dataclass(frozen=True)
class SourceFicha:
    """One ficha offered to the model, with its full body for verification."""

    key: str
    path: str = ""
    name: str = ""
    #: Full body: the only source of truth for evidence verification.
    body: str = ""
    #: Optional bounded copy sent to the model.
    prompt_body: str = ""


@dataclass(frozen=True)
class ConflictClaim:
    """A two-sided contradiction justified by a quote in each body."""

    source_key: str
    target_key: str
    quote_a: str
    quote_b: str
    conflict_type: str = "other"
    confidence: float = 0.0
    source_path: str = ""
    target_path: str = ""
    target_name: str = ""

    @property
    def pair(self) -> tuple[str, str]:
        return pair_key(self.source_key, self.target_key)

    @property
    def conflict_id(self) -> str:
        left, right = self.pair
        return f"semantic:{left}:{right}:{self.conflict_type}"


@dataclass(frozen=True)
class ConflictOutcome:
    """Claims plus whether the provider actually answered."""

    claims: tuple[ConflictClaim, ...] = ()
    provider_ok: bool = False


def build_conflict_prompt(
    source: SourceFicha,
    targets: Sequence[SourceFicha],
) -> dict[str, Any]:
    """Build the JSON prompt: one source against its related targets."""
    instructions = (
        "You compare ONE ficha with a bounded list of related fichas and report "
        "ONLY contradictions of world truth: two statements that cannot both be "
        "true at the same time (dates, statuses, names, relationships, "
        "membership). Different perspectives, legends, beliefs, rumors and "
        "deliberate ambiguity are NOT contradictions and must not be reported. "
        "Return a JSON object with a 'contradictions' array. Each entry needs "
        "'target_canonical_id' (EXACTLY one of the supplied target ids), "
        "'conflict_type' (date|status|name|relationship|other), 'quote_source' "
        "(a short VERBATIM fragment copied from the source body), 'quote_target' "
        "(a short VERBATIM fragment copied from that target's body) and "
        "'confidence' in [0,1]. An entry without both quotes is discarded. "
        "Never invent canonical ids and never quote text that is not there."
    )
    return {
        "instructions": instructions,
        "source": {
            "canonical_id": source.key,
            "display_title": source.name or source.key,
            "body": source.prompt_body or source.body,
        },
        "targets": [
            {
                "canonical_id": target.key,
                "display_title": target.name or target.key,
                "body": target.prompt_body or target.body,
            }
            for target in targets
        ],
        "conflict_types": list(CONFLICT_TYPES),
    }


def parse_conflict_response(raw: str) -> list[dict[str, Any]]:
    """Extract the ``contradictions`` array from a model reply, fail-open."""
    data = _parse_json_object(raw)
    entries = data.get("contradictions") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def verify_conflict_claims(
    raw_claims: Iterable[dict[str, Any]],
    source: SourceFicha,
    targets: Sequence[SourceFicha],
    *,
    known: Iterable[tuple[str, str, str]] | None = None,
) -> list[ConflictClaim]:
    """Keep only claims that quote BOTH bodies and were not already recorded."""
    by_key = {target.key: target for target in targets}
    already = set(known or ())
    kept: dict[tuple[str, str, str], ConflictClaim] = {}

    for entry in raw_claims:
        target_key = str(
            entry.get("target_canonical_id")
            or entry.get("target_id")
            or entry.get("target_key")
            or ""
        )
        target = by_key.get(target_key)
        if target is None or target_key == source.key:
            continue

        quote_a = str(
            entry.get("quote_source")
            or entry.get("quote_a")
            or entry.get("evidence_a")
            or ""
        ).strip()
        quote_b = str(
            entry.get("quote_target")
            or entry.get("quote_b")
            or entry.get("evidence_b")
            or ""
        ).strip()
        if not quote_in_body(source.body, quote_a):
            continue
        if not quote_in_body(target.body, quote_b):
            continue

        conflict_type = _normalize_conflict_type(entry.get("conflict_type"))
        pair = pair_key(source.key, target_key)
        slot = (pair[0], pair[1], conflict_type)
        if slot in already:
            continue

        claim = ConflictClaim(
            source_key=source.key,
            target_key=target_key,
            quote_a=quote_a,
            quote_b=quote_b,
            conflict_type=conflict_type,
            confidence=_confidence(entry.get("confidence")),
            source_path=source.path,
            target_path=target.path,
            target_name=target.name,
        )
        current = kept.get(slot)
        if current is None or claim.confidence > current.confidence:
            kept[slot] = claim

    return sorted(
        kept.values(),
        key=lambda claim: (claim.pair, claim.conflict_type, -claim.confidence),
    )


def propose_conflicts_outcome(
    *,
    source: SourceFicha,
    targets: Sequence[SourceFicha],
    runner: ModelRunner,
    known: Iterable[tuple[str, str, str]] | None = None,
    session_id: str = "",
) -> ConflictOutcome:
    """Ask the model once for one source, then keep only quote-backed claims."""
    if not targets:
        return ConflictOutcome()
    prompt = json.dumps(
        build_conflict_prompt(source, targets), ensure_ascii=False
    )
    try:
        raw = runner(prompt, session_id)
    except Exception:  # noqa: BLE001 — a provider outage is not a crash
        return ConflictOutcome()
    if _parse_json_object(raw) is None:
        return ConflictOutcome()
    claims = verify_conflict_claims(
        parse_conflict_response(raw), source, targets, known=known
    )
    return ConflictOutcome(claims=tuple(claims), provider_ok=True)


def _normalize_conflict_type(raw: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(raw or "").strip().lower()).strip("-")
    return text[:_MAX_TYPE_CHARS] or "other"


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
