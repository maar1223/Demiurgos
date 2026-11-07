"""Durable guided/co-creation sessions survive a re-login.

A credentials/local-dev principal id is minted per login. Durable sessions are
owned by an ``authorization_binding``; if that binding is the per-login
principal, every re-login (or session-expiry) orphans the session and the next
continuation fails with HTTP 401. The store normalizes the binding to the
installation identity, so a re-login of the same install still recovers.
"""

from __future__ import annotations

import sys
from pathlib import Path

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from co_creation_session_store import CoCreationSessionStore  # noqa: E402
from guided_session_store import GuidedSessionStore  # noqa: E402


_EPHEMERAL_PREFIXES = ("credentials-session-", "local-dev-session-")
_INSTALL_BINDING = "install:install_0123456789abcdef01234567"


def _normalize(value: str) -> str:
    return _INSTALL_BINDING if value.startswith(_EPHEMERAL_PREFIXES) else value


def test_guided_session_survives_a_relogin(tmp_path: Path) -> None:
    store = GuidedSessionStore(
        db_path=tmp_path / "guided.sqlite3", binding_normalizer=_normalize,
    )
    store.create("guided-1", "Vibrantes", "credentials-session-first")

    recovered = store.recover("guided-1", "credentials-session-second")

    assert recovered is not None
    assert recovered.session_id == "guided-1"


def test_guided_session_created_before_the_fix_is_adopted(tmp_path: Path) -> None:
    path = tmp_path / "guided.sqlite3"
    legacy = GuidedSessionStore(db_path=path)
    legacy.create("guided-legacy", "Vibrantes", "credentials-session-old")

    upgraded = GuidedSessionStore(db_path=path, binding_normalizer=_normalize)

    assert upgraded.recover("guided-legacy", "credentials-session-new") is not None


def test_guided_session_still_rejects_a_foreign_binding(tmp_path: Path) -> None:
    store = GuidedSessionStore(
        db_path=tmp_path / "guided.sqlite3", binding_normalizer=_normalize,
    )
    store.create("guided-1", "Vibrantes", "credentials-session-first")

    assert store.recover("guided-1", "someone-else") is None


def test_co_creation_session_survives_a_relogin(tmp_path: Path) -> None:
    store = CoCreationSessionStore(
        db_path=tmp_path / "co.sqlite3", binding_normalizer=_normalize,
    )
    store.create(
        "co-1",
        "principal",
        "credentials-session-first",
        world="Vibrantes",
        author_input="hola",
    )

    assert store.recover("co-1", "credentials-session-second") is not None


def test_production_normalizer_maps_per_login_principals(monkeypatch) -> None:
    import api_server

    monkeypatch.setattr(api_server, "_local_state", lambda: object())
    monkeypatch.setattr(
        api_server, "_install_identity", lambda state: "install_stable123",
    )

    assert (
        api_server._durable_session_binding("credentials-session-abc")
        == "install:install_stable123"
    )
    assert (
        api_server._durable_session_binding("local-dev-session-abc")
        == "install:install_stable123"
    )
    assert api_server._durable_session_binding("install:keep") == "install:keep"
    assert api_server._durable_session_binding("someone-else") == "someone-else"
