# -*- coding: utf-8 -*-
"""Manifest, retention and last-write schema tests for WU-8a.

Covers REQ-BE-4 / SC-BE-4.2 (manifest round-trip and full sha256 verification),
the version and algorithm gates, and REQ-SF-4 / SC-SF-4.1 (``last-write.json``
is a LOCAL write record and can carry no cloud/upload/sync key). Hermetic: every
case builds its own ``tmp_path`` data root and drives ``build_inventory`` over
it; the real data root is never read and no pointer is consulted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from backup.inventory import build_inventory  # noqa: E402
from backup.manifest import (  # noqa: E402
    FORBIDDEN_DELIVERY_TOKENS,
    LAST_WRITE_FIELDS,
    ChecksumMismatchError,
    DeliveryClaimError,
    LastWriteRecord,
    Manifest,
    ManifestEntryMissingError,
    ManifestError,
    RetentionRecord,
    UnknownChecksumAlgorithmError,
    UnsupportedSchemaVersionError,
    assert_no_delivery_keys,
    build_manifest,
    last_write_unserialized_fields,
    read_manifest,
    verify_manifest,
)

#: The files the fixture root holds, and therefore the staged set.
STAGED = ("ideas/alpha.md", "mundos/MyWorld/seed.bin", "zzq-unruled/note.md")


def _data_root(tmp_path: Path) -> Path:
    """A data root with a ruled member, an unruled member and an exclusion."""
    root = tmp_path / "data-root"
    (root / "ideas").mkdir(parents=True, exist_ok=True)
    (root / "ideas" / "alpha.md").write_bytes(b"alpha\n")
    (root / "mundos" / "MyWorld").mkdir(parents=True, exist_ok=True)
    (root / "mundos" / "MyWorld" / "seed.bin").write_bytes(b"\x00\x01\x02")
    (root / "zzq-unruled").mkdir(exist_ok=True)
    (root / "zzq-unruled" / "note.md").write_text("note", encoding="utf-8")
    (root / "data" / "world-trash").mkdir(parents=True, exist_ok=True)
    (root / "data" / "world-trash" / "junk.bin").write_bytes(b"junk")
    return root


def _manifest(tmp_path: Path, **overrides: Any) -> Manifest:
    """The manifest for the fixture data root, as a real run would build it."""
    kwargs: dict[str, Any] = {
        "snapshot_id": "2026-09-16T120530Z",
        "created_at": "2026-09-16T12:05:30Z",
    }
    kwargs.update(overrides)
    return build_manifest(build_inventory(_data_root(tmp_path)), **kwargs)


def _all_keys(value: Any) -> set[str]:
    """Every mapping key in *value*, at any depth — the structural key walk."""
    if isinstance(value, dict):
        found: set[str] = set()
        for key, nested in value.items():
            found.add(key)
            found |= _all_keys(nested)
        return found
    if isinstance(value, list):
        return {key for item in value for key in _all_keys(item)}
    return set()


def test_manifest_round_trip_is_typed_and_equal(tmp_path: Path) -> None:
    """build → serialize → read → the typed result equals the original."""
    original = _manifest(tmp_path)
    text = json.dumps(original.to_dict())

    restored = Manifest.from_dict(json.loads(text))

    assert restored == original
    assert restored.entries[0] == original.entries[0]
    assert isinstance(restored.entries, tuple)

    path = tmp_path / "manifest.json"
    path.write_text(text, encoding="utf-8")
    assert read_manifest(path) == original


def test_manifest_carries_every_designed_field(tmp_path: Path) -> None:
    """The document is exactly schema v1: the design's fields, no invention."""
    payload = _manifest(tmp_path).to_dict()

    assert set(payload) == {
        "schema_version", "snapshot_id", "created_at", "data_root",
        "checksum_algorithm", "complete", "totals", "top_level",
        "entries", "sqlite", "excluded", "findings",
    }
    assert set(payload["totals"]) == {"entries", "bytes"}
    assert set(payload["top_level"][0]) == {"name", "canonical_case", "kind"}
    assert set(payload["entries"][0]) == {
        "path", "kind", "size", "sha256", "mtime_ns",
    }
    assert set(payload["excluded"][0]) == {"path", "reason"}
    assert set(payload["findings"][0]) == {"kind", "paths"}
    assert payload["checksum_algorithm"] == "sha256"
    assert payload["totals"]["entries"] == len(STAGED)


def test_build_reflects_the_inventory_and_never_rescans(tmp_path: Path) -> None:
    """The staged set is the inventory's; a late file is never self-discovered."""
    root = _data_root(tmp_path)
    inventory = build_inventory(root)
    (root / "ideas" / "added-after-inventory.md").write_bytes(b"late")

    manifest = build_manifest(
        inventory, snapshot_id="2026-09-16T120530Z", created_at="2026-09-16T12:05:30Z"
    )

    assert {entry.path for entry in manifest.entries} == set(STAGED)
    assert {record.path for record in manifest.excluded} == {"data/world-trash"}
    assert {record.kind for record in manifest.findings} == {
        "unclassified_top_level"
    }
    assert {record.name for record in manifest.top_level} >= {"ideas", "mundos"}


def test_verify_accepts_an_intact_tree(tmp_path: Path) -> None:
    """The happy path verifies every entry and returns the bytes covered."""
    root = _data_root(tmp_path)
    manifest = _manifest(tmp_path)

    assert verify_manifest(manifest, root=root) == sum(
        entry.size for entry in manifest.entries
    )


def test_checksum_mismatch_names_the_offending_entry(tmp_path: Path) -> None:
    """A byte change and a deletion both fail loudly, naming the entry."""
    root = _data_root(tmp_path)
    manifest = _manifest(tmp_path)
    target = root / "ideas" / "alpha.md"
    target.write_bytes(b"ALPHA!")  # same size as b"alpha\n", different digest

    with pytest.raises(ChecksumMismatchError) as excinfo:
        verify_manifest(manifest, root=root)
    assert "ideas/alpha.md" in str(excinfo.value)
    assert "sha256" in str(excinfo.value)

    target.unlink()
    with pytest.raises(ManifestEntryMissingError) as missing:
        verify_manifest(manifest, root=root)
    assert "ideas/alpha.md" in str(missing.value)


@pytest.mark.parametrize(
    ("field", "value", "error", "named"),
    [
        ("schema_version", 99, UnsupportedSchemaVersionError, "99"),
        ("checksum_algorithm", "blake3", UnknownChecksumAlgorithmError, "blake3"),
    ],
)
def test_document_gates_reject_unknown_values(
    tmp_path: Path, field: str, value: Any, error: type[Exception], named: str
) -> None:
    """An unknown version or algorithm is refused, naming what was found."""
    payload = _manifest(tmp_path).to_dict()
    payload[field] = value

    with pytest.raises(error) as excinfo:
        Manifest.from_dict(payload)
    assert named in str(excinfo.value)


def test_schema_is_closed_to_unknown_fields(tmp_path: Path) -> None:
    """An unrecognized field is refused by name, never silently ignored."""
    payload = _manifest(tmp_path).to_dict()
    payload["upload_state"] = "pending"

    with pytest.raises(ManifestError) as excinfo:
        Manifest.from_dict(payload)
    assert "upload_state" in str(excinfo.value)


def test_last_write_json_is_local_write_only(tmp_path: Path) -> None:
    """No cloud/upload/sync key exists, structurally and explicitly."""
    record = LastWriteRecord(
        last_run_at="2026-09-16T12:05:30Z",
        status="ok_with_warnings",
        destination="/abs/folder",
        current_entries=len(STAGED),
        warnings=("sweep-stale-tmp",),
    )

    serialized = json.loads(json.dumps(record.to_dict()))
    keys = _all_keys(serialized)

    assert keys == set(LAST_WRITE_FIELDS)  # the allowlist IS the document
    assert keys & set(FORBIDDEN_DELIVERY_TOKENS) == set()
    assert not any(
        token in key.lower() for key in keys for token in FORBIDDEN_DELIVERY_TOKENS
    )
    text = json.dumps(serialized).lower()
    for token in FORBIDDEN_DELIVERY_TOKENS:
        assert token not in text  # explicit absence, not just a key-set check

    assert last_write_unserialized_fields() == frozenset()
    assert LastWriteRecord.from_dict(serialized) == record


def test_delivery_claim_is_refused_even_when_nested() -> None:
    """The refusal walks nested payloads, not only the top level."""
    with pytest.raises(DeliveryClaimError):
        assert_no_delivery_keys({"status": "ok", "sync_state": "pending"})
    with pytest.raises(DeliveryClaimError):
        assert_no_delivery_keys({"status": "ok", "warnings": [{"uploaded_at": "x"}]})


def test_retention_round_trip_carries_the_gfs_policy() -> None:
    """retention.json round-trips: policy, keep sets and the escape hatches."""
    record = RetentionRecord(
        keep=("2026-09-16T120530Z",),
        keep_failed=(("2026-09-15T120000Z", "WinError 32"),),
        unrecognized=("not-a-snapshot-id",),
        protected=("2026-09-01T000000Z",),
        last_pruned_at="2026-09-16T12:06:00Z",
    )

    payload = json.loads(json.dumps(record.to_dict()))

    assert payload["policy"] == {"daily": 7, "weekly": 4, "monthly": 6}
    assert set(payload) == {
        "schema_version", "policy", "keep", "keep_failed", "unrecognized",
        "protected", "last_pruned_at",
    }
    assert RetentionRecord.from_dict(payload) == record
