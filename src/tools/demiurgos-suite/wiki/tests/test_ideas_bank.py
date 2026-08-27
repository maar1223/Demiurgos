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


# ---------------------------------------------------------------------------
# R-2 / R-3 — media_path first-class frontmatter field
# ---------------------------------------------------------------------------

def test_to_dict_includes_media_path(bank: IdeasBank) -> None:
    """``to_dict()`` MUST carry the ``media_path`` key (None when unset)."""
    idea = _create(bank)
    data = idea.to_dict()
    assert "media_path" in data
    assert data["media_path"] is None


def test_to_dict_media_path_value() -> None:
    idea = Idea(
        id="x", slug="y", timestamp="t", source="manual", type="personaje",
        body="b", media_path="media/y.png",
    )
    assert idea.to_dict()["media_path"] == "media/y.png"


def test_create_writes_media_path_frontmatter(bank: IdeasBank, tmp_path: Path) -> None:
    """``media_path`` is a first-class frontmatter field, not a ``_body`` marker."""
    _create(bank, slug="mp")
    content = (tmp_path / "ideas" / "mp.md").read_text(encoding="utf-8")
    assert "media_path:" in content
    frontmatter = content.split("---\n")[1]
    assert "media_path:" in frontmatter


def test_idea_from_file_reads_media_path(bank: IdeasBank, tmp_path: Path) -> None:
    """``_idea_from_file`` reads ``media_path`` from frontmatter."""
    _create(bank, slug="con-media")
    path = tmp_path / "ideas" / "con-media.md"
    content = path.read_text(encoding="utf-8")
    path.write_text(
        content.replace("media_path: null", "media_path: media/con-media.png"),
        encoding="utf-8",
    )
    idea = bank.read("con-media")
    assert idea.media_path == "media/con-media.png"


def test_update_accepts_media_path(bank: IdeasBank) -> None:
    """``update`` accepts ``media_path`` and persists it through round-trip."""
    _create(bank, slug="act")
    updated = bank.update("act", {"media_path": "media/act.png"})
    assert updated.media_path == "media/act.png"
    assert bank.read("act").media_path == "media/act.png"


def test_old_idea_without_media_path_loads_none(bank: IdeasBank, tmp_path: Path) -> None:
    """Backward compat: a legacy idea without ``media_path`` loads with None (S-4.2)."""
    (tmp_path / "ideas").mkdir(parents=True)
    (tmp_path / "ideas" / "legacy.md").write_text(
        "---\nid: l1\nslug: legacy\ntimestamp: '2024-01-01'\nsource: manual\n"
        "type: concepto\ntags: []\nstatus: fresh\nused_in: []\nbased_on: null\n"
        "---\nCuerpo legacy\n",
        encoding="utf-8",
    )
    idea = bank.read("legacy")
    assert idea.media_path is None
    assert idea.body == "Cuerpo legacy"


# ---------------------------------------------------------------------------
# R-TITLE-01 — human-readable title (frontmatter field + UI concern)
# ---------------------------------------------------------------------------

def test_idea_has_title_field() -> None:
    """``Idea.title`` defaults to ``""`` and round-trips through the dataclass."""
    idea = Idea(id="x", slug="y", timestamp="t", source="manual", type="personaje",
                body="b")
    assert idea.title == ""
    titled = Idea(id="x", slug="y", timestamp="t", source="manual", type="personaje",
                  body="b", title="Prototipo de diosa")
    assert titled.title == "Prototipo de diosa"


def test_to_dict_includes_title() -> None:
    idea = Idea(id="x", slug="y", timestamp="t", source="manual", type="personaje",
                body="b", title="El Arquero")
    assert idea.to_dict()["title"] == "El Arquero"


def test_create_accepts_title(bank: IdeasBank, tmp_path: Path) -> None:
    """``create`` persists ``title`` as a first-class frontmatter field."""
    idea = bank.create(slug="titulada", type="personaje",
                       body="Un arquero.", title="El Arquero Ciego")
    assert idea.title == "El Arquero Ciego"
    content = (tmp_path / "ideas" / "titulada.md").read_text(encoding="utf-8")
    assert "title: El Arquero Ciego" in content
    assert bank.read("titulada").title == "El Arquero Ciego"


def test_create_without_title_defaults_empty(bank: IdeasBank) -> None:
    idea = bank.create(slug="sin-titulo", type="concepto", body="Una idea.")
    assert idea.title == ""


def test_create_rejects_non_string_title(bank: IdeasBank) -> None:
    with pytest.raises(InvalidIdea):
        bank.create(slug="mala", type="personaje", body="x", title=42)


def test_idea_from_file_reads_title(bank: IdeasBank, tmp_path: Path) -> None:
    _create(bank, slug="con-titulo")
    path = tmp_path / "ideas" / "con-titulo.md"
    content = path.read_text(encoding="utf-8")
    path.write_text(content.replace("title: ''", "title: Un Título"), encoding="utf-8")
    idea = bank.read("con-titulo")
    assert idea.title == "Un Título"


def test_update_accepts_title(bank: IdeasBank) -> None:
    """``update`` accepts ``title`` and persists it through round-trip."""
    _create(bank, slug="act-titulo")
    updated = bank.update("act-titulo", {"title": "El Nuevo Título"})
    assert updated.title == "El Nuevo Título"
    assert bank.read("act-titulo").title == "El Nuevo Título"


def test_update_rejects_non_string_title(bank: IdeasBank) -> None:
    _create(bank, slug="act-titulo")
    with pytest.raises(InvalidIdea):
        bank.update("act-titulo", {"title": 42})


def test_legacy_idea_without_title_loads_empty(bank: IdeasBank, tmp_path: Path) -> None:
    """Backward compat: a legacy idea without ``title`` loads as ``""``."""
    (tmp_path / "ideas").mkdir(parents=True)
    (tmp_path / "ideas" / "legacy.md").write_text(
        "---\nid: l1\nslug: legacy\ntimestamp: '2024-01-01'\nsource: manual\n"
        "type: concepto\ntags: []\nstatus: fresh\nused_in: []\nbased_on: null\n"
        "---\nCuerpo legacy\n",
        encoding="utf-8",
    )
    idea = bank.read("legacy")
    assert idea.title == ""


# ---------------------------------------------------------------------------
# FMT — structured markdown bodies (## Descripción / ## Detalles / ## Notas)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[5]

REFORMATTED_IDEAS: dict[str, dict] = {
    "2026-08-27-3fbf55b420ea": {"title": "", "media_path": None},
    "2026-08-27-48a17af9349f": {
        "title": "Vibrastal Oscuro criatura",
        "media_path": "media/2026-08-27-48a17af9349f.jpg",
    },
    "2026-08-27-91f2c681437a": {"title": "", "media_path": None},
    "2026-08-27-a6daf48fbbc3": {
        "title": "",
        "media_path": "media/2026-08-27-a6daf48fbbc3.jpg",
    },
}


def test_reformatted_repo_ideas_load_with_structure() -> None:
    """The reformatted ideas/ files keep loading: title + body + media_path.

    Integration-shaped: the repo's own Taller de Ideas bank must stay
    parseable after the markdown-structure reformat (``## Descripción`` first,
    optional ``## Detalles`` / ``## Notas``, image embed above the heading).
    Frontmatter fields (slug/id/title/media_path) are preserved exactly.
    """
    repo_bank = IdeasBank(ideas_root=_REPO_ROOT / "ideas",
                          mundos_root=_REPO_ROOT / "mundos")
    for slug, expected in REFORMATTED_IDEAS.items():
        idea = repo_bank.read(slug)
        assert idea.title == expected["title"]
        assert idea.media_path == expected["media_path"]
        if idea.media_path:
            # Image ideas keep the embed at the very top, then the heading.
            filename = Path(idea.media_path).name
            assert idea.body.startswith(f"![idea image](/api/ideas/media/{filename})")
            assert "## Descripción" in idea.body
            assert idea.body.index("![idea image]") < idea.body.index("## Descripción")
        else:
            assert idea.body.startswith("## Descripción"), f"{slug} body must be structured"


# ---------------------------------------------------------------------------
# R-1 / R-2 / R-3 / R-11 — file-level versioning (ideas-edit-versioning PR 1)
# ---------------------------------------------------------------------------

def test_to_dict_includes_version(bank: IdeasBank) -> None:
    """``to_dict()`` MUST carry ``version`` (R-1)."""
    idea = _create(bank)
    assert idea.to_dict()["version"] == 1


def test_create_emits_version_1(bank: IdeasBank, tmp_path: Path) -> None:
    """S-11.1 — ``create()`` writes ``version: 1`` in the new file's frontmatter."""
    _create(bank, slug="nueva")
    content = (tmp_path / "ideas" / "nueva.md").read_text(encoding="utf-8")
    frontmatter = content.split("---\n")[1]
    assert "version: 1" in frontmatter
    assert bank.read("nueva").version == 1


def test_idea_without_version_defaults_to_1(bank: IdeasBank, tmp_path: Path) -> None:
    """S-1.1 — a pre-versioning file without ``version`` reads as version 1.

    Non-numeric ``version`` values also default to 1 (lenient parse, no
    data migration — existing files keep working).
    """
    (tmp_path / "ideas").mkdir(parents=True)
    (tmp_path / "ideas" / "legacy.md").write_text(
        "---\nid: l1\nslug: legacy\ntimestamp: '2024-01-01'\nsource: manual\n"
        "type: concepto\ntags: []\nstatus: fresh\nused_in: []\nbased_on: null\n"
        "---\nCuerpo legacy\n",
        encoding="utf-8",
    )
    idea = bank.read("legacy")
    assert idea.version == 1
    (tmp_path / "ideas" / "rara.md").write_text(
        "---\nid: r1\nslug: rara\ntimestamp: '2024-01-01'\nsource: manual\n"
        "type: concepto\ntags: []\nstatus: fresh\nused_in: []\nbased_on: null\n"
        "version: alta\n---\nCuerpo\n",
        encoding="utf-8",
    )
    assert bank.read("rara").version == 1


def test_update_versioned_archives_v1_and_writes_v2(bank: IdeasBank, tmp_path: Path) -> None:
    """S-2.1 — a versioned edit archives the original as v1 and writes v2."""
    _create(bank, slug="editar", body="original")
    updated = bank.update_versioned("editar", {"body": "revisado"})
    assert updated.version == 2
    assert updated.body == "revisado"
    archive = tmp_path / "ideas" / "versions" / "editar-v1.md"
    assert archive.is_file()
    content = archive.read_text(encoding="utf-8")
    assert "version: 1" in content
    assert "original" in content
    current = bank.read("editar")
    assert current.version == 2
    assert current.body == "revisado"


def test_update_versioned_sequential_versions(bank: IdeasBank, tmp_path: Path) -> None:
    """S-2.2 — sequential versioned edits keep archiving: v3 → archive v3, new v4."""
    _create(bank, slug="secuencial", body="v1")
    bank.update_versioned("secuencial", {"body": "v2"})
    bank.update_versioned("secuencial", {"body": "v3"})
    updated = bank.update_versioned("secuencial", {"body": "v4"})
    assert updated.version == 4
    versions_dir = tmp_path / "ideas" / "versions"
    assert (versions_dir / "secuencial-v1.md").is_file()
    assert (versions_dir / "secuencial-v2.md").is_file()
    assert (versions_dir / "secuencial-v3.md").is_file()
    assert bank.read("secuencial").version == 4
    assert len(bank._versions_for("secuencial")) == 3


def test_next_version_is_max_plus_one(bank: IdeasBank) -> None:
    """S-2.3 — the next version is ``max(archived vN) + 1`` from disk,
    never an in-memory counter."""
    _create(bank, slug="determinista", body="v1")
    bank.update_versioned("determinista", {"body": "v2"})
    bank.update_versioned("determinista", {"body": "v3"})
    bank.update_versioned("determinista", {"body": "v4"})
    # archives v1,v2,v3 on disk → next version is 4
    assert bank._next_version("determinista") == 4
    assert bank._next_version("sin-archivos") == 1


def test_update_versioned_archive_survives_new_write_failure(
    bank: IdeasBank, monkeypatch, tmp_path: Path
) -> None:
    """S-2.4 — when the new-file write fails after the archive write, the
    archived version remains intact and recoverable."""
    _create(bank, slug="fallo", body="original")

    def failing_write(self, idea):
        raise OSError("disk full")

    monkeypatch.setattr(IdeasBank, "_write", failing_write)
    with pytest.raises(OSError):
        bank.update_versioned("fallo", {"body": "nuevo"})

    # The current file is unchanged...
    current = bank.read("fallo")
    assert current.body == "original"
    assert current.version == 1
    # ...and the archive is intact and a complete valid idea file.
    archive = tmp_path / "ideas" / "versions" / "fallo-v1.md"
    assert archive.is_file()
    archived = bank._idea_from_file(archive)
    assert archived is not None
    assert archived.body == "original"
    assert archived.version == 1


def test_update_versioned_invalid_partial_fails_closed(bank: IdeasBank, tmp_path: Path) -> None:
    """S-2.5 — an invalid partial fails without touching existing files:
    no archive is created and the current file is unchanged."""
    _create(bank, slug="cerrado", body="original")
    with pytest.raises(InvalidIdea):
        bank.update_versioned("cerrado", {"telefono": "555"})
    with pytest.raises(InvalidIdea):
        bank.update_versioned("cerrado", {"type": "nope"})
    assert not (tmp_path / "ideas" / "versions").exists()
    current = bank.read("cerrado")
    assert current.body == "original"
    assert current.version == 1


def test_update_versioned_concurrent_race_distinct_versions(
    bank: IdeasBank, monkeypatch
) -> None:
    """S-2.6 — two overlapping update_versioned calls end with distinct
    version numbers; each call derives ``max(archived vN) + 1`` from the
    filesystem at write time, never from an in-memory counter.

    The second (concurrent) call starts while the first is mid-flight, but
    its disk reads land after the first's write, so both produce distinct
    versions and the final state stays consistent with the archives.
    """
    _create(bank, slug="carrera", body="original")
    fired = {"once": False}
    orig_write = IdeasBank._write

    def interleaving_write(self, idea):
        if not fired["once"]:
            fired["once"] = True
            result = orig_write(self, idea)  # first call's write lands
            bank.update_versioned("carrera", {"body": "segundo"})  # second call
            return result
        return orig_write(self, idea)

    monkeypatch.setattr(IdeasBank, "_write", interleaving_write)
    first = bank.update_versioned("carrera", {"body": "primero"})

    assert fired["once"] is True
    # Both calls produced distinct versions (2 and 3), last write wins.
    second = bank.read("carrera")
    assert first.version == 2
    assert second.version == 3
    assert second.body == "segundo"
    # Both superseded versions archived, ascending.
    archives = bank._versions_for("carrera")
    assert [p.name for p in archives] == ["carrera-v1.md", "carrera-v2.md"]


def test_versions_for_ascending(bank: IdeasBank) -> None:
    """S-3.1 — archived versions are listed ascending by version number."""
    _create(bank, slug="historico", body="v1")
    bank.update_versioned("historico", {"body": "v2"})
    bank.update_versioned("historico", {"body": "v3"})
    bank.update_versioned("historico", {"body": "v4"})
    versions = bank._versions_for("historico")
    assert [p.name for p in versions] == [
        "historico-v1.md",
        "historico-v2.md",
        "historico-v3.md",
    ]


def test_versions_for_empty_when_no_archives(bank: IdeasBank) -> None:
    """S-3.2 — a slug without archives yields an empty list."""
    _create(bank, slug="solo-actual")
    assert bank._versions_for("solo-actual") == []
    assert bank._versions_for("nunca-existio") == []


def test_list_excludes_versions_subdir(bank: IdeasBank) -> None:
    """S-4.1 — archived files under ideas/versions/ never appear in list()
    (top-level glob naturally excludes the subdirectory)."""
    _create(bank, slug="visible", body="v1")
    _create(bank, slug="otra", body="x")
    bank.update_versioned("visible", {"body": "v2"})
    bank.update_versioned("visible", {"body": "v3"})
    slugs = [i.slug for i in bank.list()]
    assert slugs == ["otra", "visible"]
    assert all("versions" not in s for s in slugs)


def test_materialize_keeps_version_1_no_archive(bank: IdeasBank, tmp_path: Path) -> None:
    """S-5.1 — materialize() is bookkeeping: it uses update() (non-versioned),
    never creates archives and leaves version untouched."""
    _create(bank, slug="mat", type="personaje")
    result = bank.materialize("mat", "vibrantes")
    assert result["ok"] is True
    idea = bank.read("mat")
    assert idea.version == 1
    assert idea.status == "used"
    assert not (tmp_path / "ideas" / "versions").exists()


def test_archived_version_retains_media_path(bank: IdeasBank, tmp_path: Path) -> None:
    """S-9.1 — an archived version keeps the same media_path and its media
    resolves to the existing file."""
    _create(bank, slug="con-imagen", body="v1")
    bank.update("con-imagen", {"media_path": "media/con-imagen.png"})
    media = tmp_path / "ideas" / "media" / "con-imagen.png"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"\x89PNG fake")
    bank.update_versioned("con-imagen", {"body": "v2"})

    archive = tmp_path / "ideas" / "versions" / "con-imagen-v1.md"
    assert archive.is_file()
    content = archive.read_text(encoding="utf-8")
    assert "media_path: media/con-imagen.png" in content
    archived = bank._idea_from_file(archive)
    assert archived is not None
    assert archived.media_path == "media/con-imagen.png"
    resolved = (tmp_path / "ideas" / archived.media_path).resolve()
    assert resolved.is_file()


def test_update_preserves_version(bank: IdeasBank) -> None:
    """Non-versioned update() must keep the current version, never reset it
    to the dataclass default 1 (materialize()/REST PATCH rely on this)."""
    _create(bank, slug="preserva", body="v1")
    bank.update_versioned("preserva", {"body": "v2"})
    updated = bank.update("preserva", {"status": "used"})
    assert updated.version == 2
    assert bank.read("preserva").version == 2