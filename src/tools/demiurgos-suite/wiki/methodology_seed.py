"""Seed catalog loader and installer — repo-bundled foundational methodology seeds.

A seed is a committed directory of plain files at
``data/methodology/seeds/<skill-id>/{manifest.yaml, source.md, checksums.json}``
(one directory per skill). The directory listing IS the catalog: every
subdirectory of the seed root that follows the layout contributes exactly one
:class:`SeedEntry`.

Loading verifies the SHA-256 checksums declared in ``checksums.json`` against
the exact bundled bytes — the same integrity semantics as the methodology
package trust boundary — and fails closed with :class:`SeedIntegrityError` on
any mismatch. A partial or tampered catalog is never returned.

Installation (:func:`install_seeds`) is two-phase and fail-closed: every entry
is loaded, checksum-verified, AND compiled before any write (a single
failure or authority claim aborts with ZERO records inserted), then each
compiled entry is inserted through the library's ``install_published_version``
with trust values from :func:`methodology_trust.foundational_trust` ONLY.
The reconciliation is insert-only and idempotent — it never re-points
activations or companions (TW15).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from methodology_compiler import CompiledMethodology, compile_methodology, parse_manifest
from methodology_trust import foundational_trust

_MANIFEST_NAME = "manifest.yaml"
_SOURCE_NAME = "source.md"
_CHECKSUMS_NAME = "checksums.json"


class SeedIntegrityError(Exception):
    """A seed entry failed integrity verification; the catalog is not loaded."""


@dataclass(frozen=True)
class SeedEntry:
    """One verified, compiler-ready seed.

    ``manifest`` is the parsed bounded manifest mapping and ``source`` the raw
    Markdown source; both come from the exact bundled bytes that passed the
    checksum verification.
    """

    skill_id: str
    version: str
    manifest: dict
    source: str


@dataclass(frozen=True)
class SeedInstallReport:
    """Outcome of one ``install_seeds`` reconciliation pass.

    ``entries`` is the number of compiler-clean seed entries processed; the
    four outcome counters partition them (their sum equals ``entries``).
    """

    entries: int
    installed: int
    existing: int
    stale: int
    conflict: int


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _verify_entry(entry_dir: Path) -> SeedEntry:
    """Load and verify one seed entry directory, or raise SeedIntegrityError."""
    manifest_path = entry_dir / _MANIFEST_NAME
    source_path = entry_dir / _SOURCE_NAME
    checksums_path = entry_dir / _CHECKSUMS_NAME

    missing = [path.name for path in (manifest_path, source_path, checksums_path)
               if not path.is_file()]
    if missing:
        raise SeedIntegrityError(
            f"Seed entry {entry_dir.name!r} is missing required files: "
            f"{sorted(missing)}."
        )

    manifest_bytes = manifest_path.read_bytes()
    source_bytes = source_path.read_bytes()
    try:
        declared = json.loads(checksums_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SeedIntegrityError(
            f"Seed entry {entry_dir.name!r} has an unreadable checksums.json."
        ) from exc
    if not isinstance(declared, dict):
        raise SeedIntegrityError(
            f"Seed entry {entry_dir.name!r} checksums.json must be a mapping."
        )

    expected = {
        name: str(declared.get(name, "")) if declared.get(name) is not None else ""
        for name in (_MANIFEST_NAME, _SOURCE_NAME)
    }
    actual = {
        _MANIFEST_NAME: _sha256(manifest_bytes),
        _SOURCE_NAME: _sha256(source_bytes),
    }
    if not (expected[_MANIFEST_NAME] and expected[_SOURCE_NAME]) or expected != actual:
        raise SeedIntegrityError(
            f"Seed entry {entry_dir.name!r}: integrity checksum mismatch — "
            "the bundled content was modified."
        )

    manifest = parse_manifest(manifest_bytes.decode("utf-8"))
    if manifest is None:
        raise SeedIntegrityError(
            f"Seed entry {entry_dir.name!r} has a missing or malformed manifest."
        )

    skill_id = manifest.get("skill_id")
    version = manifest.get("version")
    if not isinstance(skill_id, str) or not skill_id.strip():
        raise SeedIntegrityError(
            f"Seed entry {entry_dir.name!r} manifest is missing required "
            "field 'skill_id'."
        )
    if not isinstance(version, str) or not version.strip():
        raise SeedIntegrityError(
            f"Seed entry {entry_dir.name!r} manifest is missing required "
            "field 'version'."
        )
    if entry_dir.name != skill_id:
        raise SeedIntegrityError(
            f"Seed entry {entry_dir.name!r} directory name does not match "
            f"manifest skill_id {skill_id!r}."
        )

    # Contract §4 (SR4): declared attachment carriers are verified against
    # BOTH the manifest ``sha256`` and ``checksums.json`` — missing entry,
    # missing file, or digest mismatch fails the whole catalog (no partial
    # load). An empty/absent ``adjuntos`` list adds zero code paths, so
    # zero-attachment seeds behave byte-identically to pre-PR③ (S10).
    for entry in (manifest.get("adjuntos") or []):
        if not isinstance(entry, dict):
            raise SeedIntegrityError(
                f"Seed entry {entry_dir.name!r}: manifest adjuntos entries "
                "must be mappings."
            )
        path = entry.get("path")
        if not isinstance(path, str) or not path.strip():
            raise SeedIntegrityError(
                f"Seed entry {entry_dir.name!r}: adjuntos entry is missing a path."
            )
        carrier_path = entry_dir / path
        if not carrier_path.is_file():
            raise SeedIntegrityError(
                f"Seed entry {entry_dir.name!r}: declared attachment {path!r} "
                "is missing from the bundled files."
            )
        carrier_sha = _sha256(carrier_path.read_bytes())
        declared_sha = entry.get("sha256")
        if not isinstance(declared_sha, str) or carrier_sha != declared_sha:
            raise SeedIntegrityError(
                f"Seed entry {entry_dir.name!r}: attachment {path!r} does not "
                "match its declared sha256 digest."
            )
        checksum_sha = declared.get(path)
        if not isinstance(checksum_sha, str) or carrier_sha != checksum_sha:
            raise SeedIntegrityError(
                f"Seed entry {entry_dir.name!r}: attachment {path!r} does not "
                "match its checksums.json entry."
            )

    return SeedEntry(
        skill_id=skill_id,
        version=version,
        manifest=manifest,
        source=source_bytes.decode("utf-8"),
    )


def load_seed_catalog(root: Path) -> list[SeedEntry]:
    """Load and verify every seed entry under ``root``.

    The directory listing IS the catalog: each subdirectory of ``root`` is one
    seed entry. An absent root yields an empty catalog (a checkout without
    seeds is valid); any entry that fails integrity raises
    :class:`SeedIntegrityError` — no partial catalog is ever returned.
    """
    root = Path(root)
    if not root.is_dir():
        return []
    entries: list[SeedEntry] = []
    for entry_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        entries.append(_verify_entry(entry_dir))
    return entries


def install_seeds(library, root: Path) -> SeedInstallReport:
    """Install the repo-bundled foundational seeds (two-phase, fail closed).

    Phase 1 verifies AND compiles every seed entry before any write: a
    checksum failure, a compiler rejection, or an authority claim aborts the
    whole install with ZERO records inserted. Phase 2 inserts each compiled
    entry through ``MethodologyLibrary.install_published_version`` with trust
    from :func:`methodology_trust.foundational_trust` ONLY (the sole origin of
    server trust — seeds never claim their own classification). The insert is
    idempotent and insert-only: digest-equal reruns skip, newer stored
    versions make the seed stale, and activations/companions are never
    touched (TW15).
    """
    compiled_entries: list[tuple[SeedEntry, CompiledMethodology]] = []
    for entry in load_seed_catalog(root):
        result = compile_methodology(entry.manifest, entry.source)
        if not result.ok or result.compiled is None:
            raise SeedIntegrityError(
                f"Seed entry {entry.skill_id!r} failed compilation: "
                + "; ".join(issue.message for issue in result.issues)
            )
        compiled_entries.append((entry, result.compiled))

    clasificacion, trust_attributes = foundational_trust()
    counts = {"installed": 0, "existing": 0, "stale": 0, "conflict": 0}
    for _entry, compiled in compiled_entries:
        outcome = library.install_published_version(
            compiled,
            clasificacion=clasificacion,
            trust_attributes=trust_attributes,
        )
        counts[outcome] += 1
    return SeedInstallReport(entries=len(compiled_entries), **counts)