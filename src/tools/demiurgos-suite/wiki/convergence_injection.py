"""Convergence specimen serving seam (④a, R9).

The convergence specimen is a pinned carrier Markdown file from the seed
directory, served ONLY when its bytes still match the SHA-256 pin recorded
at publish time. The seed directory is the byte authority (R8); the seam
re-verifies every serve (D10, no cache) and never truncates an over-budget
carrier — it skips instead (D6), so a drifted or oversized specimen can
never teach a broken format.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from contract_projection import _estimate_tokens
from methodology_compiler import AttachmentEntry

MAX_SPECIMEN_TOKENS = 3072
"""Token budget for one injected convergence specimen (R12; ④b consumes it)."""


def serve_adjunto(seed_dir: Path, pin: AttachmentEntry) -> str | None:
    """Return the pinned carrier bytes as text, or ``None`` on any failure.

    Guards, in order (D6/D8/D10): the resolved path must stay inside the
    seed directory (containment), the file must exist, its SHA-256 must
    equal the pin, and its estimated token count must fit the budget.
    Every failure is a silent skip; the carrier is never truncated.
    """
    root = Path(seed_dir).resolve()
    try:
        resolved = (root / pin.path).resolve()
    except (OSError, ValueError):
        return None
    if not resolved.is_relative_to(root) or not resolved.is_file():
        return None
    try:
        data = resolved.read_bytes()
    except OSError:
        return None
    if hashlib.sha256(data).hexdigest() != pin.sha256:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if _estimate_tokens(text) > MAX_SPECIMEN_TOKENS:
        return None
    return text