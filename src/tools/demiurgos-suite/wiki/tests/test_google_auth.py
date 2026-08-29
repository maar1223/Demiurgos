"""R-GA1 — Google id_token verification (auth-google-vault).

Unit tests for ``google_auth.verify_id_token``: mock
``google.oauth2.id_token.verify_oauth2_token`` and prove that issuer,
audience, expiry, and nonce failures each raise ``ValueError`` (mapped to
401 by the API layer in PR 2, S-GA1b).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest
from google.auth import exceptions as google_auth_exceptions
from google.oauth2 import id_token as google_id_token

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_WIKI))

from google_auth import (  # noqa: E402
    GOOGLE_ISSUER,
    generate_nonce,
    get_google_client_id,
    verify_id_token,
)

CLIENT_ID = "test-client-id.apps.googleusercontent.com"
NONCE = "test-nonce"


def _valid_claims(**overrides: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "iss": GOOGLE_ISSUER,
        "aud": CLIENT_ID,
        "sub": "google-user-123",
        "email": "user@example.com",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
        "nonce": NONCE,
    }
    claims.update(overrides)
    return claims


def _mock_verify(monkeypatch: pytest.MonkeyPatch, claims: dict[str, Any]) -> None:
    """Patch verify_oauth2_token to return claims, recording call kwargs."""
    captured: dict[str, Any] = {}

    def fake_verify(token: str, request: Any = None, **kwargs: Any) -> dict[str, Any]:
        captured["request"] = request
        captured["kwargs"] = kwargs
        return claims

    monkeypatch.setattr(google_id_token, "verify_oauth2_token", fake_verify)
    return captured


def test_verify_valid_token_returns_sub_email_nonce(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _mock_verify(monkeypatch, _valid_claims())
    result = verify_id_token("token", CLIENT_ID, NONCE, request=object())
    assert result == {"sub": "google-user-123", "email": "user@example.com", "nonce": NONCE}
    # The wrapper must forward audience + transport to the library.
    assert captured["kwargs"].get("audience") == CLIENT_ID
    assert captured["request"] is not None


@pytest.mark.parametrize(
    "overrides, fragment",
    [
        ({"iss": "evil-issuer.example"}, "issuer"),
        ({"iss": None}, "issuer"),
        ({"aud": "other-client-id"}, "audience"),
        ({"aud": None}, "audience"),
        ({"exp": int(time.time()) - 10}, "expired"),
        ({"exp": None}, "expired"),
        ({"nonce": "wrong-nonce"}, "nonce"),
        ({"nonce": None}, "nonce"),
    ],
)
def test_verify_rejects_bad_claims_with_value_error(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, Any], fragment: str
) -> None:
    _mock_verify(monkeypatch, _valid_claims(**overrides))
    with pytest.raises(ValueError, match=fragment):
        verify_id_token("token", CLIENT_ID, NONCE, request=object())


def test_verify_propagates_library_signature_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_verify(token: str, request: Any = None, **kwargs: Any) -> dict[str, Any]:
        raise ValueError("Invalid token signature")

    monkeypatch.setattr(google_id_token, "verify_oauth2_token", failing_verify)
    with pytest.raises(ValueError, match="signature"):
        verify_id_token("bad-token", CLIENT_ID, NONCE, request=object())


def test_verify_converts_library_issuer_error_to_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_verify(token: str, request: Any = None, **kwargs: Any) -> dict[str, Any]:
        raise google_auth_exceptions.GoogleAuthError("Wrong issuer")

    monkeypatch.setattr(google_id_token, "verify_oauth2_token", failing_verify)
    with pytest.raises(ValueError, match="issuer"):
        verify_id_token("token", CLIENT_ID, NONCE, request=object())


def test_generate_nonce_is_urlsafe_and_long_enough() -> None:
    nonce = generate_nonce()
    assert len(nonce) >= 32
    # token_urlsafe alphabet: A-Za-z0-9-_ (mixed occurrences are valid).
    assert all(c.isalnum() or c in ("-", "_") for c in nonce)


def test_get_google_client_id_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    assert get_google_client_id() == CLIENT_ID


def test_get_google_client_id_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    assert get_google_client_id() is None
    assert os.environ.get("GOOGLE_CLIENT_ID") is None