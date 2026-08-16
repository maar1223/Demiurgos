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
    normalize_language,
    read_dotenv_value,
    resolve_ui_language,
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
