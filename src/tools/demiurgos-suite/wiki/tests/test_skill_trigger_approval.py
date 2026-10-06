"""Unit tests for the trigger-approval model and ``approve_trigger``.

Etapa 2, WU 2.1a (PR 1). Covers the persisted/auditable approval record for a
skill trigger (the authored ``description``): the normalized text, its digest,
the approver identity and timestamp; whitespace-insensitive digests; the
authored intake bound (<= ``TRIGGER_INTAKE_LIMIT``) enforced server-side;
refusal of empty/whitespace-only and over-bound values; the record remaining
distinct from a later draft-description edit; and tolerant reads of records
that predate the additive field.

Hermetic ``tmp_path`` library; no runtime surface (no HTTP/process boundary).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from methodology_library import (  # noqa: E402
    TRIGGER_INTAKE_LIMIT,
    MethodologyLibrary,
    MethodologyLibraryError,
    TriggerApproval,
    TriggerInvalidError,
    TriggerNotApprovedError,
    ValidationError,
    normalize_trigger,
    normalized_trigger_digest,
)


def _library(tmp_path: Path) -> MethodologyLibrary:
    return MethodologyLibrary(tmp_path / "library.json")


def _draft(
    library: MethodologyLibrary,
    description: str = "Un gatillo de ejemplo",
) -> str:
    return library.create_draft(
        skill_id="guided-character-v1",
        version="1.2.0",
        name="Guided character methodology",
        source="## Construcción segura\n\nHaz preguntas de a una.\n",
        description=description,
    )


class TestErrorTaxonomy:
    def test_gate_error_is_a_library_error(self) -> None:
        # TD-D: the publish gate refusal must stay a MethodologyLibraryError so
        # the API can catch it before the generic handler.
        assert issubclass(TriggerNotApprovedError, MethodologyLibraryError)

    def test_invalid_error_is_a_validation_error(self) -> None:
        assert issubclass(TriggerInvalidError, ValidationError)

    def test_authored_bound_mirrors_the_renderer(self) -> None:
        assert TRIGGER_INTAKE_LIMIT == 60


class TestNormalization:
    def test_normalize_collapses_and_strips(self) -> None:
        assert normalize_trigger("  foo \t bar\n\nbaz ") == "foo bar baz"

    def test_digest_is_sha256_of_the_normalized_text(self) -> None:
        import hashlib

        expected = hashlib.sha256(b"foo bar").hexdigest()
        assert normalized_trigger_digest("  foo   bar  ") == expected

    def test_whitespace_variants_share_one_digest(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        first = library.approve_trigger(_draft(library), "foo   bar", "author")
        second = library.approve_trigger(_draft(library), " foo\tbar ", "author")
        assert first.digest == second.digest
        assert first.text == second.text == "foo bar"


class TestApprovalRecord:
    def test_record_carries_audit_fields(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        draft_id = _draft(library, description="placeholder")

        approval = library.approve_trigger(
            draft_id, "  Aprueba este gatillo  ", "author-7"
        )

        assert isinstance(approval, TriggerApproval)
        assert approval.text == "Aprueba este gatillo"
        assert approval.digest == normalized_trigger_digest("Aprueba este gatillo")
        assert approval.approved_by == "author-7"
        assert approval.approved_at  # non-empty ISO-8601 timestamp

        draft = library.get_draft(draft_id)
        assert draft is not None
        assert draft.trigger_approval == approval
        # TD-B: the approved value is written as the draft description in the
        # same locked write.
        assert draft.description == "Aprueba este gatillo"

    def test_record_persists_across_reload(self, tmp_path: Path) -> None:
        path = tmp_path / "library.json"
        library = MethodologyLibrary(path)
        draft_id = _draft(library, description="placeholder")
        approval = library.approve_trigger(draft_id, "gatillo persistido", "author-1")

        reloaded = MethodologyLibrary(path)
        draft = reloaded.get_draft(draft_id)
        assert draft is not None
        assert draft.trigger_approval == approval

    def test_within_bound_is_accepted_verbatim(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        exact = "x" * TRIGGER_INTAKE_LIMIT
        approval = library.approve_trigger(_draft(library), exact, "author")
        assert approval.text == exact
        assert len(approval.text) == TRIGGER_INTAKE_LIMIT

    def test_value_within_render_bound_survives_verbatim(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        value = "Gatillo de prueba"
        approval = library.approve_trigger(_draft(library), value, "author")
        assert approval.text == value


class TestBoundEnforcement:
    @pytest.mark.parametrize("bad", ["", "   ", "\t\n "])
    def test_empty_or_whitespace_is_refused(
        self, tmp_path: Path, bad: str
    ) -> None:
        library = _library(tmp_path)
        draft_id = _draft(library, description="original")
        with pytest.raises(TriggerInvalidError):
            library.approve_trigger(draft_id, bad, "author")
        draft = library.get_draft(draft_id)
        assert draft is not None
        assert draft.trigger_approval is None
        assert draft.description == "original"

    def test_over_bound_is_refused(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        draft_id = _draft(library, description="original")
        with pytest.raises(TriggerInvalidError):
            library.approve_trigger(
                draft_id, "x" * (TRIGGER_INTAKE_LIMIT + 1), "author"
            )
        draft = library.get_draft(draft_id)
        assert draft is not None
        assert draft.trigger_approval is None
        assert draft.description == "original"

    def test_server_bound_is_authoritative_over_the_client(
        self, tmp_path: Path
    ) -> None:
        # Simulates a client that ignored the mirrored client-side bound and
        # submitted an over-bound value directly to the server API surface.
        library = _library(tmp_path)
        draft_id = _draft(library, description="original")
        with pytest.raises(TriggerInvalidError):
            library.approve_trigger(draft_id, "y" * 200, "author")
        draft = library.get_draft(draft_id)
        assert draft is not None
        assert draft.trigger_approval is None

    def test_unknown_draft_raises_keyerror(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        with pytest.raises(KeyError):
            library.approve_trigger("missing", "valid trigger", "author")


class TestDistinctnessFromDraftDescription:
    def test_later_description_edit_does_not_mutate_the_approval(
        self, tmp_path: Path
    ) -> None:
        library = _library(tmp_path)
        draft_id = _draft(library, description="placeholder")
        approval = library.approve_trigger(draft_id, "gatillo original", "author")

        library.update_draft(draft_id, description="Un gatillo distinto")

        draft = library.get_draft(draft_id)
        assert draft is not None
        assert draft.description == "Un gatillo distinto"
        assert draft.trigger_approval == approval
        assert draft.trigger_approval is not None
        assert draft.trigger_approval.text == "gatillo original"

    def test_approval_does_not_change_the_compiled_digest(
        self, tmp_path: Path
    ) -> None:
        library = _library(tmp_path)
        plain = _draft(library, description="Gatillo coincidente")
        approved = _draft(library, description="placeholder")
        library.approve_trigger(approved, "Gatillo coincidente", "author")

        plain_digest = library.compile_draft(plain).compiled.digest
        approved_digest = library.compile_draft(approved).compiled.digest
        # Same description both sides; the additive trigger_approval field is
        # metadata and must not enter the identity digest.
        assert library.get_draft(approved).description == "Gatillo coincidente"
        assert plain_digest == approved_digest


class TestTolerantRead:
    def test_unapproved_draft_reads_none(self, tmp_path: Path) -> None:
        library = _library(tmp_path)
        draft = library.get_draft(_draft(library))
        assert draft is not None
        assert draft.trigger_approval is None

    def test_published_record_without_provenance_reads_none(
        self, tmp_path: Path
    ) -> None:
        library = _library(tmp_path)
        library.publish(_draft(library))
        published = library.get_published("guided-character-v1", "1.2.0")
        assert published is not None
        assert published.trigger_approval is None

    def test_old_records_without_the_field_deserialize(self, tmp_path: Path) -> None:
        # Pre-Etapa-2 store: neither the draft nor the published record carries
        # ``trigger_approval``. Both read paths must tolerate its absence.
        path = tmp_path / "library.json"
        path.write_text(
            json.dumps(
                {
                    "drafts": {
                        "old-draft": {
                            "draft_id": "old-draft",
                            "skill_id": "legacy-skill",
                            "version": "1.0.0",
                            "name": "Legacy draft",
                            "source": "## Legacy\n",
                            "description": "Legacy trigger",
                        }
                    },
                    "published": {
                        "legacy-skill@1.0.0": {
                            "skill_id": "legacy-skill",
                            "version": "1.0.0",
                            "name": "Legacy published",
                            "source": "## Legacy\n",
                            "description": "Legacy trigger",
                            "digest": "deadbeef",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        library = MethodologyLibrary(path)
        draft = library.get_draft("old-draft")
        assert draft is not None
        assert draft.trigger_approval is None
        published = library.get_published("legacy-skill", "1.0.0")
        assert published is not None
        assert published.trigger_approval is None
