# -*- coding: utf-8 -*-
"""Manifest, retention and last-write schemas for the backup engine (WU-8a).

One module, one source of truth for the three ``meta/`` documents:

* ``manifest.json`` — :class:`Manifest`, schema v1, built from the REAL
  inventory. :func:`build_manifest` iterates ``Inventory.included`` and never
  walks the disk to find paths again: the inventory selected the staged set, and
  a second independent scan is exactly how a manifest drifts from what was
  staged. Reading those files to record their size and digest is not a second
  discovery.
* ``retention.json`` — :class:`RetentionRecord`. WU-10 owns the GFS POLICY; this
  module owns the serialized shape only.
* ``last-write.json`` — :class:`LastWriteRecord`, the LOCAL write record ONLY.
  REQ-SF-4/SC-SF-4.1 forbid every upload, sync-state and cloud field: Demiurgos
  writes a folder and claims exactly that. The guarantee is structural — see
  :data:`LAST_WRITE_FIELDS` and :func:`assert_no_delivery_keys`.

**Refuse rather than misinterpret.** A document whose ``schema_version`` this
build does not support is rejected naming the version found, an unknown key is
rejected by name, and a manifest naming an unknown ``checksum_algorithm`` is
rejected before a byte is hashed — a recorded algorithm is detectable instead of
silently verified with the wrong function (REQ-BE-4, SC-BE-4.2).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from backup.inventory import Inventory

MANIFEST_SCHEMA_VERSION = 1
RETENTION_SCHEMA_VERSION = 1
LAST_WRITE_SCHEMA_VERSION = 1
SUPPORTED_MANIFEST_VERSIONS: frozenset[int] = frozenset({MANIFEST_SCHEMA_VERSION})
SUPPORTED_RETENTION_VERSIONS: frozenset[int] = frozenset({RETENTION_SCHEMA_VERSION})
SUPPORTED_LAST_WRITE_VERSIONS: frozenset[int] = frozenset({LAST_WRITE_SCHEMA_VERSION})

#: The digest recorded IN the document, so a future algorithm change is
#: detectable. Every algorithm this build can compute is keyed here.
DEFAULT_CHECKSUM_ALGORITHM = "sha256"
CHECKSUM_ALGORITHMS: Mapping[str, Callable[[], Any]] = {"sha256": hashlib.sha256}

_HASH_BLOCK_BYTES = 1 << 20

#: The only keys ``last-write.json`` may ever serialize, in document order.
#: Serialization reads THIS tuple, never the dataclass fields, so a member added
#: to :class:`LastWriteRecord` cannot reach the document unless it is added here
#: deliberately — and :func:`assert_no_delivery_keys` then guards this tuple.
LAST_WRITE_FIELDS: tuple[str, ...] = (
    "schema_version",
    "last_run_at",
    "status",
    "destination",
    "current_entries",
    "error",
    "warnings",
)

#: Key substrings that would turn a LOCAL write record into a delivery claim.
FORBIDDEN_DELIVERY_TOKENS: tuple[str, ...] = (
    "upload",
    "cloud",
    "sync",
    "quota",
    "account",
    "connection",
    "remote",
)


class ManifestError(RuntimeError):
    """A meta document could not be built, read or trusted."""


class UnsupportedSchemaVersionError(ManifestError):
    """The document names a schema version this build does not support."""


class UnknownChecksumAlgorithmError(ManifestError):
    """The manifest names a checksum algorithm this build cannot compute."""


class ManifestEntryMissingError(ManifestError):
    """A manifest entry has no readable bytes at its recorded path."""


class ChecksumMismatchError(ManifestError):
    """An entry's bytes no longer match the manifest's recorded digest."""


class DeliveryClaimError(ManifestError):
    """A payload carries a delivery claim REQ-SF-4 forbids."""


def new_hasher(algorithm: str) -> Any:
    """A fresh hasher for *algorithm*, refusing one this build cannot compute."""
    factory = CHECKSUM_ALGORITHMS.get(algorithm)
    if factory is None:
        raise UnknownChecksumAlgorithmError(
            f"unknown checksum_algorithm {algorithm!r}; "
            f"this build computes {sorted(CHECKSUM_ALGORITHMS)}"
        )
    return factory()


def digest_file(path: Path, algorithm: str = DEFAULT_CHECKSUM_ALGORITHM) -> str:
    """Digest *path* with *algorithm*, blockwise so a large file stays safe."""
    hasher = new_hasher(algorithm)
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(_HASH_BLOCK_BYTES), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _require_version(
    payload: Mapping[str, Any], document: str, supported: frozenset[int]
) -> int:
    """The document's schema version, or a refusal naming the version found."""
    version = payload.get("schema_version")
    if version not in supported:
        raise UnsupportedSchemaVersionError(
            f"unsupported {document} schema_version {version!r}; "
            f"this build supports {sorted(supported)}"
        )
    return version


def _reject_unknown(payload: Mapping[str, Any], cls: type, document: str) -> None:
    """Refuse a document carrying a field this schema does not define."""
    unknown = sorted(set(payload) - {field.name for field in fields(cls)})
    if unknown:
        raise ManifestError(f"{document} carries unsupported field(s) {unknown}")


def _record(
    cls: type,
    payload: Mapping[str, Any],
    document: str,
    *,
    tuples: Sequence[str] = (),
) -> Any:
    """Build one record, refusing an unknown field and normalizing tuple fields."""
    _reject_unknown(payload, cls, document)
    return cls(
        **{
            name: tuple(value) if name in tuples else value
            for name, value in payload.items()
        }
    )


@dataclass(frozen=True)
class Totals:
    """Counts and bytes covered by :attr:`Manifest.entries`."""

    entries: int
    bytes: int


@dataclass(frozen=True)
class TopLevelRecord:
    """One discovered top-level member, with its canonical case and kind."""

    name: str
    canonical_case: str
    kind: str


@dataclass(frozen=True)
class EntryRecord:
    """One staged FILE.

    A directory carries no digest, so it is not an entry: it is implied by the
    files beneath it. Only the top level is recorded explicitly, as
    :class:`TopLevelRecord`.
    """

    path: str
    kind: str
    size: int
    sha256: str
    mtime_ns: int


@dataclass(frozen=True)
class SqliteRecord:
    """One included SQLite database: its staged path, digest and integrity."""

    name: str
    path: str
    sha256: str
    integrity: str


@dataclass(frozen=True)
class ExcludedRecord:
    """A path the exclusion table refused, with the reason that matched it."""

    path: str
    reason: str


@dataclass(frozen=True)
class FindingRecord:
    """A non-fatal observation about the inventory."""

    kind: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class Manifest:
    """``meta/manifest.json``: what a snapshot contains and how it validates.

    A ``sqlite`` path is also an ``entries`` path (the design lists databases
    like any other entry), so :func:`verify_manifest` covers its bytes too; the
    ``sqlite`` block adds the per-database ``integrity`` verdict that only the
    SQLite snapshotter can produce (WU-9).
    """

    schema_version: int
    snapshot_id: str
    created_at: str
    data_root: str
    checksum_algorithm: str
    complete: bool
    totals: Totals
    top_level: tuple[TopLevelRecord, ...]
    entries: tuple[EntryRecord, ...]
    sqlite: tuple[SqliteRecord, ...]
    excluded: tuple[ExcludedRecord, ...]
    findings: tuple[FindingRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        """The document as JSON-ready data, in the design's field order."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Manifest:
        """Deserialize, gating the version, the algorithm and every field name."""
        version = _require_version(payload, "manifest", SUPPORTED_MANIFEST_VERSIONS)
        _reject_unknown(payload, cls, "manifest")
        algorithm = str(payload["checksum_algorithm"])
        new_hasher(algorithm)  # an unknown algorithm is refused, never assumed
        return cls(
            schema_version=version,
            snapshot_id=str(payload["snapshot_id"]),
            created_at=str(payload["created_at"]),
            data_root=str(payload["data_root"]),
            checksum_algorithm=algorithm,
            complete=bool(payload["complete"]),
            totals=_record(Totals, payload["totals"], "manifest.totals"),
            top_level=tuple(
                _record(TopLevelRecord, item, "manifest.top_level")
                for item in payload["top_level"]
            ),
            entries=tuple(
                _record(EntryRecord, item, "manifest.entries")
                for item in payload["entries"]
            ),
            sqlite=tuple(
                _record(SqliteRecord, item, "manifest.sqlite")
                for item in payload["sqlite"]
            ),
            excluded=tuple(
                _record(ExcludedRecord, item, "manifest.excluded")
                for item in payload["excluded"]
            ),
            findings=tuple(
                _record(FindingRecord, item, "manifest.findings", tuples=("paths",))
                for item in payload["findings"]
            ),
        )


def build_manifest(
    inventory: Inventory,
    *,
    snapshot_id: str,
    created_at: str,
    data_root: Path | None = None,
    complete: bool = True,
    sqlite: Sequence[SqliteRecord] = (),
) -> Manifest:
    """The manifest for *inventory* — the staged set is exactly what it selected.

    The inventory is the ONLY source of the set (REQ-BE-2, SC-BE-2.1): this
    function iterates ``inventory.included`` and never re-walks the data root, so
    the manifest can never describe a path the inventory did not select. Each
    selected file is read once to record its size, ``mtime_ns`` and digest.

    ``sqlite`` carries the databases the SQLite snapshotter staged (WU-9);
    ``complete`` is ``False`` for an interrupted run so the snapshot can never
    validate as whole (REQ-BE-4).
    """
    root = inventory.root
    entries: list[EntryRecord] = []
    for relative in inventory.included:
        absolute = root / relative
        if absolute.is_dir():
            continue
        if not absolute.is_file():
            raise ManifestEntryMissingError(
                f"inventory selected {relative!r} but it is not a readable file "
                f"under {root}"
            )
        stat = absolute.stat()
        entries.append(EntryRecord(
            path=relative,
            kind="file",
            size=stat.st_size,
            sha256=digest_file(absolute),
            mtime_ns=stat.st_mtime_ns,
        ))
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        snapshot_id=snapshot_id,
        created_at=created_at,
        data_root=str(root if data_root is None else data_root),
        checksum_algorithm=DEFAULT_CHECKSUM_ALGORITHM,
        complete=complete,
        totals=Totals(
            entries=len(entries), bytes=sum(entry.size for entry in entries)
        ),
        top_level=tuple(
            TopLevelRecord(member.name, member.canonical_case, member.kind)
            for member in inventory.top_level
        ),
        entries=tuple(entries),
        sqlite=tuple(sqlite),
        excluded=tuple(
            ExcludedRecord(entry.path, entry.reason) for entry in inventory.excluded
        ),
        findings=tuple(
            FindingRecord(finding.kind, finding.paths)
            for finding in inventory.findings
        ),
    )


def verify_manifest(manifest: Manifest, *, root: Path) -> int:
    """Verify every entry of *manifest* against the bytes under *root*.

    Checks presence, size and the manifest's OWN ``checksum_algorithm``; an
    algorithm this build does not know is refused before any byte is hashed, so
    a digest is never computed with the wrong function. Returns the number of
    bytes verified, and raises naming the offending entry — never a bare
    "failed" (REQ-BE-4, SC-BE-4.2).
    """
    new_hasher(manifest.checksum_algorithm)
    root = Path(root)
    verified = 0
    for entry in manifest.entries:
        absolute = root / entry.path
        if not absolute.is_file():
            raise ManifestEntryMissingError(
                f"manifest entry {entry.path!r} is missing under {root}"
            )
        size = absolute.stat().st_size
        if size != entry.size:
            raise ChecksumMismatchError(
                f"entry {entry.path!r} size mismatch: "
                f"manifest {entry.size}, found {size}"
            )
        actual = digest_file(absolute, manifest.checksum_algorithm)
        if actual != entry.sha256:
            raise ChecksumMismatchError(
                f"entry {entry.path!r} {manifest.checksum_algorithm} mismatch: "
                f"manifest {entry.sha256}, found {actual}"
            )
        verified += size
    return verified


def read_manifest(path: Path) -> Manifest:
    """Read a standalone ``manifest.json`` — a snapshot validates on its own."""
    return Manifest.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass(frozen=True)
class LastWriteRecord:
    """``meta/last-write.json`` — what Demiurgos wrote LOCALLY, nothing else.

    The record is deliberately incapable of claiming delivery (REQ-SF-4). Its
    serializer reads :data:`LAST_WRITE_FIELDS`, an explicit English allowlist, and
    then runs :func:`assert_no_delivery_keys` over the result, so neither a new
    dataclass member nor a nested payload can add an upload/cloud/sync claim.

    ``status`` is ``"ok"``, ``"ok_with_warnings"`` or ``"failed"``; ``warnings``
    carries the design's non-fatal notices (a sweep older than 24 h, a
    ``restore_leftover``, a failed prune) without turning them into ``error``.
    """

    schema_version: int = LAST_WRITE_SCHEMA_VERSION
    last_run_at: str | None = None
    status: str = "failed"
    destination: str | None = None
    current_entries: int = 0
    error: str | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize through the allowlist, refusing any delivery claim."""
        payload = {name: getattr(self, name) for name in LAST_WRITE_FIELDS}
        assert_no_delivery_keys(payload)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> LastWriteRecord:
        """Deserialize a local write record, refusing any delivery claim."""
        _require_version(
            payload, "last-write", SUPPORTED_LAST_WRITE_VERSIONS
        )
        assert_no_delivery_keys(payload)
        return cls(
            schema_version=int(payload["schema_version"]),
            last_run_at=payload.get("last_run_at"),
            status=str(payload.get("status", "failed")),
            destination=payload.get("destination"),
            current_entries=int(payload.get("current_entries", 0)),
            error=payload.get("error"),
            warnings=tuple(payload.get("warnings", ())),
        )


def last_write_unserialized_fields() -> frozenset[str]:
    """Members of :class:`LastWriteRecord` the allowlist would drop.

    Empty by construction. A field added without extending
    :data:`LAST_WRITE_FIELDS` shows up here, so the schema test fails and the
    allowlist must be edited deliberately — which is what the delivery-token
    scan guards.
    """
    return frozenset(field.name for field in fields(LastWriteRecord)) - set(
        LAST_WRITE_FIELDS
    )


def _walk_keys(value: Any) -> Iterator[str]:
    """Every mapping key in *value*, at any depth."""
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield str(key)
            yield from _walk_keys(nested)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_keys(item)


def assert_no_delivery_keys(payload: Mapping[str, Any]) -> None:
    """Refuse any key that would turn a local write record into a delivery claim.

    The walk is recursive, so a nested ``{"warnings": [{"uploaded_at": ...}]}``
    is refused too, and the match is a substring test so ``cloud_state`` or
    ``last_sync_at`` cannot slip past a fixed token list (REQ-SF-4, SC-SF-4.1).
    """
    for key in _walk_keys(payload):
        lowered = key.lower()
        for token in FORBIDDEN_DELIVERY_TOKENS:
            if token in lowered:
                raise DeliveryClaimError(
                    f"key {key!r} claims delivery ({token!r}); REQ-SF-4 allows a "
                    "LOCAL write record only"
                )


@dataclass(frozen=True)
class GfsPolicy:
    """The GFS numbers WU-10 applies; this module only stores them."""

    daily: int = 7
    weekly: int = 4
    monthly: int = 6


GFS_DAILY_7_WEEKLY_4_MONTHLY_6 = GfsPolicy()


@dataclass(frozen=True)
class RetentionRecord:
    """``meta/retention.json`` — the GFS selection record (policy is WU-10).

    ``unrecognized`` and ``protected`` are the design's escape hatches: an id
    that fails to parse is never pruned, and a pinned id is never pruned. They
    live in the schema from v1 so WU-10 records them without a schema change.
    """

    schema_version: int = RETENTION_SCHEMA_VERSION
    policy: GfsPolicy = GFS_DAILY_7_WEEKLY_4_MONTHLY_6
    keep: tuple[str, ...] = ()
    keep_failed: tuple[tuple[str, str], ...] = ()
    unrecognized: tuple[str, ...] = ()
    protected: tuple[str, ...] = ()
    last_pruned_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """The document as JSON-ready data, in the design's field order."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RetentionRecord:
        """Deserialize, gating the version and rejecting the ids shape drift."""
        _require_version(payload, "retention", SUPPORTED_RETENTION_VERSIONS)
        _reject_unknown(payload, cls, "retention")
        return cls(
            schema_version=int(payload["schema_version"]),
            policy=_record(
                GfsPolicy, payload.get("policy", {}), "retention.policy"
            ),
            keep=tuple(payload.get("keep", ())),
            keep_failed=tuple(
                (str(snapshot_id), str(error))
                for snapshot_id, error in payload.get("keep_failed", ())
            ),
            unrecognized=tuple(payload.get("unrecognized", ())),
            protected=tuple(payload.get("protected", ())),
            last_pruned_at=payload.get("last_pruned_at"),
        )
