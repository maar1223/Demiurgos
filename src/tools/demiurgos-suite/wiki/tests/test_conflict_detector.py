"""Unit tests for the deterministic conflict detector (S1).

The detector is pure and read-only: it takes the entity dicts the graph index
already caches and returns conflicts. Nothing here touches the filesystem or a
model.
"""

from __future__ import annotations

from pathlib import Path

from conflict_detector import Conflict, detect_conflicts


def _entity(
    path: str,
    name: str,
    *,
    entity_id: str = "",
    content: str = "",
    relaciones: tuple = (),
    status: str = "draft",
    canon_state: str | None = None,
    okf_issues: tuple = (),
) -> dict:
    return {
        "path": path,
        "name": name,
        "id": entity_id,
        "content": content,
        "relaciones": list(relaciones),
        "status": status,
        "canon_state": canon_state
        if canon_state is not None
        else ("propuesta" if status == "draft" else "canon"),
        "okf_issues": list(okf_issues),
        "type": "ficha",
    }


def _resolver(entities: list[dict]):
    """Mirror of EntityGraphIndex._resolve_link_candidates over fake entities."""

    def resolve(key: str) -> list[str]:
        name_lower = key.lower().replace("_", " ").strip()
        matches: list[str] = []
        for entity in entities:
            if entity.get("id") and entity["id"] == key:
                matches.append(entity["path"])
                continue
            if entity["name"].lower().replace("_", " ").strip() == name_lower:
                matches.append(entity["path"])
                continue
            if Path(entity["path"]).stem.lower().replace("_", " ").strip() == name_lower:
                matches.append(entity["path"])
        return matches

    return resolve


def _detect(entities: list[dict]) -> list[Conflict]:
    return detect_conflicts(entities, resolve_candidates=_resolver(entities))


def _codes(conflicts: list[Conflict]) -> list[str]:
    return [conflict.code for conflict in conflicts]


def test_clean_world_has_no_conflicts() -> None:
    entities = [
        _entity("lore/a.md", "Alfa", entity_id="A", status="stable"),
        _entity(
            "lore/b.md",
            "Beta",
            entity_id="B",
            status="stable",
            content="Aliada de [[Alfa]].",
            relaciones=("A",),
        ),
    ]

    assert _detect(entities) == []


def test_version_issue_is_an_error() -> None:
    entities = [
        _entity(
            "lore/a.md",
            "Alfa",
            entity_id="A",
            okf_issues=(
                {
                    "code": "version",
                    "message": "OKF version '2' is not supported (expected '1').",
                    "field": "okf_version",
                    "reference": None,
                },
            ),
        )
    ]

    conflicts = _detect(entities)

    assert _codes(conflicts) == ["version"]
    assert conflicts[0].severity == "error"
    assert conflicts[0].field == "okf_version"


def test_missing_minimum_is_a_warning() -> None:
    entities = [
        _entity(
            "lore/a.md",
            "Alfa",
            entity_id="A",
            okf_issues=(
                {
                    "code": "missing-minimum",
                    "message": "Entity of type 'sistema' is missing a required minimum.",
                    "field": "origen, fuente",
                    "reference": None,
                },
            ),
        )
    ]

    conflicts = _detect(entities)

    assert _codes(conflicts) == ["missing-minimum"]
    assert conflicts[0].severity == "warning"
    assert conflicts[0].field == "origen, fuente"


def test_body_wikilink_to_unknown_entity_is_unresolved() -> None:
    entities = [
        _entity("lore/a.md", "Alfa", entity_id="A", content="Amiga de [[Fantasma]]."),
    ]

    conflicts = _detect(entities)

    assert _codes(conflicts) == ["unresolved-reference"]
    assert conflicts[0].reference == "Fantasma"
    assert conflicts[0].severity == "error"


def test_body_wikilink_with_two_matches_is_ambiguous() -> None:
    entities = [
        _entity("lore/a.md", "Alfa", entity_id="A", content="Amiga de [[Gemela]]."),
        _entity("lore/gemela.md", "Gemela", entity_id="G1"),
        _entity("otra/gemela.md", "Gemela", entity_id="G2"),
    ]

    conflicts = _detect(entities)

    ambiguous = [c for c in conflicts if c.code == "ambiguous-reference"]
    assert len(ambiguous) == 1
    assert ambiguous[0].path == "lore/a.md"
    assert ambiguous[0].reference == "Gemela"


def test_duplicate_canonical_id_flags_every_ficha() -> None:
    entities = [
        _entity("lore/a.md", "Alfa", entity_id="A"),
        _entity("lore/alfa-copia.md", "Alfa copia", entity_id="A"),
    ]

    conflicts = _detect(entities)

    assert _codes(conflicts) == ["duplicate-id", "duplicate-id"]
    assert {c.path for c in conflicts} == {"lore/a.md", "lore/alfa-copia.md"}
    assert all(c.reference == "A" for c in conflicts)


def test_relation_entry_to_missing_target_is_dangling() -> None:
    entities = [
        _entity("lore/a.md", "Alfa", entity_id="A", relaciones=("NoExiste::Ficha",)),
    ]

    conflicts = _detect(entities)

    assert _codes(conflicts) == ["dangling-relation"]
    assert conflicts[0].reference == "NoExiste::Ficha"
    assert conflicts[0].severity == "error"


def test_relation_entry_to_itself_is_self_relation() -> None:
    entities = [
        _entity("lore/a.md", "Alfa", entity_id="A", relaciones=("A",)),
    ]

    conflicts = _detect(entities)

    assert _codes(conflicts) == ["self-relation"]
    assert conflicts[0].reference == "A"


def test_relation_wikilink_to_itself_is_self_relation() -> None:
    entities = [
        _entity("lore/a.md", "Alfa", entity_id="A", relaciones=("[[Alfa]]",)),
    ]

    conflicts = _detect(entities)

    assert _codes(conflicts) == ["self-relation"]


def test_canon_state_mismatch_is_a_warning() -> None:
    entities = [
        _entity("lore/a.md", "Alfa", entity_id="A", status="draft", canon_state="canon"),
        _entity(
            "lore/b.md",
            "Beta",
            entity_id="B",
            status="stable",
            canon_state="propuesta",
        ),
    ]

    conflicts = _detect(entities)

    assert _codes(conflicts) == ["canon-state-mismatch", "canon-state-mismatch"]
    assert all(c.severity == "warning" for c in conflicts)


def test_other_canon_states_are_not_mismatches() -> None:
    entities = [
        _entity("lore/a.md", "Alfa", entity_id="A", status="draft", canon_state="leyenda"),
        _entity("lore/b.md", "Beta", entity_id="B", status="stable", canon_state="creencia"),
    ]

    assert _detect(entities) == []


def test_same_reference_in_body_and_relaciones_is_reported_once() -> None:
    entities = [
        _entity(
            "lore/a.md",
            "Alfa",
            entity_id="A",
            content="Amiga de [[Fantasma]].",
            relaciones=("[[Fantasma]]",),
        ),
    ]

    conflicts = _detect(entities)

    assert len([c for c in conflicts if c.reference == "Fantasma"]) == 1


def test_errors_come_before_warnings_and_order_is_stable() -> None:
    entities = [
        _entity(
            "lore/a.md",
            "Alfa",
            entity_id="A",
            status="draft",
            canon_state="canon",
            content="Amiga de [[Fantasma]].",
        ),
        _entity("lore/b.md", "Beta", entity_id="B", relaciones=("NoExiste",)),
    ]

    conflicts = _detect(entities)

    assert [c.severity for c in conflicts] == ["error", "error", "warning"]
    assert [c.path for c in conflicts] == ["lore/a.md", "lore/b.md", "lore/a.md"]
