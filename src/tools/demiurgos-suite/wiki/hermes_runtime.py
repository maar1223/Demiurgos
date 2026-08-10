"""Injected, process-free acceptance seam for Hermes assistant settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class HermesRuntimeResult:
    state: str
    accepted: bool
    reload_required: bool = False


class HermesRuntimeSeam:
    """Translate Hermes acceptance into status without owning process lifecycle.

    Assistant settings owns persistence. This seam only records Hermes
    acceptance, so Active requires acceptance, Pending restart/reload records a
    deferred activation, and every rejection or unavailable result fails closed
    to Saved-not-active. It never starts, stops, reloads, or restarts Hermes.
    """

    def __init__(
        self,
        apply_runtime: Callable[[int], HermesRuntimeResult] | None = None,
    ) -> None:
        self._apply_runtime = apply_runtime or self._unavailable
        self._known_good_revision: int | None = None
        self._pending_revision: int | None = None
        self._applied_revisions: list[int] = []

    @property
    def applied_revisions(self) -> list[int]:
        return list(self._applied_revisions)

    @property
    def known_good_revision(self) -> int | None:
        return self._known_good_revision

    def apply(self, revision: int) -> HermesRuntimeResult:
        """Apply a persisted revision through the injected Hermes signal only."""
        self._applied_revisions.append(revision)
        try:
            result = self._apply_runtime(revision)
        except Exception:
            return self._saved_not_active()

        if not isinstance(result, HermesRuntimeResult):
            return self._saved_not_active()
        if result.state == "active" and result.accepted and not result.reload_required:
            self._known_good_revision = revision
            self._pending_revision = None
            return result
        if result.state == "pending-reload" and result.accepted and result.reload_required:
            self._pending_revision = revision
            return result
        self._pending_revision = None
        return self._saved_not_active()

    def state_for(self, revision: int) -> str:
        if revision == self._known_good_revision:
            return "active"
        if revision == self._pending_revision:
            return "pending-reload"
        return "saved-not-active"

    @staticmethod
    def _unavailable(revision: int) -> HermesRuntimeResult:
        return HermesRuntimeResult("unavailable", accepted=False)

    @staticmethod
    def _saved_not_active() -> HermesRuntimeResult:
        return HermesRuntimeResult("saved-not-active", accepted=False)
