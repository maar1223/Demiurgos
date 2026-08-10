"""Controlled, reversible retirement of the legacy idea-ingress path."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .migration import ParityWindow


@dataclass(frozen=True)
class RetirementResult:
    archive_path: Path
    manifest_path: Path
    source_removed: bool
    retention_until: str


class LegacyRetirement:
    """Archive legacy source only after the parity gate has passed."""

    def __init__(self, source: str | Path, archive_root: str | Path):
        self.source = Path(source)
        self.archive_root = Path(archive_root)

    def retire(
        self,
        parity: ParityWindow,
        *,
        native_update_ids: Iterable[str] = (),
        legacy_update_ids: Iterable[str] = (),
        remove_source: bool = False,
    ) -> RetirementResult:
        parity.assert_cutover_allowed()
        if not self.source.is_file():
            raise FileNotFoundError(self.source)

        now = datetime.now(timezone.utc)
        retention_until = (now + timedelta(days=30)).isoformat()
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        archive_path = self.archive_root / self.source.name
        manifest_path = self.archive_root / "retirement-manifest.json"
        self.archive_root.mkdir(parents=True, exist_ok=True)
        if archive_path.exists():
            raise FileExistsError(archive_path)
        shutil.copy2(self.source, archive_path)

        native = set(native_update_ids)
        manifest = {
            "version": 1,
            "source": str(self.source),
            "archive": str(archive_path),
            "source_sha256": digest,
            "retired_at": now.isoformat(),
            "retention_until": retention_until,
            "disabled_legacy_triggers": ["Pipedream", "Google Sheets"],
            "replay_update_ids": sorted(set(legacy_update_ids) - native),
            "rollback": "restore archive before replaying only replay_update_ids",
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if remove_source:
            self.source.unlink()
        return RetirementResult(archive_path, manifest_path, remove_source, retention_until)
