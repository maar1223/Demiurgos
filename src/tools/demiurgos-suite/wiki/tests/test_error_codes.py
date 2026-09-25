# -*- coding: utf-8 -*-
"""Error-code registry + ApiProblem handler contract (tasks 2.1/2.2).

Covers ERR-REQ-1 (stable codes + structured params), the body shape
``{"detail", "code", "params"}`` rendered by ``register_error_handlers``
on a FastAPI app, and ERR-REQ-5 (English fallback for non-UI consumers:
an app without the handler still answers with the correct status and the
English ``detail``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_TOOLS = _HERE.parents[2]
for _p in (str(_WIKI), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from error_codes import (  # noqa: E402
    REGISTRY,
    ApiProblem,
    problem,
    register_error_handlers,
)


def _registered_app() -> FastAPI:
    app = FastAPI()

    @app.get("/plain")
    def plain() -> None:
        raise problem("import.job_not_found")

    @app.get("/params")
    def with_params() -> None:
        raise problem("import.invalid_section", relative="lore/a.md", section="personajes")

    @app.get("/detail")
    def with_detail() -> None:
        raise problem("import.unsafe_path", path="lore/../x", detail="traversal path")

    register_error_handlers(app)
    return app


def _bare_app() -> FastAPI:
    """App WITHOUT the handler — simulates a hermetic test app / non-UI consumer."""
    app = FastAPI()

    @app.get("/plain")
    def plain() -> None:
        raise problem("import.job_not_found")

    return app


def test_registry_entries_are_consistent() -> None:
    assert REGISTRY, "registry must not be empty"
    for code, spec in REGISTRY.items():
        assert spec.code == code
        assert 400 <= spec.status < 600, f"{code} has an HTTP status"
        assert spec.en_detail.strip(), f"{code} has a non-empty en detail"
    # Spot-check the design's canonical entries (AD-5).
    assert REGISTRY["import.job_not_found"].status == 404
    assert REGISTRY["import.not_owner"].status == 403
    assert REGISTRY["auth.required"].status == 401


def test_api_problem_is_an_http_exception() -> None:
    # ERR-REQ-5: subclassing HTTPException keeps the English fallback working
    # through FastAPI's default handler without any registration.
    assert issubclass(ApiProblem, HTTPException)
    exc = problem("import.job_not_found")
    assert exc.code == "import.job_not_found"
    assert exc.status_code == 404
    assert exc.detail == "Import job not found"
    assert exc.params == {}


def test_registered_handler_renders_structured_body() -> None:
    client = TestClient(_registered_app())
    resp = client.get("/plain")
    assert resp.status_code == 404
    assert resp.json() == {
        "detail": "Import job not found",
        "code": "import.job_not_found",
        "params": {},
    }


def test_params_round_trip_in_body() -> None:
    client = TestClient(_registered_app())
    resp = client.get("/params")
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "import.invalid_section"
    assert body["params"] == {"relative": "lore/a.md", "section": "personajes"}
    # The English detail stays available for logs/CLI (ERR-REQ-5).
    assert body["detail"] == "Invalid section"


def test_detail_override_is_preserved_for_logs() -> None:
    client = TestClient(_registered_app())
    resp = client.get("/detail")
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "import.unsafe_path"
    assert body["detail"] == "traversal path"
    assert body["params"] == {"path": "lore/../x"}


def test_english_fallback_without_handler() -> None:
    """Un-migrated/non-UI consumers keep the current HTTPException contract."""
    client = TestClient(_bare_app())
    resp = client.get("/plain")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Import job not found"}


def test_unknown_code_fails_fast() -> None:
    with pytest.raises(ValueError, match="unknown error code"):
        problem("no.such_code")