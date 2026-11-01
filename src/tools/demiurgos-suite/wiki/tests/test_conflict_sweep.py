"""Unit tests for the semantic conflict sweep (S3)."""

from __future__ import annotations

import json
from pathlib import Path

from conflict_decisions import load_records, record_proposal
from conflict_sweep import clamp_batch_size, sweep_conflicts_batch
from relation_candidates import body_digest


class FakeIndex:
    def __init__(self, entities: list[dict]) -> None:
        self._entities = entities

    def entities(self) -> list[dict]:
        return [dict(entity) for entity in self._entities]

    def _resolve_link_candidates(self, key: str) -> list[str]:
        name = key.lower().replace("_", " ").strip()
        out: list[str] = []
        for entity in self._entities:
            if entity.get("id") and entity["id"] == key:
                out.append(entity["path"])
                continue
            if entity["name"].lower().replace("_", " ").strip() == name:
                out.append(entity["path"])
                continue
            if Path(entity["path"]).stem.lower().replace("_", " ").strip() == name:
                out.append(entity["path"])
        return out


def _entity(
    path: str,
    name: str,
    *,
    entity_id: str = "",
    content: str = "",
    relaciones: tuple = (),
    forward_links: tuple = (),
    backlinks: tuple = (),
) -> dict:
    return {
        "path": path,
        "name": name,
        "id": entity_id,
        "content": content,
        "relaciones": list(relaciones),
        "forward_links": list(forward_links),
        "backlinks": list(backlinks),
    }


def _world(tmp_path: Path) -> Path:
    world = tmp_path / "mundos" / "mundo"
    world.mkdir(parents=True)
    return world


def _contradiction() -> str:
    return json.dumps(
        {
            "contradictions": [
                {
                    "target_canonical_id": "B",
                    "conflict_type": "date",
                    "quote_source": "nació en el año 120",
                    "quote_target": "nació en el año 145",
                    "confidence": 0.9,
                }
            ]
        }
    )


def _pair() -> list[dict]:
    return [
        _entity(
            "lore/alar.md",
            "Alar",
            entity_id="A",
            content="El rey Alar nació en el año 120.",
            relaciones=("B",),
        ),
        _entity(
            "lore/vesta.md",
            "Vesta",
            entity_id="B",
            content="Alar nació en el año 145.",
        ),
    ]


def _sweep(tmp_path: Path, entities: list[dict], runner, *, batch_size: int = 3):
    return sweep_conflicts_batch(
        mundo="mundo",
        mundos_dir=tmp_path / "mundos",
        index=FakeIndex(entities),
        runner=runner,
        batch_size=batch_size,
    )


def test_clamp_batch_size_bounds_and_defaults() -> None:
    assert clamp_batch_size(None) == 3
    assert clamp_batch_size(True) == 3
    assert clamp_batch_size(0) == 1
    assert clamp_batch_size(99) == 5
    assert clamp_batch_size(2) == 2


def test_empty_world_is_done(tmp_path: Path) -> None:
    _world(tmp_path)

    result = _sweep(tmp_path, [], lambda _p, _s: _contradiction())

    assert result.status == "done"
    assert result.swept == 0


def test_a_verified_contradiction_becomes_a_proposal(tmp_path: Path) -> None:
    world = _world(tmp_path)

    result = _sweep(tmp_path, _pair(), lambda _p, _s: _contradiction())

    assert result.status == "swept"
    assert result.created == 1
    records = load_records(world)
    record = records["semantic:A:B:date"]
    assert record.state == "proposed"
    assert record.quote_a == "nació en el año 120"
    assert record.quote_b == "nació en el año 145"
    assert record.path == "lore/alar.md"


def test_provider_outage_marks_nothing_swept(tmp_path: Path) -> None:
    world = _world(tmp_path)

    def runner(_prompt: str, _session: str) -> str:
        raise RuntimeError("provider down")

    first = _sweep(tmp_path, _pair(), runner)
    second = _sweep(tmp_path, _pair(), lambda _p, _s: _contradiction())

    assert first.status == "unavailable"
    assert first.swept == 0
    assert second.status == "swept"
    assert second.swept == 2
    assert len(load_records(world)) == 1


def test_an_unchanged_ficha_is_not_reviewed_twice(tmp_path: Path) -> None:
    _world(tmp_path)
    _sweep(tmp_path, _pair(), lambda _p, _s: _contradiction())

    second = _sweep(tmp_path, _pair(), lambda _p, _s: _contradiction())

    assert second.status == "done"
    assert second.swept == 0


def test_changed_text_makes_the_ficha_reviewable_again(tmp_path: Path) -> None:
    _world(tmp_path)
    _sweep(tmp_path, _pair(), lambda _p, _s: _contradiction())
    entities = _pair()
    entities[0]["content"] += " Reinó durante treinta años."

    second = _sweep(tmp_path, entities, lambda _p, _s: _contradiction())

    assert second.status == "swept"
    assert "lore/alar.md" in second.paths


def test_a_ficha_without_related_targets_is_marked_without_a_call(
    tmp_path: Path,
) -> None:
    _world(tmp_path)
    calls: list[str] = []

    def runner(prompt: str, _session: str) -> str:
        calls.append(prompt)
        return "{}"

    result = _sweep(
        tmp_path, [_entity("lore/sola.md", "Sola", entity_id="S")], runner
    )

    assert result.status == "swept"
    assert result.swept == 1
    assert calls == []


def test_an_already_recorded_pair_is_not_proposed_again(tmp_path: Path) -> None:
    world = _world(tmp_path)
    record_proposal(
        world,
        conflict_id="semantic:A:B:date",
        source_a="A",
        source_b="B",
        path="lore/alar.md",
        name="Alar",
        quote_a="nació en el año 120",
        quote_b="nació en el año 145",
        conflict_type="date",
        pair_left="A",
        pair_right="B",
    )

    result = _sweep(tmp_path, _pair(), lambda _p, _s: _contradiction())

    assert result.created == 0
    assert result.status == "swept"


def test_targets_come_from_relations_links_and_backlinks(tmp_path: Path) -> None:
    entities = [
        _entity(
            "lore/a.md",
            "Ala",
            entity_id="A",
            content="El rey Alar nació en el año 120.",
            forward_links=("Beta",),
            backlinks=("lore/gamma.md",),
        ),
        _entity("lore/beta.md", "Beta", entity_id="B", content="Alar nació en el año 145."),
        _entity("lore/gamma.md", "Gamma", entity_id="C", content="Alar nació en el año 145."),
        _entity("lore/delta.md", "Delta", entity_id="D", content="Sin relación."),
    ]
    prompts: list[str] = []

    def runner(prompt: str, _session: str) -> str:
        prompts.append(prompt)
        return json.dumps({"contradictions": []})

    _sweep(tmp_path, entities, runner, batch_size=1)

    assert len(prompts) == 1
    payload = json.loads(prompts[0])
    assert {target["canonical_id"] for target in payload["targets"]} == {"B", "C"}
    assert payload["source"]["canonical_id"] == "A"


def test_batch_size_limits_the_fichas_reviewed(tmp_path: Path) -> None:
    entities = [
        _entity(f"lore/f{i}.md", f"F{i}", entity_id=f"F{i}", content="Texto largo.")
        for i in range(4)
    ]
    for entity in entities:
        entity["relaciones"] = ["F0"] if entity["id"] != "F0" else ["F1"]
    prompts: list[str] = []

    def runner(prompt: str, _session: str) -> str:
        prompts.append(prompt)
        return json.dumps({"contradictions": []})

    _sweep(tmp_path, entities, runner, batch_size=2)

    assert len(prompts) == 2


def test_swept_state_records_the_body_digest(tmp_path: Path) -> None:
    world = _world(tmp_path)
    _sweep(tmp_path, _pair(), lambda _p, _s: _contradiction())

    state = json.loads((world / ".conflicts" / "swept.json").read_text(encoding="utf-8"))

    assert state["swept"]["lore/alar.md"] == body_digest("El rey Alar nació en el año 120.")
