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
    normalize_language,
    normalize_locale,
    normalize_region,
    normalize_ui_language_for_domain,
    read_dotenv_value,
    resolve_ui_language,
    validate_iana_timezone,
)


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
    assert resolve_ui_language(env_file=env_file, environ={ENV_NAME: "es-ar"}) == "es"
    assert resolve_ui_language(env_file=env_file, environ={}) == "en"


def test_resolve_ui_language_defaults_safely_when_unset(tmp_path) -> None:
    assert resolve_ui_language(env_file=tmp_path / "missing.env", environ={}) == DEFAULT_LANGUAGE


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
