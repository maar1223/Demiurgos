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


def test_index_keeps_every_member_beyond_the_textual_cap(tmp_path: Path) -> None:
    """A folder index is exact hierarchy: 20 members must yield 20 relations."""
    world = tmp_path / "mundos" / "world"
    _write(
        world / "lore" / "regions" / "m00.md",
        "type: region\nid: lore::regions::m00\ntitle: Member 0\n",
        "A member.",
    )
    entities = []
    for n in range(20):
        name = f"m{n:02d}"
        _write(
            world / "lore" / "regions" / f"{name}.md",
            f"type: region\nid: lore::regions::{name}\ntitle: Member {n}\n",
            "A member.",
        )
        entities.append(
            _entity(
                f"lore/regions/{name}.md", f"lore::regions::{name}", f"Member {n}"
            )
        )
    _write(
        world / "lore" / "regions" / "regions.md",
        "type: region\nid: lore::regions::regions\ntitle: Regions\n",
        "Index.",
    )
    entities.append(
        _entity("lore/regions/regions.md", "lore::regions::regions", "Regions")
    )

    plan = build_relation_plan(
        mundo="world",
        changed_paths=["lore/regions/m00.md"],
        mundos_dir=tmp_path / "mundos",
        index=FakeIndex(entities),
    )

    index_relations = plan.relations["lore/regions/regions.md"]
    assert len(index_relations) == 20
    assert plan.structural["lore/regions/regions.md"] == frozenset(index_relations)


def test_a_hub_ficha_keeps_the_textual_cap(tmp_path: Path) -> None:
    world = tmp_path / "mundos" / "world"
    body = " ".join(f"Target {n}." for n in range(20))
    _write(
        world / "lore" / "hub.md",
        "type: region\nid: lore::hub\ntitle: Hub\n",
        body,
    )
    entities = [
        _entity(f"lore/t{n:02d}.md", f"lore::t{n:02d}", f"Target {n}")
        for n in range(20)
    ]

    plan = build_relation_plan(
        mundo="world",
        changed_paths=["lore/hub.md"],
        mundos_dir=tmp_path / "mundos",
        index=FakeIndex(entities),
    )

    assert len(plan.relations["lore/hub.md"]) == 12
    assert "lore/hub.md" not in plan.structural


def test_ambiguous_name_is_not_linked(tmp_path: Path) -> None:
    """Two fichas sharing a title or stem: the body names one, not both."""
    world = tmp_path / "mundos" / "world"
    _write(
        world / "lore" / "page.md",
        "type: personaje\nid: lore::page\ntitle: Page\n",
        "Alpha appears here.",
    )
    index = FakeIndex(
        [
            _entity("lore/north/alpha.md", "lore::north::alpha", "Alpha"),
            _entity("lore/south/alpha.md", "lore::south::alpha", "Alpha"),
        ]
    )

    plan = build_relation_plan(
        mundo="world",
        changed_paths=["lore/page.md"],
        mundos_dir=tmp_path / "mundos",
        index=index,
    )

    assert plan.relations == {}


def test_rejected_forward_pair_is_not_proposed(tmp_path: Path) -> None:
    world = tmp_path / "mundos" / "world"
    _write(
        world / "lore" / "alpha.md",
        "type: personaje\nid: lore::alpha\ntitle: Alpha\n",
        "Alpha served Beta.",
    )
    index = FakeIndex([_entity("lore/beta.md", "lore::beta", "Beta")])

    plan = build_relation_plan(
        mundo="world",
        changed_paths=["lore/alpha.md"],
        mundos_dir=tmp_path / "mundos",
        index=index,
        rejected={("lore::alpha", "lore::beta")},
    )

    assert plan.relations == {}


def test_rejected_reverse_pair_is_not_proposed(tmp_path: Path) -> None:
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
        rejected={("lore::delta", "lore::gamma")},
    )

    assert plan.relations == {}


def test_rejection_beats_folder_membership(tmp_path: Path) -> None:
    world = tmp_path / "mundos" / "world"
    _write(
        world / "lore" / "regions" / "alpha.md",
        "type: region\nid: lore::regions::alpha\ntitle: Alpha\n",
        "A region.",
    )
    index = FakeIndex(
        [_entity("lore/regions/regions.md", "lore::regions::regions", "Regions")]
    )

    plan = build_relation_plan(
        mundo="world",
        changed_paths=["lore/regions/alpha.md"],
        mundos_dir=tmp_path / "mundos",
        index=index,
        rejected={("lore::regions::alpha", "lore::regions::regions")},
    )

    assert plan.relations.get("lore/regions/alpha.md") is None
    # The reciprocal pair was not rejected: the index still lists the member.
    assert plan.relations["lore/regions/regions.md"] == ("lore::regions::alpha",)
