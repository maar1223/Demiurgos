"""The sole, thin Telegram ingress owner for native idea capture."""

from dataclasses import dataclass
from threading import Lock

from .media import MediaValidationError, validate_media
from .models import AuditWriter, CaptureReceipt, TelegramUpdate, WorldAction


class UnauthorizedUpdate(PermissionError):
    pass


@dataclass(frozen=True)
class IngressPolicy:
    private_chat_ids: frozenset[int]
    approved_group_senders: dict[int, frozenset[int]]
    authorized_bindings: frozenset[str] = frozenset()
    require_binding: bool = False


class TelegramIngress:
    def __init__(self, policy: IngressPolicy, audit: AuditWriter):
        self.policy = policy
        self.audit = audit
        self._seen: set[tuple[str, int]] = set()
        self._seen_lock = Lock()

    def accept(self, update: TelegramUpdate, active_world: str) -> CaptureReceipt:
        if not self._authorized(update):
            self.audit({"event": "unauthorized_update", "update_id": update.update_id,
                        "chat_id": update.chat_id, "sender_id": update.sender_id})
            raise UnauthorizedUpdate("update rejected by chat policy")
        seen_key = (update.binding_key, update.update_id)
        with self._seen_lock:
            if seen_key in self._seen:
                return CaptureReceipt(update.update_id, "DUPLICATE")
        try:
            validate_media(update.media)
        except MediaValidationError as error:
            self.audit({"event": "invalid_update", "update_id": update.update_id,
                        "reason": str(error)})
            raise
        with self._seen_lock:
            self._seen.add(seen_key)
        self.audit({"event": "received", "update_id": update.update_id,
                    "media": update.media.kind.value, "world": active_world})
        return CaptureReceipt(update.update_id, "AWAITING_WORLD")

    @staticmethod
    def world_buttons() -> tuple[str, ...]:
        return ("Save", "Change world", "Cancel")

    @staticmethod
    def confirm_world(action: WorldAction, active_world: str, selected_world: str | None = None) -> str | None:
        if action is WorldAction.CANCEL:
            return None
        if action is WorldAction.SAVE:
            return active_world
        if action is WorldAction.CHANGE_WORLD and selected_world:
            return selected_world
        raise ValueError("Change world requires an explicit selected world")

    def _authorized(self, update: TelegramUpdate) -> bool:
        if self.policy.require_binding:
            return update.binding_key in self.policy.authorized_bindings
        if self.policy.authorized_bindings:
            return update.binding_key in self.policy.authorized_bindings
        if not update.is_group:
            return update.chat_id in self.policy.private_chat_ids
        return update.sender_id in self.policy.approved_group_senders.get(update.chat_id, frozenset())
