# -*- coding: utf-8 -*-
"""Stable identity and the report-signing credential for bug reporting.

The relay anchors a Telegram link to the app's **stable** account key, never to
the session-scoped principal: ``principal_id`` is minted per session
(``local-dev-session-<hex>`` / ``credentials-session-<hex>``), so anchoring a
link to it would kill the link on every logout.

That stable key is, in order:

* the credentials-vault **username**, when the vault is on and an account exists;
* otherwise an ``install_id`` minted **once** and persisted in the local state.

When a link completes, the relay hands back one ``install_token``. It lives here,
server-side, and leaves the process only as the ``x-install-token`` request
header on the way to the relay. It never enters a report bundle, never reaches
the browser and never lands in a log (S15).

The slot is ``capabilities.bugreport`` in the local state registry. Every write
goes through ``LocalState.atomic_commit`` so the slot stays single-source-of-truth.
"""

from __future__ import annotations

import re
import secrets
from typing import Any, Callable, Dict

from local_state import LocalState

#: Prefix for the persisted install identity, so a stale value is recognizable.
INSTALL_ID_PREFIX = "install_"

#: Hex characters after the prefix (12 random bytes).
_INSTALL_ID = re.compile(r"^install_[0-9a-f]{24}$")

#: The relay mints the install token as 32 random bytes rendered as lowercase hex.
_INSTALL_TOKEN = re.compile(r"^[0-9a-f]{64}$")


def _slot(state: Dict[str, Any]) -> Dict[str, Any]:
    """The ``capabilities.bugreport`` slot, created on demand in ``state``."""
    capabilities = state.setdefault("capabilities", {})
    slot = capabilities.get("bugreport")
    if not isinstance(slot, dict):
        slot = {}
        capabilities["bugreport"] = slot
    return slot


def _existing_slot(local_state: LocalState) -> Dict[str, Any]:
    slot = (local_state.snapshot().get("capabilities") or {}).get("bugreport")
    return slot if isinstance(slot, dict) else {}


def account_key(
    local_state: LocalState,
    vault_active: bool,
    *,
    mint: Callable[[], str] | None = None,
) -> str:
    """The stable account key the relay should anchor a link to.

    With the vault on, the account username — the same value the vault itself
    authenticates, so a reinstall with the same account keeps its link. Without
    the vault, an ``install_id`` is minted once and persisted; a second call
    returns the same value, so the link survives restarts and logout.
    """
    state = local_state.snapshot()
    account = (state.get("capabilities") or {}).get("account") or {}
    username = account.get("username") if isinstance(account, dict) else None
    if vault_active and isinstance(username, str) and username.strip():
        return username.strip()

    persisted = _existing_slot(local_state).get("install_id")
    if isinstance(persisted, str) and _INSTALL_ID.match(persisted):
        return persisted

    fresh = INSTALL_ID_PREFIX + (mint() if mint is not None else secrets.token_hex(12))
    if not _INSTALL_ID.match(fresh):
        raise ValueError("install id must be install_<24 lowercase hex>")
    snapshot = local_state.snapshot()
    _slot(snapshot)["install_id"] = fresh
    local_state.atomic_commit(snapshot)
    return fresh


def read_install_token(local_state: LocalState) -> str | None:
    """The stored report-signing token, or ``None`` when it is absent/invalid."""
    token = _existing_slot(local_state).get("install_token")
    return token if isinstance(token, str) and _INSTALL_TOKEN.match(token) else None


def store_install_token(local_state: LocalState, token: str) -> None:
    """Persist the token the relay handed over exactly once, at link completion."""
    if not _INSTALL_TOKEN.match(token):
        raise ValueError("install token must be 64 lowercase hex characters")
    snapshot = local_state.snapshot()
    _slot(snapshot)["install_token"] = token
    local_state.atomic_commit(snapshot)


def clear_install_token(local_state: LocalState) -> None:
    """Forget the token (on revoke, or when the relay reports it invalid)."""
    if "install_token" not in _existing_slot(local_state):
        return
    snapshot = local_state.snapshot()
    _slot(snapshot).pop("install_token", None)
    local_state.atomic_commit(snapshot)


__all__ = [
    "INSTALL_ID_PREFIX",
    "account_key",
    "clear_install_token",
    "read_install_token",
    "store_install_token",
]
