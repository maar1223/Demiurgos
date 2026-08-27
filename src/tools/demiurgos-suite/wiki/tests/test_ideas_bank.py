"""tests/test_ideas_bank.py — Unit tests for wiki.ideas_bank.IdeasBank.

Covers the OKF idea model (R-IB-01), global storage location (R-IB-02),
CRUD + list filters (R-IB-03) and the materialization link (R-CG-04).
Lenient frontmatter parse only — never a world-graph OKF validation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _p in (str(_WIKI),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ideas_bank import (  # noqa: E402
    IDEA_TYPES,
    Idea,
    IdeaConflict,
    IdeaNotFound,
    IdeasBank,
    InvalidIdea,
)


@pytest.fixture()
def bank(tmp_path: Path) -> IdeasBank:
    """Hermetic bank rooted at tmp_path/ideas (mundos sibling under tmp_path)."""
    return IdeasBank(ideas_root=tmp_path / "ideas", mundos_root=tmp_path / "mundos")


def _create(bank: IdeasBank, slug: str = "arquero-ciego", type: str = "personaje",
            body: str = "Un arquero que perdió la vista.", source: str = "manual",
            tags: list[str] | None = None) -> Idea:
    return bank.create(slug=slug, type=type, body=body, tags=tags, source=source)


def test_default_ideas_root_points_at_project_ideas(monkeypatch, tmp_path):
    """Regression: the default ``ideas_root`` MUST be ``<project>/ideas``.

    Production builds ``IdeasBank()`` with no explicit ``ideas_root`` (via
    ``create_ideas_bank_router``). ``_project_root()`` returns the repo root,
    so a default of ``<project>`` made ``list()`` scan the repo root — only
    finding *.md docs with no idea frontmatter — and the Taller de Ideas
    appeared permanently empty even after captures were saved. The default must
    carry the ``/ideas`` suffix.
    """
    import ideas_bank as module

    fake_root = tmp_path / "repo"
    monkeypatch.setattr(module, "_project_root", lambda: fake_root, raising=False)
    bank = IdeasBank()
    assert bank._ideas_root == fake_root / "ideas"
    assert bank._mundos_root == fake_root / "mundos"


def test_default_ideas_root_lists_saved_idea(monkeypatch, tmp_path):
    """Regression (integration-shaped): an idea written into ``<project>/ideas``
    is returned by ``bank.list()`` when the bank uses the default root."""
    import ideas_bank as module

    fake_root = tmp_path / "repo"
    monkeypatch.setattr(module, "_project_root", lambda: fake_root, raising=False)

    bank = IdeasBank()
    bank.create(slug="desde-telegram", type="concepto",
                body="Una idea guardada desde Telegram.", source="telegram")
    ideas = bank.list()
    assert any(i.slug == "desde-telegram" for i in ideas)


# ---------------------------------------------------------------------------
# R-IB-01 — well-formed idea file
# ---------------------------------------------------------------------------

def test_create_writes_well_formed_file(bank: IdeasBank, tmp_path: Path) -> None:
    idea = _create(bank)
    path = tmp_path / "ideas" / "arquero-ciego.md"
    assert path.is_file(), "idea must be persisted to ideas/{slug}.md"
    content = path.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    for field in ("id:", "slug:", "timestamp:", "source:", "type:", "tags:",
                  "status:", "used_in:", "based_on:"):
        assert field in content, f"frontmatter must carry {field}"
    assert "Un arquero que perdió la vista." in content
    # Body is free-text AFTER the frontmatter, never a frontmatter field.
    frontmatter = content.split("---\n")[1]
    assert "body:" not in frontmatter, "body must not be a frontmatter field"
    assert content.rstrip().endswith("Un arquero que perdió la vista.")
    assert idea.slug == "arquero-ciego"
    assert idea.source == "manual"
    assert idea.type == "personaje"
    assert idea.status == "fresh"
    assert idea.used_in == []
    assert idea.based_on is None


def test_create_accepts_all_taxonomy_types(bank: IdeasBank) -> None:
    for i, type in enumerate(IDEA_TYPES):
        idea = _create(bank, slug=f"idea-{i}", type=type)
        assert idea.type == type


def test_create_rejects_unknown_type(bank: IdeasBank) -> None:
    with pytest.raises(InvalidIdea):
        _create(bank, slug="mala", type="idea_loose")


def test_create_rejects_unknown_source(bank: IdeasBank) -> None:
    with pytest.raises(InvalidIdea):
        _create(bank, slug="mala", type="personaje", source="carrier_pigeon")


def test_create_rejects_duplicate_slug(bank: IdeasBank) -> None:
    _create(bank, slug="dupe")
    with pytest.raises(IdeaConflict):
        _create(bank, slug="dupe")


def test_create_rejects_traversal_slug(bank: IdeasBank) -> None:
    with pytest.raises(InvalidIdea):
        _create(bank, slug="../../etc/passwd")


# ---------------------------------------------------------------------------
# R-IB-03 — list with filters
# ---------------------------------------------------------------------------

def test_list_with_type_filter(bank: IdeasBank) -> None:
    _create(bank, slug="a", type="personaje")
    _create(bank, slug="b", type="personaje")
    _create(bank, slug="c", type="trama")
    _create(bank, slug="d", type="concepto")
    personajes = bank.list(type="personaje")
    assert [i.slug for i in personajes] == ["a", "b"]
    assert len(bank.list()) == 4


def test_list_with_status_and_source_filters(bank: IdeasBank) -> None:
    _create(bank, slug="a", source="telegram")
    _create(bank, slug="b", source="manual")
    _create(bank, slug="c", source="assistant")
    assert [i.slug for i in bank.list(source="telegram")] == ["a"]
    assert [i.slug for i in bank.list(source="manual")] == ["b"]
    assert [i.slug for i in bank.list(status="fresh")] == ["a", "b", "c"]
    assert bank.list(status="used") == []


def test_list_empty_when_root_missing(tmp_path: Path) -> None:
    bank = IdeasBank(ideas_root=tmp_path / "no-such-dir")
    assert bank.list() == []


# ---------------------------------------------------------------------------
# R-IB-03 — read / update
# ---------------------------------------------------------------------------

def test_read_returns_idea(bank: IdeasBank) -> None:
    _create(bank, slug="leer", body="Cuerpo.")
    idea = bank.read("leer")
    assert idea.slug == "leer"
    assert idea.body == "Cuerpo."


def test_read_missing_raises(bank: IdeasBank) -> None:
    with pytest.raises(IdeaNotFound):
        bank.read("no-existe")


def test_update_type_correction(bank: IdeasBank) -> None:
    _create(bank, slug="corregir", type="sin_clasificar")
    updated = bank.update("corregir", {"type": "trama"})
    assert updated.type == "trama"
    assert bank.read("corregir").type == "trama"


def test_update_rejects_bad_type(bank: IdeasBank) -> None:
    _create(bank, slug="corregir", type="personaje")
    with pytest.raises(InvalidIdea):
        bank.update("corregir", {"type": "nope"})


def test_update_rejects_unknown_field(bank: IdeasBank) -> None:
    _create(bank, slug="corregir", type="personaje")
    with pytest.raises(InvalidIdea):
        bank.update("corregir", {"telefono": "555"})


def test_update_missing_raises(bank: IdeasBank) -> None:
    with pytest.raises(IdeaNotFound):
        bank.update("no-existe", {"type": "trama"})


# ---------------------------------------------------------------------------
# R-CG-04 — materialization link
# ---------------------------------------------------------------------------

def test_materialize_appends_used_in_and_sets_used(bank: IdeasBank) -> None:
    _create(bank, slug="arquero-ciego", type="personaje")
    result = bank.materialize("arquero-ciego", "vibrantes")
    assert result["ok"] is True
    assert result["used_in"] == ["vibrantes"]
    idea = bank.read("arquero-ciego")
    assert idea.used_in == ["vibrantes"]
    assert idea.status == "used"


def test_materialize_is_deduplicating(bank: IdeasBank) -> None:
    _create(bank, slug="duplicado", type="personaje")
    bank.materialize("duplicado", "vibrantes")
    result = bank.materialize("duplicado", "vibrantes")
    assert result["used_in"] == ["vibrantes"]
    assert bank.read("duplicado").used_in == ["vibrantes"]


def test_materialize_records_based_on_on_canon_ficha(bank: IdeasBank, tmp_path: Path) -> None:
    _create(bank, slug="arquero-ciego", type="personaje")
    ficha = tmp_path / "mundos" / "vibrantes" / "lore" / "El_Arquero.md"
    ficha.parent.mkdir(parents=True)
    ficha.write_text(
        "---\ntype: personaje\ntitle: El Arquero\n---\n# El Arquero\n",
        encoding="utf-8",
    )
    result = bank.materialize("arquero-ciego", "vibrantes", canon_rel="lore/El_Arquero.md")
    assert result["canon_path"] == str(ficha)
    content = ficha.read_text(encoding="utf-8")
    assert "based_on: ideas/arquero-ciego" in content


def test_materialize_missing_idea_raises(bank: IdeasBank) -> None:
    with pytest.raises(IdeaNotFound):
        bank.materialize("no-existe", "vibrantes")


# ---------------------------------------------------------------------------
# R-IB-02 — global storage location (structural canon safety)
# ---------------------------------------------------------------------------

def test_ideas_never_under_mundos(bank: IdeasBank, tmp_path: Path) -> None:
    _create(bank, slug="arquero-ciego")
    path = tmp_path / "ideas" / "arquero-ciego.md"
    assert path.is_file()
    # The bank root is a sibling of mundos/, never inside it.
    assert tmp_path / "ideas" != tmp_path / "mundos" / "ideas"
    assert not (tmp_path / "mundos" / "ideas").exists()


# ---------------------------------------------------------------------------
# R-IB-03 extension — delete
# ---------------------------------------------------------------------------

def test_delete_removes_file(bank: IdeasBank) -> None:
    _create(bank, slug="borrar", type="concepto")
    bank.delete("borrar")
    with pytest.raises(IdeaNotFound):
        bank.read("borrar")


def test_delete_missing_raises(bank: IdeasBank) -> None:
    with pytest.raises(IdeaNotFound):
        bank.delete("no-existe")