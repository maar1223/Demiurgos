# -*- coding: utf-8 -*-
"""Tests for server-side DOCX export (ficha-export-pdf-docx, backend slice).

Covers the pandoc conversion module (``docx_export.py``) and the two export
endpoints (``GET /api/{mundo}/export/docx`` and
``GET /api/ideas/{slug}/export/docx``).

pandoc is a system binary, not a pip dependency — it may not be installed on
the host, so every test stubs ``shutil.which`` and ``subprocess.run`` in the
``docx_export`` namespace and feeds the pipeline a minimal in-memory DOCX ZIP
(the same fixture strategy used by ``sync_lore/tests/test_docx_parser.py``:
no python-docx, no external files).
"""

from __future__ import annotations

import io
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _p in (str(_WIKI), str(_SUITE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import api_server  # noqa: E402
import docx_export  # noqa: E402
from ideas_bank import IdeasBank  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _minimal_docx_bytes() -> bytes:
    """Build a minimal valid DOCX ZIP in memory (OOXML parses as a zip).

    The member timestamp is pinned so the bytes are deterministic across
    calls — the fixture is also used as a default argument evaluated at
    import time, and a live timestamp would make two calls differ whenever
    they cross a second boundary.
    """
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body>'
        "<w:p><w:r><w:t>body</w:t></w:r></w:p>"
        "<w:sectPr/></w:body></w:document>"
    )
    buf = io.BytesIO()
    info = zipfile.ZipInfo("word/document.xml", date_time=(2020, 1, 1, 0, 0, 0))
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(info, document)
    return buf.getvalue()


class _FakeShutil:
    """Stand-in for ``docx_export.shutil`` controlling ``which`` results."""

    def __init__(self, pandoc_path: str | None) -> None:
        self._pandoc_path = pandoc_path

    def which(self, name: str) -> str | None:
        return self._pandoc_path


class _FakeSubprocess:
    """Stand-in for ``docx_export.subprocess`` exposing only ``run``."""

    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(self, run: Mock) -> None:
        self.run = run


def _stub_pandoc(
    monkeypatch: pytest.MonkeyPatch,
    stdout: bytes = _minimal_docx_bytes(),
) -> Mock:
    """Stub pandoc availability + invocation inside ``docx_export``.

    Returns the mocked ``subprocess.run`` so tests can assert the exact
    command vector and the markdown stdin pandoc received.
    """
    run = Mock(
        return_value=subprocess.CompletedProcess(
            ["pandoc"], 0, stdout=stdout, stderr=b""
        )
    )
    monkeypatch.setattr(docx_export, "shutil", _FakeShutil("/usr/bin/pandoc"))
    monkeypatch.setattr(docx_export, "subprocess", _FakeSubprocess(run))
    return run


def _pandoc_input(run: Mock) -> str:
    """The markdown stdin captured by the stubbed ``subprocess.run``."""
    return run.call_args.kwargs["input"].decode("utf-8")


def _pandoc_cmd(run: Mock) -> list[str]:
    return run.call_args.args[0]


# ---------------------------------------------------------------------------
# Conversion module — frontmatter stripping
# ---------------------------------------------------------------------------


def test_strip_frontmatter_removes_leading_block() -> None:
    content = "---\ntype: criatura\ntitle: Inicio\n---\n# Inicio\n"
    body = docx_export._strip_frontmatter(content)
    assert "type: criatura" not in body
    assert body == "# Inicio\n"


def test_strip_frontmatter_keeps_crlf_body_line() -> None:
    content = "---\r\ntype: criatura\r\n---\r\n# Inicio\r\n"
    assert docx_export._strip_frontmatter(content) == "# Inicio\r\n"


def test_strip_frontmatter_no_block_returns_content() -> None:
    content = "# Inicio\n\nsin frontmatter\n"
    assert docx_export._strip_frontmatter(content) == content


def test_strip_frontmatter_unclosed_block_treated_as_body() -> None:
    content = "---\ntype: criatura\n# Inicio\n"
    assert docx_export._strip_frontmatter(content) == content


# ---------------------------------------------------------------------------
# Conversion module — image suffix stripping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "src,expected",
    [
        ("media/foto.png#left", "media/foto.png"),
        ("media/foto.png#right", "media/foto.png"),
        ("media/foto.png#center", "media/foto.png"),
        ("media/foto.png#sm", "media/foto.png"),
        ("media/foto.png#lg", "media/foto.png"),
        ("media/foto.png#sm-lg", "media/foto.png"),
        ("media/foto.png#lg-sm", "media/foto.png"),
        ("media/foto.png", "media/foto.png"),
        ("media/foto.png#crop", "media/foto.png#crop"),  # unknown suffix kept
    ],
)
def test_strip_image_suffixes(src: str, expected: str) -> None:
    assert docx_export._strip_image_suffixes(src) == expected


# ---------------------------------------------------------------------------
# Conversion module — image resolution + placeholder + wikilinks
# ---------------------------------------------------------------------------


def test_convert_rewrites_resolvable_image_to_absolute_path(monkeypatch) -> None:
    run = _stub_pandoc(monkeypatch)
    resolved = Path("/abs/media/foto.png")

    def resolve(src: str) -> Path | None:
        assert src == "media/foto.png"  # suffix already stripped
        return resolved

    out = docx_export._convert_markdown_to_docx(
        "# T\n\n![foto](media/foto.png#left)\n",
        resolve_image=resolve,
    )
    assert out == _minimal_docx_bytes()
    assert "![foto](</abs/media/foto.png>)" in _pandoc_input(run)
    assert "#left" not in _pandoc_input(run)
    assert _pandoc_cmd(run) == ["pandoc", "-f", "gfm", "-t", "docx", "-o", "-"]


def test_convert_passes_resource_paths(monkeypatch) -> None:
    run = _stub_pandoc(monkeypatch)
    docx_export._convert_markdown_to_docx(
        "# T\n",
        resolve_image=lambda _src: None,
        resource_paths=[Path("/media/base")],
    )
    cmd = _pandoc_cmd(run)
    assert cmd[1:5] == ["-f", "gfm", "-t", "docx"]
    assert "--resource-path" in cmd
    assert cmd[cmd.index("--resource-path") + 1] == "/media/base"


def test_convert_unresolvable_image_uses_placeholder(monkeypatch) -> None:
    run = _stub_pandoc(monkeypatch)
    docx_export._convert_markdown_to_docx(
        "# T\n\n![alt](missing.png)\n",
        resolve_image=lambda _src: None,
    )
    assert "[imagen no disponible]" in _pandoc_input(run)
    assert "![alt]" not in _pandoc_input(run)


def test_convert_unresolvable_image_preserves_alt_text_never_leaks(monkeypatch) -> None:
    run = _stub_pandoc(monkeypatch)
    docx_export._convert_markdown_to_docx(
        "![foto](media/rota.png#center)\n",
        resolve_image=lambda _src: None,
    )
    # The whole image reference is replaced — the suffix cannot leak either.
    assert "[imagen no disponible]" in _pandoc_input(run)
    assert "#center" not in _pandoc_input(run)
    assert "media/rota.png" not in _pandoc_input(run)


def test_convert_degrades_wikilinks_and_wiki_urls(monkeypatch) -> None:
    run = _stub_pandoc(monkeypatch)
    docx_export._convert_markdown_to_docx(
        "[[Some Entity]] y wiki://some-entity y [texto](wiki://otra)\n",
        resolve_image=lambda _src: None,
    )
    text = _pandoc_input(run)
    assert "Some Entity" in text
    assert "some-entity" in text
    assert "texto" in text
    assert "[[" not in text
    assert "wiki://" not in text


def test_convert_missing_pandoc_raises_runtime_error(monkeypatch) -> None:
    monkeypatch.setattr(docx_export, "shutil", _FakeShutil(None))
    with pytest.raises(RuntimeError, match="pandoc not installed"):
        docx_export._convert_markdown_to_docx(
            "# T\n", resolve_image=lambda _src: None
        )


def test_convert_pandoc_failure_raises_runtime_error(monkeypatch) -> None:
    run = Mock(
        return_value=subprocess.CompletedProcess(
            ["pandoc"], 2, stdout=b"", stderr=b"boom"
        )
    )
    monkeypatch.setattr(docx_export, "shutil", _FakeShutil("/usr/bin/pandoc"))
    monkeypatch.setattr(docx_export, "subprocess", _FakeSubprocess(run))
    with pytest.raises(RuntimeError, match="boom"):
        docx_export._convert_markdown_to_docx(
            "# T\n", resolve_image=lambda _src: None
        )


def test_convert_pandoc_timeout_raises_runtime_error(monkeypatch) -> None:
    run = Mock(side_effect=subprocess.TimeoutExpired("pandoc", 30))
    monkeypatch.setattr(docx_export, "shutil", _FakeShutil("/usr/bin/pandoc"))
    monkeypatch.setattr(docx_export, "subprocess", _FakeSubprocess(run))
    with pytest.raises(RuntimeError, match="timed out"):
        docx_export._convert_markdown_to_docx(
            "# T\n", resolve_image=lambda _src: None
        )


# ---------------------------------------------------------------------------
# Endpoints — ficha export (GET /api/{mundo}/export/docx)
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with a temp mundos dir, a sample ficha and a media file."""
    mundos = tmp_path / "mundos"
    world = mundos / "test_mundo"
    (world / "lore").mkdir(parents=True)
    (world / "wiki" / "media").mkdir(parents=True)
    (world / "lore" / "00_inicio.md").write_text(
        "---\ntype: criatura\ntitle: Inicio\n---\n"
        "# Inicio\n\n![foto](media/foto.png#left)\n\n[[Entidad]] y wiki://otra-cosa\n",
        encoding="utf-8",
    )
    (world / "wiki" / "media" / "foto.png").write_bytes(
        b"\x89PNG\r\n\x1a\nfake"
    )
    monkeypatch.setattr(api_server, "MUNDOS_DIR", mundos)
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    with api_server._local_session_lock:
        api_server._local_sessions.clear()
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _assert_docx_response(response) -> None:
    assert response.status_code == 200
    assert (
        response.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert zipfile.is_zipfile(io.BytesIO(response.content))
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        assert "word/document.xml" in zf.namelist()


def test_export_ficha_docx_happy_path(client, monkeypatch) -> None:
    run = _stub_pandoc(monkeypatch)
    response = client.get(
        "/api/test_mundo/export/docx", params={"path": "lore/00_inicio.md"}
    )
    _assert_docx_response(response)
    assert 'filename="00_inicio.docx"' in response.headers["content-disposition"]
    markdown = _pandoc_input(run)
    # Frontmatter stripped — the pandoc input is body only.
    assert "type: criatura" not in markdown
    assert "# Inicio" in markdown
    # Image resolved to the absolute disk path; suffix stripped; wikilinks
    # degraded to plain text.
    resolved = api_server.MUNDOS_DIR / "test_mundo" / "wiki" / "media" / "foto.png"
    # Canonical markdown format is POSIX-separated on every platform.
    assert f"![foto](<{resolved.as_posix()}>)" in markdown
    assert "#left" not in markdown
    assert "[[Entidad]]" not in markdown
    assert "Entidad" in markdown
    assert "otra-cosa" in markdown
    assert "wiki://" not in markdown


def test_export_ficha_docx_unresolvable_image_placeholder(client, monkeypatch) -> None:
    run = _stub_pandoc(monkeypatch)
    (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "rota.md").write_text(
        "# Rota\n\n![alt](missing.png)\n", encoding="utf-8"
    )
    response = client.get(
        "/api/test_mundo/export/docx", params={"path": "lore/rota.md"}
    )
    assert response.status_code == 200
    assert "[imagen no disponible]" in _pandoc_input(run)
    assert "![alt]" not in _pandoc_input(run)


def test_export_ficha_docx_path_traversal_400(client) -> None:
    response = client.get(
        "/api/test_mundo/export/docx",
        params={"path": "lore/../wiki/media/foto.png"},
    )
    assert response.status_code == 400
    response = client.get(
        "/api/test_mundo/export/docx", params={"path": "../etc/passwd"}
    )
    assert response.status_code == 400


def test_export_ficha_docx_not_found_404(client) -> None:
    response = client.get(
        "/api/test_mundo/export/docx", params={"path": "lore/no-existe.md"}
    )
    assert response.status_code == 404


def test_export_ficha_docx_pandoc_missing_500(client, monkeypatch) -> None:
    monkeypatch.setattr(docx_export, "shutil", _FakeShutil(None))
    response = client.get(
        "/api/test_mundo/export/docx", params={"path": "lore/00_inicio.md"}
    )
    assert response.status_code == 500
    assert "pandoc" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Endpoints — idea export (GET /api/ideas/{slug}/export/docx)
# ---------------------------------------------------------------------------


@pytest.fixture()
def ideas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An ideas bank rooted at tmp_path, wired into api_server.IdeasBank."""
    bank = IdeasBank(ideas_root=tmp_path / "ideas", mundos_root=tmp_path / "mundos")
    monkeypatch.setattr(api_server, "IdeasBank", lambda: bank)
    return bank


def _authed_client(client: TestClient) -> TestClient:
    client.post("/api/auth/local-dev/session")
    return client


def test_export_idea_docx_happy_path(client, monkeypatch, ideas, tmp_path) -> None:
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "local-dev")
    ideas.create(slug="arquero", type="personaje", body="# Idea\n\n![idea image](/api/ideas/media/arquero.png)\n")
    media = tmp_path / "ideas" / "media"
    media.mkdir(parents=True)
    (media / "arquero.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    run = _stub_pandoc(monkeypatch)
    response = _authed_client(client).get("/api/ideas/arquero/export/docx")
    _assert_docx_response(response)
    assert 'filename="arquero.docx"' in response.headers["content-disposition"]
    markdown = _pandoc_input(run)
    assert "/api/ideas/media/arquero.png" not in markdown
    # Canonical markdown format is POSIX-separated on every platform.
    assert (tmp_path / "ideas" / "media" / "arquero.png").as_posix() in markdown


def test_export_idea_docx_requires_auth_401(client) -> None:
    response = client.get("/api/ideas/arquero/export/docx")
    assert response.status_code == 401


def test_export_idea_docx_not_found_404(client, monkeypatch, ideas) -> None:
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "local-dev")
    response = _authed_client(client).get("/api/ideas/desconocida/export/docx")
    assert response.status_code == 404