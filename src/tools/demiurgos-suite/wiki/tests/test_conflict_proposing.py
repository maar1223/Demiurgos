"""Unit tests for semantic ficha-vs-ficha conflict proposals (S3)."""

from __future__ import annotations

import json

from conflict_proposing import (
    ConflictClaim,
    SourceFicha,
    build_conflict_prompt,
    parse_conflict_response,
    propose_conflicts_outcome,
    verify_conflict_claims,
)

SOURCE_BODY = "El rey Alar nació en el año 120 y murió en el 190."
TARGET_BODY = "Alar, rey de Vesta, nació en el año 145."


def _source() -> SourceFicha:
    return SourceFicha(key="A", path="lore/alar.md", name="Alar", body=SOURCE_BODY)


def _target() -> SourceFicha:
    return SourceFicha(key="B", path="lore/vesta.md", name="Vesta", body=TARGET_BODY)


def _claim(**overrides) -> dict:
    claim = {
        "target_canonical_id": "B",
        "conflict_type": "date",
        "quote_source": "nació en el año 120",
        "quote_target": "nació en el año 145",
        "confidence": 0.8,
    }
    claim.update(overrides)
    return claim


def test_prompt_carries_the_source_and_its_targets() -> None:
    prompt = build_conflict_prompt(_source(), [_target()])

    assert prompt["source"]["canonical_id"] == "A"
    assert prompt["source"]["body"] == SOURCE_BODY
    assert prompt["targets"][0]["canonical_id"] == "B"
    assert "quote_source" in prompt["instructions"]
    assert "quote_target" in prompt["instructions"]


def test_parse_reads_the_contradictions_array() -> None:
    raw = json.dumps({"contradictions": [_claim()]})

    assert parse_conflict_response(raw) == [_claim()]


def test_parse_accepts_a_fenced_json_reply() -> None:
    raw = "```json\n" + json.dumps({"contradictions": [_claim()]}) + "\n```"

    assert len(parse_conflict_response(raw)) == 1


def test_parse_fails_open_on_garbage() -> None:
    assert parse_conflict_response("not json at all") == []
    assert parse_conflict_response("") == []


def test_claim_survives_when_both_quotes_are_in_their_bodies() -> None:
    claims = verify_conflict_claims([_claim()], _source(), [_target()], known=set())

    assert len(claims) == 1
    claim = claims[0]
    assert isinstance(claim, ConflictClaim)
    assert claim.source_key == "A"
    assert claim.target_key == "B"
    assert claim.conflict_type == "date"
    assert claim.conflict_id.startswith("semantic:")


def test_claim_without_the_source_quote_is_discarded() -> None:
    claims = verify_conflict_claims(
        [_claim(quote_source="nació en el año 999")], _source(), [_target()], known=set()
    )

    assert claims == []


def test_claim_without_the_target_quote_is_discarded() -> None:
    claims = verify_conflict_claims(
        [_claim(quote_target="nació en el año 999")], _source(), [_target()], known=set()
    )

    assert claims == []


def test_claim_with_a_short_quote_is_discarded() -> None:
    claims = verify_conflict_claims(
        [_claim(quote_source="el", quote_target="de")], _source(), [_target()], known=set()
    )

    assert claims == []


def test_unknown_target_is_discarded() -> None:
    claims = verify_conflict_claims(
        [_claim(target_canonical_id="Z")], _source(), [_target()], known=set()
    )

    assert claims == []


def test_self_pair_is_discarded() -> None:
    claims = verify_conflict_claims(
        [_claim(target_canonical_id="A")], _source(), [_target()], known=set()
    )

    assert claims == []


def test_already_known_pair_and_type_is_discarded() -> None:
    known = {("A", "B", "date")}

    claims = verify_conflict_claims([_claim()], _source(), [_target()], known=known)

    assert claims == []


def test_conflict_type_is_normalized_and_bounded() -> None:
    claims = verify_conflict_claims(
        [_claim(conflict_type="Date Contradiction!!")],
        _source(),
        [_target()],
        known=set(),
    )

    assert claims[0].conflict_type == "date-contradiction"


def test_unknown_conflict_type_falls_back_to_other() -> None:
    claims = verify_conflict_claims(
        [_claim(conflict_type="")], _source(), [_target()], known=set()
    )

    assert claims[0].conflict_type == "other"


def test_highest_confidence_wins_for_the_same_slot() -> None:
    low = _claim(confidence=0.2)
    high = _claim(confidence=0.9)

    claims = verify_conflict_claims(
        [low, high], _source(), [_target()], known=set()
    )

    assert len(claims) == 1
    assert claims[0].confidence == 0.9


def test_provider_outage_is_not_a_crash_and_is_not_ok() -> None:
    def runner(_prompt: str, _session: str) -> str:
        raise RuntimeError("provider down")

    outcome = propose_conflicts_outcome(
        source=_source(), targets=[_target()], runner=runner, known=set()
    )

    assert outcome.claims == ()
    assert outcome.provider_ok is False


def test_provider_answer_without_contradictions_is_ok() -> None:
    def runner(_prompt: str, _session: str) -> str:
        return json.dumps({"contradictions": []})

    outcome = propose_conflicts_outcome(
        source=_source(), targets=[_target()], runner=runner, known=set()
    )

    assert outcome.claims == ()
    assert outcome.provider_ok is True


def test_provider_claims_are_verified() -> None:
    def runner(_prompt: str, _session: str) -> str:
        return json.dumps({"contradictions": [_claim()]})

    outcome = propose_conflicts_outcome(
        source=_source(), targets=[_target()], runner=runner, known=set()
    )

    assert outcome.provider_ok is True
    assert len(outcome.claims) == 1


def test_no_targets_means_no_call() -> None:
    calls: list[str] = []

    def runner(prompt: str, _session: str) -> str:
        calls.append(prompt)
        return "{}"

    outcome = propose_conflicts_outcome(
        source=_source(), targets=[], runner=runner, known=set()
    )

    assert outcome.claims == ()
    assert outcome.provider_ok is False
    assert calls == []
