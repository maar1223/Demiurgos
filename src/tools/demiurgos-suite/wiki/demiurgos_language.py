"""Language and locale resolution for the Demiurgos runtime.

Two concerns live here:

1. Locale resolution (persisted-first, AD-6): the global UI language is read
   from the persisted ``LocaleSettings`` (``<data_root>/data/local-state.json``);
   ``DEMIURGOS_LANGUAGE`` from env/``.env`` is only a fallback when no persisted
   locale exists. Domain-aware resolvers (``ui``/``conversation``/``content``)
   let the AI path follow the selected locale instead of the environment.
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

from data_root import DataRootNotConfigured, resolve_data_root
from local_state import LocalState
from state_paths import resolve_state_dir

ENV_NAME = "DEMIURGOS_LANGUAGE"
DEFAULT_LANGUAGE = "es"

# UI language codes the current copy supports.
SUPPORTED_UI_LANGUAGES = frozenset({"es", "en"})

# Independent language domains (OC3): each is configured separately.
LOCALE_DOMAINS = ("ui", "conversation", "content")


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
    # AD-7: an explicit domain override. When false (the default, including
    # every legacy persisted locale without these keys) the domain follows UI.
    conversation_explicit: bool = False
    content_explicit: bool = False
    region: str | None = None
    region_explicit: bool = False
    iana_timezone: str = "UTC"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ui": self.ui,
            "conversation": self.conversation,
            "content": self.content,
            "conversation_explicit": self.conversation_explicit,
            "content_explicit": self.content_explicit,
            "region": self.region,
            "region_explicit": self.region_explicit,
            "iana_timezone": self.iana_timezone,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LocaleSettings":
        raw_ui = data.get("ui")
        raw_conversation = data.get("conversation")
        raw_content = data.get("content")
        raw_conversation_explicit = data.get("conversation_explicit", False)
        raw_content_explicit = data.get("content_explicit", False)
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
            conversation_explicit=bool(raw_conversation_explicit),
            content_explicit=bool(raw_content_explicit),
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


def _default_state_path() -> Path:
    """The installation-wide local-state file, resolved on every call.

    Never resolved at import time. Machine state has a platform-defined home, so
    this cannot fail for a missing content root: an installation with no
    persisted locale simply has no file there yet.
    """
    return resolve_state_dir() / "local-state.json"


def read_persisted_locale(*, state_path: Path | None = None) -> LocaleSettings | None:
    """Read the persisted ``LocaleSettings``, or ``None`` when unavailable.

    The state file is read through :class:`LocalState` so the BOM-safety and
    schema-version guarantees of the registry apply. A missing, unreadable, or
    invalid locale never raises here: callers fall back to the env/.env path
    (fail-safe, same contract as :func:`resolve_ui_language`).
    """
    path = Path(state_path) if state_path is not None else _default_state_path()
    if not path.is_file():
        return None
    try:
        snapshot = LocalState(path).snapshot()
    except Exception:
        return None
    raw = snapshot.get("locale")
    if not isinstance(raw, Mapping):
        return None
    try:
        return LocaleSettings.from_dict(raw)
    except ValueError:
        return None


def effective_languages(settings: LocaleSettings) -> dict[str, str]:
    """Resolve the effective language per domain (AD-7).

    ``conversation``/``content`` follow ``ui`` unless their ``*_explicit`` flag
    is set, in which case the persisted domain value is honored.
    """
    ui = normalize_ui_language_for_domain(settings.ui)
    return {
        "ui": ui,
        "conversation": (
            normalize_ui_language_for_domain(settings.conversation)
            if settings.conversation_explicit
            else ui
        ),
        "content": (
            normalize_ui_language_for_domain(settings.content)
            if settings.content_explicit
            else ui
        ),
    }


def _env_language(
    *,
    env_file: Path | None,
    environ: Mapping[str, str] | None,
) -> str:
    """Legacy env/.env fallback, used only when no persisted locale exists."""
    env = os.environ if environ is None else environ
    if env_file is None:
        try:
            env_file = resolve_data_root() / ".env"
        except DataRootNotConfigured:
            env_file = None
    raw = env.get(ENV_NAME, "")
    if not raw and env_file is not None:
        raw = read_dotenv_value(env_file, ENV_NAME)
    return normalize_language(raw)


def resolve_domain_language(
    domain: str,
    *,
    state_path: Path | None = None,
    env_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve one locale domain, persisted-first with env/.env fallback (AD-6).

    The persisted locale is authoritative; env/``.env`` is consulted only when
    no valid persisted locale exists. Unknown domain names fail closed to the
    default language rather than inventing a domain.
    """
    if domain not in LOCALE_DOMAINS:
        raise ValueError(f"unknown locale domain: {domain!r}")
    persisted = read_persisted_locale(state_path=state_path)
    if persisted is not None:
        return effective_languages(persisted)[domain]
    return _env_language(env_file=env_file, environ=environ)


def resolve_ui_language(
    *,
    env_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
    state_path: Path | None = None,
) -> str:
    """Resolve the normalized UI language persisted-first, env fallback.

    ``env_file`` defaults to the ``.env`` of the data root, resolved lazily
    here — never at import time, because the resolver fails loudly when no
    data root is configured. When a persisted locale exists it always wins
    over the environment (LOC-REQ-1).
    """
    return resolve_domain_language(
        "ui", state_path=state_path, env_file=env_file, environ=environ
    )