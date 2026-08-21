# -*- coding: utf-8 -*-
"""Minimal Demiurgos Wiki API server - serves world list, files, and entity graph."""
import asyncio
import base64
import hashlib
import io
import inspect
import json
import logging
import mimetypes
import os
import re
import secrets
import shutil
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

# Ensure wiki package is importable
_HERE = Path(__file__).resolve().parent
_SUITE = _HERE.parent
_TOOLS = _SUITE.parent
if str(_SUITE) not in sys.path:
    sys.path.insert(0, str(_SUITE))
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import uvicorn
from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from PIL import Image

from assistant_activity import (
    ActivityTranslator,
    AnswerEvent,
    HermesActivityRequest,
    HermesRunsActivityAdapter,
    SemanticDecisionEvent,
    TerminalEvent,
)
from guided_character_protocol import (
    Capabilities,
    ErrorCode,
    GuidedRequest,
    GuidedResponse,
    GuidedSessionStore,
    MethodologySnapshot,
    Outcome,
    PROTOCOL_VERSION,
    SessionState,
    StructuredError,
    continue_session,
)
from guided_character_domain import (
    FichaValidationError,
    extract_related_goal,
    named_reference_name,
    resolve_named_reference,
    route_new_character_intent,
    confirmation_decision,
    serialize_ficha,
)
from guided_character_persistence import ReindexCoordinator
from guided_character_provider import HermesGuidedProvider, guided_capabilities
from guided_session_store import GuidedSessionStore as DurableGuidedSessionStore
from demiurgos_language import (
    LocaleSettings,
    normalize_locale,
    resolve_ui_language,
)
from local_state import LocalState
from onboarding import (
    commit_step0 as _commit_step0,
    commit_world_created as _commit_world_created,
    status_from as _onboarding_status_from,
)
from readiness import probe_local_storage, project_cards, project_offline
from telegram_settings import (
    has_token as telegram_has_token,
    telegram_state,
)
from world_authority import WorldResultKind, create_world as _create_world
from world_authority import detect_legacy_layout
from methodology_library import (
    AlreadyPublishedError,
    MethodologyLibrary,
    NotPublishedError,
    ValidationError,
)
from methodology_trust import QuarantineStore
from semantic_intent import (
    CONTINUATION_STATES,
    SELF_CONTAINED_SEMANTIC_STATES,
    SemanticContext,
    SemanticIntentProvider,
    SemanticResult,
    action_for_state,
    unavailable_copy,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger("demiurgos-api")

app = FastAPI(title="Demiurgos Wiki API")


def _cors_config() -> dict:
    """Env-based CORS allowlist (ONB-1.9).

    Decision: origins come from ``DEMIURGOS_CORS_ORIGINS`` (comma-separated).
    The default is the local development origin set. Credentials (session
    cookies) are enabled ONLY when the allowlist is explicit — a wildcard
    origin never carries credentials, so secret/credential-bearing requests
    can never be made from arbitrary origins. Existing same-origin dev usage
    (Vite proxy) is unaffected.
    """
    raw = os.environ.get("DEMIURGOS_CORS_ORIGINS", "").strip()
    if not raw:
        origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
        allow_credentials = True
    else:
        origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
        if "*" in origins:
            origins = ["*"]
            allow_credentials = False
        else:
            allow_credentials = True
    return {"origins": origins, "allow_credentials": allow_credentials}


_cors = _cors_config()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors["origins"],
    allow_credentials=_cors["allow_credentials"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[4]  # Demiurgos/ (wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> root)
MUNDOS_DIR = PROJECT_ROOT / "mundos"


_LOCAL_STATE: LocalState | None = None


def _local_state() -> LocalState:
    """Lazily-initialized authoritative local state registry (ONB-1.3).

    Lives under ``<project>/data/local-state.json`` and is runtime-authoritative:
    Engram is recovery/context only and never governs readiness. The registry
    never touches ``.demiurgos-estado.json`` (narrative arc state).
    """
    global _LOCAL_STATE
    if _LOCAL_STATE is None:
        _LOCAL_STATE = LocalState(PROJECT_ROOT / "data" / "local-state.json")
    return _LOCAL_STATE


def _list_worlds() -> list[dict]:
    """List available worlds in mundos/ (skip Ideas, hidden dirs)."""
    worlds = []
    if not MUNDOS_DIR.is_dir():
        return worlds
    for entry in sorted(MUNDOS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith(".") or entry.name.startswith("_"):
            continue
        if entry.name == "Ideas":
            continue
        # Count files in lore + personajes
        lore_count = len(list((entry / "lore").rglob("*.md"))) if (entry / "lore").is_dir() else 0
        char_count = len(list((entry / "personajes").rglob("*.md"))) if (entry / "personajes").is_dir() else 0
        sagas_count = len(list((entry / "sagas").rglob("*.md"))) if (entry / "sagas").is_dir() else 0
        worlds.append({
            "name": entry.name,
            "path": str(entry),
            "lore_count": lore_count,
            "character_count": char_count,
            "saga_count": sagas_count,
        })
    return worlds


def _resolve_mundo_dir(mundo: str) -> Path | None:
    """Resolve *mundo* to its root directory under ``mundos/``.

    A valid world is a direct child of ``MUNDOS_DIR`` that exists and
    passes the same visibility rules as ``_list_worlds`` (not hidden,
    not ``_``-prefixed, not ``Ideas``). Returns None when *mundo* is
    missing, a traversal attempt (``..``, separators, absolute paths,
    drive letters), or not a real world — callers map None to their
    established contract (404 for mutations, soft-empty for lists).
    """
    if not isinstance(mundo, str) or not mundo:
        return None
    if Path(mundo).name != mundo:  # separators / absolute paths / dot segments
        return None
    if mundo.startswith((".", "_")) or mundo == "Ideas":
        return None
    mundo_dir = (MUNDOS_DIR / mundo).resolve()
    if not mundo_dir.is_dir():
        return None
    if mundo_dir.parent != MUNDOS_DIR.resolve():
        return None
    return mundo_dir


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/worlds")
def get_worlds():
    """List all available narrative worlds."""
    worlds = _list_worlds()
    logger.info("GET /api/worlds -> %d worlds", len(worlds))
    return worlds


@app.get("/health")
def health():
    return {"status": "ok", "worlds_available": bool(_list_worlds())}


@app.get("/api/config")
def get_app_config():
    """Non-sensitive global runtime metadata for the frontend.

    Exposes only the normalized UI language (``DEMIURGOS_LANGUAGE`` from the
    project ``.env`` or the environment); never secrets or paths.
    """
    return {"language": _configured_language()}


# ---------------------------------------------------------------------------
# Onboarding / Configuration Center (Slice 1 — Foundation)
#
# Read routes are non-sensitive (they expose onboarding progress and locale,
# never secrets or world content). Every WRITE is gated on the authenticated
# principal and fails closed (401) on unauthenticated access.
# ---------------------------------------------------------------------------


class OnboardingStep0Request(BaseModel):
    ui: str
    conversation: str
    content: str
    region: str | None = None
    region_explicit: bool = False
    iana_timezone: str = "UTC"


class WorldCreateRequest(BaseModel):
    name: str
    lore_skeleton: bool = False


def _world_names() -> list[str]:
    return [world["name"] for world in _list_worlds()]


@app.get("/api/onboarding/status")
def onboarding_status():
    """First-run gate read: completed?, current step, pending/remote pending."""
    return _onboarding_status_from(_local_state().snapshot(), world_names=_world_names())


@app.get("/api/locale")
def get_locale():
    """Current G7/OC3 locale (independent UI/conversation/content languages,
    region override, IANA timezone). Safe default when unset."""
    locale = _local_state().snapshot().get("locale")
    if not isinstance(locale, dict):
        return LocaleSettings().to_dict()
    return locale


@app.post("/api/onboarding/step0")
def onboarding_step0(body: OnboardingStep0Request, request: Request):
    """Persist step 0 locale. Gated: unauthenticated access fails closed."""
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    registry = _local_state()
    try:
        next_state = _commit_step0(
            registry.snapshot(),
            body.model_dump(),
            normalize_locale=normalize_locale,
        )
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    registry.atomic_commit(next_state)
    return _onboarding_status_from(registry.snapshot(), world_names=_world_names())


@app.post("/api/worlds")
def create_world(body: WorldCreateRequest, request: Request):
    """Create a canonical new world (lowercase tree + optional OC8 skeleton).

    Gated write; idempotent repeats are harmless; collisions and unsafe names
    are rejected without mutation. When local auth is disabled, creation is
    allowed without authentication (development mode).
    """
    if _local_auth_enabled():
        principal = _resolve_principal(request)
        if principal is None:
            return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    result = _create_world(MUNDOS_DIR, body.name, lore_skeleton=body.lore_skeleton)
    if result.kind == WorldResultKind.CREATED:
        registry = _local_state()
        registry.atomic_commit(_commit_world_created(registry.snapshot()))
        return JSONResponse(status_code=201, content={
            "kind": result.kind.value,
            "name": result.name,
            "path": str(result.path) if result.path else None,
            "message": result.message,
        })
    if result.kind == WorldResultKind.ALREADY_EXISTS:
        return JSONResponse(status_code=200, content={
            "kind": result.kind.value,
            "name": result.name,
            "path": str(result.path) if result.path else None,
            "message": result.message,
        })
    if result.kind == WorldResultKind.INVALID_NAME:
        return JSONResponse(status_code=400, content={
            "detail": result.message, "code": "invalid_name",
        })
    if result.kind == WorldResultKind.COLLISION:
        return JSONResponse(status_code=409, content={
            "detail": result.message, "code": "collision",
        })
    return JSONResponse(status_code=500, content={
        "detail": result.message, "code": "io_error",
    })


@app.get("/api/onboarding/readiness")
def onboarding_readiness():
    """Essential local readiness + card states (OC11/OC12/OC21).

    Derived runtime truth: the local-storage probe, filesystem world truth,
    the persisted locale, and the three-proof assistant evidence. Cloud cards
    without a dedicated contract (identity/backup) never become ``configured``
    from local evidence (ONB-3.1); the projection downgrades any stale
    registry claim instead of trusting it. The telegram card follows the
    ONB-3.3 backend's real evidence (write-only token presence + last
    connection test) passed through ``telegram_state``. The ``offline``
    breakdown (ONB-3.4) reports local-ready + remote-pending honestly. The
    ``legacy`` list (ONB-4.2) reports worlds using uppercase ``Lore``/
    ``Personajes`` folders — read-only detection; nothing is ever renamed.
    """
    probe = probe_local_storage(PROJECT_ROOT)
    state = _local_state().snapshot()
    cards = project_cards(
        state,
        _world_names(),
        bool(probe["ok"]),
        telegram_state=telegram_state(state, telegram_has_token()),
    )
    return {
        "local_editor": probe,
        "cards": cards,
        "offline": project_offline(cards),
        "legacy": detect_legacy_layout(MUNDOS_DIR),
    }


def _record_assistant_acceptance(runtime_state: str) -> None:
    """Record the three-proof assistant acceptance mirror in the registry.

    Called by the assistant settings router after a successful save whose
    probes passed server-side (ONB-2.5/ONB-3.6). The runtime state is the
    Hermes seam result — ``accepted`` maps to the readiness proof vocabulary;
    any other state (``pending-reload``/``saved-not-active``) keeps the badge
    honestly pending because the projection requires exactly
    text=passed + vision=passed + runtime=accepted.
    """
    registry = _local_state()
    state = registry.snapshot()
    state["assistant_acceptance"] = {
        "text": "passed",
        "vision": "passed",
        "runtime": "accepted" if runtime_state == "active" else runtime_state,
    }
    registry.atomic_commit(state)


# ---------------------------------------------------------------------------
# File tree & content endpoints
# ---------------------------------------------------------------------------

VALID_SECTIONS = {"lore", "personajes", "sagas", "referencias", "media"}

# Internal bookkeeping directories that must never be reachable as content
# targets: ``.papelera`` (trash) and ``.history`` (edit snapshots). Both are
# gitignored and managed exclusively by the server.
_INTERNAL_DIRS = {".papelera", ".history"}


def _resolve_path(mundo: str, section: str, path: str) -> Path | None:
    """Resolve a section-relative file path safely (prevent path traversal).

    Thin convenience over ``_resolve_mundo_path`` for section-style routes:
    the section is validated first, then every world/section/path rule from
    the centralized resolver applies (canonical containment, symlink escape
    rejection, internal-dir denial, section membership after normalization).
    Returns the resolved Path only when the file exists, or None on any
    failure.
    """
    if section not in VALID_SECTIONS:
        return None
    full = _resolve_mundo_path(mundo, f"{section}/{path}")
    if full is None:
        return None
    return full if full.exists() else None


def _resolve_mundo_path(mundo: str, path: str) -> Path | None:
    """Resolve a mundo-relative path safely (prevent path traversal).

    The first path segment must be a valid section (lore/personajes/sagas/
    referencias/media) and the resolved path must stay under
    ``mundos/{mundo}`` — checked canonically against the resolved root plus a
    path separator, so sibling-world names (``mundos/mundo2/...``) can never
    be mistaken for children of ``mundos/mundo``. The resolved target must
    still sit inside a declared section and must not land in an internal
    directory (``.papelera``/``.history``). Symlink escapes are rejected
    because ``.resolve()`` follows them and the containment check then fails.
    Returns the resolved Path even when it does not exist yet (so callers can
    distinguish 400 invalid-path from 404 not-found), or None when the path
    is invalid (traversal, bad section, internal target, empty).
    """
    mundo_dir = _resolve_mundo_dir(mundo)
    if mundo_dir is None:
        return None
    if not path or not path.strip():
        return None
    parts = [p for p in Path(path).parts if p not in ("", ".")]
    if not parts or parts[0] not in VALID_SECTIONS:
        return None
    try:
        full = (mundo_dir / path).resolve()
    except Exception:
        return None
    root = str(mundo_dir)
    if not (str(full) == root or str(full).startswith(root + os.sep)):
        return None
    try:
        rel_parts = full.relative_to(mundo_dir).parts
    except ValueError:
        return None
    if not rel_parts or rel_parts[0] not in VALID_SECTIONS:
        return None
    if any(p in _INTERNAL_DIRS for p in rel_parts):
        return None
    return full


# ---------------------------------------------------------------------------
# EditPrincipal seam — trusted editing identity (Slice 1A)
#
# Every gated write (confirmation, save, create, restore) must be bound to a
# principal resolved from trusted deployment auth/session middleware. The only
# provider in this bounded slice is explicitly enabled local development auth;
# production and the default configuration remain fail-closed. Caller-supplied
# identity (headers, body fields) is forgeable and MUST never be promoted to a
# principal here. The seam remains the single plug point for deployments.
# ---------------------------------------------------------------------------


class EditPrincipal:
    """Opaque, trusted identity for editing operations.

    Carries only an internal identifier (session/user handle supplied by
    trusted middleware) plus an optional human label for logs. The id is
    never exposed to clients as a credential — logs reference it opaquely.
    """

    __slots__ = ("id", "label")

    def __init__(self, principal_id: str, label: str = ""):
        if not isinstance(principal_id, str) or not principal_id.strip():
            raise ValueError("EditPrincipal requires a non-empty principal id")
        self.id = principal_id
        self.label = label

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<EditPrincipal {self.id!r}>"


_LOCAL_AUTH_MODE = "local-dev"
_LOCAL_SESSION_COOKIE = "demiurgos_local_session"
_LOCAL_SESSION_TTL = timedelta(hours=8)
_local_sessions: dict[str, dict] = {}
_local_session_lock = threading.Lock()


def _auth_mode() -> str:
    """Read auth mode at request time so local tests can isolate configuration."""
    return os.environ.get("DEMIURGOS_AUTH_MODE", "disabled").strip().lower()


def _is_loopback_request(request: Request | None) -> bool:
    """Use the socket peer only; Host and forwarded headers are untrusted."""
    if request is None or request.client is None:
        return False
    return request.client.host in {"127.0.0.1", "::1"}


def _local_auth_enabled() -> bool:
    return _auth_mode() == _LOCAL_AUTH_MODE


def _prune_local_sessions(now: datetime | None = None) -> None:
    current = now or datetime.now(timezone.utc)
    for token_hash in [
        key for key, record in _local_sessions.items()
        if record["expires_at"] <= current
    ]:
        _local_sessions.pop(token_hash, None)


def _local_session_for_request(request: Request | None) -> dict | None:
    if not _local_auth_enabled() or not _is_loopback_request(request):
        return None
    token = request.cookies.get(_LOCAL_SESSION_COOKIE) if request else None
    if not token:
        return None
    now = datetime.now(timezone.utc)
    token_hash = _hash_token(token)
    with _local_session_lock:
        _prune_local_sessions(now)
        return _local_sessions.get(token_hash)


def _local_status(request: Request) -> dict:
    enabled = _local_auth_enabled()
    if enabled and not _is_loopback_request(request):
        raise HTTPException(status_code=403, detail="Local development auth requires loopback")
    session = _local_session_for_request(request) if enabled else None
    return {
        "mode": _auth_mode(),
        "enabled": enabled,
        "authenticated": session is not None,
        "label": session["label"] if session else None,
    }


@app.get("/api/auth/local-dev/session")
def local_dev_session_status(request: Request):
    """Return local development auth status without exposing session material."""
    return _local_status(request)


@app.post("/api/auth/local-dev/session")
def local_dev_session_start(request: Request, response: Response):
    """Start an explicit loopback-only local development session."""
    if not _local_auth_enabled():
        raise HTTPException(status_code=403, detail="Local development auth is disabled")
    if not _is_loopback_request(request):
        raise HTTPException(status_code=403, detail="Local development auth requires loopback")

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    session = {
        "principal_id": f"local-dev-session-{secrets.token_hex(16)}",
        "label": "Local development user",
        "expires_at": now + _LOCAL_SESSION_TTL,
    }
    with _local_session_lock:
        _prune_local_sessions(now)
        _local_sessions[_hash_token(token)] = session
    response.set_cookie(
        _LOCAL_SESSION_COOKIE,
        token,
        max_age=int(_LOCAL_SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )
    return {
        "mode": _LOCAL_AUTH_MODE,
        "enabled": True,
        "authenticated": True,
        "label": session["label"],
    }


@app.delete("/api/auth/local-dev/session")
def local_dev_session_logout(request: Request, response: Response):
    """Clear the current local development session and its browser cookie."""
    if _local_auth_enabled() and not _is_loopback_request(request):
        raise HTTPException(status_code=403, detail="Local development auth requires loopback")
    token = request.cookies.get(_LOCAL_SESSION_COOKIE)
    if token:
        with _local_session_lock:
            _local_sessions.pop(_hash_token(token), None)
    response.delete_cookie(_LOCAL_SESSION_COOKIE, path="/", samesite="lax")
    return _local_status(request)


def _resolve_principal(request=None) -> EditPrincipal | None:
    """Resolve the trusted edit principal for a request.

    Local development auth is the only built-in provider. It requires the
    explicit ``DEMIURGOS_AUTH_MODE=local-dev`` setting, a loopback socket peer,
    and a server-issued HttpOnly session cookie. Until those conditions hold,
    every gated write fails closed. This function MUST NOT trust caller-
    supplied identity: request headers and body fields are forgeable and are
    deliberately ignored.
    """
    session = _local_session_for_request(request)
    if session is None:
        return None
    return EditPrincipal(session["principal_id"], label=session["label"])


# ---------------------------------------------------------------------------
# Guided character route contracts (PR5-A)
# ---------------------------------------------------------------------------

class GuidedStartRequest(BaseModel):
    author_input: str


class GuidedTurnRequest(BaseModel):
    session_id: str
    base_revision: int
    author_input: str


class GuidedProposalRequest(BaseModel):
    session_id: str
    base_revision: int
    key: str


class GuidedIndexRetryRequest(BaseModel):
    session_id: str
    base_revision: int


class GuidedSerializeRequest(BaseModel):
    session_id: str
    base_revision: int
    slug: str | None = None
    title: str | None = None


# ---------------------------------------------------------------------------
# Methodology library contracts (Taller de Herramientas)
# ---------------------------------------------------------------------------

class MethodologyDraftRequest(BaseModel):
    skill_id: str
    version: str
    name: str
    source: str
    description: str = ""
    phases: list[str] = []
    language: str | None = None


class MethodologyActivateRequest(BaseModel):
    world: str
    skill_id: str
    version: str


class MethodologyRollbackRequest(BaseModel):
    world: str


# The provider is capability-admitted and separate from the legacy chat route.
# The durable SQLite store is the default: without ``DEMIURGOS_GUIDED_SESSIONS_DB``
# it resolves to the stable repo-local ``<repo>/data/guided-sessions.sqlite3``
# (see ``default_db_path``), so sessions survive a restart for the 30-day TTL.
# The env var remains an explicit override; ``:memory:`` is only reachable by
# passing it directly. Every session pins the active methodology/version
# snapshot at creation.
_GUIDED_SESSIONS_DB = os.environ.get("DEMIURGOS_GUIDED_SESSIONS_DB")
_GUIDED_SESSIONS = DurableGuidedSessionStore(db_path=_GUIDED_SESSIONS_DB)
_GUIDED_PROVIDER = None
_GUIDED_CAPABILITIES: Capabilities | None = None
_GUIDED_PROBE_LOCK = asyncio.Lock()
# Active methodology/version pin. Phase 3 wires this to the compiled
# methodology library; until then the builtin guided-character contract is
# active. A session pinned to a different version fails closed on resume.
_BUILTIN_METHODOLOGY_VERSION = "builtin"
_ACTIVE_METHODOLOGY_VERSION: str | None = _BUILTIN_METHODOLOGY_VERSION
# Server-owned methodology library + mandatory-quarantine trust store. Both
# are created lazily so tests and callers can swap roots per process.
_METHODOLOGY_LIBRARY: MethodologyLibrary | None = None
_METHODOLOGY_QUARANTINE: QuarantineStore | None = None


def _methodology_library() -> MethodologyLibrary:
    global _METHODOLOGY_LIBRARY
    if _METHODOLOGY_LIBRARY is None:
        _METHODOLOGY_LIBRARY = MethodologyLibrary(
            PROJECT_ROOT / "data" / "methodology" / "library.json"
        )
    return _METHODOLOGY_LIBRARY


def _methodology_quarantine() -> QuarantineStore:
    global _METHODOLOGY_QUARANTINE
    if _METHODOLOGY_QUARANTINE is None:
        _METHODOLOGY_QUARANTINE = QuarantineStore(
            PROJECT_ROOT / "data" / "methodology" / "quarantine"
        )
    return _METHODOLOGY_QUARANTINE


def _active_methodology_version(world: str) -> str | None:
    """Active methodology version for a world.

    A published version explicitly activated for the world wins; otherwise the
    builtin pin applies. Only NEW sessions consult this; existing sessions
    keep their pinned snapshot and fail closed when it no longer matches.
    """
    activation = _methodology_library().active_for(world)
    if activation is not None:
        return activation.version
    return _ACTIVE_METHODOLOGY_VERSION


def _active_methodology_snapshot(world: str) -> MethodologySnapshot:
    """Pin the currently active methodology/version at session creation."""
    activation = _methodology_library().active_for(world)
    if activation is not None:
        return MethodologySnapshot(
            skill_id=activation.skill_id,
            skill_version=activation.version,
            compiled_contract_digest=activation.digest,
        )
    active = _ACTIVE_METHODOLOGY_VERSION or _BUILTIN_METHODOLOGY_VERSION
    return MethodologySnapshot(
        skill_id="guided-character-v1",
        skill_version=active,
        compiled_contract_digest=None,
    )
# Semantic routing seam: the mandatory Hermes-first semantic gate. Wired to a
# SemanticIntentProvider(ACTIVITY_ADAPTER) below, after the runs adapter exists.
# No lexical/plain-chat fallback exists; unavailable/invalid/exhausted Hermes
# results fail closed as ``blocked`` with localized safe copy. The type is kept
# Optional because tests replace the seam with fakes.
_SEMANTIC_PROVIDER: SemanticIntentProvider | None = None
_GUIDED_REINDEX = ReindexCoordinator(MUNDOS_DIR, lambda world: _get_graph(world))
_GUIDED_INDEX_REQUESTS: dict[str, tuple[str, str, str]] = {}
# Review records are diskless until the existing confirmed create route succeeds.
_GUIDED_PENDING_PROPOSALS: dict[str, dict[str, str | int]] = {}


def _invalidate_guided_proposal(session_id: str) -> None:
    for edit_id, record in list(_GUIDED_PENDING_PROPOSALS.items()):
        if record.get("session_id") == session_id:
            _GUIDED_PENDING_PROPOSALS.pop(edit_id, None)


def _guided_public_state(state: SessionState) -> dict:
    """Serialize only the frontend-compatible, non-provenance session view."""
    return {
        "protocol_version": PROTOCOL_VERSION,
        "session_id": state.session_id,
        "world": state.world,
        "phase": state.phase,
        "mode": state.mode,
        "depth": state.depth,
        "revision": state.revision,
        "pending_question": state.pending_question,
        "messages": [
            {
                "role": "author" if message.message_type.value == "author_input" else "assistant",
                "content": str(message.content.get("question", message.content.get("text", ""))),
            }
            for message in state.messages
        ],
        "candidate": {
            "accepted_canon": state.candidate.accepted_canon,
            "proposals": state.candidate.proposals,
            "unresolved_references": state.candidate.unresolved_references,
            "conflicts": state.candidate.conflicts,
        },
        "proposal": next((
            {"key": key, "label": key.replace("_", " ").title(),
             "value": str(value.get("value", value)) if isinstance(value, dict) else str(value),
             **({"rationale": str(value["rationale"])} if isinstance(value, dict) and "rationale" in value else {})}
            for key, value in state.candidate.proposals.items()
        ), None),
        "reference": {
            "name": state.reference_name,
            "verified": bool(state.reference_context),
            "context": state.reference_context,
            "source": "canonical-graph" if state.reference_context else None,
            "goal": state.relation_goal or None,
        },
    }


_GUIDED_ERROR_STATUS = {
    ErrorCode.INVALID_INPUT: 422,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.REVISION_CONFLICT: 409,
    ErrorCode.CAPABILITY_UNAVAILABLE: 503,
    ErrorCode.PROVIDER_UNAVAILABLE: 503,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.CANCELLED: 499,
    ErrorCode.MALFORMED_OUTPUT: 502,
    ErrorCode.INTERNAL: 500,
}


def _guided_error_response(error: StructuredError) -> JSONResponse:
    return JSONResponse(
        status_code=_GUIDED_ERROR_STATUS.get(error.code, 500),
        content={"detail": error.message, **error.as_dict()},
    )


def _guided_route_unavailable(request: Request) -> JSONResponse:
    if _resolve_principal(request) is None:
        return _guided_error_response(StructuredError(
            ErrorCode.UNAUTHORIZED, "Authentication required.", False,
        ))
    return _guided_error_response(StructuredError(
        ErrorCode.CAPABILITY_UNAVAILABLE,
        "Guided character creation is unavailable.",
        True,
    ))


def _guided_principal(request: Request) -> tuple[EditPrincipal | None, JSONResponse | None]:
    principal = _resolve_principal(request)
    if principal is None:
        return None, _guided_error_response(StructuredError(
            ErrorCode.UNAUTHORIZED, "Authentication required.", False,
        ))
    return principal, None


def _guided_result(response, state: SessionState | None):
    if response.error:
        return _guided_error_response(response.error)
    if state is None:
        return _guided_error_response(StructuredError(
            ErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
        ))
    return _guided_public_state(state)


def _guided_methodology_block(state: SessionState) -> JSONResponse | None:
    """Fail closed when the pinned methodology/version no longer matches.

    Applying a methodology change MUST require a brand-new session: resuming an
    old session whose snapshot version differs from the active one is rejected
    without any mutation.
    """
    snapshot = _GUIDED_SESSIONS.methodology_snapshot(state.session_id, state.authorization_binding)
    if snapshot is None or snapshot.skill_version is None:
        return None
    active = _active_methodology_version(state.world)
    if active is not None and snapshot.skill_version != active:
        return _guided_error_response(StructuredError(
            ErrorCode.INVALID_INPUT,
            "The methodology version has changed; start a new session.",
            False,
        ))
    return None


def _guided_revalidation_block(session_id: str, principal_id: str) -> JSONResponse | None:
    """Fail closed when a durable-restart pending proposal needs revalidation."""
    if _GUIDED_SESSIONS.requires_revalidation(session_id, principal_id):
        return _guided_error_response(StructuredError(
            ErrorCode.INVALID_INPUT,
            "The pending proposal requires revalidation before it can be serialized; continue the session.",
            True,
        ))
    return None


async def _guided_continue(
    mundo: str, session_id: str, revision: int, author_input: str,
    principal: EditPrincipal, reference_context: str = "", reference_name: str | None = None,
):
    state = _GUIDED_SESSIONS.recover(session_id, principal.id)
    if state is not None and state.phase == "complete":
        return _guided_public_state(state)
    if state is not None:
        methodology_block = _guided_methodology_block(state)
        if methodology_block is not None:
            return methodology_block
    if state is not None and state.world == mundo and state.reference_context:
        reference_context = state.reference_context
        reference_name = state.reference_name
    if state is not None and state.phase == "confirmation":
        decision = confirmation_decision(author_input)
        if decision is None:
            next_state = _GUIDED_SESSIONS.resolve_confirmation(
                session_id, principal.id, revision, None,
                _guided_confirmation_text("ambiguous"),
            )
            return _guided_public_state(next_state) if next_state else _guided_error_response(
                StructuredError(ErrorCode.REVISION_CONFLICT, "The session revision is stale.", True)
            )
        next_state = _GUIDED_SESSIONS.resolve_confirmation(
            session_id, principal.id, revision, decision,
            _guided_confirmation_text("decline") if decision is False else "",
        )
        if next_state is None:
            return _guided_error_response(StructuredError(ErrorCode.REVISION_CONFLICT, "The session revision is stale.", True))
        if decision is False:
            return _guided_public_state(next_state)
        revision = next_state.revision
        author_input = next_state.confirmation_input
    mode = state.mode if state is not None else "full"
    depth = state.depth if state is not None else "standard"
    relation_goal = state.relation_goal if state is not None else ""
    methodology: str | None = None
    if state is not None:
        snapshot = _GUIDED_SESSIONS.methodology_snapshot(state.session_id, principal.id)
        if snapshot is not None and snapshot.skill_version:
            methodology = f"{snapshot.skill_id or 'guided-character'}:{snapshot.skill_version}"
    request = GuidedRequest(
        PROTOCOL_VERSION, f"guided-{uuid.uuid4().hex}", session_id, mundo,
        revision, principal.id, author_input, reference_context=reference_context,
        reference_name=reference_name,
        relation_goal=relation_goal,
        guided_mode=mode,
        question_depth=depth,
        methodology=methodology,
    )
    response, state = await continue_session(
        _GUIDED_SESSIONS, _GUIDED_PROVIDER, request, _GUIDED_CAPABILITIES,
    )
    if state is not None:
        _invalidate_guided_proposal(session_id)
    return _guided_result(response, state)


async def _probe_guided_capabilities() -> Capabilities | None:
    """Probe Hermes once; concurrent requests share the fail-closed result."""
    global _GUIDED_CAPABILITIES
    if _GUIDED_CAPABILITIES is not None:
        return _GUIDED_CAPABILITIES
    async with _GUIDED_PROBE_LOCK:
        if _GUIDED_CAPABILITIES is not None:
            return _GUIDED_CAPABILITIES
        provider = _GUIDED_PROVIDER
        probe = getattr(provider, "probe", None)
        if not callable(probe):
            return None
        try:
            assessment = await probe()
            _GUIDED_CAPABILITIES = guided_capabilities(assessment)
        except Exception:
            _GUIDED_CAPABILITIES = None
        return _GUIDED_CAPABILITIES


@app.get("/api/{mundo}/guided-character/session/{session_id}")
def recover_guided_character(mundo: str, session_id: str, request: Request):
    principal, error = _guided_principal(request)
    if error:
        return error
    state = _GUIDED_SESSIONS.recover(session_id, principal.id)
    if state is None:
        return _guided_error_response(StructuredError(ErrorCode.UNAUTHORIZED, "The session is unavailable.", False))
    if state.world != mundo:
        return _guided_error_response(StructuredError(ErrorCode.UNAUTHORIZED, "The session is unavailable.", False))
    methodology_block = _guided_methodology_block(state)
    if methodology_block is not None:
        return methodology_block
    return _guided_public_state(state)


@app.post("/api/{mundo}/guided-character/session")
async def start_guided_character(mundo: str, body: GuidedStartRequest, request: Request):
    """Start a guarded guided character session (Hermes-first).

    The mandatory semantic gate interprets the creation message BEFORE any
    Demiurgos intent classifier or action: ``route_new_character_intent``
    derives guided policy only after a validated Hermes decision. Unavailable,
    invalid, unwired, or exhausted Hermes fails closed with the localized safe
    blocked envelope and zero session, proposal, or write.
    """
    principal, error = _guided_principal(request)
    if error:
        return error
    if _GUIDED_PROVIDER is None:
        return _guided_error_response(StructuredError(
            ErrorCode.CAPABILITY_UNAVAILABLE,
            "Guided character creation is unavailable.", True,
        ))
    capabilities = await _probe_guided_capabilities()
    if capabilities is None or not capabilities.admitted():
        return _guided_error_response(StructuredError(
            ErrorCode.CAPABILITY_UNAVAILABLE,
            "Guided character creation is unavailable.", True,
        ))
    if _resolve_mundo_dir(mundo) is None:
        return _guided_error_response(StructuredError(ErrorCode.INVALID_INPUT, "The world is unavailable.", False))
    # Resolve the named reference ONCE; the semantic gate and the guarded
    # session both reuse this single graph read (no double query).
    reference_context, graph_unavailable, reference_name = _named_reference_context(mundo, body.author_input)
    if graph_unavailable:
        return _guided_error_response(StructuredError(
            ErrorCode.CAPABILITY_UNAVAILABLE,
            "The named character reference is unavailable.", True,
        ))
    has_reference = reference_name is not None and not graph_unavailable
    context = SemanticContext(
        mundo=mundo or None,
        reference=reference_name if has_reference else None,
        graph=reference_context if has_reference else None,
    )
    result = await _semantic_gate(mundo, body.author_input, context=context)
    if result.decision is None:
        logger.info(
            "guided start: no validated Hermes decision (unavailable=%s attempts=%s); fail closed",
            result.unavailable, result.attempts,
        )
        return result.as_dict()
    intent = route_new_character_intent(body.author_input, allow_descriptive_seed=True)
    if not intent.is_new_character:
        return _guided_error_response(StructuredError(ErrorCode.INVALID_INPUT, "New-character intent is required.", False))
    session_id = f"guided-{uuid.uuid4().hex}"
    relation_goal = extract_related_goal(body.author_input, reference_name=reference_name).summary
    _GUIDED_SESSIONS.create(
        session_id, mundo, principal.id,
        reference_context=reference_context, reference_name=reference_name,
        relation_goal=relation_goal, mode=intent.mode, depth=intent.depth,
        methodology_snapshot=_active_methodology_snapshot(mundo),
    )
    if intent.requires_confirmation:
        confirmed = _GUIDED_SESSIONS.begin_confirmation(
            session_id, principal.id, body.author_input,
            _guided_confirmation_text("start"),
        )
        return _guided_public_state(confirmed or state)
    return await _guided_continue(
        mundo, session_id, 0, body.author_input, principal, reference_context, reference_name,
    )


@app.post("/api/{mundo}/guided-character/turn")
async def continue_guided_character(mundo: str, body: GuidedTurnRequest, request: Request):
    """Continue a guarded guided session (Hermes-first).

    The mandatory semantic gate interprets the turn message (including typed
    confirmation responses) BEFORE the guarded confirmation policy or guided
    provider runs. Unavailable Hermes fails closed with the localized safe
    blocked envelope and zero session mutation, proposal, or write.
    """
    principal, error = _guided_principal(request)
    if error:
        return error
    state = _GUIDED_SESSIONS.recover(body.session_id, principal.id)
    if state is None or state.world != mundo:
        return _guided_error_response(StructuredError(ErrorCode.UNAUTHORIZED, "The session is unavailable.", False))
    if state.revision != body.base_revision:
        return _guided_error_response(StructuredError(ErrorCode.REVISION_CONFLICT, "The session revision is stale.", True))
    has_reference = state.reference_name is not None
    context = SemanticContext(
        mundo=mundo or None,
        reference=state.reference_name if has_reference else None,
        graph=state.reference_context if has_reference else None,
    )
    result = await _semantic_gate(mundo, body.author_input, context=context)
    if result.decision is None:
        logger.info(
            "guided turn: no validated Hermes decision (unavailable=%s attempts=%s); fail closed",
            result.unavailable, result.attempts,
        )
        return result.as_dict()
    return await _guided_continue(mundo, body.session_id, body.base_revision, body.author_input, principal)


@app.post("/api/{mundo}/guided-character/proposal/accept")
def accept_guided_character_proposal(mundo: str, body: GuidedProposalRequest, request: Request):
    principal, error = _guided_principal(request)
    if error:
        return error
    session = _GUIDED_SESSIONS.recover(body.session_id, principal.id)
    if session is None:
        return _guided_error_response(StructuredError(ErrorCode.REVISION_CONFLICT, "The session revision is stale.", True))
    methodology_block = _guided_methodology_block(session)
    if methodology_block is not None:
        return methodology_block
    try:
        state = _GUIDED_SESSIONS.accept_proposal(
            body.session_id, principal.id, body.base_revision, body.key,
        )
    except KeyError:
        return _guided_error_response(StructuredError(ErrorCode.INVALID_INPUT, "The proposal is unavailable.", False))
    if state is None:
        return _guided_error_response(StructuredError(ErrorCode.REVISION_CONFLICT, "The session revision is stale.", True))
    _invalidate_guided_proposal(body.session_id)
    return _guided_public_state(state)


@app.post("/api/{mundo}/guided-character/proposal/reject")
def reject_guided_character_proposal(mundo: str, body: GuidedProposalRequest, request: Request):
    principal, error = _guided_principal(request)
    if error:
        return error
    session = _GUIDED_SESSIONS.recover(body.session_id, principal.id)
    if session is None:
        return _guided_error_response(StructuredError(ErrorCode.REVISION_CONFLICT, "The session revision is stale.", True))
    methodology_block = _guided_methodology_block(session)
    if methodology_block is not None:
        return methodology_block
    try:
        state = _GUIDED_SESSIONS.reject_proposal(
            body.session_id, principal.id, body.base_revision, body.key,
        )
    except KeyError:
        return _guided_error_response(StructuredError(ErrorCode.INVALID_INPUT, "The proposal is unavailable.", False))
    if state is None:
        return _guided_error_response(StructuredError(ErrorCode.REVISION_CONFLICT, "The session revision is stale.", True))
    _invalidate_guided_proposal(body.session_id)
    return _guided_public_state(state)


@app.post("/api/{mundo}/guided-character/proposal/serialize")
def serialize_guided_character(mundo: str, body: GuidedSerializeRequest, request: Request):
    """Create a diskless, revision-bound new-file proposal for the review UI."""
    principal, error = _guided_principal(request)
    if error:
        return error
    state = _GUIDED_SESSIONS.recover(body.session_id, principal.id)
    if state is None or state.world != mundo:
        return _guided_error_response(StructuredError(ErrorCode.UNAUTHORIZED, "The session is unavailable.", False))
    if state.revision != body.base_revision:
        return _guided_error_response(StructuredError(ErrorCode.REVISION_CONFLICT, "The session revision is stale.", True))
    methodology_block = _guided_methodology_block(state)
    if methodology_block is not None:
        return methodology_block
    revalidation_block = _guided_revalidation_block(body.session_id, principal.id)
    if revalidation_block is not None:
        return revalidation_block
    slug = body.slug or f"guided-{body.session_id.removeprefix('guided-')[-12:]}"
    title = body.title or "Guided Character"
    world_dir = _resolve_mundo_dir(mundo)
    existing_targets = set()
    if world_dir is not None and (world_dir / "personajes").is_dir():
        existing_targets = {f"personajes/{path.name}" for path in (world_dir / "personajes").glob("*.md")}
    try:
        proposal = serialize_ficha(state.candidate, world=mundo, slug=slug, title=title, existing_targets=existing_targets)
    except FichaValidationError as exc:
        return _guided_error_response(StructuredError(ErrorCode.INVALID_INPUT, str(exc), False))
    digest = hashlib.sha256(proposal.content.encode("utf-8")).hexdigest()
    edit_id = f"guided-proposal-{uuid.uuid4().hex}"
    _GUIDED_PENDING_PROPOSALS[edit_id] = {
        "edit_id": edit_id, "principal_id": principal.id, "session_id": state.session_id,
        "guided_revision": state.revision, "target": proposal.target,
        "content": proposal.content, "digest": digest,
    }
    return {
        "proposal_id": edit_id, "target": proposal.target, "base_revision": "",
        "proposed_content": proposal.content, "proposed_digest": digest,
        "rationale": "Review the guided character before creating the file.",
        "is_new_file": True, "guided_session_id": state.session_id,
        "guided_revision": state.revision,
    }


@app.post("/api/{mundo}/guided-character/index/retry")
def retry_guided_character_index(mundo: str, body: GuidedIndexRetryRequest, request: Request):
    principal, error = _guided_principal(request)
    if error:
        return error
    state = _GUIDED_SESSIONS.recover(body.session_id, principal.id)
    if state is None or state.world != mundo:
        return _guided_error_response(StructuredError(ErrorCode.UNAUTHORIZED, "The session is unavailable.", False))
    if state.revision != body.base_revision:
        return _guided_error_response(StructuredError(ErrorCode.REVISION_CONFLICT, "The session revision is stale.", True))
    record = _GUIDED_INDEX_REQUESTS.get(body.session_id)
    if record is None:
        return _guided_error_response(StructuredError(ErrorCode.INVALID_INPUT, "No persisted character is awaiting indexing.", False))
    operation_id, target, digest = record
    result = _GUIDED_REINDEX.reconcile(
        operation_id=operation_id, mundo=mundo, target=target, content_digest=digest,
    )
    payload = _guided_public_state(state)
    payload.update({"index_status": result.index_status, "retryable": result.retryable, "message": result.message})
    return payload


# ---------------------------------------------------------------------------
# Confirmation store — server-verified single-use proofs (Slices 1B and PR 3)
# Hashed, short-TTL, single-use tokens bound to principal/target/kind/
# edit_id/base+proposed digests. In-memory; restart invalidates outstanding
# confirmations (fail closed). The atomic replace, per-target lock, and
# snapshot seam used by the write pipeline live below
# (_target_lock_for / history helpers / _snapshot_before_write / _atomic_write).
# ---------------------------------------------------------------------------

_CONFIRM_TTL_SECONDS = 600

# token_hash -> bound write attributes (principal/target/kind/edit_id/digests)
_confirmation_store: dict[str, dict] = {}


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _prune_expired_confirmations() -> None:
    now = datetime.now(timezone.utc)
    for h in [h for h, r in _confirmation_store.items() if r["expires_at"] <= now]:
        _confirmation_store.pop(h, None)


def _issue_confirmation(principal, target_key, kind, edit_id, base_digest,
                        proposed_digest, history_id=None):
    _prune_expired_confirmations()
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=_CONFIRM_TTL_SECONDS)
    _confirmation_store[_hash_token(token)] = {
        "principal_id": principal.id,
        "target_key": target_key,
        "kind": kind,
        "edit_id": edit_id,
        "base_digest": base_digest,
        "proposed_digest": proposed_digest,
        "history_id": history_id,
        "expires_at": expires_at,
    }
    return token, expires_at


def _redeem_confirmation(principal, target_key, kind, edit_id, proposed_digest,
                         token, history_id=None) -> bool:
    """Consume a token; True only when every bound attribute matches and it
    is unexpired. Any mismatch, replay, or expiry consumes it (single use)."""
    if not token:
        return False
    record = _confirmation_store.pop(_hash_token(token), None)
    if record is None:
        return False
    if datetime.now(timezone.utc) > record["expires_at"]:
        return False
    return (
        record["principal_id"] == principal.id
        and record["target_key"] == target_key
        and record["kind"] == kind
        and record["edit_id"] == edit_id
        and record["proposed_digest"] == proposed_digest
        and record.get("history_id") == history_id
    )


def _target_key(mundo: str, section: str, path: str) -> str:
    return f"{mundo}::{section}::{path.replace(chr(92), '/')}"


def _digest_of(full: Path) -> str:
    return hashlib.sha256(full.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Papelera (trash) — v2 per-entry layout
#
#   .papelera/{section}/{entry_id12}/meta.json
#   .papelera/{section}/{entry_id12}/{original_name}
#
# Each deleted item lives in its own entry dir named after a 12-hex entry_id.
# meta.json records provenance (original_path, kind, deleted_at, size) so the
# entry can be listed, restored, or purged without scanning the original tree.
# ---------------------------------------------------------------------------

def _trash_root(mundo_dir: Path) -> Path:
    return mundo_dir / ".papelera"


def _trash_section_dir(mundo_dir: Path, section: str) -> Path:
    if section not in VALID_SECTIONS:
        raise HTTPException(404, f"Sección inválida: {section}")
    return _trash_root(mundo_dir) / section


def _trash_entry_dir(mundo_dir: Path, section: str, entry_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", entry_id):
        raise HTTPException(404, "Entrada no encontrada")
    d = _trash_section_dir(mundo_dir, section) / entry_id
    if not d.exists() or not d.is_dir():
        raise HTTPException(404, "Entrada no encontrada")
    return d


def _write_trash_meta(entry_dir: Path, meta: dict) -> None:
    (entry_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def _read_trash_meta(entry_dir: Path) -> dict:
    return json.loads((entry_dir / "meta.json").read_text(encoding="utf-8"))


def _purge_expired_trash_entries(mundo_dir: Path, max_age_days: int = 30) -> int:
    """Permanently delete trash entries older than ``max_age_days`` days.

    Lazy TTL: run on read (GET /papelera), never on delete/restore. An
    entry is expired when ``deleted_at`` is STRICTLY older than
    ``now - max_age_days``; an entry equal to the threshold survives —
    at exactly 30 days it is kept, at 30 days + 1 second it is purged.

    Malformed entries (no meta.json, unreadable JSON, missing or
    unparseable ``deleted_at``, non-text values, naive datetimes) are
    skipped and KEPT: a corrupt entry never crashes the purge nor gets
    silently destroyed. Returns the number of entries permanently purged.
    """
    threshold = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    purged = 0
    root = _trash_root(mundo_dir)
    if not root.exists():
        return 0
    for section in VALID_SECTIONS:
        sec_dir = root / section
        if not sec_dir.is_dir():
            continue
        for entry_dir in sec_dir.iterdir():
            if not entry_dir.is_dir():
                continue
            meta_file = entry_dir / "meta.json"
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                raw = meta["deleted_at"]
                if not isinstance(raw, str):
                    raise ValueError("deleted_at no es texto")
                # Normalize ISO-8601 UTC 'Z' suffix for fromisoformat.
                if raw.endswith("Z"):
                    raw = raw[:-1] + "+00:00"
                deleted_at = datetime.fromisoformat(raw)
                if deleted_at.tzinfo is None:
                    raise ValueError("deleted_at sin zona horaria")
            except Exception as exc:
                logger.warning(
                    "Papelera TTL: meta inválida en %s (%s) — se conserva",
                    entry_dir,
                    exc,
                )
                continue
            if deleted_at < threshold:
                shutil.rmtree(entry_dir, ignore_errors=True)
                purged += 1
    return purged


def _list_trash(mundo_dir: Path) -> list[dict]:
    out = []
    root = _trash_root(mundo_dir)
    if not root.exists():
        return out
    for section in VALID_SECTIONS:
        sec_dir = root / section
        if not sec_dir.is_dir():
            continue
        for entry_dir in sorted(sec_dir.iterdir()):
            if not entry_dir.is_dir():
                continue
            meta_file = entry_dir / "meta.json"
            if not meta_file.exists():
                continue
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            meta.setdefault("entry_id", entry_dir.name)
            meta.setdefault("section", section)
            out.append(meta)
    return out


_RE_PORTADA = re.compile(r"^portada:\s*(.+)$", re.MULTILINE)
_RE_BODY_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _read_head(full: Path) -> str | None:
    """First 8KB of a file decoded as text (bounded read cost)."""
    try:
        with open(full, "rb") as fh:
            head = fh.read(8192)
    except OSError:
        return None
    return head.decode("utf-8", errors="replace")


def _resolve_cover(mundo: str, full: Path) -> str | None:
    """Resolve a cover for a markdown file.

    Reads only the first 8KB of the file (bounded cost). Prefers the
    ``portada:`` frontmatter value; soft-validates existence through the
    same media resolver as /media and falls back to the first body image
    ``![alt](ruta)`` (suffix ``#...`` stripped). Returns the value as
    written (mundo-relative) or None when no valid image is found.
    """
    text = _read_head(full)
    if text is None:
        return None

    m = _RE_PORTADA.search(text)
    if m:
        val = m.group(1).strip().strip('"').strip("'")
        if val:
            r = _resolve_media_path(mundo, val)
            if r is not None and r.is_file():
                return val

    m = _RE_BODY_IMAGE.search(text)
    if m:
        val = m.group(1).strip().split("#", 1)[0].strip()
        if val:
            r = _resolve_media_path(mundo, val)
            if r is not None and r.is_file():
                return val
    return None


def _next_duplicate_name(full: Path) -> Path:
    """Find the next free duplicate name in *full*'s directory.

    Sequence: ``{stem}-copia{ext}``, then ``{stem}-2{ext}``, ``{stem}-3{ext}``…
    until a name that does not exist yet.
    """
    stem = full.stem
    ext = full.suffix
    candidate = full.with_name(f"{stem}-copia{ext}")
    n = 2
    while candidate.exists():
        candidate = full.with_name(f"{stem}-{n}{ext}")
        n += 1
    return candidate


@app.get("/api/{mundo}/{section}/tree")
def get_tree(mundo: str, section: str, covers: bool = Query(False)):
    """List files in a section as a tree structure.

    With ``?covers=true`` every file node carries a ``portada`` field
    (mundo-relative cover path or null); without it the field is absent
    (S29). Covers are resolved in a single sweep — no per-card requests.
    Every file node also carries a ``status`` field (draft|stable) when
    the file's leading frontmatter declares a known OKF ficha status;
    the field is omitted for unknown values and for directories.
    """
    if section not in VALID_SECTIONS:
        return []
    mundo_dir = _resolve_mundo_dir(mundo)
    if mundo_dir is None:
        return []
    section_dir = mundo_dir / section
    if not section_dir.is_dir():
        return []
    
    def _build_tree(dir_path: Path, base: Path) -> list[dict]:
        items = []
        try:
            # Directories first, then files; each group sorted
            # alphabetically, case-insensitively (e.g. "alpha" before "Zeta").
            entries = sorted(
                (
                    e for e in dir_path.iterdir()
                    if not e.name.startswith(".") and not e.name.startswith("_")
                ),
                key=lambda e: e.name.lower(),
            )
            for entry in entries:
                if not entry.is_dir():
                    continue
                rel = entry.relative_to(base)
                children = _build_tree(entry, base)
                if children:  # Only include dirs with files
                    node = {
                        "name": entry.name,
                        "path": str(rel).replace("\\", "/"),
                        "is_dir": True,
                        "children": children,
                    }
                    if covers:
                        node["portada"] = None
                    items.append(node)
            for entry in entries:
                if not entry.is_file():
                    continue
                if entry.suffix.lower() not in (
                    ".md", ".txt", ".json",
                    ".jpg", ".jpeg", ".png", ".gif", ".webp",
                ):
                    continue
                rel = entry.relative_to(base)
                node = {
                    "name": entry.name,
                    "path": str(rel).replace("\\", "/"),
                    "is_dir": False,
                }
                status = _file_status(entry)
                if status is not None:
                    node["status"] = status
                if covers:
                    node["portada"] = _resolve_cover(mundo, entry)
                items.append(node)
        except PermissionError:
            pass
        return items
    
    tree = _build_tree(section_dir, section_dir)
    logger.info("GET /api/%s/%s/tree -> %d items", mundo, section, len(tree))
    return tree


@app.get("/api/{mundo}/{section}/file")
def get_file(mundo: str, section: str, path: str):
    """Read a file's content plus its revision.

    ``revision`` is the SHA-256 of the file's exact bytes on disk (raw
    bytes, not the newline-normalized text), so editors can detect stale
    bases before confirming a write.
    """
    full = _resolve_path(mundo, section, path)
    if full is None:
        return {"error": "Archivo no encontrado", "path": path}
    try:
        content = full.read_text(encoding="utf-8")
        return {
            "path": path,
            "content": content,
            "size": len(content),
            "revision": hashlib.sha256(full.read_bytes()).hexdigest(),
        }
    except Exception as e:
        return {"error": str(e), "path": path}


# ---------------------------------------------------------------------------
# Atomic replacement + per-target lock + snapshot seam (Slices 1C and PR 3)
#
# The gated write pipeline serializes per resolved target: the on-disk base
# recheck, the pre-write snapshot hook, and the replacement all run under
# one lock, so a concurrent writer can never slip a change between the
# digest check and os.replace (TOCTOU-safe). Replacement writes a unique
# same-directory temp file and atomically renames it over the target;
# cleanup on failure guarantees rejected/crashed writes leave no strays.
# ---------------------------------------------------------------------------

_target_locks: dict[str, threading.Lock] = {}
_target_lock_guard = threading.Lock()


def _target_lock_for(full: Path) -> threading.Lock:
    """Return the per-target lock for a resolved path (created on demand)."""
    key = str(full)
    with _target_lock_guard:
        return _target_locks.setdefault(key, threading.Lock())


_HISTORY_MAX_SNAPSHOTS = 20
_HISTORY_MAX_AGE = timedelta(days=30)
_HISTORY_VERSION = 1
_HISTORY_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_HISTORY_FIELDS = frozenset({
    "version", "snapshot_id", "target", "created_at", "content_b64",
    "content_digest", "size",
})


def _history_world_and_target(full: Path) -> tuple[Path, str]:
    """Return the authorized world root and canonical mundo-relative target."""
    resolved = full.resolve()
    mundos_root = MUNDOS_DIR.resolve()
    if not mundos_root.is_dir():
        raise ValueError("history root is unavailable")
    for mundo_dir in mundos_root.iterdir():
        if not mundo_dir.is_dir():
            continue
        try:
            relative = resolved.relative_to(mundo_dir.resolve())
        except ValueError:
            continue
        if len(relative.parts) < 2 or relative.parts[0] not in VALID_SECTIONS:
            continue
        return mundo_dir.resolve(), relative.as_posix()
    raise ValueError("history target is outside an authorized world")


def _history_bucket(full: Path) -> tuple[Path, str]:
    """Return the private bucket for one canonical target."""
    mundo_dir, target = _history_world_and_target(full)
    bucket_id = hashlib.sha256(target.encode("utf-8")).hexdigest()
    history_root = mundo_dir / ".history"
    bucket = history_root / bucket_id
    if history_root.is_symlink() or bucket.is_symlink():
        raise ValueError("history storage is unsafe")
    return bucket, target


def _parse_history_time(value) -> datetime:
    """Parse an aware UTC-compatible history timestamp."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid history timestamp")
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        raise ValueError("history timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def _read_history_record(entry_path: Path, expected_target: str,
                         *, allow_expired: bool = False) -> dict | None:
    """Read and strictly validate one snapshot without repairing it."""
    if (
        entry_path.is_symlink()
        or not entry_path.is_file()
        or not _HISTORY_ID_RE.fullmatch(entry_path.stem)
    ):
        return None
    try:
        record = json.loads(entry_path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or set(record) != _HISTORY_FIELDS:
            return None
        snapshot_id = record["snapshot_id"]
        if (
            type(record["version"]) is not int
            or record["version"] != _HISTORY_VERSION
            or not isinstance(snapshot_id, str)
            or not _HISTORY_ID_RE.fullmatch(snapshot_id)
            or snapshot_id != entry_path.stem
            or record["target"] != expected_target
        ):
            return None
        created_at = _parse_history_time(record["created_at"])
        now = datetime.now(timezone.utc)
        if created_at > now:
            return None
        expired = created_at < now - _HISTORY_MAX_AGE
        if expired and not allow_expired:
            return None
        encoded = record["content_b64"]
        if not isinstance(encoded, str):
            return None
        content_bytes = base64.b64decode(encoded.encode("ascii"), validate=True)
        digest = record["content_digest"]
        if (
            not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or hashlib.sha256(content_bytes).hexdigest() != digest
        ):
            return None
        if type(record["size"]) is not int or record["size"] != len(content_bytes):
            return None
        content = content_bytes.decode("utf-8")
    except (OSError, ValueError, TypeError, UnicodeEncodeError,
            UnicodeDecodeError, json.JSONDecodeError):
        return None
    return {
        "snapshot_id": snapshot_id,
        "target": expected_target,
        "created_at": created_at,
        "content": content,
        "content_digest": digest,
        "size": len(content_bytes),
        "path": entry_path,
        "expired": expired,
    }


def _history_entry_response(record: dict) -> dict:
    """Build the public, authorized representation of a valid snapshot."""
    return {
        "id": record["snapshot_id"],
        "snapshot_id": record["snapshot_id"],
        "target": record["target"],
        "created_at": record["created_at"].isoformat().replace("+00:00", "Z"),
        "content": record["content"],
        "revision": record["content_digest"],
        "size": record["size"],
    }


def _list_history_records(full: Path) -> list[dict]:
    """List only valid, unexpired records for the exact target, newest first."""
    bucket, target = _history_bucket(full)
    if not bucket.is_dir():
        return []
    records = []
    for entry_path in bucket.iterdir():
        record = _read_history_record(entry_path, target)
        if record is not None:
            records.append(record)
    records.sort(key=lambda item: (item["created_at"], item["snapshot_id"]), reverse=True)
    return records


def _load_history_entry(full: Path, snapshot_id: str) -> dict | None:
    """Load one snapshot only when its identifier and target both match."""
    if not isinstance(snapshot_id, str) or not _HISTORY_ID_RE.fullmatch(snapshot_id):
        return None
    bucket, target = _history_bucket(full)
    return _read_history_record(bucket / f"{snapshot_id}.json", target)


def _write_history_snapshot(content_bytes: bytes, target: str, bucket: Path,
                            snapshot_id: str) -> None:
    """Atomically create one snapshot record."""
    bucket.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc)
    record = {
        "version": _HISTORY_VERSION,
        "snapshot_id": snapshot_id,
        "target": target,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "content_b64": base64.b64encode(content_bytes).decode("ascii"),
        "content_digest": hashlib.sha256(content_bytes).hexdigest(),
        "size": len(content_bytes),
    }
    destination = bucket / f"{snapshot_id}.json"
    temporary = bucket / f".{snapshot_id}.{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
        os.replace(str(temporary), str(destination))
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _prune_history(full: Path) -> None:
    """Remove valid expired records and valid records beyond the 20-item cap."""
    bucket, target = _history_bucket(full)
    if not bucket.is_dir():
        return
    valid = []
    for entry_path in bucket.iterdir():
        record = _read_history_record(entry_path, target, allow_expired=True)
        if record is None:
            continue
        if record["expired"]:
            entry_path.unlink()
            continue
        valid.append(record)
    valid.sort(key=lambda item: (item["created_at"], item["snapshot_id"]), reverse=True)
    for record in valid[_HISTORY_MAX_SNAPSHOTS:]:
        record["path"].unlink()


def _snapshot_before_write(full: Path) -> None:
    """Persist the exact pre-write bytes for the authorized target."""
    if not full.is_file():
        raise ValueError("snapshot target is not a file")
    bucket, target = _history_bucket(full)
    content_bytes = full.read_bytes()
    _write_history_snapshot(content_bytes, target, bucket, uuid.uuid4().hex)
    _prune_history(full)


def _atomic_write(full: Path, content: str) -> None:
    """Replace *full* atomically from a same-directory temp file.

    Writes ``.{name}.{uuid}.tmp`` next to the target (same filesystem, so
    ``os.replace`` is atomic) and renames it over the target. The temp is
    removed on any failure so a rejected/crashed write never leaves stray
    files behind.
    """
    tmp = full.with_name(f".{full.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(str(tmp), str(full))
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _write_content(mundo: str, section: str, path: str, body: dict,
                   request: Request, kind: str):
    """Shared gated persistence for edit, create, and restore operations.

    Fails closed without a trusted principal and a valid single-use token;
    the on-disk digest is re-checked under the per-target lock (409
    stale_base) and the write is an atomic same-directory replace.
    """
    principal = _resolve_principal(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    if section not in VALID_SECTIONS:
        raise HTTPException(status_code=400, detail="Sección inválida")
    if _resolve_mundo_dir(mundo) is None:
        raise HTTPException(status_code=404, detail="Mundo no encontrado")
    full = _resolve_mundo_path(mundo, f"{section}/{path}")
    if full is None:
        raise HTTPException(status_code=400, detail="Path traversal detectado")
    if kind in ("edit", "restore"):
        if not full.exists():
            raise HTTPException(status_code=404, detail="Archivo no encontrado")
    elif full.exists():
        raise HTTPException(status_code=409, detail="El archivo ya existe")
    content, edit_id = body.get("content"), body.get("edit_id")
    token, proposed_digest = body.get("token"), body.get("proposed_digest")
    base_revision = body.get("base_revision")
    if not isinstance(content, str) or not isinstance(edit_id, str) or not edit_id.strip():
        raise HTTPException(status_code=400, detail="content y edit_id requeridos")
    if not isinstance(token, str) or not token.strip():
        raise HTTPException(status_code=400, detail="token requerido")
    if not isinstance(proposed_digest, str) or len(proposed_digest) != 64:
        raise HTTPException(status_code=400, detail="proposed_digest requerido")
    if kind in ("edit", "restore") and (not isinstance(base_revision, str) or len(base_revision) != 64):
        raise HTTPException(status_code=400, detail="base_revision requerido")
    if hashlib.sha256(content.encode("utf-8")).hexdigest() != proposed_digest:
        raise HTTPException(status_code=403, detail="Confirmation inválida")
    history_id = body.get("snapshot_id") if kind == "restore" else None
    if kind == "restore":
        record = _load_history_entry(full, history_id)
        if record is None or record["content"] != content:
            raise HTTPException(status_code=403, detail="History entry invalid")
        if record["content_digest"] != proposed_digest:
            raise HTTPException(status_code=403, detail="History entry invalid")
    if not _redeem_confirmation(principal, _target_key(mundo, section, path), kind,
                                edit_id, proposed_digest, token, history_id):
        raise HTTPException(status_code=403, detail="Confirmation inválida")
    # Per-target lock: base recheck, snapshot hook, and replacement run
    # atomically with respect to other writers of the same resolved target.
    with _target_lock_for(full):
        if kind in ("edit", "restore"):
            if not full.exists() or _digest_of(full) != base_revision:
                raise HTTPException(status_code=409, detail="base_revision desactualizado")
        elif full.exists():
            raise HTTPException(status_code=409, detail="El archivo ya existe")
        try:
            if kind in ("edit", "restore"):
                # Snapshot every replacement, including restore, before the
                # atomic replace so the current version remains recoverable.
                _snapshot_before_write(full)
            full.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(full, content)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error al guardar: {e}")
    return {"success": True, "path": path}


def _resolve_history_target(mundo: str, path: str) -> tuple[Path, str]:
    """Resolve a canonical mundo-relative history target."""
    if not isinstance(path, str) or not path.strip():
        raise HTTPException(status_code=400, detail="History path required")
    normalized = path.replace("\\", "/")
    parts = Path(normalized).parts
    if len(parts) < 2 or parts[0] not in VALID_SECTIONS:
        raise HTTPException(status_code=400, detail="Invalid history path")
    full = _resolve_mundo_path(mundo, normalized)
    if full is None:
        raise HTTPException(status_code=400, detail="Path traversal detected")
    if not full.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        _, target = _history_bucket(full)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid history target")
    return full, target


@app.get("/api/{mundo}/history")
def list_history(mundo: str, request: Request,
                 path: str = Query(..., description="Canonical mundo-relative file path")):
    """List valid snapshots for one authorized file, newest first."""
    if _resolve_principal(request) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    full, target = _resolve_history_target(mundo, path)
    entries = [_history_entry_response(record) for record in _list_history_records(full)]
    return {"target": target, "entries": entries}


@app.post("/api/{mundo}/{section}/edit-confirmation")
def edit_confirmation(mundo: str, section: str, path: str, body: dict, request: Request):
    """Issue a single-use confirmation token for a reviewed edit.

    Requires a trusted principal; existing-file edits must claim the current
    on-disk digest (409 stale_base). Returns token, expiry, proposed digest.
    """
    principal = _resolve_principal(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    if section not in VALID_SECTIONS:
        raise HTTPException(status_code=400, detail="Sección inválida")
    kind = body.get("kind", "edit")
    if kind not in ("edit", "new", "restore"):
        raise HTTPException(status_code=400, detail="kind inválido")
    edit_id = body.get("edit_id")
    base_revision, proposed_content = body.get("base_revision"), body.get("proposed_content")
    if not isinstance(edit_id, str) or not edit_id.strip():
        raise HTTPException(status_code=400, detail="edit_id requerido")
    full = _resolve_mundo_path(mundo, f"{section}/{path}")
    if full is None:
        raise HTTPException(status_code=400, detail="Path traversal detectado")
    history_id = body.get("snapshot_id") if kind == "restore" else None
    if kind == "restore":
        record = _load_history_entry(full, history_id)
        if record is None:
            raise HTTPException(status_code=404, detail="History entry not found")
        if proposed_content is not None and proposed_content != record["content"]:
            raise HTTPException(status_code=400, detail="History content mismatch")
        proposed_content = record["content"]
    elif not isinstance(proposed_content, str):
        raise HTTPException(status_code=400, detail="proposed_content requerido")
    if kind in ("edit", "restore"):
        if not full.exists():
            raise HTTPException(status_code=404, detail="Archivo no encontrado")
        if not isinstance(base_revision, str) or len(base_revision) != 64:
            raise HTTPException(status_code=400, detail="base_revision requerido")
        if _digest_of(full) != base_revision:
            raise HTTPException(status_code=409, detail="base_revision desactualizado")
    else:
        if full.exists():
            raise HTTPException(status_code=409, detail="El archivo ya existe")
        base_revision = ""  # a new file has no base digest to bind
    proposed_digest = hashlib.sha256(proposed_content.encode("utf-8")).hexdigest()
    token, expires_at = _issue_confirmation(
        principal, _target_key(mundo, section, path), kind,
        edit_id, base_revision, proposed_digest, history_id)
    return {"token": token, "expires_at": expires_at.isoformat(),
            "proposed_digest": proposed_digest}


@app.post("/api/{mundo}/history/restore")
def restore_history(mundo: str, body: dict, request: Request):
    """Restore a valid snapshot through the existing gated write pipeline."""
    if _resolve_principal(request) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    body = body or {}
    full, target = _resolve_history_target(mundo, body.get("path"))
    snapshot_id = body.get("snapshot_id") or body.get("id")
    record = _load_history_entry(full, snapshot_id)
    if record is None:
        raise HTTPException(status_code=404, detail="History entry not found")
    supplied_content = body.get("content")
    if supplied_content is not None and supplied_content != record["content"]:
        raise HTTPException(status_code=400, detail="History content mismatch")
    section, relative_path = target.split("/", 1)
    payload = dict(body)
    payload.update({
        "content": record["content"],
        "snapshot_id": snapshot_id,
        "proposed_digest": record["content_digest"],
    })
    return _write_content(
        mundo, section, relative_path, payload, request, kind="restore"
    )


@app.post("/api/{mundo}/{section}/file")
def save_file(mundo: str, section: str, path: str, body: dict, request: Request):
    """Save an existing file — gated by a valid confirmation token."""
    return _write_content(mundo, section, path, body, request, kind="edit")


@app.post("/api/{mundo}/{section}/save")
def save_file_via_save(mundo: str, section: str, path: str, body: dict, request: Request):
    """Save an existing file — contract-compatible alias for the frontend.

    Same gated behavior as POST /file; kept as a distinct route so both
    callers work.
    """
    return _write_content(mundo, section, path, body, request, kind="edit")


@app.post("/api/{mundo}/{section}/create")
def create_file(mundo: str, section: str, path: str, body: dict, request: Request):
    """Create a new file — gated by a ``kind=new`` confirmation token."""
    pending = _GUIDED_PENDING_PROPOSALS.get(body.get("edit_id"))
    if pending is not None:
        principal = _resolve_principal(request)
        target = f"{section}/{path}"
        digest = hashlib.sha256(body.get("content", "").encode("utf-8")).hexdigest()
        if (principal is None or pending["principal_id"] != principal.id
                or pending["target"] != target or pending["content"] != body.get("content")
                or pending["digest"] != digest or body.get("proposed_digest") != digest):
            raise HTTPException(status_code=409, detail="Guided proposal is stale or altered")
    result = _write_content(mundo, section, path, body, request, kind="new")
    if pending is not None:
        full = _resolve_mundo_path(mundo, f"{section}/{path}")
        if full is None or not full.is_file() or _digest_of(full) != pending["digest"]:
            raise HTTPException(status_code=500, detail="Persisted guided content failed digest verification")
        session_id = str(pending["session_id"])
        operation_id = f"guided-create-{pending['edit_id']}" if "edit_id" in pending else f"guided-create-{body['edit_id']}"
        _GUIDED_INDEX_REQUESTS[session_id] = (operation_id, str(pending["target"]), str(pending["digest"]))
        result = dict(result)
        reconciliation = _GUIDED_REINDEX.reconcile(
            operation_id=operation_id, mundo=mundo,
            target=str(pending["target"]), content_digest=str(pending["digest"]),
        )
        result.update({"index_status": reconciliation.index_status, "retryable": reconciliation.retryable,
                       "message": reconciliation.message})
    return result


@app.post("/api/{mundo}/{section}/diff")
def diff_preview(mundo: str, section: str, path: str, body: dict):
    """Line-by-line diff between current file content and proposed content."""
    if section not in VALID_SECTIONS:
        raise HTTPException(status_code=400, detail="Sección inválida")
    if _resolve_mundo_dir(mundo) is None:
        raise HTTPException(status_code=404, detail="Mundo no encontrado")
    full = _resolve_path(mundo, section, path)
    original_content = ""
    if full is not None:
        try:
            original_content = full.read_text(encoding="utf-8")
        except Exception:
            original_content = ""

    new_content = body.get("content", "")
    diff_lines = _compute_diff(original_content, new_content)

    return {
        "original_path": path,
        "original_content": original_content,
        "new_content": new_content,
        "diff": diff_lines,
    }


def _compute_diff(original: str, nuevo: str) -> list[dict]:
    """Line-by-line diff between two texts (same contract as the old
    storage.compute_diff): entries {type: same|added|removed, text}."""
    import difflib

    orig_lines = original.splitlines(keepends=True)
    new_lines = nuevo.splitlines(keepends=True)

    diff_lines: list[dict] = []
    for line in difflib.unified_diff(orig_lines, new_lines, n=9999):
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("@@"):
            continue
        if line.startswith("-"):
            text = line[1:].rstrip("\n")
            diff_lines.append({"type": "removed", "text": text})
        elif line.startswith("+"):
            text = line[1:].rstrip("\n")
            diff_lines.append({"type": "added", "text": text})
        else:
            text = line.rstrip("\n")
            diff_lines.append({"type": "same", "text": text})

    # Edge case: unified_diff returns empty when files are identical.
    # Spec S22 requires all lines as type="same" for unchanged files.
    if not diff_lines and orig_lines:
        for line in orig_lines:
            diff_lines.append({"type": "same", "text": line.rstrip("\n")})

    return diff_lines


@app.delete("/api/{mundo}/{section}/file")
def delete_file(mundo: str, section: str, path: str):
    """Move a file or folder to the trash (``mundos/{mundo}/.papelera``).

    Never permanently deletes: ``shutil.move`` (recursive for folders)
    into ``.papelera/{section}/{entry_id12}/`` preserving the item's
    basename, plus a ``meta.json`` describing the entry. Invalidate the
    graph cache so the trashed entity disappears from graph/search.
    """
    if section not in VALID_SECTIONS:
        raise HTTPException(status_code=400, detail="Sección inválida")
    if _resolve_mundo_dir(mundo) is None:
        raise HTTPException(status_code=404, detail="Mundo no encontrado")
    if not path or not path.strip():
        raise HTTPException(status_code=400, detail="Ruta vacía")
    full = _resolve_mundo_path(mundo, f"{section}/{path}")
    if full is None:
        raise HTTPException(status_code=400, detail="Path traversal detectado")
    if not full.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    mundo_dir = _resolve_mundo_dir(mundo)
    is_dir = full.is_dir()
    # size computed BEFORE the move (after moving, the source path no longer
    # exists): file = its own st_size; dir = total bytes of every file under
    # the tree (recursively).
    if is_dir:
        size = sum(f.stat().st_size for f in full.rglob("*") if f.is_file())
    else:
        size = full.stat().st_size

    try:
        # 12-hex entry_id; collisions are astronomically unlikely but retry
        # up to 10 times so we never overwrite a live entry dir.
        entry_id = None
        for _ in range(10):
            candidate = uuid.uuid4().hex[:12]
            if not (_trash_section_dir(mundo_dir, section) / candidate).exists():
                entry_id = candidate
                break
        if entry_id is None:
            raise RuntimeError("no free entry_id after 10 attempts")
        entry_dir = _trash_section_dir(mundo_dir, section) / entry_id
        entry_dir.mkdir(parents=True, exist_ok=False)
        shutil.move(str(full), str(entry_dir / full.name))
        _write_trash_meta(entry_dir, {
            "entry_id": entry_id,
            "original_path": path.replace("\\", "/"),
            "kind": "dir" if is_dir else "file",
            "deleted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "size": size,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al mover a la papelera: {e}")
    _graph_indices.pop(mundo, None)
    return {"success": True, "path": path, "entry_id": entry_id}


@app.get("/api/{mundo}/papelera")
def list_papelera(mundo: str):
    """List all trash entries across every section, each with its meta.json.

    Lazy TTL: expired entries (deleted_at strictly older than 30 days) are
    purged on read, before the survivors are listed. The response keeps
    today's envelope (``{"entries": [...]}``); ``purged`` is included only
    when at least one entry was removed, so the zero-case contract stays
    byte-identical.
    """
    mundo_dir = _resolve_mundo_dir(mundo)
    if mundo_dir is None:
        return {"entries": []}
    purged = _purge_expired_trash_entries(mundo_dir)
    resp = {"entries": _list_trash(mundo_dir)}
    if purged:
        resp["purged"] = purged
        logger.info("Papelera TTL: %d entradas expiradas purgadas en %s", purged, mundo)
    return resp


@app.post("/api/{mundo}/papelera/restore")
def restore_papelera(mundo: str, body: dict):
    """Move a trashed entry back to its original section-relative path.

    Collisions at the destination are resolved with the same duplicate-name
    convention as /duplicate (``{stem}-copia{ext}``, ``{stem}-2{ext}``…).
    """
    entry_id = (body or {}).get("entry_id") or ""
    section = (body or {}).get("section")
    if section not in VALID_SECTIONS:
        raise HTTPException(status_code=400, detail="Sección requerida")
    mundo_dir = _resolve_mundo_dir(mundo)
    if mundo_dir is None:
        raise HTTPException(status_code=404, detail="Mundo no encontrado")
    entry_dir = _trash_entry_dir(mundo_dir, section, entry_id)
    meta = _read_trash_meta(entry_dir)
    original_path = meta.get("original_path")
    if not isinstance(original_path, str) or not original_path.strip():
        raise HTTPException(status_code=500, detail="meta.json corrupto: original_path inválido")
    if section == "media":
        # Media entries store original_path canonically as mundo-relative
        # ("wiki/media/foto.jpg" or "referencias/visuales/imagenes/y.png").
        # Validate it stays inside one of the media bases, then rebuild the
        # exact original target (the file was moved to trash, so it does not
        # exist yet — _resolve_media_path's structural Pass 2 confirms it is
        # a legit media path without requiring the file to exist).
        if _resolve_media_path(mundo, original_path) is None:
            raise HTTPException(status_code=500, detail="meta.json corrupto: original_path inválido")
        target = (mundo_dir / original_path).resolve()
        media_prefixes = [str(b.resolve()) + os.sep for b in _get_media_bases(mundo)]
        if not any(str(target).startswith(p) for p in media_prefixes):
            raise HTTPException(status_code=500, detail="meta.json corrupto: original_path inválido")
    else:
        target = _resolve_mundo_path(mundo, f"{section}/{original_path}")
        if target is None:
            raise HTTPException(status_code=500, detail="meta.json corrupto: original_path inválido")
    src = entry_dir / Path(original_path).name
    dst = target
    if dst.exists():
        dst = _next_duplicate_name(dst)
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        if section == "media":
            # The thumbnail travels as a unit: move it to the same target
            # parent, matching the (possibly deduplicated) restored name.
            thumb = entry_dir / f"{Path(original_path).stem}_thumb{Path(original_path).suffix}"
            if thumb.is_file():
                thumb_dst = dst.with_name(f"{dst.stem}_thumb{dst.suffix}")
                shutil.move(str(thumb), str(thumb_dst))
        shutil.rmtree(entry_dir, ignore_errors=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al restaurar: {e}")
    _graph_indices.pop(mundo, None)
    return {
        "restored_to": str(dst.relative_to(mundo_dir)).replace("\\", "/"),
        "entry_id": entry_id,
    }


@app.delete("/api/{mundo}/papelera")
def purge_papelera(mundo: str, entry_id: str = "", section: str = ""):
    """Purge one entry (entry_id + section) or the whole trash (no params)."""
    mundo_dir = _resolve_mundo_dir(mundo)
    if mundo_dir is None:
        raise HTTPException(status_code=404, detail="Mundo no encontrado")
    if not entry_id:
        root = _trash_root(mundo_dir)
        count = 0
        if root.exists():
            for sec in VALID_SECTIONS:
                sec_dir = root / sec
                if sec_dir.is_dir():
                    count += sum(1 for d in sec_dir.iterdir() if d.is_dir())
            shutil.rmtree(root, ignore_errors=True)
        return {"purged": "all", "entries": count}
    if section not in VALID_SECTIONS:
        raise HTTPException(status_code=400, detail="Sección requerida para purge individual")
    entry_dir = _trash_entry_dir(mundo_dir, section, entry_id)
    shutil.rmtree(entry_dir, ignore_errors=True)
    return {"purged": entry_id}


@app.post("/api/{mundo}/move")
def move_path(mundo: str, body: dict):
    """Move or rename a file or folder to a new mundo-relative path.

    Validates ``from`` and ``to`` independently (S16), requires ``from``
    to exist (S17) and ``to`` to be free (S18), rejects moving a folder
    into itself (S19), creates parent dirs and moves recursively (S20).
    """
    from_path = body.get("from")
    to_path = body.get("to")
    if (
        not isinstance(from_path, str)
        or not isinstance(to_path, str)
        or not from_path.strip()
        or not to_path.strip()
    ):
        raise HTTPException(status_code=400, detail="Se requieren los campos 'from' y 'to'")

    if _resolve_mundo_dir(mundo) is None:
        raise HTTPException(status_code=404, detail="Mundo no encontrado")

    full_from = _resolve_mundo_path(mundo, from_path)
    if full_from is None:
        raise HTTPException(status_code=400, detail="Ruta de origen inválida")
    if not full_from.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    full_to = _resolve_mundo_path(mundo, to_path)
    if full_to is None:
        raise HTTPException(status_code=400, detail="Ruta de destino inválida")
    if full_to.exists():
        raise HTTPException(status_code=409, detail="Ya existe un archivo o carpeta en esa ubicación")
    if str(full_to).startswith(str(full_from) + os.sep):
        raise HTTPException(status_code=400, detail="No se puede mover una carpeta dentro de sí misma")

    try:
        full_to.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(full_from), str(full_to))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al mover: {e}")

    _graph_indices.pop(mundo, None)
    return {"success": True, "path": to_path}


@app.post("/api/{mundo}/duplicate")
def duplicate_path(mundo: str, body: dict):
    """Duplicate a file with an auto-resolved non-colliding name.

    Files only (S21); the copy name is ``{stem}-copia{ext}`` and then
    ``{stem}-2{ext}``, ``{stem}-3{ext}``… until free (S22); content is
    byte-identical via ``shutil.copy2`` (S23).
    """
    from_path = body.get("from")
    if not isinstance(from_path, str) or not from_path.strip():
        raise HTTPException(status_code=400, detail="Se requiere el campo 'from'")

    if _resolve_mundo_dir(mundo) is None:
        raise HTTPException(status_code=404, detail="Mundo no encontrado")

    full = _resolve_mundo_path(mundo, from_path)
    if full is None:
        raise HTTPException(status_code=400, detail="Ruta inválida")
    if not full.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    if full.is_dir():
        raise HTTPException(status_code=422, detail="Solo se pueden duplicar archivos")

    try:
        new_full = _next_duplicate_name(full)
        shutil.copy2(str(full), str(new_full))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al duplicar: {e}")

    _graph_indices.pop(mundo, None)
    return {"success": True, "path": _rel_path(new_full, mundo)}


# ---------------------------------------------------------------------------
# Ficha status (OKF frontmatter) endpoint
# ---------------------------------------------------------------------------

# OKF `status:` values found in fichas (grep `^status:` over mundos/): fichas
# use `draft` or `stable`; `synced` exists ONLY in idea-bank files (Ideas/,
# referencias/visuales/, quoted `"synced"`) and is not a ficha status.
VALID_FICHA_STATUSES = {"draft", "stable"}

_RE_FRONTMATTER = re.compile(r"^---\r?\n([\s\S]*?)^---[ \t]*(?=\r?\n|$)", re.MULTILINE)
_RE_FM_STATUS_LINE = re.compile(r"^(?P<indent>[ \t]*)status:[ \t]*[^\r\n]*(?P<term>\r?\n|$)", re.MULTILINE)


def _file_status(full: Path) -> str | None:
    """OKF ``status:`` of a file's leading frontmatter block.

    Reads only the 8KB head (same bound as ``_resolve_cover``) and parses
    ONLY the first frontmatter block — legacy ``---`` blocks in the body
    never count (same criterion as ``_set_frontmatter_status``). Returns
    the value only when it is a known ficha status (draft|stable):
    anything else (absent, ``synced``, garbage) yields None so the tree
    never lies about a file's state.
    """
    text = _read_head(full)
    if text is None:
        return None
    m = _RE_FRONTMATTER.match(text)
    if m is None:
        return None
    line_match = _RE_FM_STATUS_LINE.search(m.group(1))
    if line_match is None:
        return None
    value = line_match.group(0).split(":", 1)[1].strip().strip('"').strip("'")
    return value if value in VALID_FICHA_STATUSES else None


def _set_frontmatter_status(content: str, status: str) -> str:
    """Rewrite ONLY the ``status:`` line of the leading frontmatter block.

    Byte-preserving for everything else: CRLF line endings, the rest of the
    frontmatter, and the body — including any legacy ``---`` blocks in it
    (e.g. ``personajes/Pert.md`` carries ``---\nstatus: draft\n---`` in the
    body, which must never be touched). Mirrors the setPortada pattern:
    edit the target line in place, insert it before the closing ``---`` when
    the field is absent, or prepend a whole block when the file has no
    frontmatter at all.
    """
    m = _RE_FRONTMATTER.match(content)
    if m is None:
        return f"---\nstatus: {status}\n---\n{content}"

    inner = m.group(1)
    line_match = _RE_FM_STATUS_LINE.search(inner)
    if line_match is None:
        # No status line → insert right before the closing delimiter,
        # using the block's own line endings (setPortada pattern).
        eol = "\r\n" if "\r\n" in inner else "\n"
        updated_inner = inner + f"status: {status}{eol}"
    else:
        new_line = f"{line_match.group('indent')}status: {status}{line_match.group('term')}"
        updated_inner = (
            inner[: line_match.start()]
            + new_line
            + inner[line_match.end():]
        )

    return content[: m.start(1)] + updated_inner + content[m.end(1):]


@app.post("/api/{mundo}/{section}/status")
def set_file_status(mundo: str, section: str, body: dict):
    """Set the OKF ``status:`` of a ficha's frontmatter block (draft|stable).

    Instantly rewrites ONLY the frontmatter — independent of any save flow,
    the body and legacy blocks are never touched, and CRLF fichas stay CRLF.
    """
    if section not in VALID_SECTIONS:
        raise HTTPException(status_code=400, detail="Sección inválida")
    mundo_dir = _resolve_mundo_dir(mundo)
    if mundo_dir is None:
        raise HTTPException(status_code=404, detail="Mundo no encontrado")
    path = body.get("path")
    if not isinstance(path, str) or not path.strip():
        raise HTTPException(status_code=400, detail="Se requiere el campo 'path'")
    status = body.get("status")
    if status not in VALID_FICHA_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Estado inválido: '{status}'. Válidos: draft, stable",
        )
    full = _resolve_mundo_path(mundo, f"{section}/{path}")
    if full is None:
        raise HTTPException(status_code=400, detail="Path traversal detectado")
    if not full.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    try:
        # newline="" keeps \r\n byte-exact on Windows (Path.read_text would
        # normalize them through universal newlines).
        with open(full, "r", encoding="utf-8", newline="") as fh:
            content = fh.read()
        updated = _set_frontmatter_status(content, status)
        with open(full, "w", encoding="utf-8", newline="") as fh:
            fh.write(updated)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al actualizar el estado: {e}")
    _graph_indices.pop(mundo, None)
    return {"success": True, "path": f"{section}/{path}", "status": status}


# ---------------------------------------------------------------------------
# Graph endpoints
# ---------------------------------------------------------------------------

# Lazy-initialized graph index per world (built on first request)
_graph_indices: dict[str, "EntityGraphIndex"] = {}


def _get_graph(mundo: str) -> "EntityGraphIndex | None":
    """Get or build the entity graph index for a world. Returns None if world missing."""
    if _resolve_mundo_dir(mundo) is None:
        return None

    if mundo not in _graph_indices:
        # Lazy import to avoid relative-import issues when running as __main__
        from wiki.graph_indexer import EntityGraphIndex  # type: ignore[import-untyped]

        idx = EntityGraphIndex(MUNDOS_DIR)
        count = idx.build(mundo)
        logger.info("Graph built for '%s': %d entities", mundo, count)
        _graph_indices[mundo] = idx

    return _graph_indices[mundo]


class _GuidedGraphReader:
    """Expose the canonical graph index through the diskless guided seam."""

    def __init__(self, index: "EntityGraphIndex") -> None:
        self._index = index

    def search(self, query: str) -> list[dict]:
        return [vars(hit) for hit in self._index.search(query)]

    def read(self, entity_path: str) -> dict | None:
        entity = self._index.get_entity(entity_path)
        return vars(entity) if entity is not None else None

    def links(self, entity_path: str, kind: str) -> list[dict]:
        return self._index.get_links(entity_path, kind)


def _resolve_entity_path(idx: "EntityGraphIndex", name: str) -> str | None:
    """Resolve an entity display name to its graph path. Returns None if not found."""
    hits = idx.search(name)
    for hit in hits:
        if hit.name.lower() == name.lower():
            return hit.path
    # Fallback: return first hit if name is a prefix match
    if hits:
        return hits[0].path
    return None


@app.get("/api/{mundo}/graph/search")
def graph_search(
    mundo: str,
    q: str = Query(default="", description="Search query"),
    type: str | None = Query(default=None, description="Filter by entity type"),
):
    """Fuzzy search entities in the knowledge graph."""
    idx = _get_graph(mundo)
    if idx is None:
        return []

    filters: dict = {}
    if type:
        filters["type"] = type

    hits = idx.search(q, filters) if q.strip() or filters else idx.search("*") or []
    return [
        {
            "name": h.name,
            "type": h.type,
            "path": h.path,
            "title": h.title,
            "description": h.description,
            "tags": h.tags,
            "link_count": h.link_count,
            "score": h.score,
        }
        for h in hits
    ]


@app.get("/api/{mundo}/graph/entity")
def graph_entity(
    mundo: str,
    name: str = Query(..., description="Entity display name"),
):
    """Get full entity detail by name."""
    idx = _get_graph(mundo)
    if idx is None:
        return {"error": "Mundo no encontrado"}

    path = _resolve_entity_path(idx, name)
    if path is None:
        return {"error": "Entidad no encontrada", "name": name}

    detail = idx.get_entity(path)
    if detail is None:
        return {"error": "Entidad no encontrada", "name": name}

    return {
        "name": detail.name,
        "type": detail.type,
        "path": detail.path,
        "content": detail.content,
        "forward_links": detail.forward_links,
        "backlinks": detail.backlinks,
        "relaciones": detail.relaciones,
    }


@app.get("/api/{mundo}/graph/links")
def graph_links(
    mundo: str,
    name: str | None = Query(default=None, description="Entity display name"),
    kind: str = Query(default="forward", description="Link kind: forward, backlinks, hubs, etc."),
):
    """Get entity connections from the knowledge graph."""
    idx = _get_graph(mundo)
    if idx is None:
        return []

    entity_path: str | None = None
    if name:
        entity_path = _resolve_entity_path(idx, name)

    # For kinds that require an entity but it wasn't found
    if kind in ("backlinks", "forward", "suggest") and entity_path is None and name:
        return []

    try:
        links = idx.get_links(entity_path, kind)
    except ValueError:
        return []

    return links


@app.get("/api/{mundo}/graph/status")
def graph_status(mundo: str):
    """Get graph indexing status and stats."""
    idx = _get_graph(mundo)
    if idx is None:
        return {"node_count": 0, "link_count": 0, "indexed": False}

    with idx._lock:
        entities = idx._cache.get("entities", {})
        node_count = len(entities)
        link_count = sum(
            len(e.get("forward_links", [])) + len(e.get("backlinks", []))
            for e in entities.values()
        )

    return {
        "node_count": node_count,
        "link_count": link_count,
        "indexed": node_count > 0,
    }


# ---------------------------------------------------------------------------
# Media endpoints — serve, upload, list, and delete wiki media (images)
# ---------------------------------------------------------------------------

# Allowed MIME types for upload validation
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}

# Allowed file extensions
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# Max upload size: 10 MB
MAX_UPLOAD_SIZE = 10 * 1024 * 1024


class ImageInfo(BaseModel):
    """Info about a single image file."""
    path: str
    name: str
    size_bytes: int
    extension: str
    thumbnail_path: str | None = None


class MediaList(BaseModel):
    """List of all images available in a world."""
    images: list[ImageInfo]
    total: int


class UploadResponse(BaseModel):
    """Response after uploading an image."""
    success: bool
    path: str
    size_bytes: int
    thumbnail_path: str | None = None


def _get_media_bases(mundo: str) -> list[Path]:
    """Return the two allowed media base directories for *mundo*."""
    mundo_base = MUNDOS_DIR / mundo
    return [
        mundo_base / "wiki" / "media",
        mundo_base / "referencias" / "visuales" / "imagenes",
    ]


def _resolve_media_path(mundo: str, path: str) -> Path | None:
    """Resolve a media file path with path-traversal protection.

    Accepts *path* in two formats:
      1. Relative to *mundo* root:   ``wiki/media/foto.jpg``
      2. Relative to a media base:   ``foto.jpg``

    Checks against both allowed base directories:

        mundos/{mundo}/wiki/media/
        mundos/{mundo}/referencias/visuales/imagenes/

    Returns the resolved *Path* if valid, or *None* if the path tries to
    escape the allowed directories.

    The resolver prefers existing files. If no file exists at any valid
    path it still returns the first structurally valid path so the caller
    can return a 404 instead of a 400.
    """
    mundo_base = _resolve_mundo_dir(mundo)
    if mundo_base is None:
        return None

    bases = _get_media_bases(mundo)

    # Collect all candidate paths (deduplicated)
    seen: set[str] = set()
    candidates: list[Path] = []
    for base in bases:
        for p in (mundo_base / path, base / path):
            resolved = p.resolve()
            key = str(resolved)
            if key not in seen:
                seen.add(key)
                candidates.append(resolved)

    # Pass 1 — return existing file first (prefer correct base)
    for full in candidates:
        for base in bases:
            base_str = str(base.resolve()) + os.sep
            if str(full).startswith(base_str) and full.is_file():
                return full

    # Pass 2 — if no existing file, return first structurally valid path
    #          (so the caller can raise 404 vs 400)
    for full in candidates:
        for base in bases:
            base_str = str(base.resolve()) + os.sep
            if str(full).startswith(base_str):
                return full

    return None


def _rel_path(full_path: Path, mundo: str) -> str:
    """Return a forward-slash path relative to mundos/{mundo}/."""
    mundo_base = MUNDOS_DIR / mundo
    return str(full_path.relative_to(mundo_base)).replace("\\", "/")


def _validate_image_file(filename: str, content_type: str) -> None:
    """Validate MIME type and extension. Raises 422 on failure."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Tipo de archivo no permitido: '{ext}'. "
                f"Permitidos: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            ),
        )
    # Only reject content_type when it is present and invalid
    if content_type and content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Tipo MIME no permitido: '{content_type}'",
        )


def _sanitize_filename(filename: str) -> str:
    """Strip path separators and truncate to 255 characters maximum."""
    name = Path(filename).name  # discards any directory components
    if not name:
        name = "uploaded_image"
    if len(name) > 255:
        stem = Path(name).stem[:250]
        ext = Path(name).suffix
        name = f"{stem}{ext}"
    return name


def compress_image(image_bytes: bytes, quality: int = 85) -> tuple[bytes, str]:
    """Compress image to JPEG. Never preserves the original format.

    Returns (compressed_bytes, extension) where extension is always '.jpg'.
    """
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue(), ".jpg"


def generate_thumbnail(image_bytes: bytes, width: int = 300) -> bytes:
    """Generate a JPEG thumbnail with the given max width (aspect ratio kept)."""
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    ratio = width / img.width
    height = int(img.height * ratio)
    img = img.resize((width, height), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75, optimize=True)
    return buf.getvalue()


@app.get("/api/{mundo}/media")
def get_media(mundo: str, path: str = Query(..., description="Ruta relativa del archivo")):
    """Serve an image file from wiki/media/ or referencias/visuales/imagenes/."""
    full_path = _resolve_media_path(mundo, path)
    if full_path is None:
        raise HTTPException(status_code=400, detail="Path traversal detectado")
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    media_type, _ = mimetypes.guess_type(str(full_path))
    if media_type is None:
        media_type = "application/octet-stream"

    return FileResponse(path=str(full_path), media_type=media_type)


@app.post("/api/{mundo}/media/upload", response_model=UploadResponse, status_code=201)
async def upload_media(
    mundo: str,
    file: UploadFile = File(...),
    overwrite: bool = Query(False, description="Sobrescribir si el archivo ya existe"),
):
    """Upload an image file. Compresses to JPEG and generates a thumbnail."""
    if _resolve_mundo_dir(mundo) is None:
        raise HTTPException(status_code=404, detail="Mundo no encontrado")

    # 1. Read file bytes
    image_bytes = await file.read()

    # 2. Size cap
    if len(image_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Archivo demasiado grande ({len(image_bytes)} bytes). "
                "Máximo: 10 MB"
            ),
        )

    # 3. MIME / extension validation
    _validate_image_file(file.filename or "unknown", file.content_type or "")

    # 4. Sanitise filename
    safe_name = _sanitize_filename(file.filename or "image")
    stem = Path(safe_name).stem

    # 5. Compress — NEVER save the original
    compressed_bytes, compressed_ext = compress_image(image_bytes)
    compressed_name = f"{stem}{compressed_ext}"  # e.g. photo.jpg
    thumb_name = f"{stem}_thumb{compressed_ext}"  # e.g. photo_thumb.jpg

    # 6. Build target paths
    save_dir = MUNDOS_DIR / mundo / "wiki" / "media"
    save_path = save_dir / compressed_name
    thumb_path = save_dir / thumb_name

    # 7. Conflict check
    if save_path.exists() and not overwrite:
        raise HTTPException(
            status_code=409,
            detail=(
                f"El archivo '{compressed_name}' ya existe. "
                "Usa ?overwrite=true para sobrescribir."
            ),
        )

    # 8. Write compressed image
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(compressed_bytes)

    # 9. Generate and write thumbnail
    thumb_bytes = generate_thumbnail(image_bytes)
    thumb_path.write_bytes(thumb_bytes)

    return UploadResponse(
        success=True,
        path=_rel_path(save_path, mundo),
        size_bytes=len(compressed_bytes),
        thumbnail_path=_rel_path(thumb_path, mundo),
    )


@app.get("/api/{mundo}/media/list", response_model=MediaList)
def list_media(mundo: str):
    """List ALL images from wiki/media/ and referencias/visuales/imagenes/."""
    if _resolve_mundo_dir(mundo) is None:
        return MediaList(images=[], total=0)
    bases = _get_media_bases(mundo)
    images: list[ImageInfo] = []

    for base in bases:
        if not base.is_dir():
            continue
        for entry in sorted(base.rglob("*")):
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            stat = entry.stat()
            images.append(ImageInfo(
                path=_rel_path(entry, mundo),
                name=entry.name,
                size_bytes=stat.st_size,
                extension=entry.suffix.lower(),
            ))

    return MediaList(images=images, total=len(images))


@app.delete("/api/{mundo}/media")
def delete_media(
    mundo: str,
    path: str = Query(..., description="Ruta relativa del archivo (desde raíz de mundo o relativa a wiki/media/)"),
):
    """Move an image to the trash (``.papelera/media/{entry_id12}/``).

    Images from BOTH media bases (``wiki/media/`` and
    ``referencias/visuales/imagenes/``) are trashed as a single ``media``
    section; the thumbnail (``{stem}_thumb{suffix}``) travels with the main
    image as a unit. Never permanently deletes — restore or TTL purge
    reclaims the entry.
    """
    mundo_base = _resolve_mundo_dir(mundo)
    if mundo_base is None:
        raise HTTPException(status_code=404, detail="Mundo no encontrado")
    bases = _get_media_bases(mundo)
    base_prefixes = [str(b.resolve()) + os.sep for b in bases]

    # Try mundo-relative first, then base-relative, for every media base
    candidates = [(mundo_base / path).resolve()]
    for base in bases:
        candidates.append((base / path).resolve())

    resolved = None
    for full in candidates:
        if any(str(full).startswith(prefix) for prefix in base_prefixes):
            resolved = full
            break

    if resolved is None:
        raise HTTPException(status_code=400, detail="Path traversal detectado")

    # File existence
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    response_path = _rel_path(resolved, mundo)
    # size computed BEFORE the move (after moving, the source path no longer exists)
    size = resolved.stat().st_size

    try:
        # 12-hex entry_id; collisions are astronomically unlikely but retry
        # up to 10 times so we never overwrite a live entry dir.
        entry_id = None
        for _ in range(10):
            candidate = uuid.uuid4().hex[:12]
            if not (_trash_section_dir(mundo_base, "media") / candidate).exists():
                entry_id = candidate
                break
        if entry_id is None:
            raise RuntimeError("no free entry_id after 10 attempts")
        entry_dir = _trash_section_dir(mundo_base, "media") / entry_id
        entry_dir.mkdir(parents=True, exist_ok=False)
        shutil.move(str(resolved), str(entry_dir / resolved.name))

        # Move the thumbnail as a unit if it exists
        thumb = resolved.parent / f"{resolved.stem}_thumb{resolved.suffix}"
        if thumb.is_file():
            shutil.move(str(thumb), str(entry_dir / thumb.name))

        _write_trash_meta(entry_dir, {
            "entry_id": entry_id,
            "original_path": response_path,
            "kind": "file",
            "deleted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "size": size,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al mover a la papelera: {e}")
    _graph_indices.pop(mundo, None)
    return {"success": True, "path": response_path}


# ---------------------------------------------------------------------------
# AI Assistant — delegates to Hermes Agent Gateway (persistent daemon)
# ---------------------------------------------------------------------------

def _load_project_env(name: str) -> str:
    """Read a value from the project .env (gitignored) — secrets never live in code."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.is_file():
        return ""
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _configured_language() -> str:
    """Normalized global UI language (``DEMIURGOS_LANGUAGE``), safe fallback."""
    return resolve_ui_language(env_file=PROJECT_ROOT / ".env", environ=os.environ)


_GATEWAY_URL = os.getenv("HERMES_GATEWAY_URL", "http://127.0.0.1:8642/v1/chat/completions")
_GATEWAY_KEY = os.getenv("HERMES_GATEWAY_KEY") or _load_project_env("HERMES_GATEWAY_KEY")
_GATEWAY_TIMEOUT = int(os.getenv("HERMES_GATEWAY_TIMEOUT", "300"))

# The adapter probes Hermes before the first activity request. Tests replace
# this seam with a fake adapter; unsupported or unreachable providers remain a
# neutral fallback and never receive a run submission.
ACTIVITY_ADAPTER = None
ACTIVITY_EVENT_TIMEOUT_SECONDS = 30.0
ACTIVITY_CLEANUP_TIMEOUT_SECONDS = 1.0
ACTIVITY_UNAVAILABLE_REASON = "file_evidence_contract_unverified"
ACTIVITY_PROVIDER_FAILURE_REASON = "provider_activity_unavailable"

_hermes_client: httpx.AsyncClient | None = None


def _get_hermes_client() -> httpx.AsyncClient:
    global _hermes_client
    if _hermes_client is None:
        _hermes_client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {_GATEWAY_KEY}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(_GATEWAY_TIMEOUT, connect=10.0),
        )
    return _hermes_client


def _hermes_api_base(url: str) -> str:
    suffix = "/v1/chat/completions"
    if url.rstrip("/").endswith(suffix):
        return url.rstrip("/")[: -len("/chat/completions")]
    return url.rstrip("/")


ACTIVITY_ADAPTER = HermesRunsActivityAdapter(
    _hermes_api_base(_GATEWAY_URL),
    api_key=_GATEWAY_KEY,
    client_provider=_get_hermes_client,
)
_GUIDED_PROVIDER = HermesGuidedProvider(ACTIVITY_ADAPTER)
# Mandatory semantic gate: Hermes-first interpretation over the runs adapter.
# Unavailable/invalid/exhausted Hermes results fail closed as ``blocked`` with
# localized safe copy and NO lexical/plain-chat fallback. Entry-handler
# reordering ahead of this seam is PR 2; wiring alone keeps the seam live.
_SEMANTIC_PROVIDER = SemanticIntentProvider(ACTIVITY_ADAPTER)

class ChatRequest(BaseModel):
    messages: list[dict]
    mundo: str = ""
    session_id: str = ""

class AskRequest(BaseModel):
    prompt: str
    session_id: str = ""
    section: str = ""
    file_path: str = ""
    guided_session_id: str = ""
    guided_revision: int | None = None

@app.post("/api/chat")
async def chat_endpoint(body: ChatRequest):
    """Hermes-first compatible chat surface.

    Every user message is interpreted by the mandatory semantic gate. A valid
    decision returns the semantic envelope plus the compatibility
    ``content=response`` key. Unavailable, invalid, unwired, or exhausted
    Hermes returns the same HTTP-200 blocked envelope used by ``/ai/ask``:
    localized safe copy, zero action or write, and never raw provider/HTTP/
    timeout/quota/credential/model/gateway text.
    """
    user_msg = body.messages[-1]["content"] if body.messages else ""
    mundo = body.mundo if _resolve_mundo_dir(body.mundo) is not None else ""
    result = await _semantic_gate(mundo, user_msg, session_id=body.session_id)
    payload = result.as_dict()
    if result.decision is not None:
        payload["content"] = result.decision.response
    return payload


@app.post("/api/{mundo}/ai/ask")
async def ai_ask_endpoint(mundo: str, body: AskRequest, request: Request):
    """Endpoint for the AI Assistant sidebar (Hermes-first).

    The mandatory semantic gate interprets every user message BEFORE any
    Demiurgos intent classifier or action. Demiurgos then applies policy to the
    validated decision: guarded guided-session continuation and typed
    confirmation, plus the auth/canon/digest/revision/approval guards. There is
    no lexical-first path and no plain-chat fallback: unavailable, invalid,
    unwired, or exhausted Hermes fails closed with the safe blocked envelope
    and zero action, session, proposal, or write.
    """
    # Pre-flight guards (NOT intent classifiers): guided-session continuation
    # requires an authenticated principal, a live world, and the current
    # revision before Hermes interprets. They keep guarded policy grounded and
    # never decide intent.
    if body.guided_session_id or body.guided_revision is not None:
        principal = _resolve_principal(request)
        if principal is None:
            return _guided_error_response(StructuredError(
                ErrorCode.UNAUTHORIZED, "Authentication required.", False,
            ))
        if _resolve_mundo_dir(mundo) is None:
            return _guided_error_response(StructuredError(
                ErrorCode.INVALID_INPUT, "The world is unavailable.", False,
            ))
        state = _GUIDED_SESSIONS.recover(body.guided_session_id, principal.id)
        if state is None or state.world != mundo:
            return _guided_error_response(StructuredError(
                ErrorCode.UNAUTHORIZED, "The guided session is unavailable.", False,
            ))
        if state.revision != body.guided_revision:
            return _guided_error_response(StructuredError(
                ErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
            ))
    # Mandatory Hermes semantic gate (decides with bounded authorized context).
    # The named-reference resolution is performed ONCE per request and reused by
    # the guarded continuation, so the graph is never queried twice.
    ficha = _active_ficha_context(mundo, body)
    context, reference_context, reference_name, graph_unavailable = _semantic_context(
        mundo, body.prompt, ficha=ficha,
    )
    result = await _semantic_gate(
        mundo, body.prompt,
        session_id=body.session_id,
        context=context,
    )
    if result.decision is None:
        logger.info(
            "ai_ask: no validated Hermes decision (unavailable=%s attempts=%s); fail closed",
            result.unavailable, result.attempts,
        )
        return result.as_dict()
    # Demiurgos policy against the validated decision:
    # 1. Active guarded guided session -> continuation policy (typed
    #    confirmation, next turn) applied only after Hermes interpretation.
    if body.guided_session_id or body.guided_revision is not None:
        guided = await _internal_guided_turn(mundo, body, request)
        if guided is not None:
            return guided
    # 2. Self-contained decisions answer directly with Hermes' voice.
    if result.decision.state in SELF_CONTAINED_SEMANTIC_STATES:
        logger.info(
            "ai_ask: semantic state=%s attempts=%s",
            result.decision.state, result.attempts,
        )
        return result.as_dict()
    # 3. require_confirmation/proposal_ready route through the guarded
    #    single-run machinery (the same run supplied the continuation).
    return await _semantic_guided_continuation(
        mundo, body, request, result,
        reference_context=reference_context,
        reference_name=reference_name,
        graph_unavailable=graph_unavailable,
    )


def _semantic_context(
    mundo: str, prompt: str, ficha: str | None = None,
) -> tuple[SemanticContext, str, str | None, bool]:
    """Bounded authorized context plus the server-side named-reference result.

    Returns ``(context, reference_context, reference_name, graph_unavailable)``.
    Only server-owned read-only evidence is admitted: the active mundo, the
    authorized open-ficha content, the resolved named reference, and the
    graph-derived reference context. Credentials, filesystem/write authority,
    provider authority, and raw secrets never reach the decision input. The
    resolution tuple lets the guarded continuation reuse the SAME graph read
    instead of re-querying it.
    """
    reference_context, graph_unavailable, reference_name = _named_reference_context(mundo, prompt)
    has_reference = reference_name is not None and not graph_unavailable
    context = SemanticContext(
        mundo=mundo or None,
        ficha=(ficha or "") or None,
        reference=reference_name if has_reference else None,
        graph=reference_context if has_reference else None,
    )
    return context, reference_context, reference_name, graph_unavailable


async def _semantic_gate(
    mundo: str, prompt: str, *, session_id: str = "",
    ficha: str | None = None, context: SemanticContext | None = None,
    request_id: str | None = None,
) -> SemanticResult:
    """Mandatory Hermes-first semantic gate shared by every assistant surface.

    Runs BEFORE any Demiurgos intent classifier or action. An unwired provider
    fails closed as ``unavailable``; unavailable/invalid/malformed/exhausted
    Hermes yields a blocked ``SemanticResult`` with zero action, session,
    proposal, or write. ``decide`` is the only semantic interpretation
    boundary and always receives the bounded authorized context.
    """
    provider = _SEMANTIC_PROVIDER
    if provider is None:
        return SemanticResult(
            decision=None,
            attempts=0,
            request_id=request_id or f"semantic-{uuid.uuid4().hex}",
            session_id=session_id or None,
            unavailable=True,
        )
    if context is None:
        context, _, _, _ = _semantic_context(mundo, prompt, ficha=ficha)
    return await provider.decide(
        prompt,
        request_id=request_id or f"semantic-{uuid.uuid4().hex}",
        session_id=session_id or None,
        context=context,
    )


def _semantic_blocked_result(result: SemanticResult) -> dict:
    """Fail a semantic outcome closed to a write-free blocked envelope."""
    return SemanticResult(
        decision=None,
        attempts=result.attempts,
        request_id=result.request_id,
        session_id=result.session_id,
    ).as_dict()


async def _semantic_guided_continuation(
    mundo: str, body: AskRequest, request: Request, result: SemanticResult,
    *, reference_context: str = "", reference_name: str | None = None,
    graph_unavailable: bool = False,
) -> dict:
    """Back require_confirmation/proposal_ready with the guarded guided machinery.

    One Hermes run supplied the semantic decision AND the typed continuation
    (confirmation question or bounded candidate delta). No second Hermes run is
    started: the session is created through ``_GUIDED_SESSIONS`` and the
    proposal is serialized server-side with a server-owned slug, target, and
    digest. The named-reference resolution was already performed once by the
    semantic gate and is reused here. Every failure path returns a fail-closed
    blocked envelope.
    """
    decision = result.decision
    if decision is None or decision.continuation is None:
        logger.info(
            "ai_ask: semantic state=%s has no backed continuation; fail closed to blocked",
            decision.state if decision is not None else "unknown",
        )
        return _semantic_blocked_result(result)
    principal = _resolve_principal(request)
    if principal is None:
        logger.info("ai_ask: semantic guided continuation requires auth; fail closed to blocked")
        return _semantic_blocked_result(result)
    if _resolve_mundo_dir(mundo) is None:
        logger.info("ai_ask: semantic guided continuation world unavailable; fail closed to blocked")
        return _semantic_blocked_result(result)
    if graph_unavailable:
        logger.info("ai_ask: semantic guided continuation graph unavailable; fail closed to blocked")
        return _semantic_blocked_result(result)
    session_id = f"guided-{uuid.uuid4().hex}"
    relation_goal = extract_related_goal(body.prompt, reference_name=reference_name).summary
    try:
        _GUIDED_SESSIONS.create(
            session_id, mundo, principal.id,
            reference_context=reference_context, reference_name=reference_name,
            relation_goal=relation_goal,
            methodology_snapshot=_active_methodology_snapshot(mundo),
        )
        if decision.state == "require_confirmation":
            return _semantic_confirmation_continuation(
                body, result, decision, principal, session_id,
            )
        return await _semantic_proposal_continuation(
            mundo, body, result, decision, principal, session_id,
            reference_context, reference_name,
        )
    except Exception:
        logger.warning("ai_ask: semantic guided continuation failed safely", exc_info=True)
        return _semantic_blocked_result(result)


def _semantic_confirmation_continuation(
    body: AskRequest, result: SemanticResult, decision, principal, session_id: str,
) -> dict:
    """Begin the guarded confirmation transition with the run's own question."""
    question = decision.continuation.question or _guided_confirmation_text("start")
    confirmed = _GUIDED_SESSIONS.begin_confirmation(
        session_id, principal.id, body.prompt, question,
    )
    if confirmed is None:
        logger.info("ai_ask: semantic confirmation transition rejected; fail closed to blocked")
        return _semantic_blocked_result(result)
    return {
        "state": "require_confirmation",
        "action": action_for_state("require_confirmation"),
        "response": question,
        "request_id": result.request_id,
        "attempts": result.attempts,
        "fallback": False,
        "guided": True,
        "session_id": session_id,
        "guided_session_id": session_id,
        "guided_revision": confirmed.revision,
        "guided_state": _guided_public_state(confirmed),
    }


async def _semantic_proposal_continuation(
    mundo: str, body: AskRequest, result: SemanticResult, decision,
    principal, session_id: str, reference_context: str, reference_name: str | None,
) -> dict:
    """Commit the run's candidate delta and expose a server-owned diskless proposal.

    The same server-authoritative completeness gate that guards the provider
    path applies here: a ``proposal_ready`` delta is never a trusted
    completeness claim. Until the candidate carries the minimum required
    identity data, the run's delta is converted into exactly one focused
    question and the guided session keeps asking one question per turn.
    """
    from guided_character_domain import candidate_minimum_complete, next_required_question
    delta = dict(decision.continuation.delta)
    commit_request = GuidedRequest(
        PROTOCOL_VERSION, f"guided-{uuid.uuid4().hex}", session_id, mundo,
        0, principal.id, body.prompt,
        reference_context=reference_context, reference_name=reference_name,
        relation_goal=extract_related_goal(body.prompt, reference_name=reference_name).summary,
        guided_mode="full", question_depth="standard",
    )
    current = _GUIDED_SESSIONS.recover(session_id, principal.id)
    if current is not None and not candidate_minimum_complete(current.candidate, delta=delta):
        question = next_required_question(current.candidate, delta=delta)
        question_response = GuidedResponse(
            PROTOCOL_VERSION, commit_request.request_id, commit_request.session_id,
            commit_request.base_revision, Outcome.QUESTION,
            provenance=(f"semantic:run:{result.request_id}",), question=question,
        )
        state = _GUIDED_SESSIONS.commit(commit_request, question_response)
        if state is None:
            logger.info("ai_ask: semantic question commit rejected; fail closed to blocked")
            return _semantic_blocked_result(result)
        return {
            "response": question,
            "request_id": result.request_id,
            "attempts": result.attempts,
            "fallback": False,
            "guided": True,
            "session_id": session_id,
            "guided_session_id": session_id,
            "guided_revision": state.revision,
            "guided_state": _guided_public_state(state),
        }
    commit_response = GuidedResponse(
        PROTOCOL_VERSION, commit_request.request_id, commit_request.session_id,
        commit_request.base_revision, Outcome.DELTA,
        provenance=(f"semantic:run:{result.request_id}",),
        delta=dict(decision.continuation.delta),
    )
    state = _GUIDED_SESSIONS.commit(commit_request, commit_response)
    if state is None:
        logger.info("ai_ask: semantic proposal commit rejected; fail closed to blocked")
        return _semantic_blocked_result(result)
    slug = _guided_character_slug(state) or f"guided-{session_id.removeprefix('guided-')[-12:]}"
    title = _guided_character_title(state) or "Guided Character"
    world_dir = _resolve_mundo_dir(mundo)
    existing_targets: set[str] = set()
    if world_dir is not None and (world_dir / "personajes").is_dir():
        existing_targets = {f"personajes/{path.name}" for path in (world_dir / "personajes").glob("*.md")}
    try:
        proposal = serialize_ficha(
            state.candidate, world=mundo, slug=slug, title=title,
            existing_targets=existing_targets,
        )
    except FichaValidationError:
        logger.info("ai_ask: semantic proposal serialization rejected; fail closed to blocked")
        return _semantic_blocked_result(result)
    digest = hashlib.sha256(proposal.content.encode("utf-8")).hexdigest()
    edit_id = f"guided-proposal-{uuid.uuid4().hex}"
    _GUIDED_PENDING_PROPOSALS[edit_id] = {
        "edit_id": edit_id, "principal_id": principal.id, "session_id": session_id,
        "guided_revision": state.revision, "target": proposal.target,
        "content": proposal.content, "digest": digest,
    }
    return {
        "state": "proposal_ready",
        "action": action_for_state("proposal_ready"),
        "response": decision.response,
        "request_id": result.request_id,
        "attempts": result.attempts,
        "fallback": False,
        "guided": True,
        "session_id": session_id,
        "proposal_id": edit_id,
        "target": proposal.target,
        "base_revision": str(state.revision),
        "proposed_content": proposal.content,
        "proposed_digest": digest,
        "rationale": "Review the guided character before creating the file.",
        "is_new_file": True,
        "guided_session_id": session_id,
        "guided_revision": state.revision,
        "guided_state": _guided_public_state(state),
    }


def _candidate_proposal_value(state, key: str):
    """Read one proposed candidate field (proposed partition, never canon)."""
    item = state.candidate.proposals.get(key)
    if isinstance(item, dict) and "value" in item:
        return item["value"]
    return item


def _guided_character_slug(state) -> str | None:
    """Derive the server-owned target slug from the candidate, never provider authority."""
    for key in ("name", "nombre", "title"):
        value = _candidate_proposal_value(state, key)
        if isinstance(value, str) and value.strip():
            slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
            if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
                return slug
    return None


def _guided_character_title(state) -> str | None:
    value = _candidate_proposal_value(state, "name") or _candidate_proposal_value(state, "nombre")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


async def _internal_guided_turn(mundo: str, body: AskRequest, request: Request):
    """Demiurgos guided-session continuation policy, applied only AFTER a
    validated Hermes interpretation of the same message.

    This never starts a session from lexical intent and never runs a factual
    shortcut: Hermes already interpreted the message, and the guarded state
    machine below only advances an existing, authenticated session (typed
    confirmation or the next guided turn).
    """
    principal = _resolve_principal(request)
    if principal is None or not (body.guided_session_id and body.guided_revision is not None):
        return _guided_error_response(StructuredError(
            ErrorCode.UNAUTHORIZED, "The guided session is unavailable.", False,
        ))
    state = _GUIDED_SESSIONS.recover(body.guided_session_id, principal.id)
    if state is None or state.world != mundo:
        return _guided_error_response(StructuredError(
            ErrorCode.UNAUTHORIZED, "The guided session is unavailable.", False,
        ))
    if state.revision != body.guided_revision:
        return _guided_error_response(StructuredError(
            ErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
        ))
    result = await _guided_continue(
        mundo, body.guided_session_id, body.guided_revision, body.prompt,
        principal,
        reference_context=state.reference_context or "",
        reference_name=state.reference_name,
    )
    if isinstance(result, dict) and "session_id" in result:
        result["response"] = _guided_response_text(result)
        result["guided_session_id"] = result["session_id"]
        result["guided_revision"] = result["revision"]
        result["guided_state"] = result.copy()
    return result


def _guided_response_text(payload: dict) -> str:
    messages = payload.get("messages", [])
    for message in reversed(messages):
        if message.get("role") == "assistant" and message.get("content"):
            return str(message["content"])
    return str(payload.get("pending_question") or "")


def _active_ficha_context(mundo: str, body: AskRequest) -> str:
    if not body.file_path:
        return ""
    resolved = _resolve_path(mundo, body.section, body.file_path)
    if resolved is None or not resolved.is_file():
        return ""
    try:
        return resolved.read_text(encoding="utf-8")[:4_000]
    except Exception:
        return ""


def _named_reference_context(mundo: str, prompt: str) -> tuple[str, bool, str | None]:
    """Resolve an explicit related-entity name without selecting arbitrary hits."""
    name = named_reference_name(prompt)
    if name is None:
        return "", False, None
    try:
        index = _get_graph(mundo)
        if index is None:
            return "", True, None
        reader = index if all(callable(getattr(index, method, None)) for method in ("search", "read", "links")) else _GuidedGraphReader(index)
        reference = resolve_named_reference(reader, prompt)
    except Exception:
        logger.warning("guided named-reference resolution failed", exc_info=True)
        return "", True, None
    if reference is None:
        return "", False, None
    if reference.unresolved:
        detail = "has multiple graph matches" if reference.ambiguous else "was not found in the graph"
        return (
            f'The named reference "{reference.name}" {detail}. '
            "Do not infer facts; ask the author to clarify the reference.",
            False, None,
        )
    return reference.context[:4_000], False, reference.name


def _build_ai_ask_prompt(
    mundo: str, body: AskRequest, ficha_context: str | None = None,
    reference_name: str | None = None,
) -> str:
    parts = [
        "[Visible response guidance: Answer directly in 1-3 short paragraphs or bullets. "
        "Ask at most one question at a time. Use the verified context silently, answer only "
        "the relevant point, and do not repeat the full ficha or internal context. Expand only "
        "when requested. Keep factual answers grounded in the provided evidence.]",
    ]
    if mundo:
        parts.insert(0, f"[Mundo: {mundo}]")
    if body.file_path:
        title = None
        resolved = _resolve_path(mundo, body.section, body.file_path)
        if resolved is not None:
            try:
                content = resolved.read_text(encoding="utf-8")
            except Exception:
                content = None
            if content is not None:
                fm = re.match(r"\A---\r?\n(.*?)\r?\n---", content, re.DOTALL)
                if fm:
                    m = re.search(r"(?m)^title:\s*(.+?)\s*$", fm.group(1))
                    if m:
                        title = m.group(1).strip().strip('"').strip("'")
                if not title:
                    title = Path(body.file_path).stem.replace("_", " ")
        if title:
            parts.append(f"[Ficha actual: [[{title}]] — ruta: {body.section}/{body.file_path}]")
        else:
            parts.append(f"[Ficha actual: {body.section}/{body.file_path}]")
        if ficha_context:
            parts.append(f"[Contenido verificado de la ficha actual:\n{ficha_context}\n]")
    elif ficha_context and reference_name:
        parts.append(
            f"[Contexto verificado de la referencia [[{reference_name}]]:\n"
            f"{ficha_context}\n"
            "Responde solo con estos hechos verificados. Si la respuesta no está en la evidencia, "
            "indica que se desconoce y no inventes detalles.\n]"
        )
    if parts:
        joined = "\n".join(parts)
        return f"{joined}\n\n{body.prompt}"
    return body.prompt


def _guided_confirmation_text(kind: str) -> str:
    texts = {
        "start": {
            "en": "I can prepare a guided proposal for this related character. Start the questions? (yes/no)",
            "es": "Puedo preparar una propuesta guiada para este personaje relacionado. ¿Comenzamos las preguntas? (sí/no)",
        },
        "ambiguous": {
            "en": "Please answer yes to start the guided character proposal, or no to cancel.",
            "es": "Por favor, responde sí para comenzar la propuesta guiada del personaje o no para cancelarla.",
        },
        "decline": {
            "en": "No character proposal was started.",
            "es": "No se inició ninguna propuesta de personaje.",
        },
    }
    return texts[kind][_configured_language()]


def _activity_unavailable(reason_code: str = ACTIVITY_UNAVAILABLE_REASON) -> JSONResponse:
    if reason_code not in {
        ACTIVITY_UNAVAILABLE_REASON,
        ACTIVITY_PROVIDER_FAILURE_REASON,
    }:
        reason_code = ACTIVITY_PROVIDER_FAILURE_REASON
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Assistant activity is unavailable",
            "code": "activity_unavailable",
            "reason_code": reason_code,
        },
    )


def _sse_event(payload: dict[str, str]) -> str:
    event_name = payload["kind"]
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"


def _semantic_decision_event(result: SemanticResult) -> SemanticDecisionEvent:
    """Build the additive authoritative SSE event from a validated decision.

    The continuation (when present) is serialized from the validated typed
    continuation only — never from raw provider output — so it stays bounded
    and free of authority claims. ``None`` is emitted when no continuation
    exists or the outcome is fail-closed.
    """
    continuation: dict[str, Any] | None = None
    if result.decision is not None and result.decision.continuation is not None:
        continuation = {"outcome": result.decision.continuation.outcome}
        if result.decision.continuation.question is not None:
            continuation["question"] = result.decision.continuation.question
        if result.decision.continuation.delta is not None:
            continuation["delta"] = dict(result.decision.continuation.delta)
    return SemanticDecisionEvent(
        request_id=result.request_id,
        state=result.state,
        action=result.action,
        unavailable=result.unavailable,
        continuation=continuation,
    )


async def _fail_closed_activity_stream(result: SemanticResult):
    """Emit the ordered fail-closed activity stream over HTTP 200.

    ``semantic_decision`` (authoritative) precedes the compatible safe-copy
    ``answer`` and final ``terminal`` events. No classifier, action, session,
    proposal, or write ever occurs on this path.
    """
    yield _sse_event(_semantic_decision_event(result).as_dict())
    yield _sse_event(AnswerEvent(result.request_id, result.response).as_dict())
    yield _sse_event(TerminalEvent(result.request_id, "failed").as_dict())


def _fail_closed_activity_response(result: SemanticResult, request_id: str) -> StreamingResponse:
    return StreamingResponse(
        _fail_closed_activity_stream(result),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Assistant-Activity-Request-Id": request_id,
        },
    )


async def _cancel_activity(adapter: object, run_id: str) -> None:
    cancel = getattr(adapter, "cancel", None)
    if not callable(cancel):
        return
    try:
        result = cancel(run_id)
        if inspect.isawaitable(result):
            await asyncio.wait_for(result, timeout=ACTIVITY_CLEANUP_TIMEOUT_SECONDS)
    except Exception:
        # Cleanup failures are intentionally not exposed to the client.
        logger.warning("assistant activity cleanup failed (%s)", type(adapter).__name__)


@app.post("/api/{mundo}/ai/ask/activity")
async def ai_ask_activity_endpoint(mundo: str, body: AskRequest, request: Request):
    """Semantic-first SSE activity boundary.

    The mandatory semantic gate interprets the user message FIRST (Hermes-first
    authority). A validated decision is emitted as the authoritative
    ``semantic_decision`` event BEFORE any compatible ``activity``/``answer``/
    ``terminal`` event; ``terminal`` remains final and legacy clients may ignore
    the additive event. Unavailable/invalid/unwired/exhausted Hermes fails
    closed over HTTP 200 with the ordered blocked stream and zero classifier,
    action, session, proposal, or write. Guided semantic decisions hand off to
    the guided path (503) without any lexical classifier.
    """
    # Pre-flight non-classifier guards: active guided sessions stream through
    # the normal assistant path so activity never double-runs Hermes.
    if body.guided_session_id or body.guided_revision is not None:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Assistant activity is unavailable",
                "code": "guided_handoff",
                "reason_code": "guided_handoff",
            },
        )
    world_root = _resolve_mundo_dir(mundo)
    if world_root is None:
        return _activity_unavailable()

    # Mandatory Hermes semantic interpretation FIRST with bounded authorized
    # context. No classifier, action, session, proposal, or write precedes the
    # validated decision.
    request_id = f"activity-{uuid.uuid4().hex}"
    context, _, _, _ = _semantic_context(mundo, body.prompt)
    result = await _semantic_gate(
        mundo, body.prompt,
        session_id=body.session_id,
        context=context,
        request_id=request_id,
    )
    decision = result.decision
    if decision is not None and decision.state in CONTINUATION_STATES:
        # Hermes decided guided work: hand off to the guided path. The handoff
        # follows the validated semantic state, never a lexical classifier.
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Assistant activity is unavailable",
                "code": "guided_handoff",
                "reason_code": "guided_handoff",
            },
        )
    if decision is None:
        # No validated decision -> fail closed to the ordered blocked stream.
        return _fail_closed_activity_response(result, request_id)

    # Admitted adapter + stream guards (not classifiers) after the decision.
    adapter = ACTIVITY_ADAPTER
    if adapter is None:
        return _fail_closed_activity_response(result, request_id)
    try:
        probe = getattr(adapter, "probe", None)
        if callable(probe):
            probe_result = probe()
            if inspect.isawaitable(probe_result):
                await probe_result
        if not bool(getattr(adapter, "available")):
            capability = getattr(adapter, "capability", None)
            reason = getattr(capability, "reason", ACTIVITY_UNAVAILABLE_REASON)
            return _fail_closed_activity_response(result, request_id)
        capability = getattr(adapter, "capability")
        events = getattr(adapter, "events")
        if not callable(events):
            return _fail_closed_activity_response(result, request_id)
    except Exception:
        return _fail_closed_activity_response(result, request_id)

    activity_request = HermesActivityRequest(
        request_id=request_id,
        prompt=_build_ai_ask_prompt(mundo, body),
        session_id=body.session_id,
    )
    try:
        run_id = adapter.start(activity_request)
        if inspect.isawaitable(run_id):
            run_id = await run_id
        translator = ActivityTranslator(
            capability=capability,
            request_id=request_id,
            run_id=run_id,
            session_id=activity_request.session_id,
            world_root=world_root,
        )
    except Exception:
        return _fail_closed_activity_response(result, request_id)

    async def stream():
        # The additive authoritative semantic event comes first; compatible
        # evidence (activity/answer/terminal) follows and terminal stays final.
        yield _sse_event(_semantic_decision_event(result).as_dict())
        completed = False
        disconnected = False
        try:
            source = events(run_id)
            if inspect.isawaitable(source):
                source = await source
            if hasattr(source, "__aiter__"):
                iterator = source.__aiter__()
                while True:
                    if await request.is_disconnected():
                        disconnected = True
                        break
                    try:
                        raw_event = await asyncio.wait_for(
                            iterator.__anext__(), timeout=ACTIVITY_EVENT_TIMEOUT_SECONDS
                        )
                    except StopAsyncIteration:
                        break
                    for event in translator.translate(raw_event):
                        if isinstance(event, TerminalEvent):
                            completed = True
                        yield _sse_event(event.as_dict())
            else:
                for raw_event in source:
                    if await request.is_disconnected():
                        disconnected = True
                        break
                    for event in translator.translate(raw_event):
                        if isinstance(event, TerminalEvent):
                            completed = True
                        yield _sse_event(event.as_dict())
            if not disconnected and not completed:
                status = getattr(adapter, "status", None)
                if callable(status):
                    status_payload = status(run_id)
                    if inspect.isawaitable(status_payload):
                        status_payload = await status_payload
                    if isinstance(status_payload, dict):
                        run_status = status_payload.get("status")
                        if run_status == "completed":
                            raw_status = {
                                "event": "run.completed",
                                "run_id": run_id,
                                "output": status_payload.get("output"),
                            }
                            for event in translator.translate(raw_status):
                                if isinstance(event, TerminalEvent):
                                    completed = True
                                yield _sse_event(event.as_dict())
                        elif run_status in {"failed", "cancelled"}:
                            raw_status = {"event": f"run.{run_status}", "run_id": run_id}
                            for event in translator.translate(raw_status):
                                if isinstance(event, TerminalEvent):
                                    completed = True
                                yield _sse_event(event.as_dict())
            if not disconnected and not completed:
                for event in translator.finalize():
                    yield _sse_event(event.as_dict())
        except asyncio.CancelledError:
            disconnected = True
            raise
        except Exception:
            if not disconnected:
                for event in translator.finalize():
                    yield _sse_event(event.as_dict())
        finally:
            if not completed:
                await _cancel_activity(adapter, run_id)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Assistant-Activity-Request-Id": request_id,
        },
    )

async def _run_hermes(prompt: str, session_id: str = "") -> str:
    """Send prompt to Hermes Gateway via HTTP (OpenAI-compatible chat completions).

    Failures return the localized safe unavailable copy — never raw provider,
    HTTP, timeout, quota, credential, model, or gateway text — so no caller can
    surface technical detail to a user. Logs keep the full diagnostic detail.
    """
    import time
    t0 = time.monotonic()
    logger.info("Hermes GW START len=%d session=%s preview=%r", len(prompt), session_id or "-", prompt[:120].replace("\n", " "))
    try:
        client = _get_hermes_client()
        payload = {
            # Hermes resolves the active profile's model.default on the next
            # request. Do not pass a browser-controlled model override here.
            "model": "hermes-agent",
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {}
        if session_id:
            # Opt-in session continuity: gateway keeps the conversation state.
            headers["X-Hermes-Session-Id"] = session_id
        resp = await client.post(_GATEWAY_URL, json=payload, headers=headers)
        elapsed = time.monotonic() - t0
        if resp.status_code != 200:
            logger.error("Hermes GW HTTP %d %.1fs: %s", resp.status_code, elapsed, resp.text[:500])
            return unavailable_copy()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "") if "choices" in data else str(data)
        logger.info("Hermes GW DONE %.1fs len=%d preview=%r", elapsed, len(content), content[:200].replace("\n", " "))
        return content or unavailable_copy()
    except httpx.ConnectError:
        logger.error("Hermes GW UNREACHABLE — is gateway running on %s?", _GATEWAY_URL)
        return unavailable_copy()
    except httpx.TimeoutException:
        logger.error("Hermes GW TIMEOUT after %.1fs", time.monotonic() - t0)
        return unavailable_copy()
    except Exception as exc:
        logger.exception("Hermes GW CRASH: %s", exc)
        return unavailable_copy()


# ---------------------------------------------------------------------------
# AI edit proposals — diskless Hermes suggestions with bounded retry (PR 2)
#
# POST /api/{mundo}/ai/edit-suggest turns a user request into a validated
# proposal for an existing or new Markdown target. Hermes is reached ONLY
# through the chat-completions gateway (_run_hermes), which has no disk-write
# surface, and the endpoint itself performs zero persistence: it reads the
# authorized target, calls the gateway, validates the structured reply, and
# returns the proposal for the later confirmation-gated write (slice 1B).
# Structured output is validated strictly before exposure; unparseable,
# schema-invalid, or transient replies retry up to a hard cap of exactly 3
# total attempts (initial + 2 retries). On exhaustion the caller receives a
# safe, actionable fallback and diagnostics record only the attempt count,
# validation category, and opaque principal — never content, raw tokens, or
# secrets.
# ---------------------------------------------------------------------------

_AI_PROPOSAL_MAX_ATTEMPTS = 3
_MAX_PROPOSAL_CONTENT = 2 * 1024 * 1024  # 2 MiB sane upper bound for proposals


def _extract_proposal_json(raw: str) -> dict | None:
    """Parse a Hermes reply into a dict, tolerating one JSON code fence.

    Returns None when the reply is not JSON or not a JSON object, so callers
    treat it as a malformed (retryable) response. A fenced block is the most
    common Hermes deviation: strip the leading/trailing ``` lines first.
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _validate_proposal_payload(data: dict, requested_target: str,
                               base_revision: str, is_new_file: bool):
    """Strictly validate a parsed Hermes proposal payload.

    Returns ``(None, proposal)`` when contract-valid, else ``(category, None)``.
    Every schema/scope violation maps to the retryable ``malformed`` category:
    missing/wrong-typed fields, a target differing from the requested one
    (Hermes must never select targets), a base revision that does not match
    the current on-disk digest, or a new-file flag inconsistent with the
    resolved target. The server computes ``proposed_digest`` itself from the
    accepted content — a Hermes-supplied digest is never trusted.
    """
    proposal_id = data.get("proposal_id")
    target = data.get("target")
    content = data.get("content")
    rationale = data.get("rationale")
    new_flag = data.get("is_new_file")
    if not isinstance(proposal_id, str) or not proposal_id.strip() or len(proposal_id) > 128:
        return "malformed", None
    if not isinstance(target, str) or target.replace("\\", "/") != requested_target:
        return "malformed", None
    if not isinstance(content, str) or not content.strip() or len(content) > _MAX_PROPOSAL_CONTENT:
        return "malformed", None
    if not isinstance(rationale, str) or not rationale.strip():
        return "malformed", None
    if not isinstance(new_flag, bool) or new_flag != is_new_file:
        return "malformed", None
    hermes_base = data.get("base_revision")
    if is_new_file:
        if hermes_base not in (None, ""):
            return "malformed", None
    elif hermes_base != base_revision:
        return "malformed", None
    return None, {
        "proposal_id": proposal_id.strip(),
        "target": requested_target,
        "base_revision": base_revision,
        "content": content,
        "proposed_digest": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "rationale": rationale.strip(),
        "is_new_file": is_new_file,
    }


def _build_proposal_prompt(section: str, path: str, is_new_file: bool,
                           base_revision: str, current_content: str,
                           user_prompt: str) -> str:
    """Build the strict-JSON instruction sent to Hermes.

    Pins the target, base revision, and new-file status so the validator can
    cross-check every one of them; Hermes is told to echo them unchanged
    inside the single JSON object it must return.
    """
    target = f"{section}/{path}"
    if is_new_file:
        context = (
            f"Target is a NEW Markdown file that does not exist yet: {target}. "
            'The field "base_revision" MUST be "" (empty string).'
        )
        current = "There is no current content for this target."
    else:
        context = (
            f"Target is an EXISTING Markdown file: {target}. "
            f'Its current base revision is "{base_revision}".'
        )
        current = f"Current content follows.\n\n{current_content}"
    return (
        "You propose an edit to a Markdown file in the Demiurgos narrative "
        "wiki. Respond with ONLY one JSON object — no markdown fences, no "
        'prose. The object MUST contain exactly these fields: "proposal_id" '
        "(a short unique id string), \"target\" (the exact target path given "
        'below, unchanged), "base_revision" (the exact base revision given '
        'below, unchanged), "content" (the COMPLETE proposed Markdown '
        'content), "rationale" (a short reason for the edit), "is_new_file" '
        "(a boolean matching the target status below).\n"
        f"User request: {user_prompt}\n"
        f"{context}\n{current}"
    )


@app.post("/api/{mundo}/ai/edit-suggest")
async def ai_edit_suggest(mundo: str, body: dict, request: Request):
    """Produce a validated, diskless Hermes edit proposal for a Markdown target.

    Accepts ``{section, path, prompt, session_id}`` and reads ONLY the
    authorized target (existing content for context, or new-target status).
    Returns ``{proposal, attempts, outcome}`` where ``proposal`` carries
    proposal_id, target, base_revision, proposed Markdown, server-computed
    proposed_digest, rationale, and is_new_file. Exactly 3 total Hermes
    attempts max (initial + 2 retries), retrying only malformed/schema-invalid
    or transient replies; on exhaustion a safe fallback is returned and
    nothing is persisted.
    """
    body = body or {}
    section = body.get("section")
    path = body.get("path")
    prompt = body.get("prompt")
    session_id = body.get("session_id") or ""
    principal = _resolve_principal(request)
    if not isinstance(section, str) or section not in VALID_SECTIONS:
        raise HTTPException(status_code=400, detail="Sección inválida")
    if not isinstance(path, str) or not path.strip():
        raise HTTPException(status_code=400, detail="path requerido")
    if not isinstance(prompt, str) or not prompt.strip():
        raise HTTPException(status_code=400, detail="prompt requerido")
    if _resolve_mundo_dir(mundo) is None:
        raise HTTPException(status_code=404, detail="Mundo no encontrado")
    full = _resolve_mundo_path(mundo, f"{section}/{path}")
    if full is None:
        raise HTTPException(status_code=400, detail="Path traversal detectado")
    if full.exists() and not full.is_file():
        raise HTTPException(status_code=400, detail="Objetivo inválido")
    is_new_file = not full.exists()
    base_revision = ""
    current_content = ""
    if not is_new_file:
        try:
            base_revision = _digest_of(full)
            current_content = full.read_text(encoding="utf-8")
        except Exception:
            raise HTTPException(status_code=400, detail="Objetivo inválido")

    target = f"{section}/{path}".replace("\\", "/")
    proposal = None
    attempts = 0
    category = "malformed"
    for attempt in range(1, _AI_PROPOSAL_MAX_ATTEMPTS + 1):
        attempts = attempt
        try:
            raw = await _run_hermes(
                _build_proposal_prompt(section, path, is_new_file,
                                       base_revision, current_content, prompt),
                session_id=session_id)
        except Exception:
            category = "transient"
            continue
        data = _extract_proposal_json(raw)
        if data is None:
            category = "transient" if raw.startswith("Error:") else "malformed"
            continue
        category, proposal = _validate_proposal_payload(
            data, target, base_revision, is_new_file)
        if proposal is not None:
            break

    outcome = "proposal" if proposal is not None else "fallback"
    principal_id = principal.id if principal is not None else "-"
    logger.info(
        "ai/edit-suggest: mundo=%s target=%s attempts=%d category=%s outcome=%s principal=%s",
        mundo, target, attempts, category or "valid", outcome, principal_id)
    if proposal is None:
        return {
            "proposal": None,
            "attempts": attempts,
            "outcome": "fallback",
            "fallback_action": "manual-edit-or-chat",
            "message": ("No se pudo generar una propuesta válida. "
                        "Edita el archivo manualmente o consulta al asistente."),
        }
    return {"proposal": proposal, "attempts": attempts, "outcome": "proposal"}


# ---------------------------------------------------------------------------
# Idea capture configuration panel — Profile → Integraciones → Captura de ideas
#
# Temporary MVP: single-user, local-auth-protected config for the native
# Hermes/Telegram ingress (config/idea-capture.yaml) plus server-side storage
# of TELEGRAM_BOT_TOKEN in .env. The router resolves the principal through a
# call-time lambda so deployments and tests can swap _resolve_principal.
# ---------------------------------------------------------------------------

from idea_capture_ui import create_idea_capture_router  # noqa: E402
from assistant_settings import create_assistant_settings_router  # noqa: E402
from telegram_settings import create_telegram_settings_router  # noqa: E402
from migration_settings import create_migration_settings_router  # noqa: E402
from import_router import create_import_router  # noqa: E402
from import_store import ImportJobStore  # noqa: E402
from import_service import ImportService  # noqa: E402

# Lazy world-importer store: reads current PROJECT_ROOT so tests can relocate it.
_IMPORT_STORE: ImportJobStore | None = None


def _import_store() -> ImportJobStore:
    global _IMPORT_STORE
    if _IMPORT_STORE is None:
        _IMPORT_STORE = ImportJobStore(PROJECT_ROOT / "data" / "import-jobs.sqlite3")
    return _IMPORT_STORE


def _reconcile_import_graph(rel: str, mundo: str) -> None:
    """Reconcile the canonical graph for a written ficha before success (2.9)."""
    idx = _get_graph(mundo)
    if idx is not None:
        full = MUNDOS_DIR / mundo / rel
        idx.update(str(full), mundo)


def _reconcile_import_graph_many(
    paths: list[str], mundo: str
) -> "GraphReconcileResult":
    """Bulk-reconcile written fichas through the bounded batch boundary (slice 3).

    Returns the bulk reconciliation result so the service can emit completion /
    partial-failure observability events. Graph state is secondary to canon
    writes; callers treat bulk failure as non-fatal for the import job.
    """
    from wiki.graph_indexer import GraphReconcileResult  # type: ignore[import-untyped]

    idx = _get_graph(mundo)
    if idx is None:
        return GraphReconcileResult(processed=0, failed=list(paths), batches=0)
    full_paths = [str(MUNDOS_DIR / mundo / rel) for rel in paths]
    return idx.update_many(full_paths, mundo)


def _register_import_gallery(world: str, src: Path, rel: str) -> None:
    """Register a spooled image into the world gallery (existing media base).

    Copies the (already bounded) image into ``mundos/{world}/wiki/media/`` so
    the existing media contract (list/upload/serve via ``getMediaUrl``) sees it
    as a first-class asset; the ficha references it via relative Markdown.
    """
    save_dir = MUNDOS_DIR / world / "wiki" / "media"
    if not src.is_file():
        return
    name = Path(rel).name
    save_dir.mkdir(parents=True, exist_ok=True)
    dest = save_dir / name
    if not dest.exists():
        shutil.copy2(src, dest)

# Assistant settings routes accept transient credentials only on authenticated
# write requests and return metadata-only status payloads. Configuration saves
# report Active, Pending restart/reload, or Saved-not-active; this API server
# does not own Hermes or start, stop, reload, or restart any process.
app.include_router(
    create_idea_capture_router(
        require_principal=lambda request: _resolve_principal(request),
    ),
)

app.include_router(
    create_assistant_settings_router(
        require_principal=lambda request: _resolve_principal(request),
        # ONB-3.6: a successful three-proof save records its runtime acceptance
        # in the local registry so the readiness badge may become configured
        # only on real acceptance (pending/no-apto otherwise).
        on_acceptance=_record_assistant_acceptance,
    ),
)

app.include_router(
    create_telegram_settings_router(
        require_principal=lambda request: _resolve_principal(request),
        registry=lambda: _local_state(),
    ),
)

# ONB-4.3 (WU-4c1) — migration approval API. The engine (wiki.migration)
# never auto-renames: approval arrives explicitly in the payload, and the
# response carries the transaction + evidence (completed/rolled_back/error).
# The evidence dir lives under the project data dir, outside mundos/.
app.include_router(
    create_migration_settings_router(
        require_principal=lambda request: _resolve_principal(request),
        mundos_dir=lambda: MUNDOS_DIR,
        evidence_dir=lambda: PROJECT_ROOT / "data" / "migration-evidence",
    ),
)

# Slice 2 — synchronous Hermes bridge for the (optional) importer enricher.
#
# The importer module is gateway-independent; the composition layer in this
# file is the only place that talks to ``_run_hermes``. The bridge wraps the
# async gateway in ``asyncio.run`` with a 5-second total budget, raises on
# timeout, and returns the empty ``unavailable_copy`` when the gateway is
# unreachable so the importer's fail-open contract holds end-to-end.
def _sync_hermes_enricher(prompt: str, session_id: str) -> str:
    """Synchronous Hermes bridge honoring the 5-second total budget."""
    import asyncio
    from import_enrichment import DEFAULT_TIMEOUT_SECONDS
    try:
        return asyncio.run(
            asyncio.wait_for(_run_hermes(prompt, session_id),
                             timeout=DEFAULT_TIMEOUT_SECONDS))
    except (asyncio.TimeoutError, TimeoutError):
        logger.warning("hermes enricher timed out after %.1fs",
                       DEFAULT_TIMEOUT_SECONDS)
        return ""
    except RuntimeError:
        # ``asyncio.run`` raises when called from a running loop (e.g., inside
        # a Test that already drives the event loop). We degrade gracefully:
        # the importer treats an empty string as "no suggestions".
        return ""


def _make_import_enricher():
    """Compose the Hermes enricher callable for the import router.

    Slice 2 contract: enrichment is OPT-IN (the request must set
    ``enrich=true``). The enricher runs the gateway bridge, parses the
    response, validates the suggestion set, and attaches the validated
    payloads to each candidate. Failures (timeout, unavailable copy,
    malformed JSON, vocabulary rejection) leave the candidates unchanged
    with ``enrichment_status="no_suggestions"`` so the import succeeds
    deterministically.
    """
    from import_enrichment import enrich_candidates as _enrich

    def enricher(candidates):
        return _enrich(candidates, hermes_runner=_sync_hermes_enricher)

    return enricher


def _make_vision_callable():
    """Compose the vision seam callable for the import router (PR2/PR3).

    Reads the active Hermes profile's ``config.yaml``, wires the PR2
    ``import_vision.build_vision_callable`` with the existing 300px
    thumbnailer and the SAME singleton store that backs the job lifecycle
    (so the vision content cache is shared with the router). Returns ``None``
    (vision disabled) when the profile is missing/invalid, the assistant is
    text-only, or the settings gate fails closed.

    The returned ``vision(candidates, media_entries)`` adapter mirrors the
    integration-test seam: it runs the batch analysis over the preserved
    media bundle and turns each result into an advisory ``vision:<sha256>``
    suggestion on its owning candidate. Vision is advisory and fail-open —
    any analysis failure returns the candidates unchanged.
    """
    try:
        from assistant_settings import _resolve_profile_paths
        from import_vision import build_vision_callable

        config_path = _resolve_profile_paths().config
        store = _import_store()
        analyze_images = build_vision_callable(
            settings_path=config_path,
            generate_thumbnail=generate_thumbnail,
            vision_cache_lookup=store.vision_cache_lookup,
            vision_cache_store=store.vision_cache_store,
        )
    except Exception:  # noqa: BLE001 — vision is advisory, fail-closed at setup
        return None
    if analyze_images is None:
        return None

    def vision(candidates, media_entries):
        if not candidates or not media_entries:
            return candidates
        try:
            results = analyze_images([m.image for m in media_entries], "")
        except Exception:  # noqa: BLE001 — vision is advisory, fail-open
            return candidates
        by_hash = {r.image_hash: r for r in results}
        by_candidate: dict[str, list[dict]] = {}
        for m in media_entries:
            result = by_hash.get(
                hashlib.sha256(m.image.image_bytes).hexdigest())
            if result is None:
                continue
            by_candidate.setdefault(m.candidate_id, []).append({
                "__type__": "vision",
                "id": f"vision:{result.image_hash}",
                "candidate_id": m.candidate_id,
                "relative_media_path": m.spool_relative_path,
                "description": result.description,
                "verdict": result.verdict,
                "analysis": result.analysis,
                "tags": list(result.tags),
                "confidence": 0.0,
                "provenance": {"provider": "vision", "capability": "multimodal"},
                "evidence": f"image:{m.spool_relative_path}",
                "review_state": "pending",
            })
        out: list = []
        for candidate in candidates:
            entries = by_candidate.get(candidate.candidate_id)
            if not entries:
                out.append(candidate)
                continue
            payload = (list(candidate.enrichment_json)
                       if candidate.enrichment_json else [])
            payload.extend(entries)
            out.append(candidate.model_copy(update={
                "enrichment_json": payload,
                "enrichment_status": "ok",
            }))
        return out

    return vision


# World importer (Phase 1 intake + Phase 2 service). Principal and world are
# resolved server-side; intake never writes canon, and only digest/token-bound
# approval may invoke gated merge + gallery registration + graph reconcile.
app.include_router(
    create_import_router(
        require_principal=lambda request: _resolve_principal(request),
        mundos_dir=lambda: MUNDOS_DIR,
        spool_dir=lambda: PROJECT_ROOT / "data" / "import-spool",
        store=_import_store,
        enricher=_make_import_enricher(),
        vision=_make_vision_callable(),
        service=ImportService(
            store=_import_store(),
            mundos_dir=MUNDOS_DIR,
            spool_dir=PROJECT_ROOT / "data" / "import-spool",
            read_file=lambda rel: (
                (PROJECT_ROOT / "data" / "import-spool" / rel).read_text(
                    encoding="utf-8") if rel else ""),
            graph_reconcile=lambda rel, mundo: _reconcile_import_graph(rel, mundo),
            graph_reconcile_many=_reconcile_import_graph_many,
            register_gallery=_register_import_gallery,
        ),
    ),
)


# ---------------------------------------------------------------------------
# Methodology library — Taller de Herramientas
#
# Publish an editable draft into an immutable version, activate it by world,
# and roll back. Activation only governs NEW guided sessions: existing
# sessions keep their pinned snapshot and fail closed on resume when the
# world's active version changed. Imports stay quarantined until the Author
# manually trusts the package; nothing activates automatically.
# ---------------------------------------------------------------------------

@app.get("/api/methodologies/status")
def methodologies_status(request: Request):
    """Library status: published versions, per-world activations, drafts."""
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    library = _methodology_library()
    published = [
        {
            "skill_id": item.skill_id,
            "version": item.version,
            "name": item.name,
            "description": item.description,
            "digest": item.digest,
            "published_at": item.published_at,
        }
        for item in library.list_published()
    ]
    activations = {}
    for world in _known_worlds():
        activation = library.active_for(world)
        if activation is not None:
            activations[world] = {
                "world": activation.world,
                "skill_id": activation.skill_id,
                "version": activation.version,
                "digest": activation.digest,
                "activated_at": activation.activated_at,
            }
    drafts = [
        {
            "draft_id": draft.draft_id,
            "skill_id": draft.skill_id,
            "version": draft.version,
            "name": draft.name,
            "source": draft.source,
            "description": draft.description,
            "updated_at": draft.updated_at,
        }
        for draft in library.list_drafts()
    ]
    return {"published": published, "activations": activations, "drafts": drafts}


def _known_worlds() -> list[str]:
    return [entry.name for entry in sorted(MUNDOS_DIR.iterdir()) if entry.is_dir()
            and not entry.name.startswith((".", "_")) and entry.name != "Ideas"]


@app.post("/api/methodologies/drafts")
def methodologies_create_draft(body: MethodologyDraftRequest, request: Request):
    """Create an editable draft. The compiler validates it on publish."""
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    library = _methodology_library()
    draft_id = library.create_draft(
        skill_id=body.skill_id,
        version=body.version,
        name=body.name,
        source=body.source,
        description=body.description,
        phases=tuple(body.phases or []),
        language=body.language,
    )
    draft = library.get_draft(draft_id)
    assert draft is not None
    return {
        "draft_id": draft.draft_id,
        "skill_id": draft.skill_id,
        "version": draft.version,
        "name": draft.name,
        "source": draft.source,
        "description": draft.description,
        "updated_at": draft.updated_at,
    }


@app.post("/api/methodologies/drafts/{draft_id}/publish")
def methodologies_publish(draft_id: str, request: Request):
    """Compile and publish an immutable methodology version."""
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    library = _methodology_library()
    try:
        published = library.publish(draft_id)
    except ValidationError as exc:
        return JSONResponse(status_code=422, content={
            "detail": str(exc), "code": "validation_error",
        })
    except AlreadyPublishedError as exc:
        return JSONResponse(status_code=409, content={
            "detail": str(exc), "code": "already_published",
        })
    return {
        "skill_id": published.skill_id,
        "version": published.version,
        "name": published.name,
        "description": published.description,
        "digest": published.digest,
        "published_at": published.published_at,
    }


@app.post("/api/methodologies/activate")
def methodologies_activate(body: MethodologyActivateRequest, request: Request):
    """Pin a published methodology version to a world (new sessions only)."""
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    if _resolve_mundo_dir(body.world) is None:
        return JSONResponse(status_code=404, content={"detail": "Mundo no encontrado"})
    library = _methodology_library()
    try:
        activation = library.activate(body.world, body.skill_id, body.version)
    except NotPublishedError as exc:
        return JSONResponse(status_code=422, content={
            "detail": str(exc), "code": "not_published",
        })
    return {
        "world": activation.world,
        "skill_id": activation.skill_id,
        "version": activation.version,
        "digest": activation.digest,
        "activated_at": activation.activated_at,
    }


@app.post("/api/methodologies/rollback")
def methodologies_rollback(body: MethodologyRollbackRequest, request: Request):
    """Roll back a world's active methodology to its previous version."""
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    library = _methodology_library()
    activation = library.rollback(body.world)
    if activation is None:
        return {"world": body.world, "skill_id": None, "version": None, "digest": None, "activated_at": None}
    return {
        "world": activation.world,
        "skill_id": activation.skill_id,
        "version": activation.version,
        "digest": activation.digest,
        "activated_at": activation.activated_at,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    logger.info("Starting Demiurgos Wiki API on port %d", port)
    logger.info("Mundos dir: %s (exists=%s)", MUNDOS_DIR, MUNDOS_DIR.is_dir())
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
