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
import tempfile
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal

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
import yaml
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from error_codes import problem, register_error_handlers

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
    candidate_minimum_complete,
    has_finished_exchange,
    resolve_candidate_nivel,
)
from convergence_injection import (
    build_specimen_block,
    carrier_root_for,
    read_adjunto_bytes,
    read_adjunto_text,
)
from guided_character_persistence import ReindexCoordinator
from guided_character_provider import HermesGuidedProvider, guided_capabilities
# Idea-materialization seam (AD2): a strict envelope + bounded prompt over the
# same runs-adapter seam as the guided provider. The provider performs no
# writes; MaterializationResponse.from_provider owns fail-closed validation.
from idea_materialization_protocol import (
    CancellationToken as MaterializationCancellationToken,
    DEADLINE_MS,
    PROTOCOL_VERSION as MATERIALIZATION_PROTOCOL_VERSION,
    MaterializationRequest,
    MaterializationResponse,
)
from idea_materialization_domain import (
    build_ficha_skeleton,
    build_grounding_candidates,
    resolve_file_slug,
    suggest_free_slug,
    validate_relations,
)
from idea_materialization_provider import HermesMaterializationProvider
from guided_session_store import GuidedSessionStore as DurableGuidedSessionStore
from co_creation_protocol import (
    Capabilities as CoCreationCapabilities,
    ErrorCode as CoCreationErrorCode,
    PROTOCOL_VERSION as CO_CREATION_PROTOCOL_VERSION,
    CoCreationRequest,
    CoCreationSessionState,
    StructuredError as CoCreationStructuredError,
    canvas_payload_issues,
    continue_co_creation_session,
)
from co_creation_session_store import CoCreationSessionStore
from co_creation_attachments import (
    ATTACHMENTS_SUBDIR,
    AttachmentUploadError,
    staging_dir_for,
    store_staged,
    validate_staged_upload,
)
from co_creation_materializer import (
    AttachmentMaterializationError,
    CoCreationMaterializer,
    _payload_adjuntos,
    _rollback_moved,
    move_publish_pins,
)
from hermes_co_creation_provider import HermesCoCreationProvider, co_creation_capabilities
from demiurgos_language import (
    LocaleSettings,
    normalize_locale,
    resolve_domain_language,
)
from local_state import LocalState
from account import (
    create_account as account_create_account,
    get_account as account_get_account,
    rotate_words as account_rotate_words,
    update_account as account_update_account,
    verify_password as account_verify_password,
    verify_words as account_verify_words,
)
import emergency_key
from onboarding import (
    commit_account_created as _commit_account_created,
    commit_step0 as _commit_step0,
    commit_world_created as _commit_world_created,
    status_from as _onboarding_status_from,
)
from readiness import probe_local_storage, project_cards
from telegram_settings import (
    has_token as telegram_has_token,
    telegram_state,
)
from wiki.world_authority import (
    WorldResultKind,
    create_world as _create_world,
    rename_world as _rename_world,
)
from wiki.world_authority import detect_legacy_layout
from methodology_library import (
    AlreadyPublishedError,
    AttachmentLimitError,
    CompanionLimitError,
    DEFAULT_FLOW_TYPE,
    GUIDED_CHARACTER_FLOW,
    MethodologyLibrary,
    MethodologyLibraryError,
    NotPublishedError,
    SUPPORTED_FLOW_TYPES,
    TRIGGER_INTAKE_LIMIT,
    FOUNDATIONAL_CHARACTER_SKILL_ID,
    TriggerApproval,
    TriggerInvalidError,
    TriggerNotApprovedError,
    ValidationError,
    normalize_trigger,
)
from methodology_compiler import AttachmentEntry
from methodology_seed import install_seeds
from methodology_trust import FOUNDATIONAL, QuarantineRecord, QuarantineStore, build_package
from semantic_intent import (
    CONTINUATION_STATES,
    SELF_CONTAINED_SEMANTIC_STATES,
    SemanticContext,
    SemanticDecision,
    SemanticIntentProvider,
    SemanticResult,
    action_for_state,
    unavailable_copy,
)
from conversation_memory_store import ConversationMemoryStore, Turn
from skill_router import SkillRouter, SkillRouteResult
from contract_projection import project_contract_markdown
from order_manifest import read_order, remove_from_order

import data_root  # flat sibling module (data-root resolver, WU-2)
import world_recycle_bin  # flat sibling module (world-level recycle bin)
from backup import runner as backup_runner  # the ONE run implementation
from backup.engine import BackupEngine  # in-process backup trigger (WU-11)
from backup.middleware import DataChangeNotifierMiddleware  # write signal + quiesce gate
from backup.router import create_backup_router  # /api/backup/* (WU-14)
from backup.state import backup_state  # backup card dedicated contract (WU-14)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger("demiurgos-api")

# ---------------------------------------------------------------------------
# Backup engine lifecycle (WU-11, portable-data-root-drive-backup)
# ---------------------------------------------------------------------------
# ONE engine per process, started and stopped by ``_lifespan``. Its runner is
# the SAME implementation ``POST /api/backup/run`` drives (``backup.runner``), so
# a debounced trigger and a manual run behave identically.
_BACKUP_ENGINE: BackupEngine | None = None
_BACKUP_ENGINE_LOCK = threading.Lock()


def _run_backup_once() -> Any:
    """One backup run, on the engine's worker thread.

    Delegates to :func:`backup.runner.run_backup`, the single run implementation
    shared with ``POST /api/backup/run``. The destination is read from the data
    root's ``config/backup.json``; with none configured the run refuses and
    records the reason in its outcome. A run never raises into the engine.
    """
    try:
        root: Path | None = _project_root()
    except Exception as exc:  # noqa: BLE001 — an unresolved root refuses, never crashes
        logger.warning("backup run skipped: %s", exc)
        return backup_runner.RunOutcome(
            status=backup_runner.STATUS_FAILED,
            refused=True,
            error=f"backup run skipped: {exc}",
        )
    return backup_runner.run_backup(data_root=root)


def _backup_engine() -> BackupEngine:
    """The process engine, built once with the data root resolved lazily.

    A data root that cannot be resolved degrades to an engine without a
    filesystem watcher — the engine still starts and still serves notifications,
    so a misconfigured root can never take the API down at startup.
    """
    global _BACKUP_ENGINE
    with _BACKUP_ENGINE_LOCK:
        if _BACKUP_ENGINE is None:
            try:
                root: Path | None = _project_root()
            except Exception as exc:  # noqa: BLE001 — startup must not depend on it
                logger.warning("backup engine starts without a data root: %s", exc)
                root = None
            _BACKUP_ENGINE = BackupEngine(_run_backup_once, data_root=root)
        return _BACKUP_ENGINE


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _GATEWAY_KEY, _hermes_client
    # Resolve the gateway key from the DATA root's .env when the environment does
    # not carry it (WU-2: an import-time read would resolve the data root while
    # this module is imported). The module-level adapter singleton captured the
    # key at import, so it is rebound here, and any client already built without
    # a key is dropped so the next request rebuilds it with the headers.
    if not _GATEWAY_KEY:
        _GATEWAY_KEY = _load_project_env("HERMES_GATEWAY_KEY")
        if _GATEWAY_KEY:
            ACTIVITY_ADAPTER.api_key = _GATEWAY_KEY
            _hermes_client = None
    # Startup: restore sessions persisted by a previous run (see the note at the
    # former ``_load_persisted_sessions()`` call site), then reclaim dead import
    # spool data once, before serving any request. Failures are logged and never
    # crash startup.
    try:
        _load_persisted_sessions()
    except Exception as exc:  # noqa: BLE001 — never crash startup
        logger.warning("session restore failed: %s", exc)
    if gc_enabled():
        try:
            counts = reap_dead_spools(
                _import_store(),
                _project_root() / "data" / "import-spool",
                gc_ttl_days(),
                mundos_dir=_mundos_dir(),
            )
            if any(counts.values()):
                logger.info("Spool GC startup sweep: %s", counts)
        except Exception as exc:  # noqa: BLE001 — never crash startup
            logger.warning("Spool GC startup sweep failed: %s", exc)
    # Etapa 1 (D6): reconcile the native skills into the unregistered staging
    # tree once at boot and record the (world, revision) epoch. Inert and
    # additive; a failure is logged and never crashes startup.
    try:
        _materialize_skills()
    except Exception as exc:  # noqa: BLE001 — never crash startup
        logger.warning("Skill materialization startup sweep failed: %s", exc)
    # The backup engine starts once the startup sweep is done, then stops on the
    # way out. A debounce deadline still pending is DROPPED, not flushed: the
    # next start's reconciliation pass catches whatever changed (SC-BE-6.3).
    engine = _backup_engine()
    engine.start()
    try:
        yield
    finally:
        engine.stop(timeout=5)


app = FastAPI(title="Demiurgos Wiki API", lifespan=_lifespan)


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

# One generic hook on the write path (REQ-BE-6): any successful mutating
# ``/api/*`` request signals the backup engine, so a future endpoint is covered
# with zero per-route work. The same middleware is the quiesce gate that answers
# mutating ``/api/*`` with 503 while a restore owns the data root (REQ-RS-3).
app.add_middleware(DataChangeNotifierMiddleware)

# UI-bound errors carry stable codes + params (AD-4/AD-5): routes raise
# ``problem("import.job_not_found")`` and this handler renders
# ``{"detail": <en>, "code": ..., "params": ...}``. English ``detail`` stays
# for logs/CLI; un-migrated sites keep their current HTTPException body.
register_error_handlers(app)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Data-root seams (WU-2, portable-data-root-drive-backup). Author data
# (``mundos``, ``data``, ``config``, ``.env``) is resolved through the
# data-root resolver instead of this file's location.
#
# Resolution is LAZY and must stay that way: an import-time call would raise
# ``DataRootNotConfigured`` while pytest collects the suite, before the
# hermetic test root exists. These three names stay plain writable module
# attributes — existing fixtures monkeypatch them — and every internal read
# goes through the accessors below so a patched value always wins.
PROJECT_ROOT: Path | None = None
MUNDOS_DIR: Path | None = None
TRASH_ROOT: Path | None = None
# Prebuilt SPA dist dir (S1 static serving). Same lazy seam contract as the
# data-root names above: ``_frontend_dist()`` reads the env override first,
# then this patched attribute, then the dev-checkout default. The launcher is
# the sole exporter of ``DEMIURGOS_FRONTEND_DIST`` (S0-C layout contract).
FRONTEND_DIST: Path | None = None


class _LazyBinding:
    """Defer a construction that needs the data root to its first use.

    Module-level bindings that used to be built while this module was imported
    (the durable session stores, the guided reindex coordinator) resolve the
    data root on construction, which must not happen at import time. Attribute
    access builds the real object once; tests keep replacing the module
    attribute itself, exactly as before.
    """

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._value: Any = None

    def _resolve(self) -> Any:
        if self._value is None:
            self._value = self._factory()
        return self._value

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)


def _project_root() -> Path:
    """Data root, resolved on first use and rebound onto ``PROJECT_ROOT``.

    Never resolved at import time (see the note above). A monkeypatched
    ``PROJECT_ROOT`` always wins and is never overwritten.
    """
    global PROJECT_ROOT
    if PROJECT_ROOT is None:
        PROJECT_ROOT = data_root.resolve_data_root()
    return PROJECT_ROOT


def _mundos_dir() -> Path:
    """``<data root>/mundos``, honouring the ``MUNDOS_DIR`` patch seam.

    Derived on every call rather than cached: caching would leak one test's
    patched ``PROJECT_ROOT`` into the next test's ``MUNDOS_DIR``.
    """
    if MUNDOS_DIR is not None:
        return MUNDOS_DIR
    return _project_root() / "mundos"


def _world_trash_root() -> Path:
    """``<data root>/data/world-trash``, honouring the ``TRASH_ROOT`` seam.

    The default is delegated to ``world_recycle_bin`` so the literal lives in
    one place — the same relationship as the pre-WU-2
    ``TRASH_ROOT = world_recycle_bin.TRASH_ROOT`` copy, now resolved on demand.
    """
    if TRASH_ROOT is not None:
        return TRASH_ROOT
    return world_recycle_bin.default_world_trash_root()


# Code checkout root — NOT the data root. Runtime wiring that points at code
# artifacts (the launcher script) must keep following the checkout, wherever
# the author data root happens to live. Derived from the sys.path anchors above.
_CODE_ROOT = _TOOLS.parent.parent


def _frontend_dist() -> Path | None:
    """Prebuilt SPA dist dir, resolved lazily on each request (S1-2).

    Order: ``DEMIURGOS_FRONTEND_DIST`` env (exported by the launcher per the
    S0-C layout contract) > patched ``FRONTEND_DIST`` module attribute (test
    seam) > ``_CODE_ROOT / "frontend" / "dist"`` (dev checkout). Derived on
    every call rather than cached so a patched value always wins, mirroring
    ``_mundos_dir()``.
    """
    env_dist = os.environ.get("DEMIURGOS_FRONTEND_DIST")
    if env_dist:
        return Path(env_dist)
    if FRONTEND_DIST is not None:
        return FRONTEND_DIST
    return _CODE_ROOT / "frontend" / "dist"


# Fixed extension -> content type map (S1-3), consulted BEFORE
# ``mimetypes.guess_type``: the Windows registry can map ``.js`` to
# ``text/plain``, which blocks ES modules and renders a blank page only on
# Windows. A deterministic map keeps the served type identical on every OS.
CONTENT_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".woff2": "font/woff2",
    ".wasm": "application/wasm",
    ".html": "text/html",
    ".ico": "image/x-icon",
}


def _content_type(path: Path) -> str:
    """Content type for a served file: fixed map first, mimetypes fallback."""
    return (
        CONTENT_TYPES.get(path.suffix.lower())
        or mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )


def _cache_control(request_path: str) -> str:
    """Cache policy (S1-5): index revalidates; content-hashed assets immutable."""
    if request_path.startswith("assets/"):
        return "public, max-age=31536000, immutable"
    return "no-cache"


def _spa_index_response(dist: Path) -> FileResponse:
    """SPA shell: ``index.html`` with a revalidate cache policy."""
    return FileResponse(
        dist / "index.html",
        media_type="text/html",
        headers={"Cache-Control": "no-cache"},
    )

# Names that can never be treated as worlds. ``trash`` is reserved so a world
# literally named "trash" can never collide with the world recycle-bin routes
# (GET /api/worlds/trash, DELETE /api/worlds/trash/{name}).
_RESERVED_WORLD_NAMES = frozenset({"Ideas", "trash"})

# The single literal ``mundo`` segment that maps to the world-agnostic assistant
# context (Taller de Ideas). ONLY this exact string is special: the AI assistant
# handlers accept it as a valid context WITHOUT a world directory, while every
# other route (and every other unknown name) keeps rejecting it.
GLOBAL_ASSISTANT_CONTEXT = "ideas-global"


_LOCAL_STATE: LocalState | None = None


def _local_state() -> LocalState:
    """Lazily-initialized authoritative local state registry (ONB-1.3).

    Lives under ``<project>/data/local-state.json`` and is runtime-authoritative:
    Engram is recovery/context only and never governs readiness. The registry
    never touches ``.demiurgos-estado.json`` (narrative arc state).
    """
    global _LOCAL_STATE
    if _LOCAL_STATE is None:
        _LOCAL_STATE = LocalState(_project_root() / "data" / "local-state.json")
    return _LOCAL_STATE


def _list_worlds() -> list[dict]:
    """List available worlds in mundos/ (skip reserved names, hidden dirs)."""
    worlds = []
    if not _mundos_dir().is_dir():
        return worlds
    for entry in sorted(_mundos_dir().iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith(".") or entry.name.startswith("_"):
            continue
        if entry.name in _RESERVED_WORLD_NAMES:
            continue
        # Count files in lore + personajes + referencias
        lore_count = len(list((entry / "lore").rglob("*.md"))) if (entry / "lore").is_dir() else 0
        char_count = len(list((entry / "personajes").rglob("*.md"))) if (entry / "personajes").is_dir() else 0
        ref_count = len(list((entry / "referencias").rglob("*.md"))) if (entry / "referencias").is_dir() else 0
        worlds.append({
            "name": entry.name,
            "path": str(entry),
            "lore_count": lore_count,
            "character_count": char_count,
            "reference_count": ref_count,
        })
    return worlds


def _resolve_mundo_dir(mundo: str) -> Path | None:
    """Resolve *mundo* to its root directory under ``mundos/``.

    A valid world is a direct child of ``_mundos_dir()`` that exists and
    passes the same visibility rules as ``_list_worlds`` (not hidden,
    not ``_``-prefixed, not ``Ideas``). Returns None when *mundo* is
    missing, a traversal attempt (``..``, separators, absolute paths,
    drive letters), or not a real world — callers map None to their
    established contract (404 for mutations, soft-empty for lists).
    """
    if not isinstance(mundo, str) or not mundo:
        return None
    # Follow a rename alias: an old world name resolves to its canonical dir,
    # so links/URLs to a renamed world keep working (no 404 on old names).
    alias = resolve_world_alias(mundo)
    if alias:
        mundo = alias
    if Path(mundo).name != mundo:  # separators / absolute paths / dot segments
        return None
    if mundo.startswith((".", "_")) or mundo in _RESERVED_WORLD_NAMES:
        return None
    mundo_dir = (_mundos_dir() / mundo).resolve()
    if not mundo_dir.is_dir():
        return None
    if mundo_dir.parent != _mundos_dir().resolve():
        return None
    return mundo_dir


def _resolve_assistant_context(mundo: str) -> tuple[str, Path | None]:
    """Resolve an assistant ``mundo`` segment to ``(kind, world_root)``.

    ``kind`` is one of:
      ``"global"``  — the single literal :data:`GLOBAL_ASSISTANT_CONTEXT`
                      (world-agnostic: ``world_root`` is ``None``, no world
                      directory is required or resolved, no lore grounding);
      ``"world"``   — a real, visible world (same rules as
                      :func:`_resolve_mundo_dir`); ``world_root`` is its root;
      ``"unknown"`` — anything else; callers fail closed.

    Only the AI assistant handlers use this narrow resolver.
    ``_resolve_mundo_dir`` itself is unchanged, so every other route keeps
    rejecting the global context and arbitrary strings are never treated as
    worlds.
    """
    if mundo == GLOBAL_ASSISTANT_CONTEXT:
        return "global", None
    world_dir = _resolve_mundo_dir(mundo)
    if world_dir is not None:
        return "world", world_dir
    return "unknown", None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/worlds")
def get_worlds():
    """List all available narrative worlds."""
    worlds = _list_worlds()
    logger.info("GET /api/worlds -> %d worlds", len(worlds))
    return worlds


@app.get("/api/worlds/aliases")
def get_world_aliases():
    """Rename-alias map ``{old_name: new_name}`` (rename redirects)."""
    return read_world_aliases()


@app.get("/health")
def health():
    return {"status": "ok", "worlds_available": bool(_list_worlds())}


@app.get("/api/config")
def get_app_config():
    """Non-sensitive global runtime metadata for the frontend.

    Exposes only the normalized UI language, persisted-first (the selected
    locale) with the project ``.env``/environment as fallback; never secrets
    or paths.
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
    conversation_explicit: bool = False
    content_explicit: bool = False
    region: str | None = None
    region_explicit: bool = False
    iana_timezone: str = "UTC"


class WorldCreateRequest(BaseModel):
    name: str
    lore_skeleton: bool = False


class WorldRenameRequest(BaseModel):
    new_name: str


class WorldRestoreRequest(BaseModel):
    new_name: str | None = None


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
    """Persist step 0 locale. Gated ONLY when the vault is ON: fresh installs
    with the vault OFF must onboard without authentication (S-AC-02a);
    with the vault ON unauthenticated access fails closed (401, S-AC-02b)."""
    if _vault_active():
        principal = _resolve_principal(request)
        if principal is None:
            raise problem("auth.required")
    registry = _local_state()
    try:
        next_state = _commit_step0(
            registry.snapshot(),
            body.model_dump(),
            normalize_locale=normalize_locale,
        )
    except ValueError as exc:
        raise problem("locale.invalid", detail=str(exc)) from exc
    registry.atomic_commit(next_state)
    return _onboarding_status_from(registry.snapshot(), world_names=_world_names())


@app.post("/api/worlds")
def create_world(body: WorldCreateRequest, request: Request):
    """Create a canonical new world (lowercase tree + optional OC8 skeleton).

    Gated write when the vault is ON (fail-closed 401, S-AC-02d); with the
    vault OFF creation needs no authentication (S-AC-02c) — the local-only
    threat model treats the vault flag as the single source of truth.
    Idempotent repeats are harmless; collisions and unsafe names are rejected
    without mutation.
    """
    if _vault_active():
        principal = _resolve_principal(request)
        if principal is None:
            raise problem("auth.required")
    result = _create_world(_mundos_dir(), body.name, lore_skeleton=body.lore_skeleton)
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
    connection test) passed through ``telegram_state``. The ``cards`` map
    (OC11/OC12/OC21) carries the honest card states. The ``legacy`` list (ONB-4.2)
    reports worlds using uppercase ``Lore``/``Personajes`` folders — read-only
    detection; nothing is ever renamed.
    """
    probe = probe_local_storage(_project_root())
    state = _local_state().snapshot()
    cards = project_cards(
        state,
        _world_names(),
        bool(probe["ok"]),
        telegram_state=telegram_state(state, telegram_has_token()),
        backup_state=backup_state(state),
    )
    return {
        "local_editor": probe,
        "cards": cards,
        "legacy": detect_legacy_layout(_mundos_dir()),
    }


def _record_assistant_acceptance(runtime_state: str) -> None:
    """Record the three-proof assistant acceptance mirror in the registry.

    Called by the assistant settings router after a successful save whose
    probes passed server-side (ONB-2.5/ONB-3.6). The runtime state is the
    Hermes seam result — ``accepted`` maps to the readiness proof vocabulary;
    any other state (``pending-reload``/``saved-not-active``) keeps the badge
    honestly pending because the projection requires exactly
    text=passed + vision=passed + runtime=accepted.

    The accepted ``revision`` is stamped so a later save invalidates this
    acceptance; the readiness projection ignores the extra key.
    """
    registry = _local_state()
    state = registry.snapshot()
    state["assistant_acceptance"] = {
        "text": "passed",
        "vision": "passed",
        "runtime": "accepted" if runtime_state == "active" else runtime_state,
        "revision": assistant_settings.current_config_revision(),
    }
    registry.atomic_commit(state)


_GATEWAY_PROBE = None


def _assistant_gateway_probe() -> "HermesGatewayProbe":
    """Lazily-built read-only gateway liveness probe (process-free)."""
    global _GATEWAY_PROBE
    if _GATEWAY_PROBE is None:
        _GATEWAY_PROBE = HermesGatewayProbe()
    return _GATEWAY_PROBE


def _resolve_assistant_runtime_state(revision: int) -> str:
    """Honest runtime state for a config revision.

    The recorded acceptance is the arbiter: ``active`` requires a live gateway
    AND an acceptance for THIS revision whose recorded ``runtime`` is
    ``accepted`` (with both probes passed). ``readiness.assistant_proven`` reads
    that same evidence for the Configuration Center card, so the panel and the
    card agree on one truth. A live gateway without such an acceptance is
    ``pending-reload`` (config present but unproven). No live gateway — or an
    unreadable snapshot — is ``saved-not-active`` (fail closed).
    """
    if not _assistant_gateway_probe().is_running():
        return "saved-not-active"
    evidence = _local_state().snapshot().get("assistant_acceptance")
    if (
        isinstance(evidence, dict)
        and evidence.get("revision") == revision
        and evidence.get("text") == "passed"
        and evidence.get("vision") == "passed"
        and evidence.get("runtime") == "accepted"
    ):
        return "active"
    return "pending-reload"


# ---------------------------------------------------------------------------
# World recycle bin (REQ-001..007) — world delete, trash list, restore, purge
#
# Auth: every route requires a trusted principal (`_resolve_principal`), the
# same fail-closed gate as every other gated write. Purge is lazy on
# GET /api/worlds/trash (house style — the only scheduled cleanup in this
# codebase, `_prune_local_sessions`/`.papelera` TTL, runs on the read path),
# guarded by a module-level timestamp + lock so it runs at most once per 24h
# and only when the trash is non-empty.
# ---------------------------------------------------------------------------

class WorldDeleteRequest(BaseModel):
    confirm_name: str


_last_purge_at: datetime | None = None
_purge_lock = threading.Lock()

_last_reap_at: datetime | None = None
_reap_lock = threading.Lock()


def _maybe_reap_spool() -> None:
    """Lazy import spool GC on the read path, at most once per guard interval.

    Mirrors ``_maybe_purge_expired`` (house style): the time-guard check sits
    inside the lock so concurrent lazy calls are serialized, and a running
    sweep is skipped while another sweep is in progress.
    """
    global _last_reap_at
    if not gc_enabled():
        return
    now = datetime.now(timezone.utc)
    with _reap_lock:
        if _last_reap_at is not None and (
            now - _last_reap_at
        ) < timedelta(hours=gc_guard_hours()):
            return
        _last_reap_at = now
    try:
        counts = reap_dead_spools(
            _import_store(),
            _project_root() / "data" / "import-spool",
            gc_ttl_days(),
            mundos_dir=_mundos_dir(),
        )
        if any(counts.values()):
            logger.info("Spool GC lazy sweep: %s", counts)
    except Exception as exc:  # noqa: BLE001 — never break the read path
        logger.warning("Spool GC lazy sweep failed: %s", exc)


def _active_world() -> str:
    """Configured active world (idea-capture config); '' when unset.

    The idea-capture config is the only active-world concept in this
    codebase. Resolved lazily so this module never hard-depends on the
    config router at import time.
    """
    try:
        from idea_capture_ui import read_config
        config, _errors = read_config()
        value = config.get("active_world")
        return value.strip() if isinstance(value, str) else ""
    except Exception:
        return ""


def _native_channel_enabled(world: str) -> bool:
    """Whether ``world`` opted into the native Hermes channel (design Q1).

    Delegates to the methodology library's per-world flag; a missing library
    or unreadable store degrades to OFF (REQ-NC-2 tolerant read), never ON.
    """
    try:
        return bool(_methodology_library().native_channel_enabled(world))
    except Exception:
        return False


def _channel_session_id(base_session_id: str) -> str:
    """D4 run-path session id: epoch-suffixed when the native channel applies.

    The run submission keys its Hermes ``session_id`` by this value so a live
    session pinned to an older ``(world, revision)`` is never reused after a
    promotion (REQ-LP-6 / REQ-MM-2). The suffix applies only when the active
    channel is healthy ``native``: the flag-OFF path (and the fail-closed
    ``unhealthy`` state) keep the base id unchanged, so the legacy run path
    stays byte-identical (REQ-NC-2/REQ-NC-5). Never raises: any read failure
    keeps the base id unchanged.
    """
    world = _active_world()
    if not world or not _native_channel_enabled(world):
        return base_session_id
    if _active_channel_state() != "native":
        # Flag ON but unhealthy: fail-closed — no epoch-suffixed native session.
        return base_session_id
    try:
        from skill_session_epochs import (
            SessionEpochRegistry,
            resolve_session_store_path,
        )

        epoch_id = SessionEpochRegistry(
            resolve_session_store_path(_project_root())
        ).epoch_for(world)
    except Exception:
        epoch_id = None
    if not epoch_id:
        return base_session_id
    return f"{base_session_id}.{epoch_id}"


# ---------------------------------------------------------------------------
# Native channel state + health (WU-3.2, REQ-NC-5/REQ-NC-6)
#
# The runtime is modelled as a single tri-state per active world (design §1):
# "legacy" (flag OFF — byte-identical baseline), "native" (flag ON and
# healthy — the native SKILL.md is the only guide), "unhealthy" (flag ON but
# health fails — fail-closed: zero methodology guidance, never a silent legacy
# fallback, loudly logged). Every legacy-projection seam is suppressed when the
# state is not "legacy" (design §2 Q7 suppression matrix).
# ---------------------------------------------------------------------------

#: Tri-state of the active world's methodology channel (design §4).
ChannelState = Literal["legacy", "native", "unhealthy"]

#: Short process-local health memo (design Q4): ``key -> bool`` keyed by
#: ``(config mtime/size, live-marker signature, staging-marker signature,
#: flag)`` so a per-turn evaluation costs a stat + small read and invalidates
#: on any marker/config/flag change. Bounded: cleared past a small size.
_NATIVE_HEALTH_MEMO: dict[tuple[object, ...], bool] = {}
_NATIVE_HEALTH_MEMO_MAX = 64


def _dedicated_profile_config_path() -> Path:
    """Resolve the dedicated product profile ``config.yaml`` (HERMES_HOME-aware).

    Mirrors the runtime resolution used by the installer
    (``assistant_settings._resolve_profile_paths``), never the personal
    ``~/.hermes`` while the installer owns ``HERMES_HOME`` (REQ-NC-3/P0-8).
    Any resolution failure degrades to a nonexistent sentinel path so health
    reads the toolset as absent (fail-closed).
    """
    try:
        from assistant_settings import _resolve_profile_paths

        return _resolve_profile_paths().config
    except Exception:
        return Path("/") / "demiurgos-nonexistent-profile" / "config.yaml"


def _marker_signature(path: Path) -> tuple[int, int, str]:
    """``(st_mtime_ns, st_size, sha256)`` of a revision marker; zeros on absence."""
    try:
        if not path.is_file():
            return (0, 0, "")
        st = path.stat()
        return (st.st_mtime_ns, st.st_size, hashlib.sha256(path.read_bytes()).hexdigest())
    except OSError:
        return (0, 0, "")


def _health_memo_key(world: str) -> tuple[object, ...]:
    """Stat signature keying ``_NATIVE_HEALTH_MEMO`` (design Q4).

    ``(config mtime/size, live-marker signature, staging-marker signature,
    flag)`` — every health input change lands a new key, so the memo
    invalidates exactly when the inputs change (REQ-NC-6 per-turn evaluation).
    """
    config = _dedicated_profile_config_path()
    config_sig = (0, 0)
    try:
        if config.is_file():
            st = config.stat()
            config_sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        pass
    project_root = _project_root()
    try:
        from hermes_profile_config import resolve_skills_dir
        from skill_materializer import REVISION_MARKER_NAME, revision_marker_path

        staging = revision_marker_path(project_root)
        live = resolve_skills_dir(project_root) / REVISION_MARKER_NAME
    except Exception:
        staging = project_root / ".nonexistent-staging-marker"
        live = project_root / ".nonexistent-live-marker"
    return (
        config_sig,
        _marker_signature(staging),
        _marker_signature(live),
        _native_channel_enabled(world),
    )


def _promotion_current(world: str) -> bool:
    """Conditions 2+3 of channel health (REQ-NC-6): the registered live folder
    exists and its revision equals the staging marker.

    The toolset condition (1) is the reconcile's own output
    (``_sync_native_channel`` owns ``ensure_skills_toolset``), so the DECISION
    half of the reconcile evaluates this pair instead of the full conjunction —
    otherwise a missing toolset could never be enabled (self-reference). The
    REQUEST path uses the full ``channel_health`` conjunction, so a drifted
    toolset still fails closed (REQ-NC-5). Never raises: a read failure
    degrades to False (fail-closed).
    """
    try:
        from hermes_profile_config import resolve_skills_dir
        from skill_materializer import REVISION_MARKER_NAME, revision_marker_path

        project_root = _project_root()
        live_dir = resolve_skills_dir(project_root)
        if not live_dir.is_dir():
            return False
        live_marker = live_dir / REVISION_MARKER_NAME
        staging_marker = revision_marker_path(project_root)
        return (
            live_marker.is_file()
            and staging_marker.is_file()
            and live_marker.read_bytes() == staging_marker.read_bytes()
        )
    except Exception:
        return False


def channel_health(world: str) -> bool:
    """Native-channel health (REQ-NC-6): pure conjunction of three conditions.

    1. ``skills`` is present in ``platform_toolsets.api_server`` of the
       dedicated product profile;
    2. the registered live folder ``resolve_skills_dir(project_root)`` is a
       directory;
    3. promotion is current: the live ``.demiurgos-revision`` exists and equals
       the staging marker (``skill_materializer.revision_marker_path``).

    Evaluated on the request path before any injection (design Q4) with a
    short process-local memo (see ``_NATIVE_HEALTH_MEMO``). Never raises: every
    read failure degrades to unhealthy so the caller fails closed (REQ-NC-5).
    """
    try:
        key = _health_memo_key(world)
        cached = _NATIVE_HEALTH_MEMO.get(key)
        if cached is not None:
            return cached
        # 1. toolset presence in the dedicated profile config.
        toolset_ok = False
        config = _dedicated_profile_config_path()
        if config.is_file():
            data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                toolsets = data.get("platform_toolsets")
                tools = (
                    toolsets.get("api_server")
                    if isinstance(toolsets, dict) else None
                )
                toolset_ok = isinstance(tools, list) and "skills" in tools
        # 2+3. live folder present and promotion current.
        healthy = bool(toolset_ok and _promotion_current(world))
        if len(_NATIVE_HEALTH_MEMO) >= _NATIVE_HEALTH_MEMO_MAX:
            _NATIVE_HEALTH_MEMO.clear()
        _NATIVE_HEALTH_MEMO[key] = healthy
        return healthy
    except Exception:
        return False


def _active_channel_state() -> ChannelState:
    """Tri-state of the active world's native channel (design §1/§4).

    - ``legacy``    — no active world or the flag is OFF: the legacy projection
      behaves byte-identically and the native channel is absent.
    - ``native``    — flag ON and ``channel_health`` true: the native
      ``SKILL.md`` is the only methodology guide; every legacy seam is
      suppressed (REQ-NC-4).
    - ``unhealthy`` — flag ON but health fails (REQ-NC-5): fail-closed —
      legacy suppressed AND no native guidance; the state is LOUD
      (``logger.warning``) at every evaluation, never a silent legacy fallback
      (D2).
    """
    world = _active_world()
    if not world or not _native_channel_enabled(world):
        return "legacy"
    if channel_health(world):
        return "native"
    logger.warning(
        "native channel unhealthy for world %r; fail-closed (no methodology guidance)",
        world,
    )
    return "unhealthy"


def _sync_native_channel(world: str) -> bool:
    """Reconcile the dedicated profile's ``skills`` toolset (REQ-NC-3).

    Ensures ``skills`` presence matches the channel the reconcile does NOT own:
    the flag and promotion currency (``_promotion_current``), behind the WU-3.0
    probe gate — so with the probe closed NOTHING enables (REQ-NC-1) and a
    zero-ON config with ``skills`` never present stays byte-identical
    (REQ-NC-3 scenario 3). The toolset itself is the reconcile's own output,
    so the full ``channel_health`` conjunction (which it feeds back into)
    gates the REQUEST path, not the reconcile — a fresh flag-ON world without
    the toolset is enabled here, then health turns ``native`` on the next
    evaluation; operator drift removing ``skills`` is re-enabled, and the
    request path stays fail-closed meanwhile. Idempotent via
    ``ensure_skills_toolset``; never raises; the caller (boot / world switch /
    flag route) proceeds on any failure.
    """
    if not _probe_passed():
        return False
    try:
        from hermes_profile_config import ensure_skills_toolset

        config_path = _dedicated_profile_config_path()
        enabled = bool(_native_channel_enabled(world) and _promotion_current(world))
        return bool(ensure_skills_toolset(config_path, enabled=enabled))
    except Exception:
        logger.warning(
            "native channel toolset reconcile failed for world %r", world, exc_info=True
        )
        return False


def _world_aliases_path() -> Path:
    """``<data root>/data/world-aliases.json``, resolved on every call (WU-2)."""
    return _project_root() / "data" / "world-aliases.json"


def _set_active_world(world: str) -> None:
    """Rewrite the idea-capture active world (no-op when unreadable)."""
    try:
        from idea_capture_ui import read_config, write_config
        config, _ = read_config()
        config["active_world"] = world
        write_config(config)
    except Exception:  # noqa: BLE001 — rename must never fail on config rewrite
        logger.warning("could not set active_world to %s", world)
    # Etapa 1 (D6): refresh the staged skills for the new active world. Inert
    # (staging is unregistered) and never raises into the caller.
    try:
        _materialize_skills()
    except Exception as exc:  # noqa: BLE001 — rename must never fail on refresh
        logger.warning("skill materialization after world switch failed: %s", exc)


def read_world_aliases() -> dict[str, str]:
    """Return the rename-alias map ``{old_name: new_name}`` (may be empty)."""
    try:
        data = json.loads(_world_aliases_path().read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()}
    except (OSError, ValueError):
        return {}


def add_world_alias(old_name: str, new_name: str) -> None:
    """Record that *old_name* now resolves to *new_name* (rename redirect)."""
    aliases = read_world_aliases()
    aliases[old_name] = new_name
    try:
        _world_aliases_path().parent.mkdir(parents=True, exist_ok=True)
        _world_aliases_path().write_text(
            json.dumps(aliases, indent=2), encoding="utf-8")
    except OSError as exc:  # noqa: BLE001 — alias failure never breaks the rename
        logger.warning("could not persist world alias %s->%s: %s",
                       old_name, new_name, exc)


def resolve_world_alias(name: str) -> str | None:
    """Follow the alias chain for *name*; returns the latest canonical name."""
    aliases = read_world_aliases()
    seen: set[str] = set()
    cur = name
    while cur in aliases and cur not in seen:
        seen.add(cur)
        cur = aliases[cur]
    return cur if cur != name else None


def _hide_world_data(world_name: str) -> None:
    """Make a world's in-process associated data invisible (REQ-002).

    Graph cache entries are popped unconditionally (a world never opened has
    no entry — house style is ``.pop(name, None)``); guided sessions bound to
    the world are dropped from the in-memory store.
    """
    _graph_indices.pop(world_name, None)
    _GUIDED_SESSIONS.delete_for_world(world_name)


def _purge_world_associated_data(world_name: str) -> None:
    """Clean every association of a permanently purged world (REQ-006).

    Hides the in-process data (graph cache, guided sessions), removes
    idea-capture rows, and deletes the world's import jobs. Idea capture runs
    as a separate runtime process; when its package is not importable from
    this server, cleanup is delegated to that runtime and logged — this server
    never fabricates a connection to a database it does not own. Each store
    cleanup is guarded so a failure never breaks the purge.
    """
    _hide_world_data(world_name)
    try:
        from idea_capture.store import CaptureStore
    except ImportError:
        logger.warning(
            "World purge: idea_capture package not importable; idea-capture rows for '%s' are cleaned by the idea-capture runtime",
            world_name,
        )
    else:
        try:
            store = CaptureStore(_project_root() / "data" / "idea-capture.sqlite3")
            cleaned = store.delete_for_world(world_name)
            store.close()
            logger.info("World purge: cleaned %d idea-capture rows for '%s'", cleaned, world_name)
        except Exception as exc:
            logger.warning("World purge: idea-capture cleanup failed for '%s': %s", world_name, exc)
    try:
        jobs = _import_store().delete_jobs_for_world(world_name)
        logger.info("World purge: cleaned %d import jobs for '%s'", jobs, world_name)
    except Exception as exc:
        logger.warning("World purge: import-jobs cleanup failed for '%s': %s", world_name, exc)


def _maybe_purge_expired() -> None:
    """Lazy 24h-guarded purge; runs only when trash is non-empty and stale."""
    global _last_purge_at
    now = datetime.now(timezone.utc)
    with _purge_lock:
        if _last_purge_at is not None and (now - _last_purge_at) < timedelta(hours=24):
            return
        if not world_recycle_bin.list_trash(trash_root=_world_trash_root()):
            _last_purge_at = now
            return
        purged = world_recycle_bin.purge_expired(
            trash_root=_world_trash_root(),
            on_purge=_purge_world_associated_data,
        )
        _last_purge_at = now
        if purged:
            logger.info("World trash: lazily purged %d expired entries", purged)


@app.delete("/api/worlds/{name}")
def delete_world(name: str, body: WorldDeleteRequest, request: Request):
    """Move a world to the recycle bin (REQ-001)."""
    if _resolve_principal(request) is None:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    if _resolve_mundo_dir(name) is None:
        raise problem("world.not_found")
    if body.confirm_name.strip().lower() != name.strip().lower():
        raise HTTPException(
            status_code=400,
            detail={"code": "confirm_name_mismatch", "message": "El nombre de confirmación no coincide"},
        )
    if _active_world().lower() == name.lower():
        raise HTTPException(
            status_code=409,
            detail={"code": "active_world", "message": "No se puede eliminar el mundo activo"},
        )
    if len(_list_worlds()) <= 1:
        raise HTTPException(
            status_code=409,
            detail={"code": "only_world", "message": "Debe existir al menos un mundo"},
        )
    try:
        entry = world_recycle_bin.move_to_trash(name, trash_root=_world_trash_root(), mundos_dir=_mundos_dir())
    except ValueError as exc:
        raise problem("world.not_found") from exc
    _hide_world_data(name)
    logger.info("DELETE /api/worlds/%s -> trash", name)
    return entry.as_dict()


@app.get("/api/worlds/trash")
def get_world_trash(request: Request):
    """List recycle bin entries, lazily purging expired ones (REQ-004/006)."""
    if _resolve_principal(request) is None:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    _maybe_purge_expired()
    entries = world_recycle_bin.list_trash(trash_root=_world_trash_root())
    return [entry.as_dict() for entry in entries]


@app.post("/api/worlds/{name}/restore")
def restore_world(name: str, request: Request, body: WorldRestoreRequest | None = None):
    """Restore the most recent trash entry for a world (REQ-005).

    ``body.new_name`` (optional) restores it under a DIFFERENT name — the
    conflict-resolution path when an active world already owns ``name``.
    """
    if _resolve_principal(request) is None:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    try:
        restored_name = world_recycle_bin.restore_from_trash(
            name, new_name=(body.new_name if body else None),
            trash_root=_world_trash_root(), mundos_dir=_mundos_dir())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Mundo no encontrado en la papelera") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "world_exists", "message": "El mundo ya existe en mundos/"},
        ) from exc
    logger.info("POST /api/worlds/%s/restore -> restored as %s", name, restored_name)
    return {"status": "restored", "world_name": restored_name}


@app.post("/api/worlds/{name}/rename")
def rename_world(name: str, request: Request, body: WorldRenameRequest):
    """Rename an active world: move ``mundos/{name}`` → ``mundos/{new_name}``.

    Also rewrites the idea-capture ``active_world`` when it points at the old
    name, and records a rename alias so old URLs redirect to the new name.
    """
    if _resolve_principal(request) is None:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    result = _rename_world(_mundos_dir(), name, body.new_name)
    if result.kind == WorldResultKind.INVALID_NAME:
        raise HTTPException(status_code=400, detail=result.message)
    if result.kind == WorldResultKind.NOT_FOUND:
        raise HTTPException(status_code=404, detail=result.message)
    if result.kind == WorldResultKind.COLLISION:
        raise HTTPException(status_code=409, detail=result.message)
    if result.kind == WorldResultKind.IO_ERROR:
        raise HTTPException(status_code=500, detail=result.message)
    # Update the idea-capture active world reference if it pointed at the old name.
    try:
        if _active_world().lower() == name.lower():
            _set_active_world(result.name)
    except Exception:  # noqa: BLE001 — never block a successful rename on config
        logger.warning("rename: could not update active_world for %s", name)
    add_world_alias(name, result.name)
    logger.info("POST /api/worlds/%s/rename -> %s", name, result.name)
    return {"status": "renamed", "old_name": name, "new_name": result.name}


@app.delete("/api/worlds/trash/{name}")
def purge_trash_world(name: str, request: Request):
    """Permanently delete a world's trash entries and associated data (REQ-010)."""
    if _resolve_principal(request) is None:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    try:
        world_recycle_bin.purge_world(name, trash_root=_world_trash_root())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Mundo no encontrado en la papelera") from exc
    _purge_world_associated_data(name)
    logger.info("DELETE /api/worlds/trash/%s -> purged", name)
    return {"status": "purged", "world_name": name}


# ---------------------------------------------------------------------------
# File tree & content endpoints
# ---------------------------------------------------------------------------

VALID_SECTIONS = {"lore", "personajes", "referencias", "media"}

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

    The first path segment must be a valid section (lore/personajes/
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
_CREDENTIALS_AUTH_MODE = "credentials"
_CREDENTIALS_PROVIDER = "credentials"
_LOCAL_SESSION_COOKIE = "demiurgos_local_session"
_SESSION_COOKIE = "demiurgos_session"
_LOCAL_SESSION_TTL = timedelta(hours=8)
_DEFAULT_SESSION_TTL_H = 8
_DEFAULT_REMEMBER_ME_TTL_D = 30
_DEFAULT_REAUTH_INTERVAL_D = 14
_RECOVERY_TOKEN_TTL = timedelta(minutes=5)
# Generalized multi-provider session store: one dict for local-dev and
# credentials sessions, keyed by the sha256 hash of the bearer token.
# Records carry ``{provider, principal_id, label, expires_at, remember_me}``;
# credentials sessions additionally carry ``last_auth_at`` (R-AC-04).
_sessions: dict[str, dict] = {}
# Backward-compatible alias: existing tests/fixtures clear the store by its
# legacy name; both names reference the SAME generalized store.
_local_sessions = _sessions
_local_session_lock = threading.Lock()


def _sessions_file() -> Path:
    """Persisted session store path (R-AC-03): survives server restarts.

    Lives alongside the other local state under ``<project>/data/``. Not
    gitignored paths would leak tokens, so ``data/sessions.json`` is ignored.
    """
    return _project_root() / "data" / "sessions.json"


def _load_persisted_sessions() -> None:
    """Restore active sessions from disk so a restart keeps the session.

    R-AC-03: a remember-me session (and the default 8h session) must survive a
    server restart, not just a page reload. Prunes expired records. Never
    raises: a missing/corrupt file simply means no sessions to restore.
    """
    global _sessions
    path = _sessions_file()
    if not path.exists():
        return
    try:
        raw = path.read_text(encoding="utf-8")
        records = json.loads(raw)
    except (OSError, ValueError):
        return
    now = datetime.now(timezone.utc)
    restored: dict[str, dict] = {}
    for key, record in records.items():
        if not isinstance(record, dict):
            continue
        record = dict(record)
        expires = record.get("expires_at")
        if isinstance(expires, str):
            try:
                record["expires_at"] = datetime.fromisoformat(expires)
            except ValueError:
                continue
        last_auth = record.get("last_auth_at")
        if isinstance(last_auth, str):
            try:
                record["last_auth_at"] = datetime.fromisoformat(last_auth)
            except ValueError:
                record.pop("last_auth_at", None)
        if record.get("expires_at", now) > now:
            restored[key] = record
    _sessions.update(restored)


def _persist_sessions() -> None:
    """Write active sessions to disk atomically (tmp + rename).

    Called on session mutations (login/logout) so a restart restores them.
    Never raises: persistence is best-effort and must not break auth.
    """
    path = _sessions_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            key: {
                field: (value.isoformat() if isinstance(value, datetime) else value)
                for field, value in rec.items()
            }
            for key, rec in _sessions.items()
        }
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


# Sessions persisted by a previous run (single-user local app: survives server
# restarts so the author is not re-prompted each time) are restored at STARTUP,
# from ``_lifespan``. Restoring them here would resolve the data root while this
# module is imported (WU-2), which must not happen.

# Independent in-memory rate limiters for password and recovery-words
# verification (R-ERK-02): exhausting one auth factor never locks out the
# other. Kill-switch property: counters reset on process restart (filesystem
# access already means the vault is compromised).
_password_rate_limiter = emergency_key.RateLimiter()
_words_rate_limiter = emergency_key.RateLimiter()

# Short-lived, single-use recovery tokens (forgot-password flow, R-AC-05),
# keyed by the sha256 hash of the token. Same kill-switch property as the
# session store: tokens vanish on process restart.
_recovery_tokens: dict[str, dict] = {}


def _auth_mode() -> str:
    """Read auth mode at request time so local tests can isolate configuration."""
    return os.environ.get("DEMIURGOS_AUTH_MODE", "disabled").strip().lower()


def _is_loopback_request(request: Request | None) -> bool:
    """Use the socket peer only; Host and forwarded headers are untrusted.

    ``getattr`` keeps the check safe for request-like objects that carry no
    socket peer (e.g. test doubles): no client means no loopback proof.
    """
    client = getattr(request, "client", None) if request is not None else None
    if client is None:
        return False
    return client.host in {"127.0.0.1", "::1"}


def _local_auth_enabled() -> bool:
    return _auth_mode() == _LOCAL_AUTH_MODE


def _prune_local_sessions(now: datetime | None = None) -> None:
    """Prune expired sessions from the shared multi-provider store."""
    current = now or datetime.now(timezone.utc)
    for token_hash in [
        key for key, record in _sessions.items()
        if record["expires_at"] <= current
    ]:
        _sessions.pop(token_hash, None)


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
        return _sessions.get(token_hash)


def _vault_active() -> bool:
    """Vault is active when the operator override OR the persisted flag is on.

    PRIMARY: ``capabilities.vault.enabled`` in local state (R-VC-01). The
    ``DEMIURGOS_AUTH_MODE=credentials`` env override is the operator escape
    hatch (S-VC-01b): it forces the vault on regardless of the flag. This
    helper replaces ``_credentials_auth_enabled`` as the single auth gate for
    every credentials endpoint and for the onboarding/world fail-closed gates
    (R-AC-01, R-AC-02, R-VC-06).
    """
    if _auth_mode() == _CREDENTIALS_AUTH_MODE:
        return True
    state = _local_state().snapshot()
    vault = state.get("capabilities", {}).get("vault") or {}
    return bool(vault.get("enabled"))


def _credentials_session_for_request(request: Request | None) -> dict | None:
    """Resolve a credentials-vault session. NOT loopback-bound (unlike local-dev)."""
    if not _vault_active():
        return None
    token = request.cookies.get(_SESSION_COOKIE) if request else None
    if not token:
        return None
    now = datetime.now(timezone.utc)
    token_hash = _hash_token(token)
    with _local_session_lock:
        _prune_local_sessions(now)
        return _sessions.get(token_hash)


def _session_for_request(request: Request | None) -> dict | None:
    """Unified session resolution across every provider in the active mode.

    ``local-dev`` keeps its loopback-only binding; credentials-vault sessions
    are NOT loopback-bound and resolve whenever the vault is active (flag or
    env override, R-VC-06). Disabled mode never resolves a session.
    """
    if _vault_active():
        return _credentials_session_for_request(request)
    if _auth_mode() == _LOCAL_AUTH_MODE:
        return _local_session_for_request(request)
    return None


def _cookie_secure(request: Request) -> bool:
    """Scheme-aware cookie Secure flag + explicit env override (R-AC-03).

    The default follows the request scheme so the session cookie works on any
    deployment without configuration: HTTPS -> secure=True; plain HTTP
    (http://localhost on Windows/Linux, or a VPS served over HTTP) ->
    secure=False so the browser actually sends the cookie back and the login
    persists. ``DEMIURGOS_COOKIE_SECURE`` overrides the scheme default
    explicitly (the operator's call, e.g. behind a TLS-terminating proxy).
    """
    override = os.environ.get("DEMIURGOS_COOKIE_SECURE")
    if override is not None:
        return override.strip().lower() in ("1", "true", "yes", "on")
    return request.url.scheme == "https"


def _session_ttl(remember_me: bool) -> timedelta:
    """Session TTL from env: 8h default, 30d with remember_me (R-AC-03)."""
    if remember_me:
        days = int(os.environ.get(
            "DEMIURGOS_REMEMBER_ME_TTL_D", str(_DEFAULT_REMEMBER_ME_TTL_D)))
        return timedelta(days=days)
    hours = int(os.environ.get(
        "DEMIURGOS_SESSION_TTL_H", str(_DEFAULT_SESSION_TTL_H)))
    return timedelta(hours=hours)


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


def _reauth_interval_d() -> int:
    """Soft re-auth countdown interval in days (R-VC-05).

    PRIMARY: ``capabilities.vault.reauth_interval_d`` persisted in local
    state (default 14, R-VC-01). ``DEMIURGOS_REAUTH_INTERVAL_D`` is the
    operator override and wins when set (S-VC-05b).
    """
    override = os.environ.get("DEMIURGOS_REAUTH_INTERVAL_D")
    if override is not None and override.strip():
        return int(override)
    state = _local_state().snapshot()
    vault = state.get("capabilities", {}).get("vault") or {}
    return int(vault.get("reauth_interval_d", _DEFAULT_REAUTH_INTERVAL_D))


def _vault_config() -> dict:
    """Public vault status for the Settings panel (R-VC-02, S-VC-02a/b).

    Read-only and safe to expose without authentication: it never returns the
    words hash, the password hash, or any session material.
    """
    account = account_get_account(_local_state())
    return {
        "enabled": _vault_active(),
        "account_exists": account is not None,
        "username": account.get("username") if account else None,
        "has_password": bool(account and account.get("password_hash")),
        "reauth_interval_d": _reauth_interval_d(),
        "env_override": _auth_mode() == _CREDENTIALS_AUTH_MODE,
    }


def _session_status(request: Request) -> dict:
    """Unified mode-aware session status (R-ID-01 / R-VC-06): provider
    included when an active session exists (local-dev | credentials).
    Credentials sessions additionally expose ``last_auth_at`` (ISO 8601) and
    ``days_until_reauth`` (clamped at 0) for the soft re-auth countdown
    (R-AC-04, S-AC-04b/d).

    ``enabled`` equals ``_vault_active()`` (R-VC-06): when the vault is OFF
    the app is open and the AuthGate passes through; when it is ON
    unauthenticated users MUST be redirected to login (S-VC-06a/b).

    An active vault ALWAYS exposes ``has_password`` (bool) so the login UI
    can choose between the password prompt and the passwordless "Enter"
    button from the account slot instead of adapting to server errors
    (R-AC-02, S-AC-02a/b)."""
    # The vault flag persisted in local state is PRIMARY (R-VC-01): once the
    # vault is active it MUST be the credentials mode, regardless of a local-dev
    # env override still present for development. Otherwise the login UI would
    # show the passwordless local-dev button even though a password is set.
    mode = _CREDENTIALS_AUTH_MODE if _vault_active() else _auth_mode()
    enabled = _vault_active()
    session = _session_for_request(request) if enabled else None
    status = {
        "mode": mode,
        "enabled": enabled,
        "authenticated": session is not None,
        "label": session["label"] if session else None,
        "provider": session["provider"] if session else None,
    }
    if _vault_active():
        account = account_get_account(_local_state())
        status["has_password"] = bool(account and account.get("password_hash"))
    if session and session.get("provider") == _CREDENTIALS_PROVIDER:
        last_auth_at = session.get("last_auth_at")
        if last_auth_at is not None:
            elapsed_days = (datetime.now(timezone.utc) - last_auth_at).days
            status["last_auth_at"] = last_auth_at.isoformat()
            status["days_until_reauth"] = max(
                0, _reauth_interval_d() - elapsed_days)
    return status


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
        "provider": _LOCAL_AUTH_MODE,
        "principal_id": f"local-dev-session-{secrets.token_hex(16)}",
        "label": "Local development user",
        "expires_at": now + _LOCAL_SESSION_TTL,
        "remember_me": False,
    }
    with _local_session_lock:
        _prune_local_sessions(now)
        _local_sessions[_hash_token(token)] = session
    _persist_sessions()
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
            _sessions.pop(_hash_token(token), None)
        _persist_sessions()
    response.delete_cookie(_LOCAL_SESSION_COOKIE, path="/", samesite="lax")
    return _local_status(request)


@app.get("/api/auth/session/status")
def auth_session_status(request: Request):
    """Unified mode-aware session status (R-ID-01 / R-AC-04)."""
    return _session_status(request)


@app.delete("/api/auth/session")
def auth_session_logout(request: Request, response: Response):
    """Unified logout (R-AC-06): remove the active session and clear its cookie."""
    # Clear the cookie of the ACTIVE session provider, resolving it the same
    # way the session resolver does (R-VC-01). When the vault is active the
    # credentials session is authoritative, so the env-derived local-dev cookie
    # must NOT be cleared instead (that would leave the real session alive).
    active = _session_for_request(request)
    if active and active.get("provider") == _CREDENTIALS_PROVIDER:
        cookie = _SESSION_COOKIE
    elif _local_auth_enabled():
        cookie = _LOCAL_SESSION_COOKIE
    else:
        cookie = _SESSION_COOKIE
    token = request.cookies.get(cookie)
    if token:
        with _local_session_lock:
            _sessions.pop(_hash_token(token), None)
        _persist_sessions()
    response.delete_cookie(cookie, path="/", samesite="lax")
    return _session_status(request)


class CredentialsAccountRequest(BaseModel):
    username: str
    password: str | None = None


@app.post("/api/auth/credentials/account")
def credentials_account_create(payload: CredentialsAccountRequest, request: Request, response: Response):
    """Create the single local account during onboarding (R-AC-01).

    The recovery words are generated and returned in plaintext exactly once;
    only their Argon2id hash is stored (S-AC-01a). ``password`` is optional:
    a null ``password_hash`` marks the account passwordless (S-AC-01b). The
    account step is recorded as completed in onboarding (blocking step).

    NOT gated on the vault being active: the account step is part of the
    default onboarding flow and must work on a fresh install with the vault
    OFF (S-AC-01b) as well as with the vault ON via the flag (S-AC-01a). A
    second account is always rejected (409).
    """
    if account_get_account(_local_state()) is not None:
        raise HTTPException(status_code=409, detail="Account already exists")
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=422, detail="Username is required")
    words, _ = account_create_account(_local_state(), username, payload.password)
    registry = _local_state()
    registry.atomic_commit(_commit_account_created(registry.snapshot()))
    return {"username": username, "words": words}


class CredentialsLoginRequest(BaseModel):
    password: str | None = None
    remember_me: bool = False


@app.post("/api/auth/credentials/login")
def credentials_login(payload: CredentialsLoginRequest, request: Request, response: Response):
    """Start a credentials session: password if set, else passwordless (R-AC-02).

    A passwordless account needs no secret: clicking "Enter" is enough
    (S-AC-02b). Wrong passwords are rate-limited independently from recovery
    words (S-AC-02c, R-ERK-02). On success the HttpOnly vault session cookie
    is set with the remember-me TTL (30d) or the 8h default (R-AC-03).
    """
    if not _vault_active():
        raise HTTPException(status_code=403, detail="Credentials auth is disabled")
    account = account_get_account(_local_state())
    if account is None:
        raise HTTPException(status_code=401, detail="No account configured")
    stored_hash = account.get("password_hash")
    if stored_hash:
        if not payload.password:
            raise HTTPException(status_code=422, detail="Password required")
        if not account_verify_password(payload.password, stored_hash, _password_rate_limiter):
            raise HTTPException(status_code=401, detail="Invalid or rate-limited password")

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    ttl = _session_ttl(payload.remember_me)
    session = {
        "provider": _CREDENTIALS_PROVIDER,
        "principal_id": f"credentials-session-{secrets.token_hex(16)}",
        "label": account.get("username") or "Demiurgos account",
        "expires_at": now + ttl,
        "remember_me": payload.remember_me,
        "last_auth_at": now,
    }
    with _local_session_lock:
        _prune_local_sessions(now)
        _sessions[_hash_token(token)] = session
    _persist_sessions()
    response.set_cookie(
        _SESSION_COOKIE,
        token,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
        path="/",
    )
    return {
        "mode": _CREDENTIALS_AUTH_MODE,
        "enabled": True,
        "authenticated": True,
        "label": session["label"],
        "provider": _CREDENTIALS_PROVIDER,
    }


class CredentialsRecoverRequest(BaseModel):
    words: str


@app.post("/api/auth/credentials/recover")
def credentials_recover(payload: CredentialsRecoverRequest, request: Request, response: Response):
    """Verify the recovery words and issue a short-lived recovery token (R-AC-05).

    Lets a user who forgot the password prove ownership (words = ownership
    key) and reset credentials. The token is single-use and expires after 5
    minutes. Wrong words are rate-limited on the words limiter (R-ERK-02),
    independent from the password limiter.
    """
    if not _vault_active():
        raise HTTPException(status_code=403, detail="Credentials auth is disabled")
    account = account_get_account(_local_state())
    if account is None:
        raise HTTPException(status_code=401, detail="No account configured")
    if not account_verify_words(payload.words, account.get("words_hash"), _words_rate_limiter):
        raise HTTPException(status_code=401, detail="Invalid or rate-limited recovery words")
    token = secrets.token_urlsafe(32)
    with _local_session_lock:
        _recovery_tokens[_hash_token(token)] = {
            "expires_at": datetime.now(timezone.utc) + _RECOVERY_TOKEN_TTL,
        }
    return {"recovery_token": token}


class CredentialsRecoverCompleteRequest(BaseModel):
    recovery_token: str
    new_username: str | None = None
    new_password: str | None = None


@app.post("/api/auth/credentials/recover/complete")
def credentials_recover_complete(payload: CredentialsRecoverCompleteRequest, request: Request, response: Response):
    """Consume the recovery token and set the new username/password (R-AC-05).

    The token is single-use: it is consumed by this call and a replay fails.
    ``new_password=None`` leaves the password untouched; ``new_username=None``
    leaves the username untouched.
    """
    if not _vault_active():
        raise HTTPException(status_code=403, detail="Credentials auth is disabled")
    token_hash = _hash_token(payload.recovery_token)
    with _local_session_lock:
        record = _recovery_tokens.pop(token_hash, None)  # single-use
    if record is None or record["expires_at"] <= datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Invalid or expired recovery token")
    new_username = payload.new_username.strip() if payload.new_username else None
    if not new_username and payload.new_password is None:
        raise HTTPException(status_code=422, detail="Nothing to update")
    account_update_account(
        _local_state(),
        new_username=new_username,
        new_password=payload.new_password,
    )
    return {"success": True}


class CredentialsPasswordRequest(BaseModel):
    words: str
    new_password: str


@app.post("/api/auth/credentials/password")
def credentials_change_password(payload: CredentialsPasswordRequest, request: Request, response: Response):
    """Change the password by proving ownership with the recovery words (R-AC-05a)."""
    if not _vault_active():
        raise HTTPException(status_code=403, detail="Credentials auth is disabled")
    if _resolve_principal(request) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    account = account_get_account(_local_state())
    if account is None:
        raise HTTPException(status_code=401, detail="No account configured")
    if not account_verify_words(payload.words, account.get("words_hash"), _words_rate_limiter):
        raise HTTPException(status_code=401, detail="Invalid or rate-limited recovery words")
    account_update_account(_local_state(), new_password=payload.new_password)
    return {"success": True}


class CredentialsPasswordRemoveRequest(BaseModel):
    words: str


@app.post("/api/auth/credentials/password/remove")
def credentials_remove_password(payload: CredentialsPasswordRemoveRequest, request: Request, response: Response):
    """Remove the password (back to passwordless) via the recovery words (R-AC-05b)."""
    if not _vault_active():
        raise HTTPException(status_code=403, detail="Credentials auth is disabled")
    if _resolve_principal(request) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    account = account_get_account(_local_state())
    if account is None:
        raise HTTPException(status_code=401, detail="No account configured")
    if not account_verify_words(payload.words, account.get("words_hash"), _words_rate_limiter):
        raise HTTPException(status_code=401, detail="Invalid or rate-limited recovery words")
    account_update_account(_local_state(), remove_password=True)
    return {"success": True}


class CredentialsUsernameRequest(BaseModel):
    words: str
    new_username: str


@app.post("/api/auth/credentials/username")
def credentials_change_username(payload: CredentialsUsernameRequest, request: Request, response: Response):
    """Change the username by proving ownership with the recovery words (R-AC-05c)."""
    if not _vault_active():
        raise HTTPException(status_code=403, detail="Credentials auth is disabled")
    if _resolve_principal(request) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    account = account_get_account(_local_state())
    if account is None:
        raise HTTPException(status_code=401, detail="No account configured")
    if not account_verify_words(payload.words, account.get("words_hash"), _words_rate_limiter):
        raise HTTPException(status_code=401, detail="Invalid or rate-limited recovery words")
    new_username = payload.new_username.strip()
    if not new_username:
        raise HTTPException(status_code=422, detail="Username is required")
    account_update_account(_local_state(), new_username=new_username)
    return {"success": True}


class CredentialsRotateWordsRequest(BaseModel):
    words: str


@app.post("/api/auth/credentials/words/rotate")
def credentials_rotate_words(
    payload: CredentialsRotateWordsRequest, request: Request, response: Response
):
    """Rotate the recovery words (R-ERK-01, amended); the CURRENT recovery
    words are the ownership proof, rate-limited exactly like R-AC-05a/b/c.

    Returns the new plaintext words exactly once; the old words are
    invalidated by the atomic commit of the new Argon2id hash.
    """
    if not _vault_active():
        raise HTTPException(status_code=403, detail="Credentials auth is disabled")
    if _resolve_principal(request) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    account = account_get_account(_local_state())
    if account is None:
        raise HTTPException(status_code=401, detail="No account configured")
    if not account_verify_words(payload.words, account.get("words_hash"), _words_rate_limiter):
        raise HTTPException(status_code=401, detail="Invalid or rate-limited recovery words")
    words, _ = account_rotate_words(_local_state())
    return {"new_words": words}


# ---------------------------------------------------------------------------
# R-VC-02..R-VC-05 — vault lifecycle (vault-settings-configure)
# ---------------------------------------------------------------------------


class VaultEnableRequest(BaseModel):
    username: str | None = None
    password: str | None = None
    words: str | None = None


class VaultDisableRequest(BaseModel):
    words: str | None = None


class VaultReauthIntervalRequest(BaseModel):
    reauth_interval_d: int


@app.get("/api/auth/vault/config")
def vault_config():
    """Public vault status for the Settings panel (R-VC-02, S-VC-02a/b).

    NOT auth-gated: the panel must be reachable before login so fresh
    installs can activate the vault from onboarding/settings (S-VC-02a), and
    an ON vault still exposes only read-only status, never secrets (S-VC-02b).
    """
    return _vault_config()


@app.post("/api/auth/vault/enable")
def vault_enable(payload: VaultEnableRequest):
    """Activate the vault (R-VC-03, S-VC-03a/b/c/d).

    Precondition: vault OFF and either no account (create the account and
    return the words exactly once, S-VC-03a) or an existing account whose
    recovery words verify (ownership proof, S-VC-03b; wrong words -> 400 and
    the flag stays off, S-VC-03c). An already-ON vault is rejected (409,
    S-VC-03d). The persisted ``capabilities.vault.enabled`` flag becomes the
    PRIMARY source; the env override still wins when set (S-VC-01b).
    """
    if _vault_active():
        raise HTTPException(status_code=409, detail="Vault is already enabled")
    registry = _local_state()
    account = account_get_account(registry)
    if account is None:
        username = (payload.username or "").strip()
        if not username:
            raise HTTPException(status_code=422, detail="Username is required")
        words, _ = account_create_account(registry, username, payload.password)
        state = registry.snapshot()
        caps = state.setdefault("capabilities", {})
        caps["vault"] = {
            "enabled": True,
            "reauth_interval_d": int(
                (caps.get("vault") or {}).get(
                    "reauth_interval_d", _DEFAULT_REAUTH_INTERVAL_D)),
        }
        registry.atomic_commit(state)
        registry.atomic_commit(_commit_account_created(registry.snapshot()))
        return {"enabled": True, "words": words}
    if not payload.words:
        raise HTTPException(status_code=400, detail="Recovery words are required")
    if not account_verify_words(
            payload.words, account.get("words_hash"), _words_rate_limiter):
        raise HTTPException(status_code=400, detail="Invalid or rate-limited recovery words")
    state = registry.snapshot()
    caps = state.setdefault("capabilities", {})
    caps["vault"] = {
        "enabled": True,
        "reauth_interval_d": int(
            (caps.get("vault") or {}).get(
                "reauth_interval_d", _DEFAULT_REAUTH_INTERVAL_D)),
    }
    registry.atomic_commit(state)
    return {"enabled": True}


@app.post("/api/auth/vault/disable")
def vault_disable(payload: VaultDisableRequest):
    """Disable the vault (R-VC-04, S-VC-04a/b/c).

    Words are the mandatory ownership proof and verification is rate-limited
    (S-VC-04c); a session alone NEVER suffices (S-VC-04b). Missing or wrong
    words return 400 (S-VC-04b/c). An already-disabled vault returns 409.
    """
    if not _vault_active():
        raise HTTPException(status_code=409, detail="Vault is already disabled")
    account = account_get_account(_local_state())
    if account is None:
        raise HTTPException(status_code=409, detail="No account configured")
    if not payload.words:
        raise HTTPException(status_code=400, detail="Recovery words are required")
    if not account_verify_words(
            payload.words, account.get("words_hash"), _words_rate_limiter):
        raise HTTPException(status_code=400, detail="Invalid or rate-limited recovery words")
    registry = _local_state()
    state = registry.snapshot()
    caps = state.setdefault("capabilities", {})
    caps["vault"] = {
        "enabled": False,
        "reauth_interval_d": int(
            (caps.get("vault") or {}).get(
                "reauth_interval_d", _DEFAULT_REAUTH_INTERVAL_D)),
    }
    registry.atomic_commit(state)
    return {"enabled": False}


@app.post("/api/auth/vault/reauth-interval")
def vault_set_reauth_interval(payload: VaultReauthIntervalRequest):
    """Adjust the soft re-auth countdown interval (R-VC-05, S-VC-05a/b).

    Persists ``capabilities.vault.reauth_interval_d`` (PRIMARY); the
    ``DEMIURGOS_REAUTH_INTERVAL_D`` env override still wins when set
    (S-VC-05b). The response always reports the EFFECTIVE interval.
    """
    if not _vault_active():
        raise HTTPException(status_code=403, detail="Vault is disabled")
    if payload.reauth_interval_d < 1:
        raise HTTPException(status_code=422, detail="reauth_interval_d must be >= 1")
    registry = _local_state()
    state = registry.snapshot()
    vault = state.setdefault("capabilities", {}).setdefault("vault", {})
    vault["reauth_interval_d"] = payload.reauth_interval_d
    registry.atomic_commit(state)
    return {"reauth_interval_d": _reauth_interval_d()}


def _resolve_principal(request=None) -> EditPrincipal | None:
    """Resolve the trusted edit principal for a request.

    Sessions come from the explicit loopback-only local development provider
    (``DEMIURGOS_AUTH_MODE=local-dev``) or from the credentials vault mode
    (``DEMIURGOS_AUTH_MODE=credentials``), whose sessions are NOT loopback-
    bound. Until a valid session exists, every gated write fails closed. This
    function MUST NOT trust caller-supplied identity: request headers and body
    fields are forgeable and are deliberately ignored.
    """
    session = _session_for_request(request)
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


class GuidedConsentRequest(BaseModel):
    """One-shot consent token issued with a musing guided suggestion (REQ-GFC-04)."""

    token: str


# ---------------------------------------------------------------------------
# Methodology library contracts (Taller de Herramientas)
# ---------------------------------------------------------------------------

class AttachmentEntryRequest(BaseModel):
    """One attachment entry wire shape (contract §4, SR4).

    Shape-validated at the boundary; the compiler enforces the count/bytes/
    path limits on publish (R2) — a draft POST with a malformed entry is
    rejected by FastAPI before any library call.
    """

    path: str
    sha256: str
    bytes: int
    nivel: str


class MethodologyDraftRequest(BaseModel):
    skill_id: str
    version: str
    name: str
    source: str
    description: str = ""
    phases: list[str] = []
    language: str | None = None
    # Inventory metadata (REQ-CC-9): optional and backward-compatible — a POST
    # with only the original fields creates a draft with null/empty extended
    # fields. ``create_draft`` already persists every field; the response
    # echoes all of them.
    taller: str | None = None
    categoria_funcional: str | None = None
    etiquetas: list[str] = []
    # Wire doc only (S7): kept in the model so omission/null/[] stay valid,
    # but the route REJECTS any non-null clasificacion or non-empty
    # trust_attributes claim with 400 ``client_trust_claim_not_allowed``.
    # Trust values are server-derived exclusively.
    clasificacion: str | None = None
    trust_attributes: list[str] = []
    # Attachment entries (contract §4, SR4): optional and backward-compatible;
    # the compiler enforces shape/count/bytes on publish (R2).
    adjuntos: list[AttachmentEntryRequest] = []


class MethodologyActivateRequest(BaseModel):
    world: str
    skill_id: str
    version: str
    # The guided-flow slot to pin (SR1); absent/omitted = guided-character.
    flow_type: str = DEFAULT_FLOW_TYPE


class MethodologyRollbackRequest(BaseModel):
    world: str
    # The guided-flow slot to roll back (SR1); absent/omitted = guided-character.
    flow_type: str = DEFAULT_FLOW_TYPE


class MethodologyDeactivateRequest(BaseModel):
    world: str
    # The guided-flow slot to roll back (SR1); absent/omitted = guided-character.
    flow_type: str = DEFAULT_FLOW_TYPE


class NativeChannelRequest(BaseModel):
    enabled: bool


class MethodologyCompanionActivateRequest(BaseModel):
    world: str
    skill_id: str
    version: str


class MethodologyCompanionDeactivateRequest(BaseModel):
    world: str
    skill_id: str


# The provider is capability-admitted and separate from the legacy chat route.
# The durable SQLite store is the default: without ``DEMIURGOS_GUIDED_SESSIONS_DB``
# it resolves to ``<data root>/data/guided-sessions.sqlite3`` (see
# ``default_db_path``), so sessions survive a restart for the 30-day TTL.
# The env var remains an explicit override; ``:memory:`` is only reachable by
# passing it directly. Every session pins the active methodology/version
# snapshot at creation.
# Bound lazily (WU-2): constructing it here would resolve the data root while
# this module is imported, which fails during pytest collection.
_GUIDED_SESSIONS_DB = os.environ.get("DEMIURGOS_GUIDED_SESSIONS_DB")
_GUIDED_SESSIONS: Any = _LazyBinding(
    lambda: DurableGuidedSessionStore(db_path=_GUIDED_SESSIONS_DB)
)
_GUIDED_PROVIDER = None
# Idea-materialization provider seam (AD2): wired to the runs adapter below
# (same pattern as _GUIDED_PROVIDER); declared here so routes/helpers defined
# before the wiring can reference it, and tests replace it after import.
_MATERIALIZE_PROVIDER = None
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
# Serializes first-boot library construction (the lazy-init was previously an
# unguarded ``if None:``; install writes disk, so concurrent inits must not
# race — S4). The seed root is resolved from PROJECT_ROOT AT CALL TIME so the
# API fixtures that monkeypatch PROJECT_ROOT keep their isolation.
_METHODOLOGY_INIT_LOCK = threading.Lock()


def _seed_foundational_skills(library: MethodologyLibrary, seed_root: Path) -> None:
    """Best-effort first-boot reconciliation of repo-bundled foundational seeds.

    Thin bridge to ``install_seeds``: every failure is caught and logged —
    boot must serve WITHOUT the seed rather than 500 every route, so lazy
    init never raises (S2/S3-boot).
    """
    try:
        report = install_seeds(library, seed_root)
        if report.installed or report.conflict:
            logger.info("Foundational seed reconciliation: %s", report)
    except Exception as exc:  # noqa: BLE001 — never break the request path
        logger.warning("Foundational seed install failed: %s", exc)


def _methodology_library() -> MethodologyLibrary:
    global _METHODOLOGY_LIBRARY
    if _METHODOLOGY_LIBRARY is None:
        with _METHODOLOGY_INIT_LOCK:
            if _METHODOLOGY_LIBRARY is None:
                library = MethodologyLibrary(
                    _project_root() / "data" / "methodology" / "library.json"
                )
                _seed_foundational_skills(
                    library,
                    _project_root() / "data" / "methodology" / "seeds",
                )
                _METHODOLOGY_LIBRARY = library
    return _METHODOLOGY_LIBRARY


#: WU-3.0 pre-flight probe gate (REQ-NC-1): ``False`` until the real-Hermes
#: probe has passed against a dedicated TEST profile proving all four — hooks
#: live, ``skills``-on toolset effect, in-process cache-clear, ``skill_manage``
#: veto. A failing or absent probe blocks every enablement path (flag ON,
#: toolset enable, promotion). Inert by default: nothing consumes it yet —
#: WU-3.1/3.2 wire the consumption into ``_materialize_skills``.
_PROBE_PASSED: bool = False


def _probe_passed() -> bool:
    """Native-channel enablement gate (REQ-NC-1 / WU-3.0 pre-flight probe).

    Read-only predicate; the probe evidence that flips ``_PROBE_PASSED`` is
    recorded by the WU-3.2 enablement path. Default ``False`` keeps the system
    on baseline behavior until the probe proves the gateway is ready.
    """
    return _PROBE_PASSED


def _materialize_skills() -> None:
    """Reconcile native skills into staging and record the ``(world, revision)`` epoch.

    Etapa 1 seam (design D6): invoked at startup and on a world switch. It is
    additive and inert — it writes only to the unregistered staging tree and
    records the session epoch; nothing reaches the model-visible prompt or tool
    set. Never raises into boot or a request: any failure (including an
    unreadable library) is logged and the caller proceeds.

    Etapa 3 (WU-3.1, REQ-MM-1/REQ-MM-2): when the world opted into the native
    channel AND the WU-3.0 probe passed, the same seam additionally drives the
    staging→live promotion; a promotion that advances the revision records the
    promoted ``(world, revision)`` epoch (D4), which the run path consumes
    through ``_channel_session_id``. With the flag default OFF nothing
    additional runs and the live folder stays untouched.
    """
    try:
        from skill_materializer import SkillMaterializer, SkillPromoter
        from skill_session_epochs import (
            SessionEpochRegistry,
            resolve_session_store_path,
        )

        project_root = _project_root()
        world = _active_world()
        report = SkillMaterializer(
            _methodology_library(), project_root=project_root
        ).materialize(world)
        if report.ok and report.revision:
            registry = SessionEpochRegistry(resolve_session_store_path(project_root))
            registry.observe(world, report.revision)
            if _native_channel_enabled(world) and _probe_passed():
                promote = SkillPromoter(
                    _methodology_library(), project_root=project_root
                ).promote(world)
                if promote.ok and promote.promoted:
                    registry.observe(world, promote.revision)
                elif not promote.ok:
                    logger.warning(
                        "skill promotion aborted for world %r; live folder untouched",
                        world,
                    )
        elif report.aborted:
            logger.warning("skill materialization aborted: %s", report.issues)
        # Toolset reconcile (REQ-NC-3): ensure ``skills`` presence matches the
        # active channel state. Idempotent; probe-gated inside — with the probe
        # closed (default) nothing enables and the dedicated profile stays
        # byte-identical.
        _sync_native_channel(world)
    except Exception as exc:  # noqa: BLE001 — never crash boot or a request
        logger.warning("skill materialization failed: %s", exc)


def _methodology_quarantine() -> QuarantineStore:
    global _METHODOLOGY_QUARANTINE
    if _METHODOLOGY_QUARANTINE is None:
        _METHODOLOGY_QUARANTINE = QuarantineStore(
            _project_root() / "data" / "methodology" / "quarantine"
        )
    return _METHODOLOGY_QUARANTINE


def _active_methodology_version(world: str, flow_type: str = DEFAULT_FLOW_TYPE) -> str | None:
    """Active methodology version for a world's ``flow_type`` slot.

    A published version explicitly activated for the world/flow wins; otherwise
    the builtin pin applies. Only NEW sessions consult this; existing sessions
    keep their pinned snapshot and fail closed when it no longer matches.
    """
    activation = _methodology_library().active_for(world, flow_type)
    if activation is not None:
        return activation.version
    return _ACTIVE_METHODOLOGY_VERSION


def _active_methodology_snapshot(
    world: str, flow_type: str = DEFAULT_FLOW_TYPE,
) -> MethodologySnapshot:
    """Pin the currently active methodology/version at session creation."""
    activation = _methodology_library().active_for(world, flow_type)
    if activation is not None:
        return MethodologySnapshot(
            skill_id=activation.skill_id,
            skill_version=activation.version,
            compiled_contract_digest=activation.digest,
            flow_type=flow_type,
        )
    if flow_type != GUIDED_CHARACTER_FLOW:
        # The builtin contract only exists for the guided-character flow;
        # other flow slots have no activation-based fallback (SR1).
        return MethodologySnapshot(flow_type=flow_type)
    active = _ACTIVE_METHODOLOGY_VERSION or _BUILTIN_METHODOLOGY_VERSION
    return MethodologySnapshot(
        skill_id="guided-character-v1",
        skill_version=active,
        compiled_contract_digest=None,
        flow_type=flow_type,
    )


def _compiled_contract_markdown(
    world: str, flow_type: str = DEFAULT_FLOW_TYPE,
) -> str | None:
    """Resolve the world's active compiled methodology as bounded Markdown.

    Walks activation → published version → ``project_contract_markdown`` and
    returns ``None`` for the builtin case (no activation) or on any resolution
    failure, so callers fall back to the legacy version-string injection.
    When the active channel is NOT ``legacy`` (native or fail-closed
    unhealthy), the legacy projection is suppressed — early ``None`` (REQ-NC-4
    path d / REQ-GF-1): the native ``SKILL.md`` is the only guide, or, when
    unhealthy, no guidance at all (never a silent legacy fallback, D2).
    """
    if _active_channel_state() != "legacy":
        return None
    try:
        activation = _methodology_library().active_for(world, flow_type)
        if activation is None:
            return None
        published = _methodology_library().get_published(activation.skill_id, activation.version)
        if published is None:
            return None
        return project_contract_markdown(published)
    except Exception:
        logger.warning("compiled contract projection failed for world %r", world, exc_info=True)
        return None


def _convergence_specimen_markdown(
    world: str, flow_type: str, state: SessionState | None,
) -> str | None:
    """Resolve the world's convergence specimen as bounded Markdown (R10–R13).

    Trigger conjuncts (all must hold, D2/D5): the recovered state exists, the
    candidate is minimally complete pre-invocation (``delta=None`` — the gate
    is evaluated BEFORE this turn's provider run, never after), and at least
    one finished exchange exists (D3). The published skill's ``adjuntos`` pins
    then drive the block. Builtin worlds (no activation), zero-attachment
    records, and every resolution failure resolve to ``None`` so the turn
    proceeds byte-identically — fail-open, mirroring :1914. When the active
    channel is NOT ``legacy`` the specimen is suppressed — early ``None``
    (REQ-NC-4 path d / REQ-GF-1): with the native channel healthy the native
    body drives the turn; unhealthy is fail-closed zero guidance (D2).
    """
    if _active_channel_state() != "legacy":
        return None
    try:
        if state is None:
            return None
        if not candidate_minimum_complete(state.candidate, delta=None, mode=state.mode):
            return None
        if not has_finished_exchange(state):
            return None
        activation = _methodology_library().active_for(world, flow_type)
        if activation is None:
            return None
        published = _methodology_library().get_published(activation.skill_id, activation.version)
        if published is None or not published.adjuntos:
            return None
        nivel = resolve_candidate_nivel(state.candidate)
        return build_specimen_block(
            carrier_root_for(published.skill_id, project_root=_project_root()),
            published.adjuntos,
            nivel,
        )
    except Exception:
        logger.warning("convergence specimen resolution failed for world %r", world, exc_info=True)
        return None


def _native_skill_body(world: str) -> str | None:
    """Resolve the native ``SKILL.md`` body that drives the guided continuation.

    REQ-GN-1/REQ-GF-1: when the active channel is ``native``, the guided
    continuation is driven by the method body exactly as the renderer composes
    it — ``published.source`` plus the co-creation rules block (the
    ``skill_renderer`` body seam at ``skill_renderer.py:318``, design §6
    verify-only). The builtin pin has no published record and resolves to
    ``None``, mirroring the legacy builtin case where the provider keeps the
    version-string methodology. Self-gated on the channel state so the
    flag-OFF path (legacy projection keeps its seam) and the fail-closed
    ``unhealthy`` state (zero guidance, D2) both stay byte-identical. Never
    raises; any read failure degrades to ``None``.
    """
    if _active_channel_state() != "native":
        return None
    try:
        from skill_renderer import CO_CREATION_RULES_BLOCK

        library = _methodology_library()
        activation = library.active_for(world, GUIDED_CHARACTER_FLOW)
        if activation is None:
            return None
        published = library.get_published(activation.skill_id, activation.version)
        if published is None:
            return None
        source = published.source or ""
        return source.rstrip() + "\n\n" + CO_CREATION_RULES_BLOCK
    except Exception:
        logger.warning("native skill body resolution failed for world %r", world, exc_info=True)
        return None
# Semantic routing seam: the mandatory Hermes-first semantic gate. Wired to a
# SemanticIntentProvider(ACTIVITY_ADAPTER) below, after the runs adapter exists.
# No lexical/plain-chat fallback exists; unavailable/invalid/exhausted Hermes
# results fail closed as ``blocked`` with localized safe copy. The type is kept
# Optional because tests replace the seam with fakes.
_SEMANTIC_PROVIDER: SemanticIntentProvider | None = None
# Conversation memory + skill routing singletons for the non-guided assistant
# path. Declared Optional here and initialized after the runs adapter exists so
# tests can replace the seams with fakes (same pattern as _SEMANTIC_PROVIDER).
_CONVERSATION_MEMORY: Any = None
_SKILL_ROUTER: SkillRouter | None = None
# Bound lazily (WU-2) for the same reason as _GUIDED_SESSIONS: building the
# coordinator here would capture the data root while this module is imported.
_GUIDED_REINDEX: Any = _LazyBinding(
    lambda: ReindexCoordinator(_mundos_dir(), lambda world: _get_graph(world))
)
_GUIDED_INDEX_REQUESTS: dict[str, tuple[str, str, str]] = {}
# Review records are diskless until the existing confirmed create route succeeds.
_GUIDED_PENDING_PROPOSALS: dict[str, dict[str, str | int]] = {}

# Materialize preview store (AD3): pending idea-materialization proposals keyed
# by ``proposal_id = f"materialize-{uuid.uuid4().hex}"``. Diskless until the
# existing confirmed create route succeeds; TTL mirrors the confirmation store
# (``_CONFIRM_TTL_SECONDS``, :3839) so the proposal and its token expire
# together. Record shape: {proposal_id, principal_id, world, section, folder,
# slug, target, content, digest, operation_id, created_at, expires_at}.
_MATERIALIZE_PENDING_PROPOSALS: dict[str, dict] = {}
_MATERIALIZE_TTL_SECONDS = 600

# Graph-indexed sections a materialize preview may target (mirrors
# ``graph_indexer._SCAN_SECTIONS``, graph_indexer.py:56). ``media`` is NOT
# ficha-eligible and is rejected (R-IM-01).
_MATERIALIZE_SECTIONS: frozenset[str] = frozenset({"lore", "personajes", "referencias"})


def _prune_materialize_proposals() -> None:
    """Drop expired materialize proposals (mirror ``_prune_expired_confirmations``)."""
    now = datetime.now(timezone.utc)
    for key in [k for k, r in _MATERIALIZE_PENDING_PROPOSALS.items() if r["expires_at"] <= now]:
        _MATERIALIZE_PENDING_PROPOSALS.pop(key, None)


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
    flow_type = snapshot.flow_type or DEFAULT_FLOW_TYPE
    active = _active_methodology_version(state.world, flow_type)
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
    # Compiled contract projection (fricción 2): resolved here so every guided
    # continuation path carries the world's active methodology as bounded
    # Markdown into the provider invoke. The projection is per-flow: it follows
    # the session's own pinned flow slot (SR1). Builtin worlds (no activation)
    # resolve to None and the provider falls back to the version-string
    # methodology.
    session_snapshot = state.methodology_snapshot if state is not None else None
    session_flow = (
        session_snapshot.flow_type or DEFAULT_FLOW_TYPE
        if session_snapshot is not None else DEFAULT_FLOW_TYPE
    )
    compiled = _compiled_contract_markdown(mundo, session_flow)
    # Convergence specimen (④b, R10–R13): resolved pre-invocation beside the
    # compiled contract. All trigger conjuncts are evaluated against the
    # RECOVERED state (delta=None), so turn one and fast-mode turn one can
    # never inject; gate-passed turns inject ≤1 pinned carrier block.
    specimen = _convergence_specimen_markdown(mundo, session_flow, state)
    # Single-channel cut (REQ-GN-4 / REQ-GF-1): with the flag ON the guided
    # continuation is driven by the native ``SKILL.md`` body instead of the
    # legacy projection — the legacy compiled contract and the convergence
    # specimen are suppressed (path d, REQ-NC-4). ``_native_skill_body``
    # self-gates on the channel state, so the flag-OFF builtin case (contract
    # also ``None``) and the fail-closed ``unhealthy`` state (zero guidance,
    # D2) both stay byte-identical.
    if compiled is None:
        compiled = _native_skill_body(mundo)
    # Shared choke point for every guided continuation. Sessions opened by the
    # semantic chat path never called the REST start route, so the module-level
    # cache was never probed: passing it straight through sent None into
    # invoke_bounded and the first real turn failed closed with
    # CAPABILITY_UNAVAILABLE (503). Probe here; the helper short-circuits when
    # already populated and returns None on probe failure (fail closed).
    capabilities = await _probe_guided_capabilities()
    response, state = await continue_session(
        _GUIDED_SESSIONS, _GUIDED_PROVIDER, request, capabilities,
        compiled_contract_markdown=compiled,
        convergence_specimen_markdown=specimen,
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
        methodology_snapshot=_active_methodology_snapshot(mundo, GUIDED_CHARACTER_FLOW),
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


@app.post("/api/{mundo}/guided-character/consent/accept")
async def accept_guided_character_consent(
    mundo: str, body: GuidedConsentRequest, request: Request,
):
    """Consume a musing consent token and open the deferred guided flow.

    The click IS the imperative (REQ-GFC-05): the token-bound continuation is
    replayed through the SAME guarded machinery as an explicit imperative, with
    NO second Hermes run and WITHOUT ``route_new_character_intent``. A
    malformed, missing, expired, replayed, foreign-principal, or foreign-world
    token fails closed with zero session and zero write (REQ-GFC-07).
    """
    principal, error = _guided_principal(request)
    if error:
        return error
    if _resolve_mundo_dir(mundo) is None:
        return _guided_error_response(StructuredError(
            ErrorCode.INVALID_INPUT, "The world is unavailable.", False,
        ))
    record = _consume_guided_consent_token(
        body.token, principal_id=principal.id, mundo=mundo,
    )
    if record is None:
        return _guided_error_response(StructuredError(
            ErrorCode.INVALID_INPUT, "The consent request is invalid.", False,
        ))
    decision = record.get("decision")
    if not isinstance(decision, SemanticDecision) or decision.continuation is None:
        return _guided_error_response(StructuredError(
            ErrorCode.INVALID_INPUT, "The consent request is invalid.", False,
        ))
    ask_body = AskRequest(
        prompt=str(record.get("prompt") or ""),
        session_id=str(record.get("session_id") or ""),
    )
    result = SemanticResult(
        decision=decision,
        attempts=int(record.get("attempts") or 0),
        request_id=decision.request_id,
        session_id=decision.session_id,
    )
    return await _open_guided_continuation(
        mundo, ask_body, result, principal, decision=decision,
        reference_context=str(record.get("reference_context") or ""),
        reference_name=record.get("reference_name") or None,
    )


@app.post("/api/{mundo}/guided-character/consent/decline")
def decline_guided_character_consent(
    mundo: str, body: GuidedConsentRequest, request: Request,
):
    """Consume/discard a consent token and persist a durable decline (REQ-GFC-06).

    A malformed, missing, expired, replayed, foreign-principal, or foreign-world
    token fails closed with zero write (REQ-GFC-07).
    """
    principal, error = _guided_principal(request)
    if error:
        return error
    record = _consume_guided_consent_token(
        body.token, principal_id=principal.id, mundo=mundo,
    )
    if record is None:
        return _guided_error_response(StructuredError(
            ErrorCode.INVALID_INPUT, "The consent request is invalid.", False,
        ))
    if _CONVERSATION_MEMORY is not None:
        try:
            _CONVERSATION_MEMORY.record_guided_consent_decline(
                str(record.get("session_id") or ""), mundo,
            )
        except Exception:
            logger.warning("guided consent decline persist failed", exc_info=True)
    return {"consent": "declined"}


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
# Co-creation route contracts (Fase 4 — Skill Madre co-creation)
#
# Hermes boundary (REQ-CC-7) at the API layer: every route validates the
# session envelope, rejects authority-key content (flat+nested, depth <= 4 —
# enforced by the protocol/provider layers), fails closed on malformed or
# unavailable Hermes output with zero mutations, and NEVER mutates canonical
# methodology state without explicit Author approval. ``materialize`` only
# creates a library DRAFT; ``publish`` and ``activate`` are the ONLY routes
# that mutate canonical methodology state, and the POST itself is the
# Author's explicit approval signal — no other route ever auto-publishes.
# ---------------------------------------------------------------------------

class CoCreationStartRequest(BaseModel):
    author_input: str
    world: str | None = None


class CoCreationTurnRequest(BaseModel):
    base_revision: int
    author_input: str


class CoCreationPublishRequest(BaseModel):
    base_revision: int


class TriggerApproveRequest(BaseModel):
    """Etapa 2: explicit Author approval of a draft's trigger.

    The server normalizes and re-validates the bound; the request is transport
    only (the client value is never trusted as authoritative).
    """

    description: str


class CoCreationTriggerApproveRequest(BaseModel):
    """Etapa 2: revision-guarded Author approval on a co-creation session.

    The approved value is written into the session canvas
    (``draft_payload["description"]``) and, when the session has a materialized
    draft, recorded on that library draft.
    """

    base_revision: int
    description: str


class CoCreationAdjunto(BaseModel):
    """One Author exemplar pin on the materialize request (REQ-CC-25).

    Same dir-independent shape the staging upload returns: ``path`` is a plain
    ``.md`` basename under the final skill dir, ``sha256``/``bytes`` pin the
    bytes, and ``nivel`` is the bounded narrative-density label.
    """

    path: str
    sha256: str
    bytes: int
    nivel: str


class CoCreationMaterializeRequest(BaseModel):
    base_revision: int
    skill_id: str | None = None
    version: str | None = None
    name: str | None = None
    description: str | None = None
    taller: str | None = None
    categoria_funcional: str | None = None
    etiquetas: list[str] = []
    language: str | None = None
    # REQ-CC-25: Author exemplar pins. ``None`` leaves the session's canvas
    # pins untouched; a list folds the confirmed pins into the draft payload so
    # materialize moves the staged bytes and persists them on the draft.
    adjuntos: list[CoCreationAdjunto] | None = None


class CoCreationActivateRequest(BaseModel):
    base_revision: int
    world: str


class CoCreationCanvasRequest(BaseModel):
    """TW12 canvas autosave: revision-guarded typed payload merge.

    The two envelope keys (``base_revision``/``payload``) are the ONLY canvas
    extension and stay OUTSIDE the 8-key AUTHORITY_KEYS set (REQ-CC-23).
    """

    base_revision: int
    payload: dict[str, Any]


class CoCreationValidateRequest(BaseModel):
    """TW12 pure validation preview: render + compile, NO state mutation."""

    payload: dict[str, Any]


class CoCreationHistoryRestoreRequest(BaseModel):
    """TW12 revision-guarded snapshot restore (REQ-CC-15)."""

    base_revision: int
    revision: int


class CoCreationWarningStatusRequest(BaseModel):
    """TW12 Author-only warning transition (REQ-CC-13)."""

    base_revision: int
    state: str


class CoCreationPendingQuestionStatusRequest(BaseModel):
    """TW12 Author-only pending-question transition (REQ-CC-14)."""

    base_revision: int
    state: str


class CoCreationDeriveRequest(BaseModel):
    """TW13 adaptation: derive a draft from a PUBLISHED skill (REQ-CC-16/20).

    The client supplies ONLY the identity of the original
    (``skill_id``/``version``/``world``). Provenance is never accepted here:
    any client-supplied ``derived_from`` is ignored and the server injects
    its own identity read from the PUBLISHED record (REQ-CC-20).
    """

    skill_id: str
    version: str
    world: str | None = None


# Durable session store + Skill Madre provider seams (mirror the
# _GUIDED_SESSIONS / _GUIDED_PROVIDER pattern). Tests replace these module
# seams after import; the default store path is ``<data root>/data/``
# (``DEMIURGOS_CO_CREATION_SESSIONS_DB`` overrides it). Bound lazily (WU-2).
_CO_CREATION_SESSIONS_DB = os.environ.get("DEMIURGOS_CO_CREATION_SESSIONS_DB")
_CO_CREATION_SESSIONS: Any = _LazyBinding(
    lambda: CoCreationSessionStore(db_path=_CO_CREATION_SESSIONS_DB)
)
_CO_CREATION_PROVIDER: HermesCoCreationProvider | None = None
_CO_CREATION_CAPABILITIES: CoCreationCapabilities | None = None
_CO_CREATION_PROBE_LOCK = asyncio.Lock()
_CO_CREATION_MATERIALIZER: CoCreationMaterializer | None = None
# In-process hint mapping session_id -> creating principal. The durable store
# remains the authoritative session state; this map only lets the API
# distinguish a KNOWN session under a foreign principal (403) from an
# unknown/expired session (404) — both satisfy REQ-CC-10's 403/404 binding
# contract. A restart clears it, and foreign access after a restart degrades
# to 404 (still within the contract).
_CO_CREATION_SESSION_PRINCIPALS: dict[str, str] = {}

_CO_CREATION_ERROR_STATUS = {
    CoCreationErrorCode.INVALID_INPUT: 422,
    CoCreationErrorCode.UNAUTHORIZED: 403,
    CoCreationErrorCode.REVISION_CONFLICT: 409,
    CoCreationErrorCode.CEILING_REACHED: 422,
    CoCreationErrorCode.CAPABILITY_UNAVAILABLE: 503,
    CoCreationErrorCode.PROVIDER_UNAVAILABLE: 503,
    CoCreationErrorCode.TIMEOUT: 504,
    CoCreationErrorCode.CANCELLED: 499,
    CoCreationErrorCode.MALFORMED_OUTPUT: 502,
    CoCreationErrorCode.INVALID_ENVELOPE: 422,
    CoCreationErrorCode.INTERNAL: 500,
}


def _co_creation_error_response(error: CoCreationStructuredError) -> JSONResponse:
    return JSONResponse(
        status_code=_CO_CREATION_ERROR_STATUS.get(error.code, 500),
        content={"detail": error.message, **error.as_dict()},
    )


def _co_creation_missing_session_response() -> JSONResponse:
    """404 for unknown/expired sessions (REQ-CC-10 TTL contract)."""
    return JSONResponse(status_code=404, content={
        "detail": "The co-creation session is unavailable.",
        "code": "unauthorized",
        "message": "The co-creation session is unavailable.",
        "retryable": False,
    })


def _co_creation_principal(request: Request) -> tuple[EditPrincipal | None, JSONResponse | None]:
    principal = _resolve_principal(request)
    if principal is None:
        # 401 for a missing trusted principal (mirrors every other gated
        # route); 403 is reserved for a KNOWN session under a foreign
        # principal (see _co_creation_session_or_error).
        return None, JSONResponse(status_code=401, content={
            "detail": "Authentication required.",
            "code": "unauthorized",
            "message": "Authentication required.",
            "retryable": False,
        })
    return principal, None


def _co_creation_session_or_error(
    session_id: str, principal: EditPrincipal,
) -> tuple[CoCreationSessionState | None, JSONResponse | None]:
    """Recover a principal-bound session; 403 for foreign principals, 404 otherwise."""
    state = _CO_CREATION_SESSIONS.recover(session_id, principal.id)
    if state is not None:
        return state, None
    creator = _CO_CREATION_SESSION_PRINCIPALS.get(session_id)
    if creator is not None and creator != principal.id:
        return None, _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.UNAUTHORIZED, "The co-creation session is unavailable.", False,
        ))
    return None, _co_creation_missing_session_response()


def _trigger_approval_dict(approval: TriggerApproval | None) -> dict | None:
    """Serialize a trigger approval for the wire (``None`` stays ``null``)."""
    if approval is None:
        return None
    return {
        "text": approval.text,
        "digest": approval.digest,
        "approved_by": approval.approved_by,
        "approved_at": approval.approved_at,
    }


def _draft_trigger_approval(draft_id: str | None) -> TriggerApproval | None:
    """Read a draft's recorded approval once at the API layer.

    The public-state serializer stays pure; call sites that know the
    materialized draft inject this value instead of reaching into the library
    from the serializer.
    """
    if draft_id is None:
        return None
    draft = _methodology_library().get_draft(draft_id)
    return draft.trigger_approval if draft is not None else None


def _normalized_trigger_or_error(
    description: str,
) -> tuple[str | None, JSONResponse | None]:
    """Normalize a trigger and validate the server-authoritative bound.

    Mirrors ``MethodologyLibrary.approve_trigger`` so the session approve route
    can refuse an empty/over-bound value with 422 BEFORE mutating any state,
    independent of whether a library draft exists yet.
    """
    normalized = normalize_trigger(description)
    if not normalized or len(normalized) > TRIGGER_INTAKE_LIMIT:
        return None, JSONResponse(status_code=422, content={
            "detail": "trigger must be non-empty and at most "
                      f"{TRIGGER_INTAKE_LIMIT} characters after normalization",
            "code": "trigger_invalid",
        })
    return normalized, None


def _co_creation_public_state(
    state: CoCreationSessionState, *, trigger_approval: TriggerApproval | None = None,
) -> dict:
    """Serialize the frontend-compatible session view (TW12 canvas included).

    Exposes the editable draft payload, the 3-state warnings list, the
    autosave history count, and the server-injected provenance (``None`` until
    a derived draft exists — Phase 2). ``trigger_approval`` (Etapa 2) is
    injected by the API layer from the materialized draft; the serializer
    itself stays pure.
    """
    return {
        "protocol_version": CO_CREATION_PROTOCOL_VERSION,
        "session_id": state.session_id,
        "principal_id": state.principal_id,
        "world": state.world,
        "revision": state.revision,
        "milestone": state.milestone,
        "progress": [
            {"name": item.name, "state": item.state} for item in state.milestone_states
        ],
        "question_count": state.question_count,
        "pending_question": state.pending_question,
        "pending_options": list(state.pending_options),
        "messages": [
            {"role": item.role, "content": item.content} for item in state.messages
        ],
        "phase": state.phase,
        "draft_id": state.draft_id,
        "compile_issues": None,
        "draft_payload": state.draft_payload,
        "warnings": [warning.as_dict() for warning in state.warnings],
        "history_count": len(state.draft_history),
        "derived_from": (
            {"skill_id": state.derived_from.skill_id, "version": state.derived_from.version}
            if state.derived_from is not None else None
        ),
        "trigger_approval": _trigger_approval_dict(trigger_approval),
    }


def _co_creation_result(
    response, state: CoCreationSessionState | None,
):
    if response.error:
        return _co_creation_error_response(response.error)
    if state is None:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
        ))
    return _co_creation_public_state(
        state, trigger_approval=_draft_trigger_approval(state.draft_id),
    )


async def _probe_co_creation_capabilities() -> CoCreationCapabilities | None:
    """Probe Hermes once; concurrent requests share the fail-closed result."""
    global _CO_CREATION_CAPABILITIES
    if _CO_CREATION_CAPABILITIES is not None:
        return _CO_CREATION_CAPABILITIES
    async with _CO_CREATION_PROBE_LOCK:
        if _CO_CREATION_CAPABILITIES is not None:
            return _CO_CREATION_CAPABILITIES
        provider = _CO_CREATION_PROVIDER
        probe = getattr(provider, "probe", None)
        if not callable(probe):
            return None
        try:
            assessment = await probe()
            _CO_CREATION_CAPABILITIES = co_creation_capabilities(assessment)
        except Exception:
            logger.warning("co-creation capability probe failed", exc_info=True)
            _CO_CREATION_CAPABILITIES = None
        return _CO_CREATION_CAPABILITIES


async def _co_creation_continue(
    session_id: str, base_revision: int, author_input: str,
    principal: EditPrincipal, world: str | None = None, milestone: str | None = None,
):
    """One bounded Hermes turn through the protocol seam (fail-closed).

    The protocol re-checks the session, the revision, the question ceiling
    (BEFORE any Hermes call), and the envelope boundary; every violation
    fails closed with zero session mutation.
    """
    if _CO_CREATION_PROVIDER is None:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.CAPABILITY_UNAVAILABLE,
            "Skill co-creation is unavailable.", True,
        ))
    capabilities = await _probe_co_creation_capabilities()
    if capabilities is None or not capabilities.admitted():
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.CAPABILITY_UNAVAILABLE,
            "Skill co-creation is unavailable.", True,
        ))
    request = CoCreationRequest(
        CO_CREATION_PROTOCOL_VERSION,
        f"co-creation-{uuid.uuid4().hex}",
        session_id,
        principal.id,
        base_revision,
        principal.id,
        author_input,
        world=world,
        milestone=milestone,
    )
    response, state = await continue_co_creation_session(
        _CO_CREATION_SESSIONS, _CO_CREATION_PROVIDER, request, capabilities,
    )
    return _co_creation_result(response, state)


@app.post("/api/co-creation/sessions")
async def start_co_creation(body: CoCreationStartRequest, request: Request):
    """Start a principal-bound Skill Madre co-creation session.

    Mirrors the guided start route: capability-admitted Hermes first, then the
    session is created and the FIRST turn runs immediately (the Author's input
    seeds the Skill Madre). A world-scoped session binds to that world; a
    transversal session (world omitted) binds to none. Only the session store
    is touched here — no canonical methodology mutation.
    """
    principal, error = _co_creation_principal(request)
    if error:
        return error
    if body.world is not None and _resolve_mundo_dir(body.world) is None:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.INVALID_INPUT, "The world is unavailable.", False,
        ))
    if _CO_CREATION_PROVIDER is None:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.CAPABILITY_UNAVAILABLE,
            "Skill co-creation is unavailable.", True,
        ))
    capabilities = await _probe_co_creation_capabilities()
    if capabilities is None or not capabilities.admitted():
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.CAPABILITY_UNAVAILABLE,
            "Skill co-creation is unavailable.", True,
        ))
    session_id = f"co-creation-{uuid.uuid4().hex}"
    _CO_CREATION_SESSIONS.create(
        session_id, principal.id, principal.id,
        world=body.world, author_input=body.author_input,
    )
    _CO_CREATION_SESSION_PRINCIPALS[session_id] = principal.id
    return await _co_creation_continue(
        session_id, 0, body.author_input, principal,
        world=body.world, milestone="proposito",
    )


@app.post("/api/co-creation/sessions/{session_id}/turn")
async def continue_co_creation(session_id: str, body: CoCreationTurnRequest, request: Request):
    """One Author answer -> one Skill Madre question (REQ-CC-3)."""
    principal, error = _co_creation_principal(request)
    if error:
        return error
    state, error = _co_creation_session_or_error(session_id, principal)
    if error:
        return error
    if state.revision != body.base_revision:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
        ))
    return await _co_creation_continue(
        session_id, body.base_revision, body.author_input, principal,
        world=state.world, milestone=state.milestone,
    )


@app.get("/api/co-creation/sessions/{session_id}")
def recover_co_creation(session_id: str, request: Request):
    """Recover a principal-bound session (REQ-CC-10)."""
    principal, error = _co_creation_principal(request)
    if error:
        return error
    state, error = _co_creation_session_or_error(session_id, principal)
    if error:
        return error
    return _co_creation_public_state(
        state, trigger_approval=_draft_trigger_approval(state.draft_id),
    )


@app.get("/api/co-creation/sessions/{session_id}/progress")
def co_creation_progress(session_id: str, request: Request):
    """Milestone progress projection (REQ-CC-3)."""
    principal, error = _co_creation_principal(request)
    if error:
        return error
    state, error = _co_creation_session_or_error(session_id, principal)
    if error:
        return error
    return {
        "session_id": state.session_id,
        "world": state.world,
        "milestone": state.milestone,
        "progress": [
            {"name": item.name, "state": item.state} for item in state.milestone_states
        ],
        "phase": state.phase,
        "question_count": state.question_count,
        "draft_id": state.draft_id,
    }


@app.post("/api/co-creation/sessions/{session_id}/materialize")
def materialize_co_creation(session_id: str, body: CoCreationMaterializeRequest, request: Request):
    """Author confirms ``borrador_listo`` -> deterministic draft materialization.

    REQ-CC-5 / REQ-CC-7: reads the accumulated structured answers from the
    session's ``draft_payload_json``, folds the Author-confirmed metadata in
    via ``merge_draft_payload``, then calls ``CoCreationMaterializer.materialize``
    (create_draft + compile_draft). Compiler issues surface in the response and
    the session STAYS at ``borrador_listo`` for correction. Success records the
    draft id (``record_draft``) and advances the phase to ``review``
    (``set_phase``). This route NEVER publishes.
    """
    principal, error = _co_creation_principal(request)
    if error:
        return error
    state, error = _co_creation_session_or_error(session_id, principal)
    if error:
        return error
    if state.revision != body.base_revision:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
        ))
    if state.phase == "complete":
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.INVALID_INPUT, "The co-creation session is complete.", False,
        ))
    if state.milestone != "borrador_listo":
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.INVALID_INPUT,
            "Materialization requires the borrador listo milestone.", False,
        ))
    materializer = _CO_CREATION_MATERIALIZER
    if materializer is None:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.CAPABILITY_UNAVAILABLE,
            "Skill draft materialization is unavailable.", True,
        ))
    payload = dict(state.draft_payload)
    # Fold the Author-confirmed metadata into the session payload (revision-
    # guarded) so the review view renders exactly what was materialized.
    confirmed = {
        key: value
        for key, value in {
            "name": body.name, "description": body.description,
            "taller": body.taller, "categoria_funcional": body.categoria_funcional,
            "etiquetas": body.etiquetas, "language": body.language,
            "skill_id": body.skill_id, "version": body.version,
        }.items()
        if value not in (None, [], "")
    }
    if body.adjuntos is not None:
        # REQ-CC-25: the Author-confirmed pins ride into the session payload so
        # materialize persists them on the draft (never silently dropped).
        confirmed["adjuntos"] = [entry.model_dump() for entry in body.adjuntos]
    if confirmed:
        merged = _CO_CREATION_SESSIONS.merge_draft_payload(
            session_id, principal.id, body.base_revision, confirmed,
        )
        if merged is None:
            return _co_creation_error_response(CoCreationStructuredError(
                CoCreationErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
            ))
        payload.update(confirmed)
        base_revision = merged.revision
    else:
        base_revision = body.base_revision
    try:
        result = materializer.materialize(
            payload,
            skill_id=body.skill_id or f"co-created-{session_id.removeprefix('co-creation-')[:10]}",
            version=body.version or "0.1.0",
            name=body.name or payload.get("name") or "Co-created skill",
            description=body.description or payload.get("description") or "",
            taller=body.taller or payload.get("taller"),
            etiquetas=tuple(body.etiquetas or payload.get("etiquetas") or ()),
            categoria_funcional=body.categoria_funcional or payload.get("categoria_funcional"),
            language=body.language or payload.get("language"),
            staging_dir=staging_dir_for(_project_root(), session_id),
            attachments_root=_project_root() / ATTACHMENTS_SUBDIR,
        )
    except AttachmentMaterializationError as exc:
        # A missing/drifted staged carrier fails closed: no draft, no partial
        # ``attachments/`` tree (the move already rolled back). ``None`` pins
        # keep the legacy behavior for payloads without exemplars.
        return _attachment_upload_error_response(exc)
    issues = [issue.to_dict() for issue in result.issues]
    if not result.ok:
        # REQ-CC-5: issues surface in the validation panel; the session stays
        # at ``borrador_listo`` so the Author can correct before retrying.
        return {
            "draft_id": result.draft_id,
            "ok": False,
            "issues": issues,
            "compile_issues": issues,
            "phase": state.phase,
            "milestone": state.milestone,
            "revision": base_revision,
        }
    recorded = _CO_CREATION_SESSIONS.record_draft(
        session_id, principal.id, base_revision, result.draft_id,
    )
    if recorded is None:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
        ))
    reviewed = _CO_CREATION_SESSIONS.set_phase(
        session_id, principal.id, recorded.revision, "review",
    )
    if reviewed is None:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
        ))
    payload = _co_creation_public_state(
        reviewed, trigger_approval=_draft_trigger_approval(reviewed.draft_id),
    )
    payload.update({"ok": True, "issues": [], "compile_issues": []})
    return payload


@app.post("/api/co-creation/sessions/{session_id}/publish")
def publish_co_creation(session_id: str, body: CoCreationPublishRequest, request: Request):
    """Author approval -> publish the materialized draft (REQ-CC-6).

    The POST itself IS the Author's explicit approval signal; nothing else in
    the subsystem calls ``publish``. Reuses ``MethodologyLibrary.publish`` so
    publishing is immutable: re-publishing changed content raises
    ``AlreadyPublishedError`` -> 409. On success the session completes.
    """
    principal, error = _co_creation_principal(request)
    if error:
        return error
    state, error = _co_creation_session_or_error(session_id, principal)
    if error:
        return error
    if state.revision != body.base_revision:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
        ))
    if state.draft_id is None:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.INVALID_INPUT,
            "The session has no materialized draft to publish.", False,
        ))
    library = _methodology_library()
    draft = library.get_draft(state.draft_id)
    if draft is None:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.INVALID_INPUT, "The session draft is unavailable.", False,
        ))
    # TW12/TW13: sync the session's final canvas payload into the library
    # draft through the SAME deterministic template used at materialization
    # (post-materialize edit path — ``update_draft`` re-renders + recompiles;
    # ``_draft_history`` snapshots the pre-publish state). Only payloads that
    # carry structured editable content are synced: a metadata-only payload
    # (e.g. an adaptation seed of a non-template original) leaves the draft's
    # seeded source untouched so the original content is never clobbered.
    # Provenance (parent fields) is never touched by this sync (REQ-CC-20).
    materializer = _CO_CREATION_MATERIALIZER
    if materializer is not None and state.draft_payload:
        structured = {
            key: state.draft_payload.get(key)
            for key in ("purpose", "scope", "main_flow", "branches", "rules")
            if state.draft_payload.get(key)
        }
        if structured:
            rendered = materializer.render_source(state.draft_payload)
            if rendered != draft.source:
                updates: dict[str, Any] = {"source": rendered}
                for key in ("name", "description"):
                    value = state.draft_payload.get(key)
                    if isinstance(value, str) and value:
                        updates[key] = value
                library.update_draft(state.draft_id, **updates)
    # DP-2/EP-3: sync the canvas ``adjuntos`` OUTSIDE the structured/source
    # gate — an exemplar-only edit leaves ``source`` unchanged. Presence-keyed:
    # an absent key leaves the draft's pins untouched. EP-4/EP-6: only pins not
    # yet verifiable are moved (after the guards); a failed update rolls back.
    if state.draft_payload and "adjuntos" in state.draft_payload:
        entries = _payload_adjuntos(state.draft_payload)
        try:
            moved = move_publish_pins(
                entries,
                skill_id=draft.skill_id,
                staging_dir=staging_dir_for(_project_root(), session_id),
                attachments_root=_project_root() / ATTACHMENTS_SUBDIR,
                project_root=_project_root(),
            )
        except AttachmentMaterializationError as exc:
            return _attachment_upload_error_response(exc)
        try:
            library.update_draft(state.draft_id, adjuntos=entries)
        except Exception:
            _rollback_moved(
                moved, _project_root() / ATTACHMENTS_SUBDIR / draft.skill_id,
            )
            raise
    try:
        published = library.publish(state.draft_id)
    except AttachmentLimitError as exc:
        # EP-7/R2: an adjuntos overflow is 422 ``attachment_limit_reached``
        # BEFORE the generic ValidationError handler (same mapping as the
        # generic draft publish route).
        return JSONResponse(status_code=422, content={
            "detail": str(exc), "code": "attachment_limit_reached",
        })
    except ValidationError as exc:
        return JSONResponse(status_code=422, content={
            "detail": str(exc), "code": "validation_error",
        })
    except AlreadyPublishedError as exc:
        return JSONResponse(status_code=409, content={
            "detail": str(exc), "code": "already_published",
        })
    except TriggerNotApprovedError as exc:
        # Etapa 2 (TD-D): this route has no generic MethodologyLibraryError
        # handler, so without this catch the gate refusal would leak as a 500.
        # The session stays incomplete and the draft remains approvable.
        return JSONResponse(status_code=409, content={
            "detail": str(exc), "code": "trigger_not_approved",
        })
    completed = _CO_CREATION_SESSIONS.set_phase(
        session_id, principal.id, body.base_revision, "complete",
    )
    return {
        "session_id": session_id,
        "phase": completed.phase if completed is not None else state.phase,
        "revision": completed.revision if completed is not None else state.revision,
        "published": {
            "skill_id": published.skill_id,
            "version": published.version,
            "name": published.name,
            "description": published.description,
            "digest": published.digest,
            "published_at": published.published_at,
        },
    }


@app.post("/api/co-creation/sessions/{session_id}/trigger/approve")
def approve_co_creation_trigger(
    session_id: str, body: CoCreationTriggerApproveRequest, request: Request,
):
    """Record the Author's explicit approval of the session draft's trigger (Etapa 2).

    Writes the normalized approved value into the session canvas
    (``draft_payload["description"]``) through the revision-guarded autosave and,
    when the session has a materialized draft, records the approval on that
    library draft in one atomic save (TD-B) — so the approved value equals the
    value publish will use. The bound is validated server-side BEFORE any state
    mutation.
    """
    principal, error = _co_creation_principal(request)
    if error:
        return error
    state, error = _co_creation_session_or_error(session_id, principal)
    if error:
        return error
    if state.revision != body.base_revision:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
        ))
    normalized, invalid = _normalized_trigger_or_error(body.description)
    if invalid is not None:
        return invalid
    merged = _CO_CREATION_SESSIONS.autosave_payload(
        session_id, principal.id, body.base_revision,
        {"description": normalized}, source="author",
    )
    if merged is None:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
        ))
    approval: TriggerApproval | None = None
    if merged.draft_id is not None:
        library = _methodology_library()
        try:
            approval = library.approve_trigger(merged.draft_id, normalized, principal.id)
        except KeyError:
            return JSONResponse(status_code=404, content={
                "detail": "The session draft is unavailable.",
                "code": "draft_unavailable",
            })
        except TriggerInvalidError as exc:
            return JSONResponse(status_code=422, content={
                "detail": str(exc), "code": "trigger_invalid",
            })
    return {
        "trigger_approval": _trigger_approval_dict(approval),
        "revision": merged.revision,
    }


@app.post("/api/co-creation/sessions/{session_id}/activate")
def activate_co_creation(session_id: str, body: CoCreationActivateRequest, request: Request):
    """Author approval -> activate the published version for a world (REQ-CC-6).

    Reuses ``MethodologyLibrary.activate`` (one active version per world; a
    new activation deactivates the previous). Activation requires a PUBLISHED
    version — the Author must publish first; this route never auto-publishes.
    """
    principal, error = _co_creation_principal(request)
    if error:
        return error
    state, error = _co_creation_session_or_error(session_id, principal)
    if error:
        return error
    if state.revision != body.base_revision:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
        ))
    if _resolve_mundo_dir(body.world) is None:
        return JSONResponse(status_code=404, content={"detail": "Mundo no encontrado"})
    if state.draft_id is None:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.INVALID_INPUT,
            "The session has no materialized draft to activate.", False,
        ))
    library = _methodology_library()
    draft = library.get_draft(state.draft_id)
    if draft is None:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.INVALID_INPUT, "The session draft is unavailable.", False,
        ))
    try:
        activation = library.activate(body.world, draft.skill_id, draft.version)
    except NotPublishedError as exc:
        return JSONResponse(status_code=422, content={
            "detail": str(exc), "code": "not_published",
        })
    return {
        "session_id": session_id,
        "phase": state.phase,
        "revision": state.revision,
        "activation": {
            "world": activation.world,
            "skill_id": activation.skill_id,
            "version": activation.version,
            "digest": activation.digest,
            "activated_at": activation.activated_at,
            "flow_type": activation.flow_type,
        },
    }


@app.post("/api/co-creation/derive")
def derive_co_creation(body: CoCreationDeriveRequest, request: Request):
    """TW13 adaptation: derive a draft from a PUBLISHED skill (REQ-CC-16/20).

    The server reads the PUBLISHED record (``get_published``) — the client
    never supplies provenance — injects ``parent_skill_id``/``parent_version``
    (server-side identity), seeds the derived draft's source from the
    original, and auto-versions it ``parent_version+1`` (REQ-CC-19). A
    ``clasificacion=\"Oficiales\"`` original REQUIRES derivation (REQ-CC-16):
    this route IS that path — published versions stay immutable, so an
    in-place edit is impossible by construction. Non-protected skills MAY be
    derived here too. Opens a co-creation session bound to the derived draft
    with the server-injected provenance and a canvas payload seeded from the
    original (REQ-CC-17). The original stays intact until the derived draft
    explicitly publishes AND activates.
    """
    principal, error = _co_creation_principal(request)
    if error:
        return error
    if body.world is not None and _resolve_mundo_dir(body.world) is None:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.INVALID_INPUT, "The world is unavailable.", False,
        ))
    library = _methodology_library()
    original = library.get_published(body.skill_id, body.version)
    if original is None:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.INVALID_INPUT,
            "The published skill is unavailable.", False,
        ))
    materializer = _CO_CREATION_MATERIALIZER
    if materializer is None:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.CAPABILITY_UNAVAILABLE,
            "Skill draft derivation is unavailable.", True,
        ))
    try:
        draft_id = library.create_derived_draft(
            original.skill_id,
            original.version,
            seed_source=original.source,
            name=original.name,
            description=original.description,
            phases=original.phases,
            language=original.language,
            taller=original.taller,
            talleres_compatibles=original.talleres_compatibles,
            categoria_funcional=original.categoria_funcional,
            etiquetas=original.etiquetas,
            clasificacion=original.clasificacion,
            trust_attributes=original.trust_attributes,
        )
    except NotPublishedError as exc:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.INVALID_INPUT, str(exc), False,
        ))
    except ValidationError as exc:
        return JSONResponse(status_code=422, content={
            "detail": str(exc), "code": "validation_error",
        })
    # Seed the adaptation session's canvas payload from the published
    # original and bind the derived draft + server-injected provenance.
    seed = materializer.seed_payload(
        original.source,
        name=original.name,
        description=original.description,
        world=body.world,
        # DP-1/EP-1: thread the parent's pins into the seeded canvas so the
        # derived session shows the same exemplars as the published original.
        adjuntos=original.adjuntos,
    )
    payload, derived_from = materializer.inject_derived_from(
        seed, original.skill_id, original.version,
    )
    session_id = f"co-creation-{uuid.uuid4().hex}"
    _CO_CREATION_SESSIONS.create(
        session_id, principal.id, principal.id,
        world=body.world,
        seed_payload=payload,
        draft_id=draft_id,
        derived_from=derived_from,
    )
    _CO_CREATION_SESSION_PRINCIPALS[session_id] = principal.id
    return {
        "session_id": session_id,
        "draft_id": draft_id,
        "derived_from": {
            "skill_id": derived_from.skill_id,
            "version": derived_from.version,
        },
    }


# ---------------------------------------------------------------------------
# TW12 canvas data layer routes (Phase 1 / PR 1) — editable structured draft
#
# REQ-CC-7 boundary preserved: canvas edits are Author-originated content that
# flow through the SAME deterministic template + compiler used at
# materialization (``validate_payload`` = render + compile, NO draft created).
# Publish/activate remain the ONLY canonical-mutation routes; the canvas PUT
# only mutates the session's draft payload under the revision guard. The
# envelope extension keys (``base_revision``/``payload``) stay OUTSIDE the
# 8-key AUTHORITY_KEYS set (REQ-CC-23).
# ---------------------------------------------------------------------------


def _co_creation_payload_error_response(payload_issues: list[str]) -> JSONResponse:
    """Map canvas payload shape violations to typed API errors (REQ-CC-11).

    Authority keys (flat or nested) are an envelope violation and fail closed
    with ``INVALID_ENVELOPE`` and zero state changes; any other shape violation
    is an ``INVALID_INPUT``.
    """
    if any("authority" in issue for issue in payload_issues):
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.INVALID_ENVELOPE,
            "Authority keys are not allowed in a canvas payload.", False,
        ))
    return _co_creation_error_response(CoCreationStructuredError(
        CoCreationErrorCode.INVALID_INPUT,
        "; ".join(payload_issues), False,
    ))


@app.put("/api/co-creation/sessions/{session_id}/canvas")
def update_co_creation_canvas(session_id: str, body: CoCreationCanvasRequest, request: Request):
    """Debounced Author canvas autosave (TW12 / REQ-CC-11).

    Merges the typed canvas payload under the session's current revision — the
    same guarded merge path chat turns use (bidirectional sync, one authority
    boundary) — then validates the rendered source through the compiler
    WITHOUT creating a library draft. Warnings reconcile keep-or-append:
    pending warnings never auto-clear (REQ-CC-13).
    """
    principal, error = _co_creation_principal(request)
    if error:
        return error
    state, error = _co_creation_session_or_error(session_id, principal)
    if error:
        return error
    if state.revision != body.base_revision:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
        ))
    payload_issues = canvas_payload_issues(body.payload)
    if payload_issues:
        return _co_creation_payload_error_response(payload_issues)
    materializer = _CO_CREATION_MATERIALIZER
    if materializer is None:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.CAPABILITY_UNAVAILABLE,
            "Skill draft validation is unavailable.", True,
        ))
    validated = materializer.validate_payload(body.payload)
    merged = _CO_CREATION_SESSIONS.autosave_payload(
        session_id, principal.id, body.base_revision, body.payload,
        source="autosave", issues=validated.issues,
    )
    if merged is None:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
        ))
    return {
        "revision": merged.revision,
        "issues": [issue.to_dict() for issue in validated.issues],
        "warnings": [warning.as_dict() for warning in merged.warnings],
        "ok": validated.ok,
    }


@app.post("/api/co-creation/sessions/{session_id}/validate")
def validate_co_creation(session_id: str, body: CoCreationValidateRequest, request: Request):
    """Pure validation preview (TW12): render + compile, NO state mutation.

    Returns the compiler issues, a fresh Pendiente warning projection, and the
    rendered source preview. The session revision, payload, and history are
    untouched — nothing is created or published.
    """
    principal, error = _co_creation_principal(request)
    if error:
        return error
    state, error = _co_creation_session_or_error(session_id, principal)
    if error:
        return error
    payload_issues = canvas_payload_issues(body.payload)
    if payload_issues:
        return _co_creation_payload_error_response(payload_issues)
    materializer = _CO_CREATION_MATERIALIZER
    if materializer is None:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.CAPABILITY_UNAVAILABLE,
            "Skill draft validation is unavailable.", True,
        ))
    validated = materializer.validate_payload(body.payload)
    return {
        "issues": [issue.to_dict() for issue in validated.issues],
        "warnings": [
            {
                "code": issue.code, "message": issue.message,
                "field": issue.field, "state": "pendiente",
            }
            for issue in validated.issues
        ],
        "source_preview": validated.source,
        "ok": validated.ok,
    }


@app.get("/api/co-creation/sessions/{session_id}/history")
def co_creation_history(session_id: str, request: Request):
    """Immutable autosave snapshot list (REQ-CC-15).

    Payloads are excluded from the list view; the restore route returns the
    chosen snapshot's payload.
    """
    principal, error = _co_creation_principal(request)
    if error:
        return error
    state, error = _co_creation_session_or_error(session_id, principal)
    if error:
        return error
    entries = _CO_CREATION_SESSIONS.list_history(session_id, principal.id)
    if entries is None:
        return _co_creation_missing_session_response()
    return {"entries": [
        {"revision": entry.revision, "source": entry.source, "ts": entry.ts}
        for entry in entries
    ]}


@app.post("/api/co-creation/sessions/{session_id}/history/restore")
def restore_co_creation(session_id: str, body: CoCreationHistoryRestoreRequest, request: Request):
    """Revision-guarded snapshot restore (REQ-CC-15).

    The session's current revision must match ``base_revision`` and the target
    snapshot must exist; otherwise the restore fails closed with zero
    mutations.
    """
    principal, error = _co_creation_principal(request)
    if error:
        return error
    state, error = _co_creation_session_or_error(session_id, principal)
    if error:
        return error
    if state.revision != body.base_revision:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
        ))
    restored = _CO_CREATION_SESSIONS.restore_payload(
        session_id, principal.id, body.base_revision, body.revision,
    )
    if restored is None:
        current = _CO_CREATION_SESSIONS.recover(session_id, principal.id)
        if current is None or current.revision != body.base_revision:
            return _co_creation_error_response(CoCreationStructuredError(
                CoCreationErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
            ))
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.INVALID_INPUT,
            "The requested history snapshot is unavailable.", False,
        ))
    return {"revision": restored.revision, "payload": restored.draft_payload}


@app.post("/api/co-creation/sessions/{session_id}/warnings/{idx}/status")
def co_creation_warning_status(
    session_id: str, idx: int, body: CoCreationWarningStatusRequest, request: Request,
):
    """Author-only warning transition (REQ-CC-13).

    Only ``Pendiente -> Resuelta | Aceptada_por_Autor`` is allowed; pending
    warnings never auto-correct and validation never touches a warning's state.
    """
    principal, error = _co_creation_principal(request)
    if error:
        return error
    state, error = _co_creation_session_or_error(session_id, principal)
    if error:
        return error
    if state.revision != body.base_revision:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
        ))
    updated = _CO_CREATION_SESSIONS.set_warning_status(
        session_id, principal.id, body.base_revision, idx, body.state,
    )
    if updated is None:
        current = _CO_CREATION_SESSIONS.recover(session_id, principal.id)
        if current is None or current.revision != body.base_revision:
            return _co_creation_error_response(CoCreationStructuredError(
                CoCreationErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
            ))
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.INVALID_INPUT,
            "The warning transition is not allowed.", False,
        ))
    return {"warnings": [warning.as_dict() for warning in updated.warnings]}


@app.post("/api/co-creation/sessions/{session_id}/pending-questions/{idx}/status")
def co_creation_pending_question_status(
    session_id: str, idx: int, body: CoCreationPendingQuestionStatusRequest, request: Request,
):
    """Author-only pending-question transition (REQ-CC-14).

    Entries are chat-appended and read-only on the canvas; the Author may only
    transition ``Pendiente -> Resuelta | Aceptada_por_Autor``.
    """
    principal, error = _co_creation_principal(request)
    if error:
        return error
    state, error = _co_creation_session_or_error(session_id, principal)
    if error:
        return error
    if state.revision != body.base_revision:
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
        ))
    updated = _CO_CREATION_SESSIONS.set_pending_question_status(
        session_id, principal.id, body.base_revision, idx, body.state,
    )
    if updated is None:
        current = _CO_CREATION_SESSIONS.recover(session_id, principal.id)
        if current is None or current.revision != body.base_revision:
            return _co_creation_error_response(CoCreationStructuredError(
                CoCreationErrorCode.REVISION_CONFLICT, "The session revision is stale.", True,
            ))
        return _co_creation_error_response(CoCreationStructuredError(
            CoCreationErrorCode.INVALID_INPUT,
            "The pending-question transition is not allowed.", False,
        ))
    return {"pending_questions": updated.draft_payload.get("pending_questions", [])}


def _attachment_upload_error_response(
    error: AttachmentUploadError | AttachmentMaterializationError,
) -> JSONResponse:
    """Structured error for a rejected exemplar upload or materialize move
    (stable wire code)."""
    return JSONResponse(status_code=error.status, content={
        "detail": error.message,
        "code": error.code,
        "message": error.message,
        "retryable": False,
    })


@app.post("/api/co-creation/sessions/{session_id}/adjuntos")
async def upload_co_creation_adjunto(
    session_id: str,
    request: Request,
    file: UploadFile = File(...),
    nivel: str = Form(...),
):
    """Stage ONE exemplar for a principal-owned session (AE-1).

    Multipart ``file`` + ``nivel``. Guards run in order — principal (401),
    session ownership (403/404), then the staging guards 3–8 — and every check
    happens BEFORE the first write, so a rejection mutates nothing. ``sha256``
    and ``bytes`` are always computed server-side (client values are never
    trusted); the response carries the pin ``{path, sha256, bytes, nivel}``
    with ``path`` as the basename under the final skill dir. Bytes stay in the
    per-session staging dir; only materialize moves them.
    """
    principal, error = _co_creation_principal(request)
    if error:
        return error
    state, error = _co_creation_session_or_error(session_id, principal)
    if error:
        return error
    data = await file.read()
    staging_dir = staging_dir_for(_project_root(), state.session_id)
    try:
        basename = validate_staged_upload(staging_dir, file.filename or "", data, nivel)
    except AttachmentUploadError as exc:
        return _attachment_upload_error_response(exc)
    store_staged(staging_dir, basename, data)
    return {"adjunto": {
        "path": basename,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "nivel": nivel,
    }}


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
    Directories are always listed, including empty ones, so the optional
    OC8 lore skeleton folders ("carpetas vacías") remain visible after
    world creation instead of being pruned.
    """
    if section not in VALID_SECTIONS:
        return []
    mundo_dir = _resolve_mundo_dir(mundo)
    if mundo_dir is None:
        return []
    section_dir = mundo_dir / section
    if not section_dir.is_dir():
        return []

    # Read the section's import-order manifest once per request. With no
    # manifest every node is unlisted and the sort degenerates to the
    # historical dirs-first, case-insensitive alphabetical order.
    order = read_order(section_dir)
    order_index = {path: i for i, path in enumerate(order)}
    # The manifest lists FILE paths only (e.g. "a/b.md"), never bare folders.
    # Give every directory the manifest index of its FIRST listed descendant
    # so a folder sorts at the position of the document that created it
    # instead of dropping into the unlisted (alphabetical) bucket. Empty or
    # unlisted folders have no entry here and keep the len(order) fallback.
    dir_index: dict[str, int] = {}
    for path, i in order_index.items():
        parts = path.split("/")
        for depth in range(1, len(parts)):
            dir_index.setdefault("/".join(parts[:depth]), i)

    def _build_tree(dir_path: Path, base: Path) -> list[dict]:
        items = []
        try:
            # Siblings sort by (manifest index, is_file, name.lower()):
            # listed nodes keep their import order, unlisted ones sort after
            # them (index = len(order)), folders before files within the same
            # index group, then case-insensitive alphabetical fallback.
            # Files use their own manifest entry; directories use the index
            # of their first listed descendant (dir_index).
            def _index_of(entry: Path) -> int:
                rel = str(entry.relative_to(base)).replace("\\", "/")
                return order_index.get(rel, dir_index.get(rel, len(order)))

            entries = sorted(
                (
                    e for e in dir_path.iterdir()
                    if not e.name.startswith(".") and not e.name.startswith("_")
                ),
                key=lambda e: (
                    _index_of(e),
                    0 if e.is_dir() else 1,
                    e.name.lower(),
                ),
            )
            for entry in entries:
                if not entry.is_dir():
                    continue
                rel = entry.relative_to(base)
                children = _build_tree(entry, base)
                # Include directories even when empty so the recommended OC8
                # lore skeleton (empty folders) — and any folder created for a
                # future file — is visible in the section tree instead of being
                # pruned into invisibility right after creation.
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
    mundos_root = _mundos_dir().resolve()
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
        raise problem("world.not_found")
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
    # Materialize proposals live in a SEPARATE store (AD3); the two branches
    # are mutually exclusive. Both pin the request world to the world the
    # proposal was generated for.
    materialize_pending = None if pending is not None else _MATERIALIZE_PENDING_PROPOSALS.get(body.get("edit_id"))
    if pending is not None:
        principal = _resolve_principal(request)
        target = f"{section}/{path}"
        digest = hashlib.sha256(body.get("content", "").encode("utf-8")).hexdigest()
        # The guided record does not carry the world directly, but its session
        # is the authority on the world the proposal was generated for. Recover
        # it and pin the confirm to that world — mirroring the serialize route's
        # ``state.world != mundo`` guard. Fail closed when it cannot be resolved
        # so a removed/expired session can never widen the write to another
        # world. This guard runs before any copy or write below.
        guided_session = (
            _GUIDED_SESSIONS.recover(str(pending["session_id"]), principal.id)
            if principal is not None else None
        )
        if (principal is None or guided_session is None
                or guided_session.world != mundo
                or pending["principal_id"] != principal.id
                or pending["target"] != target or pending["content"] != body.get("content")
                or pending["digest"] != digest or body.get("proposed_digest") != digest):
            raise HTTPException(status_code=409, detail="Guided proposal is stale or altered")
    elif materialize_pending is not None:
        principal = _resolve_principal(request)
        target = f"{section}/{path}"
        digest = hashlib.sha256(body.get("content", "").encode("utf-8")).hexdigest()
        if (principal is None or materialize_pending["world"] != mundo
                or materialize_pending["principal_id"] != principal.id
                or materialize_pending["target"] != target
                or materialize_pending["content"] != body.get("content")
                or materialize_pending["digest"] != digest
                or body.get("proposed_digest") != digest):
            raise HTTPException(status_code=409, detail="Materialize proposal is stale or altered")
        # CI-1: copy the idea image BEFORE the first canon write. Any failure
        # (destination race, missing source, copy error) fails closed with 409
        # and nothing is written; the proposal is not consumed.
        _copy_materialize_image(materialize_pending, mundo)
    result = _write_content(mundo, section, path, body, request, kind="new")
    if materialize_pending is not None:
        full = _resolve_mundo_path(mundo, f"{section}/{path}")
        if full is None or not full.is_file() or _digest_of(full) != materialize_pending["digest"]:
            raise HTTPException(status_code=500, detail="Persisted materialize content failed digest verification")
        operation_id = str(materialize_pending.get("operation_id") or f"materialize-create-{body['edit_id']}")
        result = dict(result)
        reconciliation = _GUIDED_REINDEX.reconcile(
            operation_id=operation_id, mundo=mundo,
            target=str(materialize_pending["target"]), content_digest=str(materialize_pending["digest"]),
        )
        result.update({"index_status": reconciliation.index_status, "retryable": reconciliation.retryable,
                       "message": reconciliation.message})
        # R-CG-04: on confirm the idea MUST accumulate the world slug in
        # used_in[] (deduped) and transition to status: used. This happens
        # only AFTER the ficha is durable and reconciled, and the metadata
        # update is best-effort: a failure (idea deleted in the race window,
        # disk error) must never corrupt or roll back the written ficha, so
        # it is logged and the confirm still succeeds. canon_rel is NOT
        # passed: the new ficha already carries based_on: ideas/{slug} from
        # the server-owned skeleton, and re-rendering it through the bank
        # would drift its bytes from the reconciled digest.
        try:
            IdeasBank().materialize(str(materialize_pending["slug"]), mundo)
        except Exception as exc:  # noqa: BLE001 — best-effort metadata after durable write
            logger.warning(
                "materialize-confirm: failed to mark idea %s used in world %s: %s",
                materialize_pending["slug"], mundo, exc,
            )
        # Single use: the proposal is consumed on the first confirmed write.
        _MATERIALIZE_PENDING_PROPOSALS.pop(body["edit_id"], None)
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
        raise problem("world.not_found")
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
        raise problem("world.not_found")
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
        # Keep the import-order manifest consistent with the deletion
        # (no-op when the path is not listed or no manifest exists).
        remove_from_order(mundo_dir / section, path.replace("\\", "/"))
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
        raise problem("world.not_found")
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
        raise problem("world.not_found")
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
        raise problem("world.not_found")

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
        raise problem("world.not_found")

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
_RE_FM_RELACIONES_HEADER = re.compile(
    r"^(?P<indent>[ \t]*)relaciones:[ \t]*(?P<rest>[^\r\n]*)(?P<term>\r?\n|$)"
)
_RE_FM_RELACIONES_ITEM = re.compile(
    r"^(?P<indent>[ \t]*)-(?P<body>[ \t]*[^\r\n]*)(?P<term>\r?\n|$)"
)
_RE_FM_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")


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


class RelationConflict(ValueError):
    """Raised when a create targets an existing relation or a break a missing one."""


def _validate_fm_yaml(inner: str) -> None:
    """Raise ValueError when the frontmatter block is not valid YAML.

    Safety net for the relaciones rewrite: the block is validated before AND
    after the line edit so a malformed frontmatter is never touched and the
    rewrite can never corrupt one.
    """
    try:
        yaml.safe_load(inner)
    except yaml.YAMLError:
        raise ValueError("Frontmatter YAML inválido") from None


def _relaciones_entry_key(raw: str) -> str:
    """Normalize one ``relaciones:`` entry to its dedupe key.

    The key is the inner wikilink text for ``[[Name]]`` entries or the bare
    (quote/bracket-stripped) scalar otherwise — matching the graph indexer's
    canonical-id resolution so duplicate detection works across both forms.
    """
    raw = raw.strip().strip('"').strip("'").strip()
    m = _RE_FM_WIKILINK.search(raw)
    if m:
        return m.group(1).strip()
    return raw.strip("[]").strip()


def _set_frontmatter_relaciones(content: str, action: str, target_id: str) -> str:
    """Add or remove a canonical-id entry from the frontmatter ``relaciones:`` list.

    Follows the _set_frontmatter_status pattern: CRLF-safe and byte-preserving
    for everything else. ``create`` appends ``  - <target_id>`` to the
    ``relaciones:`` block, inserts the whole block before the closing ``---``
    when the field is absent, or prepends a leading frontmatter block when the
    file has none. ``break`` removes only the matching entry and drops the
    now-empty ``relaciones:`` block. Both frontmatter states are YAML-validated
    before and after. Raises RelationConflict when create targets an existing
    relation or break a missing one.
    """
    if action not in ("create", "break"):
        raise ValueError(f"Acción inválida: {action!r}")
    m = _RE_FRONTMATTER.match(content)
    if m is None:
        if action == "break":
            raise RelationConflict("La relación no existe")
        return f"---\nrelaciones:\n  - {target_id}\n---\n{content}"

    inner = m.group(1)
    eol = "\r\n" if "\r\n" in inner else "\n"
    _validate_fm_yaml(inner)  # never rewrite a broken frontmatter block

    lines = inner.splitlines(keepends=True)
    rel_idx = next(
        (i for i, line in enumerate(lines) if _RE_FM_RELACIONES_HEADER.match(line)),
        None,
    )
    if rel_idx is None:
        if action == "break":
            raise RelationConflict("La relación no existe")
        updated_inner = inner + f"relaciones:{eol}  - {target_id}{eol}"
        _validate_fm_yaml(updated_inner)
        return content[: m.start(1)] + updated_inner + content[m.end(1):]

    # Collect existing entries: flow-form residue on the header line plus the
    # block-form ``- item`` lines that follow (until the next key, a blank
    # line, or the end of the frontmatter block).
    keys: list[str] = []
    header_line = lines[rel_idx]
    rest = header_line.split(":", 1)[1].strip()
    if rest:
        for part in rest.split(","):
            key = _relaciones_entry_key(part)
            if key and key not in keys:
                keys.append(key)
    item_matches: list[re.Match] = []
    section_end = rel_idx + 1
    while section_end < len(lines):
        item = _RE_FM_RELACIONES_ITEM.match(lines[section_end])
        if item is None:
            break
        item_matches.append(item)
        key = _relaciones_entry_key(item.group("body"))
        if key and key not in keys:
            keys.append(key)
        section_end += 1

    if action == "create":
        if target_id in keys:
            raise RelationConflict("La relación ya existe")
        if rest:
            # Flow form: normalize to the importer's ``  - item`` block layout
            # so the section stays homogeneous YAML.
            new_lines = (
                [f"relaciones:{eol}"]
                + [f"  - {k}{eol}" for k in keys]
                + [f"  - {target_id}{eol}"]
            )
        else:
            new_lines = [header_line, *lines[rel_idx + 1:section_end], f"  - {target_id}{eol}"]
    else:
        if target_id not in keys:
            raise RelationConflict("La relación no existe")
        if rest:
            remaining = [k for k in keys if k != target_id]
            new_lines = (
                [f"relaciones:{eol}"] + [f"  - {k}{eol}" for k in remaining]
                if remaining
                else []
            )
        else:
            kept = [
                item.group(0)
                for item in item_matches
                if _relaciones_entry_key(item.group("body")) != target_id
            ]
            new_lines = [header_line, *kept] if kept else []

    updated_inner = "".join(lines[:rel_idx] + new_lines + lines[section_end:])
    _validate_fm_yaml(updated_inner)
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
        raise problem("world.not_found")
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

        idx = EntityGraphIndex(_mundos_dir())
        count = idx.build(mundo)
        logger.info("Graph built for '%s': %d entities", mundo, count)
        _graph_indices[mundo] = idx

    return _graph_indices[mundo]


@app.post("/api/worlds/{world_id}/relationships/reconcile")
def relationships_reconcile(world_id: str):
    """Manually run the inter-document relationship post-process for a world.

    Uses the world's cached graph index (lazy-built on first request) and the
    synchronous Hermes bridge. The post-process is additive and idempotent:
    re-running skips existing relationships, so ``relationships_written`` is 0
    on a no-op re-call. ``run_post_process`` is fail-open (never raises);
    a missing world returns 404.
    """
    if _resolve_mundo_dir(world_id) is None:
        raise problem("world.not_found")
    idx = _get_graph(world_id)
    if idx is None:
        raise problem("world.not_found")
    from wiki.inter_doc_relationships import run_post_process  # type: ignore[import-untyped]

    result = run_post_process(world_id, idx, _sync_hermes_enricher)
    return {
        "status": "ok",
        "pairs_evaluated": result.pairs_evaluated,
        "relationships_written": result.relationships_written,
    }


class _GuidedGraphReader:
    """Expose the canonical graph index through the diskless guided seam."""

    def __init__(self, index: "EntityGraphIndex") -> None:
        self._index = index

    def search(self, query: str) -> list[dict]:
        return [vars(hit) for hit in self._index.search(query)]

    def entities(self) -> list[dict]:
        """Enumerate ALL indexed entities (index cache insertion order).

        Prefers the real index ``entities()`` seam (R-IM-03/06 grounding);
        falls back to the legacy ``search("*")`` + ``read(path)`` walk for
        index seams (test fakes) that predate the method. Read-only; the
        returned dicts are copies.
        """
        enumerate_all = getattr(self._index, "entities", None)
        if callable(enumerate_all):
            return list(enumerate_all())
        entities: list[dict] = []
        for hit in self.search("*"):
            path = hit.get("path") if isinstance(hit, dict) else None
            if not isinstance(path, str) or not path:
                continue
            entity = self.read(path)
            if entity is not None:
                entities.append(entity)
        return entities

    def read(self, entity_path: str) -> dict | None:
        entity = self._index.get_entity(entity_path)
        return vars(entity) if entity is not None else None

    def links(self, entity_path: str, kind: str) -> list[dict]:
        return self._index.get_links(entity_path, kind)

    def neighbors(self, entity_path: str) -> list[dict]:
        """One-hop graph neighbourhood: forward links + backlinks, deduped.

        Grounding expands each seed one hop so the entities the idea is
        *related to* reach the model too (the Chaae defect: the region linked
        to Pannj, but neither was advertised). Uses the index's PUBLIC
        ``get_links`` surface for both directions; each raw link record
        carries only ``{name,type,path}``, so it is resolved to the full
        entity mapping (the same shape ``entities()``/``read()`` return)
        because candidates need the canonical ``id`` and ``description``.
        Dead/unresolved links (``path`` None) are skipped.
        """
        result: list[dict] = []
        seen: set[str] = set()
        for kind in ("forward", "backlinks"):
            for link in self._index.get_links(entity_path, kind):
                path = link.get("path") if isinstance(link, dict) else None
                if not isinstance(path, str) or not path or path in seen:
                    continue
                seen.add(path)
                entity = self.read(path)
                if entity is not None:
                    result.append(entity)
        return result

    def hubs(self) -> list[dict]:
        """The world's most connected entities, as full entity mappings.

        Only consulted when a search matched nothing at all (blind map). The
        index's PUBLIC ``get_links(None, "hubs")`` branch delegates to the
        private ``EntityGraphIndex._get_hubs`` helper; each raw record is
        resolved to its full mapping so the fallback can build candidates.
        """
        result: list[dict] = []
        for link in self._index.get_links(None, "hubs"):
            path = link.get("path") if isinstance(link, dict) else None
            if not isinstance(path, str) or not path:
                continue
            entity = self.read(path)
            if entity is not None:
                result.append(entity)
        return result


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


@app.get("/api/{mundo}/graph/entities")
def graph_entities(
    mundo: str,
    status: str = Query(default="all", description="Filter: all|draft|stable"),
):
    """Bulk entities + links for graph consumption (BLOQUE 4).

    Returns ``{ entities: [...], links: [...] }``.
    Each entity: id, name, type, path, status, description, tags,
    forward_links, backlinks, content, relaciones. Each link: ``{source,
    target}`` node keys —
    the entity id when present, falling back to the entity path so legacy
    entities (empty id) still emit edges GraphView can match (id || path).
    ``status`` filter: "all" (default) returns every entity; "draft"|"stable"
    filter on ``entity.status``. Invalid status -> 422. Unknown mundo ->
    ``{ entities: [], links: [] }`` (same soft-empty contract as
    /graph/search). Referencias fichas ARE indexed (importer-inter-document-relationships
    added "referencias" to _SCAN_SECTIONS).
    """
    if status not in {"all", "draft", "stable"}:
        raise HTTPException(
            status_code=422,
            detail=f"Estado inválido: '{status}'. Válidos: all, draft, stable",
        )
    idx = _get_graph(mundo)
    if idx is None:
        return {"entities": [], "links": []}

    with idx._lock:
        entities = idx._cache.get("entities", {})
        entity_list: list[dict] = []
        link_list: list[dict] = []
        for ent in sorted(entities.values(), key=lambda e: e.get("path", "")):
            ent_status = ent.get("status", "draft")
            if status != "all" and ent_status != status:
                continue
            entity_list.append(
                {
                    "id": ent.get("id", ""),
                    "name": ent["name"],
                    "type": ent["type"],
                    "path": ent["path"],
                    "status": ent_status,
                    "description": ent.get("description", ""),
                    "tags": ent.get("tags", []),
                    "forward_links": ent.get("forward_links", []),
                    "backlinks": ent.get("backlinks", []),
                    "content": ent.get("content", ""),
                    "relaciones": ent.get("relaciones", []),
                }
            )
            for link_name in ent.get("forward_links", []):
                target_path = idx._resolve_link(link_name)
                if target_path and target_path in entities:
                    target = entities[target_path]
                    # Edges to/from hidden nodes are removed too (spec S2.5).
                    if status == "all" or target.get("status", "draft") == status:
                        # Legacy entities without a canonical id emit their
                        # path so source/target always reference a node key
                        # GraphView matches (nodeKey = id || path). Fixes
                        # WARNING 1 (relaciones-canon-panel, BLOQUE 4 Slice A):
                        # legacy worlds rendered with zero edges.
                        link_list.append(
                            {
                                "source": ent.get("id") or ent["path"],
                                "target": target.get("id") or target["path"],
                            }
                        )

    return {"entities": entity_list, "links": link_list}


@app.post("/api/{mundo}/graph/relation")
def set_graph_relation(mundo: str, body: dict):
    """Create or break a graph connection by rewriting the source ficha's
    frontmatter ``relaciones:`` list (create/break a canonical-id entry).

    Writes are anchored by the target entity's canonical id and follow the
    set_file_status pattern: read the source ficha, rewrite ONLY the
    ``relaciones:`` block (CRLF-safe, YAML-validated), write back, and
    invalidate the graph cache so the next read rebuilds it (the watcher
    auto-reindexes the changed file). Errors: 400 invalid action / missing
    fields / path traversal, 404 mundo / source entity / target entity not
    found, 409 duplicate relation (create) or missing relation (break).
    """
    action = body.get("action")
    if action not in ("create", "break"):
        raise HTTPException(status_code=400, detail="Acción inválida: 'create' o 'break'")
    source_path = body.get("source_path")
    if not isinstance(source_path, str) or not source_path.strip():
        raise HTTPException(status_code=400, detail="Se requiere el campo 'source_path'")
    target_id = body.get("target_id")
    if not isinstance(target_id, str) or not target_id.strip():
        raise HTTPException(status_code=400, detail="Se requiere el campo 'target_id'")

    mundo_dir = _resolve_mundo_dir(mundo)
    if mundo_dir is None:
        raise problem("world.not_found")
    idx = _get_graph(mundo)
    if idx is None:
        raise problem("world.not_found")

    full = _resolve_mundo_path(mundo, source_path)
    if full is None:
        raise HTTPException(status_code=400, detail="Path traversal detectado")
    with idx._lock:
        entities = idx._cache.get("entities", {})
        rel_source = str(full.relative_to(mundo_dir)).replace("\\", "/")
        if entities.get(rel_source) is None:
            raise HTTPException(status_code=404, detail="Entidad origen no encontrada")
        if not any(ent.get("id") == target_id for ent in entities.values()):
            raise HTTPException(status_code=404, detail="Entidad destino no encontrada")

    try:
        # newline="" keeps \r\n byte-exact on Windows (Path.read_text would
        # normalize them through universal newlines).
        with open(full, "r", encoding="utf-8", newline="") as fh:
            content = fh.read()
        updated = _set_frontmatter_relaciones(content, action, target_id)
        with open(full, "w", encoding="utf-8", newline="") as fh:
            fh.write(updated)
    except RelationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error al actualizar relaciones: {exc}") from exc

    _graph_indices.pop(mundo, None)
    return {"success": True, "path": rel_source, "action": action, "target_id": target_id}


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
    mundo_base = _mundos_dir() / mundo
    return [
        mundo_base / "wiki" / "media",
        mundo_base / "referencias" / "visuales" / "imagenes",
    ]


def _resolve_media_path(mundo: str, path: str) -> Path | None:
    """Resolve a media file path with path-traversal protection.

    Accepts *path* in three formats:
      1. Relative to *mundo* root:   ``wiki/media/foto.jpg``
      2. Relative to a media base:   ``foto.jpg``
      3. Relative to the wiki root:  ``media/foto.jpg`` (importer convention)

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

    # Candidate roots: the mundo root (``wiki/media/x.png`` and
    # ``referencias/...``), each media base (``x.png``), and the wiki root.
    # The importer writes references relative to ``wiki/`` (``media/x.png``),
    # which must resolve to ``wiki/media/x.png``; adding the wiki root keeps
    # those imported fichas renderable without rewriting already-written data.
    candidate_roots = [mundo_base, *bases, mundo_base / "wiki"]

    # Collect all candidate paths (deduplicated)
    seen: set[str] = set()
    candidates: list[Path] = []
    for root in candidate_roots:
        resolved = (root / path).resolve()
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
    mundo_base = _mundos_dir() / mundo
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
        raise problem("world.not_found")

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
    save_dir = _mundos_dir() / mundo / "wiki" / "media"
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
        raise problem("world.not_found")
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
    env_file = _project_root() / ".env"
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


def _locale_state_path() -> Path:
    """The runtime-authoritative local-state file for this project root."""
    return _project_root() / "data" / "local-state.json"


def _resolve_language(domain: str) -> str:
    """Resolve one locale domain persisted-first (AD-6/AD-8).

    Reads the same local-state file the onboarding routes persist, so the AI
    path and ``/api/config`` follow the selected locale instead of the env.
    """
    return resolve_domain_language(
        domain,
        env_file=_project_root() / ".env",
        environ=os.environ,
        state_path=_locale_state_path(),
    )


def _configured_language() -> str:
    """Normalized global UI language, persisted-first with env fallback."""
    return _resolve_language("ui")


_GATEWAY_URL = os.getenv("HERMES_GATEWAY_URL", "http://127.0.0.1:8642/v1/chat/completions")
# Gateway API key: the environment is read here; the DATA root's ``.env``
# fallback is loaded at STARTUP (``_lifespan``) — reading it here would resolve
# the data root while this module is imported (WU-2).
_GATEWAY_KEY = os.getenv("HERMES_GATEWAY_KEY", "")
_GATEWAY_TIMEOUT = int(os.getenv("HERMES_GATEWAY_TIMEOUT", "300"))


def _gateway_headers() -> dict[str, str]:
    """Gateway request headers.

    No ``Authorization`` header at all when no key is configured: ``Bearer ``
    with an empty key is rejected LOCALLY by httpx, which hides the real
    (unconfigured) state behind a transport error.
    """
    return {"Authorization": f"Bearer {_GATEWAY_KEY}"} if _GATEWAY_KEY else {}

# The adapter probes Hermes before the first activity request. Tests replace
# this seam with a fake adapter; unsupported or unreachable providers remain a
# neutral fallback and never receive a run submission.
ACTIVITY_ADAPTER = None
ACTIVITY_EVENT_TIMEOUT_SECONDS = 30.0
# Companion-gated awaited routing budget: one small Hermes classification run
# (same class as the already-awaited semantic gate) may delay the prompt build
# by at most this long in companion worlds; on timeout the prompt falls back to
# today's fire-and-forget shape and the shielded task resolves at stream close.
ROUTING_AWAIT_TIMEOUT_SECONDS = 5.0
ACTIVITY_CLEANUP_TIMEOUT_SECONDS = 1.0
ACTIVITY_UNAVAILABLE_REASON = "file_evidence_contract_unverified"
ACTIVITY_PROVIDER_FAILURE_REASON = "provider_activity_unavailable"

_hermes_client: httpx.AsyncClient | None = None


def _get_hermes_client() -> httpx.AsyncClient:
    global _hermes_client
    if _hermes_client is None:
        _hermes_client = httpx.AsyncClient(
            headers={"Content-Type": "application/json", **_gateway_headers()},
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
# Idea-materialization provider (AD2): one non-streaming chat-completions
# request per preview with ``tool_choice: "none"`` (no unused tool schemas).
# The activity adapter is still injected for the capability probe; strict
# envelope validation is server-side (fail closed); tests replace this module
# attribute after import.
_MATERIALIZE_PROVIDER = HermesMaterializationProvider(
    ACTIVITY_ADAPTER,
    chat_url=_GATEWAY_URL,
    client_provider=_get_hermes_client,
)
# Skill Madre provider (kernel-owned, co-creation-v1 envelope). Same adapter
# seam as the guided provider; tests replace it after import.
_CO_CREATION_PROVIDER = HermesCoCreationProvider(ACTIVITY_ADAPTER)
# Mandatory semantic gate: Hermes-first interpretation over the runs adapter.
# Unavailable/invalid/exhausted Hermes results fail closed as ``blocked`` with
# localized safe copy and NO lexical/plain-chat fallback. Entry-handler
# reordering ahead of this seam is PR 2; wiring alone keeps the seam live.
_SEMANTIC_PROVIDER = SemanticIntentProvider(ACTIVITY_ADAPTER)
# Conversation memory + skill routing (non-guided assistant path). The router
# resolves the world's activated skill via the methodology library and runs its
# LLM classification over the same runs adapter. Both are module seams that
# tests may replace after import. Bound lazily (WU-2).
_CONVERSATION_MEMORY = _LazyBinding(ConversationMemoryStore)


class _DeferredMethodologyLibrary:
    """Lazy binding for the module-level ``_SKILL_ROUTER`` seam.

    The router is wired at import time, but the library must NOT be
    constructed — or seeded — before ``_project_root()`` reaches its final
    (possibly test-swapped) state: an import-time construction would write
    seed records into the real repo store from test processes. Resolving
    ``_methodology_library()`` on first attribute access keeps the import
    side-effect free while the router sees the same seeded global instance on
    every request.
    """

    def __getattr__(self, name: str):
        return getattr(_methodology_library(), name)


_SKILL_ROUTER = SkillRouter(
    methodology_library=_DeferredMethodologyLibrary(),
    provider=ACTIVITY_ADAPTER,
)

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
    result = await _semantic_gate(
        mundo, user_msg,
        distilled_state=_distilled_summary(body.session_id),
        recent_turns=_gate_recent_turns(body.session_id),
    )
    payload = result.as_dict()
    if result.decision is not None:
        payload["content"] = result.decision.response
    return payload


async def _route_skill(prompt: str, mundo: str, distilled_state: str | None) -> str | None:
    """Route ``prompt`` to a skill_id via the skill router (non-guided path).

    Never raises and never blocks the response: on any failure or when no
    router is wired it returns ``None`` (no skill). The routing decision is a
    side effect (stored on the user turn for analytics / future summaries).
    When the active channel is NOT ``legacy`` (native or fail-closed
    unhealthy), the legacy routing seam is suppressed — early ``None``
    (REQ-NC-4 path a); the caller's persist stays as-is and records
    ``skill_id=None`` (never two channels, D2/D3).
    """
    if _active_channel_state() != "legacy":
        return None
    router = _SKILL_ROUTER
    if router is None:
        return None
    try:
        result = await router.route(prompt, mundo, distilled_state=distilled_state)
    except Exception:
        logger.warning("skill routing failed safely for world %r", mundo, exc_info=True)
        return None
    return result.skill_id if isinstance(result, SkillRouteResult) else None


def _companion_contract_for(
    winner: str | None, companions: list, mundo: str
) -> str | None:
    """Build the bounded companion methodology marker for ``winner``.

    Only a winner that is one of ``mundo``'s companions injects content: the
    published record is resolved from the companion's pinned version and its
    bounded name (≤120 chars) plus projected markdown (≤1000 tokens) is
    returned. Timeouts, no winner, non-companion winners (including
    transversals — never inject), and lookup misses all return ``None`` so the
    prompt falls back to today's byte-for-byte shape. Per-turn only: parameter,
    zero state. When the active channel is NOT ``legacy`` the companion marker
    is suppressed — early ``None`` (REQ-NC-4 path b): no ``[Companion
    methodology: …]`` marker is appended with the native channel or in the
    fail-closed unhealthy state.
    """
    if _active_channel_state() != "legacy":
        return None
    if winner is None or not companions:
        return None
    library = _methodology_library()
    if library is None:
        return None
    for companion in companions:
        if companion.skill_id == winner and companion.world == mundo:
            published = library.get_published(companion.skill_id, companion.version)
            if published is None:
                return None
            name = (getattr(published, "name", "") or "")[:120]
            return f"[Companion methodology: {name}]\n{project_contract_markdown(published)}"
    return None


def _persist_memory_turn(
    session_id: str, mundo: str, role: str, content: str, skill_id: str | None = None,
) -> None:
    """Persist one conversational turn; empty/absent session is a no-op."""
    if not session_id or _CONVERSATION_MEMORY is None:
        return
    try:
        _CONVERSATION_MEMORY.add_turn(session_id, mundo, role, content, skill_id=skill_id)
    except Exception:
        logger.warning("conversation memory turn persist failed", exc_info=True)


async def _maybe_refresh_distilled(session_id: str, mundo: str) -> None:
    """Lazily regenerate the distilled summary when the session crosses a
    refresh boundary (every ``DISTILL_REFRESH_INTERVAL`` turns).

    Runs after the response is produced and never blocks it. The summary is an
    async LLM condensation via ``_run_hermes`` (the same provider seam used for
    answers); on any failure it degrades to a bounded heuristic digest of the
    recent window so the distilled state still advances.
    """
    if not session_id or _CONVERSATION_MEMORY is None:
        return
    memory = _CONVERSATION_MEMORY
    try:
        if not memory.should_refresh_distilled(session_id):
            return
        turns = memory.get_recent_turns(session_id, limit=10)
        if not turns:
            return
        digest = "\n".join(f"{t.role}: {t.content}" for t in turns)
        summary = digest[-800:]
        try:
            condensed = await _run_hermes(
                "Condensa esta conversación en español, máximo 100 palabras, "
                "destacando decisiones, hechos establecidos e hilos abiertos:\n" + digest,
                session_id,
            )
            if condensed:
                summary = condensed
        except Exception:
            summary = summary  # heuristic fallback already set
        count = len(memory.get_recent_turns(session_id, limit=10_000))
        memory.update_distilled_state(session_id, mundo, summary, count)
    except Exception:
        logger.warning("distilled refresh failed safely", exc_info=True)


_SKILL_CREATION_MARKERS = (
    "crear una skill",
    "crear la skill",
    "crear skill",
    "crear una herramienta",
    "crear la herramienta",
    "crear herramienta",
    "crear una metodología",
    "crear la metodología",
    "crear metodología",
    "hacer una skill",
    "hacer una herramienta",
    "hacer una metodología",
    "nueva skill",
    "nueva herramienta",
    "nueva metodología",
)


def _skill_creation_redirect(prompt: str) -> dict | None:
    """Chat-level redirection recommendation (REQ-CC-2 / TW9 refined).

    When the Author asks to CREATE a skill from a non-Taller-de-Herramientas
    context, the assistant response gains a ``redirect`` field pointing at the
    Taller de Herramientas. This is a bounded chat-level hint ONLY: no
    semantic-gate state change, no auto-detected co-creation session, no
    auto-navigation, and no handoff — the frontend renders the message and the
    user decides (the assistant never creates the session on the Author's
    behalf).
    """
    text = (prompt or "").strip().lower()
    if not text:
        return None
    if any(marker in text for marker in _SKILL_CREATION_MARKERS):
        return {
            "target": "taller-herramientas",
            "message": "Para crear una skill, te recomiendo ir al Taller de Herramientas.",
        }
    return None


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
    # the guarded continuation, so the graph is never queried twice. The
    # session's distilled summary is injected so the single-run answer is
    # memory-aware (fricción 3).
    # Bounded assistant context: real worlds keep the world-scoped authorized
    # context; the single literal global context is world-agnostic (no mundo,
    # ficha, reference, or graph grounding); anything else fails closed — the
    # global special-case is never a permissive catch-all for arbitrary names.
    context_kind, _ = _resolve_assistant_context(mundo)
    if context_kind == "unknown":
        logger.info("ai_ask: unknown assistant context %r; fail closed", mundo)
        return SemanticResult(
            decision=None,
            attempts=0,
            request_id=f"semantic-{uuid.uuid4().hex}",
            session_id=body.session_id or None,
            unavailable=True,
        ).as_dict()
    ficha = _active_ficha_context(mundo, body)
    if context_kind == "global":
        context = SemanticContext()
        reference_context, reference_name, graph_unavailable = "", None, False
    else:
        context, reference_context, reference_name, graph_unavailable = _semantic_context(
            mundo, body.prompt, ficha=ficha,
        )
    distilled_state = _distilled_summary(body.session_id)
    result = await _semantic_gate(
        mundo, body.prompt,
        context=context,
        distilled_state=distilled_state,
        recent_turns=_gate_recent_turns(body.session_id),
    )
    if result.decision is None:
        logger.info(
            "ai_ask: no validated Hermes decision (unavailable=%s attempts=%s); fail closed",
            result.unavailable, result.attempts,
        )
        return result.as_dict()
    # Consent memory (REQ-GFC-06): a suggestion left unaccepted becomes a
    # session decline once the next same-session turn arrives ("keeps chatting").
    _mark_kept_chatting_decline(body.session_id, mundo)
    # Demiurgos policy against the validated decision:
    # 1. Active guarded guided session -> continuation policy (typed
    #    confirmation, next turn) applied only after Hermes interpretation.
    if body.guided_session_id or body.guided_revision is not None:
        guided = await _internal_guided_turn(mundo, body, request)
        if guided is not None:
            return guided
    # 2. Self-contained decisions answer directly with Hermes' voice. On the
    #    non-guided conversational path the response is the gate's single-run
    #    answer (already distilled-aware). Memory writes + skill routing are
    #    SIDE EFFECTS: they never mutate the returned envelope (SC-08).
    if result.decision.state in SELF_CONTAINED_SEMANTIC_STATES:
        logger.info(
            "ai_ask: semantic state=%s attempts=%s",
            result.decision.state, result.attempts,
        )
        if result.decision.state in {"allow", "clarify"}:
            # Memory + routing are side effects only for a real session; the
            # empty-string session never names a conversation (fricción 4), so
            # it neither persists nor triggers a routing/LLM call.
            if body.session_id:
                skill_id = await _route_skill(body.prompt, mundo, distilled_state)
                _persist_memory_turn(body.session_id, mundo, "user", body.prompt, skill_id)
                _persist_memory_turn(body.session_id, mundo, "assistant", result.response)
                await _maybe_refresh_distilled(body.session_id, mundo)
        payload = result.as_dict()
        redirect = _skill_creation_redirect(body.prompt)
        if redirect is not None:
            # REQ-CC-2: chat-level recommendation only — no semantic-gate
            # state change, no auto-navigation, no handoff.
            payload["redirect"] = redirect
        return payload
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


def _distilled_summary(session_id: str) -> str | None:
    """Return the session's distilled summary, or ``None`` when absent/empty.

    The empty-string session id is deliberately ignored (fricción 4): it never
    names a real conversation, so it must not trigger memory reads or writes.
    """
    if not session_id or _CONVERSATION_MEMORY is None:
        return None
    try:
        state = _CONVERSATION_MEMORY.get_distilled_state(session_id)
    except Exception:
        return None
    return state.summary if state is not None else None


GATE_RECENT_TURNS = 2
"""Turns passed verbatim to the semantic gate (blind-spot window)."""

GATE_RECENT_TURN_CHARS = 240
"""Per-turn character cap inside the gate's verbatim window."""


def _gate_recent_turns(session_id: str) -> str:
    """Bounded verbatim window of the last turns for the stateless gate.

    The distilled summary refreshes only every ``DISTILL_REFRESH_INTERVAL``
    turns, so a stateless gate would miss fresh follow-up references
    ("no, el segundo"). The last few turns, truncated, close that gap without
    re-reading the transcript. The empty-string session never names a real
    conversation (friccion 4) and returns ""."""
    if not session_id or _CONVERSATION_MEMORY is None:
        return ""
    try:
        turns = _CONVERSATION_MEMORY.get_recent_turns(
            session_id, limit=GATE_RECENT_TURNS,
        )
    except Exception:
        return ""
    lines: list[str] = []
    for turn in turns:
        text = " ".join(str(turn.content).split())[:GATE_RECENT_TURN_CHARS]
        if text:
            lines.append(f"{turn.role.capitalize()}: {text}")
    return "\n".join(lines)


async def _semantic_gate(
    mundo: str, prompt: str, *, session_id: str = "",
    ficha: str | None = None, context: SemanticContext | None = None,
    request_id: str | None = None, distilled_state: str | None = None,
    recent_turns: str | None = None,
) -> SemanticResult:
    """Mandatory Hermes-first semantic gate shared by every assistant surface.

    Runs BEFORE any Demiurgos intent classifier or action. An unwired provider
    fails closed as ``unavailable``; unavailable/invalid/malformed/exhausted
    Hermes yields a blocked ``SemanticResult`` with zero action, session,
    proposal, or write. ``decide`` is the only semantic interpretation
    boundary and always receives the bounded authorized context.

    The gate runs STATELESS by design (no gateway session replay): it is a
    classifier, and the guided/co-creation surfaces already decide correctly
    without any transcript. Conversation awareness comes from the bounded
    ``distilled_state`` summary plus ``recent_turns``, a verbatim window of
    the last turns that closes the refresh gap between distillations.
    ``session_id`` is only echoed into the result envelope when a caller
    deliberately supplies one.
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
        distilled_state=distilled_state,
        recent_turns=recent_turns,
    )


def _semantic_blocked_result(result: SemanticResult) -> dict:
    """Fail a semantic outcome closed to a write-free blocked envelope."""
    return SemanticResult(
        decision=None,
        attempts=result.attempts,
        request_id=result.request_id,
        session_id=result.session_id,
    ).as_dict()


# ---------------------------------------------------------------------------
# Guided consent: suggestion tokens + session decline memory (REQ-GFC-03/04/06)
# ---------------------------------------------------------------------------

GUIDED_CONSENT_SUGGESTION_TEXT = (
    "Parece que querés crear un personaje. ¿Abrimos el flujo guiado?"
)
"""Approved in-chat suggestion copy (REQ-GFC-04)."""

CONSENT_TOKEN_TTL = timedelta(minutes=30)
"""A consent suggestion token stays valid for this long after issuance."""

# In-memory, TTL-bounded, principal/session/world-bound consent tokens. Mirrors
# ``_GUIDED_PENDING_PROPOSALS``: no durable migration and no new dependency.
# Issued ONLY for a musing guided suggestion; the accept route (PR2) consumes
# one exactly once and fails closed on replay/expiry/foreign binding.
_GUIDED_CONSENT_TOKENS: dict[str, dict[str, object]] = {}


def _sweep_guided_consent_tokens(now: datetime) -> None:
    """Drop expired consent tokens (lazy sweep on issue and session lookup)."""
    cutoff = now - CONSENT_TOKEN_TTL
    for token, record in list(_GUIDED_CONSENT_TOKENS.items()):
        created_at = record.get("created_at")
        if not isinstance(created_at, datetime) or created_at < cutoff:
            _GUIDED_CONSENT_TOKENS.pop(token, None)


def _issue_guided_consent_token(
    *, principal_id: str, session_id: str, mundo: str, prompt: str,
    decision: SemanticDecision, attempts: int, reference_context: str,
    reference_name: str | None,
) -> str:
    """Issue a one-shot consent token bound to principal + session + world.

    The validated decision is stored whole so the deferred accept (PR2) reopens
    the exact continuation with NO second Hermes run and no re-decision.
    """
    now = datetime.now(timezone.utc)
    _sweep_guided_consent_tokens(now)
    token = f"ct-{uuid.uuid4().hex}"
    _GUIDED_CONSENT_TOKENS[token] = {
        "principal_id": principal_id,
        "session_id": session_id,
        "mundo": mundo,
        "prompt": prompt,
        "decision": decision,
        "attempts": attempts,
        "reference_context": reference_context,
        "reference_name": reference_name,
        "created_at": now,
    }
    return token


def _consume_guided_consent_token(
    token: object, *, principal_id: str, mundo: str,
) -> dict[str, object] | None:
    """One-shot pop of a consent token; fails closed on any mismatch.

    Returns the bound record exactly once, or ``None`` for a malformed,
    missing, expired, replayed, foreign-principal, or foreign-world token
    (REQ-GFC-07). A foreign attempt never destroys the rightful principal's
    token; an expired token is discarded so a stale suggestion cannot be
    replayed. This runs synchronously (no await), so peek-then-pop is atomic.
    """
    now = datetime.now(timezone.utc)
    _sweep_guided_consent_tokens(now)
    if not isinstance(token, str) or not token.startswith("ct-"):
        return None
    record = _GUIDED_CONSENT_TOKENS.get(token)
    if record is None:
        return None
    if record.get("principal_id") != principal_id or record.get("mundo") != mundo:
        return None
    created_at = record.get("created_at")
    if not isinstance(created_at, datetime) or created_at < now - CONSENT_TOKEN_TTL:
        _GUIDED_CONSENT_TOKENS.pop(token, None)
        return None
    _GUIDED_CONSENT_TOKENS.pop(token, None)
    return record


def _guided_consent_pending_for_session(session_id: str, mundo: str) -> bool:
    """True when an unconsumed suggestion token exists for the session."""
    if not session_id:
        return False
    _sweep_guided_consent_tokens(datetime.now(timezone.utc))
    return any(
        record.get("session_id") == session_id and record.get("mundo") == mundo
        for record in _GUIDED_CONSENT_TOKENS.values()
    )


def _discard_guided_consent_tokens(session_id: str, mundo: str) -> None:
    """Invalidate every pending suggestion token for a session/world."""
    for token, record in list(_GUIDED_CONSENT_TOKENS.items()):
        if record.get("session_id") == session_id and record.get("mundo") == mundo:
            _GUIDED_CONSENT_TOKENS.pop(token, None)


def _mark_kept_chatting_decline(session_id: str, mundo: str) -> None:
    """Treat an unaccepted suggestion as a session decline (REQ-GFC-06).

    Once a suggestion was emitted, the next same-session turn that arrives
    without an accept means the Author kept chatting; that counts as a decline.
    The pending token is invalidated so the stale suggestion cannot be accepted
    later.
    """
    if not session_id or _CONVERSATION_MEMORY is None:
        return
    if not _guided_consent_pending_for_session(session_id, mundo):
        return
    try:
        _CONVERSATION_MEMORY.record_guided_consent_decline(session_id, mundo)
    except Exception:
        logger.warning("guided consent decline persist failed", exc_info=True)
        return
    _discard_guided_consent_tokens(session_id, mundo)


def _guided_consent_declined(session_id: str, mundo: str) -> bool:
    """Read the server-authoritative decline flag; never raises."""
    if not session_id or _CONVERSATION_MEMORY is None:
        return False
    try:
        return bool(_CONVERSATION_MEMORY.guided_consent_declined(session_id, mundo))
    except Exception:
        logger.warning("guided consent decline read failed", exc_info=True)
        return False


def _declined_guided_answer(result: SemanticResult) -> dict:
    """Answer self-contained when a session already declined the guided flow.

    No session is opened and no suggestion is re-emitted: the turn is answered
    as a plain assistant response so a declined session is never re-nagged.
    """
    payload = result.as_dict()
    payload["state"] = "allow"
    payload["action"] = action_for_state("allow")
    payload["guided"] = False
    payload.pop("guided_explicitness", None)
    return payload


def _guided_consent_suggestion(
    mundo: str, body: AskRequest, principal, result: SemanticResult,
    *, decision: SemanticDecision, reference_context: str,
    reference_name: str | None,
) -> dict:
    """Return a token-bound consent suggestion without creating anything."""
    if _guided_consent_declined(body.session_id, mundo):
        return _declined_guided_answer(result)
    token = _issue_guided_consent_token(
        principal_id=principal.id,
        session_id=body.session_id,
        mundo=mundo,
        prompt=body.prompt,
        decision=decision,
        attempts=result.attempts,
        reference_context=reference_context,
        reference_name=reference_name,
    )
    return {
        "state": result.state,
        "action": result.action,
        "response": GUIDED_CONSENT_SUGGESTION_TEXT,
        "request_id": result.request_id,
        "attempts": result.attempts,
        "guided_explicitness": decision.guided_explicitness,
        "consent": "required",
        "consent_token": token,
    }


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
    # Consent policy: only an explicit imperative auto-opens the guided
    # surface. Musing/absent explicitness yields a token-bound suggestion and
    # creates nothing (REQ-GFC-02/03).
    if decision.guided_explicitness != "imperative":
        return _guided_consent_suggestion(
            mundo, body, principal, result,
            decision=decision,
            reference_context=reference_context,
            reference_name=reference_name,
        )
    return await _open_guided_continuation(
        mundo, body, result, principal, decision=decision,
        reference_context=reference_context, reference_name=reference_name,
    )


async def _open_guided_continuation(
    mundo: str, body: AskRequest, result: SemanticResult, principal,
    *, decision: SemanticDecision, reference_context: str = "",
    reference_name: str | None = None,
) -> dict:
    """Create the guarded session and expose the run's continuation.

    Shared by the imperative auto-open and the deferred consent accept (PR2):
    the click IS the imperative, so no second Hermes run starts. The session is
    created through ``_GUIDED_SESSIONS`` and the continuation is serialized
    server-side with a server-owned slug, target, and digest. Every failure path
    returns a fail-closed blocked envelope.
    """
    session_id = f"guided-{uuid.uuid4().hex}"
    relation_goal = extract_related_goal(body.prompt, reference_name=reference_name).summary
    try:
        _GUIDED_SESSIONS.create(
            session_id, mundo, principal.id,
            reference_context=reference_context, reference_name=reference_name,
            relation_goal=relation_goal,
            methodology_snapshot=_active_methodology_snapshot(mundo, GUIDED_CHARACTER_FLOW),
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
        "guided_explicitness": decision.guided_explicitness,
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
            "guided_explicitness": decision.guided_explicitness,
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
        "guided_explicitness": decision.guided_explicitness,
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


_GLOBAL_ASSISTANT_IDENTITY: dict[str, str] = {
    "es": (
        "[SYSTEM OVERRIDE — IDENTITY] Tu identidad es el Asistente Demiurgos del "
        "Taller de Ideas, un espacio independiente de cualquier mundo. No eres "
        "Gentle AI y no perteneces a ningún mundo narrativo concreto. Responde "
        "siempre como el Asistente Demiurgos: ayuda a generar, enriquecer y "
        "desarrollar ideas narrativas genéricas (premisas, personajes, escenarios, "
        "tramas) sin asumir acceso a ningún mundo."
    ),
    "en": (
        "[SYSTEM OVERRIDE — IDENTITY] Your identity is the Demiurgos Assistant of "
        "the Ideas Workshop, a space independent from any world. You are not "
        "Gentle AI and you do not belong to any specific narrative world. Always "
        "answer as the Demiurgos Assistant: help brainstorm, enrich, and develop "
        "generic narrative ideas (premises, characters, settings, plots) without "
        "assuming access to any world."
    ),
}

_GLOBAL_ASSISTANT_GUIDANCE: dict[str, str] = {
    "es": (
        "[Contexto: sesión global sin mundo. No hay fichas, lore, grafo ni "
        "archivos de ningún mundo. No inventes hechos de mundos existentes; si la "
        "persona menciona un mundo concreto, recuérdale que este asistente trabaja "
        "sin acceso a ese mundo y propón ideas genéricas o pídele más contexto.]"
    ),
    "en": (
        "[Context: global session without a world. There are no sheets, lore, "
        "graph, or files from any world. Do not invent facts about existing "
        "worlds; if the person mentions a specific world, remind them that this "
        "assistant works without access to that world and propose generic ideas "
        "or ask for more context.]"
    ),
}


def _build_ai_ask_prompt(
    mundo: str, body: AskRequest, ficha_context: str | None = None,
    reference_name: str | None = None,
    memory_turns: list[Turn] | None = None,
    distilled_state: str | None = None,
    skill_contract: str | None = None,
) -> str:
    from demiurgos_personality import build_identity_prompt, build_graph_context

    global_context = mundo == GLOBAL_ASSISTANT_CONTEXT
    conversation_language = _resolve_language("conversation")
    parts: list[str] = []

    # Demiurgos assistant identity: world-grounded for real worlds, or the
    # world-agnostic Taller de Ideas persona for the global context.
    if global_context:
        parts.append(_GLOBAL_ASSISTANT_IDENTITY[conversation_language])
    elif mundo:
        parts.append(build_identity_prompt(mundo, language=conversation_language))

    if global_context:
        # World-agnostic: no graph tools, no world lore grounding — the global
        # assistant brainstorms/enriches ideas generically and never claims
        # access to any world's files, graph, or lore.
        parts.append(_GLOBAL_ASSISTANT_GUIDANCE[conversation_language])
    else:
        # Tool usage guidance: use the graph tools, never generic file/lore tools
        parts.append(
            "[Tool usage guidance: For questions about this world, use the Demiurgos graph "
            "tools, not generic file tools. Prefer this flow: call graph_search to locate an "
            "entity (it returns a \"path\" field for each match), then call graph_read passing "
            "that exact value as the required \"entity_path\" argument — not the display title, "
            "name, or a \"Parent::Name\" reference — then answer using only what was read. Use "
            "graph_links only when the question is about connections between entities. Do NOT "
            "use generic search/read file tools (search_files, read_file) or lore_search for "
            "world lore when the graph tools allow answering directly. If the graph returns "
            "nothing for the world, say so plainly instead of inventing facts.]"
        )

        # Long-term memory guidance: engram as auxiliary, per-world memory.
        # Live graph evidence always outranks stored memories (contamination
        # guard); the block is world-keyed so facts never bleed across worlds.
        parts.append(
            "[Long-term memory guidance: Engram tools (mem_search, mem_save) are auxiliary "
            "cross-session memory, not evidence. Use them only for durable notes: canon "
            "decisions the author states in conversation, and author preferences (format, "
            "tone, naming). Always key by world: prefix titles with the world name (e.g. "
            '"Vibrantes: Impulsor canon decision") and include the world name in queries. '
            "Never store ficha contents or raw world text in memory; store short facts only. "
            "If a memory conflicts with the live graph or ficha, the live evidence wins: "
            "answer from the ficha and treat the stale memory as unreliable.]"
        )

        # Entity graph context (search for entities matching the prompt)
        graph_index = _get_graph(mundo) if mundo else None
        graph_ctx = build_graph_context(body.prompt, graph_index)
        if graph_ctx:
            parts.append(graph_ctx)

    # Response guidance
    parts.append(
        "[Visible response guidance: Answer directly and concisely. Format the answer "
        "with markdown when it adds structure: use ## headings for distinct sections, "
        "**bold** for key names or terms, and - bullets for short lists or steps. Do not "
        "over-format a one-line answer; keep factual answers grounded in the provided "
        "evidence and do not repeat the full ficha or internal context. Expand only "
        "when requested.]"
    )

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
    # Conversation memory window (recent turns) + distilled summary, injected
    # before the current prompt so the assistant answers with continuity.
    if memory_turns:
        formatted_turns = "\n".join(
            f"- {turn.role}: {turn.content}" for turn in memory_turns
        )
        parts.append(
            f"[Recent conversation ({len(memory_turns)} turns):\n"
            f"{formatted_turns}\n"
            f"Summary: {distilled_state or '(none)'}]"
        )
    elif distilled_state:
        parts.append(
            f"[Conversation context (summarized): {distilled_state}]"
        )
    if skill_contract:
        parts.append(skill_contract)
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
    return texts[kind][_resolve_language("conversation")]


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
    context_kind, world_root = _resolve_assistant_context(mundo)
    if context_kind == "unknown":
        return _activity_unavailable()

    # Mandatory Hermes semantic interpretation FIRST with bounded authorized
    # context. No classifier, action, session, proposal, or write precedes the
    # validated decision. The global context is world-agnostic: no mundo,
    # ficha, reference, or graph grounding reaches the gate.
    request_id = f"activity-{uuid.uuid4().hex}"
    if context_kind == "global":
        context = SemanticContext()
    else:
        context, _, _, _ = _semantic_context(mundo, body.prompt)
    distilled_state = _distilled_summary(body.session_id)
    result = await _semantic_gate(
        mundo, body.prompt,
        context=context,
        request_id=request_id,
        distilled_state=distilled_state,
        recent_turns=_gate_recent_turns(body.session_id),
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

    # Memory context for the activity surface (side effects). Only a real
    # session is routed/persisted (fricción 4). The gate above ran stateless on
    # the distilled summary plus a bounded verbatim window. The agent prompt
    # carries the distilled summary into the run; the raw recent-turns window
    # is NOT embedded here because the Hermes gateway still replays the session
    # transcript for this session_id when no conversation_history is passed
    # (api_server_runs: _conversation_history_for_session ->
    # get_messages_as_conversation), so embedding it would duplicate history
    # and inflate the input context.
    # Companion-gated awaited routing (bridge): when the world has ≥1 companion
    # AND a real session is active, routing is awaited (≤5s) BEFORE the prompt
    # is built so a companion winner's methodology can be injected as content.
    # Zero-companion worlds and session-less turns keep today's fire-and-forget
    # byte-for-byte: no added await and no extra provider call.
    library = _methodology_library()
    companions = library.list_companions(mundo)
    early_route_task = None
    skill_contract = None
    if companions and body.session_id and _CONVERSATION_MEMORY is not None:
        early_route_task = asyncio.create_task(_route_skill(body.prompt, mundo, distilled_state))
        try:
            winner = await asyncio.wait_for(
                asyncio.shield(early_route_task), ROUTING_AWAIT_TIMEOUT_SECONDS
            )
        except Exception:
            winner = None
        skill_contract = _companion_contract_for(winner, companions, mundo)
    # Skill routing is fire-and-forget: it never blocks the response and its
    # skill_id is persisted at stream close.
    activity_request = HermesActivityRequest(
        request_id=request_id,
        prompt=_build_ai_ask_prompt(
            mundo, body,
            distilled_state=distilled_state,
            skill_contract=skill_contract,
        ),
        session_id=_channel_session_id(body.session_id),
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
        assistant_parts: list[str] = []

        def emit(event) -> str:
            if isinstance(event, AnswerEvent):
                assistant_parts.append(event.response)
            return _sse_event(event.as_dict())

        yield _sse_event(_semantic_decision_event(result).as_dict())
        completed = False
        disconnected = False
        # Skill routing: reuse the companion-gated early task when one was
        # started (already resolved or shielded for close-time persistence);
        # otherwise fire-and-forget as today — the zero-companion spawn site is
        # byte-identical and adds no provider call.
        route_task = early_route_task
        try:
            if route_task is None and body.session_id and _CONVERSATION_MEMORY is not None:
                route_task = asyncio.create_task(_route_skill(body.prompt, mundo, distilled_state))
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
                        yield emit(event)
            else:
                for raw_event in source:
                    if await request.is_disconnected():
                        disconnected = True
                        break
                    for event in translator.translate(raw_event):
                        if isinstance(event, TerminalEvent):
                            completed = True
                        yield emit(event)
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
                                yield emit(event)
                        elif run_status in {"failed", "cancelled"}:
                            raw_status = {"event": f"run.{run_status}", "run_id": run_id}
                            for event in translator.translate(raw_status):
                                if isinstance(event, TerminalEvent):
                                    completed = True
                                yield emit(event)
            if not disconnected and not completed:
                for event in translator.finalize():
                    yield emit(event)
        except asyncio.CancelledError:
            disconnected = True
            raise
        except Exception:
            if not disconnected:
                for event in translator.finalize():
                    yield emit(event)
        finally:
            if not completed:
                await _cancel_activity(adapter, run_id)
            # Resolve the fire-and-forget skill routing (side effect for
            # analytics / future summaries) and persist the user turn with it.
            # The user turn is persisted unconditionally (the prompt was sent);
            # the assistant turn is persisted at close once the answer is known,
            # skipping on disconnect. The envelope of each event is untouched
            # (SC-08).
            skill_id = None
            if route_task is not None:
                try:
                    skill_id = await route_task
                except Exception:
                    skill_id = None
            _persist_memory_turn(body.session_id, mundo, "user", body.prompt, skill_id)
            if not disconnected and assistant_parts:
                _persist_memory_turn(body.session_id, mundo, "assistant", "".join(assistant_parts))
                await _maybe_refresh_distilled(body.session_id, mundo)

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


def _run_hermes_sync(prompt: str, session_id: str = "",
                     client: httpx.Client | None = None) -> str:
    """Synchronous mirror of ``_run_hermes`` for the importer's sync bridge.

    Uses a FRESH ``httpx.Client`` per call — never the module-level async
    singleton (``_get_hermes_client``) — so the bridge can run from a worker
    thread (FastAPI sync endpoints) without reusing the main event loop's
    connection pool, which httpx forbids (cross-event-loop RuntimeError).
    Payload, ``X-Hermes-Session-Id`` header, timeout, logging, and failure
    handling mirror ``_run_hermes`` exactly; failures return the localized
    unavailable copy, never raw provider text.

    An optional ``client`` may be injected (same timeout/headers contract);
    the caller owns its lifecycle — this function never closes it. This lets
    ``_sync_hermes_enricher`` abort an in-flight gateway call on budget
    timeout by closing the shared client from the main thread: the request
    tears down, raises, and falls into the generic except branch below, so the
    worker thread exits in seconds instead of billing in the background.
    """
    import time
    t0 = time.monotonic()
    logger.info("Hermes GW START len=%d session=%s preview=%r", len(prompt), session_id or "-", prompt[:120].replace("\n", " "))
    owns_client = client is None
    if owns_client:
        client = httpx.Client(
            headers={"Content-Type": "application/json", **_gateway_headers()},
            timeout=httpx.Timeout(_GATEWAY_TIMEOUT, connect=10.0),
        )
    try:
        payload = {
            # Hermes resolves the active profile's model.default on the next
            # request. Do not pass a browser-controlled model override here.
            "model": "hermes-agent",
            # Importer enrichment is a text->JSON task over the ficha bodies +
            # the document catalog it is handed; it must NOT roam with tools
            # (search / graph read) or it loops and bills far more than the
            # task needs. The gateway honors "tool_choice": "none" for THIS
            # request only — the general Demiurgos assistant never sends it,
            # so it keeps its full toolset. Scoped to the sync import bridge.
            "tool_choice": "none",
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {}
        if session_id:
            # Opt-in session continuity: gateway keeps the conversation state.
            headers["X-Hermes-Session-Id"] = session_id
        resp = client.post(_GATEWAY_URL, json=payload, headers=headers)
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
    finally:
        if owns_client:
            client.close()


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
        raise problem("world.not_found")
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
from ideas_bank_router import (  # noqa: E402
    IdeaMaterializePreviewRequest,
    IdeaMaterializeTargetRequest,
    create_ideas_bank_router,
)
from docx_export import _convert_markdown_to_docx, _strip_frontmatter  # noqa: E402
from ideas_bank import IdeaNotFound, IdeasBank  # noqa: E402
import assistant_settings  # noqa: E402
from assistant_settings import create_assistant_settings_router  # noqa: E402
from hermes_runtime_probe import HermesGatewayProbe  # noqa: E402
from telegram_settings import create_telegram_settings_router  # noqa: E402
from migration_settings import create_migration_settings_router  # noqa: E402
from import_router import create_import_router  # noqa: E402
from system_control import create_system_control_router  # noqa: E402
from import_store import ImportJobStore  # noqa: E402
from import_service import ImportService  # noqa: E402
from import_spool_gc import gc_enabled, gc_guard_hours, gc_ttl_days, reap_dead_spools  # noqa: E402

# Lazy world-importer store: reads the current data root so tests can relocate it.
_IMPORT_STORE: ImportJobStore | None = None


def _import_store() -> ImportJobStore:
    global _IMPORT_STORE
    if _IMPORT_STORE is None:
        _IMPORT_STORE = ImportJobStore(_project_root() / "data" / "import-jobs.sqlite3")
    return _IMPORT_STORE


def _reconcile_import_graph(rel: str, mundo: str) -> None:
    """Reconcile the canonical graph for a written ficha before success (2.9)."""
    idx = _get_graph(mundo)
    if idx is not None:
        full = _mundos_dir() / mundo / rel
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
    full_paths = [str(_mundos_dir() / mundo / rel) for rel in paths]
    return idx.update_many(full_paths, mundo)


def _run_inter_doc_post_process(mundo: str) -> None:
    """Run the inter-document relationship post-process for a world (fail-open).

    Composes the world's cached ``EntityGraphIndex`` with the synchronous
    Hermes bridge and feeds both to ``inter_doc_relationships.run_post_process``
    (which is itself fail-open). Wired as ``ImportService.inter_doc_post_process``
    (auto trigger after import reconciliation) and reused by the manual
    reconcile endpoint. Never raises — a post-process failure is logged and
    the import job completes normally.
    """
    try:
        from wiki.inter_doc_relationships import run_post_process  # type: ignore[import-untyped]

        idx = _get_graph(mundo)
        if idx is None:
            return
        run_post_process(mundo, idx, _sync_hermes_enricher)
    except Exception as exc:  # noqa: BLE001 — post-process is additive
        logger.warning(
            "inter_doc post-process failed for %s: %s",
            mundo, type(exc).__name__, exc_info=True,
        )


def _register_import_gallery(world: str, src: Path, rel: str) -> None:
    """Register a spooled image into the world gallery (existing media base).

    Copies the (already bounded) image into ``mundos/{world}/wiki/media/`` so
    the existing media contract (list/upload/serve via ``getMediaUrl``) sees it
    as a first-class asset; the ficha references it via relative Markdown.
    """
    save_dir = _mundos_dir() / world / "wiki" / "media"
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

# Taller de Ideas — global idea bank (/api/ideas). The bank is a separate
# top-level surface (ideas/, sibling of mundos/); canon safety is structural.
app.include_router(
    create_ideas_bank_router(
        require_principal=lambda request: _resolve_principal(request),
    ),
)

# Backup destination, runs, snapshots and restore (/api/backup/*). Every route
# is behind require_principal and fails closed (401) on an unauthenticated call;
# the status payload carries local-write fields only and is asserted
# cloud-free and vocabulary-clean before it leaves (REQ-BUI-1, REQ-SF-4).
app.include_router(
    create_backup_router(
        require_principal=lambda request: _resolve_principal(request),
        data_root=lambda: _project_root(),
        engine=lambda: _backup_engine(),
    ),
)

# ---------------------------------------------------------------------------
# DOCX export endpoints (ficha-export-pdf-docx, backend slice)
#
# Server-side markdown -> .docx via pandoc (see docx_export.py). The ficha
# export reuses the traversal-protected media resolver for embedded images;
# the idea export rewrites the absolute ``/api/ideas/media/...`` URLs that the
# idea embed uses back to disk paths under the ideas media store.
# ---------------------------------------------------------------------------

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _unlink_quiet(path: str) -> None:
    """Best-effort temp-file cleanup after the response is sent."""
    try:
        os.unlink(path)
    except OSError:
        pass


def _docx_file_response(data: bytes, filename: str) -> FileResponse:
    """Serve in-memory DOCX bytes as an attachment FileResponse.

    pandoc produces bytes in memory, but FileResponse needs a real path, so
    the bytes are spilled to a temp file that is unlinked once the response
    has been sent.
    """
    fd, tmp_path = tempfile.mkstemp(suffix=".docx")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    except Exception:
        os.unlink(tmp_path)
        raise
    return FileResponse(
        tmp_path,
        media_type=DOCX_MEDIA_TYPE,
        filename=filename,
        background=BackgroundTask(_unlink_quiet, tmp_path),
    )


def _resolve_idea_media(src: str, media_dir: Path) -> Path | None:
    """Resolve an absolute ``/api/ideas/media/{filename}`` URL to a disk path.

    Mirrors the traversal protections of the ideas media route: the filename
    must be a bare name (no separators, no ``..``) and the resolved file must
    stay inside ``<ideas_root>/media``. Missing files resolve to None so the
    conversion emits the ``[imagen no disponible]`` placeholder.
    """
    prefix = "/api/ideas/media/"
    if not src.startswith(prefix):
        return None
    filename = src[len(prefix):]
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return None
    try:
        full = (media_dir / filename).resolve()
    except (OSError, ValueError):
        return None
    if full.parent != media_dir.resolve():
        return None
    return full if full.is_file() else None


def _resolve_media_for_export(mundo: str, src: str) -> Path | None:
    """Resolve a ficha image for DOCX embedding — existing files only.

    ``_resolve_media_path`` returns structurally valid paths even when the
    file is missing (so the media endpoint can 404 vs 400). pandoc cannot
    embed a missing file, so the export resolver requires the file to exist
    and maps missing files to None, which degrades the image to the
    ``[imagen no disponible]`` placeholder.
    """
    full = _resolve_media_path(mundo, src)
    return full if full is not None and full.is_file() else None


@app.get("/api/{mundo}/export/docx")
def export_ficha_docx(
    mundo: str,
    path: str = Query(..., description="Ruta de la ficha (sección + relativa), p.ej. lore/00_inicio.md"),
):
    """Export a world ficha's body (frontmatter stripped) as a .docx file.

    ``path`` is the section-relative ficha path (``lore/00_inicio.md``).
    Embedded images resolve through the traversal-protected
    ``_resolve_media_path``; unresolvable images degrade to
    ``[imagen no disponible]``. 400 on traversal/invalid path, 404 on missing
    ficha, 500 when the pandoc conversion fails (e.g. pandoc not installed).
    """
    raw_parts = path.split("/")
    if (
        any(p == ".." for p in raw_parts)
        or path.startswith("/")
        or "\\" in path
        or "\x00" in path
    ):
        raise HTTPException(status_code=400, detail="Ruta de ficha inválida")
    parts = [p for p in raw_parts if p not in ("", ".")]
    if not parts or parts[0] not in VALID_SECTIONS:
        raise HTTPException(status_code=400, detail="Ruta de ficha inválida")
    section, rel = parts[0], "/".join(parts[1:])
    full = _resolve_path(mundo, section, rel)
    if full is None:
        raise HTTPException(status_code=404, detail="Ficha no encontrada")
    try:
        raw = full.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo leer la ficha: {exc}")
    try:
        data = _convert_markdown_to_docx(
            _strip_frontmatter(raw),
            resolve_image=lambda src: _resolve_media_for_export(mundo, src),
            resource_paths=_get_media_bases(mundo),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return _docx_file_response(data, f"{Path(path).stem}.docx")


@app.get("/api/ideas/{slug}/export/docx")
def export_idea_docx(slug: str, request: Request):
    """Export an idea's body + embedded images as a .docx file.

    Mirrors the /api/ideas auth contract (trusted principal required). The
    idea body's absolute ``/api/ideas/media/...`` image URLs are rewritten to
    disk paths under the ideas media store; unresolvable images degrade to
    the ``[imagen no disponible]`` placeholder. 404 on unknown slug, 500 when
    the pandoc conversion fails.
    """
    if _resolve_principal(request) is None:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    bank = IdeasBank()
    try:
        idea = bank.read(slug)
    except IdeaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    media_dir = bank._ideas_root / "media"
    try:
        data = _convert_markdown_to_docx(
            idea.body,
            resolve_image=lambda src: _resolve_idea_media(src, media_dir),
            resource_paths=[media_dir],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return _docx_file_response(data, f"{slug}.docx")


def _materialize_existing_ids(reader: _GuidedGraphReader) -> list[str]:
    """Existing canonical entity ids in the world, via the diskless reader seam.

    Uses the reader's ``entities()`` enumeration (the real index seam,
    R-IM-03/06) instead of ``search("*")``, which returns ``[]`` against the
    real index by design (zero-score fast path). Only entities with a
    non-empty canonical ``id`` count (``graph_indexer._entity_from_file``
    sets ``id`` only when ``is_canonical_id``), so relation validation
    against this set mirrors ``set_graph_relation``'s id-only gate (R-IM-03).
    """
    ids: list[str] = []
    for entity in reader.entities():
        if not isinstance(entity, dict):
            continue
        canonical_id = entity.get("id")
        if isinstance(canonical_id, str) and canonical_id.strip():
            ids.append(canonical_id)
    return ids


def _resolve_ficha_title(
    client_title: str | None, idea_title: str | None, idea_slug: str
) -> str:
    """Resolve the server-owned ficha title (FT-1).

    Single source for the visible title that BOTH the frontmatter ``title`` and
    the body H1 must equal: the client-supplied title (destination step) wins,
    then the idea's own title, then the idea slug. Internal whitespace runs
    collapse to a single space so the H1 and the frontmatter title never differ
    by stray spacing. The filename is derived separately by
    ``resolve_file_slug``; changing the file name never changes this value.
    """
    raw = (client_title or "").strip() or (idea_title or "").strip() or idea_slug
    return re.sub(r"\s+", " ", raw).strip()


def _resolve_materialize_target(
    world: str, section: str, folder: str, file_slug: str
) -> tuple[str, dict[str, Any], dict[str, str] | None]:
    """Resolve a materialize destination and detect an existing-file collision.

    Single source of truth for the target/collision rule shared by
    ``materialize_preview`` and ``materialize_target`` (AD5): the section-relative
    *target* (``{section}/{folder}/{file_slug}.md``), the response *target_info*
    block (``{world, section, folder, slug, path}`` with ``path`` relative to
    the section) and the additive *collision* payload
    (``{target, suggested_slug, suggested_target}``) when the target already
    exists, else ``None``. ``file_slug`` is the RESOLVED filename slug (derived
    from the title or supplied by the client), never the idea's internal slug;
    ``target_info["slug"]`` reports exactly that resolved value. Pure
    resolution — no provider, graph or write.
    """
    target_rel = f"{folder}/{file_slug}.md" if folder else f"{file_slug}.md"
    target = f"{section}/{target_rel}"
    target_info = {
        "world": world, "section": section,
        "folder": folder, "slug": file_slug, "path": target_rel,
    }
    full = _resolve_mundo_path(world, target)
    if full is not None and full.exists():
        suggested = suggest_free_slug(full)
        collision = {
            "target": target,
            "suggested_slug": suggested.stem,
            "suggested_target": f"{section}/{folder}/{suggested.stem}.md"
            if folder else f"{section}/{suggested.stem}.md",
        }
        return target, target_info, collision
    return target, target_info, None


# Idea media allowlist (mirrors the ideas media route, ideas_bank_router.py:175).
_IDEA_IMAGE_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})


def _resolve_materialize_image(
    idea: object, *, media_dir: Path, world_dir: Path, file_slug: str,
) -> dict[str, str] | None:
    """Resolve an idea's image to a free world-relative destination (READ ONLY).

    Returns ``{"source": <bare name>, "dest": "media/<name><ext>"}`` when the
    idea carries a usable image, else ``None``. Every failure degrades to
    "no image" (logged, never raised): no ``media_path``, a path that is not a
    bare ``media/<name>`` (traversal/separators/empty), a non-allowlisted
    extension, or a missing/non-file source. The destination is ``file_slug``
    plus the source extension; when ``<world_dir>/wiki/media/<name>`` already
    exists the next free ``-2``, ``-3``, … name is picked via
    ``suggest_free_slug``. This is a read-only check: it never creates the
    media directory or writes a byte (R-IM-04).
    """
    media_path = getattr(idea, "media_path", None)
    if not isinstance(media_path, str) or not media_path.startswith("media/"):
        return None
    source_name = media_path[len("media/"):]
    if (not source_name or "/" in source_name or "\\" in source_name
            or ".." in source_name):
        logger.warning("materialize-preview: unsafe idea media_path %r; treating as no image", media_path)
        return None
    if Path(source_name).suffix.lower() not in _IDEA_IMAGE_EXTENSIONS:
        logger.warning("materialize-preview: non-image idea media_path %r; treating as no image", media_path)
        return None
    source = media_dir / source_name
    if not source.is_file():
        logger.warning("materialize-preview: missing idea media file %s; treating as no image", source)
        return None
    dest_path = world_dir / "wiki" / "media" / f"{file_slug}{Path(source_name).suffix}"
    if dest_path.exists():
        dest_path = suggest_free_slug(dest_path)
    return {"source": source_name, "dest": f"media/{dest_path.name}"}


def _copy_materialize_image(pending: dict[str, Any], mundo: str) -> None:
    """Copy a pending idea image into the world at confirm time (fail closed).

    Runs after the principal/target/content/digest verification and before the
    first canon write. Raises 409 (naming the image) when the destination
    appeared after preview, the source is gone, or the copy fails, so NOTHING
    is written and the proposal is not consumed; the user re-previews to pick a
    new name. A plain ``shutil.copyfile`` byte copy — an orphan image left by a
    later ``_write_content`` failure is acceptable and harmless.
    """
    media = pending.get("media")
    if media is None:
        return
    source_name = str(media.get("source") or "")
    dest_rel = str(media.get("dest") or "")
    dest_name = Path(dest_rel).name
    world_dir = _resolve_mundo_dir(mundo)
    if (not source_name or "/" in source_name or "\\" in source_name or ".." in source_name
            or dest_rel != f"media/{dest_name}" or not dest_name or world_dir is None):
        raise HTTPException(status_code=409, detail=f"Imagen de la idea inválida: {source_name or dest_rel}")
    dest_path = world_dir / "wiki" / "media" / dest_name
    if dest_path.exists():
        raise HTTPException(
            status_code=409,
            detail=f"La imagen de destino ya existe: {dest_rel}. Vuelve a previsualizar para elegir otro nombre.",
        )
    source_path = IdeasBank()._ideas_root / "media" / source_name
    if not source_path.is_file():
        raise HTTPException(
            status_code=409,
            detail=f"No se encuentra la imagen de la idea: {source_name}. Vuelve a previsualizar.",
        )
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, dest_path)
    except Exception as exc:  # noqa: BLE001 — any copy failure must abort the write
        raise HTTPException(
            status_code=409,
            detail=f"No se pudo copiar la imagen de la idea '{source_name}': {exc}",
        )


@app.post("/api/ideas/{slug}/materialize-preview")
async def materialize_preview(slug: str, body: IdeaMaterializePreviewRequest, request: Request):
    """Preview materializing a global-bank idea into a world ficha (R-IM-01..09).

    Builds a server-owned ficha skeleton, grounds Hermes on the world's
    existing canonical entities, strictly validates the AI envelope (fail
    closed), and stores an in-memory pending proposal for the existing
    confirmation-gated create route. ZERO canon writes happen here (R-IM-04);
    the first filesystem write is inside ``_write_content`` after a redeemed
    single-use token. The provider runs exactly one Hermes run.
    """
    if _resolve_principal(request) is None:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    principal = _resolve_principal(request)
    _prune_materialize_proposals()
    bank = IdeasBank()
    try:
        idea = bank.read(slug)
    except IdeaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    mundo_dir = _resolve_mundo_dir(body.world)
    if mundo_dir is None:
        raise problem("world.not_found")
    if body.section not in _MATERIALIZE_SECTIONS:
        raise HTTPException(status_code=400, detail="Sección no fichable")
    folder = body.folder
    if folder:
        if Path(folder).is_absolute() or ".." in Path(folder).parts:
            raise HTTPException(status_code=400, detail="Path traversal detectado")
        # Defense-in-depth: the folder must resolve inside the world section
        # with the canonical containment semantics of _resolve_mundo_path.
        if _resolve_mundo_path(body.world, f"{body.section}/{folder}") is None:
            raise HTTPException(status_code=400, detail="Path traversal detectado")
    provider = _MATERIALIZE_PROVIDER
    if provider is None:
        logger.warning("materialize-preview: provider unavailable; fail closed")
        return JSONResponse(status_code=503, content={"status": "unavailable", "retryable": True})
    idx = _get_graph(body.world)
    if idx is None:
        raise problem("world.not_found")
    reader = _GuidedGraphReader(idx)
    # Graph-aware grounding (materialize-graph-grounding): seed from the idea
    # TITLE, broaden with a bounded body excerpt, then expand one hop. The
    # domain bounds the body itself (BODY_EXCERPT_CHARS); the payload budget is
    # only a guard, never a target.
    candidates = build_grounding_candidates(reader, idea_title=idea.title, idea_body=idea.body)
    # FT-1: the resolved ficha title (client title > idea title > idea slug,
    # whitespace-collapsed) owns BOTH the frontmatter title and the body H1.
    # The filename derives from it unless a client slug overrides it. The
    # provider request keeps its original idea-derived `title`/`slug` untouched
    # (the prompt is protected; the AI's own H1 is discarded by the skeleton).
    ficha_title = _resolve_ficha_title(body.title, idea.title, idea.slug)
    file_slug = resolve_file_slug(ficha_title, idea.slug, body.slug)
    title = (idea.title or "").strip() or idea.slug
    # CI-1: carry the idea's image. Read-only resolution here; the bytes are
    # copied only at confirm, so a missing/unusable image degrades to no image.
    media = _resolve_materialize_image(
        idea, media_dir=bank._ideas_root / "media", world_dir=mundo_dir, file_slug=file_slug,
    )
    request_id = f"materialize-{uuid.uuid4().hex}"
    materialize_request = MaterializationRequest(
        protocol_version=MATERIALIZATION_PROTOCOL_VERSION,
        request_id=request_id,
        session_id=request_id,  # stateless single-shot preview: identity = run id
        world=body.world,
        section=body.section,
        folder=folder,
        slug=idea.slug,
        title=title,
        idea_type=idea.type,
        idea_body=idea.body,
        tags=tuple(idea.tags),
        candidates=tuple(candidates),
        title_hint=body.title_hint,
        deadline_ms=DEADLINE_MS,
    )
    cancellation = MaterializationCancellationToken()
    try:
        call = (
            provider.invoke(materialize_request, cancellation)
            if hasattr(provider, "invoke") else provider(materialize_request, cancellation)
        )
        raw = await asyncio.wait_for(call, DEADLINE_MS / 1000)
    except asyncio.TimeoutError:
        cancellation.cancel()
        logger.warning("materialize-preview: provider timed out; fail closed")
        return _guided_error_response(StructuredError(
            ErrorCode.TIMEOUT, "The materialization provider timed out.", True,
        ))
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("materialize-preview: provider unavailable/invalid; fail closed")
        return _guided_error_response(StructuredError(
            ErrorCode.PROVIDER_UNAVAILABLE, "The materialization provider is unavailable.", True,
        ))
    parsed = MaterializationResponse.from_provider(raw, materialize_request)
    if parsed is None:
        logger.warning("materialize-preview: provider returned malformed output; fail closed")
        return _guided_error_response(StructuredError(
            ErrorCode.MALFORMED_OUTPUT, "The provider returned an invalid response.", True,
        ))
    kept_relations, discarded_relations = validate_relations(parsed.relations, _materialize_existing_ids(reader))
    content = build_ficha_skeleton(
        world_dir=mundo_dir,
        section=body.section,
        folder=folder,
        slug=file_slug,
        idea_slug=idea.slug,
        title=ficha_title,
        body=parsed.body,
        relations=kept_relations,
        image_rel=media["dest"] if media is not None else None,
    )
    target, target_info, collision = _resolve_materialize_target(
        world=body.world, section=body.section, folder=folder, file_slug=file_slug,
    )
    if collision is not None:
        # AD5: 409 with the additive suggestion payload (the existing 409
        # strings are never altered). JSONResponse keeps ``collision`` at the
        # top level exactly as the design pins it.
        return JSONResponse(status_code=409, content={"detail": "El archivo ya existe", "collision": collision})
    now = datetime.now(timezone.utc)
    proposal_id = f"materialize-{uuid.uuid4().hex}"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    _MATERIALIZE_PENDING_PROPOSALS[proposal_id] = {
        "proposal_id": proposal_id,
        "principal_id": principal.id,
        "world": body.world,
        "section": body.section,
        "folder": folder,
        "slug": idea.slug,
        "file_slug": file_slug,
        "title": ficha_title,
        "target": target,
        "content": content,
        "digest": digest,
        "operation_id": f"materialize-create-{proposal_id}",
        "created_at": now,
        "expires_at": now + timedelta(seconds=_MATERIALIZE_TTL_SECONDS),
        # CI-1: bare source filename + world-relative dest (never absolute).
        **({"media": {"source": media["source"], "dest": media["dest"]}} if media is not None else {}),
    }
    title_by_id = {candidate["id"]: candidate["title"] for candidate in candidates}
    logger.info(
        "materialize-preview: world=%s target=%s candidates=%d relations=%d discarded=%d",
        body.world, target, len(candidates), len(kept_relations), len(discarded_relations),
    )
    response = {
        "proposal_id": proposal_id,
        "title": ficha_title,
        "target": target_info,
        "content": content,
        "proposed_relations": [
            {"target_id": rel.target_id, "title": title_by_id.get(rel.target_id, ""), "rel_type": rel.rel_type}
            for rel in kept_relations
        ],
        "discarded_relations": discarded_relations,
    }
    if media is not None:
        response["media"] = {
            "src": f"/api/ideas/media/{media['source']}",
            "dest": media["dest"],
        }
    return response


@app.post("/api/ideas/{slug}/materialize-target")
def materialize_target(slug: str, body: IdeaMaterializeTargetRequest, request: Request):
    """Resolve the destination ficha path + collision for a materialize (no AI).

    Instant, provider-free counterpart to ``materialize-preview``: it runs the
    same auth/world/section/traversal validation and returns the resolved
    target (200) or the existing-file collision (409), so the UI can reveal the
    destination before paying for a generation. It performs no provider call,
    no graph build, no canon write and no pending-proposal store mutation
    (resolution only; R-IM-04 preserved).
    """
    if _resolve_principal(request) is None:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    try:
        idea = IdeasBank().read(slug)
    except IdeaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if _resolve_mundo_dir(body.world) is None:
        raise problem("world.not_found")
    if body.section not in _MATERIALIZE_SECTIONS:
        raise HTTPException(status_code=400, detail="Sección no fichable")
    folder = body.folder
    if folder:
        if Path(folder).is_absolute() or ".." in Path(folder).parts:
            raise HTTPException(status_code=400, detail="Path traversal detectado")
        # Defense-in-depth: the folder must resolve inside the world section
        # with the canonical containment semantics of _resolve_mundo_path.
        if _resolve_mundo_path(body.world, f"{body.section}/{folder}") is None:
            raise HTTPException(status_code=400, detail="Path traversal detectado")
    # FT-1: resolve the server-owned ficha title (client title > idea title >
    # idea slug); the filename derives from it unless a client slug overrides.
    ficha_title = _resolve_ficha_title(body.title, idea.title, idea.slug)
    file_slug = resolve_file_slug(ficha_title, idea.slug, body.slug)
    _target, target_info, collision = _resolve_materialize_target(
        world=body.world, section=body.section, folder=folder, file_slug=file_slug,
    )
    if collision is not None:
        return JSONResponse(status_code=409, content={"detail": "El archivo ya existe", "collision": collision})
    return {"title": ficha_title, "target": target_info}


app.include_router(
    create_assistant_settings_router(
        require_principal=lambda request: _resolve_principal(request),
        # ONB-3.6: a successful three-proof save records its runtime acceptance
        # in the local registry so the readiness badge may become configured
        # only on real acceptance (pending/no-apto otherwise).
        on_acceptance=_record_assistant_acceptance,
        # Real runtime truth: the state is derived on every read from a
        # read-only gateway liveness probe plus the persisted acceptance for the
        # revision, so a server restart no longer degrades "Activo" to a lie.
        runtime_state_resolver=_resolve_assistant_runtime_state,
        runtime_liveness=lambda: _assistant_gateway_probe().is_running(),
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
        mundos_dir=lambda: _mundos_dir(),
        evidence_dir=lambda: _project_root() / "data" / "migration-evidence",
    ),
)

# System control — UI-driven restart/shutdown (/api/system). The launcher is
# dispatched DETACHED (Popen + start_new_session): the server answers 200
# before the launcher stops/restarts the stack, and shutdown kills this very
# process only after the response is flushed. Immediate launcher failures
# (bad path, permission) surface via a short non-blocking peek. The local
# session is NOT closed server-side — the client logs out first (S-2.5/S-3.4).
#
# The launcher path comes from the frozen layout contract (S0-C) per OS:
# POSIX ships ``scripts/start-demiurgos.sh``, Windows ships
# ``scripts/start-demiurgos.ps1``. The resolved path is validated at BOOT:
# if it does not exist, /api/system reports a clear error instead of ever
# dispatching a stale path (S2-7).
def _system_launcher_path() -> Path:
    if os.name == "nt":
        return _CODE_ROOT / "scripts" / "start-demiurgos.ps1"
    return _CODE_ROOT / "scripts" / "start-demiurgos.sh"


_SYSTEM_LAUNCHER = _system_launcher_path()
_SYSTEM_LAUNCHER_AVAILABLE = _SYSTEM_LAUNCHER.is_file()
if not _SYSTEM_LAUNCHER_AVAILABLE:
    logger.warning(
        "System launcher missing at %s; /api/system restart/shutdown will fail closed",
        _SYSTEM_LAUNCHER,
    )

app.include_router(
    create_system_control_router(
        require_principal=lambda request: _resolve_principal(request),
        launcher_path=_SYSTEM_LAUNCHER,
        launcher_available=_SYSTEM_LAUNCHER_AVAILABLE,
    ),
)

# Slice 2 — synchronous Hermes bridge for the (optional) importer enricher.
#
# The importer module is gateway-independent; the composition layer in this
# file is the only place that talks to the Hermes gateway for the importer.
# The bridge runs the SYNCHRONOUS ``_run_hermes_sync`` (a fresh per-call
# ``httpx.Client``, never the module-level async singleton) on a worker thread
# with the extended 120-second total budget (``DEFAULT_TIMEOUT_SECONDS`` —
# design risk 4: large per-ficha summaries and the relationship batch need the
# extended budget), returns ``""`` on budget timeout, and returns the
# localized ``unavailable_copy`` when the gateway is unreachable so the
# importer's fail-open contract holds end-to-end. The sync path never reuses
# the async client singleton, so the bridge is safe to run from FastAPI's
# sync-endpoint threadpool (the old ``asyncio.run`` bridge crashed with a
# cross-event-loop RuntimeError that was silently swallowed, masking every
# import-card enrichment).
def _sync_hermes_enricher(prompt: str, session_id: str) -> str:
    """Synchronous Hermes bridge honoring the extended total budget.

    Runs ``_run_hermes_sync`` on a worker thread so the extended total budget
    can be enforced synchronously: a call exceeding ``DEFAULT_TIMEOUT_SECONDS``
    returns ``""`` (the importer treats it as "no suggestions"), and gateway
    failures surface as the localized unavailable copy. The bridge never
    raises and never touches the async client singleton.

    The gateway call is ABORTED, not abandoned, on budget timeout: the shared
    ``httpx.Client`` is closed from this thread (closing a client tears down
    its in-flight requests), so the worker thread exits in seconds instead of
    billing Hermes in the background until the gateway's own timeout — that
    background billing was the double-spend: the funnel fail-opened and
    re-asked while the original call was still running. ``future.cancel()`` is
    best-effort; the client close is what actually stops the call.
    """
    import concurrent.futures
    from import_enrichment import DEFAULT_TIMEOUT_SECONDS
    client = httpx.Client(
        headers={"Content-Type": "application/json", **_gateway_headers()},
        timeout=httpx.Timeout(_GATEWAY_TIMEOUT, connect=10.0),
    )
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(_run_hermes_sync, prompt, session_id, client=client)
        return future.result(timeout=DEFAULT_TIMEOUT_SECONDS)
    except TimeoutError:
        logger.warning("hermes enricher timed out after %.1fs; aborting in-flight gateway call",
                       DEFAULT_TIMEOUT_SECONDS)
        client.close()  # aborts the in-flight request; the worker thread dies in seconds
        future.cancel()  # best-effort — the task is usually already running
        return ""
    finally:
        client.close()  # idempotent; also covers the success/unreachable paths
        pool.shutdown(wait=False)


def _make_import_enricher():
    """Compose the Hermes enrichment-funnel callable for the import router.

    importador-auto-frontmatter (Phase 2): the enricher runs the funnel —
    per-ficha summaries (Step 2), one batched canonical-id relationship pass
    (Step 3), and type/frontmatter with manual fallback (Step 4) — instead of
    the legacy one-shot classification batch. Enrichment is OPT-IN (the
    request must set ``enrich=true``). Failures (timeout, unavailable copy,
    malformed JSON, vocabulary rejection) leave the candidates reviewable with
    ``manual``/``fallback`` frontmatter so the import succeeds deterministically.
    """
    from import_enrichment import analyze_ficha_funnel as _funnel

    def enricher(candidates, progress_cb=None, on_phase=None, should_cancel=None):
        return _funnel(candidates, hermes_runner=_sync_hermes_enricher,
                       progress_cb=progress_cb, on_phase=on_phase,
                       should_cancel=should_cancel)

    return enricher


def _make_structure_inference():
    """Compose the concrete Hermes H1-H5 structure-inference callable.

    Wired to the deterministic splitter's Step 0 fallback seam (task 1.2):
    consulted ONLY when the deterministic heading scan finds no headings. The
    callable asks Hermes for a JSON ``headings`` array and converts each entry
    into a ``HeadingSpan``; on any failure it returns ``[]`` so the splitter
    falls back to a single implicit ficha (fail-open — the import path never
    blocks on inference).
    """
    from import_analysis import HeadingSpan

    def structure_inference(text: str) -> list:
        import asyncio
        from import_enrichment import DEFAULT_TIMEOUT_SECONDS

        prompt = json.dumps({
            "task": "structure_inference",
            "instructions": (
                "Infer the H1-H5 heading structure of the supplied document "
                "text (it has no detectable markdown headings). Return a JSON "
                "object with a 'headings' array; each entry has 'level' "
                "(integer 1-5) and 'title' (the heading text). Preserve "
                "document order and original titles verbatim. Return an empty "
                "array if the text has no discernible structure."
            ),
            "text": (text or "")[:8000],
        }, ensure_ascii=False)
        try:
            raw = asyncio.run(
                asyncio.wait_for(_run_hermes(prompt, "import-structure"),
                                 timeout=DEFAULT_TIMEOUT_SECONDS))
        except Exception:  # noqa: BLE001 — inference is optional, fail-open
            return []
        try:
            data = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        except (TypeError, ValueError):
            return []
        entries = data.get("headings", []) if isinstance(data, dict) else []
        if not isinstance(entries, list):
            return []
        spans: list = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            level = entry.get("level")
            title = entry.get("title")
            if not isinstance(level, int) or not isinstance(title, str) or not title.strip():
                continue
            title = title.strip()
            spans.append(HeadingSpan(
                level=max(1, min(5, level)),
                title=title,
                source_text=f"{'#' * level} {title}",
                line_index=-1,  # synthetic — inferred spans have no source line
            ))
        return spans

    return structure_inference


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

    Vision is DISABLED for dense lore import by default: the import
    placement already carries the DOCX position contract, so describing each
    image adds a huge LLM cost (one multimodal call per image) the author
    does not need for placement. Set ``DEMIURGOS_IMPORT_VISION=1`` to re-enable
    it for future point-image analysis without touching any other code. The
    ``import_vision`` machinery and the ``capability`` gate stay intact.
    """
    # Reversible opt-in: default OFF for dense import; set the env var to
    # re-enable image-content analysis for point use-cases later.
    if os.getenv("DEMIURGOS_IMPORT_VISION", "0") != "1":
        return None
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
        """Seam adapter: candidates + media bundle -> candidates + suggestions."""
        if not candidates or not media_entries:
            return candidates
        try:
            results = analyze_images([m.image for m in media_entries], "")
        except Exception as exc:  # noqa: BLE001 — vision is advisory, fail-open
            logger.warning("vision adapter raised during analyze: %s", exc)
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
        mundos_dir=lambda: _mundos_dir(),
        spool_dir=lambda: _project_root() / "data" / "import-spool",
        store=_import_store,
        on_list=_maybe_reap_spool,
        enricher=_make_import_enricher(),
        vision=_make_vision_callable(),
        structure_inference=_make_structure_inference(),
        # BLOQUE 3 — collision detection seam: expose the world's graph link
        # resolver when the index exists, else None (fail-open → checks
        # skipped). ``_get_graph`` lazily builds/returns the cached index.
        graph_resolver=lambda mundo: (
            _get_graph(mundo)._resolve_link_candidates
            if _get_graph(mundo) else None
        ),
        # NOTE (WU-2): ``store=_import_store`` and the service below are
        # materialized while this module is imported, because
        # ``import_router.create_import_router`` calls the store factory itself
        # (``_store = ... else store()``). Deferring it would require rewriting
        # that router's ~20 store call sites, which is outside this work unit.
        # The suite is safe because ``tests/conftest.py`` exports a hermetic
        # DEMIURGOS_DATA_ROOT before any test module is imported.
        service=ImportService(
            store=_import_store(),
            mundos_dir=_mundos_dir(),
            spool_dir=_project_root() / "data" / "import-spool",
            read_file=lambda rel: (
                (_project_root() / "data" / "import-spool" / rel).read_text(
                    encoding="utf-8") if rel else ""),
            graph_reconcile=lambda rel, mundo: _reconcile_import_graph(rel, mundo),
            graph_reconcile_many=_reconcile_import_graph_many,
            register_gallery=_register_import_gallery,
            inter_doc_post_process=_run_inter_doc_post_process,
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

@app.get("/api/methodologies/published/{skill_id}/{version}")
def methodology_published_detail(skill_id: str, version: str, request: Request):
    """Full published version + source (TW13 original render for adaptation).

    The inventory omits ``source`` by design; this detail route exists so the
    adaptation compare view and the derive flow can read the original
    published source. Also exposes the server-injected TW14 provenance
    (``parent_skill_id``/``parent_version``) when the version is itself a
    derived publish (REQ-CC-21). ``adjuntos`` is exposed as additive
    metadata-only pins (``path``/``sha256``/``bytes``/``nivel``, R14) — carrier
    bytes are never served here. Read-only GET; never mutates state.
    """
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    library = _methodology_library()
    published = library.get_published(skill_id, version)
    if published is None:
        return JSONResponse(status_code=404, content={"detail": "Metodología no encontrada"})
    return {
        "skill_id": published.skill_id,
        "version": published.version,
        "name": published.name,
        "description": published.description,
        "phases": list(published.phases),
        "language": published.language,
        "source": published.source,
        "digest": published.digest,
        "published_at": published.published_at,
        "taller": published.taller,
        "talleres_compatibles": list(published.talleres_compatibles),
        "categoria_funcional": published.categoria_funcional,
        "etiquetas": list(published.etiquetas),
        "clasificacion": published.clasificacion,
        "trust_attributes": list(published.trust_attributes),
        "parent_skill_id": published.parent_skill_id,
        "parent_version": published.parent_version,
        # Additive metadata-only pins (R14): absent/empty -> [].
        "adjuntos": [entry.as_dict() for entry in published.adjuntos],
    }


@app.get("/api/methodologies/published/{skill_id}/{version}/adjunto/{path:path}")
def methodology_published_adjunto(skill_id: str, version: str, path: str, request: Request):
    """Serve one pinned carrier as raw markdown for the read-only viewer (R14).

    The requested ``path`` is matched EXACTLY against the published record's
    ``adjuntos`` pins — it is never used for direct filesystem resolution, so a
    traversal or absolute prefix that is not a recorded pin simply 404s. A
    known pin is re-verified on every serve through ``carrier_root_for`` +
    ``read_adjunto_text`` (containment, existence, SHA-256, byte length, and
    UTF-8); a missing, drifted, or undecodable carrier fails closed with 422
    ``attachment_unavailable`` without leaking the path, hash, or carrier root.
    Unlike the text-injection seam, the 3072-token budget is deliberately NOT
    applied: the viewer must present the complete exemplar. Read-only GET;
    never mutates state.
    """
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    library = _methodology_library()
    published = library.get_published(skill_id, version)
    if published is None:
        return JSONResponse(status_code=404, content={"detail": "Metodología no encontrada"})
    pin = next((entry for entry in published.adjuntos if entry.path == path), None)
    if pin is None:
        return JSONResponse(status_code=404, content={"detail": "Adjunto no encontrado"})
    seed_dir = carrier_root_for(published.skill_id, project_root=_project_root())
    text = read_adjunto_text(seed_dir, pin)
    if text is None:
        return JSONResponse(status_code=422, content={
            "detail": "A pinned attachment is unavailable or has drifted.",
            "code": "attachment_unavailable",
        })
    filename = Path(pin.path).name
    return Response(
        content=text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


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
            "taller": item.taller,
            "talleres_compatibles": list(item.talleres_compatibles),
            "categoria_funcional": item.categoria_funcional,
            "etiquetas": list(item.etiquetas),
            "clasificacion": item.clasificacion,
            "trust_attributes": list(item.trust_attributes),
            # TW14: server-injected provenance on list surfaces (REQ-CC-21) —
            # read from the stored published record, never from client input.
            "parent_skill_id": item.parent_skill_id,
            "parent_version": item.parent_version,
            # Additive metadata-only pins (R15): absent/empty -> [].
            "adjuntos": [entry.as_dict() for entry in item.adjuntos],
        }
        for item in library.list_published()
    ]
    activations = {}
    for world in _known_worlds():
        # Status keeps the guided-character projection (D4): the UI parses
        # ``activations[world]`` as the guided slot; ``flow_type`` is additive.
        activation = library.active_for(world, GUIDED_CHARACTER_FLOW)
        if activation is not None:
            activations[world] = {
                "world": activation.world,
                "skill_id": activation.skill_id,
                "version": activation.version,
                "digest": activation.digest,
                "activated_at": activation.activated_at,
                "flow_type": activation.flow_type,
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
            "trigger_approval": _trigger_approval_dict(draft.trigger_approval),
        }
        for draft in library.list_drafts()
    ]
    # Additive companions map (world -> entries). Only worlds with at least
    # one companion appear; empty world keys are dropped by the library on the
    # last removal, and list_companions tolerates a missing key.
    companions = {}
    for world in _known_worlds():
        world_companions = library.list_companions(world)
        if not world_companions:
            continue
        companions[world] = []
        for companion in world_companions:
            published_record = library.get_published(companion.skill_id, companion.version)
            companions[world].append({
                "world": companion.world,
                "skill_id": companion.skill_id,
                "version": companion.version,
                "description": published_record.description if published_record is not None else "",
                "activated_at": companion.activated_at,
            })
    return {
        "published": published,
        "activations": activations,
        "drafts": drafts,
        "companions": companions,
    }


@app.get("/api/methodologies/inventory")
def methodologies_inventory(
    clasificacion: str | None = None,
    categoria_funcional: str | None = None,
    taller: str | None = None,
    etiquetas: str | None = None,
    fundacional: bool = False,
):
    """Read-only inventory of ALL loaded skills (activated or not).

    Taller de Herramientas TW7 catalog surface. Filters are conjunctive (AND):
    ``clasificacion`` and ``taller`` match exactly; ``categoria_funcional`` and
    each comma-separated ``etiquetas`` token match case-insensitively by
    substring; ``fundacional=true`` restricts to server-seeded foundational
    skills (a trust attribute — by the G14 invariant these are always also
    ``Oficiales``). No auth required (public read, consistent with the read-only
    catalog policy) and the GET never mutates state.
    """
    library = _methodology_library()
    items = []
    for published in library.list_published():
        if clasificacion and published.clasificacion != clasificacion:
            continue
        if (
            categoria_funcional
            and categoria_funcional.strip().lower()
            not in (published.categoria_funcional or "").lower()
        ):
            continue
        if taller and published.taller != taller:
            continue
        if etiquetas:
            required = [
                tag.strip().lower() for tag in etiquetas.split(",") if tag.strip()
            ]
            item_tags = [str(tag).lower() for tag in published.etiquetas]
            if not all(any(req in tag for tag in item_tags) for req in required):
                continue
        if fundacional and FOUNDATIONAL not in published.trust_attributes:
            continue
        items.append({
            "skill_id": published.skill_id,
            "version": published.version,
            "name": published.name,
            "description": published.description,
            "digest": published.digest,
            "published_at": published.published_at,
            "taller": published.taller,
            "talleres_compatibles": list(published.talleres_compatibles),
            "categoria_funcional": published.categoria_funcional,
            "etiquetas": list(published.etiquetas),
            "clasificacion": published.clasificacion,
            "trust_attributes": list(published.trust_attributes),
            # TW14: server-injected provenance on list surfaces (REQ-CC-21) —
            # read from the stored published record, never from client input.
            "parent_skill_id": published.parent_skill_id,
            "parent_version": published.parent_version,
        })
    return {"items": items}


def _known_worlds() -> list[str]:
    return [entry.name for entry in sorted(_mundos_dir().iterdir()) if entry.is_dir()
            and not entry.name.startswith((".", "_")) and entry.name != "Ideas"]


@app.post("/api/methodologies/drafts")
def methodologies_create_draft(body: MethodologyDraftRequest, request: Request):
    """Create an editable draft. The compiler validates it on publish.

    ``clasificacion`` and ``trust_attributes`` are SERVER-derived (S7): a
    client claim is rejected with 400 before any draft is created. Omission,
    ``null``, and ``[]`` stay valid (S8) — ``create_draft`` receives no trust
    fields and the published record lands ``Personalizadas`` with no trust
    attributes (local-author semantics, G14).
    """
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    if body.clasificacion is not None or body.trust_attributes:
        return JSONResponse(status_code=400, content={
            "detail": "clasificacion and trust_attributes are server-derived; "
                      "client claims are not allowed.",
            "code": "client_trust_claim_not_allowed",
        })
    library = _methodology_library()
    draft_id = library.create_draft(
        skill_id=body.skill_id,
        version=body.version,
        name=body.name,
        source=body.source,
        description=body.description,
        phases=tuple(body.phases or []),
        language=body.language,
        taller=body.taller,
        categoria_funcional=body.categoria_funcional,
        etiquetas=tuple(body.etiquetas or []),
        adjuntos=tuple(
            AttachmentEntry(path=e.path, sha256=e.sha256, bytes=e.bytes, nivel=e.nivel)
            for e in body.adjuntos
        ),
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
        "taller": draft.taller,
        "categoria_funcional": draft.categoria_funcional,
        "etiquetas": list(draft.etiquetas),
        "clasificacion": draft.clasificacion,
        "trust_attributes": list(draft.trust_attributes),
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
    except AttachmentLimitError as exc:
        # R2: adjuntos overflow/oversize — 422 BEFORE the generic
        # ValidationError handler so the code stays distinct.
        return JSONResponse(status_code=422, content={
            "detail": str(exc), "code": "attachment_limit_reached",
        })
    except ValidationError as exc:
        return JSONResponse(status_code=422, content={
            "detail": str(exc), "code": "validation_error",
        })
    except AlreadyPublishedError as exc:
        return JSONResponse(status_code=409, content={
            "detail": str(exc), "code": "already_published",
        })
    except TriggerNotApprovedError as exc:
        # Etapa 2 (TD-D): MUST precede the generic MethodologyLibraryError
        # handler below — TriggerNotApprovedError subclasses it, and the generic
        # handler maps everything else to ``reserved_skill_id``. Placing this
        # after would mislabel a gate refusal.
        return JSONResponse(status_code=409, content={
            "detail": str(exc), "code": "trigger_not_approved",
        })
    except MethodologyLibraryError as exc:
        # REQ-IMP-6: the reserved id belongs to the foundational character
        # skill — an import-derived draft can never publish it. All other
        # library errors are caught above.
        return JSONResponse(status_code=409, content={
            "detail": str(exc), "code": "reserved_skill_id",
        })
    payload = {
        "skill_id": published.skill_id,
        "version": published.version,
        "name": published.name,
        "description": published.description,
        "digest": published.digest,
        "published_at": published.published_at,
    }
    # Conditional echo (4.2): the response gains ``adjuntos`` only when entries
    # exist, so pre-PR③ payloads stay byte-identical.
    if published.adjuntos:
        payload["adjuntos"] = [entry.as_dict() for entry in published.adjuntos]
    return payload


@app.post("/api/methodologies/drafts/{draft_id}/trigger/approve")
def methodologies_approve_trigger(
    draft_id: str, body: TriggerApproveRequest, request: Request,
):
    """Record the Author's explicit approval of a draft's trigger (Etapa 2).

    The library normalizes and re-validates the bound (server-authoritative),
    then writes the approved value as the draft description AND the auditable
    approval sub-record in one atomic save (TD-B) — so the approved value is
    the value publish will use.
    """
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    library = _methodology_library()
    try:
        approval = library.approve_trigger(draft_id, body.description, principal.id)
    except KeyError:
        return JSONResponse(status_code=404, content={"detail": "The draft is unavailable."})
    except TriggerInvalidError as exc:
        return JSONResponse(status_code=422, content={
            "detail": str(exc), "code": "trigger_invalid",
        })
    return {"trigger_approval": _trigger_approval_dict(approval)}


@app.post("/api/methodologies/activate")
def methodologies_activate(body: MethodologyActivateRequest, request: Request):
    """Pin a published methodology version to a world's flow slot (SR1).

    Per-flow (``body.flow_type``, default guided-character); unknown/empty
    flow types fail as 422 BEFORE any library call, so a rejected request
    never mutates any slot.
    """
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    if _resolve_mundo_dir(body.world) is None:
        return JSONResponse(status_code=404, content={"detail": "Mundo no encontrado"})
    if body.flow_type not in SUPPORTED_FLOW_TYPES:
        return JSONResponse(status_code=422, content={
            "detail": f"unsupported flow type {body.flow_type!r}",
            "code": "unsupported_flow_type",
        })
    library = _methodology_library()
    try:
        activation = library.activate(body.world, body.skill_id, body.version, body.flow_type)
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
        "flow_type": activation.flow_type,
    }


@app.get("/api/methodologies/active/{world}")
def methodologies_active(world: str, request: Request, flow_type: str = DEFAULT_FLOW_TYPE):
    """Read a world's active methodology for one flow slot (SR1, D4).

    Mirrors the slot routes' prelude (401 unauth / 404 unknown world) and
    rejects unknown/empty flow types with 422 before any library call. The
    response echoes the requested flow; ``activation`` is ``None`` when the
    slot is empty.
    """
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    if _resolve_mundo_dir(world) is None:
        return JSONResponse(status_code=404, content={"detail": "Mundo no encontrado"})
    if flow_type not in SUPPORTED_FLOW_TYPES:
        return JSONResponse(status_code=422, content={
            "detail": f"unsupported flow type {flow_type!r}",
            "code": "unsupported_flow_type",
        })
    activation = _methodology_library().active_for(world, flow_type)
    if activation is None:
        return {"world": world, "flow_type": flow_type, "activation": None}
    return {
        "world": world,
        "flow_type": flow_type,
        "activation": {
            "world": activation.world,
            "skill_id": activation.skill_id,
            "version": activation.version,
            "digest": activation.digest,
            "activated_at": activation.activated_at,
            "flow_type": activation.flow_type,
        },
    }


@app.post("/api/{mundo}/methodologies/native-channel")
def methodologies_native_channel(mundo: str, body: NativeChannelRequest, request: Request):
    """Set a world's native-channel opt-in flag and reconcile the toolset (REQ-NC-2/3).

    Minimal auth-gated surface (design §4): mirrors ``methodologies_active``'s
    prelude (401 unauth / 404 unknown world). Persists the flag through
    ``library.set_native_channel`` and reconciles the dedicated profile toolset
    through ``_sync_native_channel`` (idempotent, probe-gated, REQ-NC-3).
    Adds no behavior beyond enabling/disabling the channel; the flag flip OFF
    restores the legacy projection immediately (rollback boundary).
    """
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    if _resolve_mundo_dir(mundo) is None:
        return JSONResponse(status_code=404, content={"detail": "Mundo no encontrado"})
    library = _methodology_library()
    library.set_native_channel(mundo, bool(body.enabled))
    _sync_native_channel(mundo)
    return {
        "world": mundo,
        "native_channel": library.native_channel_enabled(mundo),
    }


@app.post("/api/methodologies/rollback")
def methodologies_rollback(body: MethodologyRollbackRequest, request: Request):
    """Roll back a world's flow slot to its previous version (SR1).

    Per-flow (``body.flow_type``, default guided-character); gains the
    world-404 prelude for parity with the other slot routes. Empty slots clear
    idempotently and echo the requested flow; unknown/empty flow types fail as
    422 before any library call.
    """
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    if _resolve_mundo_dir(body.world) is None:
        return JSONResponse(status_code=404, content={"detail": "Mundo no encontrado"})
    if body.flow_type not in SUPPORTED_FLOW_TYPES:
        return JSONResponse(status_code=422, content={
            "detail": f"unsupported flow type {body.flow_type!r}",
            "code": "unsupported_flow_type",
        })
    library = _methodology_library()
    activation = library.rollback(body.world, body.flow_type)
    if activation is None:
        return {"world": body.world, "flow_type": body.flow_type,
                "skill_id": None, "version": None, "digest": None, "activated_at": None}
    return {
        "world": activation.world,
        "flow_type": activation.flow_type,
        "skill_id": activation.skill_id,
        "version": activation.version,
        "digest": activation.digest,
        "activated_at": activation.activated_at,
    }


@app.post("/api/methodologies/deactivate")
def methodologies_deactivate(body: MethodologyDeactivateRequest, request: Request):
    """Clear a world's flow slot (SR1), per-flow.

    Mirrors the rollback prelude exactly (401 unauth / 404 unknown world /
    422 unsupported flow type before any library call). Deactivating an
    already-empty slot is idempotent: the cleared echo is returned either way.
    """
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    if _resolve_mundo_dir(body.world) is None:
        return JSONResponse(status_code=404, content={"detail": "Mundo no encontrado"})
    if body.flow_type not in SUPPORTED_FLOW_TYPES:
        return JSONResponse(status_code=422, content={
            "detail": f"unsupported flow type {body.flow_type!r}",
            "code": "unsupported_flow_type",
        })
    library = _methodology_library()
    library.deactivate(body.world, body.flow_type)
    return {"world": body.world, "flow_type": body.flow_type,
            "skill_id": None, "version": None, "digest": None, "activated_at": None}


@app.post("/api/methodologies/companions/activate")
def methodologies_activate_companion(body: MethodologyCompanionActivateRequest, request: Request):
    """Pin a published methodology version as a companion skill of a world.

    Mirrors the slot activate route's auth/world prelude; the activation slot
    itself is never touched (companions are independent of ``activate``).
    """
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    if _resolve_mundo_dir(body.world) is None:
        return JSONResponse(status_code=404, content={"detail": "Mundo no encontrado"})
    library = _methodology_library()
    try:
        companion = library.add_companion(body.world, body.skill_id, body.version)
    except NotPublishedError as exc:
        return JSONResponse(status_code=422, content={
            "detail": str(exc), "code": "not_published",
        })
    except CompanionLimitError as exc:
        return JSONResponse(status_code=422, content={
            "detail": str(exc), "code": "companion_limit_reached",
        })
    published = library.get_published(body.skill_id, body.version)
    return {
        "world": companion.world,
        "companion": {
            "world": companion.world,
            "skill_id": companion.skill_id,
            "version": companion.version,
            "description": published.description if published is not None else "",
            "activated_at": companion.activated_at,
        },
    }


@app.post("/api/methodologies/companions/deactivate")
def methodologies_deactivate_companion(body: MethodologyCompanionDeactivateRequest, request: Request):
    """Remove a companion skill from a world (idempotent: ``removed`` false)."""
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    if _resolve_mundo_dir(body.world) is None:
        return JSONResponse(status_code=404, content={"detail": "Mundo no encontrado"})
    removed = _methodology_library().remove_companion(body.world, body.skill_id)
    return {"world": body.world, "removed": removed}


# ---------------------------------------------------------------------------
# Skill transfer (Fase 5b, REQ-IMP-1..6): export published versions as `.zip`
# packages and import them through mandatory quarantine → manual trust →
# editable draft. The foundational character-skill id is reserved: it can
# never be trusted or published from an import.
# ---------------------------------------------------------------------------


def _quarantine_record_payload(record: QuarantineRecord) -> dict[str, Any]:
    """Wire shape of a quarantine record (verdict without the compiled body)."""
    verdict = record.verdict
    return {
        "package_id": record.package_id,
        "verdict": {
            "ok": verdict.ok,
            "checksum_valid": verdict.checksum_valid,
            "signature_present": verdict.signature_present,
            "signature_valid": verdict.signature_valid,
            "issues": list(verdict.issues),
        },
        "trusted": record.trusted,
        "draft_id": record.draft_id,
        "clasificacion": record.clasificacion,
        "trust_attributes": list(record.trust_attributes),
    }


@app.post("/api/methodologies/published/{skill_id}/{version}/export")
def methodologies_export(skill_id: str, version: str, request: Request):
    """Export a published version as a `.zip` methodology package (REQ-IMP-1).

    The package contains the bounded manifest, the author source, the integrity
    checksum manifest, and the official signature when one was recorded. When
    the version pins adjuntos, each carrier is embedded at its package-relative
    path with exactly the pinned bytes and declared in the manifest (R16). A
    pinned carrier that is missing under the resolved carrier root or has
    drifted from its ``sha256``/``bytes`` pin fails closed with 422
    ``attachment_unavailable`` — the export never emits a partial package its
    own import would reject (R17), and the error never leaks the path, hash, or
    carrier root.
    """
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    library = _methodology_library()
    published = library.get_published(skill_id, version)
    if published is None:
        return JSONResponse(status_code=404, content={"detail": "Metodología no encontrada"})
    manifest = {
        "skill_id": published.skill_id,
        "version": published.version,
        "name": published.name,
        "description": published.description,
        "phases": list(published.phases),
        "language": published.language,
        "taller": published.taller,
        "talleres_compatibles": list(published.talleres_compatibles),
        "categoria_funcional": published.categoria_funcional,
        "etiquetas": list(published.etiquetas),
    }
    attachments: dict[str, bytes] = {}
    if published.adjuntos:
        manifest["adjuntos"] = [entry.as_dict() for entry in published.adjuntos]
        seed_dir = carrier_root_for(published.skill_id, project_root=_project_root())
        for pin in published.adjuntos:
            carrier = read_adjunto_bytes(seed_dir, pin)
            if carrier is None or len(carrier) != pin.bytes:
                return JSONResponse(status_code=422, content={
                    "detail": "A pinned attachment is unavailable or has drifted.",
                    "code": "attachment_unavailable",
                })
            attachments[pin.path] = carrier
    package = build_package(manifest, published.source, attachments=attachments or None)
    return Response(
        content=package,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{skill_id}-{version}.zip"'},
    )


@app.post("/api/methodologies/import")
async def methodologies_import(
    request: Request,
    file: UploadFile = File(...),
    origin: str = Form("community"),
):
    """Import a `.zip` methodology package into mandatory quarantine (REQ-IMP-2).

    The package is isolated with its integrity verdict; the library is never
    mutated by import. The Author must explicitly trust it (REQ-IMP-4) before
    it becomes an editable draft.
    """
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    data = await file.read()
    if not data:
        return JSONResponse(status_code=400, content={"detail": "El archivo está vacío."})
    record = _methodology_quarantine().quarantine(
        data,
        library=_methodology_library(),
        name=file.filename or "",
        origin=origin,
    )
    return _quarantine_record_payload(record)


@app.get("/api/methodologies/quarantine")
def methodologies_quarantine_list(request: Request):
    """List quarantined imports with fresh re-inspected verdicts (REQ-IMP-3)."""
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    entries = [
        _quarantine_record_payload(record)
        for record in _methodology_quarantine().list()
    ]
    return {"entries": entries}


@app.post("/api/methodologies/quarantine/{package_id}/trust")
def methodologies_quarantine_trust(package_id: str, request: Request):
    """Manually trust a quarantined package, promoting it to a draft (REQ-IMP-4).

    Rejects the reserved foundational id with 409 (REQ-IMP-6) and fails closed
    (422) when the package no longer re-validates.
    """
    principal = _resolve_principal(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    store = _methodology_quarantine()
    record = store.get(package_id)
    if record is None:
        return JSONResponse(status_code=404, content={"detail": "Metodología no encontrada"})
    compiled = record.verdict.compiled
    if compiled is not None and compiled.skill_id == FOUNDATIONAL_CHARACTER_SKILL_ID:
        return JSONResponse(status_code=409, content={
            "detail": "reserved_skill_id", "code": "reserved_skill_id",
        })
    trusted = store.trust(
        package_id,
        library=_methodology_library(),
        attachments_root=_project_root() / ATTACHMENTS_SUBDIR,
    )
    if trusted is None:
        return JSONResponse(status_code=422, content={
            "detail": "La metodología no pasó la validación de integridad.",
            "code": "trust_rejected",
        })
    return {
        "package_id": trusted.package_id,
        "trusted": trusted.trusted,
        "draft_id": trusted.draft_id,
        "clasificacion": trusted.clasificacion,
        "trust_attributes": list(trusted.trust_attributes),
    }


# ---------------------------------------------------------------------------
# Static SPA serving (S1)
# ---------------------------------------------------------------------------
# Single catch-all registered LAST on purpose: Starlette matches in
# registration order, so only paths no earlier route claimed ever reach this
# handler. It serves the prebuilt same-origin SPA (index + hashed assets +
# client-route fallback), keeps unknown ``/api/*`` paths on the API's own JSON
# 404 (never ``index.html``), and is inert when no dist is present so the Vite
# dev proxy path keeps working unchanged.


@app.get("/{full_path:path}")
def spa_fallback(full_path: str) -> Response:
    """Serve the prebuilt SPA, falling back to ``index.html`` for client routes.

    Precedence (S1-1): the ``/api`` carve-out stays on the API's JSON 404;
    an absent dist answers 503 ``app.not_served`` while ``/api/*`` and
    ``/health`` keep working; a traversal-safe file inside the dist dir is
    served with a deterministic content type; anything else is the SPA shell.
    """
    if full_path == "api" or full_path.startswith("api/"):
        if _api_route_method_mismatch(full_path):
            # The path exists under a non-GET method: keep the API's native
            # 405 instead of hiding it behind the SPA carve-out 404.
            return JSONResponse(
                status_code=405, content={"detail": "Method Not Allowed"}
            )
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    dist = _frontend_dist()
    if dist is None or not dist.is_dir() or not (dist / "index.html").is_file():
        return JSONResponse(
            status_code=503,
            content={
                "code": "app.not_served",
                "detail": "Frontend build not present. Build the SPA or point "
                "DEMIURGOS_FRONTEND_DIST at a built dist directory.",
            },
        )

    if not full_path:
        return _spa_index_response(dist)

    candidate = (dist / full_path).resolve()
    dist_root = dist.resolve()
    if dist_root not in candidate.parents:
        # Traversal attempt (or the dist dir itself): never serve outside it.
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    if candidate.is_file():
        return FileResponse(
            candidate,
            media_type=_content_type(candidate),
            headers={"Cache-Control": _cache_control(full_path)},
        )
    return _spa_index_response(dist)


def _api_route_method_mismatch(full_path: str) -> bool:
    """True when an API path exists only under non-GET methods (→ 405).

    The catch-all is registered last, so a GET reaching it for a path that a
    POST/DELETE/PUT route owns would otherwise turn Starlette's native 405
    into the carve-out 404. Re-runs the router's own matching with a synthetic
    GET scope: any ``PARTIAL`` match means the path exists but not for GET.
    Uses ``route.matches()`` (not ``path_regex``) so router objects wrapped by
    ``include_router`` are seen through on every FastAPI version.
    """
    from starlette.routing import Match  # noqa: PLC0415 — local, tiny

    scope: dict = {
        "type": "http",
        "method": "GET",
        "path": "/" + full_path,
        "raw_path": ("/" + full_path).encode("latin-1"),
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 8000),
        "server": ("127.0.0.1", 8000),
    }
    for route in app.routes:
        match, _ = route.matches(scope)
        if match == Match.PARTIAL:
            return True
    return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    logger.info("Starting Demiurgos Wiki API on port %d", port)
    logger.info("Mundos dir: %s (exists=%s)", _mundos_dir(), _mundos_dir().is_dir())
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
