"""Readiness probes for essential local capabilities (OC11/OC21).

``local_editor`` readiness is proven by a real local storage round-trip:
write a probe payload, read it back, verify byte-identity, then delete it.
The result is derived runtime truth — configuration or registry state alone
never proves readiness. It never overstates a remote/cloud capability.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any


def probe_local_storage(root: Path) -> dict[str, Any]:
    """Round-trip probe: write → read → verify → delete.

    Returns ``{"probe": "local_editor", "ok": bool, "detail": str}``. The probe
    file lives under ``<root>/data/probes/`` and is always removed afterwards.
    """
    probe_dir = Path(root) / "data" / "probes"
    payload = f"demiurgos-local-editor-probe-{uuid.uuid4().hex}\n"
    probe = probe_dir / f"local-editor-{uuid.uuid4().hex}.probe"
    try:
        probe_dir.mkdir(parents=True, exist_ok=True)
        probe.write_text(payload, encoding="utf-8")
        read_back = probe.read_text(encoding="utf-8")
        if read_back != payload:
            return {
                "probe": "local_editor",
                "ok": False,
                "detail": "read-back mismatch",
            }
        return {
            "probe": "local_editor",
            "ok": True,
            "detail": "storage round-trip ok",
        }
    except OSError as exc:
        return {"probe": "local_editor", "ok": False, "detail": str(exc)}
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass


def local_editor_ready(root: Path) -> bool:
    """Derived essential badge: true only when the probe round-trips."""
    return bool(probe_local_storage(root).get("ok"))