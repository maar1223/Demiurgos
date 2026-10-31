"""Unit tests for deterministic sweep candidate detection (P3)."""

from __future__ import annotations

from pathlib import Path

from relation_candidates import body_digest, scan_candidates
from relation_state import SweepState


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


def _scan(tmp_path: Path, entities: list[dict], *, state=None, rejected=None):
    return scan_candidates(
        mundo="world",
        mundos_dir=tmp_path / "mundos",
        index=FakeIndex(entities),
        state=state if state is not None else SweepState(),
        rejected=rejected if rejected is not None else set(),
    )


def test_a_ficha_that_mentions_another_is_a_candidate(tmp_path: Path) -> None:
    entities = [
        _entity("lore/alpha.md", "lore::alpha", "Alpha", "Alpha served Beta."),
        _entity("lore/beta.md", "lore::beta", "Beta", "Beta."),
    ]

    candidates = _scan(tmp_path, entities)

    assert [candidate.path for candidate in candidates] == ["lore/alpha.md"]
    assert candidates[0].mentions == ("lore::beta",)
    assert candidates[0].missing == ("lore::beta",)


def test_a_declared_relation_is_not_missing_but_still_reviewable(tmp_path: Path) -> None:
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

    candidates = _scan(tmp_path, entities)

    assert len(candidates) == 1
    assert candidates[0].mentions == ("lore::beta",)
    assert candidates[0].missing == ()


def test_a_ficha_without_mentions_is_not_a_candidate(tmp_path: Path) -> None:
    entities = [
        _entity("lore/alpha.md", "lore::alpha", "Alpha", "Nothing connects here."),
        _entity("lore/beta.md", "lore::beta", "Beta", "Beta."),
    ]

    assert _scan(tmp_path, entities) == []


def test_muted_ficha_is_excluded(tmp_path: Path) -> None:
    entities = [
        _entity("lore/alpha.md", "lore::alpha", "Alpha", "Alpha served Beta."),
        _entity("lore/beta.md", "lore::beta", "Beta", "Beta."),
    ]

    candidates = _scan(tmp_path, entities, state=SweepState(muted={"lore/alpha.md"}))

    assert candidates == []


def test_swept_digest_hides_the_ficha_until_the_body_changes(tmp_path: Path) -> None:
    body = "Alpha served Beta."
    entities = [
        _entity("lore/alpha.md", "lore::alpha", "Alpha", body),
        _entity("lore/beta.md", "lore::beta", "Beta", "Beta."),
    ]
    swept = SweepState(swept={"lore/alpha.md": body_digest(body)})

    assert _scan(tmp_path, entities, state=swept) == []

    entities[0]["content"] = "Alpha served Beta in the north."
    assert [c.path for c in _scan(tmp_path, entities, state=swept)] == ["lore/alpha.md"]


def test_rejected_pair_is_not_a_mention(tmp_path: Path) -> None:
    entities = [
        _entity("lore/alpha.md", "lore::alpha", "Alpha", "Alpha served Beta."),
        _entity("lore/beta.md", "lore::beta", "Beta", "Beta."),
    ]

    candidates = _scan(
        tmp_path, entities, rejected={("lore::alpha", "lore::beta")}
    )

    assert candidates == []


def test_candidates_are_sorted_by_path(tmp_path: Path) -> None:
    entities = [
        _entity("lore/zeta.md", "lore::zeta", "Zeta", "Zeta mentions Alpha."),
        _entity("lore/alpha.md", "lore::alpha", "Alpha", "Alpha mentions Zeta."),
    ]

    candidates = _scan(tmp_path, entities)

    assert [candidate.path for candidate in candidates] == [
        "lore/alpha.md",
        "lore/zeta.md",
    ]
