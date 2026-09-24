"""Tests: idea-materialization-v1 strict envelope validation (task 1.3).

Table-driven coverage of ``MaterializationResponse.from_provider``. Every
envelope-level failure returns ``None`` (the caller maps it to a fail-closed
502 ``MALFORMED_OUTPUT``), while an out-of-vocabulary ``rel_type`` is NOT an
envelope failure — the relation passes through untouched for the domain
validator to drop and report (binding clarification).
"""

from __future__ import annotations

from pathlib import Path
import sys

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import pytest  # noqa: E402

from idea_materialization_protocol import (  # noqa: E402
    MAX_BODY_CHARS,
    MAX_RELATIONS,
    PROTOCOL_VERSION,
    MaterializationRequest,
    MaterializationResponse,
    Relation,
)


def _request() -> MaterializationRequest:
    return MaterializationRequest(
        protocol_version=PROTOCOL_VERSION,
        request_id="request-1",
        session_id="session-1",
        world="Vibrantes",
        section="lore",
        folder="sistema-stal-poderes",
        slug="arquero-ciego",
        title="Arquero Ciego",
        idea_type="personaje",
        idea_body="Un arquero que no ve.",
        tags=("misterio",),
        deadline_ms=8_000,
    )


def _envelope(**overrides: object) -> dict[str, object]:
    envelope: dict[str, object] = {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": "request-1",
        "session_id": "session-1",
        "outcome": "delta",
        "delta": {
            "body": "# El arquero ciego\n\nUna leyenda silenciosa.",
            "relations": [{"target_id": "Sistema Stal::Poderes", "rel_type": "concepto"}],
        },
        "provider_run_id": "run-1",
        "provenance": ["hermes:run:run-1"],
    }
    envelope.update(overrides)
    return envelope


def _delta(body: str, relations: object) -> dict[str, object]:
    return {"body": body, "relations": relations}


@pytest.mark.parametrize("raw", [
    None,
    42,
    "delta",
    [],
    {"outcome": "delta"},                      # protocol_version missing
    {"protocol_version": PROTOCOL_VERSION},    # request_id/session_id missing
])
def test_envelope_not_a_mapping_or_missing_identity_fails_closed(raw: object) -> None:
    assert MaterializationResponse.from_provider(raw, _request()) is None


@pytest.mark.parametrize("override", [
    {"protocol_version": "guided-character-v1"},
    {"request_id": "request-2"},
    {"session_id": "session-2"},
])
def test_identity_mismatch_fails_closed(override: dict[str, object]) -> None:
    assert MaterializationResponse.from_provider(_envelope(**override), _request()) is None


@pytest.mark.parametrize("outcome", ["question", "conflict", "error", "unavailable", None, 1])
def test_outcome_not_delta_fails_closed(outcome: object) -> None:
    assert MaterializationResponse.from_provider(_envelope(outcome=outcome), _request()) is None


@pytest.mark.parametrize("delta", [None, "delta", [], 42])
def test_delta_not_a_mapping_fails_closed(delta: object) -> None:
    assert MaterializationResponse.from_provider(_envelope(delta=delta), _request()) is None


@pytest.mark.parametrize("body", [
    "",
    "   ",
    "\n\t ",
    "x" * (MAX_BODY_CHARS + 1),
    "---\ntitle: Hack\n---\ncontenido",
    "---",
    "  ---\nid: hax\n",
])
def test_invalid_body_fails_closed(body: str) -> None:
    assert MaterializationResponse.from_provider(_envelope(delta=_delta(body, [])), _request()) is None


@pytest.mark.parametrize("relations", [
    None,                                          # missing / not a list
    "relations",
    {"target_id": "x", "rel_type": "concepto"},
    [{"target_id": f"id-{i}", "rel_type": "concepto"} for i in range(MAX_RELATIONS + 1)],
])
def test_relations_not_a_list_or_over_cap_fails_closed(relations: object) -> None:
    assert MaterializationResponse.from_provider(_envelope(delta=_delta("Un cuerpo válido.", relations)), _request()) is None


def test_missing_relations_key_fails_closed() -> None:
    assert MaterializationResponse.from_provider(_envelope(delta={"body": "Un cuerpo válido."}), _request()) is None


@pytest.mark.parametrize("relation", [
    "concepto",
    42,
    None,
    [],
    {"target_id": "Sistema Stal::Poderes"},                  # missing rel_type
    {"rel_type": "concepto"},                                # missing target_id
    {"target_id": "", "rel_type": "concepto"},               # empty target_id
    {"target_id": "   ", "rel_type": "concepto"},
    {"target_id": "Sistema Stal::Poderes", "rel_type": ""},  # empty rel_type
    {"target_id": "Sistema Stal::Poderes", "rel_type": "  "},
])
def test_relation_structural_shape_fails_closed(relation: object) -> None:
    assert MaterializationResponse.from_provider(_envelope(delta=_delta("Un cuerpo válido.", [relation])), _request()) is None


def test_out_of_vocabulary_rel_type_is_not_an_envelope_failure() -> None:
    """Binding clarification: the envelope stays valid, the relation passes through."""
    envelope = _envelope(delta=_delta("Un cuerpo válido.", [
        {"target_id": "Sistema Stal::Poderes", "rel_type": "made_up_type"},
    ]))
    response = MaterializationResponse.from_provider(envelope, _request())
    assert response is not None
    assert response.relations == (Relation("Sistema Stal::Poderes", "made_up_type"),)


def test_envelope_ignores_frontmatter_id_and_path_fields() -> None:
    """R-IM-02: only body/relations are consumed; the rest of the envelope is ignored."""
    envelope = _envelope(
        frontmatter={"id": "Hacked", "type": "pwned"},
        id="Hacked",
        path="/etc/passwd",
    )
    response = MaterializationResponse.from_provider(envelope, _request())
    assert response is not None
    assert response.body == "# El arquero ciego\n\nUna leyenda silenciosa."
    assert response.relations == (Relation("Sistema Stal::Poderes", "concepto"),)


def test_valid_delta_envelope_parses_body_and_relations() -> None:
    response = MaterializationResponse.from_provider(_envelope(), _request())
    assert response is not None
    assert response.protocol_version == PROTOCOL_VERSION
    assert response.request_id == "request-1"
    assert response.session_id == "session-1"
    assert response.body == "# El arquero ciego\n\nUna leyenda silenciosa."
    assert response.relations == (Relation("Sistema Stal::Poderes", "concepto"),)
    assert response.provider_run_id == "run-1"
    assert response.provenance == ("hermes:run:run-1",)


def test_empty_relations_list_is_valid() -> None:
    """R-IM-03: an empty relation list is a valid envelope."""
    response = MaterializationResponse.from_provider(_envelope(delta=_delta("Un cuerpo válido.", [])), _request())
    assert response is not None
    assert response.relations == ()


def test_body_at_max_bound_is_accepted() -> None:
    response = MaterializationResponse.from_provider(_envelope(delta=_delta("x" * MAX_BODY_CHARS, [])), _request())
    assert response is not None
    assert response.body == "x" * MAX_BODY_CHARS
    assert response.relations == ()