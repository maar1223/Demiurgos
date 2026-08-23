# -*- coding: utf-8 -*-
"""ProbeRunner contract tests: text + causal vision oracles (ONB-2.3)."""

import base64
from pathlib import Path
import sys
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
_PROBES = _HERE.parent
if str(_PROBES) not in sys.path:
    sys.path.insert(0, str(_PROBES))

from runner import (  # noqa: E402
    OUTCOME_MALFORMED,
    OUTCOME_NOT_CAUSAL,
    OUTCOME_PASSED,
    OUTCOME_PROVIDER_FAILURE,
    OUTCOME_TIMEOUT,
    TEXT_MARKER,
    ProbeResult,
    ProbeRunner,
    chat_completions_url,
)

_FIXTURE = _PROBES / "fixtures" / "logo-demiurgos.jpg"
_VARIANT = _PROBES / "fixtures" / "logo-demiurgos-altered.jpg"


def _transport(calls: list[tuple[str, str, dict[str, Any]]], answers: list[Any]):
    def transport(method: str, url: str, headers: dict[str, str], payload: dict[str, Any]):
        calls.append((method, url, payload))
        return 200, answers.pop(0)

    return transport


def _text_answer(word: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": word}}]}


class TestChatUrl:
    def test_normalizes_v1_and_plain_bases(self):
        assert chat_completions_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434/v1/chat/completions"
        assert chat_completions_url("http://127.0.0.1:1234/v1/") == "http://127.0.0.1:1234/v1/chat/completions"
        assert (
            chat_completions_url("https://api.openai.com/v1") == "https://api.openai.com/v1/chat/completions"
        )
        assert (
            chat_completions_url("http://x.test/v1/chat/completions")
            == "http://x.test/v1/chat/completions"
        )


class TestTextOracle:
    def test_passes_when_marker_is_echoed(self):
        calls: list = []
        runner = ProbeRunner(
            "http://127.0.0.1:11434", "llama3", transport=_transport(calls, [_text_answer(TEXT_MARKER)])
        )

        result = runner.run_text()

        assert result == ProbeResult(OUTCOME_PASSED, "text-marker", "Text oracle passed.")
        assert calls[0][0] == "POST"
        assert calls[0][1].endswith("/v1/chat/completions")
        assert TEXT_MARKER in calls[0][2]["messages"][0]["content"]

    def test_wrong_marker_is_not_causal(self):
        runner = ProbeRunner("http://x.test/v1", "m", transport=_transport([], [_text_answer("otra-cosa")]))

        assert runner.run_text().outcome == OUTCOME_NOT_CAUSAL

    def test_malformed_response_is_malformed(self):
        runner = ProbeRunner("http://x.test/v1", "m", transport=_transport([], [{"unexpected": True}]))

        assert runner.run_text().outcome == OUTCOME_MALFORMED

    def test_content_parts_array_passes_text_oracle(self):
        # Multimodal OpenAI-compatible endpoints return content as an array of
        # content parts even for plain text answers.
        answer = {"choices": [{"message": {"content": [{"type": "text", "text": TEXT_MARKER}]}}]}
        runner = ProbeRunner("http://x.test/v1", "m", transport=_transport([], [answer]))

        assert runner.run_text() == ProbeResult(OUTCOME_PASSED, "text-marker", "Text oracle passed.")

    def test_content_parts_array_skips_non_text_parts(self):
        answer = {
            "choices": [{
                "message": {
                    "content": [
                        {"type": "image_url", "image_url": "data:image/jpeg;base64,AAAA=="},
                        {"type": "text", "text": f"the {TEXT_MARKER} word"},
                    ],
                },
            }],
        }
        runner = ProbeRunner("http://x.test/v1", "m", transport=_transport([], [answer]))

        assert runner.run_text().outcome == OUTCOME_PASSED

    def test_content_parts_array_without_text_is_malformed(self):
        answer = {"choices": [{"message": {"content": [{"type": "image_url", "image_url": "data:image/jpeg;base64,AAAA=="}]}}]}
        runner = ProbeRunner("http://x.test/v1", "m", transport=_transport([], [answer]))

        assert runner.run_text().outcome == OUTCOME_MALFORMED

    def test_reasoning_content_fallback_passes_text_oracle(self):
        # Reasoning models (MiMo, DeepSeek-reasoner) put the answer in
        # reasoning_content while content is null.
        answer = {"choices": [{"message": {"content": None, "reasoning_content": TEXT_MARKER}}]}
        runner = ProbeRunner("http://x.test/v1", "m", transport=_transport([], [answer]))

        assert runner.run_text() == ProbeResult(OUTCOME_PASSED, "text-marker", "Text oracle passed.")

    def test_reasoning_text_wrapped_in_think_tag_still_passes(self):
        answer = {"choices": [{"message": {"content": f"<think>some reasoning</think> {TEXT_MARKER}"}}]}
        runner = ProbeRunner("http://x.test/v1", "m", transport=_transport([], [answer]))

        assert runner.run_text().outcome == OUTCOME_PASSED

    def test_malformed_hint_is_redacted_and_bounded(self):
        answer = {"choices": [{"message": {"content": None}}]}
        runner = ProbeRunner("http://x.test/v1", "m", transport=_transport([], [answer]))

        result = runner.run_text()
        assert result.outcome == OUTCOME_MALFORMED
        assert "Hint:" in result.message
        assert len(result.message) < 300

    def test_http_error_is_provider_failure(self):
        def failing(method, url, headers, payload):
            return 503, {"error": "unavailable"}

        runner = ProbeRunner("http://x.test/v1", "m", transport=failing)

        assert runner.run_text().outcome == OUTCOME_PROVIDER_FAILURE

    def test_http_error_surfaces_safe_provider_detail(self):
        def failing(method, url, headers, payload):
            return 400, {"error": {"message": "model 'gpt-5.6-luna' does not support image input"}}

        runner = ProbeRunner("http://x.test/v1", "gpt-5.6-luna", transport=failing)

        result = runner.run_text()

        assert result.outcome == OUTCOME_PROVIDER_FAILURE
        assert "does not support image input" in result.message
        assert result.message.startswith("The provider rejected the probe request (HTTP 400).")

    def test_http_error_missing_or_blank_detail_uses_fallback(self):
        def failing(method, url, headers, payload):
            return 400, {"error": {"message": "   "}}

        runner = ProbeRunner("http://x.test/v1", "m", transport=failing)

        result = runner.run_text()

        assert result.outcome == OUTCOME_PROVIDER_FAILURE
        assert result.message == "The provider rejected the probe request (HTTP 400)."

    def test_http_error_never_echoes_secrets_or_image_blob(self):
        def failing(method, url, headers, payload):
            # A hostile/misbehaving provider echoes the request body back,
            # including the image data URI and a leaked credential shape.
            message = (
                "invalid request: sk-opaque-secret and "
                "data:image/jpeg;base64,AAAA== in payload"
            )
            return 400, {"error": {"message": message}}

        runner = ProbeRunner(
            "http://x.test/v1", "m", api_key="opaque-probe-secret", transport=failing
        )

        result = runner.run_vision()

        assert result.outcome == OUTCOME_PROVIDER_FAILURE
        assert "sk-opaque-secret" not in result.message
        assert "opaque-probe-secret" not in result.message
        assert "data:image/jpeg" not in result.message
        assert "AAAA" not in result.message
        # Detail is bounded to a short diagnostic snippet.
        assert len(result.message) <= 200

    def test_transport_timeout_is_timeout(self):
        import httpx

        def failing(method, url, headers, payload):
            raise httpx.TimeoutException("slow")

        runner = ProbeRunner("http://x.test/v1", "m", transport=failing)

        assert runner.run_text().outcome == OUTCOME_TIMEOUT


class TestVisionOracle:
    def test_passes_fixture_and_variant(self):
        calls: list = []
        answers = [_text_answer("no"), _text_answer("Yes.")]
        runner = ProbeRunner("http://127.0.0.1:11434", "llava", transport=_transport(calls, answers))

        result = runner.run_vision()

        assert result == ProbeResult(OUTCOME_PASSED, "causal-vision", "Text and causal vision probes passed.")
        assert len(calls) == 2
        for _, _, payload in calls:
            content = payload["messages"][0]["content"]
            assert isinstance(content, list) and len(content) == 2
            image = content[1]
            assert image["type"] == "image_url"
            # OpenCode Go/OpenAI-compatible endpoints expect image_url as a
            # direct data-URI string (see sync_lore providers), not an object.
            assert isinstance(image["image_url"], str)
            assert image["image_url"].startswith("data:image/jpeg;base64,")
            assert "opaque-key" not in repr(payload)

    def test_fixture_wrong_answer_is_not_causal(self):
        runner = ProbeRunner("http://x.test/v1", "m", transport=_transport([], [_text_answer("yes")]))

        assert runner.run_vision().outcome == OUTCOME_NOT_CAUSAL

    def test_variant_wrong_answer_is_not_causal(self):
        answers = [_text_answer("no"), _text_answer("no")]
        runner = ProbeRunner("http://x.test/v1", "m", transport=_transport([], answers))

        result = runner.run_vision()

        assert result.outcome == OUTCOME_NOT_CAUSAL
        assert result.oracle == "vision-variant"

    def test_ambiguous_answer_is_not_causal(self):
        runner = ProbeRunner("http://x.test/v1", "m", transport=_transport([], [_text_answer("maybe")]))

        assert runner.run_vision().outcome == OUTCOME_NOT_CAUSAL

    def test_vision_with_think_wrapper_still_passes(self):
        # Reasoning models wrap the binary answer in <think>...</think>.
        runner = ProbeRunner(
            "http://x.test/v1", "m",
            transport=_transport([], [_text_answer("<think>let me see</think> no"), _text_answer("<think>checking</think> Yes.")]),
        )
        assert runner.run_vision().outcome == OUTCOME_PASSED

    def test_failure_on_first_image_stops_early(self):
        import httpx

        def failing(method, url, headers, payload):
            raise httpx.TimeoutException("slow")

        runner = ProbeRunner("http://x.test/v1", "m", transport=failing)

        assert runner.run_vision().outcome == OUTCOME_TIMEOUT


class TestAlteredVariantFixture:
    def test_variant_differs_and_contains_the_marker(self):
        from PIL import Image

        assert _FIXTURE.is_file() and _VARIANT.is_file()
        original = Image.open(_FIXTURE).convert("RGB")
        altered = Image.open(_VARIANT).convert("RGB")
        assert original.size == altered.size == (800, 800)
        assert original.tobytes() != altered.tobytes()
        corner = altered.crop((0, 0, 60, 60))
        pixels = list(corner.getdata())
        average = tuple(sum(channel[i] for channel in pixels) // len(pixels) for i in range(3))
        assert average[0] > 200 and average[1] < 60 and average[2] > 200

    def test_fixture_corner_is_not_magenta(self):
        from PIL import Image

        original = Image.open(_FIXTURE).convert("RGB")
        corner = original.crop((0, 0, 60, 60))
        pixels = list(corner.getdata())
        average = tuple(sum(channel[i] for channel in pixels) // len(pixels) for i in range(3))
        assert not (average[0] > 200 and average[1] < 60 and average[2] > 200)


class TestSecretBoundaryInProbes:
    def test_credentials_never_reach_response_payload_or_repr(self):
        calls: list = []
        runner = ProbeRunner(
            "http://x.test/v1",
            "m",
            api_key="opaque-probe-secret",
            transport=_transport(calls, [_text_answer("no"), _text_answer("yes")]),
        )

        result = runner.run_vision()

        assert "opaque-probe-secret" not in repr(result)
        assert "opaque-probe-secret" not in str(result)
        payload = calls[0][2]
        assert "opaque-probe-secret" not in repr(payload)
        image = payload["messages"][0]["content"][1]
        assert base64.b64decode(image["image_url"].split(",", 1)[1])[:8]