"""Platform-neutral contracts for the native capture boundary."""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


class MediaKind(str, Enum):
    TEXT = "text"
    VOICE = "voice"
    IMAGE = "image"


class WorldAction(str, Enum):
    SAVE = "save"
    CHANGE_WORLD = "change_world"
    CANCEL = "cancel"
    SAVE_GLOBAL = "save_global"


class CaptureState(str, Enum):
    RECEIVED = "RECEIVED"
    RAW_PERSISTED = "RAW_PERSISTED"
    AWAITING_WORLD = "AWAITING_WORLD"
    PROCESSING = "PROCESSING"
    SAVED = "SAVED"
    RETRYABLE = "RETRYABLE"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class MediaInput:
    kind: MediaKind
    data: bytes = b""
    mime: str = ""
    duration_seconds: Optional[float] = None
    text: str = ""
    path: str = ""


@dataclass(frozen=True)
class TelegramUpdate:
    update_id: int
    chat_id: int
    sender_id: int
    is_group: bool
    media: MediaInput
    platform: str = "telegram"
    profile: str = "default"

    @property
    def binding_key(self) -> str:
        """Stable identity for auth and idempotency; chat and user stay distinct."""
        return ":".join((
            self.platform,
            str(self.chat_id),
            str(self.sender_id),
            self.profile or "default",
        ))


@dataclass(frozen=True)
class CaptureReceipt:
    update_id: int
    status: str
    # Global-first default: capture always lands in the Taller de Ideas. The
    # per-world Save/Change world actions remain a world-scoped variant.
    prompt: tuple[str, ...] = ("Save global", "Cancel")
    capture_id: str | None = None


@dataclass(frozen=True)
class CaptureRecord:
    capture_id: str
    update_id: int
    world: str | None
    state: CaptureState
    raw_text: str
    raw_bytes: bytes
    mime: str
    media_kind: MediaKind
    slug: str
    attempt: int
    error: str | None = None
    created_at: str = ""
    source: str = ""
    media_path: str = ""
    media_duration_seconds: float | None = None
    global_: bool = False


AuditWriter = Callable[[dict], None]
