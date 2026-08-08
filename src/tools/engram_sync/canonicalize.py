"""Deterministic canonical representation and stable fingerprints."""

import hashlib
import json
from datetime import date, datetime
from typing import Any

# Keys that change on every scan without meaning for comparison.
VOLATILE_KEYS: frozenset[str] = frozenset({"scan_time", "scanned_at"})

def _normalize(value: Any, exclude_volatile: bool) -> Any:
    if isinstance(value, dict):
        items = value.items()
        if exclude_volatile:
            items = ((k, v) for k, v in items if k not in VOLATILE_KEYS)
        return {k: _normalize(v, exclude_volatile) for k, v in items}
    if isinstance(value, list):
        return [_normalize(v, exclude_volatile) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value

def canonical_json(value: Any, *, exclude_volatile: bool = True) -> str:
    """Deterministic, sorted, compact JSON representation."""
    return json.dumps(
        _normalize(value, exclude_volatile),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

def fingerprint(value: Any, *, exclude_volatile: bool = True) -> str:
    """Stable sha256 fingerprint of the canonical form."""
    encoded = canonical_json(value, exclude_volatile=exclude_volatile).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()