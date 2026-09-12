"""RED/unit tests for the convergence specimen serving seam (④a, R9).

Covers the serve seam guards: pinned carrier bytes are served exactly when
the carrier's sha256 equals the pin (scenario "serve pinned bytes"); drifted
bytes, missing carriers, over-budget text, ``../`` traversal, and malformed
pins all skip silently (scenario "skip on drift" + threat guards, D6/D8/D10).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from convergence_injection import MAX_SPECIMEN_TOKENS, serve_adjunto  # noqa: E402
from methodology_compiler import AttachmentEntry  # noqa: E402


def _pin(path: str, *, sha256: str | None = None, text: str | None = None):
    """Build an AttachmentEntry whose sha256 matches ``text`` by default."""
    data = text.encode("utf-8") if text is not None else b"# Carrier\n\nContenido.\n"
    return AttachmentEntry(
        path=path,
        sha256=sha256 or hashlib.sha256(data).hexdigest(),
        bytes=len(data),
        nivel="1º",
    ), data


class TestServeAdjunto:
    """R9 seam: serve only pinned carrier bytes; silently skip every failure."""

    def test_serve_pinned_bytes(self, tmp_path: Path) -> None:
        """Scenario "serve pinned bytes": exactly those bytes are served."""
        pin, data = _pin("ejemplos/ejemplo.md", text="# Ejemplo\n\nContenido fiel.\n")
        (tmp_path / "ejemplos").mkdir()
        (tmp_path / "ejemplos" / "ejemplo.md").write_bytes(data)
        assert serve_adjunto(tmp_path, pin) == data.decode("utf-8")

    def test_skip_on_drift(self, tmp_path: Path) -> None:
        """Scenario "skip on drift": bytes changed post-publish are never served."""
        pin, _ = _pin("ejemplos/ejemplo.md")
        (tmp_path / "ejemplos").mkdir()
        (tmp_path / "ejemplos" / "ejemplo.md").write_bytes(b"# Drifted\n\nModificado.\n")
        assert serve_adjunto(tmp_path, pin) is None

    def test_missing_carrier_skips(self, tmp_path: Path) -> None:
        """Threat guard: absent carrier file is a silent skip."""
        pin, _ = _pin("ejemplos/ausente.md")
        assert serve_adjunto(tmp_path, pin) is None

    def test_over_budget_skips_never_truncates(self, tmp_path: Path) -> None:
        """Threat guard (D6): over-budget text is skipped, never truncated."""
        over = "x" * (MAX_SPECIMEN_TOKENS * 4 + 1)
        pin, data = _pin("grande.md", text=over)
        (tmp_path / "grande.md").write_bytes(data)
        assert serve_adjunto(tmp_path, pin) is None

    def test_traversal_is_containment_skipped(self, tmp_path: Path) -> None:
        """Threat guard (D8): ``../`` escaping the seed dir is a silent skip."""
        outside = tmp_path.parent / "outside.md"
        outside.write_text("# Fuera\n")
        pin, data = _pin("../outside.md", text=outside.read_text())
        assert serve_adjunto(tmp_path, pin) is None

    def test_malformed_pin_skips(self, tmp_path: Path) -> None:
        """Threat guard: a pin whose sha256 is not the carrier digest skips."""
        pin, data = _pin("ejemplos/ejemplo.md", sha256="0" * 64)
        (tmp_path / "ejemplos").mkdir()
        (tmp_path / "ejemplos" / "ejemplo.md").write_bytes(data)
        assert serve_adjunto(tmp_path, pin) is None