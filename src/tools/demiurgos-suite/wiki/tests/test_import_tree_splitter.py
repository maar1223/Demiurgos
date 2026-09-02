# -*- coding: utf-8 -*-
"""World importer — Phase 1 (importador-auto-frontmatter) tests for the
deterministic H1-H5 tree splitter: H1-H5 nesting, canonical parent-qualified
identities, empty-scaffold preservation, tree-aware materialization (a
heading is a ficha ONLY when it is a root or has children — a childless
non-root heading folds into its parent ficha as an ``##`` item and every
emitted ficha owns a folder materialized as ``<own>/<own>.md``),
repeated-title ordinals, the Hermes structure-inference fallback seam, and
reference-image diagnostics.
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
        """Nested H1-H5 produce parent-qualified ficha ids in source order.
        A heading is a ficha only when it is a root or has children: the
        childless leaf ``Manos`` is NOT a ficha — it folds into
        ``Extremidades`` as an ``##`` item."""
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
        ]
        root = tree.fichas[0]
        assert root.level == 1 and root.source_order == 0
        assert root.children[0].title == "Descripción Física"
        # The leaf Manos is NOT a ficha: it folds into Extremidades as an
        # ``##`` item (heading re-anchored to H2, then its prose).
        extremidades = tree.fichas[-1]
        assert extremidades.level == 4
        assert extremidades.body == "# Extremidades\n\n## Manos\n\nCinco dedos."
        assert extremidades.children == []
        # Forma Base keeps only its own heading — Extremidades is its child.
        forma_base = tree.fichas[-2]
        assert forma_base.body == "# Forma Base"
        assert [c.title for c in forma_base.children] == ["Extremidades"]

    def test_empty_h1_scaffold_is_preserved(self):
        """An empty H1 remains a valid root/index ficha, never dropped. Its
        body carries the heading line so the ficha is self-descriptive."""
        tree = split_heading_tree("# Vacía\n\n# Llena\n\nContenido.\n")
        assert [f.canonical_id for f in tree.fichas] == ["Vacía", "Llena"]
        vacia, llena = tree.fichas
        assert vacia.body == "# Vacía"
        assert vacia.level == 1 and vacia.is_ficha
        assert llena.body == "# Llena\n\nContenido."

    def test_childless_heading_folds_into_parent_ficha(self):
        """A childless non-root heading (``Sociedad`` H2, ``Forma Base`` H3)
        is NOT a ficha: it folds into its parent ficha's body as an ``##``
        item (heading re-anchored to H2) with its own prose, in source
        order."""
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
        # Only roots and headings with children become fichas: Ayagares
        # (root) and Descripción Física (has child Forma Base).
        assert [f.canonical_id for f in tree.fichas] == [
            "Ayagares",
            "Ayagares::Descripción Física",
        ]
        ayagares, df = tree.fichas
        # Sociedad folds into Ayagares as an ``##`` item after the intro.
        assert ayagares.body == (
            "# Ayagares\n\nIntro del mundo.\n\n"
            "## Sociedad\n\nSin hijos.")
        assert "## Sociedad" in ayagares.body
        assert "Sin hijos." in ayagares.body
        assert ayagares.children == [df]
        # Forma Base folds into Descripción Física as an ``##`` item.
        assert df.body == (
            "# Descripción Física\n\nProsa directa.\n\n"
            "## Forma Base\n\nCuerpo y extremidades.")
        assert df.children == []
        assert df.level == 2

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
        parent receive ``#2`` ordinals in source order; the leaf H4s
        (``Detalles``/``Otros``) fold into their Forma Base parents."""
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
        # Only root/with-children headings are fichas now: the leaf H4s
        # (``Detalles``/``Otros``) fold into their parents, and duplicate
        # siblings keep their ordinals.
        assert [f.canonical_id for f in tree.fichas] == [
            "Ayagares",
            "Ayagares::Descripción Física",
            "Ayagares::Descripción Física::Forma Base",
            "Ayagares::Descripción Física#2",
            "Ayagares::Descripción Física#2::Forma Base",
        ]
        fb = tree.fichas[2]
        assert fb.body == "# Forma Base\n\n## Detalles\n\nCuerpo A."
        fb2 = tree.fichas[4]
        assert fb2.body == "# Forma Base\n\n## Otros\n\nCuerpo B."

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
        # ``## Sociedad`` is a childless non-root heading: it is NOT a ficha
        # and folds into Ayagares, so its image span is diagnosed in
        # Ayagares' ficha (the body includes the folded item).
        assert [f.canonical_id for f in tree.fichas] == ["Ayagares"]
        ayagares = tree.fichas[0]
        assert "## Sociedad" in ayagares.body
        diags = ayagares.media_diagnostics
        assert len(diags) == 2
        by_key = {d.image_key: d for d in diags}
        assert by_key["image1"].reference == "![][image1]"
        assert by_key["image1"].status == "unresolved"
        assert by_key["image1"].target_ficha == "Ayagares"
        assert "no definition" in by_key["image1"].message
        assert by_key["image2"].image_key == "image2"
        assert by_key["image2"].alt_text == "portada"
        assert by_key["image2"].status == "unresolved"
        assert by_key["image2"].target_ficha == "Ayagares"

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
    """Tree-aware materialization (import folder rule): a heading is a ficha
    only when it is a ROOT (the top title of the tree — no parent heading,
    whatever its level) or has at least one child; every emitted ficha owns
    a FOLDER, so its file materializes as ``<own>/<own>.md`` (relative to
    the section, ``lore``/...). A childless non-root heading is NOT a ficha
    — it folds into its parent's ficha as an ``##`` item, so the loose-file
    materialization case disappears. The ``canonical_id`` identity is
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
        """An H1 with children keeps its own folder + file; a childless H2
        (``Descripción Física``) is NOT a ficha — it folds into the H1."""
        tree = split_heading_tree(
            "# Ayagares\n\n"
            "## Descripción Física\n\n"
            "Prosa.\n"
        )
        assert len(tree.fichas) == 1
        ayagares = tree.fichas[0]
        assert ayagares.canonical_id == "Ayagares"
        assert ayagares.materialized_path == "ayagares/ayagares.md"
        assert ayagares.body == "# Ayagares\n\n## Descripción Física\n\nProsa."
        assert ayagares.children == []

    def test_childless_h2_folds_into_parent_folder(self):
        """H2 child of H1 without children → NO ficha, NO loose file: it
        folds into the H1's ficha as an ``##`` item (the loose-file
        materialization case disappears)."""
        tree = split_heading_tree(
            "# Ayagares\n\n"
            "## Sociedad\n\n"
            "Sin hijos.\n"
        )
        assert len(tree.fichas) == 1
        ayagares = tree.fichas[0]
        assert ayagares.materialized_path == "ayagares/ayagares.md"
        assert ayagares.body == "# Ayagares\n\n## Sociedad\n\nSin hijos."
        assert ayagares.children == []

    def test_h2_with_only_leaf_children_is_loose_file(self):
        """H2 child of H1 that only groups leaf items (no child with children)
        → NOT a folder: its ficha is a LOOSE ``<h1>/<h2>.md`` in the parent
        folder; the childless H3 folds into it."""
        tree = split_heading_tree(
            "# Ayagares\n\n"
            "## Descripción Física\n\n"
            "### Forma Base\n\n"
            "Cuerpo.\n"
        )
        by_id = {f.canonical_id: f for f in tree.fichas}
        assert by_id["Ayagares::Descripción Física"].materialized_path == \
            "ayagares/descripcion-fisica.md"
        assert by_id["Ayagares::Descripción Física"].body == \
            "# Descripción Física\n\n## Forma Base\n\nCuerpo."
        # H3 childless under the leaf-grouping H2 → folded item, not a ficha.
        assert "Ayagares::Descripción Física::Forma Base" not in by_id

    def test_h3_with_leaf_child_folds_into_h2_folder(self):
        """H2 (its child H3 has children) owns the folder; the H3 that only
        groups leaf items is a LOOSE ``<h1>/<h2>/<h3>.md`` file inside it;
        the childless H4 folds into the H3."""
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
            "ayagares/descripcion-fisica/forma-base.md"
        assert by_id[
            "Ayagares::Descripción Física::Forma Base"].body == \
            "# Forma Base\n\n## Detalles\n\nCuerpo."
        assert "Ayagares::Descripción Física::Forma Base::Detalles" not in by_id

    def test_deep_childless_leaf_folds_into_ancestor_chain(self):
        """A childless leaf at any depth is NOT a ficha: it folds as an
        ``##`` item into its parent ficha. A heading owns a folder only when
        one of its children also has children — the H2/H3 chains keep theirs,
        but the H4 ``Extremidades`` (its only child is the H5 leaf) is a
        LOOSE file inside the H3 folder."""
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
        # H4 has a child (Manos, a leaf) → NO deep subtree → loose file in H3's
        # folder; the H5 leaf folds into it.
        assert by_id[
            "Ayagares::Descripción Física::Forma Base::Extremidades"
        ].materialized_path == \
            "ayagares/descripcion-fisica/forma-base/extremidades.md"
        assert by_id[
            "Ayagares::Descripción Física::Forma Base::Extremidades"
        ].body == "# Extremidades\n\n## Manos\n\nCinco dedos."
        assert "Ayagares::Descripción Física::Forma Base::Extremidades::Manos" \
            not in by_id

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
        AND in the materialized path (``#2`` → ``-2`` slug suffix); both
        siblings only group leaf items here, so they are LOOSE files
        (``<h1>/<h2>.md`` / ``-2.md``) with their childless H3 folded in."""
        text = (
            "# Ayagares\n\n"
            "## Descripción Física\n\n"
            "### Forma Base\n\n"
            "Cuerpo A.\n\n"
            "## Descripción Física\n\n"
            "### Forma Base\n\n"
            "Cuerpo B.\n"
        )
        tree = split_heading_tree(text)
        by_id = {f.canonical_id: f for f in tree.fichas}
        assert by_id["Ayagares::Descripción Física"].materialized_path == \
            "ayagares/descripcion-fisica.md"
        assert by_id["Ayagares::Descripción Física#2"].materialized_path == \
            "ayagares/descripcion-fisica-2.md"
        assert by_id["Ayagares::Descripción Física"].body == \
            "# Descripción Física\n\n## Forma Base\n\nCuerpo A."
        assert by_id["Ayagares::Descripción Física#2"].body == \
            "# Descripción Física\n\n## Forma Base\n\nCuerpo B."
