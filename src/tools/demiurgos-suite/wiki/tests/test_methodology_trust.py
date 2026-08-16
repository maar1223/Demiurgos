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
    QuarantineStore,
    build_package,
    inspect_package,
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
