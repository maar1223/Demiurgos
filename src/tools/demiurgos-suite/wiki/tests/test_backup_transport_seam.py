# -*- coding: utf-8 -*-
"""Transport seam tests — the contract of ``backup.transport.base`` (WU-4).

Covers REQ-BE-8 and SC-BE-8.1 (the engine drives the seam; every call arrives
through the protocol) plus REQ-BE-10.1 (no delete-at-destination verb and no
``sync`` verb — non-destructiveness is structural, not a caller's discipline).

**Scope honesty — half of SC-BE-8.1 is deferred on purpose.** There is NO engine
yet: it lands in WU-9/WU-11. This suite proves the STRUCTURAL half — a fake
transport satisfies the protocol, a transport missing any single verb is
rejected, and the nine verbs are drivable through the Protocol alone — and it
does NOT assert "the engine holds no transport special case", because there is
no engine to assert it against. That half belongs to the engine's own slice and
is deliberately not faked here.
"""

from __future__ import annotations

import inspect
import sys
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from backup.transport.base import (  # noqa: E402
    BackupTransport,
    FetchResult,
    PruneResult,
    PublishResult,
    SnapshotIncompleteError,
    SnapshotInfo,
    SnapshotRef,
    TargetCapabilities,
    TransportError,
)

# The contract's nine verbs, in design order (REQ-BE-8): exactly these, no others.
VERBS = (
    "probe",
    "ensure_layout",
    "publish_current",
    "publish_snapshot",
    "prune",
    "list_snapshots",
    "read_meta",
    "write_meta",
    "fetch",
)

# The frozen seam shapes and their exact field order (REQ-BE-8).
SHAPES = (
    (TargetCapabilities, ("kind", "path", "writable",
                          "same_volume_as_data_root", "mode_hint")),
    (SnapshotInfo, ("snapshot_id", "complete", "entries", "bytes")),
    (PublishResult, ("published", "skipped", "bytes")),
    (PruneResult, ("deleted", "failed")),
    (FetchResult, ("dest_dir", "entries", "bytes")),
    (SnapshotRef, ("snapshot_id",)),
)

# Verbs that would reintroduce a destructive mirror (the retired ``rclone sync``).
# ``prune`` is deliberately NOT here: policy snapshot deletion is the one allowed
# deletion (REQ-BE-7) and it never touches ``current/``.
FORBIDDEN_VERBS = (
    "sync",
    "mirror",
    "mirror_to",
    "delete",
    "delete_at_destination",
    "remove",
    "unlink",
    "rmtree",
    "purge",
    "wipe",
)


class FakeTransport:
    """The in-memory transport the engine tests (WU-9+) will drive."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.meta: dict[str, Mapping[str, Any]] = {}

    def probe(self) -> TargetCapabilities:
        self.calls.append("probe")
        return TargetCapabilities("memory", "memory://", True, True, "mirrored")

    def ensure_layout(self) -> None:
        self.calls.append("ensure_layout")

    def publish_current(
        self, staged: Any, *, manifest: Mapping[str, Any]
    ) -> PublishResult:
        self.calls.append("publish_current")
        return PublishResult(published=1, skipped=0, bytes=1)

    def publish_snapshot(self, snapshot_id: str, staged: Any) -> PublishResult:
        self.calls.append("publish_snapshot")
        return PublishResult(published=1, skipped=0, bytes=1)

    def prune(self, snapshot_ids: Sequence[str]) -> PruneResult:
        self.calls.append("prune")
        return PruneResult(deleted=tuple(snapshot_ids), failed=())

    def list_snapshots(self) -> list[SnapshotInfo]:
        self.calls.append("list_snapshots")
        return [SnapshotInfo("2026-09-16T120530Z", True, 1, 1)]

    def read_meta(self, name: str) -> Mapping[str, Any] | None:
        self.calls.append("read_meta")
        return self.meta.get(name)

    def write_meta(self, name: str, payload: Mapping[str, Any]) -> None:
        self.calls.append("write_meta")
        self.meta[name] = dict(payload)

    def fetch(self, snapshot_ref: SnapshotRef, dest_dir: Path) -> FetchResult:
        self.calls.append("fetch")
        return FetchResult(dest_dir=dest_dir, entries=0, bytes=0)


def _drive(transport: BackupTransport) -> None:
    """Run every verb through the Protocol — no concrete transport is named."""
    transport.ensure_layout()
    capabilities = transport.probe()
    assert capabilities.mode_hint in {"mirrored", "streaming", "unknown"}
    transport.publish_current({"entry.md": b"x"}, manifest={"schema_version": 1})
    transport.publish_snapshot("2026-09-16T120530Z", {"entry.md": b"x"})
    infos = transport.list_snapshots()
    transport.write_meta("manifest.json", {"schema_version": 1})
    assert transport.read_meta("manifest.json") == {"schema_version": 1}
    transport.fetch(SnapshotRef(infos[0].snapshot_id), Path("staging"))
    transport.prune([info.snapshot_id for info in infos])


def _protocol_verbs() -> set[str]:
    """The public callables the protocol itself declares."""
    return {
        name
        for name, value in vars(BackupTransport).items()
        if not name.startswith("_") and callable(value)
    }


def _transport_class_without(missing: str) -> type:
    """A transport class exposing every verb except *missing*."""
    namespace: dict[str, Any] = {
        verb: (lambda self, *args, **kwargs: None)
        for verb in VERBS
        if verb != missing
    }
    return type(f"TransportWithout{missing}", (), namespace)


def test_backup_transport_is_a_runtime_checkable_protocol() -> None:
    assert getattr(BackupTransport, "_is_protocol", False) is True
    assert getattr(BackupTransport, "_is_runtime_protocol", False) is True


def test_protocol_declares_exactly_the_nine_verbs() -> None:
    assert _protocol_verbs() == set(VERBS)


def test_protocol_signatures_match_the_contract() -> None:
    publish_current = inspect.signature(BackupTransport.publish_current)
    assert list(publish_current.parameters) == ["self", "staged", "manifest"]
    assert (
        publish_current.parameters["manifest"].kind
        is inspect.Parameter.KEYWORD_ONLY
    )
    assert list(inspect.signature(BackupTransport.publish_snapshot).parameters) == [
        "self", "snapshot_id", "staged",
    ]
    assert list(inspect.signature(BackupTransport.prune).parameters) == [
        "self", "snapshot_ids",
    ]
    assert list(inspect.signature(BackupTransport.fetch).parameters) == [
        "self", "snapshot_ref", "dest_dir",
    ]
    assert list(inspect.signature(BackupTransport.probe).parameters) == ["self"]


def test_fake_transport_satisfies_the_protocol() -> None:
    assert isinstance(FakeTransport(), BackupTransport)


@pytest.mark.parametrize("missing", VERBS)
def test_a_transport_missing_any_single_verb_is_rejected(missing: str) -> None:
    assert not isinstance(_transport_class_without(missing)(), BackupTransport)


def test_fake_transport_is_drivable_through_the_seam() -> None:
    fake = FakeTransport()
    _drive(fake)
    assert set(fake.calls) == set(VERBS)


def test_no_sync_or_delete_at_destination_verb_exists() -> None:
    for forbidden in FORBIDDEN_VERBS:
        assert not hasattr(BackupTransport, forbidden), forbidden
        assert forbidden not in _protocol_verbs(), forbidden
        assert not hasattr(FakeTransport, forbidden), forbidden


def test_seam_dataclasses_are_frozen_with_exact_fields() -> None:
    for cls, expected in SHAPES:
        assert is_dataclass(cls), cls
        assert cls.__dataclass_params__.frozen is True, cls
        assert tuple(field.name for field in fields(cls)) == expected, cls


def test_error_hierarchy() -> None:
    assert issubclass(TransportError, RuntimeError)
    assert issubclass(SnapshotIncompleteError, TransportError)
