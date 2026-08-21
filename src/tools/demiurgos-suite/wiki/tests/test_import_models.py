# -*- coding: utf-8 -*-
"""World importer — Phase 1 (importador-auto-frontmatter) tests for the
analysis model contracts in import_models: canonical identity normalization,
FrontmatterCandidate/FrontmatterState, MediaDiagnostic, and the
``Candidate.canonical_id`` alias.
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

from import_models import (  # noqa: E402
    Candidate,
    FrontmatterCandidate,
    FrontmatterState,
    MediaDiagnostic,
    Provenance,
    canonical_identity_from_segments,
    normalize_identity_segment,
)


class TestCanonicalIdentityHelpers:
    def test_normalize_identity_segment_nfc_and_whitespace(self):
        assert normalize_identity_segment("  Descripción   Física ") == \
            "Descripción Física"
        assert normalize_identity_segment("café") == "café"
        assert normalize_identity_segment("Descripción Física#2") == \
            "Descripción Física#2"
        assert normalize_identity_segment("") == ""

    def test_canonical_identity_from_segments_joins_with_separator(self):
        assert canonical_identity_from_segments(
            ["Ayagares", "Descripción Física", "Forma Base"]) == \
            "Ayagares::Descripción Física::Forma Base"
        assert canonical_identity_from_segments([]) == ""


class TestAnalysisContracts:
    def test_frontmatter_candidate_contract_defaults(self):
        candidate = FrontmatterCandidate(title="Forma Base")
        assert candidate.type is None
        assert candidate.description == ""
        assert candidate.relaciones == []
        assert candidate.state == FrontmatterState.MANUAL

    def test_frontmatter_candidate_generated_state(self):
        candidate = FrontmatterCandidate(
            title="Forma Base", type="concepto", description="d",
            relaciones=["Ayagares::Descripción Física"],
            state=FrontmatterState.GENERATED,
        )
        assert candidate.state == FrontmatterState.GENERATED
        assert candidate.relaciones == ["Ayagares::Descripción Física"]

    def test_media_diagnostic_contract_defaults(self):
        diag = MediaDiagnostic(reference="![][image1]", image_key="image1")
        assert diag.status == "unresolved"
        assert diag.alt_text == ""
        assert diag.target_path == ""
        assert diag.target_ficha == ""

    def test_candidate_canonical_id_defaults_empty_for_legacy_rows(self):
        candidate = Candidate(
            candidate_id="c1", job_id="j1", world="w1",
            normalized_identity="Forma Base",
            source_hash="sha256:abc",
            provenance=Provenance(
                source_path="a.md", source_kind="loose",
                source_hash="sha256:abc"),
        )
        assert candidate.canonical_id == ""