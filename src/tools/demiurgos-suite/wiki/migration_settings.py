# -*- coding: utf-8 -*-
"""ONB-4.3 — Legacy migration backend routes: explicit approval API (WU-4c1).

The transactional migration engine (``wiki.migration``, WU-4b) never decides
what to migrate and never auto-renames: approval must arrive explicitly at
call time. This router is that approval surface. A single authenticated
endpoint, ``POST /api/migration/execute``, takes the explicit approval
payload (``world`` + the exact legacy folders to move) and runs the engine's
plan → execute pipeline: plan with transaction id and source/destination
hashes, atomic move of ONLY the approved folders, content-intact hash
verification, and failure restore with rollback evidence.

Contract (design ONB-4.3 / spec OC7, OC23–25; WU-4c1 scope):

- Explicit approval required: missing payload → 422; empty folder list →
  400; folders outside the legacy set → 400. Nothing is ever planned or
  moved without the approval payload (never auto-rename).
- Fail-closed auth: every route resolves the trusted local principal
  (``require_principal``) and returns 401 when absent.
- Machine-readable error mapping: ``MigrationErrorKind`` → HTTP status
  (``invalid_world`` 404, ``empty_approval`` 400, ``unknown_folder`` 400,
  ``collision`` 409, ``symlink_escape`` 422, ``io_error`` 500). The body
  carries ``code`` (the kind) and ``transaction_id`` when a plan was built.
- Honest outcome: ``completed`` or ``rolled_back`` with the transaction id,
  per-folder source/destination hashes, ``restore_verified``, and timestamps
  — the same record the engine persists as JSON evidence.

Out of scope (WU-4c1): no preview endpoints (read-only detection already
lives in readiness ``legacy``), no history endpoints, no frontend, no
registry writes — readiness reflects the moved tree through re-detection.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from wiki.migration import (
    MigrationError,
    MigrationErrorKind,
    MigrationEvidence,
    build_migration_plan,
    execute_migration,
)

logger = logging.getLogger("demiurgos-migration-api")


class MigrationApprovalRequest(BaseModel):
    """Explicit approval payload: world + the exact legacy folders to move."""

    world: str
    folders: list[str]


# Machine-readable MigrationErrorKind -> HTTP status (fail-closed mapping).
# A missing world is a lookup failure (404); an occupied destination is a
# conflict (409); a symlink escape is an unacceptable folder shape (422);
# IO failures are server-side (500). Empty/unknown approval is a client
# payload error (400).
_ERROR_HTTP: dict[MigrationErrorKind, int] = {
    MigrationErrorKind.INVALID_WORLD: 404,
    MigrationErrorKind.EMPTY_APPROVAL: 400,
    MigrationErrorKind.UNKNOWN_FOLDER: 400,
    MigrationErrorKind.COLLISION: 409,
    MigrationErrorKind.SYMLINK_ESCAPE: 422,
    MigrationErrorKind.IO_ERROR: 500,
}


def _migration_error_response(exc: MigrationError) -> JSONResponse:
    payload: dict[str, Any] = {"detail": str(exc), "code": exc.kind.value}
    if exc.transaction_id:
        payload["transaction_id"] = exc.transaction_id
    return JSONResponse(
        status_code=_ERROR_HTTP.get(exc.kind, 500),
        content=payload,
    )


def _outcome_payload(evidence: MigrationEvidence) -> dict[str, Any]:
    """Mirror of the persisted evidence record for the API response."""
    return {
        "status": evidence.outcome.value,
        "transaction_id": evidence.transaction_id,
        "world": evidence.world,
        "restore_verified": evidence.restore_verified,
        "started_at": evidence.started_at,
        "finished_at": evidence.finished_at,
        "error": evidence.error,
        "steps": [
            {
                "folder": step.folder,
                "source": str(step.source),
                "destination": str(step.destination),
                "source_hash": step.source_hash,
                "destination_hash": step.destination_hash,
                "restored": step.restored,
            }
            for step in evidence.steps
        ],
    }


def create_migration_settings_router(
    require_principal: Callable[[Request], Any],
    mundos_dir: Callable[[], Path] | None = None,
    evidence_dir: Callable[[], Path] | None = None,
) -> APIRouter:
    """Build the authenticated /api/migration routes.

    ``require_principal`` returns the trusted local principal for the request
    or None; None maps to 401. ``mundos_dir``/``evidence_dir`` are callables
    so deployments and tests can swap the sandbox at call time; they default
    to None and the router raises if a route is ever used unwired (keeps the
    module importable standalone).
    """
    router = APIRouter(prefix="/api/migration", tags=["migration"])

    def _mundos() -> Path:
        if mundos_dir is None:
            raise RuntimeError("migration router used without a wired mundos dir")
        return Path(mundos_dir())

    def _evidence() -> Path:
        if evidence_dir is None:
            raise RuntimeError("migration router used without a wired evidence dir")
        return Path(evidence_dir())

    def _guard(request: Request) -> None:
        if require_principal(request) is None:
            raise HTTPException(status_code=401, detail="Autenticación requerida")

    @router.post("/execute")
    def execute_approved_migration(
        request: Request, body: MigrationApprovalRequest
    ) -> JSONResponse:
        """Explicitly-approved migration: plan + atomic execute + evidence.

        Never auto-renames: the plan is built only from the explicit approval
        payload and moves exactly those folders. Errors map machine-readably
        (``code``); outcomes return the transaction + evidence record.
        """
        _guard(request)
        try:
            plan = build_migration_plan(_mundos(), body.world, body.folders)
            evidence = execute_migration(plan, _evidence())
        except MigrationError as exc:
            return _migration_error_response(exc)
        logger.info(
            "migration %s for world '%s': %s (%d step(s))",
            evidence.transaction_id,
            evidence.world,
            evidence.outcome.value,
            len(evidence.steps),
        )
        return JSONResponse(status_code=200, content=_outcome_payload(evidence))

    return router
