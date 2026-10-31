"""Unit tests for the P1 deterministic relation service."""

from __future__ import annotations

from pathlib import Path

from relation_service import build_relation_plan


class FakeIndex:
    """Minimal ``EntityGraphIndex`` seam: only ``entities()`` is used."""

    def __init__(self, entities: list[dict]) -> None:
        self._entities = entities

    def entities(self) -> list[dict]:
        return [dict(entity) for entity in self._entities]


def _write(path: Path, frontmatter: str, body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")


def _entity(path: str, canonical_id: str, name: str, body: str = "") -> dict:
    return {"path": path, "id": canonical_id, "name": name, "content": body}


def test_forward_pass_links_a_body_mention(tmp_path: Path) -> None:
    world = tmp_path / "mundos" / "world"
    _write(
        world / "lore" / "alpha.md",
        "type: personaje\nid: lore::alpha\ntitle: Alpha\n",
        "Alpha served Beta in the northern war.",
    )
    index = FakeIndex([_entity("lore/beta.md", "lore::beta", "Beta")])

    plan = build_relation_plan(
        mundo="world",
        changed_paths=["lore/alpha.md"],
        mundos_dir=tmp_path / "mundos",
        index=index,
    )

    assert plan.relations == {"lore/alpha.md": ("lore::beta",)}


def test_reverse_pass_links_existing_fichas_that_name_the_new_one(tmp_path: Path) -> None:
    world = tmp_path / "mundos" / "world"
    _write(
        world / "lore" / "gamma.md",
        "type: personaje\nid: lore::gamma\ntitle: Gamma\n",
        "Gamma is new.",
    )
    index = FakeIndex(
        [_entity("lore/delta.md", "lore::delta", "Delta", "Delta mentions Gamma.")]
    )

    plan = build_relation_plan(
        mundo="world",
        changed_paths=["lore/gamma.md"],
        mundos_dir=tmp_path / "mundos",
        index=index,
    )

    assert plan.relations["lore/delta.md"] == ("lore::gamma",)


def test_folder_index_and_member_link_each_other(tmp_path: Path) -> None:
    world = tmp_path / "mundos" / "world"
    _write(
        world / "lore" / "regions" / "alpha.md",
        "type: region\nid: lore::regions::alpha\ntitle: Alpha\n",
        "A region.",
    )
    index = FakeIndex(
        [
            _entity(
                "lore/regions/regions.md",
                "lore::regions::regions",
                "Regions",
                "Index of regions.",
            )
        ]
    )

    plan = build_relation_plan(
        mundo="world",
        changed_paths=["lore/regions/alpha.md"],
        mundos_dir=tmp_path / "mundos",
        index=index,
    )

    assert plan.relations["lore/regions/alpha.md"] == ("lore::regions::regions",)
    assert plan.relations["lore/regions/regions.md"] == ("lore::regions::alpha",)


def test_non_entity_is_never_linked(tmp_path: Path) -> None:
    world = tmp_path / "mundos" / "world"
    _write(
        world / "lore" / "ghost.md",
        "type: concepto\nid: lore::ghost\ntitle: Ghost\ngraph: false\n",
        "Ghost.",
    )
    index = FakeIndex(
        [_entity("lore/delta.md", "lore::delta", "Delta", "Delta mentions Ghost.")]
    )

    plan = build_relation_plan(
        mundo="world",
        changed_paths=["lore/ghost.md"],
        mundos_dir=tmp_path / "mundos",
        index=index,
    )

    assert plan.relations == {}


def test_malformed_frontmatter_is_ignored(tmp_path: Path) -> None:
    world = tmp_path / "mundos" / "world"
    target = world / "lore" / "broken.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("---\ntype: [unclosed\n---\nBeta.\n", encoding="utf-8")
    index = FakeIndex([_entity("lore/beta.md", "lore::beta", "Beta")])

    plan = build_relation_plan(
        mundo="world",
        changed_paths=["lore/broken.md"],
        mundos_dir=tmp_path / "mundos",
        index=index,
    )

    assert plan.relations == {}


def test_body_without_mentions_produces_no_relation(tmp_path: Path) -> None:
    world = tmp_path / "mundos" / "world"
    _write(
        world / "lore" / "alpha.md",
        "type: personaje\nid: lore::alpha\ntitle: Alpha\n",
        "Nothing here connects to anyone.",
    )
    index = FakeIndex([_entity("lore/beta.md", "lore::beta", "Beta")])

    plan = build_relation_plan(
        mundo="world",
        changed_paths=["lore/alpha.md"],
        mundos_dir=tmp_path / "mundos",
        index=index,
    )

    assert plan.relations == {}


def test_plan_is_deterministic(tmp_path: Path) -> None:
    world = tmp_path / "mundos" / "world"
    _write(
        world / "lore" / "alpha.md",
        "type: personaje\nid: lore::alpha\ntitle: Alpha\n",
        "Alpha names Beta and Gamma.",
    )
    index = FakeIndex(
        [
            _entity("lore/beta.md", "lore::beta", "Beta"),
            _entity("lore/gamma.md", "lore::gamma", "Gamma"),
        ]
    )

    first = build_relation_plan(
        mundo="world",
        changed_paths=["lore/alpha.md"],
        mundos_dir=tmp_path / "mundos",
        index=index,
    )
    second = build_relation_plan(
        mundo="world",
        changed_paths=["lore/alpha.md"],
        mundos_dir=tmp_path / "mundos",
        index=index,
    )

    assert first == second
