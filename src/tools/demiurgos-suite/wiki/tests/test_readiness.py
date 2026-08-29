"""ONB-1.8 — local_editor readiness probe: storage write→read→delete round-trip.
Readiness is derived runtime truth, never configuration claims.

Also covers the vault-settings-configure identity contract (R-ID-01,
S-ID-01a/b): the identity card is ``configured`` ONLY when the persisted
vault flag is on (``capabilities.vault.enabled``, PRIMARY) OR when
``DEMIURGOS_AUTH_MODE=credentials`` is active; an account alone never
configures it (S-ID-01b) and registry claims never configure it.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from readiness import (  # noqa: E402
    identity_configured,
    local_editor_ready,
    probe_local_storage,
    project_cards,
    project_offline,
)


def test_probe_round_trips_and_cleans_up(tmp_path: Path) -> None:
    result = probe_local_storage(tmp_path)
    assert result["probe"] == "local_editor"
    assert result["ok"] is True
    probe_dir = tmp_path / "data" / "probes"
    assert list(probe_dir.iterdir()) == [], "probe file must be deleted"


def test_local_editor_ready_derives_from_probe(tmp_path: Path) -> None:
    assert local_editor_ready(tmp_path) is True


def test_probe_fails_safely_when_storage_is_unwritable(tmp_path: Path) -> None:
    blocked = tmp_path / "data"
    blocked.write_text("occupied", encoding="utf-8")  # data/ is a file, not a dir
    result = probe_local_storage(tmp_path)
    assert result["probe"] == "local_editor"
    assert result["ok"] is False
    assert result["detail"]
    assert local_editor_ready(tmp_path) is False


def test_probe_readback_mismatch_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_write = Path.write_text

    def broken_write(self, *args, **kwargs):
        # Whatever the probe intends to write, the disk returns tampered bytes.
        return real_write(self, "tampered", *args[1:], **kwargs)

    monkeypatch.setattr(Path, "write_text", broken_write)
    result = probe_local_storage(tmp_path)
    assert result["ok"] is False
    assert "mismatch" in result["detail"]


# ---------------------------------------------------------------------------
# R-ID-01 — identity card dedicated contract (S-ID-01a/b)
# ---------------------------------------------------------------------------


def _account_state(username: str | None = "ada", words_hash: str | None = "$argon2id$abc") -> dict:
    return {
        "capabilities": {
            "account": {
                "username": username,
                "password_hash": None,
                "words_hash": words_hash,
            }
        }
    }


def _vault_on_state(username: str | None = "ada",
                    words_hash: str | None = "$argon2id$abc") -> dict:
    """Account slot + persisted vault flag ON (S-ID-01a)."""
    state = _account_state(username, words_hash)
    state["capabilities"]["vault"] = {"enabled": True, "reauth_interval_d": 14}
    return state


def test_identity_configured_when_vault_flag_on(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """S-ID-01a — the persisted vault flag (with an account) configures
    identity, regardless of auth mode."""
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    cards = project_cards(_vault_on_state(), worlds=[], probe_ok=True)
    assert cards["identity"] == "configured"
    # The identity contract is local configuration, not connectivity: it must
    # never surface as remote-pending (R-ID-01).
    assert "identity" not in project_offline(cards)["remote_pending"]


def test_identity_pending_when_account_exists_but_vault_off(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """S-ID-01b — an account alone NEVER configures identity: without the
    vault flag (or the env override) the card stays pending."""
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    cards = project_cards(_account_state(), worlds=[], probe_ok=True)
    assert cards["identity"] == "pending"
    # The identity contract is local configuration, not connectivity: it must
    # never surface as remote-pending (R-ID-01).
    assert "identity" not in project_offline(cards)["remote_pending"]


def test_identity_configured_when_credentials_mode_active(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """S-ID-01b — credentials mode configures identity even before the account
    is created (onboarding needs the card available)."""
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "credentials")
    cards = project_cards({}, worlds=[], probe_ok=True)
    assert cards["identity"] == "configured"


def test_identity_pending_without_account_and_without_credentials_mode(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """S-ID-01c — no account and a non-credentials mode leaves identity
    pending."""
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "local-dev")
    cards = project_cards({}, worlds=[], probe_ok=True)
    assert cards["identity"] == "pending"


def test_identity_pending_ignores_registry_claims(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    cards = project_cards(
        {"capabilities": {"identity": "configured"}}, worlds=[], probe_ok=True)
    assert cards["identity"] == "pending"


def test_identity_pending_for_partial_account(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A slot with a username but no words hash is not a configured account."""
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    cards = project_cards(_account_state(words_hash=None), worlds=[], probe_ok=True)
    assert cards["identity"] == "pending"
    cards = project_cards(_account_state(username=None), worlds=[], probe_ok=True)
    assert cards["identity"] == "pending"


def test_identity_configured_helper_contract(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "credentials")
    assert identity_configured() is True
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "CREDENTIALS")
    assert identity_configured() is True  # mode is case-normalized
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "local-dev")
    assert identity_configured() is False
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    assert identity_configured() is False
    # Flag branch is mode-independent (flag-primary contract, S-ID-01a/b).
    assert identity_configured(_vault_on_state()) is True
    assert identity_configured(_account_state()) is False  # account alone, flag OFF
    assert identity_configured(_account_state(words_hash=None)) is False


def test_identity_configured_flag_primary_without_env(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Direct helper contract mapping S-ID-01a/b: with no env override the
    persisted flag alone decides identity — ON configures it, OFF leaves it
    pending even when an account exists."""
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    assert identity_configured(_vault_on_state()) is True   # S-ID-01a
    assert identity_configured(_account_state()) is False   # S-ID-01b