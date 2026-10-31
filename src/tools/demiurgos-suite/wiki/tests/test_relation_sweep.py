"""Unit tests for the on-demand sweep (P3)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _path in (str(_HERE.parent), str(_HERE.parents[2])):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from relation_candidates import body_digest
from relation_proposals import load_proposals
from relation_state import load_state
from relation_sweep import sweep_next


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


def _sweep(entities: list[dict], runner, *, mundos: Path, rejected=None):
    return sweep_next(
        mundo="world",
        mundos_dir=mundos,
        index=FakeIndex(entities),
        runner=runner,
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

    assert result.status == "swept"
    assert result.path == "lore/alpha.md"
    assert result.created == 1
    assert result.pending == 1
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
    assert load_state(mundos / "world").swept == {}


def test_no_candidates_finishes(tmp_path: Path) -> None:
    mundos = tmp_path / "mundos"
    entities = [
        _entity("lore/alpha.md", "lore::alpha", "Alpha", "Nothing connects."),
        _entity("lore/beta.md", "lore::beta", "Beta", "Beta."),
    ]

    result = _sweep(entities, _runner({"relationships": []}), mundos=mundos)

    assert result.status == "done"


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
