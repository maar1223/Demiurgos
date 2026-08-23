# -*- coding: utf-8 -*-
"""World importer — Phase 1 (importador-auto-frontmatter) tests for the
deterministic H1-H5 tree splitter: H1-H5 nesting, canonical parent-qualified
identities, empty-scaffold preservation, childless prose folding, repeated-
title ordinals, the Hermes structure-inference fallback seam, and
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
        """Nested H1-H5 produce parent-qualified ficha ids in source order."""
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
        # H5 ``Manos`` cannot have children (levels cap at 5) so it folds
        # verbatim into its H4 parent ficha instead of becoming a node.
        root = tree.fichas[0]
        assert root.level == 1 and root.source_order == 0
        assert root.children[0].title == "Descripción Física"
        extremidades = tree.fichas[-1]
        assert extremidades.level == 4
        assert extremidades.body == "##### Manos\n\nCinco dedos."
        assert extremidades.children == []

    def test_empty_h1_scaffold_is_preserved(self):
        """An empty H1 remains a valid root/index ficha, never dropped."""
        tree = split_heading_tree("# Vacía\n\n# Llena\n\nContenido.\n")
        assert [f.canonical_id for f in tree.fichas] == ["Vacía", "Llena"]
        vacia, llena = tree.fichas
        assert vacia.body == ""
        assert vacia.level == 1 and vacia.is_ficha
        assert llena.body == "Contenido."

    def test_childless_prose_folds_into_parent_ficha(self):
        """Childless headings fold (verbatim, heading included) into the
        parent ficha instead of being discarded or emitted empty."""
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
        # Sociedad (childless H2) folds into Ayagares; Forma Base (childless
        # H3) folds into Descripción Física. Neither is emitted as a ficha.
        assert [f.canonical_id for f in tree.fichas] == [
            "Ayagares", "Ayagares::Descripción Física",
        ]
        ayagares, df = tree.fichas
        assert "Intro del mundo." in ayagares.body
        assert "## Sociedad" in ayagares.body
        assert "Sin hijos." in ayagares.body
        assert "Prosa directa." in df.body
        assert "### Forma Base" in df.body
        assert "Cuerpo y extremidades." in df.body

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
        assert tree.fichas[0].body == "Cuerpo."


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
        assert [f.canonical_id for f in tree.fichas] == [
            "Ayagares",
            "Ayagares::Descripción Física",
            "Ayagares::Descripción Física::Forma Base",
            "Ayagares::Descripción Física#2",
            "Ayagares::Descripción Física#2::Forma Base",
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
        assert tree.fichas[0].body == "Texto plano."


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
        # ``## Sociedad`` is childless, so both spans live in Ayagares' body.
        diagnostics = tree.fichas[0].media_diagnostics
        assert len(diagnostics) == 2
        by_key = {d.image_key: d for d in diagnostics}
        assert by_key["image1"].reference == "![][image1]"
        assert by_key["image1"].status == "unresolved"
        assert by_key["image1"].target_ficha == "Ayagares"
        assert "no definition" in by_key["image1"].message
        assert by_key["image2"].alt_text == "portada"
        assert by_key["image2"].status == "unresolved"

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
