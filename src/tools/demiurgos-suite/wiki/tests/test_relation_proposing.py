"""Unit tests for the batch-safe proposal primitive.

The property under test is the one that broke the importer: a batch must be
able to change RECALL (which fichas got a turn) but never TRUTH (which pairs
exist). Every claim below is justified by its own source body or dropped.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _path in (str(_HERE.parent), str(_HERE.parents[2])):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from relation_proposing import (
    CatalogEntry,
    Claim,
    Source,
    build_proposal_prompt,
    pair_key,
    propose_relations,
    quote_in_body,
    verify_claims,
)


def _catalog(*ids: str) -> list[CatalogEntry]:
    return [CatalogEntry(canonical_id=value, display_title=value) for value in ids]


def _source(key: str, body: str, name: str = "") -> Source:
    return Source(key=key, path=f"lore/{key}.md", name=name or key, body=body)


def _runner(*claims: dict):
    return lambda prompt, session_id: json.dumps({"relationships": list(claims)})


def _claim(source: str, target: str, quote: str, **extra):
    payload = {
        "source_canonical_id": source,
        "target_canonical_id": target,
        "evidence": quote,
        "relationship_type": "related",
        "confidence": 0.8,
    }
    payload.update(extra)
    return payload


# --- evidence ---------------------------------------------------------------


def test_quote_must_appear_in_the_source_body() -> None:
    assert quote_in_body("El Director acompaña al Conector.", "acompaña al Conector")
    assert not quote_in_body("El Director acompaña al Conector.", "una frase inventada")


def test_quote_normalization_ignores_case_accents_and_punctuation() -> None:
    body = "El Áyagar del 1er Stal — Director, refleja al Vibrante."
    assert quote_in_body(body, "el ayagar del 1er stal director")
    assert quote_in_body(body, "EL ÁYAGAR DEL 1ER STAL")


def test_elided_quote_is_accepted_when_every_fragment_appears() -> None:
    body = "El Director ordena. El Conector conecta. El Proyector proyecta."
    assert quote_in_body(body, "El Director ordena... El Proyector proyecta")


def test_a_two_character_fragment_is_not_evidence() -> None:
    assert not quote_in_body("El Director ordena el mundo.", "el")


# --- the importer regression: batch membership is not evidence ---------------


def test_a_batch_of_eight_without_mentions_produces_no_clique() -> None:
    """The K8 pathology: the model enumerates the batch instead of the text."""
    sources = [_source(f"entity-{index}", f"Body {index} with no names.") for index in range(8)]
    claims = [
        _claim(left.key, right.key, "")  # no quote at all
        for left in sources
        for right in sources
        if left.key != right.key
    ]
    assert verify_claims(claims, sources, _catalog(*[s.key for s in sources])) == []


def test_a_quoted_sentence_from_another_source_is_not_evidence() -> None:
    sources = [
        _source("alpha", "Alpha mentions Beta explicitly."),
        _source("beta", "Beta is about something else."),
    ]
    # The claim quotes ALPHA but pretends to be about BETA as the source.
    claim = _claim("beta", "alpha", "Alpha mentions Beta explicitly.")
    assert verify_claims([claim], sources, _catalog("alpha", "beta")) == []


# --- batch independence ------------------------------------------------------


def test_cross_batch_pairs_are_identical_to_single_call_pairs() -> None:
    alpha = _source("alpha", "Alpha mentions Beta explicitly.")
    beta = _source("beta", "Beta mentions Alpha explicitly.")
    catalog = _catalog("alpha", "beta")
    payload = [
        _claim("alpha", "beta", "Alpha mentions Beta explicitly."),
        _claim("beta", "alpha", "Beta mentions Alpha explicitly."),
    ]

    together = propose_relations(
        sources=[alpha, beta], catalog=catalog, runner=_runner(*payload)
    )
    first = propose_relations(sources=[alpha], catalog=catalog, runner=_runner(*payload))
    second = propose_relations(sources=[beta], catalog=catalog, runner=_runner(*payload))

    assert {claim.pair for claim in together} == {
        claim.pair for claim in first + second
    }
    assert {claim.pair for claim in together} == {pair_key("alpha", "beta")}


def test_symmetric_claims_collapse_to_one_pair_on_a_deterministic_side() -> None:
    alpha = _source("alpha", "Alpha mentions Beta explicitly.")
    beta = _source("beta", "Beta mentions Alpha explicitly.")
    claims = verify_claims(
        [
            _claim("alpha", "beta", "Alpha mentions Beta explicitly.", confidence=0.9),
            _claim("beta", "alpha", "Beta mentions Alpha explicitly.", confidence=0.4),
        ],
        [alpha, beta],
        _catalog("alpha", "beta"),
    )
    assert len(claims) == 1
    assert claims[0].pair == pair_key("alpha", "beta")
    assert claims[0].anchor == "alpha"


# --- rejections --------------------------------------------------------------


def test_target_outside_the_world_catalog_is_dropped() -> None:
    alpha = _source("alpha", "Alpha mentions Beta explicitly.")
    assert (
        verify_claims(
            [_claim("alpha", "gamma", "Alpha mentions Beta explicitly.")],
            [alpha],
            _catalog("alpha", "beta"),
        )
        == []
    )


def test_unknown_source_self_link_and_known_pairs_are_dropped() -> None:
    alpha = _source("alpha", "Alpha mentions Beta explicitly.")
    body_quote = "Alpha mentions Beta explicitly."
    catalog = _catalog("alpha", "beta")
    assert verify_claims([_claim("ghost", "beta", body_quote)], [alpha], catalog) == []
    assert verify_claims([_claim("alpha", "alpha", body_quote)], [alpha], catalog) == []
    assert (
        verify_claims(
            [_claim("alpha", "beta", body_quote)],
            [alpha],
            catalog,
            known_pairs=[pair_key("alpha", "beta")],
        )
        == []
    )


def test_runner_failure_yields_no_claims() -> None:
    def exploding(prompt: str, session_id: str) -> str:
        raise RuntimeError("provider down")

    assert (
        propose_relations(
            sources=[_source("alpha", "Alpha mentions Beta.")],
            catalog=_catalog("alpha", "beta"),
            runner=exploding,
        )
        == []
    )


def test_malformed_reply_yields_no_claims() -> None:
    assert (
        propose_relations(
            sources=[_source("alpha", "Alpha mentions Beta.")],
            catalog=_catalog("alpha", "beta"),
            runner=lambda prompt, session_id: "not json at all",
        )
        == []
    )


# --- prompt shape ------------------------------------------------------------


def test_prompt_forbids_reading_the_batch_as_a_group() -> None:
    prompt = build_proposal_prompt(
        [_source("alpha", "body"), _source("beta", "body")],
        _catalog("alpha", "beta"),
    )
    instructions = prompt["instructions"]
    assert "on its OWN" in instructions
    assert "NOT context" in instructions
    assert "VERBATIM" in instructions
    assert [entry["canonical_id"] for entry in prompt["catalog"]] == ["alpha", "beta"]
    assert [entry["canonical_id"] for entry in prompt["sources"]] == ["alpha", "beta"]


def test_claim_anchor_is_order_independent() -> None:
    left = Claim(source_key="zed", target_id="alpha", quote="q")
    right = Claim(source_key="alpha", target_id="zed", quote="q")
    assert left.pair == right.pair == ("alpha", "zed")
    assert left.anchor == right.anchor == "alpha"


def test_outcome_distinguishes_nothing_found_from_no_answer() -> None:
    from relation_proposing import propose_relations_outcome

    source = _source("alpha", "Alpha mentions Beta.")
    catalog = _catalog("alpha", "beta")
    empty = propose_relations_outcome(
        sources=[source],
        catalog=catalog,
        runner=lambda prompt, session_id: json.dumps({"relationships": []}),
    )
    assert empty.provider_ok is True
    assert empty.claims == ()
    silent = propose_relations_outcome(
        sources=[source],
        catalog=catalog,
        runner=lambda prompt, session_id: "",
    )
    assert silent.provider_ok is False
