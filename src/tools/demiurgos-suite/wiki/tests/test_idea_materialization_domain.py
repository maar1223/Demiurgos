"""Tests: idea materialization domain helpers (tasks 1.4-1.7).

Table-driven coverage of ``idea_materialization_domain``: slug helpers, the
AD4 folder-convention probe + server-owned ficha skeleton, the AD6 grounding
candidates, and relation validation (R-IM-03). Tests are written alongside
the behavior (TDD is OFF for this project, testing-capabilities #506).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import pytest  # noqa: E402
import yaml  # noqa: E402

from idea_materialization_domain import (  # noqa: E402
    FolderConvention,
    build_ficha_skeleton,
    build_grounding_candidates,
    probe_folder_convention,
    resolve_file_slug,
    slugify_title,
    suggest_free_slug,
    validate_relations,
)
from idea_materialization_protocol import (  # noqa: E402
    MAX_CANDIDATE_PAYLOAD_CHARS,
    MAX_CANDIDATES,
    MAX_SLUG_LEN,
    Relation,
)

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_ficha(root: Path, rel: str, frontmatter: str) -> Path:
    """Write an OKF-ish ficha (frontmatter block + body) under *root*."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}---\n\n# Body\n", encoding="utf-8")
    return path


def _frontmatter(content: str) -> dict:
    """Parse the leading frontmatter block of a skeleton back into a dict."""
    assert content.startswith("---\n")
    block = content.split("---\n", 2)[1]
    return yaml.safe_load(block)


def _skeleton(
    world: Path,
    *,
    section: str = "lore",
    folder: str = "tema",
    slug: str = "idea-uno",
    idea_slug: str | None = None,
    title: str = "Idea Uno",
    body: str = "# Cuerpo\n",
    relations: tuple[Relation, ...] = (),
    convention: FolderConvention | None = None,
    image_rel: str | None = None,
) -> str:
    return build_ficha_skeleton(
        world_dir=world,
        section=section,
        folder=folder,
        slug=slug,
        idea_slug=idea_slug if idea_slug is not None else slug,
        title=title,
        body=body,
        relations=relations,
        convention=convention,
        image_rel=image_rel,
    )


class _FakeReader:
    """Ranked entity source mirroring ``_GuidedGraphReader``'s search/read seam."""

    def __init__(self, entities: list[dict]) -> None:
        self._entities = list(entities)

    def search(self, query: str) -> list[dict]:
        return [{"path": e["path"]} for e in self._entities]

    def read(self, path: str) -> dict | None:
        for entity in self._entities:
            if entity["path"] == path:
                return dict(entity)
        return None


def _entity(path: str, *, id: str = "", title: str = "", type: str = "concepto",
            description: str = "") -> dict:
    return {"path": path, "id": id, "title": title, "type": type, "description": description}


# ---------------------------------------------------------------------------
# slugify_title (task 1.4, AD5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("title, expected", [
    ("Daest cruza un Umbral inestable", "daest-cruza-un-umbral-inestable"),
    ("Árbol del Éxito", "arbol-del-exito"),
    ("Ñoño & Übel", "nono-ubel"),
    ("Stal 1: Director", "stal-1-director"),
    ("  Multiple   Spaces  ", "multiple-spaces"),
    ("Daest, el Director Ciego", "daest-el-director-ciego"),
    ("", ""),
    ("!!!", ""),
])
def test_slugify_title_transliterates_to_ascii(title: str, expected: str) -> None:
    assert slugify_title(title) == expected


def test_slugify_title_respects_max_slug_len() -> None:
    slug = slugify_title("Palabra " * 60)
    assert len(slug) <= MAX_SLUG_LEN
    assert not slug.endswith("-")
    assert _SLUG_RE.fullmatch(slug)


def test_slugify_title_truncates_single_token() -> None:
    slug = slugify_title("x" * (MAX_SLUG_LEN + 50))
    assert len(slug) == MAX_SLUG_LEN
    assert _SLUG_RE.fullmatch(slug)


# ---------------------------------------------------------------------------
# resolve_file_slug (WU-6, iteration 2 — the typed name is the filename)
# ---------------------------------------------------------------------------


def test_resolve_file_slug_derives_from_ficha_title() -> None:
    """FT-1: the caller resolves the title; the filename derives from it."""
    assert resolve_file_slug("Mi Título", "idea-slug", None) == "mi-titulo"


def test_resolve_file_slug_uses_idea_title_as_ficha_title() -> None:
    assert resolve_file_slug("Idea Title", "idea-slug", None) == "idea-title"


def test_resolve_file_slug_untitled_idea_falls_back_to_idea_slug() -> None:
    """An untitled idea (``title == slug``) keeps its internal slug as name."""
    telegram_id = "2026-08-28-524e8b9c9770"
    assert resolve_file_slug(telegram_id, telegram_id, None) == telegram_id


def test_resolve_file_slug_empty_title_falls_back_to_idea_slug() -> None:
    assert resolve_file_slug("", "2026-08-28-524e8b9c9770", None) == "2026-08-28-524e8b9c9770"


def test_resolve_file_slug_client_slug_overrides_default() -> None:
    assert resolve_file_slug("Mi Título", "idea-slug", "custom-name") == "custom-name"


def test_resolve_file_slug_client_slug_is_normalized() -> None:
    assert resolve_file_slug("Idea Title", "idea-slug", "Mi Nombre Raro!") == "mi-nombre-raro"


@pytest.mark.parametrize("client_slug", ["", "   ", "!!!"])
def test_resolve_file_slug_empty_or_empty_normalizing_client_slug_falls_back(client_slug: str) -> None:
    assert resolve_file_slug("Idea Title", "idea-slug", client_slug) == "idea-title"


def test_resolve_file_slug_client_slug_is_traversal_safe_by_normalization() -> None:
    """``slugify_title`` strips path separators; the result never escapes."""
    resolved = resolve_file_slug("Idea Title", "idea-slug", "../../etc/passwd")
    assert resolved == "etc-passwd"
    assert "/" not in resolved and ".." not in resolved


def test_resolve_file_slug_client_slug_is_length_bounded() -> None:
    resolved = resolve_file_slug("Idea Title", "idea-slug", "x" * (MAX_SLUG_LEN + 50))
    assert len(resolved) == MAX_SLUG_LEN
    assert _SLUG_RE.fullmatch(resolved)


def test_resolve_file_slug_derived_from_title_is_length_bounded() -> None:
    resolved = resolve_file_slug("Palabra " * 60, "idea-slug", None)
    assert len(resolved) <= MAX_SLUG_LEN
    assert _SLUG_RE.fullmatch(resolved)


# ---------------------------------------------------------------------------
# suggest_free_slug (task 1.4, AD5)
# ---------------------------------------------------------------------------


def test_suggest_free_slug_starts_at_minus_two(tmp_path: Path) -> None:
    target = tmp_path / "lore" / "tema" / "slug.md"
    assert suggest_free_slug(target) == tmp_path / "lore" / "tema" / "slug-2.md"


def test_suggest_free_slug_increments_past_existing_names(tmp_path: Path) -> None:
    target = tmp_path / "slug.md"
    target.write_text("x", encoding="utf-8")
    (tmp_path / "slug-2.md").write_text("x", encoding="utf-8")
    (tmp_path / "slug-3.md").write_text("x", encoding="utf-8")
    assert suggest_free_slug(target) == tmp_path / "slug-4.md"


def test_suggest_free_slug_preserves_extension(tmp_path: Path) -> None:
    target = tmp_path / "slug.md"
    (tmp_path / "slug-2.md").write_text("x", encoding="utf-8")
    assert suggest_free_slug(target).name == "slug-3.md"
    assert suggest_free_slug(target).suffix == ".md"


# ---------------------------------------------------------------------------
# probe_folder_convention (task 1.5, AD4)
# ---------------------------------------------------------------------------


def test_probe_personajes_convention_from_type(tmp_path: Path) -> None:
    _write_ficha(tmp_path, "personajes/Daest.md", "type: Personaje\ntitle: Daest\nstatus: stable\n")
    conv = probe_folder_convention(tmp_path, "personajes", "")
    assert conv.convention == "personajes"
    assert conv.type == "Personaje"
    assert conv.parent == ""
    assert conv.status == "stable"
    assert conv.source == "Daest"


def test_probe_personajes_convention_from_schema_version(tmp_path: Path) -> None:
    _write_ficha(tmp_path, "personajes/Anisa.md", "id: anisa\ntype: Persona\nschema_version: 1\n")
    conv = probe_folder_convention(tmp_path, "personajes", "")
    assert conv.convention == "personajes"
    assert conv.type == "Personaje"
    assert conv.status == "draft"


def test_probe_canonical_convention_from_qualified_id(tmp_path: Path) -> None:
    # No index ficha: the first sibling with a ``::`` id defines the convention.
    _write_ficha(
        tmp_path, "lore/politica/chaae.md",
        'id: "Política | Distribución Y Territorios::Chaae"\ntitle: Chaae\ntype: lugar\nstatus: stable\n',
    )
    conv = probe_folder_convention(tmp_path, "lore", "politica")
    assert conv.convention == "canonical"
    assert conv.parent == "Política | Distribución Y Territorios"
    assert conv.type == "lugar"
    assert conv.status == "stable"


def test_probe_canonical_single_convention_from_index(tmp_path: Path) -> None:
    _write_ficha(
        tmp_path, "lore/politica/politica.md",
        'id: "Política | Distribución Y Territorios"\ntitle: "Política | Distribución Y Territorios"\ntype: concepto\nstatus: stable\n',
    )
    _write_ficha(
        tmp_path, "lore/politica/atherr.md",
        'id: "Política | Distribución Y Territorios::Atherr"\ntitle: Atherr\ntype: lugar\nstatus: stable\n',
    )
    conv = probe_folder_convention(tmp_path, "lore", "politica")
    assert conv.convention == "canonical-single"
    assert conv.parent == "Política | Distribución Y Territorios"
    assert conv.type == "concepto"
    assert conv.status == "stable"
    assert conv.source == "politica"


def test_probe_prefers_template_even_though_excluded_from_indexing(tmp_path: Path) -> None:
    _write_ficha(
        tmp_path, "lore/politica/_Plantilla_Ficha.md",
        'id: "Política | Distribución Y Territorios::Título"\ntype: concepto\n',
    )
    _write_ficha(
        tmp_path, "lore/politica/atherr.md",
        'id: "Política | Distribución Y Territorios::Atherr"\ntype: lugar\nstatus: stable\n',
    )
    conv = probe_folder_convention(tmp_path, "lore", "politica")
    assert conv.source == "_Plantilla_Ficha"
    assert conv.convention == "canonical"
    assert conv.type == "concepto"
    assert conv.status == "draft"


def test_probe_skips_excluded_siblings_and_prefers_section_level(tmp_path: Path) -> None:
    _write_ficha(tmp_path, "lore/politica/_README.md", "id: Inútil\ntype: concepto\nstatus: stable\n")
    _write_ficha(tmp_path, "lore/lore.md", 'id: "Lore"\ntitle: Lore\ntype: concepto\nstatus: stable\n')
    conv = probe_folder_convention(tmp_path, "lore", "politica")
    assert conv.convention == "canonical-single"
    assert conv.parent == "Lore"
    assert conv.source == "lore"


def test_probe_status_outside_valid_ficha_statuses_degrades_to_draft(tmp_path: Path) -> None:
    _write_ficha(tmp_path, "lore/politica/politica.md", "id: Tema\ntitle: Tema\ntype: concepto\nstatus: synced\n")
    conv = probe_folder_convention(tmp_path, "lore", "politica")
    assert conv.status == "draft"


def test_probe_empty_personajes_folder_falls_back_to_personajes_default(tmp_path: Path) -> None:
    (tmp_path / "personajes").mkdir(parents=True)
    conv = probe_folder_convention(tmp_path, "personajes", "")
    assert conv.convention == "personajes"
    assert conv.type == "Personaje"
    assert conv.status == "draft"
    assert conv.source is None


def test_probe_absent_personajes_folder_falls_back_to_personajes_default(tmp_path: Path) -> None:
    conv = probe_folder_convention(tmp_path, "personajes", "")
    assert conv.convention == "personajes"
    assert conv.type == "Personaje"


def test_probe_empty_lore_folder_falls_back_to_canonical_default(tmp_path: Path) -> None:
    conv = probe_folder_convention(tmp_path, "lore", "nuevo-tema")
    assert conv.convention == "canonical"
    assert conv.parent == "Nuevo Tema"
    assert conv.type == "concepto"
    assert conv.status == "draft"


def test_probe_empty_referencias_folder_falls_back_to_referencia_default(tmp_path: Path) -> None:
    conv = probe_folder_convention(tmp_path, "referencias", "")
    assert conv.convention == "canonical"
    assert conv.parent == "Referencias"
    assert conv.type == "referencia"


# ---------------------------------------------------------------------------
# build_ficha_skeleton (task 1.5, AD4)
# ---------------------------------------------------------------------------


def test_skeleton_personajes_emits_slug_id_type_and_schema_version(tmp_path: Path) -> None:
    conv = FolderConvention("personajes", "", "Personaje", "draft", None)
    content = _skeleton(tmp_path, section="personajes", folder="", slug="arquero-ciego",
                        title="Arquero Ciego", convention=conv)
    fm = _frontmatter(content)
    assert fm["id"] == "arquero-ciego"
    assert fm["title"] == "Arquero Ciego"
    assert fm["type"] == "Personaje"
    assert fm["schema_version"] == 1
    assert fm["status"] == "draft"
    assert fm["based_on"] == "ideas/arquero-ciego"
    assert fm["relaciones"] == []
    assert "# Arquero Ciego" in content


def test_skeleton_canonical_emits_parent_qualified_id_and_wikilinks(tmp_path: Path) -> None:
    conv = FolderConvention("canonical", "Política | Distribución Y Territorios", "concepto", "stable", None)
    relations = (Relation("Política | Distribución Y Territorios::Ekkor", "relacionado-con"),)
    content = _skeleton(tmp_path, section="lore", folder="politica", slug="arquero-ciego",
                        title="Atherr", relations=relations, convention=conv)
    fm = _frontmatter(content)
    assert fm["id"] == "Política | Distribución Y Territorios::Atherr"
    assert fm["type"] == "concepto"
    assert fm["status"] == "stable"
    assert fm["based_on"] == "ideas/arquero-ciego"
    assert fm["relaciones"] == ["[[Política | Distribución Y Territorios::Ekkor]]"]


def test_skeleton_canonical_single_index_ficha_uses_title_as_id(tmp_path: Path) -> None:
    conv = FolderConvention("canonical-single", "Tema", "concepto", "draft", None)
    content = _skeleton(tmp_path, section="lore", folder="tema", slug="tema", title="Tema", convention=conv)
    assert _frontmatter(content)["id"] == "Tema"


def test_skeleton_canonical_single_child_uses_parent_qualified_id(tmp_path: Path) -> None:
    conv = FolderConvention("canonical-single", "Tema", "concepto", "draft", None)
    content = _skeleton(tmp_path, section="lore", folder="tema", slug="idea-uno", title="Idea Uno", convention=conv)
    assert _frontmatter(content)["id"] == "Tema::Idea Uno"


def test_skeleton_normalizes_title_whitespace_in_canonical_id(tmp_path: Path) -> None:
    conv = FolderConvention("canonical", "Tema", "concepto", "draft", None)
    content = _skeleton(tmp_path, section="lore", folder="tema", slug="idea-uno",
                        title="  Idea   Uno  ", convention=conv)
    assert _frontmatter(content)["id"] == "Tema::Idea Uno"


def test_skeleton_builds_from_probed_convention(tmp_path: Path) -> None:
    _write_ficha(
        tmp_path, "lore/politica/politica.md",
        'id: "Política | Distribución Y Territorios"\ntitle: "Política | Distribución Y Territorios"\ntype: concepto\nstatus: stable\n',
    )
    content = _skeleton(tmp_path, section="lore", folder="politica", slug="nueva-region", title="Nueva Región")
    fm = _frontmatter(content)
    assert fm["id"] == "Política | Distribución Y Territorios::Nueva Región"
    assert fm["type"] == "concepto"
    assert fm["status"] == "stable"
    assert fm["based_on"] == "ideas/nueva-region"


def test_skeleton_always_emits_type_and_based_on(tmp_path: Path) -> None:
    for section, expected_type in (("personajes", "Personaje"), ("lore", "concepto"), ("referencias", "referencia")):
        content = _skeleton(tmp_path, section=section, folder="tema", slug="idea-uno", title="Idea Uno")
        fm = _frontmatter(content)
        assert fm["type"] == expected_type
        assert fm["based_on"] == "ideas/idea-uno"


def test_skeleton_based_on_uses_idea_slug_while_id_follows_slug(tmp_path: Path) -> None:
    """WU-6 trap 1: the filename slug and the idea link are independent.

    ``id`` follows the file slug (``slug``) while ``based_on`` must keep the
    idea's internal slug — passing the title-derived filename into ``based_on``
    would silently corrupt traceability.
    """
    conv = FolderConvention("canonical", "Tema", "concepto", "draft", None)
    content = _skeleton(
        tmp_path, section="lore", folder="tema",
        slug="mi-nombre-raro", idea_slug="2026-08-28-524e8b9c9770",
        title="Mi Nombre Raro", convention=conv,
    )
    fm = _frontmatter(content)
    assert fm["id"] == "Tema::Mi Nombre Raro"
    assert fm["based_on"] == "ideas/2026-08-28-524e8b9c9770"


def test_skeleton_canonical_single_based_on_uses_idea_slug_with_slug_equal_folder(tmp_path: Path) -> None:
    """WU-6 trap 3: the ``slug == folder`` index branch still keys ``id`` off
    ``slug`` (title-as-id) while ``based_on`` keeps the separate idea slug."""
    conv = FolderConvention("canonical-single", "Tema", "concepto", "draft", None)
    content = _skeleton(
        tmp_path, section="lore", folder="tema",
        slug="tema", idea_slug="2026-08-28-524e8b9c9770",
        title="Tema", convention=conv,
    )
    fm = _frontmatter(content)
    assert fm["id"] == "Tema"
    assert fm["based_on"] == "ideas/2026-08-28-524e8b9c9770"


def test_skeleton_canonical_single_title_derived_slug_fails_index_test_not_fixed(tmp_path: Path) -> None:
    """WU-6 trap 3: a title-derived slug correctly fails ``slug == folder``, so
    a child ficha (not the index) keeps the ``Parent::Title`` id — do NOT
    "fix" this into an index id."""
    conv = FolderConvention("canonical-single", "Tema", "concepto", "draft", None)
    content = _skeleton(
        tmp_path, section="lore", folder="tema",
        slug="mi-nombre-raro", idea_slug="idea-uno",
        title="Mi Nombre Raro", convention=conv,
    )
    assert _frontmatter(content)["id"] == "Tema::Mi Nombre Raro"


# ---------------------------------------------------------------------------
# build_ficha_skeleton — image injection (CI-1, materialize-carry-idea-image)
# ---------------------------------------------------------------------------


def test_skeleton_image_injected_immediately_after_imposed_h1(tmp_path: Path) -> None:
    """FT-1: the AI's own H1 is replaced by the title, and the image follows it."""
    content = _skeleton(
        tmp_path, slug="arquero-ciego", title="Arquero Ciego",
        body="# Cuerpo del arquero\n\nTexto posterior.\n",
        image_rel="media/arquero-ciego.jpg",
    )
    assert (
        "# Arquero Ciego\n![Arquero Ciego](media/arquero-ciego.jpg)\n\nTexto posterior."
        in content
    )
    assert "# Cuerpo del arquero" not in content
    assert content.endswith("Texto posterior.\n")


def test_skeleton_image_injected_after_inserted_h1_when_body_has_none(tmp_path: Path) -> None:
    """FT-1: a body without an H1 gets one, and the image follows it."""
    content = _skeleton(tmp_path, body="Texto sin encabezado.\n", image_rel="media/idea-uno.png")
    assert content.endswith(
        "---\n\n# Idea Uno\n![Idea Uno](media/idea-uno.png)\n\nTexto sin encabezado.\n"
    )


def test_skeleton_image_only_h1_body_has_no_dangling_blank_line(tmp_path: Path) -> None:
    content = _skeleton(tmp_path, body="# Solo titulo\n", image_rel="media/idea-uno.png")
    assert content.endswith("# Idea Uno\n![Idea Uno](media/idea-uno.png)\n")


def test_skeleton_image_after_h1_collapses_extra_leading_blanks(tmp_path: Path) -> None:
    content = _skeleton(
        tmp_path, body="# Titulo\n\n\n\nTexto.\n", image_rel="media/idea-uno.png",
    )
    assert "# Idea Uno\n![Idea Uno](media/idea-uno.png)\n\nTexto." in content


def test_skeleton_image_alt_escapes_markdown_brackets(tmp_path: Path) -> None:
    """A bracket or newline in the title must not break the image syntax."""
    content = _skeleton(
        tmp_path, title="Nivel [5]\nde Chaae", body="Texto.\n",
        image_rel="media/nivel-5.png",
    )
    assert "![Nivel \\[5\\] de Chaae](media/nivel-5.png)" in content


def test_skeleton_no_image_is_byte_identical_to_current_output(tmp_path: Path) -> None:
    """CI-1 invariant 4: with no H1 rewrite, ``image_rel=None`` emits exactly
    today's bytes (the body already opens with ``# {title}``)."""
    conv = FolderConvention("personajes", "", "Personaje", "draft", None)
    kwargs = dict(
        section="personajes", folder="", slug="arquero-ciego",
        title="Arquero Ciego", body="# Arquero Ciego\n", convention=conv,
    )
    default = _skeleton(tmp_path, **kwargs)
    explicit_none = _skeleton(tmp_path, image_rel=None, **kwargs)
    assert explicit_none == default
    assert "![" not in default
    golden = (
        "---\n"
        "id: arquero-ciego\n"
        "title: Arquero Ciego\n"
        "type: Personaje\n"
        "status: draft\n"
        "relaciones: []\n"
        "based_on: ideas/arquero-ciego\n"
        "schema_version: 1\n"
        "---\n\n"
        "# Arquero Ciego\n"
    )
    assert default == golden


# ---------------------------------------------------------------------------
# build_ficha_skeleton — the title owns the H1 (FT-1, ficha-title-owns-h1)
# ---------------------------------------------------------------------------


def test_skeleton_replaces_ai_h1_with_title(tmp_path: Path) -> None:
    """FT-1: the AI's own leading H1 is discarded and replaced by the title."""
    content = _skeleton(
        tmp_path, title="Arquero Ciego",
        body="# Titulo inventado por la IA\n\nTexto posterior.\n",
    )
    assert content.endswith("---\n\n# Arquero Ciego\n\nTexto posterior.\n")
    assert "Titulo inventado por la IA" not in content


def test_skeleton_prepends_h1_when_body_has_none(tmp_path: Path) -> None:
    """FT-1: a body without a leading H1 gets ``# {title}`` + one blank line."""
    content = _skeleton(
        tmp_path, title="Arquero Ciego",
        body="Texto sin encabezado.\n",
    )
    assert content.endswith("---\n\n# Arquero Ciego\n\nTexto sin encabezado.\n")


def test_skeleton_h1_equals_frontmatter_title(tmp_path: Path) -> None:
    """FT-1: the imposed H1 and the frontmatter ``title`` are the same value."""
    content = _skeleton(tmp_path, title="Arquero Ciego", body="# Otro encabezado\n")
    fm = _frontmatter(content)
    assert fm["title"] == "Arquero Ciego"
    assert f"# {fm['title']}\n" in content


def test_skeleton_leaves_later_h1_untouched(tmp_path: Path) -> None:
    """FT-1: only the leading H1 is rewritten; any later H1 survives."""
    body = "# Primer encabezado\n\nTexto.\n\n# Segundo encabezado\n\nMas texto.\n"
    content = _skeleton(tmp_path, title="Arquero Ciego", body=body)
    assert "# Arquero Ciego\n\nTexto." in content
    assert "# Segundo encabezado\n\nMas texto." in content
    assert "# Primer encabezado" not in content


def test_skeleton_image_lands_right_after_imposed_h1(tmp_path: Path) -> None:
    content = _skeleton(
        tmp_path, title="Arquero Ciego",
        body="# Otro encabezado\n\nTexto.\n",
        image_rel="media/arquero-ciego.jpg",
    )
    assert content.endswith(
        "---\n\n# Arquero Ciego\n![Arquero Ciego](media/arquero-ciego.jpg)\n\nTexto.\n"
    )


def test_skeleton_no_rewrite_keeps_bytes_identical(tmp_path: Path) -> None:
    """FT-1: when the body already opens with ``# {title}`` there is no rewrite
    and ``image_rel=None`` output stays byte-identical to the previous behavior."""
    conv = FolderConvention("personajes", "", "Personaje", "draft", None)
    content = _skeleton(
        tmp_path, section="personajes", folder="", slug="arquero-ciego",
        title="Arquero Ciego", body="# Arquero Ciego\n\nTexto.\n", convention=conv,
    )
    assert content.endswith("---\n\n# Arquero Ciego\n\nTexto.\n")


# ---------------------------------------------------------------------------
# build_grounding_candidates (task 1.6, AD6)
# ---------------------------------------------------------------------------


def test_candidates_empty_world_is_empty_list() -> None:
    assert build_grounding_candidates(_FakeReader([])) == []


def test_candidates_skip_entities_without_canonical_id() -> None:
    reader = _FakeReader([
        _entity("lore/a/one.md", id="Tema::Uno", title="Uno"),
        _entity("lore/a/two.md", id="", title="Dos"),
        _entity("lore/a/three.md", id="Tema::Tres", title="Tres"),
    ])
    candidates = build_grounding_candidates(reader)
    assert [c["id"] for c in candidates] == ["Tema::Uno", "Tema::Tres"]


def test_candidates_shape_and_summary_truncated_to_160() -> None:
    reader = _FakeReader([
        _entity("lore/a/one.md", id="Tema::Uno", title="Uno", type="lugar", description="d" * 200),
    ])
    assert build_grounding_candidates(reader) == [
        {"id": "Tema::Uno", "title": "Uno", "type": "lugar", "summary": "d" * 160},
    ]


def test_candidates_preserve_rank_order_and_cap_at_max_candidates() -> None:
    reader = _FakeReader([
        _entity(f"lore/a/e{i}.md", id=f"Tema::E{i}", title=f"E{i}") for i in range(30)
    ])
    candidates = build_grounding_candidates(reader)
    assert len(candidates) == MAX_CANDIDATES
    assert [c["id"] for c in candidates] == [f"Tema::E{i}" for i in range(25)]


def test_candidates_bounded_by_payload_chars_drops_lowest_ranked() -> None:
    reader = _FakeReader([
        _entity(f"lore/a/e{i}.md", id=f"Tema::E{i}", title=f"E{i}", description="d" * 160)
        for i in range(30)
    ])
    candidates = build_grounding_candidates(reader)
    assert len(candidates) < MAX_CANDIDATES
    payload = sum(len(json.dumps(c, ensure_ascii=False, separators=(",", ":"))) for c in candidates)
    assert payload <= MAX_CANDIDATE_PAYLOAD_CHARS
    assert candidates[0]["id"] == "Tema::E0"


def test_candidates_section_filter_keeps_matching_paths() -> None:
    reader = _FakeReader([
        _entity("lore/a/one.md", id="Tema::Uno", title="Uno"),
        _entity("personajes/Daest.md", id="daest", title="Daest", type="Personaje"),
    ])
    candidates = build_grounding_candidates(reader, section_filter="lore")
    assert [c["id"] for c in candidates] == ["Tema::Uno"]


def test_candidates_skip_hits_without_path() -> None:
    class _PathlessReader(_FakeReader):
        def search(self, query: str) -> list[dict]:
            return [{"name": "no-path"}]

    assert build_grounding_candidates(_PathlessReader([_entity("lore/a/one.md", id="Tema::Uno")])) == []


def test_candidates_use_entities_seam_when_search_is_empty() -> None:
    """BUG-B regression at the domain level: grounding must use the reader's
    ``entities()`` enumeration seam — ``search("*")`` returns [] against the
    real index by design, so a reader mirroring that behavior must still
    yield candidates."""
    class _RealIndexLikeReader(_FakeReader):
        def entities(self) -> list[dict]:
            return [dict(e) for e in self._entities]

        def search(self, query: str) -> list[dict]:
            return []

    reader = _RealIndexLikeReader([
        _entity("personajes/rhyz.md", id="Rhyz::Rhyz", title="Rhyz", type="Personaje"),
    ])
    assert build_grounding_candidates(reader) == [
        {"id": "Rhyz::Rhyz", "title": "Rhyz", "type": "Personaje", "summary": ""},
    ]


def test_candidates_prefer_entities_seam_order_when_both_exposed() -> None:
    """A reader with both seams must enumerate via ``entities()`` (index
    insertion order), never re-derive from search hits."""
    class _BothSeamsReader(_FakeReader):
        def entities(self) -> list[dict]:
            return [dict(e) for e in reversed(self._entities)]

    reader = _BothSeamsReader([
        _entity("lore/a/one.md", id="Tema::Uno", title="Uno"),
        _entity("lore/a/two.md", id="Tema::Dos", title="Dos"),
    ])
    # The enumeration seam is authoritative (reversed order proves it is used
    # instead of the search/read fallback).
    assert [c["id"] for c in build_grounding_candidates(reader)] == ["Tema::Dos", "Tema::Uno"]


# ---------------------------------------------------------------------------
# validate_relations (task 1.6, R-IM-03 + binding clarification)
# ---------------------------------------------------------------------------


def test_validate_relations_keeps_existing_and_in_vocabulary() -> None:
    proposed = [Relation("A::B", "aliado-de"), Relation("C::D", "enemigo-de")]
    kept, discarded = validate_relations(proposed, {"A::B", "C::D"})
    assert kept == proposed
    assert discarded == []


@pytest.mark.parametrize("target_id, rel_type, reason", [
    ("E::F", "aliado-de", "target_not_found"),
    ("A::B", "made_up_type", "rel_type_out_of_vocabulary"),
    ("E::F", "made_up_type", "target_not_found"),   # target checked first
])
def test_validate_relations_drops_and_reports(target_id: str, rel_type: str, reason: str) -> None:
    kept, discarded = validate_relations([Relation(target_id, rel_type)], {"A::B"})
    assert kept == []
    assert discarded == [{"target_id": target_id, "reason": reason}]


def test_validate_relations_never_creates_stubs() -> None:
    proposed = [
        Relation("E::F", "aliado-de"),
        Relation("A::B", "aliado-de"),
        Relation("G::H", "mentor-de"),
    ]
    kept, discarded = validate_relations(proposed, {"A::B"})
    assert kept == [Relation("A::B", "aliado-de")]
    assert discarded == [
        {"target_id": "E::F", "reason": "target_not_found"},
        {"target_id": "G::H", "reason": "target_not_found"},
    ]


def test_validate_relations_empty_proposed_is_valid() -> None:
    kept, discarded = validate_relations([], {"A::B"})
    assert kept == []
    assert discarded == []


def test_validate_relations_custom_vocabulary() -> None:
    kept, discarded = validate_relations(
        [Relation("A::B", "made_up_type")], {"A::B"}, vocab=frozenset({"made_up_type"}),
    )
    assert kept == [Relation("A::B", "made_up_type")]
    assert discarded == []