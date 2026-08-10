import importlib.util
from pathlib import Path

import pytest


BRIDGE_PATH = Path(__file__).parents[1] / "opencode-bridge.py"
SPEC = importlib.util.spec_from_file_location("opencode_bridge", BRIDGE_PATH)
bridge = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(bridge)


@pytest.fixture(autouse=True)
def reset_notification_state():
    with bridge.RUN_LOCK:
        bridge.CURRENT_RUN["session_id"] = None
        bridge.CURRENT_RUN["aborted"] = False
        bridge.LAST_IDLE_NOTIFY.clear()


@pytest.mark.parametrize(
    "event",
    [
        {"properties": {"sessionID": "ses-1"}},
        {"properties": {"sessionId": "ses-2"}},
        {"properties": {"session_id": "ses-3"}},
        {"properties": {"session": {"id": "ses-4"}}},
        {"sessionID": "ses-5"},
    ],
)
def test_session_id_from_event_accepts_payload_variants(event):
    assert bridge.session_id_from_event(event).startswith("ses-")


def test_tui_idle_notifies_owner_when_session_is_not_telegram_mapped(monkeypatch):
    sent = []
    monkeypatch.setattr(bridge, "chat_id_for_session", lambda *_: None)
    monkeypatch.setattr(bridge, "send_message", lambda env, chat, text: sent.append((chat, text)))

    bridge.handle_session_idle(
        {},
        "owner-chat",
        {"type": "session.idle", "properties": {"sessionID": "tui-session"}},
    )

    assert sent == [("owner-chat", "✅ OpenCode terminó")]


def test_telegram_run_does_not_get_a_second_idle_notification(monkeypatch):
    sent = []
    monkeypatch.setattr(bridge, "send_typing", lambda *args: None)
    monkeypatch.setattr(bridge, "send_prompt", lambda *args, **kwargs: "agent reply")
    monkeypatch.setattr(bridge, "send_message", lambda env, chat, text: sent.append(text))

    bridge.worker_run(
        {},
        "owner-chat",
        {"session_id": "telegram-session", "num": 1},
        lambda env: ("prompt", None),
    )
    bridge.handle_session_idle(
        {},
        "owner-chat",
        {"type": "session.idle", "properties": {"sessionID": "telegram-session"}},
    )

    assert sent == ["agent reply"]
