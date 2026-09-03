"""Methodology package trust boundary — `.zip` import/export.

A methodology package is a `.zip` archive with a bounded layout:

- ``manifest.yaml`` — the bounded manifest.
- ``source.md`` — the methodology Markdown source.
- ``checksums.json`` — declared SHA-256 checksums of ``manifest.yaml`` and
  ``source.md`` (the integrity layer, always required).
- ``signature`` — an optional *official* digital signature over the checksum
  manifest. It is an **additive** trust layer: when present it is verified
  against the official verifier and fails closed on mismatch; when absent the
  package is still importable after checksum + compiler validation.

Imports are **always quarantined**. Nothing is activated or published by the
act of importing. A human Author must explicitly ``trust`` a quarantined
package; trusting validates the archive again and only then surfaces it as an
editable draft. Failed validation produces zero side effects: no activation,
no publish, no library mutation, no canon write.

Third-party / community trust chains are deliberately OUT OF SCOPE for the
Core: trust is manual and Author-owned. No unofficial signing authority is
invented here.
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

import yaml

from methodology_compiler import CompiledMethodology, compile_methodology

_MANIFEST_NAME = "manifest.yaml"
_SOURCE_NAME = "source.md"
_CHECKSUMS_NAME = "checksums.json"
_SIGNATURE_NAME = "signature"

_ALLOWED_ENTRIES = frozenset({_MANIFEST_NAME, _SOURCE_NAME, _CHECKSUMS_NAME, _SIGNATURE_NAME})


@dataclass(frozen=True)
class PackageVerdict:
    """Result of inspecting a `.zip` methodology package."""

    ok: bool
    checksum_valid: bool
    signature_present: bool
    signature_valid: bool | None
    issues: tuple[str, ...]
    compiled: CompiledMethodology | None = None


@dataclass(frozen=True)
class QuarantineRecord:
    package_id: str
    verdict: PackageVerdict
    trusted: bool = False
    # System-derived inventory metadata (Taller de Herramientas, Fase 1):
    # computed server-side, never author-claimed.
    clasificacion: str | None = None
    trust_attributes: tuple[str, ...] = ()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# System-derived classification + trust attributes (TW5)
#
# ``clasificacion`` and trust attributes are ALWAYS computed server-side from
# signature + origin; a manifest can never claim them (the compiler rejects
# ``clasificacion`` as unknown and ``trust`` as kernel-owned).
# ---------------------------------------------------------------------------


def _derive_clasificacion(verdict: PackageVerdict, origin: str) -> str:
    """Derive the classification from signature validity + import origin.

    - Valid official Demiurgos signature → ``Oficiales``.
    - Author-created draft (no signature, local author) → ``Personalizadas``.
    - Community import without an official signature → ``Comunitarias``.
    """
    if verdict.signature_valid:
        return "Oficiales"
    if origin == "local_author":
        return "Personalizadas"
    return "Comunitarias"


def _derive_trust_attributes(verdict: PackageVerdict, trusted: bool) -> tuple[str, ...]:
    """Derive trust attributes from package state.

    ``verified`` tracks an official signature; ``quarantined`` tracks the
    mandatory pre-trust state. ``fundamental``/``derived``/``co-created`` are
    reserved for later phases.
    """
    attributes: list[str] = []
    if verdict.signature_valid:
        attributes.append("verified")
    if not trusted:
        attributes.append("quarantined")
    return tuple(attributes)


# ---------------------------------------------------------------------------
# Package building (export)
# ---------------------------------------------------------------------------


def build_package(
    manifest: Mapping,
    source: str,
    signer: Callable[[str], str] | None = None,
) -> bytes:
    """Build a `.zip` methodology package from a manifest + Markdown source.

    ``signer`` is an optional official-signature callback: given the canonical
    checksum manifest text it returns a signature string stored as the
    ``signature`` entry (additive layer).
    """
    manifest_bytes = yaml.safe_dump(
        dict(manifest), sort_keys=False, allow_unicode=True,
    ).encode("utf-8")
    source_bytes = source.encode("utf-8")

    checksums = {
        _MANIFEST_NAME: _sha256(manifest_bytes),
        _SOURCE_NAME: _sha256(source_bytes),
    }
    checksum_text = json.dumps(checksums, sort_keys=True, separators=(",", ":"))

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(_MANIFEST_NAME, manifest_bytes)
        archive.writestr(_SOURCE_NAME, source_bytes)
        archive.writestr(_CHECKSUMS_NAME, checksum_text)
        if signer is not None:
            archive.writestr(_SIGNATURE_NAME, signer(checksum_text))
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Package inspection (import validation)
# ---------------------------------------------------------------------------


def inspect_package(
    data: bytes,
    verifier: Callable[[str, str], bool] | None = None,
) -> PackageVerdict:
    """Validate a `.zip` package: integrity checksum + optional signature + compiler.

    ``verifier(payload, signature)`` verifies the *official* signature
    (additive). When a signature is present and no verifier is supplied the
    package fails closed. Absent signature is accepted.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError):
        return PackageVerdict(False, False, False, None, ("Not a valid zip archive.",))

    names = set(archive.namelist())
    if not names or not names.issubset(_ALLOWED_ENTRIES):
        return PackageVerdict(
            False, False, False, None,
            (f"Package contains unexpected entries: {sorted(names)}.",),
        )

    try:
        manifest_text = archive.read(_MANIFEST_NAME).decode("utf-8")
        source_text = archive.read(_SOURCE_NAME).decode("utf-8")
        checksum_text = archive.read(_CHECKSUMS_NAME).decode("utf-8")
    except (KeyError, UnicodeDecodeError):
        return PackageVerdict(
            False, False, False, None,
            ("Package is missing required entries or is not valid UTF-8.",),
        )
    signature_text = None
    if _SIGNATURE_NAME in names:
        try:
            signature_text = archive.read(_SIGNATURE_NAME).decode("utf-8")
        except (KeyError, UnicodeDecodeError):
            return PackageVerdict(
                False, False, True, None,
                ("Package signature entry is not valid UTF-8.",),
            )

    issues: list[str] = []
    try:
        declared = json.loads(checksum_text)
    except json.JSONDecodeError:
        declared = None
    checksum_valid = False
    if isinstance(declared, dict):
        expected = {
            name: str(declared.get(name, "")) if declared.get(name) is not None else ""
            for name in (_MANIFEST_NAME, _SOURCE_NAME)
        }
        actual = {
            _MANIFEST_NAME: _sha256(archive.read(_MANIFEST_NAME)),
            _SOURCE_NAME: _sha256(archive.read(_SOURCE_NAME)),
        }
        checksum_valid = (
            bool(expected[_MANIFEST_NAME] and expected[_SOURCE_NAME])
            and expected == actual
        )
    if not checksum_valid:
        issues.append("Integrity checksum mismatch: the package content was modified.")

    signature_present = signature_text is not None
    signature_valid: bool | None = None
    if signature_present:
        if verifier is None:
            signature_valid = False
            issues.append("Official signature present but no verifier is configured.")
        elif verifier(checksum_text, signature_text):
            signature_valid = True
        else:
            signature_valid = False
            issues.append("Official signature verification failed.")

    manifest = None
    if _MANIFEST_NAME in names:
        try:
            parsed = yaml.safe_load(manifest_text)
        except yaml.YAMLError:
            parsed = None
        manifest = parsed if isinstance(parsed, dict) else None

    compiled = None
    compiler_issues: list[str] = []
    if manifest is not None and checksum_valid:
        result = compile_methodology(manifest, source_text)
        if result.ok and result.compiled is not None:
            compiled = result.compiled
        else:
            compiler_issues = [issue.message for issue in result.issues]

    ok = (
        checksum_valid
        and signature_valid is not False
        and manifest is not None
        and compiled is not None
    )
    if manifest is None and not issues:
        issues.append("Manifest is missing or malformed.")
    issues.extend(compiler_issues)
    return PackageVerdict(
        ok=ok,
        checksum_valid=checksum_valid,
        signature_present=signature_present,
        signature_valid=signature_valid,
        issues=tuple(issues),
        compiled=compiled,
    )


# ---------------------------------------------------------------------------
# Quarantine store
# ---------------------------------------------------------------------------


class QuarantineStore:
    """Mandatory-quarantine store for imported methodology packages.

    Importing only stores the package and its verdict; nothing is published or
    activated. ``trust`` re-validates and, only for a valid package, surfaces
    it as an editable draft in the library.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def quarantine(
        self,
        data: bytes,
        library=None,
        name: str = "",
        origin: str = "community",
        verifier: Callable[[str, str], bool] | None = None,
    ) -> QuarantineRecord:
        """Quarantine an imported package.

        ``library`` is accepted for future validation hooks but is NEVER
        mutated by importing. ``origin`` (``community`` default |
        ``local_author``) and ``verifier`` feed the system-derived
        classification + trust attributes. Failed packages stay quarantined
        with zero side effects.
        """
        del library  # imports never mutate the library
        verdict = inspect_package(data, verifier=verifier)
        package_id = uuid.uuid4().hex[:12]
        clasificacion = _derive_clasificacion(verdict, origin)
        trust_attributes = _derive_trust_attributes(verdict, trusted=False)
        self._root.mkdir(parents=True, exist_ok=True)
        (self._root / f"{package_id}.zip").write_bytes(data)
        (self._root / f"{package_id}.json").write_text(json.dumps({
            "package_id": package_id,
            "name": name,
            "origin": origin,
            "imported_at": _utcnow(),
            "ok": verdict.ok,
            "checksum_valid": verdict.checksum_valid,
            "signature_present": verdict.signature_present,
            "signature_valid": verdict.signature_valid,
            "issues": list(verdict.issues),
            "clasificacion": clasificacion,
            "trust_attributes": list(trust_attributes),
        }, ensure_ascii=False), encoding="utf-8")
        return QuarantineRecord(
            package_id=package_id,
            verdict=verdict,
            clasificacion=clasificacion,
            trust_attributes=trust_attributes,
        )

    def get(self, package_id: str) -> QuarantineRecord | None:
        record_path = self._root / f"{package_id}.json"
        if not record_path.exists():
            return None
        try:
            with open(record_path, encoding="utf-8") as handle:
                meta = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return None
        data = (self._root / f"{package_id}.zip").read_bytes()
        return QuarantineRecord(
            package_id=package_id,
            verdict=inspect_package(data),
            trusted=bool(meta.get("trusted")),
            clasificacion=meta.get("clasificacion"),
            trust_attributes=tuple(meta.get("trust_attributes") or ()),
        )

    def trust(self, package_id: str, library=None, verifier: Callable[[str, str], bool] | None = None):
        """Manually trust a quarantined package.

        Only a package that re-validates (checksum + optional official
        signature + compiler) is surfaced as an **editable draft**. Returns a
        ``QuarantineRecord`` on success (or ``None`` on failure); never
        publishes or activates automatically.
        """
        record_path = self._root / f"{package_id}.json"
        package_path = self._root / f"{package_id}.zip"
        if not record_path.exists() or not package_path.exists():
            return None
        data = package_path.read_bytes()
        verdict = inspect_package(data, verifier=verifier)
        if not verdict.ok or verdict.compiled is None:
            return None
        meta = json.loads(record_path.read_text(encoding="utf-8"))
        origin = meta.get("origin", "community")
        clasificacion = _derive_clasificacion(verdict, origin)
        trust_attributes = _derive_trust_attributes(verdict, trusted=True)
        draft_id = None
        if library is not None:
            compiled = verdict.compiled
            draft_id = library.create_draft(
                skill_id=compiled.skill_id,
                version=compiled.version,
                name=compiled.name,
                source=compiled.source,
                description=compiled.description,
                phases=tuple(compiled.phases),
                language=compiled.language,
                taller=compiled.taller,
                talleres_compatibles=tuple(compiled.talleres_compatibles),
                categoria_funcional=compiled.categoria_funcional,
                etiquetas=tuple(compiled.etiquetas),
                clasificacion=clasificacion,
                trust_attributes=trust_attributes,
            )
        meta["trusted"] = True
        meta["draft_id"] = draft_id
        meta["clasificacion"] = clasificacion
        meta["trust_attributes"] = list(trust_attributes)
        with open(record_path, "w", encoding="utf-8") as handle:
            json.dump(meta, handle, ensure_ascii=False)
        return QuarantineRecord(
            package_id=package_id,
            verdict=verdict,
            trusted=True,
            clasificacion=clasificacion,
            trust_attributes=trust_attributes,
        )
