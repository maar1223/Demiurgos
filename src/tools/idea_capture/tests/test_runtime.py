"""Runtime-readiness tests: config, adapter, composition root, ownership, poll.

These tests never touch the network: media bytes come from stub resolvers and
the Telegram boundary is a fake transport.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from idea_capture import runtime
from idea_capture.adapter import InvalidUpdate, update_from_telegram
from idea_capture.config import CaptureConfig, CaptureLimits, load_policy
from idea_capture.models import CaptureState, MediaInput, MediaKind, WorldAction
from idea_capture.outbox import MemoryPublisher
from idea_capture.runtime import (IdeaCaptureRuntime, OwnershipLock,
                                  build_capture_keyboard, build_world_keyboard,
                                  encode_capture_callback, handle_confirmation_command,
                                  parse_capture_callback, poll_once)
from idea_capture.telegram import IngressPolicy, UnauthorizedUpdate


def test_smoke_default_config_resolves_from_the_configured_data_root(
        tmp_path: Path, monkeypatch) -> None:
    """WU-3: the smoke default config path comes from the data root.

    ``python -m idea_capture smoke`` used to work from anywhere because the
    config path was code-relative; it now requires a configured data root and
    reads ``<data root>/config/idea-capture.yaml``. An explicit path still
    bypasses the resolver, so only the DEFAULT is affected.
    """
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "idea-capture.yaml").write_text(
        "private_chat_ids: [7]\n", encoding="utf-8")
    monkeypatch.setenv("DEMIURGOS_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(runtime, "REPO_ROOT", None)

    report = runtime.run_smoke()

    assert Path(report["config_path"]) == (
        tmp_path / "config" / "idea-capture.yaml").resolve()
    assert report["config"]["authorized_private_chats"] == 1
    assert report["ok"] is True


def test_config_path_honours_the_repo_root_patch_seam(tmp_path: Path,
                                                      monkeypatch) -> None:
    """A patched ``REPO_ROOT`` wins over the resolver, like every WU-2 seam."""
    monkeypatch.setenv("DEMIURGOS_DATA_ROOT", str(tmp_path / "ignored"))
    monkeypatch.setattr(runtime, "REPO_ROOT", tmp_path / "patched")

    assert runtime._config_path() == (
        tmp_path / "patched" / "config" / "idea-capture.yaml")


def policy_for(*chats: int, groups: dict[int, tuple[int, ...]] | None = None) -> CaptureConfig:
    return CaptureConfig(IngressPolicy(frozenset(chats),
                                       {k: frozenset(v) for k, v in (groups or {}).items()}),
                         CaptureLimits())


def text_payload(update_id: int, chat: int = 7, sender: int = 8, text: str = "idea",
                 group: bool = False) -> dict:
    return {"update_id": update_id, "message": {
        "chat": {"id": chat, "type": "supergroup" if group else "private"},
        "from": {"id": sender}, "text": text}}


class ConfigTests(unittest.TestCase):
    def test_empty_and_missing_config_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = root / "empty.yaml"
            empty.write_text("private_chat_ids: []\napproved_groups: {}\n", encoding="utf-8")
            for path in (empty, root / "missing.yaml"):
                config = load_policy(path)
                self.assertEqual(len(config.policy.private_chat_ids), 0)
                self.assertEqual(config.policy.approved_group_senders, {})

    def test_allowlists_are_parsed_and_fail_closed_on_bad_types(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.yaml"
            path.write_text(
                "private_chat_ids: [7, 42]\n"
                "approved_groups:\n  99: [8, 9]\n"
                "limits:\n  image_mb: 5\n", encoding="utf-8")
            config = load_policy(path)
            self.assertEqual(config.policy.private_chat_ids, frozenset({7, 42}))
            self.assertEqual(config.policy.approved_group_senders[99], frozenset({8, 9}))
            self.assertEqual(config.limits.image_mb, 5)
            path.write_text("private_chat_ids: [abc]\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_policy(path)


class AdapterTests(unittest.TestCase):
    def test_text_payload_converts(self):
        update = update_from_telegram(text_payload(1, text="hello"))
        self.assertEqual(update.update_id, 1)
        self.assertEqual(update.chat_id, 7)
        self.assertEqual(update.sender_id, 8)
        self.assertFalse(update.is_group)
        self.assertEqual(update.media.kind, MediaKind.TEXT)
        self.assertEqual(update.media.text, "hello")

    def test_group_chat_is_marked(self):
        update = update_from_telegram(text_payload(2, group=True))
        self.assertTrue(update.is_group)

    def test_malformed_payloads_are_rejected(self):
        for payload in ({}, {"update_id": 1}, {"update_id": "x", "message": {}},
                        {"update_id": 1, "message": {"chat": {}, "from": {}}},
                        {"update_id": 1, "message": {"chat": {"id": 7}, "from": {"id": 8}}}):
            with self.assertRaises(InvalidUpdate, msg=payload):
                update_from_telegram(payload)

    def test_voice_uses_injectable_resolver_and_fails_closed_without_it(self):
        payload = {"update_id": 3, "message": {"chat": {"id": 7, "type": "private"},
                                               "from": {"id": 8},
                                               "voice": {"file_id": "f1", "duration": 2,
                                                         "mime_type": "audio/ogg"}}}
        with self.assertRaises(InvalidUpdate):
            update_from_telegram(payload)
        update = update_from_telegram(payload, resolve_file=lambda fid: b"OggS bytes")
        self.assertEqual(update.media.kind, MediaKind.VOICE)
        self.assertEqual(update.media.data, b"OggS bytes")

    def test_oversized_voice_is_rejected_after_resolution(self):
        payload = {"update_id": 4, "message": {"chat": {"id": 7, "type": "private"},
                                               "from": {"id": 8},
                                               "voice": {"file_id": "f1", "duration": 301,
                                                         "mime_type": "audio/ogg"}}}
        with self.assertRaises(InvalidUpdate):
            update_from_telegram(payload, resolve_file=lambda fid: b"OggS")


class RuntimeFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.publisher = MemoryPublisher()
        self.audit = []
        self.runtime = IdeaCaptureRuntime(
            config=policy_for(7),
            state_path=self.root / "capture.sqlite3",
            mundos_root=self.root / "mundos",
            active_world="vibrantes",
            publisher=self.publisher,
            audit=self.audit.append,
        )

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def test_fail_closed_rejects_unauthorized_without_network(self):
        with self.assertRaises(UnauthorizedUpdate):
            self.runtime.handle_update(text_payload(1, chat=55))
        self.assertEqual(self.runtime.store.count(), 0)
        self.assertEqual(self.audit[0]["event"], "unauthorized_update")

    def test_save_change_cancel_flow_through_worker(self):
        receipt = self.runtime.handle_update(text_payload(1, text="first idea"))
        self.assertEqual(receipt.status, "RAW_PERSISTED")
        # Global-first default: the prompt names the Taller de Ideas save.
        self.assertEqual(receipt.prompt, ("Save global", "Cancel"))

        self.runtime.confirm(receipt.capture_id, WorldAction.SAVE)
        saved = self.runtime.wait_state(receipt.capture_id, CaptureState.SAVED)
        self.assertEqual(saved.state, CaptureState.SAVED)
        self.assertTrue((self.root / "mundos" / "vibrantes" / "Ideas" / f"{saved.slug}.md").exists())

        cancelled = self.runtime.handle_update(text_payload(2, text="second idea"))
        self.runtime.confirm(cancelled.capture_id, WorldAction.CANCEL)
        self.assertEqual(self.runtime.store.get(cancelled.capture_id).state, CaptureState.CANCELLED)

        changed = self.runtime.handle_update(text_payload(3, text="third idea"))
        self.runtime.confirm(changed.capture_id, WorldAction.CHANGE_WORLD, "nec")
        moved = self.runtime.wait_state(changed.capture_id, CaptureState.SAVED)
        self.assertEqual(moved.world, "nec")
        self.assertTrue((self.root / "mundos" / "nec" / "Ideas" / f"{moved.slug}.md").exists())

        # Invalid world is rejected and does not reach the worker.
        with self.assertRaises(ValueError):
            self.runtime.confirm(cancelled.capture_id, WorldAction.CHANGE_WORLD, "../unsafe")

        self.runtime.drain_outbox()
        self.assertEqual(len(self.publisher.messages), 2)

    def test_media_update_resolves_through_injected_resolver(self):
        resolver = lambda fid: b"OggS media"  # noqa: E731
        self.runtime.resolve_file = resolver
        payload = {"update_id": 9, "message": {"chat": {"id": 7, "type": "private"},
                                               "from": {"id": 8},
                                               "voice": {"file_id": "f1", "duration": 3,
                                                         "mime_type": "audio/ogg"}}}
        receipt = self.runtime.handle_update(payload)
        self.assertEqual(receipt.status, "RAW_PERSISTED")


class OwnershipTests(unittest.TestCase):
    def test_single_owner_and_stale_takeover(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "owner.lock"
            import os
            current = os.getpid()
            alive = lambda pid: pid == current  # only the live owner is alive  # noqa: E731
            first = OwnershipLock(lock, pid_alive=alive)
            second = OwnershipLock(lock, pid_alive=alive)

            state = first.acquire()
            self.assertTrue(state.acquired)
            refused = second.acquire()
            self.assertFalse(refused.acquired)
            self.assertIn("alive", refused.reason)

            first.release()
            self.assertFalse(lock.exists())
            # A stale lock (dead pid) is taken over, not duplicated.
            lock.write_text("999999", encoding="utf-8")
            takeover = OwnershipLock(lock, pid_alive=alive)
            self.assertTrue(takeover.acquire().acquired)
            takeover.release()

    def test_health_check_refuses_second_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "owner.lock"
            unhealthy = OwnershipLock(lock, health_check=lambda: False)
            self.assertFalse(unhealthy.acquire().acquired)
            healthy = OwnershipLock(lock, health_check=lambda: True)
            self.assertTrue(healthy.acquire().acquired)
            healthy.release()


class ConfirmationCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = IdeaCaptureRuntime(config=policy_for(7),
                                          state_path=self.root / "capture.sqlite3",
                                          mundos_root=self.root / "mundos",
                                          active_world="vibrantes")

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def test_commands_drive_the_confirmation_flow(self):
        receipt = self.runtime.handle_update(text_payload(1, text="idea"))
        self.assertIn("Usá `/save", handle_confirmation_command(self.runtime, "hola"))
        self.assertIn("guardada", handle_confirmation_command(self.runtime, f"/save {receipt.capture_id}"))
        self.runtime.wait_state(receipt.capture_id, CaptureState.SAVED)

        receipt2 = self.runtime.handle_update(text_payload(2, text="idea2"))
        reply = handle_confirmation_command(self.runtime, f"/world {receipt2.capture_id} nec")
        self.assertIn("asignada", reply)
        self.runtime.wait_state(receipt2.capture_id, CaptureState.SAVED)

        receipt3 = self.runtime.handle_update(text_payload(3, text="idea3"))
        self.assertIn("cancelada", handle_confirmation_command(self.runtime, f"/cancel {receipt3.capture_id}"))
        self.assertEqual(self.runtime.store.get(receipt3.capture_id).state, CaptureState.CANCELLED)

    def test_unknown_capture_is_reported_not_crashed(self):
        self.assertIn("⚠", handle_confirmation_command(self.runtime, "/save nope"))


class FakeTransport:
    """Offline Telegram boundary: returns canned updates, records replies."""

    def __init__(self, updates):
        self.updates = updates
        self.sent = []          # (chat_id, text) sent via send_message
        self.sent_markup = []   # reply_markup passed to each send_message
        self.answered = []      # (callback_query_id, text) from answer_callback_query

    def get_updates(self, offset):
        return [u for u in self.updates if u["update_id"] >= offset]

    def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text))
        self.sent_markup.append(reply_markup)
        return text

    def answer_callback_query(self, callback_query_id, text=None):
        self.answered.append((callback_query_id, text))


def callback_payload(update_id: int, query_id: str, chat: int = 7, sender: int = 8,
                     data: str = "capture:unused:save", group: bool = False) -> dict:
    return {"update_id": update_id, "callback_query": {
        "id": query_id,
        "from": {"id": sender},
        "message": {"chat": {"id": chat, "type": "supergroup" if group else "private"}},
        "data": data}}


class PollLoopTests(unittest.TestCase):
    def test_poll_once_runs_capture_and_confirmation_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            publisher = MemoryPublisher()
            runtime = IdeaCaptureRuntime(config=policy_for(7),
                                         state_path=root / "capture.sqlite3",
                                         mundos_root=root / "mundos",
                                         active_world="vibrantes",
                                         publisher=publisher)
            transport = FakeTransport([text_payload(1, text="capture me")])
            try:
                # First poll: the text idea is captured and acknowledged.
                offset = poll_once(runtime, transport, 0, replies=[])
                self.assertEqual(offset, 2)
                self.assertEqual(len(transport.sent), 1)
                self.assertIn("id=", transport.sent[0][1])
                self.assertEqual(runtime.store.count(), 1)

                # Second poll: the owner confirms with /save and the worker saves it.
                capture_id = runtime.store.list_capture_ids()[0]
                transport.updates = [text_payload(3, text=f"/save {capture_id}")]
                offset = poll_once(runtime, transport, offset, replies=[])
                self.assertEqual(offset, 4)
                saved = runtime.wait_state(capture_id, CaptureState.SAVED)
                self.assertEqual(saved.state, CaptureState.SAVED)
                self.assertEqual(len(transport.sent), 2)  # capture ack + confirmation reply
                self.assertIn("guardada", transport.sent[1][1])
                self.assertTrue(
                    (root / "mundos" / "vibrantes" / "Ideas" / f"{saved.slug}.md").exists())

                # Outbox carries exactly one message; drain publishes once.
                runtime.drain_outbox()
                self.assertEqual(len(publisher.messages), 1)
                self.assertEqual(len(runtime.store.pending_outbox()), 0)
            finally:
                runtime.close()


class KeyboardTests(unittest.TestCase):
    def test_capture_keyboard_defaults_to_global_save(self):
        capture_id = "c" * 36
        keyboard = build_capture_keyboard(capture_id)
        buttons = {b["text"]: b["callback_data"]
                   for b in keyboard["inline_keyboard"][0]}
        # SAVE_GLOBAL is the default path: no world chosen at capture, so the
        # keyboard only offers the Taller de Ideas save and Cancel.
        self.assertEqual(list(buttons),
                         ["Guardar en Taller de Ideas", "Cancelar"])
        self.assertEqual(buttons["Guardar en Taller de Ideas"],
                         f"capture:{capture_id}:save_global")
        self.assertEqual(buttons["Cancelar"], f"capture:{capture_id}:cancel")
        # The per-world buttons are NOT offered on the primary keyboard.
        self.assertNotIn("Guardar", buttons)
        self.assertNotIn("Cambiar mundo", buttons)
        for data in buttons.values():
            self.assertLessEqual(len(data), 64)

    def test_world_keyboard_lists_safe_worlds_including_active(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "mundos" / "vibrantes").mkdir(parents=True)
            (root / "mundos" / "nec").mkdir(parents=True)
            (root / "mundos" / ".hidden").mkdir()
            (root / "mundos" / "bad name").mkdir()  # unsafe name -> excluded
            (root / "mundos" / "plain.txt").write_text("x", encoding="utf-8")
            runtime = IdeaCaptureRuntime(config=policy_for(7),
                                         state_path=root / "capture.sqlite3",
                                         mundos_root=root / "mundos",
                                         active_world="vibrantes")
            try:
                self.assertEqual(runtime.available_worlds(), ["nec", "vibrantes"])
                keyboard = build_world_keyboard(runtime, "c" * 36)
                worlds = {b["text"]: b["callback_data"]
                          for row in keyboard["inline_keyboard"] for b in row}
                self.assertEqual(sorted(worlds), ["nec", "vibrantes"])
                self.assertEqual(worlds["vibrantes"], f"capture:{'c'*36}:world:vibrantes")
                for data in worlds.values():
                    self.assertLessEqual(len(data), 64)
            finally:
                runtime.close()

    def test_callback_encoding_round_trip(self):
        capture_id = "a" * 36
        cases = [(WorldAction.SAVE, None), (WorldAction.CANCEL, None),
                 (WorldAction.CHANGE_WORLD, None), (WorldAction.CHANGE_WORLD, "nec"),
                 (WorldAction.SAVE_GLOBAL, None)]
        for action, world in cases:
            parsed = parse_capture_callback(encode_capture_callback(capture_id, action, world))
            self.assertEqual(parsed, (capture_id, action, world))

    def test_malformed_callback_data_is_rejected_by_parser(self):
        capture_id = "a" * 36
        for bad in (None, 123, "", "save", "capture:", f"capture:{capture_id}:save:extra",
                    "capture:zz-not-a-uuid:save", f"capture:{capture_id}:explode",
                    f"capture:{capture_id}:world:../unsafe",
                    f"capture:{capture_id}:world:{'x' * 100}"):
            self.assertIsNone(parse_capture_callback(bad), msg=repr(bad))


class CallbackFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "mundos" / "vibrantes").mkdir(parents=True)
        (self.root / "mundos" / "nec").mkdir(parents=True)
        self.publisher = MemoryPublisher()
        self.audit = []
        self.runtime = IdeaCaptureRuntime(config=policy_for(7),
                                          state_path=self.root / "capture.sqlite3",
                                          mundos_root=self.root / "mundos",
                                          active_world="vibrantes",
                                          publisher=self.publisher,
                                          audit=self.audit.append)

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def capture(self, update_id=1, text="button idea"):
        return self.runtime.handle_update(text_payload(update_id, text=text)).capture_id

    def test_save_callback_confirms_directly_and_never_leaks_content(self):
        capture_id = self.capture()
        transport = FakeTransport(
            [callback_payload(50, "q-save", data=f"capture:{capture_id}:save")])
        replies = []
        offset = poll_once(self.runtime, transport, 0, replies)
        self.assertEqual(offset, 51)
        saved = self.runtime.wait_state(capture_id, CaptureState.SAVED)
        self.assertEqual(saved.state, CaptureState.SAVED)
        self.assertTrue(
            (self.root / "mundos" / "vibrantes" / "Ideas" / f"{saved.slug}.md").exists())
        # The callback is acknowledged (spinner cleared) with a confirmation.
        self.assertEqual(transport.answered,
                         [("q-save", "✅ Idea guardada en vibrantes (procesando…).")])
        self.assertEqual(replies, ["✅ Idea guardada en vibrantes (procesando…)."])
        # No idea text leaves through the transport, and nothing is echoed back.
        self.assertNotIn("button idea", str(transport.sent))
        self.assertNotIn("button idea", str(transport.answered))
        self.runtime.drain_outbox()
        self.assertEqual(len(self.publisher.messages), 1)

    def test_cancel_callback_cancels_directly(self):
        capture_id = self.capture()
        transport = FakeTransport(
            [callback_payload(50, "q-cancel", data=f"capture:{capture_id}:cancel")])
        poll_once(self.runtime, transport, 0, [])
        self.assertEqual(self.runtime.store.get(capture_id).state, CaptureState.CANCELLED)
        self.assertEqual(transport.answered, [("q-cancel", "🗑 Idea cancelada.")])

    def test_change_world_shows_picker_then_confirms_explicit_world(self):
        capture_id = self.capture()
        transport = FakeTransport(
            [callback_payload(50, "q-picker", data=f"capture:{capture_id}:world")])
        replies = []
        poll_once(self.runtime, transport, 0, replies)
        # A second inline keyboard with the safe worlds is sent, no command needed.
        self.assertEqual(len(transport.sent), 1)
        _chat_id, text = transport.sent[0]
        markup = transport.sent_markup[0]
        self.assertIn("Elegí el mundo", text)
        worlds = {b["text"]: b["callback_data"]
                  for row in markup["inline_keyboard"] for b in row}
        self.assertEqual(sorted(worlds), ["nec", "vibrantes"])
        self.assertEqual(worlds["nec"], f"capture:{capture_id}:world:nec")
        self.assertEqual(transport.answered, [("q-picker", "Elegí un mundo.")])
        # The picker itself never mutates the capture.
        self.assertEqual(self.runtime.store.get(capture_id).state, CaptureState.RAW_PERSISTED)

        # The owner taps a world -> explicit confirm -> durable save.
        transport.updates = [
            callback_payload(51, "q-world", data=f"capture:{capture_id}:world:nec")]
        offset = poll_once(self.runtime, transport, 50, replies)
        self.assertEqual(offset, 52)
        moved = self.runtime.wait_state(capture_id, CaptureState.SAVED)
        self.assertEqual(moved.world, "nec")
        self.assertTrue(
            (self.root / "mundos" / "nec" / "Ideas" / f"{moved.slug}.md").exists())
        self.assertEqual(transport.answered[-1],
                         ("q-world", "✅ Idea asignada a nec (procesando…)."))

    def test_malformed_and_unknown_callbacks_are_rejected_without_mutation(self):
        capture_id = self.capture()
        before = self.runtime.store.count()
        payloads = [
            callback_payload(60, "q-bad", data="garbage"),
            callback_payload(61, "q-unknown", data=f"capture:{'f'*36}:save"),
            callback_payload(62, "q-unsafe", data=f"capture:{capture_id}:world:../unsafe"),
            callback_payload(63, "q-ghost", data=f"capture:{capture_id}:world:ghost"),
            callback_payload(64, "q-big", data="x" * 100),
        ]
        transport = FakeTransport(payloads)
        poll_once(self.runtime, transport, 0, [])
        self.assertEqual(self.runtime.store.count(), before)
        self.assertEqual(self.runtime.store.get(capture_id).state, CaptureState.RAW_PERSISTED)
        # Every callback is acknowledged (spinner cleared), none mutate.
        self.assertEqual(len(transport.answered), len(payloads))
        self.assertEqual(transport.sent, [])  # no follow-up messages
        self.assertTrue(any(e["event"] == "malformed_callback" for e in self.audit))

    def test_callback_from_unauthorized_chat_is_rejected_without_mutation(self):
        capture_id = self.capture()
        transport = FakeTransport(
            [callback_payload(70, "q-nope", chat=55, data=f"capture:{capture_id}:save")])
        poll_once(self.runtime, transport, 0, [])
        self.assertEqual(transport.answered, [("q-nope", "No autorizado.")])
        self.assertEqual(self.runtime.store.get(capture_id).state, CaptureState.RAW_PERSISTED)
        self.assertTrue(any(e["event"] == "unauthorized_callback" for e in self.audit))

    def test_callback_without_bindable_chat_is_rejected_without_mutation(self):
        capture_id = self.capture()
        payload = {"update_id": 80, "callback_query": {
            "id": "q-noid", "from": {"id": 8},
            "data": f"capture:{capture_id}:save"}}
        transport = FakeTransport([payload])
        poll_once(self.runtime, transport, 0, [])
        self.assertEqual(self.runtime.store.get(capture_id).state, CaptureState.RAW_PERSISTED)
        self.assertEqual(transport.answered, [("q-noid", "Acción inválida.")])

    def test_text_commands_still_work_alongside_callbacks(self):
        first = self.capture(update_id=1, text="first")
        second = self.runtime.handle_update(text_payload(2, text="second")).capture_id
        transport = FakeTransport([
            callback_payload(60, "q-save", data=f"capture:{first}:save"),
            text_payload(61, text=f"/save {second}"),
        ])
        poll_once(self.runtime, transport, 0, [])
        self.assertEqual(self.runtime.wait_state(first, CaptureState.SAVED).state,
                         CaptureState.SAVED)
        self.assertEqual(self.runtime.wait_state(second, CaptureState.SAVED).state,
                         CaptureState.SAVED)
        # Callback answered via toast; command answered via message.
        self.assertEqual(len(transport.answered), 1)
        self.assertIn("guardada", transport.sent[-1][1])


class GlobalSaveFlowTests(unittest.TestCase):
    """SAVE_GLOBAL: capture persists to the global ideas/ bank, no world."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "mundos" / "vibrantes").mkdir(parents=True)
        self.publisher = MemoryPublisher()
        self.audit = []
        self.runtime = IdeaCaptureRuntime(
            config=policy_for(7),
            state_path=self.root / "capture.sqlite3",
            mundos_root=self.root / "mundos",
            active_world="vibrantes",
            publisher=self.publisher,
            audit=self.audit.append,
            global_ideas_root=self.root / "ideas",
        )

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def test_save_global_writes_to_global_bank_without_world(self):
        receipt = self.runtime.handle_update(text_payload(1, text="global idea"))
        record = self.runtime.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        self.assertTrue(record.global_)
        self.assertIsNone(record.world)
        saved = self.runtime.wait_state(receipt.capture_id, CaptureState.SAVED)
        self.assertEqual(saved.state, CaptureState.SAVED)
        target = self.root / "ideas" / f"{saved.slug}.md"
        self.assertTrue(target.exists())
        content = target.read_text(encoding="utf-8")
        self.assertIn("source: telegram", content)
        self.assertIn("status: fresh", content)
        self.assertIn("used_in: []", content)
        # Default (offline) enrich fails open to the explicit bucket.
        self.assertIn("type: sin_clasificar", content)
        self.assertNotIn("idea_loose", content)
        # The per-world bank was NOT written.
        self.assertFalse(
            (self.root / "mundos" / "vibrantes" / "Ideas" / f"{saved.slug}.md").exists())
        self.runtime.drain_outbox()
        self.assertEqual(len(self.publisher.messages), 1)

    def test_save_global_uses_enriched_type(self):
        self.runtime.processor.enrich = lambda raw: (str(raw).strip(), "trama")
        receipt = self.runtime.handle_update(text_payload(1, text="a plot twist"))
        self.runtime.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
        saved = self.runtime.wait_state(receipt.capture_id, CaptureState.SAVED)
        content = (self.root / "ideas" / f"{saved.slug}.md").read_text(encoding="utf-8")
        self.assertIn("type: trama", content)
        self.assertIn("a plot twist", content)

    def test_save_global_callback_persists_to_global_bank(self):
        capture_id = self.runtime.handle_update(
            text_payload(1, text="button global idea")).capture_id
        transport = FakeTransport(
            [callback_payload(50, "q-global", data=f"capture:{capture_id}:save_global")])
        replies = []
        poll_once(self.runtime, transport, 0, replies)
        saved = self.runtime.wait_state(capture_id, CaptureState.SAVED)
        self.assertEqual(saved.state, CaptureState.SAVED)
        self.assertTrue(saved.global_)
        self.assertIsNone(saved.world)
        self.assertTrue((self.root / "ideas" / f"{saved.slug}.md").exists())
        self.assertEqual(transport.answered,
                         [("q-global", "✅ Idea guardada en el Taller de Ideas (procesando…).")])
        self.assertEqual(replies, ["✅ Idea guardada en el Taller de Ideas (procesando…)."])

    def test_save_global_without_global_ideas_root_is_retryable(self):
        # A runtime that never received a global root cannot persist globally:
        # the capture is retryable, never SAVED, and never crashes the flow.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = IdeaCaptureRuntime(config=policy_for(7),
                                         state_path=root / "capture.sqlite3",
                                         mundos_root=root / "mundos",
                                         active_world="vibrantes")
            try:
                receipt = runtime.handle_update(text_payload(1, text="orphan idea"))
                runtime.confirm(receipt.capture_id, WorldAction.SAVE_GLOBAL)
                record = runtime.wait_state(receipt.capture_id, CaptureState.RETRYABLE,
                                            timeout=5)
                self.assertEqual(record.state, CaptureState.RETRYABLE)
                self.assertIn("global_ideas_root", record.error)
            finally:
                runtime.close()


class PerWorldInvariantRegressionTests(unittest.TestCase):
    """Dedicated regression (R-CG-01): SAVE/CHANGE_WORLD/CANCEL behave
    identically to the pre-SAVE_GLOBAL runtime — the additive invariant."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.publisher = MemoryPublisher()
        self.runtime = IdeaCaptureRuntime(
            config=policy_for(7),
            state_path=self.root / "capture.sqlite3",
            mundos_root=self.root / "mundos",
            active_world="vibrantes",
            publisher=self.publisher,
        )

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def test_per_world_save_is_unchanged(self):
        receipt = self.runtime.handle_update(text_payload(1, text="per-world idea"))
        self.runtime.confirm(receipt.capture_id, WorldAction.SAVE)
        saved = self.runtime.wait_state(receipt.capture_id, CaptureState.SAVED)
        self.assertFalse(saved.global_)
        self.assertEqual(saved.world, "vibrantes")
        target = self.root / "mundos" / "vibrantes" / "Ideas" / f"{saved.slug}.md"
        self.assertTrue(target.exists())
        content = target.read_text(encoding="utf-8")
        # Legacy per-world schema untouched: type idea_loose, status pending.
        self.assertIn("type: idea_loose", content)
        self.assertIn("status: pending", content)
        self.assertIn("source: telegram", content)
        # The global bank was NOT written.
        self.assertFalse((self.root / "ideas" / f"{saved.slug}.md").exists())

    def test_change_world_is_unchanged(self):
        (self.root / "mundos" / "nec").mkdir(parents=True)
        receipt = self.runtime.handle_update(text_payload(2, text="move me"))
        self.runtime.confirm(receipt.capture_id, WorldAction.CHANGE_WORLD, "nec")
        moved = self.runtime.wait_state(receipt.capture_id, CaptureState.SAVED)
        self.assertEqual(moved.world, "nec")
        self.assertFalse(moved.global_)
        self.assertTrue((self.root / "mundos" / "nec" / "Ideas" / f"{moved.slug}.md").exists())

    def test_cancel_is_unchanged(self):
        receipt = self.runtime.handle_update(text_payload(3, text="discard me"))
        self.runtime.confirm(receipt.capture_id, WorldAction.CANCEL)
        record = self.runtime.store.get(receipt.capture_id)
        self.assertEqual(record.state, CaptureState.CANCELLED)
        self.assertFalse(record.global_)
        self.assertFalse(
            (self.root / "mundos" / "vibrantes" / "Ideas" / f"{record.slug}.md").exists())

    def test_invalid_world_still_rejected(self):
        receipt = self.runtime.handle_update(text_payload(4, text="bad target"))
        with self.assertRaises(ValueError):
            self.runtime.confirm(receipt.capture_id, WorldAction.CHANGE_WORLD, "../unsafe")
        self.assertEqual(self.runtime.store.get(receipt.capture_id).state,
                         CaptureState.RAW_PERSISTED)


if __name__ == "__main__":
    unittest.main()
