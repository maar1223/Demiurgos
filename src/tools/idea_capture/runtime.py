"""Native runtime wiring: config + store + ingress + service + worker + publisher.

This composition root is the runtime-readiness wiring the audit found missing.
It is a thin layer over the existing SDD contracts and adds:

- fail-closed policy loading from ``config/idea-capture.yaml`` (``load_policy``)
- a Telegram adapter entrypoint (``update_from_telegram``) with an injectable
  file resolver, so it is testable without network calls
- the Save global / Cancel confirmation flow (``confirm``); SAVE_GLOBAL is the
  default capture path (Taller de Ideas, no world), while SAVE/CHANGE_WORLD
  remain a world-scoped variant
- an injectable publisher/transport boundary (``MemoryPublisher`` by default,
   ``TelegramTransport`` only for the compatibility command)
- Telegram inline keyboards for the capture flow (Guardar en Taller de Ideas /
  Cancelar) with callback-query handling; the text commands remain a
  backward-compatible fallback
- an ownership lock retained for the compatibility command so it cannot race
   Hermes' production Telegram owner
- a ``smoke`` CLI that runs fully offline in a temporary directory
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .adapter import InvalidUpdate, update_from_telegram
from .config import CaptureConfig, CaptureLimits, load_policy
from .models import CaptureRecord, CaptureState, CaptureReceipt, WorldAction
from .outbox import MemoryPublisher
from .processor import IdeaProcessor
from .service import CaptureService
from .store import CaptureStore
from .telegram import IngressPolicy, TelegramIngress, UnauthorizedUpdate
from .worker import CaptureWorker

log = logging.getLogger(__name__)

# Data-root seam (WU-3, portable-data-root-drive-backup). Author data
# (``config``, ``mundos``, ``data``) resolves through the shared data-root
# resolver instead of this module's location. Resolution is LAZY and must stay
# that way: an import-time call would raise ``DataRootNotConfigured`` while
# pytest collects the suite. ``REPO_ROOT`` stays a plain writable module
# attribute so the seam stays patchable, and the derived values are never
# cached — a cached root would leak one test's environment into the next.
REPO_ROOT: Path | None = None


def _ensure_wiki_on_path() -> None:
    """Make ``src/tools/demiurgos-suite/wiki`` importable for the resolver.

    ``data_root`` is a flat sibling of the wiki modules, so the lazy import
    below only resolves once that directory is on ``sys.path``. A
    ``python -m idea_capture`` process does not guarantee it, so this code
    locator inserts it from the module's own location: ``idea_capture/ ->
    tools/ -> src/ -> repo root``. It locates CODE, never author data.
    """
    wiki = (Path(__file__).resolve().parents[3]
            / "src" / "tools" / "demiurgos-suite" / "wiki")
    if str(wiki) not in sys.path:
        sys.path.insert(0, str(wiki))


def _project_root() -> Path:
    """Resolve the data root lazily; a ``REPO_ROOT`` patch always wins."""
    if REPO_ROOT is not None:
        return REPO_ROOT
    _ensure_wiki_on_path()
    from data_root import resolve_data_root  # noqa: PLC0415 — needs the path above

    return resolve_data_root()


def _notify_backup_engine() -> None:
    """Signal the backup engine after an intake that bypassed the API (REQ-BE-6).

    Layer B of the trigger: the compatibility poller persists captures without
    an HTTP request, so the API's middleware never sees them. The call is
    non-blocking and I/O-free and is a no-op when no engine runs in this process;
    it can never break an intake.
    """
    try:
        _ensure_wiki_on_path()
        from backup.engine import notify_data_changed  # noqa: PLC0415 — needs the path above

        notify_data_changed()
    except Exception:  # noqa: BLE001 — a signal must never fail an intake
        return


def _config_path() -> Path:
    """``<data root>/config/idea-capture.yaml``, resolved on every call."""
    return _project_root() / "config" / "idea-capture.yaml"

# Callback data is opaque and content-free: it never carries idea text, the bot
# token, or chat ids — only the capture id, the action, and (for world
# selection) a short safe world name. The strict parsers below reject anything
# else, and Telegram itself caps callback_data at 64 bytes.
_CALLBACK_PREFIX = "capture:"
_CALLBACK_MAX_LENGTH = 64
_CAPTURE_ID_PATTERN = r"[0-9a-fA-F-]{36}"  # uuid5 hex form, e.g. 8-4-4-4-12
_CALLBACK_ACTION_RE = re.compile(
    rf"^{_CALLBACK_PREFIX}({_CAPTURE_ID_PATTERN}):(save|save_global|cancel)$")
_CALLBACK_PICKER_RE = re.compile(
    rf"^{_CALLBACK_PREFIX}({_CAPTURE_ID_PATTERN}):world$")
_CALLBACK_WORLD_RE = re.compile(
    rf"^{_CALLBACK_PREFIX}({_CAPTURE_ID_PATTERN}):world:([A-Za-z0-9_-]+)$")
# Safe-world alphabet for the world picker and callback encoding. MUST stay in
# sync with ``demiurgos-suite/wiki/world_authority.py``
# ``normalize_world_name`` (``_SAFE_NAME_RE``): a world that can be created
# but cannot be selected/linked in the capture flow is a bug.
_SAFE_WORLD = re.compile(r"^[A-Za-z0-9_-]+$")


def encode_capture_callback(capture_id: str, action: WorldAction,
                            world: str | None = None) -> str:
    """Encode one capture-flow button into Telegram callback data.

    ``action`` is SAVE/CANCEL -> ``capture:<id>:<action>``; CHANGE_WORLD with a
    world -> ``capture:<id>:world:<world>``; CHANGE_WORLD without one is the
    "show the world picker" trigger -> ``capture:<id>:world``.
    """
    if action is WorldAction.CHANGE_WORLD:
        suffix = "world" if world is None else f"world:{world}"
    else:
        suffix = action.value
    return f"{_CALLBACK_PREFIX}{capture_id}:{suffix}"


def parse_capture_callback(data) -> tuple[str, WorldAction, str | None] | None:
    """Strictly parse callback data; ``None`` means malformed/unknown (reject).

    Returns ``(capture_id, action, world_or_None)`` where world is ``None``
    for save/cancel and for the world-picker trigger, and the validated safe
    world name for an explicit world selection.
    """
    if not isinstance(data, str) or len(data) > _CALLBACK_MAX_LENGTH:
        return None
    match = _CALLBACK_ACTION_RE.fullmatch(data)
    if match:
        return match.group(1), WorldAction(match.group(2)), None
    match = _CALLBACK_PICKER_RE.fullmatch(data)
    if match:
        return match.group(1), WorldAction.CHANGE_WORLD, None
    match = _CALLBACK_WORLD_RE.fullmatch(data)
    if match:
        return match.group(1), WorldAction.CHANGE_WORLD, match.group(2)
    return None


def build_capture_keyboard(capture_id: str) -> dict:
    """Inline keyboard shown after a capture: Guardar en Taller de Ideas / Cancelar.

    SAVE_GLOBAL is the default capture path: the idea lands in the global
    Taller de Ideas bank with no world chosen at capture. The per-world
    SAVE/CHANGE_WORLD actions remain supported at the runtime level as a
    world-scoped variant (text commands /save, /world), but they are not
    offered on the primary keyboard.
    """
    return {"inline_keyboard": [[
        {"text": "Guardar en Taller de Ideas",
         "callback_data": encode_capture_callback(capture_id, WorldAction.SAVE_GLOBAL)},
        {"text": "Cancelar",
         "callback_data": encode_capture_callback(capture_id, WorldAction.CANCEL)},
    ]]}


def build_world_keyboard(runtime: IdeaCaptureRuntime, capture_id: str) -> dict:
    """Second inline keyboard: one button per safe world (explicit confirm).

    Worlds that cannot be encoded within Telegram's callback_data limit are
    skipped (fail closed) rather than emitted and rejected by the API.
    """
    rows = []
    for world in runtime.available_worlds():
        data = encode_capture_callback(capture_id, WorldAction.CHANGE_WORLD, world)
        if len(data) > _CALLBACK_MAX_LENGTH:
            continue
        rows.append([{"text": world, "callback_data": data}])
    return {"inline_keyboard": rows}


def default_pid_alive(pid: int) -> bool:
    """Portable liveness probe. Never uses os.kill on Windows (it terminates)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            alive = bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)))
            return alive and exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@dataclass(frozen=True)
class OwnershipState:
    acquired: bool
    lock_path: Path | None = None
    reason: str = ""


class OwnershipLock:
    """Single-owner guard retained for the compatibility Telegram command.

    A PID lock file owns the bot while its process is alive; a dead PID is
    stale and can be taken over. ``health_check`` is an optional injectable
    probe (e.g. the Hermes gateway) that must pass before ownership is granted,
    mirroring the "no second instance" guard in start-demiurgos.ps1.
    """

    def __init__(self, lock_path: str | Path,
                 health_check: Callable[[], bool] | None = None,
                 pid_alive: Callable[[int], bool] = default_pid_alive):
        self.lock_path = Path(lock_path)
        self.health_check = health_check
        self._pid_alive = pid_alive
        self._owned = False

    def acquire(self) -> OwnershipState:
        if self.health_check is not None and not self.health_check():
            return OwnershipState(False, self.lock_path,
                                  "health check failed: refusing to start a second owner")
        if self.lock_path.exists():
            pid = int((self.lock_path.read_text(encoding="utf-8") or "0").strip() or "0")
            if pid and self._pid_alive(pid):
                return OwnershipState(False, self.lock_path,
                                      f"another owner (pid {pid}) is alive")
            log.warning("Lock file exists but pid %s is stale; taking over", pid)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text(str(os.getpid()), encoding="utf-8")
        self._owned = True
        return OwnershipState(True, self.lock_path, "")

    def release(self) -> None:
        if not self._owned:
            return
        try:
            self.lock_path.unlink(missing_ok=True)
        except OSError:
            pass
        self._owned = False


class IdeaCaptureRuntime:
    """Composition root: durable store + ingress policy + service + worker + publisher."""

    def __init__(self, *, config: CaptureConfig, state_path: str | Path,
                 mundos_root: str | Path, active_world: str,
                 publisher=None, enrich: Callable[..., tuple[str, str]] | None = None,
                 resolve_file=None, audit: Callable[[dict], None] | None = None,
                 ownership: OwnershipLock | None = None,
                 busy_timeout_seconds: float = 10.0,
                 global_ideas_root: str | Path | None = None):
        self.config = config
        self.state_path = Path(state_path)
        self.mundos_root = Path(mundos_root)
        self.active_world = active_world
        self.global_ideas_root = Path(global_ideas_root) if global_ideas_root else None
        self.store = CaptureStore(self.state_path, busy_timeout_seconds=busy_timeout_seconds)
        self.audit = audit or (lambda event: log.debug("capture audit: %s", event))
        self.ingress = TelegramIngress(config.policy, self.audit)
        self.service = CaptureService(self.ingress, self.store, active_world)
        self.publisher = publisher or MemoryPublisher()
        self.processor = IdeaProcessor(self.store, self.mundos_root,
                                       enrich or self._default_enrich, self.publisher,
                                       global_ideas_root=self.global_ideas_root)
        self.worker = CaptureWorker(self.processor)
        self.resolve_file = resolve_file
        self.ownership = ownership

    @staticmethod
    def _default_enrich(raw: object, *, media_kind=None, media_path=None,
                        mime=None) -> tuple[str, str]:
        """Fallback enrich: text only; voice/image require a provider.

        ``media_kind``, ``media_path``, and ``mime`` are accepted so the
        processor seam can pass the capture's media context through without
        breaking the no-provider fallback. Bytes inputs (voice/image without
        an injected provider) keep failing as before.
        """
        if isinstance(raw, bytes):
            raise ValueError("voice/image capture requires an enrichment provider")
        body = str(raw).strip()
        if not body:
            raise ValueError("empty idea")
        return body, "sin_clasificar"

    # -- ingress -------------------------------------------------------------

    def handle_update(self, payload: dict) -> CaptureReceipt:
        """Convert + authorize + persist one raw Telegram update (fail closed)."""
        if self.resolve_file is None:
            update = update_from_telegram(payload)
        else:
            update = update_from_telegram(payload, resolve_file=self.resolve_file)
        receipt = self.service.accept(update)
        # Layer B (REQ-BE-6): the capture is persisted without an API request.
        _notify_backup_engine()
        return receipt

    # -- confirmation flow (Save / Change world / Cancel) --------------------

    def confirm(self, capture_id: str, action: WorldAction,
                selected_world: str | None = None) -> CaptureRecord:
        """Apply the owner's decision; SAVE submits durable async processing."""
        record = self.service.confirm(capture_id, action, selected_world)
        if record.state is CaptureState.PROCESSING:
            self.worker.submit(capture_id)
        return record

    def drain_outbox(self) -> int:
        """Publish every pending outbox message through the publisher."""
        pending = self.store.pending_outbox()
        self.processor.drain_outbox()
        return len(pending)

    def close(self) -> None:
        self.worker.close()
        self.store.close()
        if self.ownership is not None:
            self.ownership.release()

    def wait_state(self, capture_id: str, state: CaptureState, timeout: float = 5.0) -> CaptureRecord:
        deadline = time.monotonic() + timeout
        record = self.store.get(capture_id)
        while record.state is not state and time.monotonic() < deadline:
            time.sleep(0.01)
            record = self.store.get(capture_id)
        return record

    def available_worlds(self) -> list[str]:
        """Safe worlds the owner may pick: the active world plus existing safe
        subdirectories of ``mundos_root``.

        Fail closed: hidden and unsafe names are never offered, and a callback
        can only confirm a world that appears in this listing.
        """
        candidates = {self.active_world} if _SAFE_WORLD.fullmatch(self.active_world) else set()
        if self.mundos_root.is_dir():
            for entry in self.mundos_root.iterdir():
                if (entry.is_dir() and not entry.name.startswith(".")
                        and _SAFE_WORLD.fullmatch(entry.name)):
                    candidates.add(entry.name)
        return sorted(candidates)

    def _chat_authorized(self, chat_id: int, sender_id: int, is_group: bool) -> bool:
        """Mirror of the ingress policy for callback context (no TelegramUpdate)."""
        if not is_group:
            return chat_id in self.config.policy.private_chat_ids
        return sender_id in self.config.policy.approved_group_senders.get(chat_id, frozenset())


class TelegramTransport:
    """Injectable Telegram Bot API boundary; fakes make tests fully offline."""

    def __init__(self, token: str, api: str = "https://api.telegram.org"):
        self.token = token
        self.api = api.rstrip("/")

    def get_updates(self, offset: int) -> list[dict]:
        import requests
        resp = requests.get(f"{self.api}/bot{self.token}/getUpdates",
                            params={"offset": offset, "timeout": 25}, timeout=35)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"getUpdates error: {data.get('description')}")
        return data.get("result", [])

    def send_message(self, chat_id: int, text: str,
                     reply_markup: dict | None = None) -> str:
        import requests
        payload = {"chat_id": chat_id, "text": text[:3500],
                   "parse_mode": "Markdown"}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            requests.post(f"{self.api}/bot{self.token}/sendMessage",
                          json=payload, timeout=30)
        except requests.RequestException as exc:
            log.warning("sendMessage failed: %s", exc)
        return text

    def answer_callback_query(self, callback_query_id: str,
                              text: str | None = None) -> None:
        """Acknowledge a callback query so the client stops its spinner.

        ``text`` is plain text (no markdown), shown as a toast. Called for
        every callback we can acknowledge, even rejected ones.
        """
        import requests
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text[:200]
        try:
            requests.post(f"{self.api}/bot{self.token}/answerCallbackQuery",
                          json=payload, timeout=30)
        except requests.RequestException as exc:
            log.warning("answerCallbackQuery failed: %s", exc)


def handle_confirmation_command(runtime: IdeaCaptureRuntime, text: str) -> str:
    """Parse /save, /world <world>, /cancel against a capture id -> reply text."""
    parts = text.strip().split()
    if len(parts) < 2:
        return "Usa `/save <id>`, `/world <id> <mundo>`, o `/cancel <id>`."
    command, capture_id = parts[0], parts[1]
    try:
        if command == "/save":
            runtime.confirm(capture_id, WorldAction.SAVE)
            return f"✅ Idea guardada en `{runtime.active_world}` (procesando…)."
        if command == "/world":
            if len(parts) < 3:
                return "Falta el mundo: `/world <id> <mundo>`."
            runtime.confirm(capture_id, WorldAction.CHANGE_WORLD, parts[2])
            return f"✅ Idea asignada a `{parts[2]}` (procesando…)."
        if command == "/cancel":
            runtime.confirm(capture_id, WorldAction.CANCEL)
            return "🗑 Idea cancelada."
    except (KeyError, ValueError) as exc:
        return f"⚠ {exc}"
    return "Comando no reconocido."


def _handle_callback_query(runtime: IdeaCaptureRuntime, transport: TelegramTransport,
                           callback: dict, replies: list[str]) -> None:
    """Handle one Telegram callback_query update (inline keyboard button).

    Every callback is answered so the client clears its spinner, but mutation
    only happens for a callback that is (1) bound to an authorized chat,
    (2) strictly parseable, and (3) referencing an existing capture. Anything
    malformed, unknown, or unauthorized is rejected without touching the store.
    """
    query_id = callback.get("id")
    data = callback.get("data")
    sender = (callback.get("from") or {}).get("id")
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    is_group = chat.get("type") in ("group", "supergroup")

    if not isinstance(query_id, str):
        return  # nothing Telegram expects us to acknowledge
    if not isinstance(chat_id, int) or not isinstance(sender, int):
        transport.answer_callback_query(query_id, "Acción inválida.")
        replies.append("Acción inválida.")
        return
    if not runtime._chat_authorized(chat_id, sender, is_group):
        runtime.audit({"event": "unauthorized_callback", "chat_id": chat_id,
                       "sender_id": sender})
        transport.answer_callback_query(query_id, "No autorizado.")
        replies.append("No autorizado.")
        return

    parsed = parse_capture_callback(data)
    if parsed is None:
        runtime.audit({"event": "malformed_callback", "chat_id": chat_id})
        transport.answer_callback_query(query_id, "Acción inválida.")
        replies.append("Acción inválida.")
        return
    capture_id, action, world = parsed

    # Idempotency: only a capture that already exists may be mutated; an
    # unknown id is acknowledged and left untouched (no partial confirm).
    try:
        runtime.store.get(capture_id)
    except KeyError:
        transport.answer_callback_query(query_id, "Captura no encontrada.")
        replies.append("Captura no encontrada.")
        return

    # "Cambiar mundo" without a name -> second inline keyboard with safe worlds.
    if action is WorldAction.CHANGE_WORLD and world is None:
        reply_markup = build_world_keyboard(runtime, capture_id)
        if not reply_markup["inline_keyboard"]:
            transport.answer_callback_query(query_id, "No hay mundos disponibles.")
            replies.append("No hay mundos disponibles.")
            return
        text = "Elige el mundo para esta idea:"
        transport.send_message(chat_id, text, reply_markup=reply_markup)
        transport.answer_callback_query(query_id, "Elige un mundo.")
        replies.append(text)
        return

    try:
        if action is WorldAction.CHANGE_WORLD:
            # The world must still be on the safe listing: never create an
            # arbitrary world directory from external input.
            if world not in runtime.available_worlds():
                transport.answer_callback_query(query_id, "Mundo no disponible.")
                replies.append("Mundo no disponible.")
                return
            runtime.confirm(capture_id, action, world)
            answer = f"✅ Idea asignada a {world} (procesando…)."
        elif action is WorldAction.SAVE:
            runtime.confirm(capture_id, action)
            answer = f"✅ Idea guardada en {runtime.active_world} (procesando…)."
        elif action is WorldAction.SAVE_GLOBAL:
            runtime.confirm(capture_id, action)
            answer = "✅ Idea guardada en el Taller de Ideas (procesando…)."
        else:  # CANCEL
            runtime.confirm(capture_id, action)
            answer = "🗑 Idea cancelada."
    except (KeyError, ValueError) as exc:
        answer = f"⚠ {exc}"
    transport.answer_callback_query(query_id, answer)
    replies.append(answer)


def poll_once(runtime: IdeaCaptureRuntime, transport: TelegramTransport,
              offset: int, replies: list[str]) -> int:
    """Poll one batch offline-style; appends bot replies and returns new offset."""
    updates = transport.get_updates(offset)
    for update in updates:
        offset = max(offset, int(update["update_id"]) + 1)
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            _handle_callback_query(runtime, transport, callback, replies)
            continue
        message = update.get("message") or {}
        text = (message.get("text") or "").strip()
        chat_id = (message.get("chat") or {}).get("id")
        if not isinstance(chat_id, int):
            continue
        if text.startswith("/") and text.split()[0] in ("/save", "/world", "/cancel"):
            replies.append(transport.send_message(chat_id, handle_confirmation_command(runtime, text)))
            continue
        try:
            receipt = runtime.handle_update(update)
            replies.append(transport.send_message(
                chat_id,
                f"📥 Idea capturada (id=`{receipt.capture_id}`).\n"
                "Usa `/save <id>`, `/world <id> <mundo>`, o `/cancel <id>` "
                "si prefieres comandos.",
                reply_markup=build_capture_keyboard(receipt.capture_id),
            ))
        except UnauthorizedUpdate:
            log.warning("Unauthorized update %s rejected", update.get("update_id"))
        except InvalidUpdate as exc:
            log.warning("Invalid update %s rejected: %s", update.get("update_id"), exc)
    return offset


# ---------------------------------------------------------------------------
# CLI (python -m idea_capture smoke|serve)
# ---------------------------------------------------------------------------


def _build_test_policy() -> CaptureConfig:
    # Smoke never uses the real allowlist: it authorizes a synthetic chat only.
    return CaptureConfig(IngressPolicy(frozenset({7}), {}), CaptureLimits())


def run_smoke(config_path: str | Path | None = None) -> dict:
    """Offline dry-run: temporary root, in-memory publisher, no credentials.

    ``config_path`` defaults to the data root's ``config/idea-capture.yaml``,
    so the smoke run is hermetic only when a data root is configured (env
    override or bootstrap pointer). Pass an explicit path to bypass the
    resolver entirely.
    """
    if config_path is None:
        config_path = _config_path()
    report: dict = {"config_path": str(config_path), "steps": []}

    loaded = load_policy(config_path)  # missing/empty -> empty policy (fail closed)
    report["config"] = {
        "authorized_private_chats": len(loaded.policy.private_chat_ids),
        "authorized_groups": len(loaded.policy.approved_group_senders),
    }

    def step(name: str, ok: bool, detail: str = "") -> None:
        report["steps"].append({"name": name, "ok": ok, "detail": detail})

    with tempfile.TemporaryDirectory(prefix="idea-capture-smoke-") as directory:
        root = Path(directory)
        publisher = MemoryPublisher()
        runtime = IdeaCaptureRuntime(config=_build_test_policy(),
                                     state_path=root / "capture.sqlite3",
                                     mundos_root=root / "mundos",
                                     active_world="smoke", publisher=publisher,
                                     global_ideas_root=root / "ideas")

        # 1. Fail closed: an unauthorized chat is rejected, nothing persisted.
        try:
            runtime.handle_update({"update_id": 100, "message": {
                "chat": {"id": 55, "type": "private"}, "from": {"id": 8},
                "text": "secret idea"}})
            step("fail_closed_rejects_unauthorized", False)
        except UnauthorizedUpdate:
            step("fail_closed_rejects_unauthorized", True)

        # 2. Authorized text idea -> raw persisted, prompt offered.
        receipt = runtime.handle_update({"update_id": 1, "message": {
            "chat": {"id": 7, "type": "private"}, "from": {"id": 8},
            "text": "Smoke test idea"}})
        step("authorized_text_captured", receipt.status == "RAW_PERSISTED",
             f"status={receipt.status} prompt={receipt.prompt}")

        # 3. Cancel flow.
        runtime.confirm(receipt.capture_id, WorldAction.CANCEL)
        step("cancel_flow", runtime.store.get(receipt.capture_id).state is CaptureState.CANCELLED)

        # 4. Save flow -> durable processing reaches SAVED.
        receipt = runtime.handle_update({"update_id": 2, "message": {
            "chat": {"id": 7, "type": "private"}, "from": {"id": 8},
            "text": "Second smoke idea"}})
        second_capture_id = receipt.capture_id
        runtime.confirm(receipt.capture_id, WorldAction.SAVE)
        record = runtime.wait_state(receipt.capture_id, CaptureState.SAVED)
        step("save_flow_reaches_saved", record.state is CaptureState.SAVED,
             f"state={record.state.value} slug={record.slug}")

        # 5. Change world flow (world-scoped variant, still supported).
        receipt = runtime.handle_update({"update_id": 3, "message": {
            "chat": {"id": 7, "type": "private"}, "from": {"id": 8},
            "text": "Third smoke idea"}})
        runtime.confirm(receipt.capture_id, WorldAction.CHANGE_WORLD, "smoke2")
        record = runtime.wait_state(receipt.capture_id, CaptureState.SAVED)
        step("change_world_flow", record.world == "smoke2" and record.state is CaptureState.SAVED,
             f"world={record.world} state={record.state.value}")

        # 6. Save global flow -> default path, no world, Taller de Ideas.
        receipt = runtime.handle_update({"update_id": 4, "message": {
            "chat": {"id": 7, "type": "private"}, "from": {"id": 8},
            "text": "Fourth smoke idea"}})
        runtime.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        record = runtime.wait_state(receipt.capture_id, CaptureState.SAVED)
        step("save_global_flow", record.global_ and record.world is None
             and record.state is CaptureState.SAVED,
             f"global={record.global_} state={record.state.value} slug={record.slug}")

        # 7. Replaying the same update is a durable no-op: same capture id, no new row.
        before = runtime.store.count()
        duplicate = runtime.handle_update({"update_id": 2, "message": {
            "chat": {"id": 7, "type": "private"}, "from": {"id": 8},
            "text": "Second smoke idea"}})
        step("duplicate_is_durable_noop",
             duplicate.capture_id == second_capture_id and runtime.store.count() == before,
             f"same_id={duplicate.capture_id == second_capture_id} count={runtime.store.count()}")

        # 8. Outbox published exactly once per saved idea.
        runtime.drain_outbox()
        step("outbox_published", len(publisher.messages) == 3,
             f"published={len(publisher.messages)}")

        runtime.close()

    report["ok"] = all(s["ok"] for s in report["steps"])
    return report


def run_serve(args) -> int:
    """Compatibility-only Telegram long-poll entrypoint.

    Production ingress belongs to Hermes. This command remains guarded for
    migration diagnostics and must never run alongside the Hermes gateway.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("serve requires TELEGRAM_BOT_TOKEN (fail closed)", file=sys.stderr)
        return 2
    config_path = Path(args.config or _config_path())
    config = load_policy(config_path)
    if not config.policy.private_chat_ids and not config.policy.approved_group_senders:
        print(f"serve refuses to start: {config_path} authorizes nobody (fail closed)",
              file=sys.stderr)
        return 2
    world = args.world or os.environ.get("DEMIURGOS_WORLD", "")
    if not world:
        print("serve requires a world (--world or DEMIURGOS_WORLD)", file=sys.stderr)
        return 2
    mundos_root = Path(args.mundos or _project_root() / "mundos")
    if not (mundos_root / world).is_dir():
        print(f"serve refuses to start: {mundos_root / world} does not exist", file=sys.stderr)
        return 2

    lock_path = Path(args.state or _project_root() / "data" / "idea-capture.sqlite3")
    state_path = lock_path
    lock_file = lock_path.with_suffix(".lock")
    health_check = None
    if args.hermes_health_url:
        import requests
        def health_check() -> bool:
            try:
                return requests.get(args.hermes_health_url, timeout=2).status_code == 200
            except requests.RequestException:
                return False
    ownership = OwnershipLock(lock_file, health_check=health_check)
    state = ownership.acquire()
    if not state.acquired:
        print(f"refusing to start: {state.reason}", file=sys.stderr)
        return 3

    runtime = IdeaCaptureRuntime(config=config, state_path=state_path,
                                 mundos_root=mundos_root, active_world=world,
                                 ownership=ownership)
    transport = TelegramTransport(token)
    try:
        offset = 0
        print(f"serve started: world={world} policy_private={len(config.policy.private_chat_ids)}")
        while True:
            try:
                offset = poll_once(runtime, transport, offset, replies=[])
            except Exception as exc:
                log.warning("poll failed: %s", exc)
                time.sleep(5)
    except KeyboardInterrupt:
        print("serve stopped by operator")
        return 0
    finally:
        runtime.close()
