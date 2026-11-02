# -*- coding: utf-8 -*-
"""The release package must place the Windows launcher at the contract path.

AUD-03: the release assembled the payload with ``start-demiurgos.ps1`` at the
stage root, while the backend, the boot rollback, the installer's closing hint
and ``INSTALL_LAYOUT.md`` all use ``<current>\\scripts\\start-demiurgos.ps1``.
The installer contract fixtures already modelled the *correct* layout, so every
test stayed green while a real Windows install would fail closed.

This guard reads the packaging workflow and enforces the single invariant that
makes the layout unambiguous: every root-form ``start-demiurgos.ps1`` mention
is a copy *source*, and both cells copy it to the contract path.
"""

from __future__ import annotations

import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[4]
_RELEASE = _REPO_ROOT / ".github" / "workflows" / "release.yml"
_LAYOUT = _REPO_ROOT / "docs" / "architecture" / "INSTALL_LAYOUT.md"
_LAUNCHER = _REPO_ROOT / "start-demiurgos.ps1"

# A root-form mention: not preceded by a path separator (POSIX or Windows) or a
# dotted prefix, so `scripts/start-demiurgos.ps1` and
# `scripts\start-demiurgos.ps1` do not match.
_ROOT_FORM = re.compile(r"(?<![\w/.\-\\])start-demiurgos\.ps1")

# The only places a root-form mention is legitimate: the two copy sources.
_COPY_PREFIXES = (
    "cp ",
    "-LiteralPath '",
)


class TestReleasePayloadLayout:
    def test_the_launcher_source_exists_in_the_repo(self) -> None:
        assert _LAUNCHER.is_file()

    def test_both_cells_copy_the_launcher_to_the_contract_path(self) -> None:
        text = _RELEASE.read_text(encoding="utf-8")

        # POSIX packaging block.
        assert 'cp start-demiurgos.ps1 "$stage/scripts/start-demiurgos.ps1"' in text
        # Windows packaging block.
        assert (
            "$launcherDest = Join-Path $stage 'scripts/start-demiurgos.ps1'" in text
        )

    def test_no_root_form_mention_outside_a_copy_source(self) -> None:
        text = _RELEASE.read_text(encoding="utf-8")

        for match in _ROOT_FORM.finditer(text):
            prefix = text[max(0, match.start() - 32) : match.start()]
            assert prefix.endswith(_COPY_PREFIXES), (
                "root-form start-demiurgos.ps1 outside a copy source "
                f"(it would ship at <current>/, not <current>/scripts/): {prefix!r}"
            )

    def test_the_frozen_layout_document_agrees(self) -> None:
        layout = _LAYOUT.read_text(encoding="utf-8")

        assert r"<current>\scripts\start-demiurgos.ps1" in layout
