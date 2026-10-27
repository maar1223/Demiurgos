# -*- coding: utf-8 -*-
"""tests/test_bugreport_identity.py — stable account key and the token slot.

The link anchor must be the app's STABLE identity (vault username, else the
``install_id`` minted once), never the session-scoped principal: a session id
would die on every logout and silently unlink the reporter (S10).

The ``install_token`` that signs later reports is stored server-side and validated
on read, so a corrupted or hand-edited state file cannot make the backend send
garbage in an ``x-install-token`` header (S15).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from bugreport_identity import (  # noqa: E402
    account_key,
    clear_install_token,
    install_id,
    read_install_token,
    store_install_token,
)
from local_state import LocalState  # noqa: E402

_TOKEN = "ab" * 32


def _state(tmp_path: Path) -> LocalState:
    return LocalState(tmp_path / "state.json")


def test_without_the_vault_the_install_id_is_minted_once_and_survives_a_reload(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)

    first = account_key(state, vault_active=False)
    second = account_key(state, vault_active=False)

    assert first == second
    assert first.startswith("install_")
    # A fresh registry over the same file returns the same anchor: the link
    # survives a restart, which is the whole point of persisting it.
    reloaded = LocalState(tmp_path / "state.json")
    assert account_key(reloaded, vault_active=False) == first


def test_with_the_vault_the_account_username_is_the_anchor(tmp_path: Path) -> None:
    state = _state(tmp_path)
    snapshot = state.snapshot()
    snapshot.setdefault("capabilities", {})["account"] = {
        "username": "ana",
        "password_hash": None,
        "words_hash": "hash",
    }
    state.atomic_commit(snapshot)

    assert account_key(state, vault_active=True) == "ana"


def test_the_vault_without_an_account_still_falls_back_to_the_install_id(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)

    key = account_key(state, vault_active=True)

    assert key.startswith("install_")


def test_the_pseudonym_id_is_minted_once_even_with_the_vault_on(tmp_path: Path) -> None:
    """S20: the anonymous install id is independent of the account anchor."""
    from local_state import LocalState

    state = LocalState(tmp_path / "state.json")

    first = install_id(state)
    second = install_id(state)

    assert first == second
    assert first.startswith("install_")
    assert len(first) == len("install_") + 24

    # With the vault on, the ACCOUNT anchor is the username while the pseudonym
    # stays this install's own anonymous id.
    snapshot = state.snapshot()
    snapshot.setdefault("capabilities", {})["account"] = {
        "username": "ana",
        "password_hash": None,
        "words_hash": "hash",
    }
    state.atomic_commit(snapshot)
    assert account_key(state, vault_active=True) == "ana"
    assert install_id(state) == first


def test_the_token_round_trips_and_clears(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert read_install_token(state) is None

    store_install_token(state, _TOKEN)
    assert read_install_token(state) == _TOKEN

    clear_install_token(state)
    assert read_install_token(state) is None
    # Clearing twice is a no-op, not an error.
    clear_install_token(state)


def test_a_malformed_token_is_never_stored_or_trusted(tmp_path: Path) -> None:
    state = _state(tmp_path)

    with pytest.raises(ValueError):
        store_install_token(state, "not-a-token")
    with pytest.raises(ValueError):
        store_install_token(state, "AB" * 32)  # uppercase is not the minted shape

    snapshot = state.snapshot()
    snapshot.setdefault("capabilities", {})["bugreport"] = {"install_token": "garbage"}
    state.atomic_commit(snapshot)
    assert read_install_token(state) is None
