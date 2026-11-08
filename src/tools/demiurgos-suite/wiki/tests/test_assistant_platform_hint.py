# -*- coding: utf-8 -*-
"""Boot reconcile for the assistant's ``api_server`` platform hint (S4).

The stock Hermes hint assumes a plain-text renderer and forbids markdown; the
Demiurgos chat renders GFM. The boot reconcile writes the replacement on the
dedicated profile so an existing install converges without reinstalling.
"""

from __future__ import annotations

import yaml


def test_boot_reconcile_writes_the_markdown_hint(tmp_path, monkeypatch):
    import api_server
    from hermes_profile_config import API_SERVER_PLATFORM_HINT

    config = tmp_path / "config.yaml"
    monkeypatch.setattr(api_server, "_dedicated_profile_config_path", lambda: config)

    assert api_server._sync_assistant_platform_hint() is True

    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert data["platform_hints"]["api_server"] == {
        "replace": API_SERVER_PLATFORM_HINT
    }


def test_boot_reconcile_is_idempotent(tmp_path, monkeypatch):
    import api_server

    config = tmp_path / "config.yaml"
    monkeypatch.setattr(api_server, "_dedicated_profile_config_path", lambda: config)

    assert api_server._sync_assistant_platform_hint() is True
    before = config.read_bytes()
    assert api_server._sync_assistant_platform_hint() is False
    assert config.read_bytes() == before


def test_boot_reconcile_never_raises_on_write_failure(tmp_path, monkeypatch):
    import api_server

    def _boom():
        raise RuntimeError("no profile")

    monkeypatch.setattr(api_server, "_dedicated_profile_config_path", _boom)

    assert api_server._sync_assistant_platform_hint() is False
