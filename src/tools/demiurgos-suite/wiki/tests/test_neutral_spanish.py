# -*- coding: utf-8 -*-
"""Backend neutral-Spanish guard (PER-REQ-1, AD-9).

Loads the canonical blocklist ``frontend/src/i18n/forbidden.json`` — the same
source the vitest catalogue guard consumes — and asserts the built Spanish
identity/system prompt contains zero prohibited voseo/regionalism tokens and
zero mojibake. The English prompt must request English output.

This test lives in the standard backend test directory, so the usual
``pytest src/tools/demiurgos-suite/wiki/tests`` run enforces it.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from demiurgos_personality import build_identity_prompt  # noqa: E402


def _find_forbidden() -> Path:
    """Locate the canonical blocklist by walking up to the repository root."""
    for parent in (_HERE, *_HERE.parents):
        candidate = parent / "frontend" / "src" / "i18n" / "forbidden.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("frontend/src/i18n/forbidden.json not found")


_FORBIDDEN = json.loads(_find_forbidden().read_text(encoding="utf-8"))

_VERB_TOKENS = {token.lower() for token in _FORBIDDEN["verbs"]}
_EXPRESSIONS = [token.lower() for token in _FORBIDDEN["expressions"]]
_IMPERATIVE_STEMS = set(_FORBIDDEN["imperativeStems"])
_MOJIBAKE_CODEPOINTS = set(_FORBIDDEN["mojibakeCodepoints"])

# The exact voseo forms the spec names as present in the old prompt
# (PER-REQ-1, "Assistant identity prompt is neutral Spanish").
_KNOWN_VOSEO_FORMS = (
    "NO sos",
    "Respondé",
    "Usá",
    "informalo",
    "ofrecete",
    "indicá",
    "nombrá",
    "buscá",
    "usá",
    "afirmes",
    "chequear",
)


def _tokens_of(value: str) -> list[str]:
    """Mirror the frontend guard's tokenizer (lowercase + non-letter splits)."""
    return [token for token in re.split(r"[^a-záéíóúñü]+", value.lower()) if token]


def _blocklist_hit(value: str) -> str | None:
    lower = value.lower()
    for expression in _EXPRESSIONS:
        if expression in lower:
            return expression
    for token in _tokens_of(value):
        if token in _VERB_TOKENS:
            return token
        # Unambiguous first-conjugation voseo imperative: stem + "á".
        if token.endswith("á") and token[:-1] in _IMPERATIVE_STEMS:
            return token
    return None


def _mojibake_hit(text: str) -> str | None:
    for char in text:
        codepoint = ord(char)
        if codepoint in _MOJIBAKE_CODEPOINTS:
            return f"U+{codepoint:X} ({char})"
    return None


def test_spanish_identity_prompt_has_zero_blocklist_tokens() -> None:
    prompt = build_identity_prompt("Aurelia", language="es")
    hit = _blocklist_hit(prompt)
    assert hit is None, f"Spanish identity prompt contains blocked token {hit!r}"


def test_spanish_identity_prompt_has_no_mojibake() -> None:
    prompt = build_identity_prompt("Aurelia", language="es")
    hit = _mojibake_hit(prompt)
    assert hit is None, f"Spanish identity prompt contains mojibake {hit}"


def test_spanish_identity_prompt_replaces_known_voseo_forms() -> None:
    lowered = build_identity_prompt("Aurelia", language="es").lower()
    for form in _KNOWN_VOSEO_FORMS:
        assert form.lower() not in lowered, f"voseo form {form!r} survived de-voseo"


def test_spanish_identity_prompt_preserves_identity_and_multi_world_search() -> None:
    prompt = build_identity_prompt("Aurelia", language="es")
    assert "Asistente Demiurgos" in prompt
    assert "Transparencia de mundo" in prompt
    assert "otros mundos" in prompt


def test_english_identity_prompt_requests_english_output() -> None:
    prompt = build_identity_prompt("Aurelia", language="en")
    assert "Answer in English" in prompt
    assert "You are not Gentle AI" in prompt


def test_english_identity_prompt_has_no_mojibake() -> None:
    prompt = build_identity_prompt("Aurelia", language="en")
    hit = _mojibake_hit(prompt)
    assert hit is None, f"English identity prompt contains mojibake {hit}"


def test_canonical_blocklist_file_is_well_formed() -> None:
    assert _FORBIDDEN["verbs"]
    assert _FORBIDDEN["expressions"]
    assert _FORBIDDEN["imperativeStems"]
    assert _FORBIDDEN["mojibakeCodepoints"]
