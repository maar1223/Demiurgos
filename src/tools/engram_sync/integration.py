"""The explicit scan, report, and apply integration boundary."""

from dataclasses import dataclass

from .confirm import ConfirmedChoice, ConfirmResult, confirm
from .journal import RunJournal
from .models import NormalizedItem
from .views import Report, build_report, scan


@dataclass(frozen=True)
class IntegrationResult:
    """Read-only report plus optional explicitly authorized results."""

    items: tuple[NormalizedItem, ...]
    report: Report
    results: tuple[ConfirmResult, ...] = ()


def scan_and_report(registry, domain: str | None = None) -> IntegrationResult:
    """Scan all requested domains and build the deterministic user report."""
    items = tuple(scan(registry, domain))
    return IntegrationResult(items=items, report=build_report(list(items)))


def apply_confirmation(registry, choices: list[ConfirmedChoice], journal: RunJournal,
                       *, confirmation: str, run_id: str = "manual",
                       dry_run: bool = False) -> list[ConfirmResult]:
    """Apply a previously reviewed choice only after explicit confirmation."""
    return confirm(registry, choices, journal=journal, confirmation=confirmation,
                   run_id=run_id, dry_run=dry_run)
