"""Methodology package trust boundary — `.zip` import/export.

A methodology package is a `.zip` archive with a bounded layout:

- ``manifest.yaml`` — the bounded manifest.
- ``source.md`` — the methodology Markdown source.
- ``checksums.json`` — declared SHA-256 checksums of ``manifest.yaml``,
  ``source.md``, and every attached carrier (the integrity layer, always
  required).
- zero or more **carrier** entries — pinned attachment Markdown files declared
  by the manifest's ``adjuntos``, stored at their package-relative paths. The
  allowed entry set is the static base set plus these declared carriers.
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
import os
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

import yaml

from methodology_compiler import (
    CompiledMethodology,
    _RESERVED_ATTACHMENT_PREFIXES,
    compile_methodology,
)

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
    # Draft promoted by ``trust`` (REQ-IMP-4); None while still quarantined.
    draft_id: str | None = None


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
    mandatory pre-trust state. ``fundacional``/``derived``/``co-created`` are
    reserved for later phases.
    """
    attributes: list[str] = []
    if verdict.signature_valid:
        attributes.append("verified")
    if not trusted:
        attributes.append("quarantined")
    return tuple(attributes)


# ---------------------------------------------------------------------------
# Server-authoritative trust values (sole origin)
#
# ``clasificacion`` values and trust attributes are SERVER-ONLY: no client
# request, manifest, or import path may set them. They originate exclusively
# here (S12). Two-axis invariant (G14): every ``fundacional`` skill is also
# ``Oficiales``, but ``Oficiales`` skills need not be ``fundacional``.
# ---------------------------------------------------------------------------

OFFICIAL = "Oficiales"
PERSONALIZADAS = "Personalizadas"
FOUNDATIONAL = "fundacional"


def foundational_trust() -> tuple[str, tuple[str, ...]]:
    """Return the classification + trust attributes of a foundational skill.

    The sole origin of server trust for seeded skills: ``("Oficiales",
    ("fundacional",))``. Only server install paths may use it; no client or
    manifest path may claim these values.
    """
    return (OFFICIAL, (FOUNDATIONAL,))


def scrub_foundational(trust: tuple[str, ...]) -> tuple[str, ...]:
    """Return ``trust`` without the ``fundacional`` attribute.

    Applied when deriving from a foundational skill: a fork is local
    authorship, so it keeps other inherited attributes (e.g. ``verified``)
    but never the foundational marker.
    """
    return tuple(attribute for attribute in trust if attribute != FOUNDATIONAL)


# ---------------------------------------------------------------------------
# Package building (export)
# ---------------------------------------------------------------------------


def build_package(
    manifest: Mapping,
    source: str,
    signer: Callable[[str], str] | None = None,
    attachments: Mapping[str, bytes] | None = None,
) -> bytes:
    """Build a `.zip` methodology package from a manifest + Markdown source.

    ``signer`` is an optional official-signature callback: given the canonical
    checksum manifest text it returns a signature string stored as the
    ``signature`` entry (additive layer).

    ``attachments`` optionally embeds pinned carrier bytes at their
    package-relative paths (D4). Each carrier joins ``checksums.json``
    alongside the manifest and source, so an optional signature covers the
    carriers too. ``None`` (the default) reproduces the pre-attachment package
    byte-for-byte, keeping every existing caller source-compatible.
    """
    manifest_bytes = yaml.safe_dump(
        dict(manifest), sort_keys=False, allow_unicode=True,
    ).encode("utf-8")
    source_bytes = source.encode("utf-8")
    carriers = {
        str(path): bytes(data) for path, data in (attachments or {}).items()
    }

    checksums = {
        _MANIFEST_NAME: _sha256(manifest_bytes),
        _SOURCE_NAME: _sha256(source_bytes),
        **{path: _sha256(data) for path, data in carriers.items()},
    }
    checksum_text = json.dumps(checksums, sort_keys=True, separators=(",", ":"))

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(_MANIFEST_NAME, manifest_bytes)
        archive.writestr(_SOURCE_NAME, source_bytes)
        for path, data in carriers.items():
            archive.writestr(path, data)
        archive.writestr(_CHECKSUMS_NAME, checksum_text)
        if signer is not None:
            archive.writestr(_SIGNATURE_NAME, signer(checksum_text))
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Package inspection (import validation)
# ---------------------------------------------------------------------------


def _derived_adjunto_entries(
    manifest: Mapping,
) -> tuple[tuple[Mapping, ...] | None, str | None]:
    """Derive the strictly-valid declared adjunto entries from a manifest (D1).

    Returns ``(entries, None)`` on success — an empty tuple when the manifest
    declares no attachments — or ``(None, issue)`` when the declaration shape
    or any declared path is invalid. Every path must be a non-empty
    package-relative ``.md`` that stays inside the package: no absolute path,
    no ``..`` component, no reserved ``mundos/``/``referencias/`` prefix, and
    no collision with a base package entry (``source.md`` is the only reachable
    one). The allowlist is derived from this declaration, never assumed.
    """
    raw = manifest.get("adjuntos")
    if raw is None:
        return (), None
    if not isinstance(raw, list) or not all(isinstance(entry, Mapping) for entry in raw):
        return None, "Manifest adjuntos is malformed."
    for entry in raw:
        path = entry.get("path")
        if (
            not isinstance(path, str)
            or not path
            or path.startswith("/")
            or not path.endswith(".md")
            or ".." in Path(path).parts
            or path.startswith(_RESERVED_ATTACHMENT_PREFIXES)
            or path in _ALLOWED_ENTRIES
        ):
            return None, f"Package declares an invalid attachment path {path!r}."
    return tuple(raw), None


def inspect_package(
    data: bytes,
    verifier: Callable[[str, str], bool] | None = None,
) -> PackageVerdict:
    """Validate a `.zip` package: integrity checksum + optional signature + compiler.

    ``verifier(payload, signature)`` verifies the *official* signature
    (additive). When a signature is present and no verifier is supplied the
    package fails closed. Absent signature is accepted.

    Validation order (D1): the manifest is parsed FIRST so the allowed entry set
    can be derived from its declared ``adjuntos`` — the static base set plus
    every strictly-valid declared carrier. Each declared carrier must then exist
    and re-verify against its ``sha256``/``bytes`` pin (and its ``checksums.json``
    binding when present). Packages without adjuntos behave as before.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError):
        return PackageVerdict(False, False, False, None, ("Not a valid zip archive.",))

    names = set(archive.namelist())
    if not names:
        return PackageVerdict(
            False, False, False, None,
            (f"Package contains unexpected entries: {sorted(names)}.",),
        )

    try:
        manifest_text = archive.read(_MANIFEST_NAME).decode("utf-8")
    except (KeyError, UnicodeDecodeError):
        return PackageVerdict(
            False, False, False, None,
            ("Package is missing required entries or is not valid UTF-8.",),
        )

    try:
        parsed_manifest = yaml.safe_load(manifest_text)
    except yaml.YAMLError:
        parsed_manifest = None
    manifest = parsed_manifest if isinstance(parsed_manifest, dict) else None
    if manifest is None:
        return PackageVerdict(
            False, False, False, None, ("Manifest is missing or malformed.",),
        )

    adjunto_entries, declared_issue = _derived_adjunto_entries(manifest)
    if declared_issue is not None:
        return PackageVerdict(False, False, False, None, (declared_issue,))
    assert adjunto_entries is not None  # declared_issue is None
    declared_paths = tuple(str(entry["path"]) for entry in adjunto_entries)

    allowed = _ALLOWED_ENTRIES | set(declared_paths)
    if not names.issubset(allowed):
        return PackageVerdict(
            False, False, False, None,
            (f"Package contains unexpected entries: {sorted(names)}.",),
        )
    for path in declared_paths:
        if path not in names:
            return PackageVerdict(
                False, False, False, None,
                (f"Package declares attachment {path!r}, which is missing from the archive.",),
            )

    try:
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

    # Per-carrier verification (R18): every declared carrier must match its
    # declared sha256/bytes, and its checksums.json binding when one exists.
    adjuntos_verified = True
    checksum_entries = declared if isinstance(declared, dict) else {}
    for entry in adjunto_entries:
        path = str(entry["path"])
        carrier_bytes = archive.read(path)
        digest = _sha256(carrier_bytes)
        if digest != entry.get("sha256") or len(carrier_bytes) != entry.get("bytes"):
            issues.append(
                f"Attachment {path!r} does not match its declared sha256/bytes."
            )
            adjuntos_verified = False
            continue
        if path in checksum_entries and checksum_entries[path] != digest:
            issues.append(
                f"Attachment {path!r} does not match its declared sha256/bytes."
            )
            adjuntos_verified = False

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
        and adjuntos_verified
    )
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
# Trust-time carrier extraction (Slice 5, AE-4)
# ---------------------------------------------------------------------------


def _write_verified_carriers(
    data: bytes,
    compiled: CompiledMethodology,
    attachments_root: Path,
) -> bool:
    """Materialize a trusted package's verified carrier bytes (AE-4).

    Every declared carrier is read from the package zip and re-verified against
    its ``sha256``/``bytes`` pin BEFORE anything is written. Extraction is
    all-or-nothing: any unreadable carrier, digest mismatch, or OSError writes
    nothing (no partial ``attachments/{skill_id}/`` tree) and returns ``False``.
    On success each file lands atomically (temp + ``os.replace``) reusing the
    author-carrier storage convention, and the skill dir is left intact.
    """
    if not compiled.adjuntos:
        return True
    dest_dir = Path(attachments_root) / compiled.skill_id
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError):
        return False

    verified: list[tuple[str, bytes]] = []
    try:
        for pin in compiled.adjuntos:
            try:
                carrier_bytes = archive.read(pin.path)
            except (KeyError, OSError):
                return False
            if (
                _sha256(carrier_bytes) != pin.sha256
                or len(carrier_bytes) != pin.bytes
            ):
                return False
            verified.append((pin.path, carrier_bytes))
    finally:
        archive.close()

    dest_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    try:
        for path, carrier_bytes in verified:
            dest = dest_dir / path
            tmp = dest.with_name(dest.name + ".tmp")
            tmp.write_bytes(carrier_bytes)
            os.replace(tmp, dest)
            written.append(dest)
    except OSError:
        # Roll back every file this call wrote; never leave partial bytes.
        for dest in written:
            try:
                dest.unlink()
            except OSError:
                pass
        try:
            if dest_dir.is_dir() and not any(dest_dir.iterdir()):
                dest_dir.rmdir()
        except OSError:
            pass
        return False
    return True


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
            draft_id=meta.get("draft_id"),
        )

    def list(self) -> list[QuarantineRecord]:
        """Return all quarantine records with fresh re-inspected verdicts.

        Mirrors ``get()``: every stored record is re-validated at read time so
        a package tampered on disk is surfaced as failed (fails closed). The
        store root is created lazily by ``quarantine``; an absent root lists
        empty.
        """
        if not self._root.is_dir():
            return []
        records: list[QuarantineRecord] = []
        for meta_path in sorted(self._root.glob("*.json")):
            package_id = meta_path.stem
            try:
                with open(meta_path, encoding="utf-8") as handle:
                    meta = json.load(handle)
            except (json.JSONDecodeError, OSError):
                continue
            package_path = self._root / f"{package_id}.zip"
            if not package_path.is_file():
                continue
            records.append(QuarantineRecord(
                package_id=package_id,
                verdict=inspect_package(package_path.read_bytes()),
                trusted=bool(meta.get("trusted")),
                clasificacion=meta.get("clasificacion"),
                trust_attributes=tuple(meta.get("trust_attributes") or ()),
                draft_id=meta.get("draft_id"),
            ))
        return records

    def trust(
        self,
        package_id: str,
        library=None,
        verifier: Callable[[str, str], bool] | None = None,
        *,
        attachments_root: Path | None = None,
    ):
        """Manually trust a quarantined package.

        Only a package that re-validates (checksum + optional official
        signature + compiler) is surfaced as an **editable draft**. Returns a
        ``QuarantineRecord`` on success (or ``None`` on failure); never
        publishes or activates automatically.

        When ``attachments_root`` is provided, each declared carrier's verified
        bytes are materialized to ``attachments/{skill_id}/`` (AE-4) before the
        draft is created, so a trusted import's export round-trips. Extraction
        is fail-closed: an unverifiable carrier writes no bytes at all and
        yields no draft. ``None`` (the default) preserves the legacy behavior —
        extraction is skipped and only the draft is created.
        """
        record_path = self._root / f"{package_id}.json"
        package_path = self._root / f"{package_id}.zip"
        if not record_path.exists() or not package_path.exists():
            return None
        data = package_path.read_bytes()
        verdict = inspect_package(data, verifier=verifier)
        if not verdict.ok or verdict.compiled is None:
            return None
        if attachments_root is not None and not _write_verified_carriers(
            data, verdict.compiled, Path(attachments_root),
        ):
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
                adjuntos=tuple(compiled.adjuntos),
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
            draft_id=draft_id,
        )
