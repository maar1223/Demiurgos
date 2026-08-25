"""World importer — Hermes advisory enrichment (slice 2).

Optional, reviewable classification + relationship suggestions sourced from a
Hermes batch call. Suggestions are NON-AUTHORITATIVE: they ride on each
candidate without mutating deterministic identity/digest, are surfaced as
advisory in review, and only materialize into canon during a gated execute
(via ``apply_approved_suggestions``).

Module boundaries
-----------------

* ``build_enrichment_prompt`` — bounded JSON prompt for a batch of candidates.
* ``parse_hermes_response`` — JSON adapter: tolerates a single code fence,
  yields typed ``ClassificationSuggestion``/``RelationshipSuggestion`` lists.
* ``validate_suggestions`` — vocabulary/reference safety filter: rejects
  unknown entity types, confidence out of ``[0,1]``, self-links, and
  ungrounded targets.
* ``enrich_candidates`` — top-level orchestration: invoke the injected
  ``hermes_runner``, attach suggestions to each candidate, and return the
  patched list. Fail-open: any runner exception, timeout, or parse failure
  returns candidates unchanged with ``enrichment_status="no_suggestions"``.
* ``apply_approved_suggestions`` — pure content patch: updates
  ``content_preview`` frontmatter (type/tags) and appends deduplicated
  ``[[target]]`` entries to ``relaciones`` when an author approves.

Vocabulary alignment: types are seeded from ``sync_lore.schemas.EntityType``
(the canonical 8-value closed enum). Relationship types stay on an open,
normalized allowlist (``lowercase, hyphen-separated``) so projects can extend
without breaking existing imports; unknown values are filtered out.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import re
from typing import Any, Callable, Iterable

from import_models import (
    Candidate,
    ClassificationSuggestion,
    EnrichmentStatus,
    FrontmatterCandidate,
    FrontmatterState,
    RelationshipSuggestion,
)

logger = logging.getLogger("demiurgos-import-enrichment")

# Default prompt version (server-attached provenance field). Bumping this
# changes every suggestion's provenance and surfaces "new model version"
# reviews to authors; never overwrite silently.
DEFAULT_PROMPT_VERSION = "import-enrichment/v1"
DEFAULT_PROVIDER = "hermes-gateway"
DEFAULT_MODEL = "hermes-agent"

# Extended per-call budget for the enrichment funnel (importador-auto-
# frontmatter, design risk 4): per-ficha summaries and a relationship pass can
# carry large bodies, so the total Hermes budget is 120 seconds (including the
# async bridge/client budget). The runner is responsible for honoring it
# (async runners wrap the gateway with an httpx timeout); on timeout the
# funnel fails open to manual/fallback and never blocks the import path.
DEFAULT_TIMEOUT_SECONDS = 120.0

# Prompt bounds: a candidate preview is bounded so a large source file can
# never blow up the LLM context window. The total bound guards against an
# accidental "thousands of candidates" batch.
_PREVIEW_CHAR_BUDGET = 1500
_MAX_CANDIDATES_PER_BATCH = 100
# Funnel chunking (importador-auto-frontmatter): keep each Hermes call's prompt
# AND expected output small enough to avoid response truncation on large
# imports. Chunks are bounded by BYTES, not by ficha count — a fixed count of
# 12 large fichas can still total ~72k chars (the observed "respaldo desde el
# 9no Stal" failure), which truncates Hermes and drops the tail of the batch.
# ``_FUNNEL_CHUNK_BYTES`` bounds the cumulative ``content_preview`` bytes per
# chunk; a single oversized ficha still travels COMPLETE (never split, never
# truncated). ``_FUNNEL_FILL_GROUP_SIZE`` bounds the fill-in re-ask for
# candidates the model omitted.
# Tuned 2026-08-25 (live A/B, 60 real fichas, 4 workers): 40000 gives 58/60 ok
# vs 38/60 at 60000, at only ~19% more wall-time — 60000 degrades quality
# (22 fichas without suggestions) for a small time saving, so 40000 is the
# default sweet spot. Never raise to 60000.
_FUNNEL_CHUNK_BYTES = 40000
_FUNNEL_FILL_GROUP_SIZE = 4

# Relationship-type vocabulary: lowercase, hyphen-separated, ASCII only.
# Open allowlist: projects can extend by passing a custom ``rel_vocab`` to
# ``build_enrichment_prompt``. Unknown types are rejected during validation.
_REL_VOCAB_DEFAULT = frozenset({
    "aliado-de", "enemigo-de", "sirve-a", "miembro-de", "lidera",
    "habita-en", "ubicado-en", "aparece-en", "participa-en",
    "crea", "creado-por", "deriva-de", "relacionado-con",
    "amigo-de", "rival-de", "padre-de", "madre-de", "hijo-de",
    "hermano-de", "esposo-de", "mentor-de", "alumno-de",
})


def entity_type_vocabulary() -> tuple[str, ...]:
    """Return the canonical EntityType vocabulary seeded from sync_lore.

    The vocabulary is computed lazily so importing this module never requires
    ``sync_lore.schemas`` (the importer package must remain importable
    independent of the wiki toolchain).
    """
    from sync_lore.schemas import EntityType
    return tuple(member.value for member in EntityType)


def _safe_identity(candidate: Candidate) -> str:
    """Stable display identity for a candidate (filename stem)."""
    return candidate.normalized_identity or candidate.candidate_id


def _bounded_preview(text: str, *, budget: int = _PREVIEW_CHAR_BUDGET) -> str:
    """Slice a candidate's preview into a prompt-safe window.

    Whitespace is collapsed so multi-newline chunks do not waste budget.
    A trailing ellipsis marks truncated previews so the model can rely on
    "..." meaning "content was cut, do not guess beyond it".
    """
    flat = re.sub(r"\s+", " ", (text or "").strip())
    if len(flat) <= budget:
        return flat
    return flat[:budget].rstrip() + "..."


def build_enrichment_prompt(
    candidates: list[Candidate],
    *,
    entity_vocab: Iterable[str] | None = None,
    rel_vocab: Iterable[str] | None = None,
    provenance: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Assemble the bounded prompt payload sent to Hermes.

    The result is a JSON-serializable dict the runner can serialize as the
    prompt body. ``entity_vocab``/``rel_vocab`` default to the canonical
    vocabulary (``entity_type_vocabulary()`` + ``_REL_VOCAB_DEFAULT``); the
    caller may pass custom values for tests or per-project extensions.

    The batch is hard-capped at ``_MAX_CANDIDATES_PER_BATCH``: callers MUST
    page larger imports. The preview is hard-capped at
    ``_PREVIEW_CHAR_BUDGET`` per candidate.
    """
    type_vocab = tuple(entity_vocab) if entity_vocab is not None else entity_type_vocabulary()
    rel_vocab_set = frozenset(rel_vocab) if rel_vocab is not None else _REL_VOCAB_DEFAULT
    prov = dict(provenance or {"prompt_version": DEFAULT_PROMPT_VERSION,
                                "provider": DEFAULT_PROVIDER,
                                "model": DEFAULT_MODEL})

    batch = candidates[:_MAX_CANDIDATES_PER_BATCH]
    payload_candidates = [
        {
            "candidate_id": c.candidate_id,
            "identity": _safe_identity(c),
            "preview": _bounded_preview(c.content_preview),
        }
        for c in batch
    ]
    instructions = (
        "You are classifying imported worldbuilding candidates. "
        "Return a JSON object with two arrays: 'classifications' and "
        "'relationships'. Each classification must reference one of the "
        "supplied candidate_ids and use a type from 'entity_vocab'. Each "
        "relationship must reference a 'source_candidate_id' and either a "
        "'target_candidate_id' (preferred) or 'target_name' (only when the "
        "target is not in the batch). Confidence must be in [0,1] and "
        "evidence must be a short quote or paraphrase from the supplied "
        "preview. NEVER invent targets outside the batch or preview."
    )
    return {
        "instructions": instructions,
        "entity_vocab": list(type_vocab),
        "rel_vocab": sorted(rel_vocab_set),
        "provenance": prov,
        "candidates": payload_candidates,
    }


# ---------------------------------------------------------------------------
# JSON adapter (parse + validate)
# ---------------------------------------------------------------------------


def parse_hermes_response(raw: str) -> dict[str, list[dict[str, Any]]]:
    """Tolerantly parse a Hermes reply into typed arrays.

    Returns ``{"classifications": [...], "relationships": [...]}`` with raw
    dicts (validation runs separately so test failures pinpoint the failing
    stage). Empty arrays when the payload is missing or not a JSON object. A
    fenced block is stripped before parsing, and a prose prefix (Hermes often
    intro's the reply) is tolerated via ``_parse_json_object`` — which recovers
    the first balanced ``{...}`` object even when it is not the whole reply.
    """
    data = _parse_json_object(raw)
    if data is None:
        return {"classifications": [], "relationships": []}
    cls_raw = data.get("classifications", [])
    rel_raw = data.get("relationships", [])
    cls_list = cls_raw if isinstance(cls_raw, list) else []
    rel_list = rel_raw if isinstance(rel_raw, list) else []
    return {"classifications": [x for x in cls_list if isinstance(x, dict)],
            "relationships": [x for x in rel_list if isinstance(x, dict)]}


def _normalize_confidence(value: Any) -> float | None:
    """Return a confidence value iff it is numeric and inside ``[0, 1]``.

    The spec is strict: confidence MUST be in ``[0, 1]``. Out-of-bounds,
    NaN, or non-numeric values are dropped (fail-open) so a malformed
    Hermes reply cannot smuggle in an unbounded score.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN guard
        return None
    if number < 0.0 or number > 1.0:
        return None
    return number


def _normalize_tags(value: Any) -> list[str]:
    """Coerce a tag list to a list of non-empty trimmed strings."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        tag = item.strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def _normalize_rel_type(value: Any, vocab: frozenset[str]) -> str | None:
    """Lowercase/hyphenate a relationship type; return None when unknown."""
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"[\s_]+", "-", value.strip().lower())
    return normalized if normalized in vocab else None


def validate_suggestions(
    parsed: dict[str, list[dict[str, Any]]],
    candidates: list[Candidate],
    *,
    rel_vocab: Iterable[str] | None = None,
) -> tuple[list[ClassificationSuggestion], list[RelationshipSuggestion]]:
    """Validate Hermes output against vocabulary + reference safety rules.

    Filters out:
      * unknown ``type`` values (not in the canonical EntityType vocabulary)
      * confidence outside ``[0, 1]`` (NaN, infinity, negatives, >1)
      * self-links (source == target)
      * ungrounded ``target_name`` values not present in the batch
      * unsupported ``relationship_type`` values

    Returns ``(classifications, relationships)`` with only the safe entries.
    Pydantic ``extra="forbid"`` on the suggestion models surfaces malformed
    shapes (e.g., a list passed where a string was expected); those entries
    are silently dropped to keep the import fail-open.
    """
    entity_vocab = frozenset(entity_type_vocabulary())
    rel_vocab_set = frozenset(rel_vocab) if rel_vocab is not None else _REL_VOCAB_DEFAULT
    valid_candidate_ids = {c.candidate_id for c in candidates}
    valid_identities = {_safe_identity(c) for c in candidates}

    cls_out: list[ClassificationSuggestion] = []
    for entry in parsed.get("classifications", []):
        cand_id = entry.get("candidate_id")
        if not isinstance(cand_id, str) or cand_id not in valid_candidate_ids:
            continue
        type_value = entry.get("type")
        if not isinstance(type_value, str):
            continue
        normalized_type = type_value.strip().lower()
        if normalized_type not in entity_vocab:
            continue
        confidence = _normalize_confidence(entry.get("confidence"))
        if confidence is None:
            continue
        evidence = entry.get("evidence", "")
        if not isinstance(evidence, str):
            evidence = ""
        try:
            suggestion = ClassificationSuggestion(
                id=str(entry.get("id") or ""),
                candidate_id=cand_id,
                type=normalized_type,
                tags=_normalize_tags(entry.get("tags")),
                confidence=confidence,
                evidence=evidence,
                provenance={},
                review_state="pending",
            )
        except Exception:  # noqa: BLE001 — pydantic extra=forbid surfaces here
            continue
        cls_out.append(suggestion)

    rel_out: list[RelationshipSuggestion] = []
    for entry in parsed.get("relationships", []):
        src = entry.get("source_candidate_id")
        if not isinstance(src, str) or src not in valid_candidate_ids:
            continue
        rel_type = _normalize_rel_type(entry.get("relationship_type"),
                                       rel_vocab_set)
        if rel_type is None:
            continue
        confidence = _normalize_confidence(entry.get("confidence"))
        if confidence is None:
            continue
        tgt_id = entry.get("target_candidate_id")
        tgt_name = entry.get("target_name")
        target_candidate_id: str | None = None
        target_name: str | None = None
        if isinstance(tgt_id, str) and tgt_id in valid_candidate_ids:
            if tgt_id == src:
                continue  # self-link rejected
            target_candidate_id = tgt_id
            # A batched target gets its human title so the frontend can show a
            # readable name instead of the internal candidate hex id.
            target = next(
                (c for c in candidates if c.candidate_id == tgt_id), None)
            if target is not None:
                target_name = (
                    target.display_title
                    or target.normalized_identity
                    or target.candidate_id)
        elif isinstance(tgt_name, str):
            candidate_identity = tgt_name.strip()
            if not candidate_identity or candidate_identity == src:
                continue
            # The named target must appear as an identity in the batch. If
            # not, the suggestion is ungrounded and never reaches canon.
            if candidate_identity not in valid_identities:
                continue
            target_name = candidate_identity
        else:
            continue
        evidence = entry.get("evidence", "")
        if not isinstance(evidence, str):
            evidence = ""
        try:
            suggestion = RelationshipSuggestion(
                id=str(entry.get("id") or ""),
                source_candidate_id=src,
                target_candidate_id=target_candidate_id,
                target_name=target_name,
                relationship_type=rel_type,
                confidence=confidence,
                evidence=evidence,
                provenance={},
                review_state="pending",
            )
        except Exception:  # noqa: BLE001 — pydantic extra=forbid surfaces here
            continue
        rel_out.append(suggestion)

    return cls_out, rel_out


# ---------------------------------------------------------------------------
# Orchestration (fail-open)
# ---------------------------------------------------------------------------


def enrich_candidates(
    candidates: list[Candidate],
    hermes_runner: Callable[[str, str], str] | None,
    *,
    entity_vocab: Iterable[str] | None = None,
    rel_vocab: Iterable[str] | None = None,
    provenance: dict[str, str] | None = None,
) -> list[Candidate]:
    """Run Hermes enrichment over a batch and patch candidates in place.

    ``hermes_runner`` is an injected callable (sync ``Callable[[prompt, session_id], str]``)
    so the importer module stays gateway-independent and is trivially mockable
    in tests. Returns a NEW list with each input candidate copied; the input
    list is never mutated. Fail-open: any runner exception, timeout,
    unavailable copy, malformed JSON, or empty/zero-valid batch leaves the
    candidates' enrichment untouched and marks them ``"no_suggestions"``.

    The returned candidates carry:
      * ``enrichment_json`` — list of suggestion dicts (classifications
        followed by relationships) or ``None`` when the batch yielded zero.
      * ``enrichment_status`` — ``"ok"`` when at least one suggestion was
        accepted, ``"no_suggestions"`` otherwise. Never raises.
    """
    if hermes_runner is None or not candidates:
        return [_copy_candidate(c,
                                enrichment_json=None,
                                enrichment_status=EnrichmentStatus.DISABLED.value)
                for c in candidates]

    payload = build_enrichment_prompt(
        candidates, entity_vocab=entity_vocab, rel_vocab=rel_vocab,
        provenance=provenance)
    prov = payload["provenance"]
    session_id = f"import-enrich:{candidates[0].job_id}"
    try:
        prompt_text = json.dumps(payload, ensure_ascii=False)
        raw = hermes_runner(prompt_text, session_id)
    except Exception as exc:  # noqa: BLE001 — fail-open: enrichment must never crash analyze
        logger.warning("enrich_candidates runner failed: %s",
                       type(exc).__name__, exc_info=True)
        return [_copy_candidate(c, enrichment_json=None,
                                enrichment_status=EnrichmentStatus.NO_SUGGESTIONS.value)
                for c in candidates]

    parsed = parse_hermes_response(raw)
    classifications, relationships = validate_suggestions(
        parsed, candidates, rel_vocab=rel_vocab)

    if not classifications and not relationships:
        return [_copy_candidate(c, enrichment_json=None,
                                enrichment_status=EnrichmentStatus.NO_SUGGESTIONS.value)
                for c in candidates]

    # Server-attached provenance: provider/model/prompt-version come from
    # the prompt payload, not the LLM. Every suggestion carries the same
    # provenance so reviewers can compare across candidates. The
    # ``__type__`` discriminator lets the executor rebuild typed objects
    # from a serialized JSON list without re-running validation.
    cls_dicts = [
        cls.model_dump() | {"provenance": dict(prov), "__type__": "classification"}
        for cls in classifications
    ]
    rel_dicts = [
        rel.model_dump() | {"provenance": dict(prov), "__type__": "relationship"}
        for rel in relationships
    ]
    by_candidate: dict[str, list[dict[str, Any]]] = {}
    # Classifications live on their target candidate; relationships live on
    # their source candidate. Both are surfaced in review under the same
    # ``suggestions`` map keyed by candidate_id.
    for entry in cls_dicts:
        by_candidate.setdefault(entry["candidate_id"], []).append(entry)
    for entry in rel_dicts:
        by_candidate.setdefault(entry["source_candidate_id"], []).append(entry)
    patched: list[Candidate] = []
    for candidate in candidates:
        own = by_candidate.get(candidate.candidate_id)
        patched.append(_copy_candidate(
            candidate,
            enrichment_json=own,
            enrichment_status=(EnrichmentStatus.OK.value if own
                               else EnrichmentStatus.NO_SUGGESTIONS.value),
        ))
    return patched


def _copy_candidate(candidate: Candidate, **overrides: Any) -> Candidate:
    """Return a new Candidate with selected fields overridden.

    Used by ``enrich_candidates`` so the input list is never mutated; every
    override is JSON-safe (list/dict/primitive) so the copy survives round
    trips through the SQLite JSON column.
    """
    data = candidate.model_dump()
    data.update(overrides)
    return Candidate.model_validate(data)


# ---------------------------------------------------------------------------
# importador-auto-frontmatter — enrichment funnel (Steps 2-4).
#
# The funnel turns complete-ficha candidates into reviewable frontmatter:
#   Step 2 — per-ficha dense summaries from the FULL body (200-400 tokens),
#            carrying ``{candidate_id, canonical_id, display_title}``.
#   Step 3 — ONE batched relationship pass over the summaries, anchored to
#            exact canonical ids; ambiguous leaf names are rejected.
#   Step 4 — type/frontmatter per ficha (``FrontmatterCandidate``) with
#            ``generated`` / ``manual`` / ``fallback`` state.
# Every step is fail-open (design risks 3 & 4): a timeout, unavailable
# gateway, malformed, or invalid output marks the affected candidates
# ``manual``/``fallback`` and preserves them — the import path never blocks on
# enrichment. Reuses ``validate_suggestions``, ``RelationshipSuggestion``,
# ``_REL_VOCAB_DEFAULT``, and the ``_copy_candidate`` fail-open pattern.
# ---------------------------------------------------------------------------


# Dense summary length guidance (tokens) surfaced to the model in Step 2.
_SUMMARY_WORD_BUDGET = (200, 400)


def _default_provenance() -> dict[str, str]:
    """Server-attached provenance dict for a funnel prompt (not LLM-derived)."""
    return {
        "prompt_version": DEFAULT_PROMPT_VERSION,
        "provider": DEFAULT_PROVIDER,
        "model": DEFAULT_MODEL,
    }


def _strip_code_fence(text: str) -> str:
    """Strip a single ```json ... ``` fence (Hermes' most common deviation)."""
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _extract_json_object_text(text: str) -> str | None:
    """Locate the first balanced ``{...}`` block in *text*, if any.

    Hermes frequently wraps its JSON in a ```json fence BUT also prepends a
    short intro (e.g. "Aquí tienes las fichas resumidas según el pipeline
    import-enrichment/v1.") or appends a closing remark. ``_strip_code_fence``
    only removes a fence when it is at the very start, so a prose prefix makes
    ``json.loads`` fail on the whole reply even though the object is intact
    inside. This scans for the first ``{`` and returns the substring up to the
    matching ``}`` (tracking nesting and string literals so a ``}`` inside a
    summary never ends the block early). Returns ``None`` when no ``{`` exists.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    # Unbalanced (e.g. truncated) — fall back to the rest of the string so the
    # caller's tolerant ``json.loads`` can still try the tail.
    return text[start:].strip()


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    """Tolerantly parse a Hermes reply into a JSON object, or ``None``.

    Tries in order: the whole (fence-stripped) reply, then the first balanced
    ``{...}`` substring embedded in prose. Fail-open: returns ``None`` when no
    object can be recovered — a malformed reply never raises.
    """
    text = _strip_code_fence(raw)
    if not text:
        return None
    for candidate in (text, _extract_json_object_text(text)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


def build_summary_prompt(candidates: list[Candidate]) -> dict[str, Any]:
    """Step 2 — per-ficha summary prompt from each candidate's full body.

    Each payload entry carries ``{candidate_id, canonical_id, display_title}``
    so Hermes never has to guess an identity, plus the complete body (the
    ficha's original text — preservation-first). The dense 200-400 token
    summary is what Step 3 relationships and Step 4 frontmatter reason over.
    """
    payload_candidates = [
        {
            "candidate_id": c.candidate_id,
            "canonical_id": c.canonical_id or c.normalized_identity,
            "display_title": c.display_title or c.normalized_identity,
            "body": (c.content_preview or "").strip(),
        }
        for c in candidates
    ]
    lo, hi = _SUMMARY_WORD_BUDGET
    instructions = (
        "You are summarizing imported worldbuilding fichas. For each supplied "
        f"candidate write a dense summary of {lo}-{hi} tokens that captures "
        "the essential, non-redundant facts of its body. Return a JSON object "
        "with a 'summaries' array; each entry must reference one candidate_id "
        "exactly and have a 'summary' string. NEVER invent facts or "
        "identities not present in the body."
    )
    return {
        "instructions": instructions,
        "provenance": _default_provenance(),
        "candidates": payload_candidates,
    }


def parse_summary_response(raw: str) -> dict[str, str]:
    """Step 2 parser: map ``candidate_id`` -> non-empty trimmed summary."""
    data = _parse_json_object(raw)
    if data is None:
        return {}
    entries = data.get("summaries", [])
    if not isinstance(entries, list):
        return {}
    out: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cid = entry.get("candidate_id")
        summary = entry.get("summary")
        if not isinstance(cid, str) or not isinstance(summary, str):
            continue
        summary = summary.strip()
        if cid and summary:
            out[cid] = summary
    return out


def build_relationship_batch_prompt(
    candidates: list[Candidate],
    *,
    rel_vocab: Iterable[str] | None = None,
    catalog: list[Candidate] | None = None,
) -> dict[str, Any]:
    """Step 3 — one relationship pass over the per-ficha summaries.

    Anchored to canonical ids: in-batch relationships reference an exact
    ``canonical_id`` (or candidate_id); ``validate_relationship_batch`` maps
    those back to candidates and rejects ambiguous leaf names. Reuses
    ``_REL_VOCAB_DEFAULT`` for the relationship vocabulary.

    ``catalog`` (importador-auto-frontmatter, global relationship reach) is the
    DOCUMENT-WIDE universe of valid targets: every ficha of the import. When
    supplied, targets may be any ficha of the whole document, not just the
    current batch, so a real relationship crossing two chunks survives. Sources
    stay limited to ``candidates`` (the batch, which is what has summaries to
    reason over). The catalog is small (ids + display titles, ~1.1k tokens for
    50+ fichas), so it fits in one call. When omitted, behavior is unchanged
    (in-batch only) for backward-compatible callers.
    """
    rel_vocab_set = frozenset(rel_vocab) if rel_vocab is not None else _REL_VOCAB_DEFAULT
    payload_candidates = [
        {
            "candidate_id": c.candidate_id,
            "canonical_id": c.canonical_id or c.normalized_identity,
            "display_title": c.display_title or c.normalized_identity,
            "summary": c.summary or "",
        }
        for c in candidates
    ]
    instructions = (
        "You are suggesting relationships between imported worldbuilding "
        "fichas based on their summaries. Return a JSON object with a "
        "'relationships' array. Each relationship must use "
        "'source_candidate_id' and 'target_canonical_id' referencing the "
        "EXACT canonical_id values supplied (never a bare or ambiguous "
        "display title). A source must be one of the supplied candidate_ids; "
        "a target may be any canonical_id in the catalog (if provided), not "
        "just the source ficha's own batch. Use 'relationship_type' from the "
        "vocabulary, 'confidence' in [0,1], and a short 'evidence' quote. "
        "NEVER invent canonical ids or targets outside the catalog/batch."
    )
    payload: dict[str, Any] = {
        "instructions": instructions,
        "rel_vocab": sorted(rel_vocab_set),
        "provenance": _default_provenance(),
        "candidates": payload_candidates,
    }
    if catalog is not None:
        payload["catalog"] = [
            {
                "canonical_id": c.canonical_id or c.normalized_identity,
                "display_title": c.display_title or c.normalized_identity,
            }
            for c in catalog
        ]
    return payload


def validate_relationship_batch(
    parsed: dict[str, Any],
    candidates: list[Candidate],
    *,
    rel_vocab: Iterable[str] | None = None,
    catalog: list[Candidate] | None = None,
) -> list[RelationshipSuggestion]:
    """Step 3 validator: canonical-id-anchored relationships, reusing
    ``validate_suggestions`` safety rules (vocabulary, confidence, self-link,
    grounding).

    Canonical ids are first mapped back to candidate ids so an ambiguous leaf
    name (e.g. ``"Descripción Física"`` when two branches share the title)
    never survives — only an exact ``canonical_id`` (fully qualified, e.g.
    ``"Ayagares::Descripción Física"``) matches a candidate. Returns
    ``RelationshipSuggestion`` objects anchored to ``candidate_id``.

    ``catalog`` (importador-auto-frontmatter, global relationship reach) is the
    DOCUMENT-WIDE universe. When supplied, the target grounds against the whole
    document (so a relationship crossing two chunks is not rejected as
    ungrounded), while the SOURCE stays restricted to ``candidates`` (the
    summarized batch — it needs a summary to reason over). A target in the
    catalog that is itself fallback still grounds, so the graph never breaks
    around a fallback ficha. When omitted, behavior is unchanged (per-batch
    grounding) for backward-compatible callers.
    """
    universe = catalog if catalog is not None else candidates
    by_canonical = {
        (c.canonical_id or c.normalized_identity): c.candidate_id for c in universe
    }
    by_candidate = {c.candidate_id: c.candidate_id for c in universe}
    source_ids = {c.candidate_id for c in candidates}
    rel_list = parsed.get("relationships", []) if isinstance(parsed, dict) else []
    remapped: list[dict[str, Any]] = []
    for entry in rel_list:
        if not isinstance(entry, dict):
            continue
        src = entry.get("source_candidate_id") or entry.get("source_canonical_id")
        tgt = (entry.get("target_candidate_id")
               or entry.get("target_canonical_id")
               or entry.get("target_name"))
        if not isinstance(src, str) or not isinstance(tgt, str):
            continue
        src_id = by_canonical.get(src) or by_candidate.get(src)
        tgt_id = by_canonical.get(tgt) or by_candidate.get(tgt)
        # Source must be a summarized ficha (has a summary to reason over).
        if src_id is None or src_id not in source_ids:
            continue  # ungrounded source or not summarized
        if tgt_id is None:
            continue  # ungrounded / ambiguous target — rejected
        if src_id == tgt_id:
            continue  # self-link rejected
        remapped.append({
            "id": entry.get("id"),
            "source_candidate_id": src_id,
            "target_candidate_id": tgt_id,
            "relationship_type": entry.get("relationship_type"),
            "confidence": entry.get("confidence"),
            "evidence": entry.get("evidence"),
        })
    _, relationships = validate_suggestions(
        {"classifications": [], "relationships": remapped},
        universe,
        rel_vocab=rel_vocab,
    )
    return relationships


def build_type_frontmatter_prompt(candidates: list[Candidate]) -> dict[str, Any]:
    """Step 4 — per-ficha type/frontmatter prompt.

    Generates a ``FrontmatterCandidate`` (``title``, ``type``, ``description``,
    ``relaciones``) from each ficha's summary. ``title`` defaults to the
    display title unless the body clearly implies a better canonical title.
    """
    payload_candidates = [
        {
            "candidate_id": c.candidate_id,
            "canonical_id": c.canonical_id or c.normalized_identity,
            "display_title": c.display_title or c.normalized_identity,
            "summary": c.summary or "",
        }
        for c in candidates
    ]
    instructions = (
        "You are writing OKF frontmatter for imported worldbuilding fichas. "
        "Return a JSON object with a 'frontmatter' array. Each entry must "
        "reference one candidate_id and provide 'title', 'type' (one of the "
        "entity types or null), a concise 'description', and 'relaciones' (an "
        "array of canonical ids from the supplied set). 'title' should match "
        "the display_title unless the body clearly implies a better canonical "
        "title. NEVER invent canonical ids outside the batch."
    )
    return {
        "instructions": instructions,
        "entity_vocab": list(entity_type_vocabulary()),
        "provenance": _default_provenance(),
        "candidates": payload_candidates,
    }


def parse_frontmatter_response(raw: str) -> dict[str, dict[str, Any]]:
    """Step 4 parser: map ``candidate_id`` -> ``FrontmatterCandidate`` dict.

    Only entries with a non-empty title are kept; ``type`` is normalized to
    ``None`` when absent/invalid. The returned dicts carry ``state`` equal to
    ``"generated"`` (the caller upgrades/degrades per candidate outcome).
    """
    data = _parse_json_object(raw)
    if data is None:
        return {}
    entries = data.get("frontmatter", [])
    if not isinstance(entries, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cid = entry.get("candidate_id")
        if not isinstance(cid, str) or not cid:
            continue
        title = entry.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        description = entry.get("description")
        if not isinstance(description, str):
            description = ""
        rel = entry.get("relaciones")
        rel_list = [r for r in rel if isinstance(r, str)] if isinstance(rel, list) else []
        fm_type = entry.get("type")
        if not isinstance(fm_type, str) or not fm_type:
            fm_type = None
        out[cid] = {
            "title": title.strip(),
            "type": fm_type,
            "description": description,
            "relaciones": rel_list,
            "state": FrontmatterState.GENERATED.value,
        }
    return out


def _fallback_frontmatter(candidate: Candidate) -> FrontmatterCandidate:
    """Reviewable fallback frontmatter for a candidate that failed enrichment."""
    return FrontmatterCandidate(
        title=candidate.display_title or candidate.normalized_identity,
        type=None,
        description="",
        relaciones=[],
        state=FrontmatterState.FALLBACK,
    )


# ---------------------------------------------------------------------------
# Combined Steps 3+4 (relationships + frontmatter in ONE Hermes call)
# ---------------------------------------------------------------------------


def build_frontmatter_and_relationships_prompt(
    candidates: list[Candidate],
    *,
    rel_vocab: Iterable[str] | None = None,
    catalog: list[Candidate] | None = None,
) -> dict[str, Any]:
    """Steps 3+4 — ONE relationship + frontmatter pass over summarized fichas.

    The funnel previously made two separate Hermes calls (Step 3 for
    relationships, Step 4 for frontmatter) over the same ``candidates``. Both
    consume the same per-ficha summary, so a single call returns both arrays
    at once, halving the LLM round-trips per chunk (the dominant cost of the
    slow enrichment phase). The combined prompt asks for a JSON object with a
    ``relationships`` array AND a ``frontmatter`` array; the caller validates
    each side independently (fail-open), so a malformed ``relationships`` half
    never discards a valid ``frontmatter`` half.

    Relationship grounding mirrors ``build_relationship_batch_prompt``: sources
    stay limited to ``candidates``; targets may be any ``canonical_id`` in the
    DOCUMENT-WIDE ``catalog``. Frontmatter mirrors
    ``build_type_frontmatter_prompt``: one ``title``/``type``/``description``/
    ``relaciones`` per candidate_id.
    """
    rel_vocab_set = frozenset(rel_vocab) if rel_vocab is not None else _REL_VOCAB_DEFAULT
    payload_candidates = [
        {
            "candidate_id": c.candidate_id,
            "canonical_id": c.canonical_id or c.normalized_identity,
            "display_title": c.display_title or c.normalized_identity,
            "summary": c.summary or "",
        }
        for c in candidates
    ]
    instructions = (
        "You are enriching imported worldbuilding fichas from their summaries. "
        "Return a single JSON object with TWO arrays: 'relationships' and "
        "'frontmatter'. "
        "'relationships': each entry needs 'source_candidate_id' (one of the "
        "supplied candidate_ids), 'target_canonical_id' (an EXACT canonical_id "
        "from the supplied catalog, never a bare or ambiguous title), "
        "'relationship_type' (from the vocabulary), 'confidence' in [0,1], and "
        "a short 'evidence' quote. NEVER invent targets outside the catalog. "
        "'frontmatter': each entry needs 'candidate_id', 'title' (match the "
        "display_title unless the body clearly implies a better canonical "
        "title), 'type' (one of the entity types or null), a concise "
        "'description', and 'relaciones' (an array of canonical ids from the "
        "supplied candidates). NEVER invent canonical ids outside the batch."
    )
    payload: dict[str, Any] = {
        "instructions": instructions,
        "rel_vocab": sorted(rel_vocab_set),
        "entity_vocab": list(entity_type_vocabulary()),
        "provenance": _default_provenance(),
        "candidates": payload_candidates,
    }
    if catalog is not None:
        payload["catalog"] = [
            {
                "canonical_id": c.canonical_id or c.normalized_identity,
                "display_title": c.display_title or c.normalized_identity,
            }
            for c in catalog
        ]
    return payload


def parse_frontmatter_and_relationships_response(
    raw: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Parse the combined Steps 3+4 response into (frontmatter, relationship).

    Returns ``(frontmatter_by_candidate, relationships_payload)``. The
    ``frontmatter`` dict is the ``parse_frontmatter_response`` shape (caller
    builds a ``FrontmatterCandidate``); the ``relationships`` payload is the
    raw parsed object the caller feeds to ``validate_relationship_batch``.
    Both sides are tolerant/independent: a malformed or missing ``frontmatter``
    half degrades to ``{}`` without touching the ``relationships`` half, and
    vice versa (fail-open — one bad half never kills the other).
    """
    data = _parse_json_object(raw)
    if data is None:
        return {}, {}
    # Frontmatter: same tolerant parsing as the Step 4 standalone path.
    fm_entries = data.get("frontmatter", [])
    fm_out: dict[str, dict[str, Any]] = {}
    if isinstance(fm_entries, list):
        for entry in fm_entries:
            if not isinstance(entry, dict):
                continue
            cid = entry.get("candidate_id")
            if not isinstance(cid, str) or not cid:
                continue
            title = entry.get("title")
            if not isinstance(title, str) or not title.strip():
                continue
            description = entry.get("description")
            if not isinstance(description, str):
                description = ""
            rel = entry.get("relaciones")
            rel_list = [r for r in rel if isinstance(r, str)] if isinstance(rel, list) else []
            fm_type = entry.get("type")
            if not isinstance(fm_type, str) or not fm_type:
                fm_type = None
            fm_out[cid] = {
                "title": title.strip(),
                "type": fm_type,
                "description": description,
                "relaciones": rel_list,
                "state": FrontmatterState.GENERATED.value,
            }
    # Relationships: keep the full parsed object for validate_relationship_batch.
    rel_payload: dict[str, Any] = {}
    if isinstance(data.get("relationships"), list):
        rel_payload["relationships"] = data["relationships"]
    return fm_out, rel_payload


def _ficha_byte_len(candidate: Candidate) -> int:
    """Byte length of a ficha's body (the size that drives the LLM prompt)."""
    return len(candidate.content_preview or "")


def _group_by_bytes(
    candidates: list[Candidate],
    *,
    budget_chars: int | None = None,
) -> list[list[Candidate]]:
    """Group complete fichas into chunks bounded by cumulative body bytes.

    INVARIANT (design): a ficha is NEVER split across chunks and NEVER
    truncated. Each group accumulates whole, already-complete fichas up to
    ``budget_chars`` (default ``_FUNNEL_CHUNK_BYTES``). A single ficha that
    alone exceeds the budget still travels COMPLETE and alone — the budget is
    a packing target, not a hard truncation limit. Empty input yields no
    groups; ficha order is preserved.
    """
    budget = budget_chars if budget_chars is not None else _FUNNEL_CHUNK_BYTES
    groups: list[list[Candidate]] = []
    current: list[Candidate] = []
    current_chars = 0
    for cand in candidates:
        cand_chars = _ficha_byte_len(cand)
        if current and current_chars + cand_chars > budget:
            groups.append(current)
            current = []
            current_chars = 0
        current.append(cand)
        current_chars += cand_chars
    if current:
        groups.append(current)
    return groups


def _fill_missing_summaries(
    candidates: list[Candidate],
    hermes_runner: Callable[[str, str], str],
    session_id: str,
    *,
    fill_group_size: int | None = None,
    max_rounds: int = 5,
) -> dict[str, str]:
    """Run Step 2 (summaries) and re-ask any candidate the model omitted.

    FAIL-OPEN and bounded: first returns summaries for the whole ``candidates``
    batch; then, for every candidate that came back WITHOUT a summary, re-asks
    in small groups (``fill_group_size``, default ``_FUNNEL_FILL_GROUP_SIZE``)
    so a single truncated/large response cannot drop a ficha again. Up to
    ``max_rounds`` of fill-in rounds run; a candidate the model genuinely
    cannot summarize stays missing (it falls back, but does not drag down the
    rest — see relationship-reach tests). Never raises.
    """
    size = fill_group_size if fill_group_size is not None else _FUNNEL_FILL_GROUP_SIZE
    summaries: dict[str, str] = {}

    def _ask(group: list[Candidate]) -> dict[str, str]:
        try:
            raw = hermes_runner(
                json.dumps(build_summary_prompt(group), ensure_ascii=False),
                session_id,
            )
        except Exception as exc:  # noqa: BLE001 — fail-open never breaks analyze
            logger.warning("funnel fill-in ask failed: %s", type(exc).__name__,
                           exc_info=True)
            return {}
        return parse_summary_response(raw or "")

    summaries.update(_ask(candidates))
    missing = [c for c in candidates if not summaries.get(c.candidate_id)]
    rounds = 0
    while missing and rounds < max_rounds:
        rounds += 1
        before = len(summaries)
        for start in range(0, len(missing), size):
            summaries.update(_ask(missing[start:start + size]))
        # No-progress guard: when a fill-in round recovers ZERO new summaries,
        # the runner is repeating a non-productive response (the observed
        # "same candidates, identical JSON" loop). Re-asking the same missing
        # group again would only burn a bounded but pointless round-trip, so
        # stop early and let the remaining candidates fail-open to fallback
        # (they do not drag down the rest — see relationship-reach tests).
        if len(summaries) == before:
            break
        missing = [c for c in candidates if not summaries.get(c.candidate_id)]
    return summaries


def _enrich_funnel_chunk(
    chunk: list[Candidate],
    hermes_runner: Callable[[str, str], str],
    session_id: str,
    *,
    catalog: list[Candidate],
    rel_vocab: Iterable[str] | None,
    prov: dict[str, str],
) -> list[Candidate]:
    """Run Steps 2-4 for ONE byte-bounded chunk (the unit of parallelism).

    Marked as a separate module-level function so ``analyze_ficha_funnel`` can
    fan chunks out to a bounded thread pool (``ThreadPoolExecutor``) without
    sharing mutable state between workers. Returns a NEW list of enriched
    candidates for this chunk, in the same order as ``chunk``. Fail-open: any
    step failure (timeout/malformed/unavailable) leaves the affected candidates
    with ``fallback``/``no_suggestions`` so the import path never blocks.

    The ``session_id`` is unique to this chunk (the caller appends a chunk
    index) so concurrent chunks do NOT share a gateway session — a shared
    session_id makes the gateway serialize concurrent turns ("two routing keys
    mapped to one session_id"), which caps enrichment at 1x. A per-chunk
    session is the whole point of the parallelism.
    """
    # Step 2 — per-ficha summaries from the full body (this chunk). Uses
    # fill-in: re-asks any candidate the model omitted in small groups, so a
    # single truncated response cannot drop a ficha (which would cascade into
    # loss of its relationships in Step 3, not just fallback).
    summaries: dict[str, str] = _fill_missing_summaries(
        chunk, hermes_runner, session_id)

    summarized: list[Candidate] = []
    for c in chunk:
        patched = _copy_candidate(c, summary=summaries.get(c.candidate_id, ""))
        if patched.summary:
            summarized.append(patched)
    summarized_by_id = {c.candidate_id: c for c in summarized}

    # Steps 3+4 — ONE combined relationship + frontmatter pass over this chunk's
    # summaries, grounded against the DOCUMENT-WIDE catalog. Sources stay
    # limited to this summarized batch; targets may be any ficha of the whole
    # document. Merging the two former calls halves the LLM round-trips per
    # chunk. Each half validates independently (fail-open): a malformed
    # relationships side never discards a valid frontmatter side.
    relationships: list[RelationshipSuggestion] = []
    frontmatter: dict[str, dict[str, Any]] = {}
    if summarized:
        try:
            raw = hermes_runner(
                json.dumps(
                    build_frontmatter_and_relationships_prompt(
                        summarized, rel_vocab=rel_vocab, catalog=catalog),
                    ensure_ascii=False,
                ),
                session_id,
            )
            fm_out, rel_payload = parse_frontmatter_and_relationships_response(raw)
            frontmatter = fm_out
            relationships = validate_relationship_batch(
                rel_payload, summarized, rel_vocab=rel_vocab, catalog=catalog)
        except Exception as exc:  # noqa: BLE001 — fail-open never breaks analyze
            logger.warning(
                "funnel steps 3+4 (relationships/frontmatter) failed: %s",
                type(exc).__name__, exc_info=True)

    rel_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for rel in relationships:
        rel_by_candidate.setdefault(rel.source_candidate_id, []).append(
            rel.model_dump()
            | {"provenance": dict(prov), "__type__": "relationship"})

    out: list[Candidate] = []
    for c in chunk:
        sc = summarized_by_id.get(c.candidate_id)
        fm_data = frontmatter.get(c.candidate_id)
        if fm_data is not None:
            candidate_fm = FrontmatterCandidate(
                title=fm_data["title"],
                type=fm_data["type"],
                description=fm_data["description"],
                relaciones=fm_data["relaciones"],
                state=FrontmatterState.GENERATED,
            )
        else:
            # Enrichment was attempted but produced no generated frontmatter
            # for this candidate -> fallback, reviewable and importable.
            candidate_fm = _fallback_frontmatter(sc or c)
        own = rel_by_candidate.get(c.candidate_id, [])
        out.append(_copy_candidate(
            sc or c,
            frontmatter=candidate_fm,
            enrichment_json=own or None,
            enrichment_status=(EnrichmentStatus.OK.value if own
                               else EnrichmentStatus.NO_SUGGESTIONS.value),
        ))
    return out


def _default_funnel_max_workers() -> int:
    """Resolve the funnel parallelism from env (``DEMIURGOS_IMPORT_WORKERS``).

    Defaults to 4 — the measured sweet spot (N=4 isolated per-chunk sessions
    gave a median ~3.6x wall-clock speedup with no error and no meaningful
    gateway RSS growth). Bounded so a 4 GB machine never sees the gateway
    spawn more sessions than it can safely interleave; overrides via env.
    """
    raw = os.getenv("DEMIURGOS_IMPORT_WORKERS", "")
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return 4
    return max(1, min(val, 8))


def _fail_open_runner(
    hermes_runner: Callable[[str, str], str],
) -> Callable[[str, str], str]:
    """Wrap a runner so a raising worker degrades to ``""`` instead of escaping.

    Used only on the degraded-chunk path: if a parallel worker raised (network,
    gateway, timeout), re-running its chunk through this wrapper lets
    ``_enrich_funnel_chunk`` fail-open (malformed/empty replies produce
    ``fallback``/``no_suggestions`` candidates) instead of re-raising the same
    exception. The import never blocks and the chunk never escapes.
    """
    if hermes_runner is None:
        return lambda _p, _s: ""
    def wrapper(prompt: str, session_id: str) -> str:
        try:
            return hermes_runner(prompt, session_id)
        except Exception as _exc:  # noqa: BLE001 — fail-open never breaks analyze
            logger.warning("funnel degraded-chunk runner failed: %s",
                           type(_exc).__name__, exc_info=True)
            return ""
    return wrapper


def analyze_ficha_funnel(
    candidates: list[Candidate],
    hermes_runner: Callable[[str, str], str] | None,
    *,
    rel_vocab: Iterable[str] | None = None,
    provenance: dict[str, str] | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
    max_workers: int | None = None,
    chunk_budget: int | None = None,
) -> list[Candidate]:
    """Run Steps 2-4 of the enrichment funnel over complete-ficha candidates.

    ``hermes_runner`` is the injected sync ``Callable[[prompt, session_id], str]``
    (gateway-independent, trivially mockable). Returns a NEW list; the input is
    never mutated. Each candidate is patched with ``summary``, ``frontmatter``
    (``FrontmatterCandidate``), and ``enrichment_json`` (relationship
    suggestions). Fail-open: a timeout, unavailable gateway, malformed, or
    invalid output at any step marks the affected candidates ``fallback`` and
    preserves them — the import path never blocks on enrichment (design risks
    3 & 4). Candidates are left ``manual`` only when no runner was supplied
    (enrichment not requested).

    Parallelism: chunks are processed through a bounded ``ThreadPoolExecutor``
    when ``max_workers > 1`` (default resolved from ``DEMIURGOS_IMPORT_WORKERS``,
    see ``_default_funnel_max_workers``). Each chunk gets a UNIQUE session_id
    (``import-funnel:{job}:chunk:{i}``) so concurrent chunks do not collide on a
    shared gateway session — a shared session makes the gateway serialize turns
    and caps enrichment at 1x. Output order and fail-open semantics are
    preserved: results are re-assembled in the original candidate order, and a
    raising/timing-out chunk only degrades its own candidates. ``max_workers=1``
    (or <= 1) keeps the historical purely-sequential behavior.

    ``chunk_budget`` overrides the byte bound for ``_group_by_bytes`` (tests and
    tuning): when set, it replaces ``_FUNNEL_CHUNK_BYTES`` for this call only.

    ``progress_cb`` (optional) is invoked as ``progress_cb(done, total)`` after
    each byte-bounded chunk completes, where ``done`` is the cumulative count of
    fichas fully enriched so far and ``total`` is ``len(candidates)``. It is a
    liveness hook — the caller may surface a coarse "ficha X de Y" progress bar
    during the slow Hermes phase. Never raised and never blocks enrichment.

    importador-auto-frontmatter (global relationship reach):
    * Chunks are bounded by BYTES (``_group_by_bytes``), not ficha count, so a
      large batch cannot truncate Hermes and drop the tail fichas.
    * Step 2 uses ``_fill_missing_summaries``: a candidate the model omits is
      re-asked in small groups, so a truncation cannot cascade into lost
      relationships for that ficha.
    * Step 3 grounds targets against a DOCUMENT-WIDE ``catalog`` (every ficha of
      the import), so a real relationship crossing two chunks is preserved
      instead of rejected as ungrounded. Sources stay per-chunk (summarized).
    """
    if hermes_runner is None or not candidates:
        # Enrichment not requested: leave candidates reviewable with a manual
        # frontmatter (guaranteeing frontmatter is never None after analysis).
        out: list[Candidate] = []
        for c in candidates:
            if c.frontmatter is None:
                c = _copy_candidate(c, frontmatter=FrontmatterCandidate(
                    title=c.display_title or c.normalized_identity,
                    type=None, description="", relaciones=[],
                    state=FrontmatterState.MANUAL))
            out.append(c)
        return out
    base_session_id = f"import-funnel:{candidates[0].job_id}"
    prov = dict(provenance or _default_provenance())
    # Enrichment WAS attempted: any candidate that ends up without generated
    # frontmatter is an affected candidate -> fallback (fail-open), never a
    # silent ``manual`` (manual is reserved for "no enrichment requested").

    # Document-wide relationship catalog (importador-auto-frontmatter): the
    # universe of valid targets for Step 3. It is every ficha of the import, so
    # a real relationship crossing two chunks is NOT rejected as ungrounded. It
    # also enumerates fallback fichas, so the graph never breaks around one.
    # It is small (ids + display titles, ~1.1k tokens for 50+ fichas), so it
    # fits in a single Step 3 call. Sources stay limited per-chunk.
    catalog = list(candidates)

    # Byte-bounded chunks (per ``_group_by_bytes``; ``chunk_budget`` overrides
    # only for this call when the caller (tests/tuning) supplies it).
    chunks = _group_by_bytes(candidates, budget_chars=chunk_budget)

    # Outer chunk callback used by both the sequential and the parallel paths.
    # It enriches chunk ``idx`` with its OWN session_id and returns
    # ``(idx, [Candidate])`` so the caller can re-assemble in input order.
    def _run_chunk(idx: int) -> tuple[int, list[Candidate]]:
        chunk = chunks[idx]
        chunk_session = f"{base_session_id}:chunk:{idx}"
        return idx, _enrich_funnel_chunk(
            chunk, hermes_runner, chunk_session,
            catalog=catalog, rel_vocab=rel_vocab, prov=prov)

    workers = max_workers if max_workers is not None else _default_funnel_max_workers()
    if workers <= 1 or len(chunks) <= 1:
        # Sequential (historical) path: one chunk at a time, deterministic order.
        final_flat: list[Candidate] = []
        _done = 0
        for idx in range(len(chunks)):
            _i, enriched = _run_chunk(idx)
            final_flat.extend(enriched)
            _done += len(chunks[idx])
            if progress_cb is not None:
                try:
                    progress_cb(_done, len(candidates))
                except Exception as _exc:  # noqa: BLE001 — progress is advisory
                    logger.warning("funnel progress_cb failed: %s",
                                   type(_exc).__name__, exc_info=True)
        return final_flat

    # Parallel path: a bounde ThreadPoolExecutor over independent chunks. Each
    # chunk uses its OWN session_id (unique per chunk, see ``_run_chunk``) so
    # concurrent chunks never share a gateway session — which would force the
    # gateway to serialize turns and defeat the parallelism. Correctness is
    # order-independent (read-only catalog + independent candidates), so we
    # simply re-assemble the results in the original chunk order below.
    final: list[list[Candidate]] = [None] * len(chunks)  # type: ignore[list-item]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        future_by_idx: dict[int, concurrent.futures.Future] = {}
        for idx in range(len(chunks)):
            future_by_idx[idx] = ex.submit(_run_chunk, idx)
        # Re-assemble in input order regardless of completion order.
        for idx in range(len(chunks)):
            try:
                _i, enriched = future_by_idx[idx].result()
                final[idx] = enriched
            except Exception:
                # Degraded chunk (a raising/timing-out worker): fail-open to a
                # non-raising fallback runner so the import never blocks and no
                # chunk ever escapes an exception. Only its own chunk degrades.
                final[idx] = _enrich_funnel_chunk(
                    chunks[idx], _fail_open_runner(hermes_runner),
                    f"{base_session_id}:chunk:{idx}",
                    catalog=catalog, rel_vocab=rel_vocab, prov=prov)

    ordered: list[Candidate] = []
    _done = 0
    for idx, enriched in enumerate(final):
        if enriched is None:
            continue
        ordered.extend(enriched)
        _done += len(chunks[idx])
        if progress_cb is not None:
            try:
                progress_cb(_done, len(candidates))
            except Exception as _exc:  # noqa: BLE001 — progress is advisory
                logger.warning("funnel progress_cb failed: %s",
                               type(_exc).__name__, exc_info=True)
    return ordered


# ---------------------------------------------------------------------------
# Pure content patch (used during execute, not analyze)
# ---------------------------------------------------------------------------


_RE_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
_RE_WIKILINK_INSIDE = re.compile(r"\[\[([^\]]+)\]\]")


def _split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Extract a tolerant YAML-lite frontmatter dict + the body.

    We deliberately avoid PyYAML here: the importer is on a read-only path
    and must never crash on malformed frontmatter. Unknown shapes are
    returned as ``{}``; non-string scalars are coerced to ``str``.
    """
    if not content.startswith("---"):
        return {}, content
    end = content.find("\n---", 3)
    if end < 0:
        return {}, content
    head = content[3:end].strip("\n")
    body = content[end + 4:].lstrip("\n")
    parsed: dict[str, Any] = {}
    for line in head.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            parsed[key] = value
    return parsed, body


def _serialize_frontmatter(fields: dict[str, Any]) -> str:
    """Serialize a flat dict back into a minimal ``---\n...\n---\n`` block.

    Values are coerced to strings; lists are emitted as YAML-style flow lists
    (``[a, b, c]``) so the parser round-trips and the diff stays minimal.
    ``relaciones`` is the OKF-open relationship convention: every entry is a
    ``[[Name]]`` wikilink, so the serialized form keeps that wrapping.
    """
    lines = ["---"]
    for key, value in fields.items():
        if key == "relaciones" and isinstance(value, list):
            items = ", ".join(_wrap_wikilink(v) for v in value)
            lines.append(f"relaciones: [{items}]")
        elif isinstance(value, list):
            items = ", ".join(str(v) for v in value)
            lines.append(f"{key}: [{items}]")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _wrap_wikilink(value: Any) -> str:
    """Ensure a value is serialized as a ``[[Name]]`` wikilink."""
    text = str(value).strip()
    if text.startswith("[[") and text.endswith("]]"):
        return text
    if text.startswith("[") and text.endswith("]") and not text.startswith("[["):
        # Strip a single-wrap that the parser left behind from legacy YAML.
        return f"[[{text[1:-1].strip()}]]"
    return f"[[{text}]]"


def apply_approved_suggestions(
    candidate: Candidate,
    *,
    classifications: list[ClassificationSuggestion],
    relationships: list[RelationshipSuggestion],
    approved_classification_ids: Iterable[str],
    approved_relationship_ids: Iterable[str],
) -> str:
    """Patch a candidate's ``content_preview`` per the approved suggestions.

    Pure: takes the existing preview + the approved IDs and returns the
    patched content string. Multiple classifications on the same candidate
    are not supported (one entity type wins); only the FIRST approved
    classification's ``type`` is applied. Approved relationships append
    deduplicated ``[[target]]`` entries to the existing ``relaciones`` list.

    Never raises on missing IDs; unknown IDs are skipped silently so a stale
    approval cannot break a fresh candidate.
    """
    preview = candidate.content_preview or ""
    fm, body = _split_frontmatter(preview)

    approved_cls_ids = set(approved_classification_ids)
    approved_rel_ids = set(approved_relationship_ids)
    for cls in classifications:
        if cls.candidate_id != candidate.candidate_id:
            continue
        if cls.id not in approved_cls_ids:
            continue
        if cls.type:
            fm["type"] = cls.type
        if cls.tags:
            # Merge tags without losing existing ones; case-insensitive dedupe.
            existing = [str(t).strip() for t in
                        re.findall(r"[^,\[\]]+",
                                   str(fm.get("tags", "")))]
            seen = {t.lower() for t in existing if t}
            merged = list(existing)
            for tag in cls.tags:
                if tag.lower() not in seen:
                    merged.append(tag)
                    seen.add(tag.lower())
            if merged:
                fm["tags"] = merged
        break  # only one classification per candidate

    # Relationships: append to ``relaciones`` (create the field if absent).
    new_links: list[str] = []
    for rel in relationships:
        if rel.source_candidate_id != candidate.candidate_id:
            continue
        if rel.id not in approved_rel_ids:
            continue
        target = rel.target_name or rel.target_candidate_id or ""
        if not target:
            continue
        new_links.append(f"[[{target}]]")

    if new_links:
        raw_rel = fm.get("relaciones", [])
        if isinstance(raw_rel, str):
            existing_links = _RE_WIKILINK_INSIDE.findall(raw_rel)
        elif isinstance(raw_rel, list):
            existing_links = []
            for item in raw_rel:
                if isinstance(item, str):
                    existing_links.extend(_RE_WIKILINK_INSIDE.findall(item))
        else:
            existing_links = []
        seen_links = set(existing_links)
        for link in new_links:
            target = link.strip("[]")
            if target not in seen_links:
                existing_links.append(target)
                seen_links.add(target)
        if existing_links:
            fm["relaciones"] = existing_links

    return _serialize_frontmatter(fm) + body


__all__ = [
    "DEFAULT_PROMPT_VERSION",
    "DEFAULT_PROVIDER",
    "DEFAULT_MODEL",
    "DEFAULT_TIMEOUT_SECONDS",
    "apply_approved_suggestions",
    "build_enrichment_prompt",
    "enrich_candidates",
    "entity_type_vocabulary",
    "parse_hermes_response",
    "validate_suggestions",
    # importador-auto-frontmatter enrichment funnel (Steps 2-4).
    "build_summary_prompt",
    "parse_summary_response",
    "build_relationship_batch_prompt",
    "validate_relationship_batch",
    "build_type_frontmatter_prompt",
    "parse_frontmatter_response",
    "analyze_ficha_funnel",
]
