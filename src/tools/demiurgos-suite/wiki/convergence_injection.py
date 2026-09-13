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


def read_adjunto_bytes(seed_dir: Path, pin: AttachmentEntry) -> bytes | None:
    """Return the pinned carrier bytes, or ``None`` on any guard failure.

    Shared byte seam (D2): the resolved path must stay inside the seed
    directory (containment), the file must exist, and its SHA-256 must equal
    the pin. Decoding and the token budget are deliberately NOT applied here —
    ``serve_adjunto`` layers them for text injection, while the package export
    path consumes the raw bytes verbatim.
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
    return data


def serve_adjunto(seed_dir: Path, pin: AttachmentEntry) -> str | None:
    """Return the pinned carrier bytes as text, or ``None`` on any failure.

    Guards, in order (D6/D8/D10): ``read_adjunto_bytes`` enforces containment,
    existence, and the SHA-256 pin; this seam then requires valid UTF-8 and an
    estimated token count within the budget. Every failure is a silent skip;
    the carrier is never truncated.
    """
    data = read_adjunto_bytes(seed_dir, pin)
    if data is None:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if _estimate_tokens(text) > MAX_SPECIMEN_TOKENS:
        return None
    return text


def build_specimen_block(
    seed_dir: Path, adjuntos: tuple[AttachmentEntry, ...], nivel: str,
) -> str | None:
    """Build the final convergence specimen block for one turn (R11, D7).

    Selects at most one pin: the entry whose ``nivel`` matches the resolved
    candidate nivel, falling back to the ``1º`` principal exemplar when
    nothing matches (unknown nivel → 1º). With no pins, or when the selected
    carrier cannot be served (drift / missing / over-budget), returns ``None``
    so the turn proceeds without a specimen — never a drifted or cut block
    (D6). This is the single format site: the header, the carrier bytes, and
    the trailing newline are assembled only here.
    """
    if not adjuntos:
        return None
    matched = next((pin for pin in adjuntos if pin.nivel == nivel), None)
    if matched is None:
        matched = next((pin for pin in adjuntos if pin.nivel == "1º"), None)
    if matched is None:
        return None
    content = serve_adjunto(seed_dir, matched)
    if content is None:
        return None
    return f"[Convergence specimen — nivel {matched.nivel}]\n\n{content}\n"