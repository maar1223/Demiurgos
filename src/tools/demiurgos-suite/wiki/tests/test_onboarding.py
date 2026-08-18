"""ONB-1.4 — onboarding coordinator: first-run gate, resume, pending list,
locale step 0, and completion derivation. Writes never happen here (route
layer gates them); the coordinator is pure read/transform.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from demiurgos_language import normalize_locale  # noqa: E402
from onboarding import (  # noqa: E402
    REMOTE_STEPS,
    STEP_ORDER,
    commit_step0,
    commit_world_created,
    default_onboarding,
    status_from,
)


def _fresh_state() -> dict:
    return {
        "schema_version": 1,
        "revision": 0,
        "onboarding": default_onboarding(),
        "locale": None,
        "capabilities": {},
    }


def test_fresh_installation_needs_step0_and_lists_remote_pending() -> None:
    status = status_from(_fresh_state(), world_names=[])
    assert status["completed"] is False
    assert status["current_step"] == "step0"
    assert status["completed_steps"] == []
    assert status["pending_steps"] == list(STEP_ORDER)
    assert set(status["remote_pending"]) == set(REMOTE_STEPS)


def test_after_step0_without_world_current_step_is_world() -> None:
    state = commit_step0(
        _fresh_state(),
        {
            "ui": "es", "conversation": "es", "content": "es",
            "region": "AR", "region_explicit": True,
            "iana_timezone": "America/Argentina/Buenos_Aires",
        },
        normalize_locale=normalize_locale,
    )
    status = status_from(state, world_names=[])
    assert status["completed"] is False
    assert status["current_step"] == "world"
    assert "step0" in status["completed_steps"]
    # step0 is not offered again — completed steps are never replayed.
    assert "step0" not in status["pending_steps"]


def test_completed_requires_step0_and_world() -> None:
    state = commit_step0(
        _fresh_state(),
        {"ui": "en", "conversation": "en", "content": "en",
         "region": "US", "region_explicit": True, "iana_timezone": "America/New_York"},
        normalize_locale=normalize_locale,
    )
    state = commit_world_created(state)
    status = status_from(state, world_names=["mundo-nuevo"])
    assert status["completed"] is True
    assert status["current_step"] == "ready"
    assert set(status["remote_pending"]) == set(REMOTE_STEPS)


def test_remote_steps_never_claimed_ready_without_world() -> None:
    state = commit_step0(
        _fresh_state(),
        {"ui": "es", "conversation": "es", "content": "es",
         "region": None, "region_explicit": False, "iana_timezone": "UTC"},
        normalize_locale=normalize_locale,
    )
    status = status_from(state, world_names=["un-mundo"])
    assert set(status["remote_pending"]) == set(REMOTE_STEPS), \
        "cloud capabilities stay pending even when the core is ready"


def test_commit_step0_persists_locale_and_marks_step() -> None:
    state = commit_step0(
        _fresh_state(),
        {"ui": "es", "conversation": "en", "content": "es",
         "region": "AR", "region_explicit": True,
         "iana_timezone": "America/Argentina/Buenos_Aires"},
        normalize_locale=normalize_locale,
    )
    assert state["locale"]["ui"] == "es"
    assert state["locale"]["conversation"] == "en"
    assert state["locale"]["content"] == "es"
    assert state["locale"]["region"] == "AR"
    assert state["locale"]["region_explicit"] is True
    assert state["locale"]["iana_timezone"] == "America/Argentina/Buenos_Aires"
    assert "step0" in state["onboarding"]["completed_steps"]


def test_commit_step0_never_replays_on_repeat() -> None:
    state = commit_step0(
        _fresh_state(),
        {"ui": "es", "conversation": "es", "content": "es",
         "region": None, "region_explicit": False, "iana_timezone": "UTC"},
        normalize_locale=normalize_locale,
    )
    again = commit_step0(
        state,
        {"ui": "en", "conversation": "en", "content": "en",
         "region": None, "region_explicit": False, "iana_timezone": "UTC"},
        normalize_locale=normalize_locale,
    )
    assert again["onboarding"]["completed_steps"].count("step0") == 1


def test_invalid_locale_is_rejected_without_mutation() -> None:
    with pytest.raises(ValueError):
        commit_step0(
            _fresh_state(),
            {"ui": "es", "conversation": "es", "content": "es",
             "region": "AR", "region_explicit": True, "iana_timezone": "not-a-zone"},
            normalize_locale=normalize_locale,
        )


def test_world_commit_marks_operational_step() -> None:
    state = commit_step0(
        _fresh_state(),
        {"ui": "es", "conversation": "es", "content": "es",
         "region": None, "region_explicit": False, "iana_timezone": "UTC"},
        normalize_locale=normalize_locale,
    )
    after = commit_world_created(state)
    assert "world" in after["onboarding"]["completed_steps"]
    assert after["capabilities"]["world"] == "configured"