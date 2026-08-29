"""Readiness probes and honest card projection for the Configuration Center.

``local_editor`` readiness is proven by a real local storage round-trip:
write a probe payload, read it back, verify byte-identity, then delete it.
The result is derived runtime truth — configuration or registry state alone
never proves readiness. It never overstates a remote/cloud capability.

``project_cards`` derives the OC12 card states from authoritative local
truth (ONB-3.1/3.2, OC11/OC12/OC21):

- Cloud cards WITHOUT a dedicated contract (backup) NEVER become
  ``configured`` from local evidence: only their dedicated contracts may mark
  them configured. A stale registry claim is downgraded to ``pending``
  instead of being trusted.
- The identity card HAS a dedicated contract (auth-vault-credentials,
  R-ID-01): it is ``configured`` ONLY when a local account exists in the
  registry (``capabilities.account`` with a username and a words hash) OR
  when ``DEMIURGOS_AUTH_MODE=credentials`` is active; a registry claim never
  configures it.
- The telegram card HAS a dedicated contract (ONB-3.3 backend): its state is
  supplied by the backend from real evidence (write-only token presence plus
  the last Telegram API connection-test outcome), never from a bare registry
  claim. ``project_cards`` accepts that derived state via ``telegram_state``
  and defaults to ``pending`` when absent.
- The assistant card is ``configured`` ONLY when the registry records the
  three-proof evidence (text + vision probes passed and Hermes runtime
  acceptance). A bare ``capabilities.assistant == "configured"`` claim is
  never proof.
- ``world`` follows filesystem truth (a real world directory exists),
  ``locale`` follows the persisted step-0 locale, and ``offline`` follows
  the local-storage probe.

``project_offline`` derives the honest offline/dispositivo breakdown (OC5):
the local core is ready when the storage probe round-trips, and every remote
capability that is still pending or requires connection is listed as
remote-pending — never claimed available offline.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from local_state import CARD_STATES


# Cloud/remote capabilities without a dedicated contract: their cards can
# never be derived to ``configured`` from local evidence in this slice
# (ONB-3.1). ``identity`` is excluded because auth-vault-credentials (R-ID1)
# provides its dedicated contract below. Telegram is excluded here because
# ONB-3.3 provides its dedicated backend contract; its state is passed in
# explicitly.
CLOUD_CARDS: frozenset[str] = frozenset({"backup"})

# Remote capabilities whose readiness depends on connectivity (OC5): they are
# never available offline. ``assistant`` is included because a cloud/multimodal
# model needs its provider; a pending assistant (no proven multimodal model)
# therefore surfaces as remote-pending while the local core keeps working.
# ``identity`` is NOT remote-pending: the credentials identity contract is
# local (account slot + mode), not connectivity-bound.
REMOTE_CARDS: tuple[str, ...] = ("telegram", "backup", "assistant")

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


def identity_configured(state: Mapping[str, Any] | None = None) -> bool:
    """Dedicated identity contract (R-ID-01, S-ID-01a/b/c).

    The identity card is ``configured`` when a local account exists in the
    registry (``capabilities.account`` carrying a username AND a words hash)
    OR when the credentials auth mode is active (``DEMIURGOS_AUTH_MODE=
    credentials``). Any other mode or a missing account leaves the card
    ``pending``. Registry capability claims never configure identity.
    """
    mode = os.environ.get("DEMIURGOS_AUTH_MODE", "").strip().lower()
    if mode == "credentials":
        return True
    if state is None:
        return False
    capabilities = state.get("capabilities")
    account = capabilities.get("account") if isinstance(capabilities, Mapping) else None
    if isinstance(account, Mapping):
        if account.get("username") and account.get("words_hash"):
            return True
    return False


def project_cards(
    state: Mapping[str, Any],
    worlds: Sequence[str],
    probe_ok: bool,
    telegram_state: str | None = None,
) -> dict[str, str]:
    """Derive honest Configuration Center card states (OC11/OC12/OC21).

    ``state`` is the local registry snapshot; ``worlds`` is the runtime list
    of existing world names (filesystem truth); ``probe_ok`` is the derived
    local-storage probe result; ``telegram_state`` is the state supplied by
    the ONB-3.3 telegram backend (write-only token presence + last connection
    test) or None when no backend evidence exists. Returns one CardState per
    card key.
    """
    cards: dict[str, str] = {}
    for key in CLOUD_CARDS:
        cards[key] = "pending"
    # Identity HAS a dedicated contract (auth-vault-credentials, R-ID-01): the
    # card follows the live account slot + credentials mode, never a registry
    # claim.
    cards["identity"] = "configured" if identity_configured(state) else "pending"
    # The importer has no dedicated contract in this change (ONB-3.5): its
    # card exposes entry/pending only and can never be derived to configured
    # from local evidence. The dedicated importer SDD owns completion.
    cards["import"] = "pending"
    # Telegram has a dedicated backend contract (ONB-3.3): its card follows
    # the backend's real evidence; without it the card stays pending.
    cards["telegram"] = (
        telegram_state if telegram_state in CARD_STATES else "pending"
    )
    cards["assistant"] = "configured" if assistant_proven(state) else "pending"
    cards["world"] = "configured" if worlds else "pending"
    cards["locale"] = "configured" if state.get("locale") else "pending"
    cards["offline"] = "configured" if probe_ok else "error"
    return cards


def project_offline(cards: Mapping[str, str]) -> dict[str, Any]:
    """Derive the honest offline/dispositivo breakdown (OC5/OC21).

    ``local_ready`` follows the projected offline card (the storage probe
    round-trip) — the local core (editor, worlds, ideas, plantillas, graph)
    works without connection. ``remote_pending`` lists the remote capabilities
    that still need connectivity or a dedicated contract; none is ever claimed
    available offline.
    """
    return {
        "local_ready": cards.get("offline") == "configured",
        "remote_pending": [
            key for key in REMOTE_CARDS
            if cards.get(key) in ("pending", "requires_connection")
        ],
    }


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