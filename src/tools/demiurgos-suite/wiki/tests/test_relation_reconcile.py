"""Unit tests for the world-wide reconciliation plan (P4)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _path in (str(_HERE.parent), str(_HERE.parents[2])):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from relation_reconcile import build_global_plan, create_preimage_backup
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


def _plan(tmp_path: Path, entities: list[dict], *, state=None, rejected=None):
    return build_global_plan(
        mundo="world",
        mundos_dir=tmp_path / "mundos",
        index=FakeIndex(entities),
        state=state if state is not None else SweepState(),
        rejected=rejected if rejected is not None else set(),
    )


def test_adds_a_grounded_relation_that_is_missing(tmp_path: Path) -> None:
    entities = [
        _entity("lore/alpha.md", "lore::alpha", "Alpha", "Alpha served Beta."),
        _entity("lore/beta.md", "lore::beta", "Beta", "Beta."),
    ]

    plan = _plan(tmp_path, entities)

    assert len(plan.files) == 1
    assert plan.files[0].path == "lore/alpha.md"
    assert plan.files[0].add == ("lore::beta",)
    assert plan.files[0].remove == ()
    assert plan.additions == 1
    assert plan.removals == 0


def test_removes_a_declared_relation_the_text_does_not_back(tmp_path: Path) -> None:
    entities = [
        _entity(
            "lore/alpha.md",
            "lore::alpha",
            "Alpha",
            "Alpha mentions nobody.",
            relaciones=["lore::gamma"],
        ),
        _entity("lore/gamma.md", "lore::gamma", "Gamma", "Gamma."),
    ]

    plan = _plan(tmp_path, entities)

    assert len(plan.files) == 1
    removal = plan.files[0].remove[0]
    assert removal.key == "lore::gamma"
    assert removal.target_id == "lore::gamma"
    assert removal.reason == "ungrounded"


def test_a_grounded_declared_relation_is_kept(tmp_path: Path) -> None:
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

    assert _plan(tmp_path, entities).files == ()


def test_a_dangling_reference_is_removed_as_unresolved(tmp_path: Path) -> None:
    entities = [
        _entity(
            "lore/alpha.md",
            "lore::alpha",
            "Alpha",
            "Alpha mentions nobody.",
            relaciones=["Ghost"],
        )
    ]

    plan = _plan(tmp_path, entities)

    removal = plan.files[0].remove[0]
    assert removal.reason == "unresolved"
    assert removal.key == "Ghost"
    assert removal.target_id == ""
    assert plan.unresolved == 1


def test_a_rejected_pair_is_removed_and_not_added(tmp_path: Path) -> None:
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

    plan = _plan(
        tmp_path, entities, rejected={("lore::alpha", "lore::beta")}
    )

    assert plan.files[0].add == ()
    removal = plan.files[0].remove[0]
    assert removal.reason == "rejected"


def test_a_muted_ficha_is_skipped_entirely(tmp_path: Path) -> None:
    entities = [
        _entity(
            "lore/alpha.md",
            "lore::alpha",
            "Alpha",
            "Alpha served Beta.",
            relaciones=["Ghost"],
        ),
        _entity("lore/beta.md", "lore::beta", "Beta", "Beta."),
    ]

    plan = _plan(
        tmp_path, entities, state=SweepState(muted={"lore/alpha.md"})
    )

    assert plan.files == ()


def test_folder_membership_is_grounded_and_kept(tmp_path: Path) -> None:
    entities = [
        _entity(
            "lore/regions/alpha.md",
            "lore::regions::alpha",
            "Alpha",
            "A region.",
            relaciones=["lore::regions::regions"],
        ),
        _entity(
            "lore/regions/regions.md",
            "lore::regions::regions",
            "Regions",
            "Index.",
            relaciones=["lore::regions::alpha"],
        ),
    ]

    assert _plan(tmp_path, entities).files == ()


def test_repeated_runs_are_deterministic(tmp_path: Path) -> None:
    entities = [
        _entity("lore/zeta.md", "lore::zeta", "Zeta", "Zeta mentions Alpha."),
        _entity("lore/alpha.md", "lore::alpha", "Alpha", "Alpha mentions Zeta."),
    ]

    first = _plan(tmp_path, entities)
    second = _plan(tmp_path, entities)

    assert first == second
    assert [file_plan.path for file_plan in first.files] == [
        "lore/alpha.md",
        "lore/zeta.md",
    ]


def test_preimage_backup_copies_files_and_writes_a_manifest(tmp_path: Path) -> None:
    world = tmp_path / "world"
    (world / "lore").mkdir(parents=True)
    (world / "lore" / "alpha.md").write_text("alpha\n", encoding="utf-8")
    (world / "lore" / "beta.md").write_text("beta\n", encoding="utf-8")
    moment = datetime(2026, 10, 31, 22, 0, 0, tzinfo=timezone.utc)

    root, skipped = create_preimage_backup(
        world,
        ["lore/alpha.md", "lore/beta.md", "lore/missing.md"],
        counts={"additions": 2, "removals": 1},
        moment=moment,
    )

    assert skipped == ("lore/missing.md",)

    assert (root / "files" / "lore" / "alpha.md").read_text(encoding="utf-8") == "alpha\n"
    assert (root / "files" / "lore" / "beta.md").read_text(encoding="utf-8") == "beta\n"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"] == ["lore/alpha.md", "lore/beta.md"]
    assert manifest["counts"] == {"additions": 2, "removals": 1}
    assert root.parent.parent.name == ".relations"
