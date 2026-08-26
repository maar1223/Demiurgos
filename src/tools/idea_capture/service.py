"""Application boundary: ingress only stores raw input and returns immediately."""

import re

from .models import CaptureReceipt, TelegramUpdate, WorldAction
from .store import CaptureStore
from .telegram import TelegramIngress

_WORLD = re.compile(r"^[A-Za-z0-9_-]+$")


class CaptureService:
    def __init__(self, ingress: TelegramIngress, store: CaptureStore, active_world: str):
        self.ingress, self.store, self.active_world = ingress, store, active_world

    def accept(self, update: TelegramUpdate) -> CaptureReceipt:
        self.ingress.accept(update, self.active_world)
        existing = self.store.find_by_source_update(update)
        record = self.store.reserve(update)
        status = "DUPLICATE" if existing is not None else "RAW_PERSISTED"
        return CaptureReceipt(update.update_id, status,
                              ("Save", "Change world", "Cancel"), record.capture_id)

    def confirm(self, capture_id: str, action: WorldAction, selected_world: str | None = None):
        if action is WorldAction.CANCEL:
            return self.store.set_world(capture_id, None)
        if action is WorldAction.SAVE_GLOBAL:
            # Global bank capture: no world required, durable processing.
            return self.store.set_global(capture_id)
        world = self.active_world if action is WorldAction.SAVE else selected_world
        if not world or not _WORLD.fullmatch(world):
            raise ValueError("world must be a safe explicit name")
        return self.store.set_world(capture_id, world)
