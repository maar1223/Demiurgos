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

from convergence_injection import (  # noqa: E402
    MAX_SPECIMEN_TOKENS,
    build_specimen_block,
    read_adjunto_bytes,
    serve_adjunto,
)
from contract_projection import _CHARS_PER_TOKEN, _estimate_tokens  # noqa: E402
from methodology_compiler import AttachmentEntry  # noqa: E402

REPO_ROOT = _WIKI.parents[3]
SEED_ROOT = REPO_ROOT / "data" / "methodology" / "seeds"


def _pin(path: str, *, sha256: str | None = None, text: str | None = None, nivel: str = "1º"):
    """Build an AttachmentEntry whose sha256 matches ``text`` by default."""
    data = text.encode("utf-8") if text is not None else b"# Carrier\n\nContenido.\n"
    return AttachmentEntry(
        path=path,
        sha256=sha256 or hashlib.sha256(data).hexdigest(),
        bytes=len(data),
        nivel=nivel,
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

    def test_sha256_mismatch_skips(self, tmp_path: Path) -> None:
        """Threat guard: a pin whose sha256 is not the carrier digest skips.

        Structural malformation is unreachable here: ``AttachmentEntry`` is
        frozen and the pin is built from it, so only a digest mismatch is
        exercisable from this seam.
        """
        pin, data = _pin("ejemplos/ejemplo.md", sha256="0" * 64)
        (tmp_path / "ejemplos").mkdir()
        (tmp_path / "ejemplos" / "ejemplo.md").write_bytes(data)
        assert serve_adjunto(tmp_path, pin) is None


def _three_pins(tmp_path: Path):
    """Write the three nivel carriers and return their pins (R11 carriers)."""
    pins = []
    for path, nivel, text in (
        ("nivel-1.md", "1º", "# Principal\n\nContenido principal.\n"),
        ("nivel-2.md", "2º", "# Secundario\n\nContenido secundario.\n"),
        ("nivel-3.md", "3º", "# Relleno\n\nContenido de relleno.\n"),
    ):
        pin, data = _pin(path, text=text, nivel=nivel)
        (tmp_path / path).write_bytes(data)
        pins.append(pin)
    return tuple(pins)


class TestReadAdjuntoBytes:
    """D2 shared byte seam: raw pinned bytes guarded by containment, existence,
    and the SHA-256 pin — with NO decode and NO token budget (those stay in
    ``serve_adjunto``)."""

    def test_returns_pinned_bytes(self, tmp_path: Path) -> None:
        """The exact pinned bytes are returned verbatim."""
        pin, data = _pin("ejemplos/ejemplo.md", text="# Ejemplo\n\nContenido fiel.\n")
        (tmp_path / "ejemplos").mkdir()
        (tmp_path / "ejemplos" / "ejemplo.md").write_bytes(data)
        assert read_adjunto_bytes(tmp_path, pin) == data

    def test_missing_carrier_returns_none(self, tmp_path: Path) -> None:
        """Threat guard: an absent carrier file yields ``None``."""
        pin, _ = _pin("ejemplos/ausente.md")
        assert read_adjunto_bytes(tmp_path, pin) is None

    def test_drift_returns_none(self, tmp_path: Path) -> None:
        """Threat guard: bytes changed post-publish are never returned."""
        pin, _ = _pin("ejemplos/ejemplo.md")
        (tmp_path / "ejemplos").mkdir()
        (tmp_path / "ejemplos" / "ejemplo.md").write_bytes(b"# Drifted\n")
        assert read_adjunto_bytes(tmp_path, pin) is None

    def test_traversal_returns_none(self, tmp_path: Path) -> None:
        """Threat guard: ``../`` escaping the seed dir is contained away."""
        outside = tmp_path.parent / "outside.md"
        outside.write_text("# Fuera\n")
        pin, _ = _pin("../outside.md", text=outside.read_text())
        assert read_adjunto_bytes(tmp_path, pin) is None

    def test_ignores_token_budget(self, tmp_path: Path) -> None:
        """The byte seam never applies the text budget: an over-budget carrier
        is still returned; ``serve_adjunto`` is the layer that skips it."""
        over = "x" * (MAX_SPECIMEN_TOKENS * 4 + 1)
        pin, data = _pin("grande.md", text=over)
        (tmp_path / "grande.md").write_bytes(data)
        assert read_adjunto_bytes(tmp_path, pin) == data


class TestBuildSpecimenBlock:
    """R11/R12 (④b): ``build_specimen_block`` selects ≤1 nivel-matched pin per
    turn (scenario "one per turn"), falls back to the 1º principal exemplar
    (scenario "unknown nivel → 1º"), and returns the single D7 block format."""

    def test_nivel_matched_pin_serves_that_carrier(self, tmp_path: Path) -> None:
        """The block carries exactly the nivel-matched carrier bytes (verbatim,
        trailing newline included) with the D7 header and trailer."""
        pins = _three_pins(tmp_path)
        block = build_specimen_block(tmp_path, pins, "2º")
        assert block == (
            "[Convergence specimen — nivel 2º]\n\n"
            "# Secundario\n\nContenido secundario.\n\n"
        )

    def test_unknown_nivel_falls_back_to_principal_pin(self, tmp_path: Path) -> None:
        """Scenario "unknown nivel → 1º": no match → 1º principal carrier."""
        pins = _three_pins(tmp_path)
        block = build_specimen_block(tmp_path, pins, "4º")
        assert block is not None
        assert block.startswith("[Convergence specimen — nivel 1º]")
        assert "# Principal" in block and "Contenido secundario" not in block

    def test_one_block_per_turn(self, tmp_path: Path) -> None:
        """Scenario "one per turn": exactly one block per gate-passed turn."""
        pins = _three_pins(tmp_path)
        block = build_specimen_block(tmp_path, pins, "2º")
        assert block is not None
        assert block.count("[Convergence specimen — nivel ") == 1

    def test_header_carrier_and_trailer_format_single_site(self, tmp_path: Path) -> None:
        """D7: ``[Convergence specimen — nivel {label}]`` + blank line + the
        pinned carrier bytes verbatim + trailing newline — the only format
        site."""
        pin, data = _pin("carrier.md", text="# Contenido\n\nLínea dos.\n", nivel="3º")
        (tmp_path / "carrier.md").write_bytes(data)
        block = build_specimen_block(tmp_path, (pin,), "3º")
        assert block == "[Convergence specimen — nivel 3º]\n\n# Contenido\n\nLínea dos.\n\n"

    def test_over_budget_carrier_skips_block(self, tmp_path: Path) -> None:
        """Scenario "over-budget skip": an over-budget carrier never injects."""
        over = "x" * (MAX_SPECIMEN_TOKENS * 4 + 1)
        pin, data = _pin("grande.md", text=over, nivel="1º")
        (tmp_path / "grande.md").write_bytes(data)
        assert build_specimen_block(tmp_path, (pin,), "1º") is None

    def test_empty_adjuntos_returns_none(self, tmp_path: Path) -> None:
        """Zero-attachment skills never build a block."""
        assert build_specimen_block(tmp_path, (), "1º") is None

    def test_combined_bound_projection_cap_plus_korrane_block(self) -> None:
        """Scenario "combined bound": projection (≤1000-token cap) + the
        largest real carrier (Korrane = 1º) stay ≤ 4072 estimated tokens."""
        seed_dir = SEED_ROOT / "narrative-character-creation"
        carrier = (seed_dir / "adjunto-nivel-1-principal.md").read_bytes()
        pin = AttachmentEntry(
            path="adjunto-nivel-1-principal.md",
            sha256=hashlib.sha256(carrier).hexdigest(),
            bytes=len(carrier),
            nivel="1º",
        )
        block = build_specimen_block(seed_dir, (pin,), "1º")
        assert block is not None
        projection_at_cap = "x" * (1000 * _CHARS_PER_TOKEN)
        combined = _estimate_tokens(projection_at_cap) + _estimate_tokens(block)
        assert combined <= 4072