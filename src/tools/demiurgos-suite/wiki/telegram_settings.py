# -*- coding: utf-8 -*-
"""ONB-3.3 — Telegram configuration backend (token write-only).

The Telegram card is independently resumable and exposes the four contractual
card states (OC12): ``pending``, ``requires_connection``, ``configured``, and
``error``. Readiness is never overstated:

- No stored token -> ``pending`` (card actionable: store a token).
- Stored token, connection not proven -> ``requires_connection`` (offline or
  never tested; the card stays actionable and retryable).
- Stored token + a real Telegram Bot API ``getMe`` check that succeeded ->
  ``configured`` (server-side proof, not a local claim).
- Stored token + a failed check (invalid token, API error) -> ``error``.

Secret boundary (ONB-2.4 contract, reused): the token lives ONLY in the
project ``.env`` as ``TELEGRAM_BOT_TOKEN``, written atomically by the same
writer the idea-capture panel uses (``idea_capture_ui.write_env_var``,
comment/unrelated-variable preserving). It is write-only: it is accepted in
request payloads, never returned, never logged, and never stored in the local
registry. The registry keeps only the test evidence (state, timestamp,
machine-readable error code) under ``telegram_evidence``.

This module now exposes ONLY the pure helpers reused by the idea-capture path
(``telegram_state``, ``has_token``, ``test_connection``, ``EVIDENCE_KEY``). The
duplicate Telegram settings router was retired; the idea-capture probe
(``POST /api/idea-capture/test-connection``) now owns connection testing.
"""

from __future__ import annotations

from typing import Any, Mapping

import requests

from idea_capture_ui import (
    _ENV_TOKEN_NAME,
    read_env_var,
)

_TELEGRAM_API = "https://api.telegram.org"
_CONNECTION_TIMEOUT = 15

# Card states (OC12) — same vocabulary as the readiness projection.
CARD_STATES = ("pending", "configured", "requires_connection", "error")

# Registry evidence key for the last connection-test outcome. The token
# itself is NEVER stored here.
EVIDENCE_KEY = "telegram_evidence"


def telegram_state(state: Mapping[str, Any], has_token: bool) -> str:
    """Derive the honest telegram card state from registry evidence.

    ``has_token`` is the write-only presence probe (``.env``). Evidence is the
    last connection-test outcome stored in the registry; without a token the
    card is always ``pending`` (a stale test result is meaningless).
    """
    if not has_token:
        return "pending"
    evidence = state.get(EVIDENCE_KEY)
    if not isinstance(evidence, Mapping):
        return "requires_connection"
    current = evidence.get("state")
    if current in CARD_STATES and current != "pending":
        return current
    return "requires_connection"


def has_token() -> bool:
    """Write-only presence probe: is a bot token stored? Value never leaves
    this function; only the boolean is exposed to callers."""
    return bool(read_env_var(_ENV_TOKEN_NAME))


def test_connection(token: str, api_base: str = _TELEGRAM_API) -> dict[str, Any]:
    """Run a real Telegram Bot API ``getMe`` check; never echoes the token.

    Returns ``{"state", "error_code", "message"}``. Network/offline failures
    map to ``requires_connection`` (the card stays actionable and retryable);
    invalid/API failures map to ``error``; a successful check maps to
    ``configured``. The token is used server-side only.
    """
    try:
        resp = requests.get(f"{api_base}/bot{token}/getMe",
                            timeout=_CONNECTION_TIMEOUT)
    except requests.RequestException:
        return {
            "state": "requires_connection",
            "error_code": "network",
            "message": "No se pudo contactar la API de Telegram. "
                       "Verificá la conexión e intentá de nuevo.",
        }
    if resp.status_code == 401:
        return {
            "state": "error",
            "error_code": "invalid_token",
            "message": "El token guardado no es válido o fue revocado. "
                       "Guardá un token nuevo.",
        }
    if resp.status_code >= 400:
        return {
            "state": "error",
            "error_code": "telegram_http",
            "message": f"Telegram respondió con error HTTP {resp.status_code}. "
                       "Reintentá en unos segundos.",
        }
    try:
        data = resp.json()
    except ValueError:
        data = None
    if not isinstance(data, dict) or not data.get("ok"):
        return {
            "state": "error",
            "error_code": "telegram_api",
            "message": "Telegram no validó el token. Revisalo e intentá de nuevo.",
        }
    return {
        "state": "configured",
        "error_code": "",
        "message": "Conexión verificada con Telegram.",
    }
