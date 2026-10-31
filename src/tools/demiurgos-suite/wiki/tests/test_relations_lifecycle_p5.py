"""P5 — relation-health report for one saved ficha."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
for _path in (str(_HERE.parent), str(_HERE.parents[2])):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import api_server
from import_relations import RelationTarget, ficha_quality
from test_api_server import client, _principal  # noqa: F401


def _targets() -> list[RelationTarget]:
    return [RelationTarget("lore::beta", "Beta", "lore/beta.md")]


def test_a_connected_ficha_is_healthy() -> None:
    assert ficha_quality(
        body="Alpha served Beta.",
        relaciones=["lore::beta"],
        graph=True,
        source_id="lore::alpha",
        source_path="lore/alpha.md",
        targets=_targets(),
    ) == []


def test_a_mention_without_relation_is_a_false_orphan() -> None:
    assert ficha_quality(
        body="Alpha served Beta.",
        relaciones=[],
        graph=True,
        source_id="lore::alpha",
        source_path="lore/alpha.md",
        targets=_targets(),
    ) == ["false-orphan"]


def test_no_mention_at_all_is_standalone() -> None:
    assert ficha_quality(
        body="Nothing connects here.",
        relaciones=[],
        graph=True,
        source_id="lore::alpha",
        source_path="lore/alpha.md",
        targets=_targets(),
    ) == ["standalone"]


def test_a_non_entity_is_reported_as_such() -> None:
    assert ficha_quality(
        body="Alpha served Beta.",
        relaciones=["lore::beta"],
        graph=False,
        source_id="lore::alpha",
        source_path="lore/alpha.md",
        targets=_targets(),
    ) == ["non-entity"]


def test_folder_membership_alone_does_not_count_as_a_mention() -> None:
    targets = [
        RelationTarget(
            "lore::regions::regions", "Regions", "lore/regions/regions.md"
        )
    ]
    assert ficha_quality(
        body="A region.",
        relaciones=[],
        graph=True,
        source_id="lore::regions::alpha",
        source_path="lore/regions/alpha.md",
        targets=targets,
    ) == ["standalone"]


def _world():
    return api_server.MUNDOS_DIR / "test_mundo"


def _add(world, rel: str, fm: str, body: str) -> None:
    path = world / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm}---\n{body}", encoding="utf-8")
    api_server._graph_indices.clear()


def test_endpoint_reports_a_standalone_ficha(client, monkeypatch):
    _principal(monkeypatch)
    _add(_world(), "lore/lonely.md", "type: personaje\nid: lore::lonely\ntitle: Lonely\n", "Nothing.\n")

    response = client.get("/api/test_mundo/relations/quality?path=lore/lonely.md")

    assert response.status_code == 200, response.text
    assert response.json() == {"path": "lore/lonely.md", "tags": ["standalone"]}


def test_endpoint_reports_a_false_orphan(client, monkeypatch):
    _principal(monkeypatch)
    world = _world()
    _add(world, "lore/beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    _add(world, "lore/alpha.md", "type: personaje\nid: lore::alpha\ntitle: Alpha\n", "Alpha served Beta.\n")

    response = client.get("/api/test_mundo/relations/quality?path=lore/alpha.md")

    assert response.json()["tags"] == ["false-orphan"]


def test_endpoint_reports_a_connected_ficha_as_healthy(client, monkeypatch):
    _principal(monkeypatch)
    world = _world()
    _add(world, "lore/beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    _add(
        world,
        "lore/alpha.md",
        "type: personaje\nid: lore::alpha\ntitle: Alpha\nrelaciones:\n  - lore::beta\n",
        "Alpha served Beta.\n",
    )

    response = client.get("/api/test_mundo/relations/quality?path=lore/alpha.md")

    assert response.json()["tags"] == []


def test_endpoint_reports_a_non_entity(client, monkeypatch):
    _principal(monkeypatch)
    _add(
        _world(),
        "lore/glossary.md",
        "type: concepto\nid: lore::glossary\ntitle: Glossary\ngraph: false\n",
        "A glossary.\n",
    )

    response = client.get("/api/test_mundo/relations/quality?path=lore/glossary.md")

    assert response.json()["tags"] == ["non-entity"]


def test_endpoint_rejects_an_unknown_path(client, monkeypatch):
    _principal(monkeypatch)

    response = client.get("/api/test_mundo/relations/quality?path=lore/nope.md")

    assert response.status_code == 404
