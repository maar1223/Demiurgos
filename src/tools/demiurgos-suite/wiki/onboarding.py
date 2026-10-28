"""Server-owned onboarding coordinator (OC1/OC2/OC5/OC22).

Implements the first-run gate and the resumable step machine:

    new → step0 → account → ai → telegram → world → backup_handoff → ready

Rules enforced here:
- Onboarding runs once; completed steps are NEVER replayed after a restart.
- Local work stays available offline; remote (cloud) steps surface as pending
  until their dedicated contracts complete — never fabricated as done.
- Step 0 persists independent UI/conversation/content languages, an explicit
  region override, and an IANA timezone (OC3).
- All writes are gated on an authenticated principal by the route layer;
  unauthenticated access fails closed. This module is read/transform only and
  never touches the filesystem directly.

The local registry is the authoritative runtime store; Engram is recovery/
context only. The world step's completion derives from filesystem truth
(a world exists), never from the registry.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

# Strict MVP order (OC2). Steps are addressable, resumable units. "account"
# is the local account creation step (auth-vault-credentials, R-AC-01): it
# sits right after step0 and blocks onboarding completion (BLOCKING_STEPS).
STEP_ORDER: tuple[str, ...] = (
    "step0",
    "account",
    "content_folder",
    "ai",
    "telegram",
    "world",
    "backup_handoff",
    "ready",
)

# Steps whose capability is remote and therefore always reported pending until
# their dedicated contract completes (never claimed ready from local evidence).
REMOTE_STEPS: frozenset[str] = frozenset({"ai", "telegram", "backup_handoff"})

# Steps that are optional: skipping them never blocks onboarding completion.
OPTIONAL_STEPS: frozenset[str] = frozenset({"ai", "telegram", "backup_handoff"})

# Blocking local steps: step 0 (locale), the local account (R-AC-01), and the
# world (last operational step, blocking only for the Taller de Mundo). The
# content-folder step (step 4) is deliberately NOT blocking: showing where the
# content lives is a service, and creating a world settles the question.
BLOCKING_STEPS: tuple[str, ...] = ("step0", "account", "world")


def default_onboarding() -> dict[str, Any]:
    return {
        "completed": False,
        "current_step": "step0",
        "completed_steps": [],
    }


def status_from(
    state: Mapping[str, Any],
    world_names: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Derive the public onboarding status from authoritative state + filesystem.

    ``world_names`` is the runtime list of existing worlds (filesystem truth).
    Completion = step 0 persisted AND at least one world exists. Optional steps
    stay pending without blocking completion.
    """
    onboarding = state.get("onboarding") or default_onboarding()
    completed_raw = onboarding.get("completed_steps", [])
    completed = [s for s in STEP_ORDER if s in completed_raw]

    step0_done = "step0" in completed
    account_done = "account" in completed
    world_exists = bool(world_names)
    # A world already on disk answers the folder question implicitly: the author
    # chose (even by accepting the default) before creating it. Without this an
    # install that finished onboarding before step 4 existed would see the step
    # as pending forever.
    content_folder_done = "content_folder" in completed or world_exists

    current_step = _current_step(
        completed, step0_done, account_done, content_folder_done, world_exists
    )
    complete = step0_done and account_done and world_exists

    pending = [
        s
        for s in STEP_ORDER
        if s not in completed and not (s == "content_folder" and content_folder_done)
    ]
    return {
        "completed": complete,
        "current_step": current_step,
        "completed_steps": completed,
        "pending_steps": pending,
        "remote_pending": [s for s in pending if s in REMOTE_STEPS],
        "blocking_pending": [s for s in pending if s in BLOCKING_STEPS],
    }


def _current_step(
    completed: Sequence[str],
    step0_done: bool,
    account_done: bool,
    content_folder_done: bool,
    world_exists: bool,
) -> str:
    if not step0_done:
        return "step0"
    if not account_done:
        return "account"
    if not content_folder_done:
        return "content_folder"
    if not world_exists:
        return "world"
    return "ready"


def commit_step0(
    state: Mapping[str, Any],
    locale: Mapping[str, Any],
    *,
    normalize_locale,
) -> dict[str, Any]:
    """Persist step 0 locale and mark the step completed.

    ``normalize_locale`` is injected (demiurgos_language.normalize_locale) so
    this module stays pure and unit-testable. Raises ValueError on invalid
    locale input (route maps it to a 422 without mutation).
    """
    normalized = normalize_locale(dict(locale))
    next_state = deepcopy(dict(state))
    next_state["locale"] = normalized
    onboarding = deepcopy(next_state.get("onboarding") or default_onboarding())
    steps = list(onboarding.get("completed_steps", []))
    if "step0" not in steps:
        steps.append("step0")
    onboarding["completed_steps"] = steps
    onboarding["current_step"] = "account"
    onboarding["completed"] = False
    next_state["onboarding"] = onboarding
    return next_state


def commit_account_created(state: Mapping[str, Any]) -> dict[str, Any]:
    """Record the local account creation step (R-AC-01, blocking).

    Called by the credentials account endpoint after ``account.create_account``
    commits the account slot; this only mirrors the step so the registry
    reflects the blocking local step without inventing content.
    """
    next_state = deepcopy(dict(state))
    onboarding = deepcopy(next_state.get("onboarding") or default_onboarding())
    steps = list(onboarding.get("completed_steps", []))
    if "account" not in steps:
        steps.append("account")
    onboarding["completed_steps"] = steps
    onboarding["current_step"] = "content_folder"
    onboarding["completed"] = False
    next_state["onboarding"] = onboarding
    return next_state


def commit_content_folder(state: Mapping[str, Any]) -> dict[str, Any]:
    """Record the content-folder step (step 4): the author confirmed the folder.

    No path is stored here on purpose — the data-root pointer is the single
    source of truth (``data_root.write_pointer``). This only mirrors the step so
    the registry resumes at the world instead of asking again.
    """
    next_state = deepcopy(dict(state))
    onboarding = deepcopy(next_state.get("onboarding") or default_onboarding())
    steps = list(onboarding.get("completed_steps", []))
    if "content_folder" not in steps:
        steps.append("content_folder")
    onboarding["completed_steps"] = steps
    onboarding["current_step"] = "world"
    onboarding["completed"] = False
    next_state["onboarding"] = onboarding
    return next_state


def commit_world_created(state: Mapping[str, Any]) -> dict[str, Any]:
    """Record that a world now exists (derived from the authority's result).

    World completion is filesystem truth; this only mirrors it so the registry
    reflects the operational step without inventing content.
    """
    next_state = deepcopy(dict(state))
    onboarding = deepcopy(next_state.get("onboarding") or default_onboarding())
    steps = list(onboarding.get("completed_steps", []))
    for step in ("world", "ready"):
        if step not in steps:
            steps.append(step)
    onboarding["completed_steps"] = steps
    # Completion is truthful: it requires step 0 (locale), the local account
    # (R-AC-01), and a world. Without the account the flow resumes there.
    account_done = "account" in steps
    onboarding["current_step"] = "ready" if account_done else "account"
    onboarding["completed"] = "step0" in steps and account_done and "world" in steps
    next_state["onboarding"] = onboarding
    caps = deepcopy(next_state.get("capabilities") or {})
    caps["world"] = "configured"
    next_state["capabilities"] = caps
    return next_state