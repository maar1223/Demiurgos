"""Focused production adapter tests for Hermes idea-materialization wiring.

The provider is transport + prompt assembly only: strict envelope validation
is the server-side ``MaterializationResponse.from_provider`` boundary
(R-IM-09), so malformed output must be passed through unchanged. A fake
``HermesRunsActivityAdapter`` (``Runs``) drives every scenario, mirroring
``test_guided_character_provider.py``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from assistant_activity import CapabilityAssessment  # noqa: E402
from idea_materialization_protocol import (  # noqa: E402
    CancellationToken,
    MAX_IDEA_BODY_CHARS,
    MaterializationRequest,
    MaterializationResponse,
    PROTOCOL_VERSION,
)
from idea_materialization_provider import HermesMaterializationProvider  # noqa: E402


def materialization_request(**overrides) -> MaterializationRequest:
    values = dict(
        protocol_version=PROTOCOL_VERSION,
        request_id="request-1",
        session_id="session-1",
        world="Vibrantes",
        section="lore",
        folder="sistema-stal-poderes-vibrantes",
        slug="arquero-ciego",
        title="El Arquero Ciego",
        idea_type="personaje",
        idea_body="An idea body.",
        tags=("personaje", "vibrantes"),
        candidates=(
            {"id": "Política | Distribución Y Territorios::Atherr", "title": "Atherr", "type": "lugar", "summary": "A ruined city."},
            {"id": "Naciones::Vibrantes", "title": "Vibrantes", "type": "concepto", "summary": "The empire."},
        ),
    )
    values.update(overrides)
    return MaterializationRequest(**values)


def delta_envelope(**overrides) -> dict:
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": "request-1",
        "session_id": "session-1",
        "outcome": "delta",
        "delta": {
            "body": "# El Arquero Ciego\n\nUn arquero que no ve.",
            "relations": [
                {"target_id": "Política | Distribución Y Territorios::Atherr", "rel_type": "lugar"},
            ],
        },
    }
    payload.update(overrides)
    return payload


def test_probe_delegates_to_runs_probe() -> None:
    async def scenario() -> None:
        class Runs:
            def __init__(self) -> None:
                self.probed = 0

            async def probe(self) -> CapabilityAssessment:
                self.probed += 1
                return CapabilityAssessment(True, "", None)

        runs = Runs()
        provider = HermesMaterializationProvider(runs)
        assessment = await provider.probe()
        assert assessment.admitted is True
        assert runs.probed == 1

    asyncio.run(scenario())


def test_invoke_starts_exactly_one_run_per_invocation() -> None:
    """Single-run guarantee: one provider invocation = one Hermes run."""

    async def scenario() -> None:
        class Runs:
            def __init__(self) -> None:
                self.starts = 0

            async def start(self, _request: object) -> str:
                self.starts += 1
                return "run-1"

            async def events(self, _run_id: str):
                yield {"event": "run.completed", "run_id": "run-1", "output": delta_envelope()}

        runs = Runs()
        provider = HermesMaterializationProvider(runs)
        await provider.invoke(materialization_request(), CancellationToken())
        await provider.invoke(materialization_request(), CancellationToken())
        assert runs.starts == 2

    asyncio.run(scenario())


def test_delta_assembly_from_message_delta_events() -> None:
    """Streamed ``message.delta`` chunks are concatenated into one envelope."""

    async def scenario() -> None:
        chunks = [
            '{"protocol_version": "idea-materialization-v1", "request_id": "request-1", ',
            '"session_id": "session-1", "outcome": "delta", "delta": {"body": "Un arquero que no ve.", ',
            '"relations": [{"target_id": "Política | Distribución Y Territorios::Atherr", "rel_type": "lugar"}]}}',
        ]

        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                for chunk in chunks:
                    yield {"event": "message.delta", "run_id": "run-1", "delta": chunk}
                yield {"event": "run.completed", "run_id": "run-1", "output": ""}

        result = await HermesMaterializationProvider(Runs()).invoke(
            materialization_request(), CancellationToken()
        )
        assert result["protocol_version"] == PROTOCOL_VERSION
        assert result["outcome"] == "delta"
        assert result["delta"]["body"] == "Un arquero que no ve."
        assert result["delta"]["relations"][0]["target_id"] == "Política | Distribución Y Territorios::Atherr"

    asyncio.run(scenario())


def test_fenced_json_output_is_stripped() -> None:
    """A fenced ```json block is stripped before parsing (fence precedent)."""

    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                fenced = "```json\n" + json.dumps(delta_envelope()) + "\n```"
                yield {"event": "run.completed", "run_id": "run-1", "output": fenced}

        result = await HermesMaterializationProvider(Runs()).invoke(
            materialization_request(), CancellationToken()
        )
        assert result["outcome"] == "delta"
        assert result["delta"]["body"].startswith("# El Arquero Ciego")

    asyncio.run(scenario())


def test_provider_run_id_and_provenance_defaults_are_stamped() -> None:
    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-9"

            async def events(self, _run_id: str):
                yield {"event": "run.completed", "run_id": "run-9", "output": delta_envelope()}

        result = await HermesMaterializationProvider(Runs()).invoke(
            materialization_request(), CancellationToken()
        )
        assert result["provider_run_id"] == "run-9"
        assert result["provenance"] == ["hermes:run:run-9"]

    asyncio.run(scenario())


def test_stamped_defaults_do_not_override_provider_values() -> None:
    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                envelope = delta_envelope(provider_run_id="other-run", provenance=["custom"])
                yield {"event": "run.completed", "run_id": "run-1", "output": envelope}

        result = await HermesMaterializationProvider(Runs()).invoke(
            materialization_request(), CancellationToken()
        )
        assert result["provider_run_id"] == "other-run"
        assert result["provenance"] == ["custom"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "output",
    [
        "not-json",
        "",
        "```json\n{not valid json}\n```",
    ],
)
def test_invalid_json_text_is_passed_through_unchanged(output: str) -> None:
    """The provider never fabricates an envelope: unparseable text is returned
    as-is so the server-side ``from_provider`` fails it closed (R-IM-09)."""

    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                yield {"event": "run.completed", "run_id": "run-1", "output": output}

        result = await HermesMaterializationProvider(Runs()).invoke(
            materialization_request(), CancellationToken()
        )
        assert result == output

    asyncio.run(scenario())


def test_non_envelope_mapping_is_passed_through_with_run_stamp() -> None:
    """A Mapping that is not a valid envelope is returned (stamped, unvalidated)
    and the strict server-side validator rejects it — fail closed."""

    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                yield {"event": "run.completed", "run_id": "run-1", "output": {
                    "outcome": "delta",
                    "delta": {"body": 42},
                }}

        result = await HermesMaterializationProvider(Runs()).invoke(
            materialization_request(), CancellationToken()
        )
        assert isinstance(result, dict)
        assert result["provider_run_id"] == "run-1"
        assert MaterializationResponse.from_provider(result, materialization_request()) is None

    asyncio.run(scenario())


def test_provider_performs_no_filesystem_write(tmp_path, monkeypatch) -> None:
    """The provider is transport-only: invoking it leaves the filesystem empty."""
    monkeypatch.setenv("DEMIURGOS_LANGUAGE", "en")
    monkeypatch.chdir(tmp_path)

    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                yield {"event": "run.completed", "run_id": "run-1", "output": delta_envelope()}

        await HermesMaterializationProvider(Runs()).invoke(
            materialization_request(), CancellationToken()
        )
        assert list(tmp_path.iterdir()) == []

    asyncio.run(scenario())


def test_prompt_contains_idea_target_candidates_and_envelope(monkeypatch) -> None:
    monkeypatch.setenv("DEMIURGOS_LANGUAGE", "en")

    async def scenario() -> None:
        prompts: list[str] = []

        class Runs:
            async def start(self, request: object) -> str:
                prompts.append(request.prompt)  # type: ignore[attr-defined]
                return "run-1"

            async def events(self, _run_id: str):
                yield {"event": "run.completed", "run_id": "run-1", "output": delta_envelope()}

        await HermesMaterializationProvider(Runs()).invoke(
            materialization_request(), CancellationToken()
        )
        prompt = prompts[0]
        assert "ONLY one JSON object" in prompt
        assert "no markdown fences, no code blocks" in prompt
        assert PROTOCOL_VERSION in prompt
        assert 'request-1' in prompt
        assert 'session-1' in prompt
        assert "- world: Vibrantes" in prompt
        assert "- section: lore" in prompt
        assert "- folder: sistema-stal-poderes-vibrantes" in prompt
        assert "- slug: arquero-ciego" in prompt
        assert "- title: El Arquero Ciego" in prompt
        assert "- type: personaje" in prompt
        assert "- tags: personaje, vibrantes" in prompt
        assert "- body: An idea body." in prompt
        assert "Política | Distribución Y Territorios::Atherr" in prompt
        assert "Naciones::Vibrantes" in prompt
        assert '"outcome": "delta"' in prompt
        assert "no filesystem, graph, or credential access" in prompt
        assert "Never write frontmatter, paths, or new entity names" in prompt

    asyncio.run(scenario())


def test_prompt_truncates_idea_body_to_max_idea_body_chars(monkeypatch) -> None:
    monkeypatch.setenv("DEMIURGOS_LANGUAGE", "en")

    async def scenario() -> None:
        prompts: list[str] = []

        class Runs:
            async def start(self, request: object) -> str:
                prompts.append(request.prompt)  # type: ignore[attr-defined]
                return "run-1"

            async def events(self, _run_id: str):
                yield {"event": "run.completed", "run_id": "run-1", "output": delta_envelope()}

        long_body = "x" * (MAX_IDEA_BODY_CHARS + 500)
        await HermesMaterializationProvider(Runs()).invoke(
            materialization_request(idea_body=long_body), CancellationToken()
        )
        prompt = prompts[0]
        assert f"- body: {'x' * MAX_IDEA_BODY_CHARS}" in prompt
        assert "x" * (MAX_IDEA_BODY_CHARS + 1) not in prompt

    asyncio.run(scenario())


def test_empty_candidates_render_as_empty_json_list(monkeypatch) -> None:
    """An empty world yields ``[]`` in the prompt yet still a valid envelope
    (R-IM-03 empty-relation scenario is server-side, not provider-side)."""
    monkeypatch.setenv("DEMIURGOS_LANGUAGE", "en")

    async def scenario() -> None:
        prompts: list[str] = []

        class Runs:
            async def start(self, request: object) -> str:
                prompts.append(request.prompt)  # type: ignore[attr-defined]
                return "run-1"

            async def events(self, _run_id: str):
                yield {"event": "run.completed", "run_id": "run-1", "output": delta_envelope()}

        result = await HermesMaterializationProvider(Runs()).invoke(
            materialization_request(candidates=()), CancellationToken()
        )
        assert "[]" in prompts[0]
        assert result["outcome"] == "delta"

    asyncio.run(scenario())


def test_prompt_language_follows_configured_ui_language(monkeypatch) -> None:
    async def scenario() -> None:
        prompts: list[str] = []

        class Runs:
            async def start(self, request: object) -> str:
                prompts.append(request.prompt)  # type: ignore[attr-defined]
                return "run-1"

            async def events(self, _run_id: str):
                yield {"event": "run.completed", "run_id": "run-1", "output": delta_envelope()}

        provider = HermesMaterializationProvider(Runs())
        monkeypatch.setenv("DEMIURGOS_LANGUAGE", "es")
        await provider.invoke(materialization_request(), CancellationToken())
        monkeypatch.setenv("DEMIURGOS_LANGUAGE", "en")
        await provider.invoke(materialization_request(), CancellationToken())
        assert "(Spanish)" in prompts[0]
        assert "(English)" in prompts[1]

    asyncio.run(scenario())


def test_cancelled_invoke_cancels_the_run() -> None:
    async def scenario() -> None:
        class Runs:
            def __init__(self) -> None:
                self.cancelled = 0

            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                yield {"event": "message.delta", "run_id": "run-1", "delta": "{"}

            async def cancel(self, _run_id: str) -> None:
                self.cancelled += 1

        runs = Runs()
        token = CancellationToken()
        token.cancel()
        with pytest.raises(asyncio.CancelledError):
            await HermesMaterializationProvider(runs).invoke(materialization_request(), token)
        assert runs.cancelled == 1

    asyncio.run(scenario())