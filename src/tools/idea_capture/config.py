"""Fail-closed loading of config/idea-capture.yaml into the ingress policy.

Missing file or empty allowlists mean NOTHING is authorized: every update is
rejected until an operator explicitly adds chat ids / approved senders. A
malformed file or a non-numeric id raises ValueError instead of silently
granting or revoking access.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .telegram import IngressPolicy

log = logging.getLogger(__name__)
_ID = re.compile(r"^-?\d+$")
_PROFILE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class CaptureLimits:
    image_mb: int = 20
    audio_mb: int = 50
    audio_minutes: int = 5
    raw_retention_days: int = 30


@dataclass(frozen=True)
class CaptureConfig:
    policy: IngressPolicy
    limits: CaptureLimits


def load_policy(config_path: str | Path) -> CaptureConfig:
    """Parse the YAML config. Missing file -> empty policy (fail closed)."""
    raw: dict[str, Any] = _load_yaml(config_path)
    private = _int_list(raw.get("private_chat_ids"), "private_chat_ids")
    groups: dict[int, frozenset[int]] = {}
    groups_raw = raw.get("approved_groups") or {}
    if not isinstance(groups_raw, dict):
        raise ValueError("approved_groups must be a mapping of chat_id -> [sender_id]")
    for chat, senders in groups_raw.items():
        chat_id = _as_int(chat, "approved_groups key")
        senders_list = _int_list(senders, f"approved_groups.{chat}")
        if senders_list:
            groups[chat_id] = frozenset(senders_list)
    bindings = _binding_list(raw.get("authorized_bindings"), "authorized_bindings")
    limits_raw = raw.get("limits") or {}
    limits = CaptureLimits(
        image_mb=int(_as_int(limits_raw.get("image_mb", 20), "limits.image_mb")),
        audio_mb=int(_as_int(limits_raw.get("audio_mb", 50), "limits.audio_mb")),
        audio_minutes=int(_as_int(limits_raw.get("audio_minutes", 5), "limits.audio_minutes")),
        raw_retention_days=int(_as_int(limits_raw.get("raw_retention_days", 30),
                                      "limits.raw_retention_days")),
    )
    return CaptureConfig(
        IngressPolicy(
            frozenset(private), groups,
            authorized_bindings=frozenset(":".join(binding) for binding in bindings),
        ),
        limits,
    )


def load_active_world(config_path: str | Path, fallback: str = "") -> str:
    """Read the non-secret world selector used by the native handler."""
    raw = _load_yaml(config_path)
    value = raw.get("active_world")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback.strip()


def _load_yaml(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    if not path.is_file():
        log.warning("idea-capture config %s missing; policy is empty (fail closed)", path)
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid idea-capture config {path}: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"idea-capture config {path} must be a mapping")
    return raw


def _as_int(value: Any, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer, got {value!r}") from exc


def _int_list(value: Any, label: str) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list of integers")
    return [_as_int(item, f"{label} entry") for item in value]


def _binding_list(value: Any, label: str) -> list[tuple[str, str, str, str]]:
    """Parse exact native identities without conflating chat and user IDs."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list of bindings")
    bindings: list[tuple[str, str, str, str]] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise ValueError(f"{label}[{index}] must be a mapping")
        platform = str(entry.get("platform", "")).strip().lower()
        chat_id = str(entry.get("chat_id", "")).strip()
        user_id = str(entry.get("user_id", "")).strip()
        profile = str(entry.get("profile", "default")).strip() or "default"
        if platform != "telegram":
            raise ValueError(f"{label}[{index}].platform must be telegram")
        if not chat_id or not user_id or not profile:
            raise ValueError(
                f"{label}[{index}] requires platform, chat_id, user_id, and profile"
            )
        if not _ID.fullmatch(chat_id) or not _ID.fullmatch(user_id):
            raise ValueError(f"{label}[{index}] chat_id and user_id must be integers")
        if not _PROFILE.fullmatch(profile):
            raise ValueError(f"{label}[{index}].profile is unsafe")
        bindings.append((platform, chat_id, user_id, profile))
    return bindings
