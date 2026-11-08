# -*- coding: utf-8 -*-
"""Guided conversation style: synthesis cap, convergence, plan progress (S5)."""

from __future__ import annotations

import sys
from pathlib import Path

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from contract_projection import project_contract_markdown  # noqa: E402
from guided_character_protocol import (  # noqa: E402
    PROTOCOL_VERSION,
    GuidedRequest,
    GuidedResponse,
)
from methodology_compiler import CompiledMethodology  # noqa: E402


def _request() -> GuidedRequest:
    return GuidedRequest(
        protocol_version=PROTOCOL_VERSION,
        request_id="guided-test",
        session_id="guided-session",
        world="Vibrantes",
        base_revision=0,
        authorization_binding="install:test",
        author_input="¿qué sigue?",
    )


def test_synthesis_is_capped_to_three_sentences():
    request = _request()
    response = GuidedResponse.from_provider(
        {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "question",
            "question": "¿Qué busca?",
            "synthesis": "frase. " * 400,
        },
        request,
    )

    assert response is not None
    assert response.synthesis is not None
    assert len(response.synthesis) == GuidedResponse.SYNTHESIS_MAX_CHARS
    assert GuidedResponse.SYNTHESIS_MAX_CHARS <= 700


def test_projection_carries_the_convergence_rule():
    projection = project_contract_markdown(
        CompiledMethodology(
            skill_id="guided-character-v1",
            version="1.0.0",
            name="Guided character",
            description="Character method.",
            phases=("identity", "desire", "conflict"),
            language="es",
            source="## Principio\n\nUna pregunta a la vez.\n",
            digest="abc",
        )
    )

    assert "Converge:" in projection
    assert "summarize and offer the proposal" in projection


def test_plan_state_reports_the_next_uncovered_slot(monkeypatch):
    import api_server

    class _Profile:
        entity_type = "personaje"

    class _Candidate:
        accepted_canon = {"nombre": "Ganic"}

    class _State:
        candidate = _Candidate()

    monkeypatch.setattr(api_server, "_flow_profile", lambda state: _Profile())

    line = api_server._guided_plan_state(_State())

    assert "1/6" in line
    assert "next: desire" in line


def test_plan_state_announces_completion(monkeypatch):
    import api_server

    class _Profile:
        entity_type = "personaje"

    class _Candidate:
        accepted_canon = {
            "nombre": "Ganic",
            "deseo": "curarse",
            "conflicto": "su cuerpo",
            "relacion": "su novia",
            "secreto": "el Dvex",
            "arco": "detener la deuda",
        }

    class _State:
        candidate = _Candidate()

    monkeypatch.setattr(api_server, "_flow_profile", lambda state: _Profile())

    line = api_server._guided_plan_state(_State())

    assert "complete" in line.lower()
    assert "offer the proposal" in line
