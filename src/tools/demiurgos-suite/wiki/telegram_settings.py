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

Every route is gated on the trusted local principal (``require_principal``)
and fails closed with 401 when absent.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from idea_capture_ui import (
    _ENV_TOKEN_NAME,
    read_env_var,
    validate_token,
    write_env_var,
)

logger = logging.getLogger("demiurgos-telegram")

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


def _evidence(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    evidence = snapshot.get(EVIDENCE_KEY)
    return evidence if isinstance(evidence, dict) else {}


def create_telegram_settings_router(
    require_principal: Callable[[Request], Any],
    registry: Callable[[], Any] | None = None,
) -> APIRouter:
    """Build authenticated /api/telegram routes.

    ``require_principal`` must return a trusted principal for the request or
    None; None maps to 401. ``registry`` returns the authoritative local
    registry (``LocalState``-like with ``snapshot()`` and ``atomic_commit()``);
    it defaults to a read-only snapshot so the router stays importable in
    isolation, and api_server wires the real registry.
    """
    router = APIRouter(prefix="/api/telegram", tags=["telegram-settings"])

    def _registry() -> Any:
        if registry is None:
            return _EmptyRegistry()
        return registry()

    def _guard(request: Request) -> None:
        if require_principal(request) is None:
            raise HTTPException(status_code=401, detail="Autenticación requerida")

    def _commit_evidence(next_state: Mapping[str, Any]) -> None:
        _registry().atomic_commit(dict(next_state))

    def _status_payload(snapshot: Mapping[str, Any]) -> dict[str, Any]:
        present = has_token()
        state = telegram_state(snapshot, present)
        evidence = _evidence(snapshot)
        return {
            "state": state,
            "has_token": present,
            "tested_at": evidence.get("tested_at"),
            "error_code": evidence.get("error_code", ""),
        }

    @router.get("/status")
    def get_status(request: Request) -> dict[str, Any]:
        _guard(request)
        return _status_payload(_registry().snapshot())

    @router.put("/token")
    def put_token(request: Request, body: dict | None = None) -> dict[str, Any]:
        """Store the bot token write-only; never echo or persist the value."""
        _guard(request)
        raw = (body if isinstance(body, dict) else {}).get("token")
        try:
            value = validate_token(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not write_env_var(_ENV_TOKEN_NAME, value):
            raise HTTPException(
                status_code=500,
                detail="No se pudo escribir .env (token no guardado)")
        logger.info("telegram: token configurado (valor no expuesto)")
        # A freshly stored token is untested: the card requires a connection
        # check before it may ever be configured.
        snapshot = _registry().snapshot()
        next_state = dict(snapshot)
        next_state[EVIDENCE_KEY] = {
            "state": "requires_connection",
            "tested_at": None,
            "error_code": "",
        }
        _commit_evidence(next_state)
        return {"state": "requires_connection", "has_token": True}

    @router.delete("/token")
    def clear_token(request: Request) -> dict[str, Any]:
        """Remove the stored token; the card returns to pending."""
        _guard(request)
        write_env_var(_ENV_TOKEN_NAME, "")
        logger.info("telegram: token eliminado (valor no expuesto)")
        snapshot = _registry().snapshot()
        next_state = dict(snapshot)
        next_state.pop(EVIDENCE_KEY, None)
        _commit_evidence(next_state)
        return {"state": "pending", "has_token": False}

    @router.post("/test-connection")
    def run_test(request: Request) -> dict[str, Any]:
        """Test the STORED token against Telegram; never accept one in body.

        Offline/network failure -> requires_connection (retryable). Invalid
        token or API failure -> error. Success -> configured. The token is
        read server-side and never returned or logged.
        """
        _guard(request)
        token = read_env_var(_ENV_TOKEN_NAME)
        if not token:
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "Todavía no hay token guardado. Guardá el token "
                              "del bot antes de probar la conexión.",
                    "code": "no_token",
                })
        result = test_connection(token)
        snapshot = _registry().snapshot()
        next_state = dict(snapshot)
        next_state[EVIDENCE_KEY] = {
            "state": result["state"],
            "tested_at": datetime.now(timezone.utc).isoformat(),
            "error_code": result["error_code"],
        }
        _commit_evidence(next_state)
        logger.info("telegram: prueba de conexión finalizada (estado=%s, "
                    "valor no expuesto)", result["state"])
        evidence = next_state[EVIDENCE_KEY]
        return {
            "state": result["state"],
            "has_token": True,
            "tested_at": evidence["tested_at"],
            "error_code": evidence["error_code"],
            "message": result["message"],
        }

    return router


class _EmptyRegistry:
    """Read-only fallback registry so the router imports without a wired store.

    api_server always wires the real local registry; this only guarantees the
    module is importable standalone and fails loudly if a route is ever used
    with it.
    """

    def snapshot(self) -> dict[str, Any]:
        return {}

    def atomic_commit(self, next_state: Mapping[str, Any]) -> int:
        raise RuntimeError("telegram router used without a wired registry")