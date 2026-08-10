"""Conservative historical migration and parity gates for native idea capture.

The migrator is deliberately source-preserving: it only writes new canonical,
quarantine, audit, and rollback artifacts. Legacy files and records are never
deleted or modified by this module.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping


_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class HistoricalRecord:
    source: str
    path: str
    content: str
    raw_bytes: bytes
    world: str | None = None
    record_id: str = ""
    slug: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.raw_bytes).hexdigest()


@dataclass(frozen=True)
class MigrationResult:
    planned: int
    migrated: int
    quarantined: int
    duplicates: int
    audit_path: Path
    rollback_path: Path
    quarantine_path: Path
    dry_run: bool


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse the closed, scalar frontmatter used by legacy Idea files."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) != 3:
        return {}, text
    values: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip().strip('"').strip("'")
        if key.strip() in {"id", "slug", "timestamp", "source", "type", "status", "world"}:
            values[key.strip()] = value
    return values, parts[2].lstrip("\r\n")


def _safe_slug(value: str, content: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip()).strip("-")
    if candidate and _SAFE_NAME.fullmatch(candidate):
        return candidate[:120]
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    return f"migrated-{digest}"


class HistoricalMigrator:
    def __init__(self, legacy_roots: Iterable[str | Path], output_root: str | Path,
                 engram_records: Iterable[Mapping[str, object] | HistoricalRecord] = ()):
        self.legacy_roots = tuple(Path(root) for root in legacy_roots)
        self.output_root = Path(output_root)
        self.engram_records = tuple(engram_records)

    def inventory(self) -> list[HistoricalRecord]:
        records: list[HistoricalRecord] = []
        for root in self.legacy_roots:
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*.md")):
                raw = path.read_bytes()
                front, body = _frontmatter(raw.decode("utf-8", errors="replace"))
                world = front.get("world") or self._world_from_path(path, root)
                records.append(HistoricalRecord(
                    source=str(path), path=str(path), content=body,
                    raw_bytes=raw, world=world, record_id=front.get("id", ""),
                    slug=front.get("slug", path.stem), metadata=front,
                ))
        for item in self.engram_records:
            if isinstance(item, HistoricalRecord):
                records.append(item)
                continue
            content = str(item.get("content", ""))
            raw = str(item.get("raw", content)).encode("utf-8")
            records.append(HistoricalRecord(
                source=str(item.get("source", "engram")),
                path=str(item.get("path", item.get("source", "engram"))),
                content=content, raw_bytes=raw,
                world=str(item.get("world")) if item.get("world") else None,
                record_id=str(item.get("id", "")), slug=str(item.get("slug", "")),
                metadata={str(k): str(v) for k, v in item.items()},
            ))
        return records

    @staticmethod
    def _world_from_path(path: Path, root: Path) -> str | None:
        parts = path.relative_to(root).parts
        # Global mundos/Ideas has no trustworthy world; quarantine it.
        return parts[0] if len(parts) > 1 and _SAFE_NAME.fullmatch(parts[0]) else None

    @staticmethod
    def _normalized(record: HistoricalRecord) -> str:
        return " ".join(unicodedata.normalize("NFC", record.content).split())

    def _clusters(self, records: list[HistoricalRecord]) -> list[list[HistoricalRecord]]:
        clusters: list[list[HistoricalRecord]] = []
        by_key: dict[str, list[HistoricalRecord]] = {}
        for record in records:
            content_hash = hashlib.sha256(self._normalized(record).encode("utf-8")).hexdigest()
            keys = [content_hash]
            if record.record_id:
                keys.append(f"id:{record.record_id}")
            elif record.slug:
                keys.append(f"slug:{record.slug}")
            matches = {id(cluster): cluster for key in keys for cluster in by_key.get(key, [])}
            if matches:
                existing = next(iter(matches.values()))
                for other in matches.values():
                    if other is not existing:
                        existing.extend(other)
                        clusters.remove(other)
            else:
                existing = []
                clusters.append(existing)
            existing.append(record)
            for key in keys:
                by_key[key] = [existing]
        return clusters

    def migrate(self, *, dry_run: bool = True, quarantine_ambiguous: bool = True) -> MigrationResult:
        if not dry_run and not quarantine_ambiguous:
            raise ValueError("apply requires quarantine_ambiguous=True")
        records = self.inventory()
        artifact_root = self.output_root / ".idea-migration"
        audit_dir = artifact_root / "audit"
        rollback_dir = artifact_root / "rollback"
        quarantine_dir = artifact_root / "quarantine"
        for directory in (audit_dir, rollback_dir, quarantine_dir):
            directory.mkdir(parents=True, exist_ok=True)

        entries = []
        migrated = quarantined = duplicates = 0
        for cluster in self._clusters(records):
            normalized = {self._normalized(record) for record in cluster}
            conflict = len(normalized) > 1 or any(not record.world for record in cluster)
            if conflict:
                quarantined += len(cluster)
                for record in cluster:
                    destination = quarantine_dir / f"{record.checksum}.json"
                    destination.write_text(json.dumps(self._entry(record, "quarantined"), indent=2), encoding="utf-8")
                    self._snapshot(record, rollback_dir)
                entries.append({"identity": self._identity(cluster[0]), "status": "quarantined",
                                "records": [self._entry(record, "quarantined") for record in cluster]})
                continue

            representative = cluster[0]
            duplicates += max(0, len(cluster) - 1)
            world = representative.world
            slug = _safe_slug(representative.slug, self._normalized(representative))
            destination = self.output_root / "mundos" / str(world) / "Ideas" / f"{slug}.md"
            if not dry_run:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    destination.write_text(self._canonical(representative, slug), encoding="utf-8")
            self._snapshot(representative, rollback_dir)
            migrated += 1
            entries.append({"identity": self._identity(representative), "status": "migrated",
                            "destination": str(destination),
                            "records": [self._entry(record, "duplicate" if record is not representative else "migrated")
                                        for record in cluster]})

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        audit_path = audit_dir / f"migration-{stamp}.json"
        audit_path.write_text(json.dumps({"version": 1, "dry_run": dry_run,
                                          "planned": len(records), "migrated": migrated,
                                          "quarantined": quarantined, "duplicates": duplicates,
                                          "entries": entries}, indent=2), encoding="utf-8")
        return MigrationResult(len(records), migrated, quarantined, duplicates,
                               audit_path, rollback_dir, quarantine_dir, dry_run)

    @staticmethod
    def _identity(record: HistoricalRecord) -> str:
        return record.record_id or record.slug or record.checksum

    @staticmethod
    def _entry(record: HistoricalRecord, status: str) -> dict[str, object]:
        return {"source": record.source, "path": record.path, "status": status,
                "world": record.world, "id": record.record_id, "slug": record.slug,
                "checksum": record.checksum}

    @staticmethod
    def _canonical(record: HistoricalRecord, slug: str) -> str:
        return (f'---\nid: "{record.record_id or record.checksum[:16]}"\n'
                f'slug: "{slug}"\ntimestamp: ""\nsource: "migration"\n'
                f'type: "idea_loose"\ntags: []\nstatus: "migrated"\n'
                f'---\n\n{record.content.rstrip()}\n')

    @staticmethod
    def _snapshot(record: HistoricalRecord, rollback_dir: Path) -> None:
        destination = rollback_dir / record.checksum[:2] / f"{record.checksum}.source"
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(record.raw_bytes)


@dataclass
class ParityWindow:
    expected_updates: int = 0
    observed_updates: int = 0
    raw_loss: int = 0
    unauthorized_writes: int = 0
    eventual_successes: int = 0
    duplicate_writes: int = 0
    elapsed_days: float = 0.0

    def evaluate(self) -> dict[str, object]:
        accounting = self.expected_updates == self.observed_updates
        success_rate = (self.eventual_successes / self.observed_updates
                        if self.observed_updates else 0.0)
        duplicate_rate = (self.duplicate_writes / self.observed_updates
                          if self.observed_updates else 0.0)
        passed = (self.elapsed_days >= 14 and accounting and self.raw_loss == 0 and
                  self.unauthorized_writes == 0 and success_rate >= 0.99 and duplicate_rate <= 0.01)
        return {"passed": passed, "accounting": accounting, "success_rate": success_rate,
                "duplicate_rate": duplicate_rate, "raw_loss": self.raw_loss,
                "unauthorized_writes": self.unauthorized_writes, "elapsed_days": self.elapsed_days}

    def assert_cutover_allowed(self) -> None:
        result = self.evaluate()
        if not result["passed"]:
            raise RuntimeError(f"legacy retirement blocked: {result}")
