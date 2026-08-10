"""Project plugin registration for native Demiurgos idea capture."""

from __future__ import annotations

import os
import sys
from pathlib import Path


_handler = None


def register(ctx) -> None:
    global _handler
    root = Path(os.environ.get("DEMIURGOS_ROOT", Path.cwd())).resolve()
    tools = root / "src" / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))

    from idea_capture.hermes_handler import IdeaCaptureHandler

    _handler = IdeaCaptureHandler(repo_root=root)
    ctx.register_gateway_handler("demiurgos-idea-capture", _handler.handle_message)
    ctx.register_gateway_interaction_handler(
        "telegram", "capture:", _handler.handle_interaction,
    )
