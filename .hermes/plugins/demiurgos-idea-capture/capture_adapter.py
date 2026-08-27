"""CaptureTelegramAdapter — minimal TelegramAdapter subclass for the capture flow.

PR 2 of ``idea-capture-native-adapter``. Subclasses the bundled Hermes v0.20
``TelegramAdapter`` (imported from the Hermes plugins path) and adds ONLY the
capture behavior:

- a ``capture:`` branch in ``_handle_callback_query``, inserted
  before the bundled silent-return gate (``adapter.py:6763-6764`` — the
  ``update_prompt:`` fallthrough that silently drops unknown prefixes), and
- ``send_capture_prompt``, which renders the Guardar/Descartar keyboard with
  real PTB ``InlineKeyboardButton``/``InlineKeyboardMarkup`` objects.

Everything else delegates to the parent via ``super()`` so built-in callbacks
(``mp:``, ``cp:``, ``gt:``, ``ea:``, ``sc:``, ``cl:``, ``update_prompt:``)
keep working untouched.

The subclass is intentionally thin: any Hermes upgrade that renames or removes
the private helpers it touches is caught by ``verify_bundled_adapter_surface``
at plugin load (fail loud) instead of failing at runtime in a user chat.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from idea_capture.models import CaptureState, WorldAction
from idea_capture.runtime import build_capture_keyboard, parse_capture_callback

log = logging.getLogger(__name__)

# The runtime encodes Guardar/Descartar buttons with the ``capture:<id>:<action>``
# envelope (see ``idea_capture.runtime._CALLBACK_PREFIX``). The adapter branch MUST
# match that exact prefix or every tap falls through to the bundled parent handler,
# which silently drops unknown prefixes and the button appears to "do nothing".
_CAPTURE_PREFIX = "capture:"

# Capture states that still allow a button tap to mutate the capture. Any
# other state (PROCESSING/SAVED/CANCELLED/RETRYABLE/ERROR) means the tap is
# stale and must be acknowledged idempotently (S-6.5) — the runtime never
# deletes rows on confirm, so the store.get KeyError gate alone would let a
# second tap re-confirm and re-queue processing.
_CONFIRMABLE_STATES = frozenset({
    CaptureState.RECEIVED,
    CaptureState.RAW_PERSISTED,
    CaptureState.AWAITING_WORLD,
    CaptureState.AWAITING_CONFIRM,
})


def hermes_agent_root() -> Path:
    """Resolve the Hermes agent source root (parent of the ``plugins`` package).

    Inside a running gateway the agent root is already importable, so this is
    only a fallback for standalone/test processes. Honours an explicit
    ``HERMES_AGENT_ROOT`` override, then ``HERMES_HOME`` (default ``~/.hermes``)
    + ``hermes-agent``.
    """
    override = os.environ.get("HERMES_AGENT_ROOT", "").strip()
    if override:
        return Path(override).resolve()
    home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()
    return (home / "hermes-agent").resolve()


# The gateway process already has the agent root on ``sys.path``; standalone
# processes (and this repo's unit tests) fall back to ``hermes_agent_root()``.
try:
    from plugins.platforms.telegram.adapter import TelegramAdapter
except ImportError:  # pragma: no cover - exercised in the repo's test venv
    _root = hermes_agent_root()
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from plugins.platforms.telegram.adapter import TelegramAdapter


def _adapter_module():
    """Return the bundled telegram adapter module (after the import fallback)."""
    from plugins.platforms.telegram import adapter as _mod
    return _mod


def verify_bundled_adapter_surface() -> None:
    """Fail loud when the bundled TelegramAdapter drifted from our override points.

    Raises ``RuntimeError`` listing the missing helpers so the plugin load
    fails loudly instead of the first capture tap failing at runtime.
    """
    mod = _adapter_module()
    missing = [
        name for name in ("_handle_callback_query", "_send_message_with_thread_fallback")
        if not hasattr(mod.TelegramAdapter, name)
    ]
    if not hasattr(mod, "_probe_voice_duration_seconds"):
        missing.append("_probe_voice_duration_seconds")
    if missing:
        raise RuntimeError(
            "demiurgos-idea-capture: bundled TelegramAdapter API drifted — missing "
            f"{missing}. Refusing to override the telegram platform."
        )


def capture_platform_deps_ready() -> bool:
    """PASSIVE dependency probe for ``register_platform(check_fn=...)``.

    Never installs anything: status displays and config loading call it freely
    (gateway/platform_registry.py). True when the PTB SDK is importable AND the
    bundled adapter still exposes every helper the capture flow relies on.
    """
    try:
        import telegram  # noqa: F401
        mod = _adapter_module()
        return all(
            hasattr(mod.TelegramAdapter, name)
            for name in ("_handle_callback_query", "_send_message_with_thread_fallback")
        ) and hasattr(mod, "_probe_voice_duration_seconds")
    except Exception:
        return False


class CaptureTelegramAdapter(TelegramAdapter):
    """Minimal subclass: capture callbacks + keyboard send; all else delegates."""

    def __init__(self, config, capture_handler=None):
        super().__init__(config)
        # IdeaCaptureHandler providing capture policy (authorized_bindings) and
        # the runtime (store.get / confirm). None -> callbacks fail closed.
        self._capture_handler = capture_handler

    # -- callback routing ---------------------------------------------------

    async def _handle_callback_query(self, update, context):
        """Route ``capture:`` taps; defer everything else to the parent.

        The capture branch runs BEFORE the bundled handlers — i.e. before the
        silent-return gate (adapter.py:6763-6764) that drops unknown prefixes —
        so capture taps never fall through to the assistant. All other prefixes
        (mp:/cp:/gt:/ea:/sc:/cl:/update_prompt:) reach ``super()`` untouched.
        """
        query = getattr(update, "callback_query", None)
        data = getattr(query, "data", "") if query is not None else ""
        if isinstance(data, str) and data.startswith(_CAPTURE_PREFIX):
            await self._handle_capture_callback(query, data)
            return
        await super()._handle_callback_query(update, context)

    async def _handle_capture_callback(self, query, data: str) -> None:
        """Resolve one Guardar/Descartar tap (or reject it); always answers.

        Every tap is acknowledged via ``query.answer`` so the client clears its
        spinner, but the store is only mutated for a tap that is (1) parseable,
        (2) from the capture binding, and (3) referencing a still-confirmable
        capture. Everything else is answered gracefully and idempotently.
        """
        handler = self._capture_handler
        if handler is None:
            await query.answer("No autorizado.")
            return

        # The runtime parser reads the ``capture:<id>:<action>`` envelope
        # verbatim; the adapter branch already matched that prefix, so pass the
        # data through unchanged.
        parsed = parse_capture_callback(data)
        if parsed is None:
            await query.answer("Acción inválida.")
            return
        capture_id, action, _world = parsed

        # Auth (R-8): capture binding only — NOT _is_callback_user_authorized,
        # which consults the assistant gate (TELEGRAM_ALLOWED_USERS).
        message = getattr(query, "message", None)
        chat_id = str(getattr(message, "chat_id", "")) if message is not None else ""
        user_id = str(getattr(getattr(query, "from_user", None), "id", ""))
        profile = getattr(self, "_profile_name", None) or "default"
        binding_key = f"telegram:{chat_id}:{user_id}:{profile}"
        if not chat_id or not user_id or binding_key not in handler.policy.authorized_bindings:
            log.warning("idea-capture callback rejected (unauthorized binding %r)", binding_key)
            await query.answer("No autorizado.")
            await self._strip_buttons(query, "No autorizado.")
            return

        # Idempotency (S-6.4 / S-6.5): unknown id or already-resolved state
        # means the tap is stale — acknowledge and never mutate.
        try:
            record = handler.runtime.store.get(capture_id)
        except KeyError:
            await query.answer("Ya resuelta.")
            return
        if record.state not in _CONFIRMABLE_STATES:
            await query.answer("Ya resuelta.")
            return

        if action is WorldAction.SAVE_GLOBAL:
            handler.runtime.confirm(capture_id, action)
            answer = "Idea guardada en el Taller de Ideas (procesando...)."
        elif action is WorldAction.CANCEL:
            handler.runtime.confirm(capture_id, action)
            answer = "Idea cancelada."
        else:
            # SAVE / CHANGE_WORLD are the world-scoped variant — out of PR 2
            # scope (proposal: world assignment at capture time is deferred).
            # The capture keyboard never offers them; a stale button is
            # acknowledged gracefully.
            await query.answer("Acción no disponible.")
            await self._strip_buttons(query, "Acción no disponible.")
            return

        await query.answer(answer)
        await self._strip_buttons(query, answer)

    @staticmethod
    async def _strip_buttons(query, text: str) -> None:
        """Remove the inline keyboard, replacing the message text with ``text``."""
        try:
            await query.edit_message_text(text=text, reply_markup=None)
        except Exception:
            pass  # non-fatal: message may already be edited/deleted

    # -- keyboard send -------------------------------------------------------

    async def send_capture_prompt(self, *, chat_id, capture_id: str, thread_id=None) -> None:
        """Send the Guardar/Descartar keyboard via the real adapter send path.

        Rendered with real PTB ``InlineKeyboardButton``/``InlineKeyboardMarkup``
        (R-7); the fictional ``send_interaction_message`` is never used.
        """
        markup = self._build_markup(build_capture_keyboard(capture_id))
        text = f"Idea capturada (id=`{capture_id}`). Elegí una acción:"
        kwargs = {"chat_id": chat_id, "text": text, "reply_markup": markup}
        if thread_id:
            kwargs["message_thread_id"] = thread_id
        await self._send_message_with_thread_fallback(**kwargs)

    @staticmethod
    def _build_markup(keyboard_dict: dict):
        """Convert ``build_capture_keyboard`` dict rows into PTB markup."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        rows = [
            [
                InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"])
                for btn in row
            ]
            for row in keyboard_dict["inline_keyboard"]
        ]
        return InlineKeyboardMarkup(rows)