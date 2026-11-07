"""Focused tests for the memory Curator and the deterministic policy."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from assistant_memory_store import AssistantMemoryStore  # noqa: E402
from memory_curator import (  # noqa: E402
    DEFAULT_CONFIDENCE_THRESHOLD,
    MemoryCandidate,
    MemoryCurator,
    apply_candidates,
    build_extraction_prompt,
    derive_topic_key,
    parse_candidates,
)


def _store(tmp_path: Path) -> AssistantMemoryStore:
    return AssistantMemoryStore(tmp_path / "memory.sqlite3")


def test_parse_valid_candidates() -> None:
    raw = (
        '{"memories":[{"kind":"canon","topic":"Ganic origin",'
        '"entity":"Ganic","statement":"Ganic llegó de fuera.",'
        '"confidence":0.92,"status":"accepted","scope":"project"}]}'
    )
    candidates = parse_candidates(raw)
    assert len(candidates) == 1
    assert candidates[0].kind == "canon"
    assert candidates[0].entity == "Ganic"
    assert candidates[0].confidence == pytest.approx(0.92)
    assert candidates[0].status == "accepted"


def test_parse_tolerates_code_fences_and_clamps_confidence() -> None:
    raw = (
        "```json\n"
        '{"memories":[{"kind":"canon","topic":"x","statement":"Something.",'
        '"confidence":3,"status":"weird","scope":"galaxy"}]}\n'
        "```"
    )
    candidate = parse_candidates(raw)[0]
    assert candidate.confidence == 1.0
    assert candidate.status == "accepted"
    assert candidate.scope == "project"


def test_parse_rejects_invalid_payloads() -> None:
    assert parse_candidates("") == []
    assert parse_candidates("not json") == []
    assert parse_candidates('{"memories": "no"}') == []
    assert parse_candidates('{"memories":[{"statement":""}]}') == []


def test_derive_topic_key_is_stable_and_world_scoped() -> None:
    first = derive_topic_key("Vibrantes", "project", "canon", "Ganic origin")
    second = derive_topic_key("Vibrantes", "project", "canon", "  GANIC   origin ")
    global_key = derive_topic_key("Vibrantes", "global", "preference", "Neutral Spanish")
    assert first == second == "world/vibrantes/canon/ganic-origin"
    assert global_key == "global/preference/neutral-spanish"


def test_apply_respects_the_confidence_threshold(tmp_path: Path) -> None:
    store = _store(tmp_path)
    candidates = [
        MemoryCandidate("canon", "Low", "Low confidence fact.", 0.2),
        MemoryCandidate("canon", "High", "High confidence fact.", 0.9),
    ]
    stored = apply_candidates(store, candidates, world="Vibrantes")
    assert [entry.topic_key for entry in stored] == [
        "world/vibrantes/canon/high"
    ]
    store.close()


def test_apply_explicit_bypasses_the_threshold(tmp_path: Path) -> None:
    store = _store(tmp_path)
    candidate = MemoryCandidate("preference", "Voice", "Prefers short answers.", 0.1)
    stored = apply_candidates(
        store, [candidate], world="Vibrantes", explicit=True,
    )
    assert stored[0].status == "accepted"
    store.close()


def test_apply_never_demotes_canon_with_a_proposal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    accepted = MemoryCandidate("canon", "Ganic origin", "Ganic llegó de fuera.", 0.9)
    apply_candidates(store, [accepted], world="Vibrantes")
    proposal = MemoryCandidate(
        "canon", "Ganic origin", "Ganic nació en el pueblo.", 0.9,
        status="proposal",
    )
    stored = apply_candidates(store, [proposal], world="Vibrantes")
    assert stored == []
    entry = store.find(
        topic_key="world/vibrantes/canon/ganic-origin", world="Vibrantes",
    )
    assert entry is not None and entry.statement == "Ganic llegó de fuera."
    assert entry.status == "accepted"
    store.close()


def test_apply_consolidates_near_duplicate_statements(tmp_path: Path) -> None:
    """Label drift from the LLM must not grow duplicate topics."""
    store = _store(tmp_path)
    first = MemoryCandidate(
        "canon", "llegada al pueblo",
        "Ganic llegó de joven a un pueblo de interior lejos de todo, sin decir de dónde venía.",
        0.9, entity="Ganic",
    )
    apply_candidates(store, [first], world="Vibrantes")
    second = MemoryCandidate(
        "canon", "ganic llegada al pueblo",
        "Ganic llegó de joven a un pueblo de interior, lejos de todo, sin decir de dónde venía.",
        0.9, entity="Ganic",
    )
    apply_candidates(store, [second], world="Vibrantes")

    entries = store.list(world="Vibrantes")
    assert len(entries) == 1
    assert entries[0].revision_count == 2
    store.close()


def test_apply_keeps_unrelated_facts_apart(tmp_path: Path) -> None:
    store = _store(tmp_path)
    apply_candidates(store, [
        MemoryCandidate("canon", "Ganic origin", "Ganic llegó de fuera.", 0.9, entity="Ganic"),
        MemoryCandidate("canon", "Ekkor", "El vibrastal de Ekkor canaliza el tiempo.", 0.9),
    ], world="Vibrantes")
    assert len(store.list(world="Vibrantes")) == 2
    store.close()


def test_apply_records_a_conflict_without_losing_canon(tmp_path: Path) -> None:
    store = _store(tmp_path)
    accepted = MemoryCandidate("canon", "Ganic origin", "Ganic llegó de fuera.", 0.9)
    apply_candidates(store, [accepted], world="Vibrantes")
    contradicting = MemoryCandidate(
        "canon", "Ganic origin", "Ganic nació en el pueblo.", 0.9,
    )
    stored = apply_candidates(store, [contradicting], world="Vibrantes")
    assert len(stored) == 1
    assert stored[0].status == "conflict"
    assert "#conflict:" in stored[0].topic_key
    canon = store.find(
        topic_key="world/vibrantes/canon/ganic-origin", world="Vibrantes",
    )
    assert canon is not None and canon.statement == "Ganic llegó de fuera."
    store.close()


def test_apply_default_threshold_is_exposed() -> None:
    assert DEFAULT_CONFIDENCE_THRESHOLD == 0.7


def test_curator_fails_open_without_a_completer() -> None:
    curator = MemoryCurator()
    assert asyncio.run(curator.extract(
        world="Vibrantes", user_text="Hola", assistant_text="Hola.",
    )) == []


def test_curator_returns_empty_when_the_model_fails() -> None:
    async def broken(_prompt: str) -> str:
        raise RuntimeError("gateway down")

    curator = MemoryCurator(broken)
    assert asyncio.run(curator.extract(
        world="Vibrantes", user_text="Hola", assistant_text="Hola.",
    )) == []


def test_curator_parses_the_model_response() -> None:
    async def complete(_prompt: str) -> str:
        return (
            '{"memories":[{"kind":"entity","topic":"Ganic",'
            '"entity":"Ganic","statement":"Ganic es relojero.",'
            '"confidence":0.8}]}'
        )

    curator = MemoryCurator(complete)
    candidates = asyncio.run(curator.extract(
        world="Vibrantes", user_text="Ganic es relojero", assistant_text="Anotado.",
    ))
    assert [candidate.topic for candidate in candidates] == ["Ganic"]


def test_extraction_prompt_is_language_agnostic_and_bounded() -> None:
    prompt = build_extraction_prompt(
        world="Vibrantes",
        user_text="Ganic llegó de fuera",
        assistant_text="Entendido.",
        skill_hints=["identity", "relationships"],
    )
    assert "Return ONLY a JSON object" in prompt
    assert "author's language" in prompt
    assert "Maximum 5 memories" in prompt
    assert "identity, relationships" in prompt
