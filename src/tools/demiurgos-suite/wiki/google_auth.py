"""Google Identity Services id_token verification (auth-google-vault, R-GA1).

Server-side verification of Google id_tokens before a vault session is
issued. The library (``google-auth``) validates the token signature against
Google's certificate chain, expiry, and issuer; this module additionally
enforces the application-level audience (client id) and nonce checks.

Contract:
- ``generate_nonce()`` -> URL-safe random nonce bound to the browser by the
  caller (short-lived cookie).
- ``verify_id_token(id_token, client_id, expected_nonce)`` -> dict with
  ``sub`` (principal id), ``email`` (label), ``nonce``; raises ``ValueError``
  on ANY verification failure (bad signature, expired, wrong iss/aud, missing
  or mismatched nonce).
- ``get_google_client_id()`` -> ``GOOGLE_CLIENT_ID`` from the environment.

NOTE: this module is intentionally NOT network-free. The zero-HTTP-import
guarantee (R-ERK2) applies to ``emergency_key.py`` only; Google login by
design requires network access (JWKS fetch).
"""

from __future__ import annotations

import os
import secrets
import time
from typing import Any

from google.auth import exceptions as google_auth_exceptions
from google.oauth2 import id_token as google_id_token

# Google OpenID issuer for hosted Google accounts (R-GA1, S-GA1a/b).
GOOGLE_ISSUER = "accounts.google.com"


def generate_nonce() -> str:
    """Generate a cryptographically secure nonce for id_token verification."""
    return secrets.token_urlsafe(32)


def _default_request() -> Any:
    """Build a transport for the certificate fetch (lazy, google-auth 2.x).

    ``verify_oauth2_token`` requires a callable ``request`` object used to
    fetch Google's JWKS. Constructed lazily so importing this module never
    pulls an HTTP client; the transport is only materialized at verify time.
    """
    from google.auth.transport import requests as ga_requests

    return ga_requests.Request()


def verify_id_token(
    id_token_str: str,
    client_id: str,
    expected_nonce: str,
    request: Any | None = None,
) -> dict[str, Any]:
    """Verify a Google id_token end-to-end and return its claims.

    Validates signature + expiry via ``google.oauth2.id_token.
    verify_oauth2_token`` (JWKS fetch through ``request``), then enforces the
    application checks: ``iss`` == accounts.google.com, ``aud`` == client_id,
    ``exp`` in the future, and ``nonce`` == expected_nonce.

    Returns a dict with ``sub`` (principal id), ``email`` (label), ``nonce``.

    Raises ``ValueError`` on any failure — the caller maps it to a 401 with
    no session issued (S-GA1b).
    """
    if request is None:
        request = _default_request()
    try:
        claims = google_id_token.verify_oauth2_token(
            id_token_str, request=request, audience=client_id
        )
    except (ValueError, google_auth_exceptions.GoogleAuthError) as exc:
        raise ValueError(f"id_token verification failed: {exc}") from exc

    issuer = claims.get("iss")
    if issuer != GOOGLE_ISSUER:
        raise ValueError(f"id_token issuer mismatch: {issuer!r}")
    audience = claims.get("aud")
    if audience != client_id:
        raise ValueError(f"id_token audience mismatch: {audience!r}")
    expires = claims.get("exp")
    if not isinstance(expires, (int, float)) or expires < time.time():
        raise ValueError("id_token expired or missing exp")
    nonce = claims.get("nonce")
    if nonce != expected_nonce:
        raise ValueError("id_token nonce mismatch")
    subject = claims.get("sub")
    if not subject:
        raise ValueError("id_token missing sub")

    return {
        "sub": subject,
        "email": claims.get("email"),
        "nonce": nonce,
    }


def get_google_client_id() -> str | None:
    """Read ``GOOGLE_CLIENT_ID`` from the environment; None when unset."""
    return os.environ.get("GOOGLE_CLIENT_ID")