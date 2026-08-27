"""MediaEnrichProvider dispatch tests (SDD idea-capture-ai-gate, Phase 3, R-5).

Covers the provider-level contract: TEXT delegates to the Hermes classifier
(S-5.1), IMAGE runs the flag-gated vision callable (S-5.2 / S-5.3), AUDIO
transcribes the persisted file and classifies the transcript (S-5.4 / S-5.5),
and every branch fails open to ``sin_clasificar`` while the raw body/caption
is preserved — capture is never blocked by enrichment (S-5.6). The processor
-level caption fallback (S-5.3/S-5.7) is covered in test_media_enrich_wiring.
"""

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_TOOLS = Path(__file__).resolve().parents[2]  # src/tools
for _p in (str(_TOOLS),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from idea_capture.enrich import (  # noqa: E402
    DEFAULT_TYPE,
    MediaEnrichProvider,
    _audio_suffix_for_mime,
    map_tags_to_taxonomy,
)
from idea_capture.models import MediaKind  # noqa: E402


# ---------------------------------------------------------------------------
# Dispatch: TEXT -> Hermes classifier (S-5.1)
# ---------------------------------------------------------------------------


class TestTextDispatch:
    def test_text_delegates_to_hermes_classifier(self):
        provider = MediaEnrichProvider(hermes=lambda raw: "personaje")
        result = provider("un mercenario sombrío", media_kind=MediaKind.TEXT)
        assert result.body == "un mercenario sombrío"
        assert result.type == "personaje"

    def test_text_title_from_tuple_classifier(self):
        provider = MediaEnrichProvider(
            hermes=lambda raw: ("trama", "La conspiración"),
        )
        result = provider("una conspiración", media_kind=MediaKind.TEXT)
        assert result.type == "trama"
        assert result.title == "La conspiración"

    def test_text_failure_fails_open_preserving_body(self):
        def exploding(_raw):
            raise RuntimeError("classifier down")

        provider = MediaEnrichProvider(hermes=exploding, timeout_seconds=5)
        result = provider("una idea", media_kind=MediaKind.TEXT)
        assert result.body == "una idea"
        assert result.type == DEFAULT_TYPE
        assert result.title == ""

    def test_unknown_media_kind_classifies_as_text(self):
        provider = MediaEnrichProvider(hermes=lambda raw: "concepto")
        result = provider("una idea", media_kind="video")
        assert result.body == "una idea"
        assert result.type == "concepto"

    def test_classifier_timeout_fails_open_to_sin_clasificar(self):
        import time

        def slow(_raw):
            time.sleep(1.0)
            return ("personaje", "El personaje")

        provider = MediaEnrichProvider(hermes=slow, timeout_seconds=0.05)
        result = provider("una idea lenta", media_kind=MediaKind.TEXT)
        assert result.body == "una idea lenta"
        assert result.type == DEFAULT_TYPE
        assert result.title == ""


# ---------------------------------------------------------------------------
# Dispatch: IMAGE -> vision callable (S-5.2 / S-5.3)
# ---------------------------------------------------------------------------


_IMAGE_BYTES = b"\x89PNG\r\n\x1a\nraw-image"


class TestImageDispatch:
    def test_vision_descripcion_becomes_body_and_tags_map_to_type(self):
        provider = MediaEnrichProvider(
            vision_fn=lambda raw, ctx: {
                "descripcion": "un mapa de la corte",
                "tags": ["ambientacion"],
                "veredicto": "ambientacion",
            },
            vision_enabled=True,
        )
        result = provider(_IMAGE_BYTES, media_kind=MediaKind.IMAGE)
        assert result.body == "un mapa de la corte"
        assert result.type == "ambientacion"

    def test_vision_ambiguous_tags_fall_back_to_concepto(self):
        provider = MediaEnrichProvider(
            vision_fn=lambda raw, ctx: {
                "descripcion": "dos figuras",
                "tags": ["personaje", "relacion"],
            },
            vision_enabled=True,
        )
        result = provider(_IMAGE_BYTES, media_kind=MediaKind.IMAGE)
        assert result.body == "dos figuras"
        assert result.type == "concepto"

    def test_vision_title_from_payload_titulo_field(self):
        provider = MediaEnrichProvider(
            vision_fn=lambda raw, ctx: {
                "descripcion": "un mapa de la corte",
                "titulo": "El Mapa de la Corte",
                "tags": ["ambientacion"],
            },
            vision_enabled=True,
        )
        result = provider(_IMAGE_BYTES, media_kind=MediaKind.IMAGE)
        assert result.type == "ambientacion"
        assert result.title == "El Mapa de la Corte"

    def test_vision_title_derived_from_descripcion_first_words(self):
        provider = MediaEnrichProvider(
            vision_fn=lambda raw, ctx: {
                "descripcion": "un mapa con tesoros escondidos bajo la corte",
                "tags": ["concepto"],
            },
            vision_enabled=True,
        )
        result = provider(_IMAGE_BYTES, media_kind=MediaKind.IMAGE)
        assert result.title == "un mapa con tesoros escondidos"

    def test_vision_empty_descripcion_yields_empty_title(self):
        provider = MediaEnrichProvider(
            vision_fn=lambda raw, ctx: {"descripcion": "", "tags": []},
            vision_enabled=True,
        )
        result = provider(_IMAGE_BYTES, media_kind=MediaKind.IMAGE)
        assert result.title == ""

    def test_vision_disabled_fails_open_empty_body(self):
        provider = MediaEnrichProvider(
            vision_fn=lambda raw, ctx: {"descripcion": "x", "tags": []},
            vision_enabled=False,
        )
        result = provider(_IMAGE_BYTES, media_kind=MediaKind.IMAGE)
        assert result.body == ""
        assert result.type == DEFAULT_TYPE

    def test_vision_fn_missing_fails_open(self):
        provider = MediaEnrichProvider(vision_enabled=True)
        result = provider(_IMAGE_BYTES, media_kind=MediaKind.IMAGE)
        assert result.body == ""
        assert result.type == DEFAULT_TYPE

    def test_vision_fn_raising_fails_open(self):
        def exploding(_raw, _ctx):
            raise RuntimeError("vision down")

        provider = MediaEnrichProvider(vision_fn=exploding, vision_enabled=True)
        result = provider(_IMAGE_BYTES, media_kind=MediaKind.IMAGE)
        assert result.body == ""
        assert result.type == DEFAULT_TYPE

    def test_vision_empty_payload_fails_open(self):
        provider = MediaEnrichProvider(
            vision_fn=lambda raw, ctx: None,
            vision_enabled=True,
        )
        result = provider(_IMAGE_BYTES, media_kind=MediaKind.IMAGE)
        assert result.body == ""
        assert result.type == DEFAULT_TYPE


# ---------------------------------------------------------------------------
# Dispatch: AUDIO -> transcribe + classify (S-5.4 / S-5.5)
# ---------------------------------------------------------------------------


class TestAudioDispatch:
    def test_transcript_becomes_body_and_is_classified(self, tmp_path):
        audio = tmp_path / "voice.ogg"
        audio.write_bytes(b"OggS\x01fake-voice")
        seen = {}

        def transcribe_fn(path, language):
            seen["path"] = path
            seen["language"] = language
            return "una idea hablada"

        provider = MediaEnrichProvider(
            hermes=lambda raw: "concepto",
            transcribe_fn=transcribe_fn,
            language_resolver=lambda: "es",
        )
        result = provider(
            b"OggS\x01fake-voice",
            media_kind=MediaKind.VOICE,
            media_path=str(audio),
            mime="audio/ogg",
        )
        assert result.body == "una idea hablada"
        assert result.type == "concepto"
        # The persisted media file is passed through, not re-written.
        assert seen["path"] == str(audio)
        assert seen["language"] == "es"

    def test_audio_title_flows_from_transcript_classification(self, tmp_path):
        """AUDIO routes through the Hermes classifier over the transcript, so
        a ``(label, title)``-returning classifier yields the idea title."""
        audio = tmp_path / "voice.ogg"
        audio.write_bytes(b"OggS\x01fake-voice")
        provider = MediaEnrichProvider(
            hermes=lambda raw: ("personaje", "El arquero ciego"),
            transcribe_fn=lambda path, language: "un arquero ciego protege la ciudad",
            language_resolver=lambda: "es",
        )
        result = provider(
            b"OggS\x01fake-voice",
            media_kind=MediaKind.VOICE,
            media_path=str(audio),
            mime="audio/ogg",
        )
        assert result.body == "un arquero ciego protege la ciudad"
        assert result.type == "personaje"
        assert result.title == "El arquero ciego"

    def test_transcription_unavailable_fails_open_empty_body(self):
        provider = MediaEnrichProvider(transcribe_fn=None)
        result = provider(b"OggS\x01fake-voice", media_kind=MediaKind.VOICE)
        assert result.body == ""
        assert result.type == DEFAULT_TYPE

    def test_transcription_failure_fails_open_empty_body(self):
        def failing(_path, _language):
            raise RuntimeError("whisper down")

        provider = MediaEnrichProvider(transcribe_fn=failing, language_resolver=lambda: "es")
        result = provider(b"OggS\x01fake-voice", media_kind=MediaKind.VOICE)
        assert result.body == ""
        assert result.type == DEFAULT_TYPE

    def test_empty_transcript_fails_open(self, tmp_path):
        audio = tmp_path / "voice.ogg"
        audio.write_bytes(b"OggS\x01fake-voice")

        provider = MediaEnrichProvider(
            transcribe_fn=lambda path, language: "   ",
            language_resolver=lambda: "es",
        )
        result = provider(b"OggS\x01fake-voice", media_kind=MediaKind.VOICE,
                          media_path=str(audio))
        assert result.body == ""
        assert result.type == DEFAULT_TYPE

    def test_missing_media_path_writes_temp_file_and_cleans_up(self):
        temp_files: list = []

        def transcribe_fn(path, language):
            temp_files.append(path)
            return "grabación recuperada"

        provider = MediaEnrichProvider(
            hermes=lambda raw: "concepto",
            transcribe_fn=transcribe_fn,
            language_resolver=lambda: "en",
        )
        result = provider(
            b"OggS\x01fake-voice",
            media_kind=MediaKind.VOICE,
            media_path=None,
            mime="audio/ogg",
        )
        assert result.body == "grabación recuperada"
        assert result.type == "concepto"
        # The temp fallback file was removed after transcription.
        assert temp_files
        assert not Path(temp_files[0]).exists()

    def test_default_language_is_es_when_no_resolver(self, tmp_path):
        audio = tmp_path / "voice.ogg"
        audio.write_bytes(b"OggS\x01fake-voice")
        seen = {}

        provider = MediaEnrichProvider(
            transcribe_fn=lambda path, language: seen.setdefault("language", language)
            or "un eco",
        )
        provider(b"OggS\x01fake-voice", media_kind=MediaKind.VOICE,
                 media_path=str(audio))
        assert seen["language"] == "es"


# ---------------------------------------------------------------------------
# map_tags_to_taxonomy (R-5): empty/single/ambiguous mapping
# ---------------------------------------------------------------------------


class TestMapTagsToTaxonomy:
    def test_empty_tags_fall_back_to_concepto(self):
        assert map_tags_to_taxonomy([]) == "concepto"

    def test_non_list_tags_fall_back_to_concepto(self):
        assert map_tags_to_taxonomy(None) == "concepto"
        assert map_tags_to_taxonomy("personaje") == "concepto"

    def test_single_tag_maps_to_type(self):
        assert map_tags_to_taxonomy(["personaje"]) == "personaje"

    def test_plural_tag_maps_to_singular_type(self):
        assert map_tags_to_taxonomy(["personajes"]) == "personaje"

    def test_unknown_tags_fall_back_to_concepto(self):
        assert map_tags_to_taxonomy(["paisaje"]) == "concepto"

    def test_ambiguous_tags_fall_back_to_concepto(self):
        assert map_tags_to_taxonomy(["personaje", "trama"]) == "concepto"

    def test_case_and_whitespace_tolerant(self):
        assert map_tags_to_taxonomy(["  Ambientacion "]) == "ambientacion"


class TestAudioSuffixForMime:
    def test_known_mime_maps_to_suffix(self):
        assert _audio_suffix_for_mime("audio/ogg") == ".ogg"
        assert _audio_suffix_for_mime("audio/mpeg") == ".mp3"
        assert _audio_suffix_for_mime("audio/mp4") == ".m4a"
        assert _audio_suffix_for_mime("audio/wav; codecs=1") == ".wav"

    def test_unknown_mime_defaults_to_ogg(self):
        assert _audio_suffix_for_mime("application/octet-stream") == ".ogg"
        assert _audio_suffix_for_mime(None) == ".ogg"
        assert _audio_suffix_for_mime("") == ".ogg"