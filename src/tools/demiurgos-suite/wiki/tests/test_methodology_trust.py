"""RED/unit tests for the methodology trust boundary.

Covers `.zip` package checksum validation, mandatory quarantine until manual
Author trust, additive official-signature verification, and the guarantee
that a failed validation produces zero side effects (no activation, no
library mutation, no canon write).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from methodology_library import MethodologyLibrary  # noqa: E402
from methodology_trust import (  # noqa: E402
    FOUNDATIONAL,
    OFFICIAL,
    PERSONALIZADAS,
    QuarantineStore,
    build_package,
    foundational_trust,
    inspect_package,
    scrub_foundational,
)


def _valid_manifest() -> dict:
    return {
        "skill_id": "guided-character-v1",
        "version": "1.2.0",
        "name": "Guided character methodology",
        "description": "A safe construction methodology.",
        "phases": ["conversation", "review", "complete"],
        "language": "es",
    }


def _valid_source() -> str:
    return "## Construcción segura\n\nHaz preguntas de a una.\n"


def _library(tmp_path: Path) -> MethodologyLibrary:
    return MethodologyLibrary(tmp_path / "library.json")


def _package():
    return build_package(_valid_manifest(), _valid_source())


def _tampered_package() -> bytes:
    package = bytearray(_package())
    # Flip the first content byte of the last entry; byte-level corruption is
    # guaranteed to change the source.md checksum.
    package[-20] ^= 0xFF
    return bytes(package)


def _signer(data: str) -> str:
    return f"sig:{data[:16]}"


def _verifier(payload: str, signature: str) -> bool:
    return signature == _signer(payload)


class TestChecksumIntegrity:
    def test_intact_package_verifies(self) -> None:
        verdict = inspect_package(_package())
        assert verdict.ok, verdict.issues
        assert verdict.checksum_valid is True
        assert verdict.compiled is not None

    def test_tampered_package_fails_checksum(self) -> None:
        verdict = inspect_package(_tampered_package())
        assert not verdict.ok
        assert verdict.checksum_valid is False
        assert verdict.compiled is None

    def test_malformed_zip_is_rejected(self) -> None:
        verdict = inspect_package(b"not-a-zip")
        assert not verdict.ok
        assert verdict.checksum_valid is False


class TestQuarantine:
    def test_import_is_quarantined_until_manual_trust(self, tmp_path: Path) -> None:
        store = QuarantineStore(tmp_path / "quarantine")
        library = _library(tmp_path)
        record = store.quarantine(_package(), library=library)
        assert record.package_id
        assert store.get(record.package_id) is not None
        # Import alone must NOT activate or publish anything.
        assert library.list_published() == []
        assert library.active_for("nec") is None

    def test_quarantine_failure_has_zero_side_effects(self, tmp_path: Path) -> None:
        store = QuarantineStore(tmp_path / "quarantine")
        library = _library(tmp_path)
        record = store.quarantine(_tampered_package(), library=library)
        assert not record.verdict.ok
        assert library.list_published() == []
        assert library.active_for("nec") is None
        assert library.list_drafts() == []

    def test_manual_trust_activates_nothing(self, tmp_path: Path) -> None:
        store = QuarantineStore(tmp_path / "quarantine")
        library = _library(tmp_path)
        record = store.quarantine(_package(), library=library)
        trusted = store.trust(record.package_id, library=library)
        assert trusted is not None
        assert trusted.verdict.ok
        # Trust yields an editable draft, never an automatic publish/activation.
        assert len(library.list_drafts()) == 1
        assert library.list_published() == []
        assert library.active_for("nec") is None

    def test_trust_fails_closed_for_corrupt_package(self, tmp_path: Path) -> None:
        store = QuarantineStore(tmp_path / "quarantine")
        library = _library(tmp_path)
        record = store.quarantine(_tampered_package(), library=library)
        trusted = store.trust(record.package_id, library=library)
        assert trusted is None
        assert library.list_drafts() == []


class TestQuarantineList:
    """Fase 5b (REQ-IMP-3): list all quarantine records with fresh verdicts."""

    def test_list_returns_all_records_with_fresh_verdicts(self, tmp_path: Path) -> None:
        store = QuarantineStore(tmp_path / "quarantine")
        assert store.list() == []
        first = store.quarantine(_package())
        second = store.quarantine(_package(), origin="local_author")
        records = store.list()
        assert {record.package_id for record in records} == {
            first.package_id, second.package_id,
        }
        by_id = {record.package_id: record for record in records}
        assert by_id[first.package_id].verdict.ok
        assert by_id[first.package_id].clasificacion == "Comunitarias"
        assert by_id[first.package_id].trusted is False
        assert by_id[second.package_id].clasificacion == "Personalizadas"

    def test_list_reinspects_tampered_package_on_disk(self, tmp_path: Path) -> None:
        store = QuarantineStore(tmp_path / "quarantine")
        record = store.quarantine(_package())
        # Tamper the stored .zip on disk: list() must re-inspect and fail
        # closed (the quarantine review is never a stale cached verdict).
        package_path = tmp_path / "quarantine" / f"{record.package_id}.zip"
        raw = bytearray(package_path.read_bytes())
        raw[-20] ^= 0xFF
        package_path.write_bytes(bytes(raw))
        loaded = store.list()[0]
        assert loaded.package_id == record.package_id
        assert loaded.verdict.ok is False
        assert loaded.verdict.checksum_valid is False

    def test_list_exposes_trusted_draft_id(self, tmp_path: Path) -> None:
        store = QuarantineStore(tmp_path / "quarantine")
        library = _library(tmp_path)
        record = store.quarantine(_package(), library=library)
        trusted = store.trust(record.package_id, library=library)
        assert trusted is not None
        assert trusted.draft_id is not None
        loaded = store.list()[0]
        assert loaded.trusted is True
        assert loaded.draft_id == trusted.draft_id


class TestOfficialSignature:
    def test_signature_is_additive_layer(self) -> None:
        package = build_package(_valid_manifest(), _valid_source(), signer=_signer)
        verdict = inspect_package(package, verifier=_verifier)
        assert verdict.ok
        assert verdict.signature_valid is True

    def test_invalid_official_signature_fails_closed(self) -> None:
        package = build_package(_valid_manifest(), _valid_source(), signer=_signer)
        verdict = inspect_package(package, verifier=lambda _payload, _sig: False)
        assert not verdict.ok
        assert verdict.signature_valid is False

    def test_no_signature_is_still_trusted_by_checksum(self) -> None:
        verdict = inspect_package(_package())
        assert verdict.ok
        assert verdict.signature_present is False


class TestInventoryClassification:
    """Taller de Herramientas Fase 1: system-derived classification + trust
    attributes computed at quarantine/trust and threaded into drafts."""

    def test_signed_package_is_classified_oficiales(self, tmp_path: Path) -> None:
        store = QuarantineStore(tmp_path / "quarantine")
        package = build_package(_valid_manifest(), _valid_source(), signer=_signer)
        record = store.quarantine(package, verifier=_verifier)
        assert record.clasificacion == "Oficiales"
        assert record.trust_attributes == ("verified", "quarantined")

    def test_unsigned_local_author_is_personalizadas(self, tmp_path: Path) -> None:
        store = QuarantineStore(tmp_path / "quarantine")
        record = store.quarantine(_package(), origin="local_author")
        assert record.clasificacion == "Personalizadas"
        assert record.trust_attributes == ("quarantined",)

    def test_unsigned_community_is_comunitarias(self, tmp_path: Path) -> None:
        store = QuarantineStore(tmp_path / "quarantine")
        record = store.quarantine(_package(), origin="community")
        assert record.clasificacion == "Comunitarias"
        assert record.trust_attributes == ("quarantined",)

    def test_classification_survives_get_from_disk(self, tmp_path: Path) -> None:
        store = QuarantineStore(tmp_path / "quarantine")
        record = store.quarantine(_package(), origin="local_author")
        loaded = store.get(record.package_id)
        assert loaded is not None
        assert loaded.clasificacion == "Personalizadas"
        assert loaded.trust_attributes == ("quarantined",)

    def test_trust_removes_quarantined_and_threads_to_draft(self, tmp_path: Path) -> None:
        store = QuarantineStore(tmp_path / "quarantine")
        library = _library(tmp_path)
        record = store.quarantine(_package(), library=library, origin="community")
        trusted = store.trust(record.package_id, library=library)
        assert trusted is not None
        assert trusted.trusted is True
        assert trusted.clasificacion == "Comunitarias"
        assert trusted.trust_attributes == ()  # trusted + unsigned: no markers
        drafts = library.list_drafts()
        assert len(drafts) == 1
        assert drafts[0].clasificacion == "Comunitarias"
        assert drafts[0].trust_attributes == ()
        assert drafts[0].taller is None  # manifest carried no inventory fields

    def test_trust_signed_package_keeps_verified(self, tmp_path: Path) -> None:
        store = QuarantineStore(tmp_path / "quarantine")
        library = _library(tmp_path)
        package = build_package(_valid_manifest(), _valid_source(), signer=_signer)
        record = store.quarantine(package, library=library, verifier=_verifier)
        trusted = store.trust(record.package_id, library=library, verifier=_verifier)
        assert trusted is not None
        assert trusted.clasificacion == "Oficiales"
        assert trusted.trust_attributes == ("verified",)
        drafts = library.list_drafts()
        assert len(drafts) == 1
        assert drafts[0].clasificacion == "Oficiales"
        assert drafts[0].trust_attributes == ("verified",)

    def test_trust_threads_inventory_fields_into_draft(self, tmp_path: Path) -> None:
        store = QuarantineStore(tmp_path / "quarantine")
        library = _library(tmp_path)
        manifest = dict(
            _valid_manifest(),
            taller="Creación",
            talleres_compatibles=["Investigación"],
            categoria_funcional="Análisis",
            etiquetas=["lore", "npc"],
        )
        package = build_package(manifest, _valid_source())
        record = store.quarantine(package, library=library)
        trusted = store.trust(record.package_id, library=library)
        assert trusted is not None
        assert trusted.clasificacion == "Comunitarias"
        draft = library.list_drafts()[0]
        assert draft.taller == "Creación"
        assert draft.talleres_compatibles == ("Investigación",)
        assert draft.categoria_funcional == "Análisis"
        assert draft.etiquetas == ("lore", "npc")


class TestServerTrustOrigin:
    """S12: classification values and trust attributes originate ONLY here.

    ``methodology_trust`` is the sole origin of server trust — constants are
    pinned, ``foundational_trust`` yields the canonical Oficiales+fundacional
    pair, and ``scrub_foundational`` strips the marker while keeping other
    attributes (e.g. ``verified``).
    """

    def test_constants_are_pinned(self) -> None:
        assert OFFICIAL == "Oficiales"
        assert PERSONALIZADAS == "Personalizadas"
        assert FOUNDATIONAL == "fundacional"

    def test_foundational_trust_returns_canonical_pair(self) -> None:
        assert foundational_trust() == ("Oficiales", ("fundacional",))

    def test_scrub_foundational_keeps_other_attributes(self) -> None:
        assert scrub_foundational(("fundacional", "verified")) == ("verified",)
        assert scrub_foundational(("verified",)) == ("verified",)
        assert scrub_foundational(()) == ()

    def test_scrub_foundational_never_invents_attributes(self) -> None:
        assert scrub_foundational(("fundacional",)) == ()
        assert "fundacional" not in scrub_foundational(("fundacional",))
