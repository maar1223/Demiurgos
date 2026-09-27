#!/usr/bin/env python3
"""Edge TTS wrapper that selects the voice from the Demiurgos UI language.

Hermes invokes a "command TTS provider" as a shell command that receives a
text file and must write the synthesized audio to an output path::

    python scripts/hermes_tts_voice.py <input_text_path> <output_audio_path>

This wrapper picks the Microsoft Edge TTS voice from ``DEMIURGOS_LANGUAGE``
(``es`` or ``en``) so Spanish output uses a Spanish voice and English uses an
English voice.

The language is resolved with this precedence:

1. the ``DEMIURGOS_LANGUAGE`` environment variable;
2. the value parsed from ``$DEMIURGOS_ROOT/.env`` (falling back to
   ``$DEMIURGOS_DATA_ROOT/.env``);
3. the default ``es``.

Constraints honored here:

- Standard library only. The Hermes virtual environment does not ship
  ``platformdirs``, so this script must NOT import any repository module
  (``data_root``, ``demiurgos_language``, ...). It reads the language from the
  process environment and a plain ``.env`` file instead.
- The ``edge-tts`` binary lives in the Hermes virtual environment. It is
  located with :func:`shutil.which` and falls back to the documented path
  ``~/.hermes/hermes-agent/venv/bin/edge-tts``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

#: Environment variable that carries the Demiurgos UI language.
LANGUAGE_ENV_VAR = "DEMIURGOS_LANGUAGE"

#: Language used when nothing valid is configured.
DEFAULT_LANGUAGE = "es"

#: Languages accepted by :func:`resolve_language`; anything else falls back.
SUPPORTED_LANGUAGES = frozenset({"es", "en"})

#: Edge TTS voice per supported language.
VOICES: dict[str, str] = {
    "es": "es-MX-DaliaNeural",  # Neutral Latin-American Spanish.
    "en": "en-US-AriaNeural",   # Hermes default English voice.
}

#: Documented fallback when ``edge-tts`` is not on ``PATH``.
FALLBACK_EDGE_TTS = Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "edge-tts"

#: Repository roots that may contain the ``.env`` file, in lookup order.
_ENV_ROOT_VARS = ("DEMIURGOS_ROOT", "DEMIURGOS_DATA_ROOT")


class TtsSynthesisError(RuntimeError):
    """Raised when ``edge-tts`` fails or produces no audio."""


def parse_env_text(env_file_text: str | None) -> dict[str, str]:
    """Parse a ``.env``-style text into a ``KEY=VALUE`` mapping.

    Blank lines and lines whose first non-space character is ``#`` are ignored,
    an optional leading ``export `` is tolerated, and surrounding single or
    double quotes are stripped from the value.
    """
    if not env_file_text:
        return {}

    values: dict[str, str] = {}
    for raw_line in env_file_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def resolve_language(env: Mapping[str, str], env_file_text: str | None) -> str:
    """Resolve the UI language from the environment and a ``.env`` text.

    Precedence: ``env[DEMIURGOS_LANGUAGE]`` (when the key is present) wins over
    the value parsed from ``env_file_text``, which wins over the ``es`` default.
    The result is lowercased and restricted to :data:`SUPPORTED_LANGUAGES`;
    any other value resolves to ``es``.
    """
    if LANGUAGE_ENV_VAR in env:
        raw = env[LANGUAGE_ENV_VAR]
    else:
        raw = parse_env_text(env_file_text).get(LANGUAGE_ENV_VAR)

    if raw is None:
        return DEFAULT_LANGUAGE

    normalized = raw.strip().lower()
    if normalized in SUPPORTED_LANGUAGES:
        return normalized
    return DEFAULT_LANGUAGE


def resolve_voice(language: str) -> str:
    """Map a language to its Edge TTS voice, defaulting to the ``es`` voice."""
    return VOICES.get(language, VOICES[DEFAULT_LANGUAGE])


def read_env_language_file() -> str | None:
    """Return the text of ``<root>/.env``, or ``None`` when unreadable.

    Looks under ``$DEMIURGOS_ROOT`` first and ``$DEMIURGOS_DATA_ROOT`` second,
    returning the first file that can be read successfully.
    """
    for var in _ENV_ROOT_VARS:
        root = os.environ.get(var)
        if not root:
            continue
        try:
            return (Path(root) / ".env").read_text(encoding="utf-8")
        except OSError:
            continue
    return None


def find_edge_tts() -> str | None:
    """Locate the ``edge-tts`` binary on ``PATH`` or at the fallback path."""
    found = shutil.which("edge-tts")
    if found:
        return found
    if FALLBACK_EDGE_TTS.is_file() and os.access(FALLBACK_EDGE_TTS, os.X_OK):
        return str(FALLBACK_EDGE_TTS)
    return None


def _as_text(data: object) -> str:
    """Decode captured subprocess output for an error message."""
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return str(data)


def synthesize(
    text_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    voice: str,
    edge_tts_bin: str,
) -> None:
    """Synthesize ``text_path`` into ``output_path`` with the given voice.

    Runs ``edge-tts --voice <voice> -f <text_path> --write-media <output_path>``.
    Any pre-existing file at ``output_path`` is removed first, so a success
    verdict always reflects THIS run rather than stale audio. Raises
    :class:`TtsSynthesisError` when the process cannot be spawned, exits
    non-zero, or leaves no usable output file.
    """
    output = Path(output_path)
    try:
        output.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise TtsSynthesisError(
            f"cannot clear existing output file {str(output_path)!r}: {exc}"
        ) from exc

    command = [
        edge_tts_bin,
        "--voice", voice,
        "-f", str(text_path),
        "--write-media", str(output_path),
    ]
    try:
        completed = subprocess.run(command, check=False, capture_output=True)
    except OSError as exc:
        raise TtsSynthesisError(
            f"failed to run edge-tts at {edge_tts_bin!r}: {exc}"
        ) from exc

    if completed.returncode != 0:
        detail = _as_text(completed.stderr).strip()
        message = f"edge-tts exited with code {completed.returncode}"
        if detail:
            message = f"{message}: {detail}"
        raise TtsSynthesisError(message)

    if not output.is_file() or output.stat().st_size == 0:
        raise TtsSynthesisError(
            f"edge-tts produced no audio at {str(output_path)!r}"
        )


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(
            "usage: hermes_tts_voice.py <input_text_path> <output_audio_path>",
            file=sys.stderr,
        )
        return 2

    text_path, output_path = args

    try:
        text = Path(text_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(
            f"hermes_tts_voice: cannot read input text file {text_path!r}: {exc}",
            file=sys.stderr,
        )
        return 1

    if not text.strip():
        print(
            f"hermes_tts_voice: input text file {text_path!r} is empty",
            file=sys.stderr,
        )
        return 1

    language = resolve_language(os.environ, read_env_language_file())
    voice = resolve_voice(language)

    edge_tts_bin = find_edge_tts()
    if edge_tts_bin is None:
        print(
            "hermes_tts_voice: 'edge-tts' binary not found on PATH or at "
            f"{str(FALLBACK_EDGE_TTS)!r}",
            file=sys.stderr,
        )
        return 1

    try:
        synthesize(text_path, output_path, voice, edge_tts_bin)
    except TtsSynthesisError as exc:
        print(f"hermes_tts_voice: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
