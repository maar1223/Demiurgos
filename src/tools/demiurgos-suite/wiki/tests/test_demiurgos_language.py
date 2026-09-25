"""Focused tests for the global UI language contract (DEMIURGOS_LANGUAGE)."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from demiurgos_language import (  # noqa: E402
    DEFAULT_LANGUAGE,
    ENV_NAME,
    LocaleSettings,
    effective_languages,
    normalize_language,
    normalize_locale,
    normalize_region,
    normalize_ui_language_for_domain,
    read_dotenv_value,
    read_persisted_locale,
    resolve_domain_language,
    resolve_ui_language,
    validate_iana_timezone,
)
from local_state import default_state  # noqa: E402


@pytest.mark.parametrize("raw,expected", [
    ("es", "es"),
    ("es-ar", "es"),
    ("es-es", "es"),
    ("es_ar", "es"),
    ("ES", "es"),
    (" en ", "en"),
    ("en-us", "en"),
    ("EN_US", "en"),
    ("", DEFAULT_LANGUAGE),
    (None, DEFAULT_LANGUAGE),
    ("fr", DEFAULT_LANGUAGE),
    ("klingon", DEFAULT_LANGUAGE),
])
def test_normalize_language_maps_supported_codes_and_fails_closed(raw, expected) -> None:
    assert normalize_language(raw) == expected


def test_read_dotenv_value_prefers_clean_unquoted_value(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"DEMIURGOS_LANGUAGE=\"es-ar\"\nSOME_SECRET=top-secret\n",
        encoding="utf-8",
    )
    assert read_dotenv_value(env_file, ENV_NAME) == "es-ar"
    assert read_dotenv_value(env_file, "SOME_SECRET") == "top-secret"
    assert read_dotenv_value(tmp_path / "missing.env", ENV_NAME) == ""


def test_resolve_ui_language_environment_wins_over_env_file(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{ENV_NAME}=en\n", encoding="utf-8")
    missing_state = tmp_path / "no-local-state.json"
    assert resolve_ui_language(
        env_file=env_file, environ={ENV_NAME: "es-ar"}, state_path=missing_state
    ) == "es"
    assert resolve_ui_language(
        env_file=env_file, environ={}, state_path=missing_state
    ) == "en"


def test_resolve_ui_language_defaults_safely_when_unset(tmp_path) -> None:
    assert resolve_ui_language(
        env_file=tmp_path / "missing.env",
        environ={},
        state_path=tmp_path / "no-local-state.json",
    ) == DEFAULT_LANGUAGE


# ---------------------------------------------------------------------------
# G7/OC3 locale: independent domains, region override, IANA timezone
# ---------------------------------------------------------------------------

def test_normalize_region_uppercases_and_strips() -> None:
    assert normalize_region(" ar ") == "AR"
    assert normalize_region("us") == "US"
    assert normalize_region("GLOBAL") == "GLOBAL"
    assert normalize_region(None) is None
    assert normalize_region("") is None
    assert normalize_region("a b") is None


def test_validate_iana_timezone() -> None:
    assert validate_iana_timezone("America/Argentina/Buenos_Aires") is True
    assert validate_iana_timezone("UTC") is True
    assert validate_iana_timezone("Invalid/Zone") is False
    assert validate_iana_timezone("") is False
    assert validate_iana_timezone(None) is False


def test_three_languages_persist_independently() -> None:
    locale = LocaleSettings.from_dict({
        "ui": "es", "conversation": "en", "content": "es",
        "region": "AR", "region_explicit": True,
        "iana_timezone": "America/Argentina/Buenos_Aires",
    })
    assert locale.ui == "es"
    assert locale.conversation == "en"
    assert locale.content == "es"
    assert locale.region == "AR"
    assert locale.region_explicit is True


def test_dialect_not_forced_by_region() -> None:
    locale = normalize_locale({
        "ui": "es", "conversation": "es", "content": "es",
        "region": "MX", "region_explicit": False,
        "iana_timezone": "America/Mexico_City",
    })
    assert locale["ui"] == "es"
    assert locale["conversation"] == "es"
    assert locale["content"] == "es"
    # Region stays explicit-only: it must not rewrite languages.
    assert locale["region"] == "MX"
    assert locale["region_explicit"] is False


def test_normalize_locale_rejects_bad_timezone() -> None:
    import pytest

    with pytest.raises(ValueError):
        normalize_locale({
            "ui": "es", "conversation": "es", "content": "es",
            "region": "AR", "region_explicit": True, "iana_timezone": "GMT+3",
        })


def test_normalize_locale_rejects_invalid_region() -> None:
    import pytest

    with pytest.raises(ValueError):
        normalize_locale({
            "ui": "es", "conversation": "es", "content": "es",
            "region": "AR/BA", "region_explicit": True, "iana_timezone": "UTC",
        })


def test_normalize_ui_language_for_domain_fails_closed() -> None:
    assert normalize_ui_language_for_domain("es-ar") == "es"
    assert normalize_ui_language_for_domain("en-us") == "en"
    assert normalize_ui_language_for_domain("klingon") == DEFAULT_LANGUAGE


# ---------------------------------------------------------------------------
# AD-6/AD-7: persisted-first resolution + explicit domain inheritance
# ---------------------------------------------------------------------------

def _write_state(tmp_path: Path, locale: dict, *, revision: int = 1) -> Path:
    """Write a valid local-state.json holding *locale* and return its path."""
    import json

    state = default_state()
    state["revision"] = revision
    state["locale"] = locale
    path = tmp_path / "local-state.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def _locale(**overrides) -> dict:
    base = {
        "ui": "es",
        "conversation": "es",
        "content": "es",
        "conversation_explicit": False,
        "content_explicit": False,
        "region": None,
        "region_explicit": False,
        "iana_timezone": "UTC",
    }
    base.update(overrides)
    return base


def test_explicit_flags_round_trip_and_legacy_locale_defaults_false() -> None:
    locale = LocaleSettings.from_dict(_locale(conversation_explicit=True, content_explicit=True))
    assert locale.conversation_explicit is True
    assert locale.content_explicit is True
    assert locale.to_dict()["conversation_explicit"] is True
    assert locale.to_dict()["content_explicit"] is True

    legacy = LocaleSettings.from_dict({
        "ui": "en", "conversation": "es", "content": "es",
        "region": None, "region_explicit": False, "iana_timezone": "UTC",
    })
    assert legacy.conversation_explicit is False
    assert legacy.content_explicit is False


def test_effective_languages_inherit_ui_unless_explicit() -> None:
    inherited = effective_languages(LocaleSettings.from_dict(
        _locale(ui="en", conversation="es", content="es")
    ))
    assert inherited == {"ui": "en", "conversation": "en", "content": "en"}

    overridden = effective_languages(LocaleSettings.from_dict(
        _locale(
            ui="en", conversation="es", content="en",
            conversation_explicit=True, content_explicit=False,
        )
    ))
    assert overridden == {"ui": "en", "conversation": "es", "content": "en"}


def test_read_persisted_locale_returns_none_when_absent(tmp_path) -> None:
    assert read_persisted_locale(state_path=tmp_path / "missing.json") is None


def test_read_persisted_locale_fails_safe_on_invalid_state(tmp_path) -> None:
    state = _write_state(tmp_path, _locale(iana_timezone="GMT+3"))
    assert read_persisted_locale(state_path=state) is None


def test_persisted_locale_wins_over_env(tmp_path) -> None:
    state = _write_state(tmp_path, _locale(ui="en"))
    env_file = tmp_path / ".env"
    env_file.write_text(f"{ENV_NAME}=es\n", encoding="utf-8")
    assert resolve_ui_language(
        env_file=env_file,
        environ={ENV_NAME: "es"},
        state_path=state,
    ) == "en"


def test_missing_persisted_locale_falls_back_to_env(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{ENV_NAME}=en\n", encoding="utf-8")
    assert resolve_ui_language(
        env_file=env_file,
        environ={},
        state_path=tmp_path / "missing.json",
    ) == "en"


def test_resolve_domain_language_inheritance_from_persisted(tmp_path) -> None:
    inherited = _write_state(tmp_path, _locale(ui="en"))
    assert resolve_domain_language("conversation", state_path=inherited) == "en"
    assert resolve_domain_language("content", state_path=inherited) == "en"

    explicit_dir = tmp_path / "explicit"
    explicit_dir.mkdir()
    explicit = _write_state(explicit_dir, _locale(
        ui="en", conversation="es", content="en",
        conversation_explicit=True, content_explicit=True,
    ))
    assert resolve_domain_language("conversation", state_path=explicit) == "es"
    assert resolve_domain_language("content", state_path=explicit) == "en"


def test_resolve_domain_language_rejects_unknown_domain() -> None:
    import pytest

    with pytest.raises(ValueError):
        resolve_domain_language("nonsense")


def test_persisted_unsupported_language_normalizes_fail_closed(tmp_path) -> None:
    state = _write_state(tmp_path, _locale(ui="fr", conversation="fr", content="fr"))
    persisted = read_persisted_locale(state_path=state)
    assert persisted is not None
    assert persisted.ui == DEFAULT_LANGUAGE
    assert resolve_ui_language(state_path=state, environ={}) == DEFAULT_LANGUAGE
