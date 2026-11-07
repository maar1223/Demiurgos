"""LLM proposes, deterministic policy decides.

The Curator turns one conversation turn into at most ``MAX_CANDIDATES_PER_TURN``
durable-memory candidates. It never writes directly: ``apply_candidates`` is a
pure rules layer over ``AssistantMemoryStore`` that owns the confidence
threshold, topic-key derivation, dedupe, proposal-vs-canon and conflict handling.

Why this split: an LLM that both decides and writes eventually stores
hallucinations as canon. Here the model decides *what is extractable*; the rules
decide *what is durable*. A guided ``delta`` arrives as ``proposal`` and only an
acceptance promotes it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable

from assistant_memory_store import (
    AssistantMemoryStore,
    MemoryEntry,
    VALID_SCOPES,
    VALID_STATUSES,
    normalize_statement,
)

DEFAULT_CONFIDENCE_THRESHOLD = 0.7
MAX_CANDIDATES_PER_TURN = 5

_VALID_KINDS = frozenset(
    {"canon", "preference", "entity", "relationship", "fact"}
)

_SLUG_RE = re.compile(r"[^\wáéíóúüñÁÉÍÓÚÜÑ]+", re.UNICODE)


@dataclass(frozen=True)
class MemoryCandidate:
    """One proposed memory before the deterministic policy sees it."""

    kind: str
    topic: str
    statement: str
    confidence: float = 0.0
    status: str = "accepted"
    scope: str = "project"
    entity: str = ""


def slug(value: str, *, limit: int = 60) -> str:
    """Stable, readable slug that keeps Spanish letters."""
    text = _SLUG_RE.sub("-", str(value or "").strip().lower()).strip("-")
    return text[:limit] or "memory"


def derive_topic_key(world: str, scope: str, kind: str, topic: str) -> str:
    """Deterministic topic key, so the LLM cannot drift the same fact."""
    prefix = "global" if scope == "global" else f"world/{slug(world) or 'unknown'}"
    return f"{prefix}/{slug(kind)}/{slug(topic)}"


def _extract_json(raw: str) -> dict | None:
    """Tolerate code fences and surrounding prose around one JSON object."""
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_candidates(raw: str) -> list[MemoryCandidate]:
    """Validate and clamp the model's JSON into safe candidates."""
    payload = _extract_json(raw)
    if payload is None:
        return []
    items = payload.get("memories")
    if not isinstance(items, list):
        return []
    candidates: list[MemoryCandidate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        statement = " ".join(str(item.get("statement") or "").split())
        if not statement:
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in _VALID_KINDS:
            kind = "fact"
        topic = " ".join(str(item.get("topic") or "").split()) or statement[:80]
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(1.0, max(0.0, confidence))
        status = str(item.get("status") or "accepted").strip().lower()
        if status not in VALID_STATUSES or status == "conflict":
            status = "accepted"
        scope = str(item.get("scope") or "project").strip().lower()
        if scope not in VALID_SCOPES:
            scope = "project"
        entity = " ".join(str(item.get("entity") or "").split())
        candidates.append(MemoryCandidate(
            kind=kind,
            topic=topic,
            statement=statement,
            confidence=confidence,
            status=status,
            scope=scope,
            entity=entity,
        ))
        if len(candidates) >= MAX_CANDIDATES_PER_TURN:
            break
    return candidates


def _conflict_topic_key(topic_key: str, statement: str) -> str:
    digest = hashlib.sha256(normalize_statement(statement).encode("utf-8")).hexdigest()
    return f"{topic_key}#conflict:{digest[:8]}"


def apply_candidates(
    store: AssistantMemoryStore,
    candidates: Iterable[MemoryCandidate],
    *,
    world: str,
    source_session: str = "",
    source_turn: str = "",
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    explicit: bool = False,
) -> list[MemoryEntry]:
    """Persist the candidates that pass the deterministic policy."""
    stored: list[MemoryEntry] = []
    for candidate in list(candidates)[:MAX_CANDIDATES_PER_TURN]:
        if not explicit and candidate.confidence < confidence_threshold:
            continue
        scope = candidate.scope if candidate.scope in VALID_SCOPES else "project"
        entry_world = "" if scope == "global" else str(world or "")
        topic_key = derive_topic_key(
            entry_world, scope, candidate.kind, candidate.topic,
        )
        existing = store.find(scope=scope, world=entry_world, topic_key=topic_key)
        if existing is not None and existing.status == "accepted" and (
            candidate.status in {"proposal", "rumor"}
        ):
            # A draft or an in-world rumor never overwrites established canon.
            continue
        is_conflict = (
            existing is not None
            and existing.status == "accepted"
            and candidate.status == "accepted"
            and normalize_statement(existing.statement)
            != normalize_statement(candidate.statement)
        )
        target_key = (
            _conflict_topic_key(topic_key, candidate.statement)
            if is_conflict else topic_key
        )
        stored.append(store.upsert(
            world=entry_world,
            scope=scope,
            kind=candidate.kind,
            entity=candidate.entity,
            topic_key=target_key,
            statement=candidate.statement,
            confidence=candidate.confidence,
            status="conflict" if is_conflict else candidate.status,
            source_session=source_session,
            source_turn=source_turn,
        ))
    return stored


def build_extraction_prompt(
    *,
    world: str,
    user_text: str,
    assistant_text: str,
    skill_hints: Iterable[str] | None = None,
) -> str:
    """Prompt for one extraction pass. It must be language-agnostic."""
    hints = ", ".join(sorted({str(hint) for hint in (skill_hints or []) if hint}))
    return (
        "Extract durable memories from ONE conversation turn in a worldbuilding "
        "app. Return ONLY a JSON object, no prose:\n"
        '{"memories":[{"kind":"canon|preference|entity|relationship|fact",'
        '"topic":"short stable label","entity":"optional name",'
        '"statement":"one sentence","confidence":0.0-1.0,'
        '"status":"accepted|proposal|rumor","scope":"project|global"}]}\n'
        "Rules:\n"
        "- Save only durable facts the author stated or explicitly confirmed.\n"
        "- Anything the assistant suggested but the author did not accept is "
        'status "proposal".\n'
        '- In-world uncertain claims are "rumor".\n'
        "- Author preferences about how they work are scope \"global\"; world "
        'facts are "project".\n'
        "- Write the statement in the author's language. One sentence. No "
        "secrets, credentials or private data.\n"
        "- Maximum 5 memories. If nothing is worth remembering, return "
        '{"memories":[]}.\n'
        f"World: {world or '(none)'}\n"
        f"Active skill hints: {hints or '(none)'}\n"
        f"User: {user_text}\n"
        f"Assistant: {assistant_text}\n"
    )


class MemoryCurator:
    """Turn a conversation turn into candidates through one bounded LLM call."""

    def __init__(
        self,
        complete: Callable[[str], Awaitable[str]] | None = None,
    ) -> None:
        self._complete = complete

    async def extract(
        self,
        *,
        world: str,
        user_text: str,
        assistant_text: str,
        skill_hints: Iterable[str] | None = None,
    ) -> list[MemoryCandidate]:
        if self._complete is None:
            return []
        prompt = build_extraction_prompt(
            world=world,
            user_text=user_text,
            assistant_text=assistant_text,
            skill_hints=skill_hints,
        )
        try:
            raw = await self._complete(prompt)
        except Exception:
            return []
        return parse_candidates(raw)
