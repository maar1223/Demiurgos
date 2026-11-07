"""Focused tests for the finite guided detail plan and its progress."""

from __future__ import annotations

import sys
from pathlib import Path

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from guided_flow import (  # noqa: E402
    detail_plan_for,
    detail_progress,
    next_detail_slot,
    slot_for_key,
    visible_proposal_key,
)


def test_character_plan_has_six_ordered_slots() -> None:
    plan = detail_plan_for("personaje")
    assert [slot for slot, _ in plan] == [
        "identity", "desire", "conflict", "relationship", "secret", "arc",
    ]
    assert slot_for_key(plan, "motivacion") == "desire"
    assert slot_for_key(plan, "relacion_anciano") == "relationship"
    assert slot_for_key(plan, "mecanismo") == "secret"
    assert slot_for_key(plan, "mundo") is None


def test_progress_counts_accepted_only_and_shows_one_plan_proposal() -> None:
    plan = detail_plan_for("personaje")
    accepted = {"nombre": "Ganic"}
    proposals = {
        "mundo": "Vibrantes",
        "motivacion": "controlar el tiempo",
        "defectos": "obsesivo",
    }
    assert next_detail_slot(accepted, plan) == "desire"
    assert detail_progress(accepted, plan) == {
        "index": 2, "total": 6, "slot": "desire", "complete": False,
    }
    # `mundo` is off-plan and comes first; the visible card must be desire.
    assert visible_proposal_key(proposals, accepted, plan) == "motivacion"


def test_no_plan_proposal_is_visible_when_the_next_slot_is_missing() -> None:
    plan = detail_plan_for("personaje")
    accepted = {"nombre": "Ganic"}
    proposals = {"mundo": "Vibrantes", "defectos": "obsesivo"}
    assert visible_proposal_key(proposals, accepted, plan) is None


def test_complete_plan_has_no_visible_proposal() -> None:
    plan = detail_plan_for("personaje")
    accepted = {
        "nombre": "Ganic", "motivacion": "controlar el tiempo",
        "defectos": "obsesivo", "relacion_anciano": "un anciano",
        "mecanismo": "un reloj", "arco": "redimirse",
    }
    assert detail_progress(accepted, plan) == {
        "index": 6, "total": 6, "slot": "arc", "complete": True,
    }
    assert visible_proposal_key({"mundo": "Vibrantes"}, accepted, plan) is None


def test_non_contiguous_acceptance_reports_the_real_next_slot() -> None:
    plan = detail_plan_for("personaje")
    accepted = {"nombre": "Ganic", "defectos": "obsesivo"}
    assert detail_progress(accepted, plan) == {
        "index": 2, "total": 6, "slot": "desire", "complete": False,
    }
