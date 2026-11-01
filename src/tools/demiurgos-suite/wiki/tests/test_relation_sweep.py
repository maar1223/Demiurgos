"""Unit tests for the batch-safe on-demand sweep (P3/S2)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _path in (str(_HERE.parent), str(_HERE.parents[2])):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import relation_sweep
from relation_candidates import body_digest
from relation_proposals import load_proposals
from relation_proposing import pair_key
from relation_state import load_state
from relation_sweep import clamp_batch_size, sweep_batch


class FakeIndex:
    def __init__(self, entities: list[dict]) -> None:
        self._entities = entities

    def entities(self) -> list[dict]:
        return [dict(entity) for entity in self._entities]


def _entity(path: str, canonical_id: str, name: str, body: str = "", relaciones=()) -> dict:
    return {
        "path": path,
        "id": canonical_id,
        "name": name,
        "content": body,
        "relaciones": list(relaciones),
    }


def _runner(payload: dict):
    return lambda prompt, session_id: json.dumps(payload)


def _sweep(
    entities: list[dict],
    runner,
    *,
    mundos: Path,
    batch_size: int = 5,
):
    return sweep_batch(
        mundo="world",
        mundos_dir=mundos,
        index=FakeIndex(entities),
        runner=runner,
        batch_size=batch_size,
    )


def _standard_entities() -> list[dict]:
    return [
        _entity("lore/alpha.md", "lore::alpha", "Alpha", "Alpha served Beta."),
        _entity("lore/beta.md", "lore::beta", "Beta", "Beta."),
    ]


def test_sweep_proposes_and_marks_the_ficha_swept(tmp_path: Path) -> None:
    mundos = tmp_path / "mundos"

    result = _sweep(
        _standard_entities(),
        _runner(
            {
                "relationships": [
                    {
                        "source_canonical_id": "lore::alpha",
                        "target_canonical_id": "lore::beta",
                        "relationship_type": "aliado-de",
                        "confidence": 0.9,
                        "evidence": "Alpha served Beta.",
                    }
                ]
            }
        ),
        mundos=mundos,
    )

    assert result.status == "swept"
    assert result.swept == 1
    assert result.created == 1
    assert result.pending == 1
    assert result.paths == ["lore/alpha.md"]
    proposals = load_proposals(mundos / "world")
    assert proposals[0].target_id == "lore::beta"
    state = load_state(mundos / "world")
    assert state.swept["lore/alpha.md"] == body_digest("Alpha served Beta.")


def test_a_silent_provider_does_not_mark_the_ficha_swept(tmp_path: Path) -> None:
    mundos = tmp_path / "mundos"

    result = _sweep(
        _standard_entities(),
        lambda prompt, session_id: "",
        mundos=mundos,
    )

    assert result.status == "unavailable"
    assert result.swept == 0
    assert load_state(mundos / "world").swept == {}


def test_a_raising_provider_does_not_mark_the_ficha_swept(tmp_path: Path) -> None:
    mundos = tmp_path / "mundos"

    def boom(prompt: str, session_id: str) -> str:
        raise RuntimeError("upstream down")

    result = _sweep(_standard_entities(), boom, mundos=mundos)

    assert result.status == "unavailable"
    assert load_state(mundos / "world").swept == {}


def test_no_candidates_finishes(tmp_path: Path) -> None:
    mundos = tmp_path / "mundos"
    entities = [
        _entity("lore/alpha.md", "lore::alpha", "Alpha", "Nothing connects."),
        _entity("lore/beta.md", "lore::beta", "Beta", "Beta."),
    ]

    result = _sweep(entities, _runner({"relationships": []}), mundos=mundos)

    assert result.status == "done"
    assert result.swept == 0


def test_a_declared_target_is_not_proposed(tmp_path: Path) -> None:
    mundos = tmp_path / "mundos"
    entities = [
        _entity(
            "lore/alpha.md",
            "lore::alpha",
            "Alpha",
            "Alpha served Beta.",
            relaciones=["lore::beta"],
        ),
        _entity("lore/beta.md", "lore::beta", "Beta", "Beta."),
    ]

    result = _sweep(
        entities,
        _runner(
            {
                "relationships": [
                    {
                        "source_candidate_id": "lore::alpha",
                        "target_canonical_id": "lore::beta",
                        "relationship_type": "aliado-de",
                        "confidence": 0.9,
                        "evidence": "Alpha served Beta.",
                    }
                ]
            }
        ),
        mundos=mundos,
    )

    assert result.created == 0
    assert result.status == "swept"
    assert load_proposals(mundos / "world") == []


def test_an_ungrounded_target_is_dropped(tmp_path: Path) -> None:
    mundos = tmp_path / "mundos"

    result = _sweep(
        _standard_entities(),
        _runner(
            {
                "relationships": [
                    {
                        "source_candidate_id": "lore::alpha",
                        "target_canonical_id": "lore::ghost",
                        "relationship_type": "aliado-de",
                        "confidence": 0.9,
                        "evidence": "Alpha served a ghost.",
                    }
                ]
            }
        ),
        mundos=mundos,
    )

    assert result.created == 0
    assert result.status == "swept"


def test_a_rejected_pair_is_not_proposed(tmp_path: Path) -> None:
    mundos = tmp_path / "mundos"
    world = mundos / "world"
    (world / ".relations").mkdir(parents=True)
    (world / ".relations" / "rejected.json").write_text(
        json.dumps({"version": 1, "rejected": [["lore::alpha", "lore::beta"]]}),
        encoding="utf-8",
    )
    # The rejected pair stops being a mention, so there is no candidate at all.
    result = _sweep(_standard_entities(), _runner({"relationships": []}), mundos=mundos)

    assert result.status == "done"
    assert load_proposals(world) == []


def test_the_quote_is_verified_against_the_full_body(
    tmp_path: Path, monkeypatch
) -> None:
    """The prompt excerpt may be truncated; evidence uses the full body (S1)."""
    mundos = tmp_path / "mundos"
    monkeypatch.setattr(relation_sweep, "SOURCE_BODY_LIMIT", 20)
    body = ("x" * 30) + " Alpha served Beta."
    entities = [
        _entity("lore/alpha.md", "lore::alpha", "Alpha", body),
        _entity("lore/beta.md", "lore::beta", "Beta", "Beta."),
    ]

    result = _sweep(
        entities,
        _runner(
            {
                "relationships": [
                    {
                        "source_canonical_id": "lore::alpha",
                        "target_canonical_id": "lore::beta",
                        "relationship_type": "aliado-de",
                        "confidence": 0.9,
                        "evidence": "Alpha served Beta.",
                    }
                ]
            }
        ),
        mundos=mundos,
    )

    assert result.created == 1
    assert load_proposals(mundos / "world")[0].evidence == "Alpha served Beta."


def test_batch_size_is_clamped() -> None:
    assert clamp_batch_size(0) == 1
    assert clamp_batch_size(3) == 3
    assert clamp_batch_size(99) == 10
    assert clamp_batch_size(None) == 5
    assert clamp_batch_size(True) == 5
    assert clamp_batch_size("4") == 5


def test_a_zero_batch_size_reviews_exactly_one_ficha(tmp_path: Path) -> None:
    mundos = tmp_path / "mundos"
    entities = [
        _entity("lore/aaa.md", "lore::aaa", "Alpha", "Alpha served Beta."),
        _entity("lore/bbb.md", "lore::bbb", "Gamma", "Gamma served Beta."),
        _entity("lore/beta.md", "lore::beta", "Beta", "Beta."),
    ]

    result = _sweep(entities, _runner({"relationships": []}), mundos=mundos, batch_size=0)

    assert result.paths == ["lore/aaa.md"]
    state = load_state(mundos / "world")
    assert set(state.swept) == {"lore/aaa.md"}


def test_candidates_are_ordered_by_value_before_the_batch(tmp_path: Path) -> None:
    """The first batch must start with the richest ficha, not its sibling."""
    mundos = tmp_path / "mundos"
    entities = [
        _entity("lore/aaa.md", "lore::aaa", "Alpha", "Alpha served Beta."),
        _entity(
            "lore/bbb.md",
            "lore::bbb",
            "Beta",
            "Beta offered Gamma and Delta and Epsilon.",
        ),
        _entity("lore/gamma.md", "lore::gamma", "Gamma", "Gamma."),
        _entity("lore/delta.md", "lore::delta", "Delta", "Delta."),
        _entity("lore/epsilon.md", "lore::epsilon", "Epsilon", "Epsilon."),
    ]

    result = _sweep(entities, _runner({"relationships": []}), mundos=mundos, batch_size=1)

    assert result.paths == ["lore/bbb.md"]


def _per_source_runner(prompt: str, session_id: str) -> str:
    """One independent claim per source: pair it with the world's Gamma."""
    data = json.loads(prompt)
    relationships = []
    for source in data.get("sources", []):
        source_key = source.get("canonical_id") or ""
        body = source.get("body") or ""
        if not source_key or source_key == "lore::gamma":
            continue
        relationships.append(
            {
                "source_canonical_id": source_key,
                "target_canonical_id": "lore::gamma",
                "relationship_type": "aliado-de",
                "confidence": 0.8,
                "evidence": body.strip(),
            }
        )
    return json.dumps({"relationships": relationships})


def _independence_entities() -> list[dict]:
    return [
        _entity("lore/alpha.md", "lore::alpha", "Alpha", "Alpha met Gamma."),
        _entity("lore/beta.md", "lore::beta", "Beta", "Beta met Gamma."),
        _entity("lore/gamma.md", "lore::gamma", "Gamma", "Gamma."),
    ]


def _proposal_pairs(world: Path) -> list[tuple[str, str, str, str]]:
    return sorted(
        (proposal.source_key, proposal.target_id, proposal.relationship_type, proposal.evidence)
        for proposal in load_proposals(world)
    )


def test_batch_composition_does_not_change_the_pair_set(tmp_path: Path) -> None:
    """S2: one call and split calls must produce the same graph."""
    single = tmp_path / "single"
    split = tmp_path / "split"

    one_call = _sweep(
        _independence_entities(), _per_source_runner, mundos=single, batch_size=10
    )
    assert one_call.swept == 2

    first = _sweep(
        _independence_entities(), _per_source_runner, mundos=split, batch_size=1
    )
    second = _sweep(
        _independence_entities(), _per_source_runner, mundos=split, batch_size=1
    )
    assert first.swept == 1
    assert second.swept == 1

    assert _proposal_pairs(single / "world") == _proposal_pairs(split / "world")
    assert {
        pair_key(item[0], item[1]) for item in _proposal_pairs(single / "world")
    } == {
        pair_key(item[0], item[1]) for item in _proposal_pairs(split / "world")
    }
