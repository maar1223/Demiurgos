"""Language and locale resolution for the Demiurgos runtime.

Two concerns live here:

1. The global UI language (``DEMIURGOS_LANGUAGE`` from env/.env) used for the
   current copy — unchanged legacy contract.
2. G7/OC3 locale settings: independent UI/conversation/content languages, an
   explicit region override, and an IANA timezone. Timestamps are stored in UTC;
   the IANA zone governs presentation only. A region MAY suggest values but is
   NEVER applied silently.

Locale values are validated here and persisted by the onboarding step 0 through
the local state registry. Unsupported input fails closed (never invented).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ENV_NAME = "DEMIURGOS_LANGUAGE"
DEFAULT_LANGUAGE = "es"

# UI language codes the current copy supports.
SUPPORTED_UI_LANGUAGES = frozenset({"es", "en"})

# Independent language domains (OC3): each is configured separately.
LOCALE_DOMAINS = ("ui", "conversation", "content")

# Demiurgos/ (wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> root)
_PROJECT_ROOT = Path(__file__).resolve().parents[4]


def normalize_language(raw: str | None) -> str:
    """Normalize a configured language code to the UI copy key (es|en)."""
    value = (raw or "").strip().lower().replace("_", "-")
    if value == "es" or value.startswith("es-"):
        return "es"
    if value == "en" or value.startswith("en"):
        return "en"
    return DEFAULT_LANGUAGE


def normalize_region(raw: str | None) -> str | None:
    """Normalize an explicit region override (ISO-style, uppercase).

    Returns None when the value is empty/garbage so the caller can decide
    whether a region is required. No dialect is ever forced from a region.
    """
    if not isinstance(raw, str):
        return None
    value = raw.strip().upper()
    if not value or not value.isalnum():
        return None
    return value


def validate_iana_timezone(raw: str | None) -> bool:
    """True when *raw* is a valid IANA timezone identifier (e.g. ``America/Argentina/Buenos_Aires``)."""
    if not isinstance(raw, str) or not raw.strip():
        return False
    try:
        ZoneInfo(raw.strip())
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def normalize_ui_language_for_domain(raw: str | None) -> str:
    """Normalize a domain language to a supported UI/assistant/content code.

    Fails closed to the configured UI language default; a dialect is never
    silently forced by a region.
    """
    value = (raw or "").strip().lower().replace("_", "-")
    if value == "es" or value.startswith("es-"):
        return "es"
    if value == "en" or value.startswith("en"):
        return "en"
    return DEFAULT_LANGUAGE


@dataclass(frozen=True)
class LocaleSettings:
    """Validated G7/OC3 locale. Serialized to/from the local state registry."""

    ui: str = "es"
    conversation: str = "es"
    content: str = "es"
    region: str | None = None
    region_explicit: bool = False
    iana_timezone: str = "UTC"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ui": self.ui,
            "conversation": self.conversation,
            "content": self.content,
            "region": self.region,
            "region_explicit": self.region_explicit,
            "iana_timezone": self.iana_timezone,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LocaleSettings":
        raw_ui = data.get("ui")
        raw_conversation = data.get("conversation")
        raw_content = data.get("content")
        raw_region = data.get("region")
        raw_explicit = data.get("region_explicit", False)
        raw_tz = data.get("iana_timezone")

        ui = normalize_ui_language_for_domain(raw_ui)
        conversation = normalize_ui_language_for_domain(raw_conversation)
        content = normalize_ui_language_for_domain(raw_content)
        if not ui or not conversation or not content:
            raise ValueError("locale requires UI, conversation and content languages")

        region = normalize_region(raw_region) if raw_region is not None else None
        if raw_region is not None and region is None:
            raise ValueError("region override is not valid")

        if not validate_iana_timezone(raw_tz):
            raise ValueError("iana_timezone must be a valid IANA timezone identifier")

        return cls(
            ui=ui,
            conversation=conversation,
            content=content,
            region=region,
            region_explicit=bool(raw_explicit),
            iana_timezone=raw_tz.strip(),
        )


def normalize_locale(data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize locale input for persistence.

    Raises ValueError on invalid input (callers map to 422 without mutation).
    Returns the canonical serializable dict.
    """
    return LocaleSettings.from_dict(data).to_dict()


def read_dotenv_value(env_file: Path, name: str) -> str:
    """Read one value from a project .env (gitignored); never stored in code."""
    if not env_file.is_file():
        return ""
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def resolve_ui_language(
    *,
    env_file: Path = _PROJECT_ROOT / ".env",
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve the normalized UI language with a safe default on failure."""
    env = os.environ if environ is None else environ
    raw = env.get(ENV_NAME) or read_dotenv_value(env_file, ENV_NAME)
    return normalize_language(raw)