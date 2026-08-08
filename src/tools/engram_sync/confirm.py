"""Confirmation: keep-local / keep-Engram / defer, per-item or homogeneous
batch, source-revision revalidation, fail-closed apply boundary. Persistence
only through adapter.apply() after revalidation against fresh discovery; a
changed source leaves both sides untouched and requires a fresh report."""

from dataclasses import dataclass

from .engram_client import EngramError
from .models import (Action, ApplyResult, AuthorizedOperation, Classification,
                     NormalizedItem, PersistenceBoundaryError)

_ALLOWED = {Classification.EQUIVALENT: (Action.DEFER,),
            Classification.LOCAL_ONLY: (Action.KEEP_LOCAL, Action.DEFER),
            Classification.ENGRAM_ONLY: (Action.KEEP_ENGRAM, Action.DEFER),
            Classification.DIVERGENT: (Action.KEEP_LOCAL, Action.KEEP_ENGRAM, Action.DEFER),
            Classification.AMBIGUOUS: (Action.DEFER,),
            Classification.INVALID: (Action.DEFER,),
            Classification.UNREADABLE: (Action.DEFER,)}


@dataclass(frozen=True)
class ConfirmedChoice:
    domain: str
    item_key: str
    action: Action
    source_revision: str


@dataclass(frozen=True)
class ConfirmResult:
    item_key: str
    applied: bool
    message: str = ""


class ConfirmError(Exception):
    """A confirmed choice could not proceed; nothing was written."""


def allowed_actions(classification: Classification) -> tuple[Action, ...]:
    return _ALLOWED.get(classification, (Action.DEFER,))


def homogeneous_batch(choices: list[ConfirmedChoice]) -> bool:
    """Batch confirmation only for one domain, one non-defer action."""
    if not choices:
        return False
    d, a = choices[0].domain, choices[0].action
    return all(c.domain == d and c.action == a and c.action is not Action.DEFER
               for c in choices)


def _source(item: NormalizedItem, action: Action):
    return item.local if action is Action.KEEP_LOCAL else item.remote


def _target(item: NormalizedItem, action: Action) -> str:
    source = (item.remote if action is Action.KEEP_LOCAL and item.remote is not None
              else item.local)
    if source is not None and source.location:
        return source.location
    return f"{item.domain}/{item.item_key}"


def confirm(registry, choices: list[ConfirmedChoice], journal, *,
            confirmation: str = "", run_id: str = "manual",
            dry_run: bool = False) -> list[ConfirmResult]:
    """Revalidate, authorize, journal, and apply a reviewed operation.

    Every choice is validated before any journal row or adapter write exists.
    ``APPLY`` is the only accepted confirmation token. Dry runs still perform
    discovery and validation but never create journal rows or call adapters.
    """
    if not choices:
        raise ConfirmError("no choices were supplied; a fresh report is required")

    try:
        fresh = {(item.domain, item.item_key): item
                 for domain in {c.domain for c in choices}
                 for item in registry.get(domain).discover()}
    except EngramError as err:
        raise ConfirmError(f"saved memory is unavailable ({type(err).__name__}); nothing was written") from err

    pending: list[tuple[ConfirmedChoice, NormalizedItem, str]] = []
    results: list[ConfirmResult] = []
    for choice in choices:
        current = fresh.get((choice.domain, choice.item_key))
        if current is None:
            raise ConfirmError(f"{choice.item_key} is no longer available; a fresh report is required")
        if choice.action is Action.DEFER:
            results.append(ConfirmResult(item_key=choice.item_key, applied=False,
                                         message="deferred; nothing was written"))
            continue
        source = _source(current, choice.action)
        if source is None:
            raise ConfirmError(f"{choice.item_key} has no source for {choice.action.value}; a fresh report is required")
        if source.revision != choice.source_revision:
            raise ConfirmError(f"{choice.item_key} changed since it was reported; a fresh report is required")
        if choice.action not in allowed_actions(current.classification):
            raise ConfirmError(f"{choice.item_key} cannot be applied with {choice.action.value}")
        pending.append((choice, current, _target(current, choice.action)))

    if confirmation != "APPLY":
        raise ConfirmError("explicit confirmation required: pass the exact APPLY confirmation")
    if dry_run:
        return results + [ConfirmResult(item_key=choice.item_key, applied=False,
                                        message="dry-run; nothing was written")
                          for choice, _, _ in pending]

    entries = []
    for choice, _, target in pending:
        op_id = journal.operation_id(choice.domain, choice.item_key,
                                     choice.source_revision, target,
                                     choice.action.value)
        existing = journal.find(op_id)
        if existing is not None:
            if journal.is_resolved(op_id):
                results.append(ConfirmResult(item_key=choice.item_key, applied=False,
                                             message="already completed; no write repeated"))
                continue
            raise ConfirmError(f"{choice.item_key} has incomplete recovery evidence; operation blocked")
        entries.append((choice, target))

    planned = []
    for choice, target in entries:
        try:
            planned.append((choice, target, journal.plan(
                run_id=run_id, domain=choice.domain, item_key=choice.item_key,
                source_revision=choice.source_revision, target=target,
                action=choice.action.value)))
        except (KeyError, ValueError) as err:
            raise ConfirmError(f"{choice.item_key} could not be journaled; operation blocked") from err
    for _, _, entry in planned:
        journal.mark(entry.operation_id, "confirmed", "explicit-confirmation")

    for choice, _, entry in planned:
        try:
            result = registry.get(choice.domain).apply(
                AuthorizedOperation(domain=choice.domain, item_key=choice.item_key,
                                    action=choice.action, source_revision=choice.source_revision))
            if not isinstance(result, ApplyResult):
                raise TypeError("adapter returned an invalid apply result")
            journal.mark(entry.operation_id, "applied", result.status)
            results.append(ConfirmResult(item_key=choice.item_key, applied=True,
                                         message=result.message))
        except NotImplementedError:
            journal.mark(entry.operation_id, "failed", "not-implemented")
            results.append(ConfirmResult(item_key=choice.item_key, applied=False,
                                         message="persistence is not enabled for this item; nothing was written"))
        except PersistenceBoundaryError as err:
            journal.mark(entry.operation_id, "failed", "persistence-boundary")
            results.append(ConfirmResult(item_key=choice.item_key, applied=False,
                                         message=f"apply blocked: {err}; nothing was written"))
        except Exception as err:
            journal.mark(entry.operation_id, "failed", type(err).__name__)
            results.append(ConfirmResult(item_key=choice.item_key, applied=False,
                                         message="apply failed closed; nothing else was written"))
    return results
