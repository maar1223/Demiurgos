"""Seed catalog loader — repo-bundled foundational methodology seeds.

A seed is a committed directory of plain files at
``data/methodology/seeds/<skill-id>/{manifest.yaml, source.md, checksums.json}``
(one directory per skill). The directory listing IS the catalog: every
subdirectory of the seed root that follows the layout contributes exactly one
:class:`SeedEntry`.

Loading verifies the SHA-256 checksums declared in ``checksums.json`` against
the exact bundled bytes — the same integrity semantics as the methodology
package trust boundary — and fails closed with :class:`SeedIntegrityError` on
any mismatch. A partial or tampered catalog is never returned.

This module is deliberately inert at boot: it only loads and integrity-checks
seeds. Compilation (``compile_methodology``) and installation are owned by the
first-boot seeding wiring, so this loader stays pure and read-only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from methodology_compiler import parse_manifest

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