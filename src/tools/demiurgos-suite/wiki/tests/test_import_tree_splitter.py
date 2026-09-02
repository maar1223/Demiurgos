# -*- coding: utf-8 -*-
"""World importer — Phase 1 (importador-auto-frontmatter) tests for the
deterministic H1-H5 tree splitter: H1-H5 nesting, canonical parent-qualified
identities, empty-scaffold preservation, tree-aware materialization (every
heading is a ficha; a folder is created only when the heading has children
or is H1 — a childless heading at level > 1 lands as a loose file in the
nearest ancestor's folder), repeated-title ordinals, the Hermes
structure-inference fallback seam, and reference-image diagnostics.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_TOOLS = _HERE.parents[2]
for _p in (str(_WIKI), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from import_analysis import (  # noqa: E402
    HeadingSpan,
    HeadingStructure,
    detect_heading_structure,
    reference_image_diagnostics,
    split_heading_tree,
)


# ---------------------------------------------------------------------------
# Task 1.3 — H1-H5 nesting and deterministic splitting
# ---------------------------------------------------------------------------


class TestHeadingTreeSplitter:
    def test_h1_h5_nesting_builds_hierarchy(self):
        """Nested H1-H5 produce parent-qualified ficha ids in source order;
        EVERY heading — including the leaf H5 ``Manos`` — is its own ficha
        (no heading folds into a parent)."""
        text = (
            "# Ayagares\n\n"
            "## Descripción Física\n\n"
            "### Forma Base\n\n"
            "#### Extremidades\n\n"
            "##### Manos\n\n"
            "Cinco dedos.\n"
        )
        tree = split_heading_tree(text)
        assert tree.usable_structure is True
        assert tree.diagnostic == ""
        assert [f.canonical_id for f in tree.fichas] == [
            "Ayagares",
            "Ayagares::Descripción Física",
            "Ayagares::Descripción Física::Forma Base",
            "Ayagares::Descripción Física::Forma Base::Extremidades",
            "Ayagares::Descripción Física::Forma Base::Extremidades::Manos",
        ]
        root = tree.fichas[0]
        assert root.level == 1 and root.source_order == 0
        assert root.children[0].title == "Descripción Física"
        manos = tree.fichas[-1]
        assert manos.level == 5
        # The ficha's own heading opens its body (self-descriptive ficha).
        assert manos.body == "##### Manos\n\nCinco dedos."
        assert manos.children == []
        # The leaf's parent keeps ONLY its own prose — nothing folded.
        extremidades = tree.fichas[-2]
        assert extremidades.body == "#### Extremidades"
        assert [c.title for c in extremidades.children] == ["Manos"]

    def test_empty_h1_scaffold_is_preserved(self):
        """An empty H1 remains a valid root/index ficha, never dropped. Its
        body carries the heading line so the ficha is self-descriptive."""
        tree = split_heading_tree("# Vacía\n\n# Llena\n\nContenido.\n")
        assert [f.canonical_id for f in tree.fichas] == ["Vacía", "Llena"]
        vacia, llena = tree.fichas
        assert vacia.body == "# Vacía"
        assert vacia.level == 1 and vacia.is_ficha
        assert llena.body == "# Llena\n\nContenido."

    def test_childless_heading_is_own_ficha_not_folded(self):
        """A childless heading (``Sociedad`` H2, ``Forma Base`` H3) is its
        OWN ficha — never folded into the parent — and keeps its own prose
        in its body. Materialization is tree-aware: the childless headings
        land as loose files in the nearest ancestor's folder (see
        ``TestMaterializedPaths``)."""
        text = (
            "# Ayagares\n\n"
            "Intro del mundo.\n\n"
            "## Descripción Física\n\n"
            "Prosa directa.\n\n"
            "### Forma Base\n\n"
            "Cuerpo y extremidades.\n\n"
            "## Sociedad\n\n"
            "Sin hijos.\n"
        )
        tree = split_heading_tree(text)
        # Every heading becomes a ficha: childless Sociedad and Forma Base
        # are emitted (at execution they land as loose files in the nearest
        # ancestor's folder, per the tree-aware folder rule).
        assert [f.canonical_id for f in tree.fichas] == [
            "Ayagares",
            "Ayagares::Descripción Física",
            "Ayagares::Descripción Física::Forma Base",
            "Ayagares::Sociedad",
        ]
        ayagares, df, fb, sociedad = tree.fichas
        # Nothing folds: each ficha carries only its own prose.
        assert "Intro del mundo." in ayagares.body
        assert "## Sociedad" not in ayagares.body
        assert "Sin hijos." not in ayagares.body
        assert "Prosa directa." in df.body
        assert "### Forma Base" not in df.body
        assert "Cuerpo y extremidades." in fb.body
        assert "Sin hijos." in sociedad.body
        assert sociedad.level == 2 and sociedad.children == []

    def test_preamble_folds_into_first_root(self):
        """Lines before the first heading are preserved in the first root."""
        tree = split_heading_tree("Intro global.\n\n# Ayagares\n\nCuerpo.\n")
        assert len(tree.fichas) == 1
        ficha = tree.fichas[0]
        assert ficha.canonical_id == "Ayagares"
        assert "Intro global." in ficha.body
        assert "Cuerpo." in ficha.body

    def test_no_headings_yields_implicit_single_ficha(self):
        """Legacy path: a source without headings is one implicit ficha."""
        tree = split_heading_tree(
            "Texto suelto sin encabezados.\n\nSegunda línea.\n")
        assert tree.usable_structure is False
        assert tree.diagnostic == "no_heading_structure"
        assert len(tree.fichas) == 1
        ficha = tree.fichas[0]
        assert ficha.is_implicit is True
        assert ficha.canonical_id == ""
        assert ficha.body == "Texto suelto sin encabezados.\n\nSegunda línea."

    def test_accepts_explicit_structure(self):
        """Callers that already detected can short-circuit Step 0."""
        structure = HeadingStructure(
            spans=[HeadingSpan(level=1, title="Manual",
                               source_text="# Manual", line_index=0)],
            usable=True, diagnostic="",
        )
        tree = split_heading_tree("# Manual\n\nCuerpo.\n", structure=structure)
        assert tree.fichas[0].canonical_id == "Manual"
        assert tree.fichas[0].body == "# Manual\n\nCuerpo."


# ---------------------------------------------------------------------------
# Task 1.1/1.3 — canonical parent-qualified identities
# ---------------------------------------------------------------------------


class TestCanonicalIdentities:
    def test_repeated_title_siblings_get_deterministic_ordinals(self):
        """``Descripción Física``/``Forma Base`` repeated under the same
        parent receive ``#2`` ordinals in source order."""
        text = (
            "# Ayagares\n\n"
            "## Descripción Física\n\n"
            "### Forma Base\n\n"
            "#### Detalles\n\n"
            "Cuerpo A.\n\n"
            "## Descripción Física\n\n"
            "### Forma Base\n\n"
            "#### Otros\n\n"
            "Cuerpo B.\n"
        )
        tree = split_heading_tree(text)
        # Every level is a ficha now: the leaf H4s (``Detalles``/``Otros``)
        # are emitted too, and duplicate siblings keep their ordinals.
        assert [f.canonical_id for f in tree.fichas] == [
            "Ayagares",
            "Ayagares::Descripción Física",
            "Ayagares::Descripción Física::Forma Base",
            "Ayagares::Descripción Física::Forma Base::Detalles",
            "Ayagares::Descripción Física#2",
            "Ayagares::Descripción Física#2::Forma Base",
            "Ayagares::Descripción Física#2::Forma Base::Otros",
        ]

    def test_repeated_titles_across_branches_are_parent_qualified(self):
        """Same titles in different branches stay distinct and addressable."""
        text = (
            "# Ayagares\n\n"
            "## Descripción Física\n\n"
            "### Forma Base\n\n"
            "#### A\n\n"
            "Cuerpo A.\n\n"
            "# Vibrantes\n\n"
            "## Descripción Física\n\n"
            "### Forma Base\n\n"
            "#### B\n\n"
            "Cuerpo B.\n"
        )
        tree = split_heading_tree(text)
        ids = [f.canonical_id for f in tree.fichas]
        assert "Ayagares::Descripción Física::Forma Base" in ids
        assert "Vibrantes::Descripción Física::Forma Base" in ids
        assert len(ids) == len(set(ids)), "canonical ids must be unique"


# ---------------------------------------------------------------------------
# Task 1.2 — Step 0 detection with the Hermes structure-inference seam
# ---------------------------------------------------------------------------


class TestHeadingDetection:
    def test_deterministic_scan(self):
        structure = detect_heading_structure("# A\n\n## B\n\n### C\n")
        assert structure.usable is True
        assert structure.inferred is False
        assert [(s.level, s.title) for s in structure.spans] == [
            (1, "A"), (2, "B"), (3, "C"),
        ]

    def test_inference_fallback_used_when_no_headings(self):
        called: list[str] = []

        def infer(text: str):
            called.append(text)
            return [HeadingSpan(level=1, title="Inferido",
                                source_text="# Inferido", line_index=0)]

        structure = detect_heading_structure(
            "Sin encabezados.", structure_inference=infer)
        assert structure.usable is True
        assert structure.inferred is True
        assert structure.diagnostic == "structure_inferred"
        assert structure.spans[0].title == "Inferido"
        assert called == ["Sin encabezados."]

    def test_fail_open_without_fallback(self):
        structure = detect_heading_structure("Sin encabezados.")
        assert structure.usable is False
        assert structure.diagnostic == "no_heading_structure"

    def test_inference_failure_fails_open(self):
        def boom(text: str):
            raise RuntimeError("hermes down")

        structure = detect_heading_structure(
            "Sin encabezados.", structure_inference=boom)
        assert structure.usable is False
        assert structure.diagnostic == "no_heading_structure"

    def test_inferred_structure_feeds_the_splitter(self):
        structure = HeadingStructure(
            spans=[HeadingSpan(level=1, title="Inferido",
                               source_text="# Inferido", line_index=0)],
            usable=True, diagnostic="structure_inferred", inferred=True,
        )
        tree = split_heading_tree(
            "# Inferido\n\nTexto plano.\n", structure=structure)
        assert tree.fichas[0].canonical_id == "Inferido"
        assert tree.fichas[0].body == "# Inferido\n\nTexto plano."


# ---------------------------------------------------------------------------
# Task 1.4 — reference-image diagnostics
# ---------------------------------------------------------------------------


class TestReferenceImageDiagnostics:
    def test_unresolved_reference_preserved_verbatim(self):
        text = (
            "# Ayagares\n\n"
            "Intro con ![][image1] referencia.\n\n"
            "## Sociedad\n\n"
            "Otra ![portada][image2].\n"
        )
        tree = split_heading_tree(text)
        # ``## Sociedad`` is its OWN ficha (every heading is a ficha), so
        # its diagnostic span lives in Sociedad's ficha, not Ayagares'.
        by_ficha = {f.canonical_id: f for f in tree.fichas}
        ayagares = by_ficha["Ayagares"]
        sociedad = by_ficha["Ayagares::Sociedad"]
        diags = ayagares.media_diagnostics
        assert len(diags) == 1
        assert diags[0].image_key == "image1"
        assert diags[0].reference == "![][image1]"
        assert diags[0].status == "unresolved"
        assert diags[0].target_ficha == "Ayagares"
        assert "no definition" in diags[0].message
        diag2 = sociedad.media_diagnostics[0]
        assert diag2.image_key == "image2"
        assert diag2.alt_text == "portada"
        assert diag2.status == "unresolved"
        assert diag2.target_ficha == "Ayagares::Sociedad"

    def test_resolved_reference_with_definition(self):
        text = (
            "# Ayagares\n\n"
            "![][portada]\n\n"
            "[portada]: media/portada.png\n"
        )
        tree = split_heading_tree(text)
        diag = tree.fichas[0].media_diagnostics[0]
        assert diag.reference == "![][portada]"
        assert diag.status == "resolved"
        assert diag.target_path == "media/portada.png"

    def test_direct_function_is_pure(self):
        diags = reference_image_diagnostics(
            "![][a] y ![][b]\n\n[b]: media/b.png\n", "Ayagares")
        by_key = {d.image_key: d for d in diags}
        assert by_key["a"].status == "unresolved"
        assert by_key["b"].status == "resolved"
        assert by_key["b"].target_path == "media/b.png"

class TestMarkdownCleaning:
    """Converted .docx/.pdf sources carry ``**``/image noise that must be
    cleaned from derived TITLES/IDENTITIES only. The ficha BODY stays
    verbatim markdown so the viewer keeps rendering bold/italic/code."""

    def test_bold_title_is_unwrapped_in_identity(self):
        tree = split_heading_tree(
            "# **El Origen | Breve Historia De Los Vibrantes**\n\nTexto.\n")
        ficha = tree.fichas[0]
        assert ficha.title == "El Origen | Breve Historia De Los Vibrantes"
        assert ficha.canonical_id == "El Origen | Breve Historia De Los Vibrantes"
        assert "**" not in ficha.title
        assert "**" not in ficha.canonical_id

    def test_heading_with_only_image_falls_back_to_seccion(self):
        tree = split_heading_tree(
            "# **![](data:image/png;base64,AAAA)![]()**\n\nCuerpo.\n")
        ficha = tree.fichas[0]
        assert ficha.title == "Sección"
        assert ficha.canonical_id == "Sección"

    def test_ficha_own_heading_opens_body_with_pipe_preserved(self):
        """BUG 3 — the ficha's own heading line opens the body verbatim, and a
        ``|`` in the title stays a real markdown heading (self-descriptive
        ficha, no duplicated title)."""
        tree = split_heading_tree(
            "# Vibrastal | Estados y Niveles\n\nContenido.\n")
        ficha = tree.fichas[0]
        assert ficha.body == "# Vibrastal | Estados y Niveles\n\nContenido."
        assert ficha.title == "Vibrastal | Estados y Niveles"

    def test_body_preserves_markdown_formatting_verbatim(self):
        # Emphasis markers are REAL document formatting (bold/italic/code from
        # the original Word source) — the viewer renders them. Only derived
        # metadata (title/identity) is cleaned, never the body.
        tree = split_heading_tree(
            "# Ayagares\n\n"
            "Los **Ayagares** son *seres* de `luz`.\n\n"
            "![portada](media/portada.png)\n")
        body = tree.fichas[0].body
        assert "**Ayagares**" in body
        assert "*seres*" in body
        assert "`luz`" in body
        assert "![portada](media/portada.png)" in body

    def test_identity_contract_also_strips_markdown(self):
        from import_models import normalize_identity_segment
        assert normalize_identity_segment(
            "**Descripción Física**") == "Descripción Física"
        # Image alt text is preserved (it is the only human text); the base64
        # payload and markdown markers disappear.
        assert normalize_identity_segment(
            "![logo](data:image/png;base64,xxx) Sección") == "logo Sección"
        assert normalize_identity_segment("![]() Sección") == "Sección"


class TestMaterializedPaths:
    """Tree-aware materialization (import folder rule): a heading creates a
    FOLDER only when it has children OR is a ROOT (the top title of the tree
    — no parent heading, whatever its level). A non-root childless heading
    does NOT create a folder: its ficha lands as a loose file in the folder
    of the nearest ancestor that owns one. The ``materialized_path`` is
    relative to the section (``lore``/...); the ``canonical_id`` identity is
    unchanged."""

    def test_h1_alone_always_creates_folder(self):
        """A lone H1 (no children) is ALWAYS a folder with its file inside
        (``lore/<h1>/<h1>.md``) — never a flat file."""
        tree = split_heading_tree("# Dottua\n\nTexto.\n")
        ficha = tree.fichas[0]
        assert ficha.canonical_id == "Dottua"
        assert ficha.materialized_path == "dottua/dottua.md"

    def test_root_not_h1_always_creates_folder(self):
        """A document whose top title is NOT an H1 (here it starts at H2)
        still makes that ROOT a folder (``lore/<h2>/<h2>.md``) — so the root
        scope always owns a folder regardless of the author's heading levels.
        """
        tree = split_heading_tree("## Dottua\n\nTexto.\n")
        ficha = tree.fichas[0]
        assert ficha.level == 2
        assert ficha.children == []
        assert ficha.materialized_path == "dottua/dottua.md"

    def test_h1_with_children_creates_folder(self):
        """An H1 with children keeps its own folder + file; children land
        inside it."""
        tree = split_heading_tree(
            "# Ayagares\n\n"
            "## Descripción Física\n\n"
            "Prosa.\n"
        )
        by_id = {f.canonical_id: f for f in tree.fichas}
        assert by_id["Ayagares"].materialized_path == "ayagares/ayagares.md"
        # H2 childless → loose file in the H1's folder (no H2 folder).
        assert by_id["Ayagares::Descripción Física"].materialized_path == \
            "ayagares/descripcion-fisica.md"

    def test_childless_h2_lands_in_parent_folder(self):
        """H2 child of H1 without children → ``lore/<h1>/<h2>.md`` (no H2
        folder)."""
        tree = split_heading_tree(
            "# Ayagares\n\n"
            "## Sociedad\n\n"
            "Sin hijos.\n"
        )
        sociedad = tree.fichas[1]
        assert sociedad.level == 2 and sociedad.children == []
        assert sociedad.materialized_path == "ayagares/sociedad.md"

    def test_h2_with_children_creates_folder(self):
        """H2 child of H1 WITH children → ``lore/<h1>/<h2>/<h2>.md`` + its
        children inside."""
        tree = split_heading_tree(
            "# Ayagares\n\n"
            "## Descripción Física\n\n"
            "### Forma Base\n\n"
            "Cuerpo.\n"
        )
        by_id = {f.canonical_id: f for f in tree.fichas}
        assert by_id["Ayagares::Descripción Física"].materialized_path == \
            "ayagares/descripcion-fisica/descripcion-fisica.md"
        # H3 childless under the H2-with-children → loose file in H2's folder.
        assert by_id[
            "Ayagares::Descripción Física::Forma Base"].materialized_path == \
            "ayagares/descripcion-fisica/forma-base.md"

    def test_h3_with_children_creates_folder(self):
        """H3 child of H2 WITH children → ``lore/<h1>/<h2>/<h3>/<h3>.md``."""
        tree = split_heading_tree(
            "# Ayagares\n\n"
            "## Descripción Física\n\n"
            "### Forma Base\n\n"
            "#### Detalles\n\n"
            "Cuerpo.\n"
        )
        by_id = {f.canonical_id: f for f in tree.fichas}
        assert by_id[
            "Ayagares::Descripción Física::Forma Base"].materialized_path == \
            "ayagares/descripcion-fisica/forma-base/forma-base.md"
        # H4 childless → loose file in the H3's folder.
        assert by_id[
            "Ayagares::Descripción Física::Forma Base::Detalles"
        ].materialized_path == \
            "ayagares/descripcion-fisica/forma-base/detalles.md"

    def test_deep_childless_leaf_keeps_ancestor_chain(self):
        """A childless leaf at any depth keeps ONLY the folder chain of its
        ancestors that own folders; the leaf itself never creates one."""
        text = (
            "# Ayagares\n\n"
            "## Descripción Física\n\n"
            "### Forma Base\n\n"
            "#### Extremidades\n\n"
            "##### Manos\n\n"
            "Cinco dedos.\n"
        )
        tree = split_heading_tree(text)
        by_id = {f.canonical_id: f for f in tree.fichas}
        # H4 has a child (Manos) → folder; H5 childless → loose file inside.
        assert by_id[
            "Ayagares::Descripción Física::Forma Base::Extremidades"
        ].materialized_path == \
            "ayagares/descripcion-fisica/forma-base/extremidades/extremidades.md"
        assert by_id[
            "Ayagares::Descripción Física::Forma Base::Extremidades::Manos"
        ].materialized_path == \
            "ayagares/descripcion-fisica/forma-base/extremidades/manos.md"

    def test_implicit_ficha_has_no_materialized_path(self):
        """A source without headings yields the implicit ficha with an empty
        materialized path — resolve_target falls back to the legacy
        ``{section}/{identity}.md`` mapping."""
        tree = split_heading_tree("Texto suelto sin encabezados.\n")
        ficha = tree.fichas[0]
        assert ficha.is_implicit is True
        assert ficha.materialized_path == ""

    def test_ordinal_slug_participates_in_path(self):
        """Duplicate same-title siblings keep ``#N`` ordinals in the identity
        AND in the materialized path (``#2`` → ``-2`` slug suffix)."""
        text = (
            "# Ayagares\n\n"
            "## Descripción Física\n\n"
            "Cuerpo A.\n\n"
            "## Descripción Física\n\n"
            "Cuerpo B.\n"
        )
        tree = split_heading_tree(text)
        by_id = {f.canonical_id: f for f in tree.fichas}
        assert by_id["Ayagares::Descripción Física"].materialized_path == \
            "ayagares/descripcion-fisica.md"
        assert by_id["Ayagares::Descripción Física#2"].materialized_path == \
            "ayagares/descripcion-fisica-2.md"
