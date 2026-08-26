"""Project plugin registration for native Demiurgos idea capture.

PR 1 (foundation): replaces the fictional ``register_gateway_handler`` /
``register_gateway_interaction_handler`` calls with a real Hermes v0.20
integration — a synchronous ``pre_gateway_dispatch`` intake hook that
intercepts the designated capture chat so messages never reach the assistant.

PR 2 adds the ``CaptureTelegramAdapter`` subclass registered via
``ctx.register_platform("telegram", ...)`` for the inline Guardar/Descartar
keyboard and callback routing; ``_schedule_capture_prompt`` now calls
``adapter.send_capture_prompt`` (falling back to plain ``send`` when the
platform override is not in effect).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_handler = None


def register(ctx) -> None:
    global _handler
    root = Path(os.environ.get("DEMIURGOS_ROOT", Path.cwd())).resolve()
    tools = root / "src" / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))

    from idea_capture.hermes_handler import IdeaCaptureHandler
    from .capture_adapter import (
        CaptureTelegramAdapter,
        capture_platform_deps_ready,
        verify_bundled_adapter_surface,
    )

    _handler = IdeaCaptureHandler(repo_root=root)

    # Native intake: intercept the designated capture chat before Hermes auth
    # or assistant dispatch. The hook is synchronous and returns a skip dict so
    # captured messages are consumed and never reach the assistant.
    ctx.register_hook("pre_gateway_dispatch", capture_intake_hook)

    # PR 2: override the bundled telegram adapter with the capture subclass so
    # Guardar/Descartar callbacks route and the prompt carries a real keyboard.
    # Fail loud if the bundled adapter's private helpers drifted (Hermes
    # upgrade), then register last-writer-wins (platform_registry replaces
    # same-name entries).
    verify_bundled_adapter_surface()

    def _adapter_factory(cfg):
        return CaptureTelegramAdapter(cfg, capture_handler=_handler)

    ctx.register_platform(
        name="telegram",
        label="Telegram (Demiurgos capture)",
        adapter_factory=_adapter_factory,
        check_fn=capture_platform_deps_ready,
        required_env=["TELEGRAM_BOT_TOKEN"],
    )


def capture_intake_hook(*, event, gateway, session_store) -> dict | None:
    """Synchronous intake for the designated capture chat.

    Hermes' ``invoke_hook`` calls this callback synchronously (``cb(**kwargs)``);
    it MUST return a dict, never a coroutine — an un-awaited coroutine here
    would silently disable the skip contract. Returns:

    - ``{"action": "skip", "reason": "idea-capture"}`` for a captured message,
    - ``{"action": "skip", "reason": "idea-capture-duplicate"}`` for a replay,
    - ``{"action": "skip", "reason": "idea-capture-rejected"}`` when a capture
      attempt fails (fail closed: never leak the message to the assistant,
      never crash dispatch),
    - ``None`` for fall-through to the normal assistant flow (non-capture
      chat, unauthorized sender, non-telegram platform, or non-capturable
      media).
    """
    handler = _handler
    source = getattr(event, "source", None)
    if handler is None or source is None:
        return None
    platform = str(getattr(getattr(source, "platform", None), "value", ""))
    if platform != "telegram":
        return None  # S-3.1: non-capture platform -> assistant handles
    if not handler._binding_allowed(source):
        return None  # S-3.2: unauthorized sender -> assistant handles

    try:
        update = handler._update_from_event(event)
    except ValueError:
        # S-10.3 / S-10.4: unsupported media type, no capturable text/media,
        # or missing Telegram identity -> normal assistant flow, never capture.
        return None
    except Exception as exc:  # noqa: BLE001 — fail closed, never crash dispatch
        log.exception("idea-capture event conversion failed: %s", exc)
        return {"action": "skip", "reason": "idea-capture-rejected"}
    try:
        receipt = handler.runtime.service.accept(update)
    except Exception as exc:  # noqa: BLE001 — fail closed, never leak
        log.warning("idea-capture intake rejected update: %s", exc)
        return {"action": "skip", "reason": "idea-capture-rejected"}
    if receipt.status == "DUPLICATE":
        return {"action": "skip", "reason": "idea-capture-duplicate"}  # R-4 / S-4.1

    adapter = gateway._adapter_for_source(event.source)
    if adapter is not None:
        _schedule_capture_prompt(adapter, source, receipt.capture_id)
    return {"action": "skip", "reason": "idea-capture"}


def _schedule_capture_prompt(adapter, source, capture_id: str) -> None:
    """Schedule the outbound capture prompt without blocking dispatch.

    PR 2: the prompt rides ``CaptureTelegramAdapter.send_capture_prompt`` so
    the Guardar/Descartar keyboard is attached. Falls back to the PR 1
    plain-text ``send`` when the active adapter predates the subclass (e.g.
    the platform override is not yet in effect).
    """
    kwargs = {"chat_id": str(source.chat_id), "capture_id": capture_id}
    if getattr(source, "thread_id", None):
        kwargs["thread_id"] = source.thread_id
    send_prompt = getattr(adapter, "send_capture_prompt", None)
    try:
        if callable(send_prompt):
            asyncio.create_task(send_prompt(**kwargs))
        else:
            text = f"Idea capturada (id=`{capture_id}`). Elegí una acción:"
            metadata = {"thread_id": kwargs["thread_id"]} if "thread_id" in kwargs else None
            asyncio.create_task(adapter.send(str(source.chat_id), text, metadata=metadata))
    except RuntimeError as exc:  # no running loop: prompt cannot be scheduled
        log.warning("idea-capture prompt scheduling failed for %s: %s", capture_id, exc)
