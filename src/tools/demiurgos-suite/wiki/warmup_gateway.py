# ---------------------------------------------------------------------------
# Warm-up script for the Hermes Gateway + graph MCP stack.
#
# After the gateway starts, sends one trivial graph query so the first real
# user request never pays the cold-start cost (MCP tool call ~131s the
# first time after gateway boot). Run in the background after starting the
# gateway; harmless if the gateway is already warm.
# ---------------------------------------------------------------------------
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from data_root import resolve_data_root

GATEWAY_URL = "http://127.0.0.1:8642/v1/chat/completions"
SESSION_ID = "warmup-session"
MAX_WAIT = 240  # seconds to wait for the gateway to come up
WARMUP_TIMEOUT = 300  # seconds for the warm-up request itself


def _project_root() -> Path:
    """Data root, resolved through the resolver on every call (WU-2).

    The previous ``_HERE.parents[3]`` literal resolved to the same folder, but
    as an import-time constant it would have made this module unimportable
    without a configured data root.
    """
    return resolve_data_root()


def resolve_gateway_key() -> str:
    """Resolve the gateway API key: env var first, then project .env (gitignored)."""
    env_val = os.getenv("HERMES_GATEWAY_KEY", "").strip()
    if env_val:
        return env_val

    project_root = _project_root()
    env_file = project_root / ".env"
    if env_file.is_file():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("HERMES_GATEWAY_KEY="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val
        except OSError:
            pass
    return ""


def gateway_key() -> str:
    """Resolve the gateway key on demand — never while this module is imported.

    The ``.env`` fallback lives in the data root since WU-2, and resolving it at
    import time would make this module unimportable without a configured root.
    """
    return resolve_gateway_key()


def resolve_mundo() -> str:
    """Resolve the active world name (same logic as mcp_launcher)."""
    env_val = os.getenv("DEMIURGOS_WORLD", "").strip()
    if env_val:
        return env_val

    project_root = _project_root()

    env_file = project_root / ".env"
    if env_file.is_file():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("DEMIURGOS_WORLD="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val
        except OSError:
            pass

    mundos_dir = project_root / "mundos"
    if mundos_dir.is_dir():
        candidates = [
            d.name
            for d in sorted(mundos_dir.iterdir())
            if d.is_dir()
            and not d.name.startswith("_")
            and d.name.lower() not in ("ideas",)
        ]
        if candidates:
            return candidates[0]

    return ""


def wait_for_gateway() -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < MAX_WAIT:
        try:
            req = urllib.request.Request("http://127.0.0.1:8642/health")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(3)
    return False


def warm_up() -> None:
    if not wait_for_gateway():
        print("warmup: gateway not reachable after 240s, skipping", flush=True)
        return

    mundo = resolve_mundo()
    if not mundo:
        print("warmup: no world configured yet, skipping graph warm-up", flush=True)
        return

    payload = json.dumps({
        "model": "hermes-agent",
        "messages": [
            {
                "role": "user",
                "content": (
                    f"[Mundo: {mundo}]\n\n"
                    "Usa graph_status y responde SOLO el entity_count."
                ),
            }
        ],
    }).encode("utf-8")

    req = urllib.request.Request(
        GATEWAY_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {gateway_key()}",
            "X-Hermes-Session-Id": SESSION_ID,
        },
        method="POST",
    )

    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=WARMUP_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        elapsed = time.monotonic() - t0
        content = (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            if isinstance(body, dict)
            else ""
        )
        print(f"warmup: OK in {elapsed:.1f}s -> {content[:80]!r}", flush=True)
    except Exception as exc:
        print(f"warmup: FAILED after {time.monotonic() - t0:.1f}s: {exc}", flush=True)


if __name__ == "__main__":
    warm_up()
