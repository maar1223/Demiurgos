# -*- coding: utf-8 -*-
"""Stable backend error-code registry (AD-4/AD-5).

UI-bound backend errors carry a stable machine-readable ``code`` plus
structured ``params``; the frontend localizes codes through its typed
message catalogue at render time (never a pre-rendered string), so a
language switch re-renders a previously surfaced error in the new
language. The English ``detail`` is retained for logs/CLI and direct API
consumers (ERR-REQ-5): non-UI paths keep working unchanged.

``ApiProblem`` subclasses ``HTTPException`` on purpose. Apps that call
``register_error_handlers(app)`` render the structured body
``{"detail": <en>, "code": <code>, "params": {...}}``; an app without the
handler (e.g. a hermetic test app mounting only a router) still gets the
correct status code plus the English ``detail`` through FastAPI's default
handler, so migration is incremental and never breaks existing consumers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


@dataclass(frozen=True)
class ErrorSpec:
    """One registry entry: stable code, HTTP status, English fallback detail."""

    code: str
    status: int
    en_detail: str


# Stable, locale-independent codes. ``en_detail`` is the English fallback for
# logs/CLI/non-UI consumers; the UI never renders it (ERR-REQ-3/ERR-REQ-4).
REGISTRY: dict[str, ErrorSpec] = {
    "auth.required": ErrorSpec("auth.required", 401, "Authentication required."),
    # Keeps the long-standing literal the API already emitted so existing
    # non-UI consumers and pinned tests see the same string.
    "world.not_found": ErrorSpec("world.not_found", 404, "Mundo no encontrado"),
    "locale.invalid": ErrorSpec("locale.invalid", 422, "Invalid locale input"),
    "import.invalid_source": ErrorSpec(
        "import.invalid_source", 400, "Invalid source_kind"),
    "import.unsafe_path": ErrorSpec("import.unsafe_path", 400, "Unsafe path"),
    "import.invalid_section": ErrorSpec(
        "import.invalid_section", 400, "Invalid section"),
    "import.invalid_cursor": ErrorSpec(
        "import.invalid_cursor", 400, "Invalid cursor"),
    "import.job_not_found": ErrorSpec(
        "import.job_not_found", 404, "Import job not found"),
    "import.not_owner": ErrorSpec("import.not_owner", 403, "Not the job owner"),
    "import.job_busy": ErrorSpec(
        "import.job_busy", 409, "Job busy (lease held)"),
    "import.bad_state": ErrorSpec(
        "import.bad_state", 409, "Job not in an intake state"),
    "import.invalid_decision": ErrorSpec(
        "import.invalid_decision", 400, "Invalid decision"),
    "import.not_configured": ErrorSpec(
        "import.not_configured", 501, "Service not configured"),
    "import.approval_denied": ErrorSpec(
        "import.approval_denied", 409, "Approval could not be issued"),
    "import.execute_failed": ErrorSpec(
        "import.execute_failed", 409, "Execution failed"),
    "import.resume_denied": ErrorSpec(
        "import.resume_denied", 403, "Resume denied"),
    "import.rollback_failed": ErrorSpec(
        "import.rollback_failed", 409, "Rollback failed"),
    # Bug-report submission (report-submission): clear, non-secret codes.
    "bugreport.not_allowlisted": ErrorSpec(
        "bugreport.not_allowlisted", 400,
        "Field is not on the bug-report allow-list"),
    "bugreport.too_large": ErrorSpec(
        "bugreport.too_large", 413, "Bug report exceeds a size cap"),
    "bugreport.rate_limited": ErrorSpec(
        "bugreport.rate_limited", 429, "Too many bug reports submitted"),
    "bugreport.relay_unavailable": ErrorSpec(
        "bugreport.relay_unavailable", 502, "Bug-report relay is unavailable"),
    "bugreport.delivery_failed": ErrorSpec(
        "bugreport.delivery_failed", 502, "Bug-report delivery failed"),
    # Chat document attachments (chat-attachments T2). The UI localizes these
    # through ``error.attachment.*``; ``detail`` stays a stable English fallback.
    "attachment.unsupported_type": ErrorSpec(
        "attachment.unsupported_type", 422,
        "Unsupported attachment type; only .docx and .pdf are accepted."),
    "attachment.too_large": ErrorSpec(
        "attachment.too_large", 413,
        "The attachment exceeds the size limit."),
    "attachment.too_many": ErrorSpec(
        "attachment.too_many", 422,
        "Too many attachments in one message."),
    "attachment.empty": ErrorSpec(
        "attachment.empty", 422,
        "The document has no extractable text."),
    "attachment.conversion_unavailable": ErrorSpec(
        "attachment.conversion_unavailable", 422,
        "Document conversion is unavailable on this platform."),
    "attachment.conversion_failed": ErrorSpec(
        "attachment.conversion_failed", 422,
        "The document could not be converted."),
    "attachment.vision_unavailable": ErrorSpec(
        "attachment.vision_unavailable", 422,
        "Vision is unavailable for the active assistant model."),
    "attachment.vision_failed": ErrorSpec(
        "attachment.vision_failed", 502,
        "The image could not be described."),
    "attachment.expired": ErrorSpec(
        "attachment.expired", 409,
        "The attachment is no longer available."),
}


class ApiProblem(HTTPException):
    """Structured UI-bound error: stable ``code`` + ``params`` (+ en detail).

    Subclassing ``HTTPException`` keeps the English fallback free: without a
    registered handler, FastAPI renders ``{"detail": <en>}`` with the correct
    status, exactly like today's plain ``HTTPException`` sites.
    """

    def __init__(
        self,
        code: str,
        *,
        params: Mapping[str, object] | None = None,
        detail: str | None = None,
        status: int | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        spec = REGISTRY.get(code)
        if spec is None:
            raise ValueError(f"unknown error code: {code}")
        self.code = spec.code
        self.params = dict(params or {})
        super().__init__(
            status_code=status if status is not None else spec.status,
            detail=detail if detail is not None else spec.en_detail,
            headers=dict(headers) if headers else None,
        )


def problem(code: str, *, detail: str | None = None, **params: object) -> ApiProblem:
    """Raise a structured UI-bound error: ``raise problem("import.job_not_found")``.

    Keyword params become the structured ``params`` payload (JSON-safe values
    are passed through; anything else is stringified by the handler). The
    optional ``detail`` overrides the registry English fallback — use it to
    preserve a specific reason for logs/CLI while the UI consumes the code.
    """
    return ApiProblem(code, params=params, detail=detail)


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    return str(value)


def _render_problem(request: Request, exc: ApiProblem) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "code": exc.code,
            "params": {key: _jsonable(value) for key, value in exc.params.items()},
        },
        headers=exc.headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Render ``ApiProblem`` as ``{"detail": <en>, "code": <code>, "params": ...}``."""
    app.add_exception_handler(ApiProblem, _render_problem)