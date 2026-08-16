"""Single source of truth for the global Demiurgos UI language.

Every visible assistant/guided copy follows ``DEMIURGOS_LANGUAGE`` from the
project ``.env`` (environment wins, then the file), never the language of an
individual author message. Spanish variants normalize to ``es`` for the
current copy; unsupported values fail closed to the project default.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

ENV_NAME = "DEMIURGOS_LANGUAGE"
DEFAULT_LANGUAGE = "es"

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
