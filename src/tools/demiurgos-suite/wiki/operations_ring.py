# -*- coding: utf-8 -*-
"""Operations ring buffer (Phase 1, S5, task T1.3).

A bug report has to answer "what was done, and where did it fail" without
shipping a database. This module owns one append-only JSONL file under the
install's state directory and the ASGI middleware that feeds it.

Deliberate limits:

- **Fixed schema, never author content.** Only the documented keys are stored,
  the world is stored as a :func:`hash_world` digest and free text (endpoint,
  error code) is clipped, so a caller cannot accidentally journal world text or
  a prompt body into a bundle that leaves the author's machine (S6).
- **Bounded by entries and bytes.** At most :data:`MAX_ENTRIES` records and
  :data:`MAX_BYTES` on disk; the newest records are the ones kept. The file is
  rewritten atomically (temp + ``os.replace``) when it would exceed either
  bound, so a crash during compaction cannot corrupt the ring.
- **Append-only between compactions.** A record is one ``write`` of one line,
  which survives a crash of the API; a torn trailing line is skipped by the
  reader instead of poisoning the whole file.
- **Failures and writes only.** The middleware records ``/api/*`` requests that
  either failed (``status >= 400``) or changed something (POST/PUT/PATCH/DELETE).
  Successful reads are skipped on purpose: the UI polls graph and health
  endpoints on a timer and would otherwise evict every real operation.
- **Never breaks a request.** Every storage error is swallowed and the
  middleware runs no matter what; recording is observability, not a dependency.
- ``DEMIURGOS_OPERATIONS_RING=0`` disables recording (the rollback switch).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import state_paths

RING_FILENAME = "operations-ring.jsonl"
MAX_ENTRIES = 200
MAX_BYTES = 512 * 1024
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
KILL_SWITCH_ENV = "DEMIURGOS_OPERATIONS_RING"
KILL_SWITCH_VALUES = frozenset({"0", "false", "no", "off"})
#: Free-text fields are clipped: a path or an error code is not a document.
MAX_TEXT_CHARS = 300
#: How much of a failed response body is parsed to learn its stable error code.
MAX_ERROR_BODY_BYTES = 8192

_lock = threading.Lock()
_counts: dict[str, int] = {}


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def recording_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Whether the middleware records at all (kill switch, default on)."""
    env = os.environ if environ is None else environ
    return str(env.get(KILL_SWITCH_ENV, "")).strip().lower() not in KILL_SWITCH_VALUES


def hash_world(world: object) -> str | None:
    """Stable, non-reversible world identifier (``None`` when absent)."""
    if not isinstance(world, str) or not world.strip():
        return None
    return hashlib.sha256(world.strip().encode("utf-8")).hexdigest()[:16]


def default_ring_path() -> Path:
    """Where the ring lives: the state dir, beside the other state artifacts."""
    return state_paths.resolve_state_dir() / RING_FILENAME


def _clip(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:MAX_TEXT_CHARS]


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _normalize(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    """Reduce an entry to the fixed, non-content-bearing schema."""
    if not isinstance(entry, Mapping):
        return None
    world_hash = entry.get("world_hash")
    if not isinstance(world_hash, str) or not world_hash:
        world_hash = hash_world(entry.get("world"))
    return {
        "ts": _clip(entry.get("ts")) or _iso_now(),
        "run_id": _clip(entry.get("run_id")) or "",
        "method": (str(entry.get("method") or "")).upper()[:16],
        "endpoint": _clip(entry.get("endpoint")),
        "world_hash": world_hash,
        "status": _int_or_none(entry.get("status")),
        "duration_ms": _int_or_none(entry.get("duration_ms")),
        "error_code": _clip(entry.get("error_code")),
    }


def _count_lines(path: Path) -> int:
    count = 0
    try:
        with path.open("rb") as handle:
            for line in handle:
                if line.strip():
                    count += 1
    except OSError:
        return 0
    return count


def _compact(path: Path, *, max_entries: int, max_bytes: int) -> None:
    """Rewrite the ring with the newest records that fit both bounds."""
    try:
        raw = path.read_bytes()
    except OSError:
        return
    lines = [line for line in raw.splitlines() if line.strip()][-max_entries:]
    kept: list[bytes] = []
    used = 0
    for line in reversed(lines):
        cost = len(line) + 1
        if used + cost > max_bytes:
            break
        kept.append(line)
        used += cost
    kept.reverse()
    staged = path.with_name(path.name + ".tmp")
    try:
        staged.write_bytes(b"".join(line + b"\n" for line in kept))
        os.replace(staged, path)
    except OSError:
        try:
            staged.unlink()
        except OSError:
            pass


def record_operation(
    entry: Mapping[str, Any],
    *,
    path: Path | None = None,
    max_entries: int = MAX_ENTRIES,
    max_bytes: int = MAX_BYTES,
) -> bool:
    """Append one bounded record; ``False`` when storage refused it.

    Never raises: an unwritable state dir or a full disk leaves the ring as it
    was and the request that produced the entry untouched.
    """
    normalized = _normalize(entry)
    if normalized is None:
        return False
    target = Path(path) if path is not None else default_ring_path()
    line = (json.dumps(normalized, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    key = str(target)
    with _lock:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("ab") as handle:
                handle.write(line)
            count = _counts.get(key)
            if count is None:
                count = _count_lines(target)
            count += 1
            size = target.stat().st_size
            if count > max_entries or size > max_bytes:
                _compact(target, max_entries=max_entries, max_bytes=max_bytes)
                count = _count_lines(target)
            _counts[key] = count
        except OSError:
            return False
    return True


def recent_operations(
    *,
    limit: int = 50,
    path: Path | None = None,
    max_bytes: int = MAX_BYTES,
) -> list[dict[str, Any]]:
    """The newest records first, skipping a torn line; never raises."""
    if limit <= 0:
        return []
    target = Path(path) if path is not None else default_ring_path()
    try:
        size = target.stat().st_size
        with target.open("rb") as handle:
            start = size - max_bytes if size > max_bytes else 0
            handle.seek(start)
            raw = handle.read()
    except OSError:
        return []
    lines = raw.splitlines()
    if start > 0 and lines:
        # The window may have cut the oldest line in half: drop it.
        lines = lines[1:]
    entries: list[dict[str, Any]] = []
    for line in reversed(lines):
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            decoded = json.loads(text)
        except ValueError:
            continue
        if isinstance(decoded, dict):
            entries.append(decoded)
        if len(entries) >= limit:
            break
    return entries


def _error_code(body: bytes) -> str | None:
    """The stable ``code`` of a structured error body, when it carries one."""
    if not body:
        return None
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    code = payload.get("code")
    return code if isinstance(code, str) and code.strip() else None


class OperationRecorderMiddleware:
    """Record failed and mutating ``/api/*`` requests in the ring.

    An ASGI middleware (like the backup write signal) instead of
    ``BaseHTTPMiddleware``: it never buffers the response, and it reads the
    matched route template and path params *after* the app handled the request,
    so the world name is hashed instead of journaled.
    """

    def __init__(
        self,
        app: Any,
        *,
        recorder: Callable[..., bool] | None = None,
        clock: Callable[[], float] | None = None,
        enabled: Callable[[], bool] | None = None,
        max_body_bytes: int = MAX_ERROR_BODY_BYTES,
    ) -> None:
        self.app = app
        self._record = recorder or record_operation
        self._clock = clock or time.monotonic
        self._enabled = enabled or recording_enabled
        self._max_body = max_body_bytes

    async def __call__(self, scope: dict, receive: Any, send: Callable[[dict], Awaitable[None]]) -> None:
        if scope.get("type") != "http" or not self._enabled():
            await self.app(scope, receive, send)
            return

        started = self._clock()
        status: int | None = None
        collected = bytearray()

        async def send_wrapper(message: dict) -> None:
            nonlocal status
            kind = message.get("type")
            if kind == "http.response.start":
                status = message.get("status")
            elif kind == "http.response.body" and status is not None and status >= 400:
                chunk = message.get("body") or b""
                if chunk and len(collected) < self._max_body:
                    collected.extend(chunk[: self._max_body - len(collected)])
            await send(message)

        await self.app(scope, receive, send_wrapper)
        self._record_if_interesting(scope, status, started, bytes(collected))

    def _record_if_interesting(
        self,
        scope: dict,
        status: int | None,
        started: float,
        body: bytes,
    ) -> None:
        try:
            if status is None:
                return
            method = str(scope.get("method") or "").upper()
            path = str(scope.get("path") or "")
            template = getattr(scope.get("route"), "path", None)
            if template is None:
                if not path.startswith("/api/"):
                    return
                endpoint = "unmatched"
            else:
                if not str(template).startswith("/api/"):
                    return
                endpoint = str(template)
            if status < 400 and method not in MUTATING_METHODS:
                return
            params = scope.get("path_params") or {}
            world = params.get("mundo") if isinstance(params, dict) else None
            duration_ms = max(0, int(round((self._clock() - started) * 1000)))
            self._record(
                {
                    "run_id": f"op-{uuid.uuid4().hex[:12]}",
                    "method": method,
                    "endpoint": endpoint,
                    # Hashed here, never handed on raw: a custom recorder cannot
                    # leak the author's world name by accident (S6).
                    "world_hash": hash_world(world),
                    "status": status,
                    "duration_ms": duration_ms,
                    "error_code": _error_code(body) if status >= 400 else None,
                }
            )
        except Exception:  # noqa: BLE001 — observability never breaks a request
            return
