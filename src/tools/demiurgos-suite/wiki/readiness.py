"""Readiness probes and honest card projection for the Configuration Center.

``local_editor`` readiness is proven by a real local storage round-trip:
write a probe payload, read it back, verify byte-identity, then delete it.
The result is derived runtime truth — configuration or registry state alone
never proves readiness. It never overstates a remote/cloud capability.

``project_cards`` derives the OC12 card states from authoritative local
truth (ONB-3.1/3.2, OC11/OC12/OC21):

- Cloud cards (identity, telegram, backup) NEVER become ``configured`` from
  local evidence: only their dedicated contracts may mark them configured,
  and none exists in this slice. A stale registry claim is downgraded to
  ``pending`` instead of being trusted.
- The assistant card is ``configured`` ONLY when the registry records the
  three-proof evidence (text + vision probes passed and Hermes runtime
  acceptance). A bare ``capabilities.assistant == "configured"`` claim is
  never proof.
- ``world`` follows filesystem truth (a real world directory exists),
  ``locale`` follows the persisted step-0 locale, and ``offline`` follows
  the local-storage probe.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence


# Cloud/remote capabilities: their cards can never be derived to
# ``configured`` from local evidence in this slice (ONB-3.1).
CLOUD_CARDS: frozenset[str] = frozenset({"identity", "telegram", "backup"})

# Assistant proof evidence keys required before the card may be configured.
ASSISTANT_PROOF_KEYS: tuple[str, ...] = ("text", "vision", "runtime")
ASSISTANT_PROOF_VALUES: Mapping[str, str] = {
    "text": "passed",
    "vision": "passed",
    "runtime": "accepted",
}


def assistant_proven(state: Mapping[str, Any]) -> bool:
    """True only when all three proofs are recorded in the registry.

    The registry must hold ``assistant_acceptance`` with the exact outcome
    values from the three-proof gate (ONB-2.5): text=passed, vision=passed,
    runtime=accepted. Anything else — including a bare capability claim —
    is not proof.
    """
    evidence = state.get("assistant_acceptance")
    if not isinstance(evidence, Mapping):
        return False
    return all(
        evidence.get(key) == expected
        for key, expected in ASSISTANT_PROOF_VALUES.items()
    )


def project_cards(
    state: Mapping[str, Any],
    worlds: Sequence[str],
    probe_ok: bool,
) -> dict[str, str]:
    """Derive honest Configuration Center card states (OC11/OC12/OC21).

    ``state`` is the local registry snapshot; ``worlds`` is the runtime list
    of existing world names (filesystem truth); ``probe_ok`` is the derived
    local-storage probe result. Returns one CardState per card key.
    """
    cards: dict[str, str] = {}
    for key in CLOUD_CARDS:
        cards[key] = "pending"
    cards["assistant"] = "configured" if assistant_proven(state) else "pending"
    cards["world"] = "configured" if worlds else "pending"
    cards["locale"] = "configured" if state.get("locale") else "pending"
    cards["offline"] = "configured" if probe_ok else "error"
    return cards


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