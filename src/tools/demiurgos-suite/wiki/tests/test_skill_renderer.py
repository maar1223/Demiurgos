# -*- coding: utf-8 -*-
"""methodology-skill-renderer (WU 1.1) — pure deterministic SKILL.md rendering.

``skill_renderer`` is the pure, no-disk-write boundary that turns one published
methodology version plus its pinned attachments into the bytes of one native
Hermes skill folder. Covered scenarios (spec ``methodology-skill-renderer``):

- Deterministic render (byte-identical across calls; fs-order independent).
- Frontmatter carries name, description, and metadata (transversal/world).
- Description is hard-bounded to 57 characters (verbatim/overflow/too-long/
  missing).
- Co-creation rules are always present in the body (non-empty and empty source).
- Attachments are emitted as sibling files (verified emitted, drifted omitted).
- Skill identity is namespaced.
- Template discipline is brace-safe.
"""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import pytest
import yaml

from methodology_compiler import AttachmentEntry
from methodology_library import PublishedVersion
from skill_renderer import (
    CO_CREATION_RULES_BLOCK,
    DESCRIPTION_INTAKE_LIMIT,
    DESCRIPTION_RENDER_LIMIT,
    SKILL_MD_TEMPLATE,
    AttachmentOutput,
    RenderIssue,
    RenderedSkill,
    render_skill,
)

_MODULE_PATH = Path(__file__).resolve().parents[1] / "skill_renderer.py"


def _published(**overrides) -> PublishedVersion:
    base = {
        "skill_id": "story-weaver",
        "version": "1.0.0",
        "name": "Story Weaver",
        "description": "Craft a coherent story with the author",
        "phases": ("discovery",),
        "language": None,
        "source": "# Story Weaver\n\nBody text.",
        "digest": "0" * 64,
        "published_at": "2026-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return PublishedVersion(**base)


def _pin(carrier_root: Path, rel_path: str, content: bytes, nivel: str = "1º") -> AttachmentEntry:
    target = carrier_root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return AttachmentEntry(
        path=rel_path,
        sha256=hashlib.sha256(content).hexdigest(),
        bytes=len(content),
        nivel=nivel,
    )


def _frontmatter(rendered: RenderedSkill) -> dict:
    text = rendered.skill_md.decode("utf-8")
    return yaml.safe_load(text.split("---", 2)[1])


def _transversal(published: PublishedVersion, carrier_root: Path) -> RenderedSkill:
    return render_skill(
        published,
        scope="transversal",
        world_token=None,
        carrier_root=carrier_root,
    )


# -- Shape / purity -----------------------------------------------------------


def test_dataclasses_are_frozen():
    """The contract dataclasses are frozen."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        RenderIssue(code="x", message="y", field="z").code = "other"
    with pytest.raises(dataclasses.FrozenInstanceError):
        AttachmentOutput(path="a", bytes=b"b").path = "c"


def test_identical_input_renders_byte_identical_output(tmp_path):
    """Spec 'Identical input renders byte-identical output'."""
    published = _published()
    first = _transversal(published, tmp_path)
    second = _transversal(published, tmp_path)
    assert first.skill_md == second.skill_md
    assert first.skill_md_sha256 == second.skill_md_sha256
    assert first.attachments == second.attachments


def test_render_order_is_filesystem_independent(tmp_path):
    """Spec 'Render order is filesystem-independent': pin input order does not
    change the normalized attachment list or the SKILL.md bytes."""
    pin_b = _pin(tmp_path, "b.md", b"bravo")
    pin_a = _pin(tmp_path, "a.md", b"alpha")
    rendered_forward = _transversal(_published(adjuntos=(pin_a, pin_b)), tmp_path)
    rendered_reverse = _transversal(_published(adjuntos=(pin_b, pin_a)), tmp_path)
    assert [a.path for a in rendered_forward.attachments] == ["a.md", "b.md"]
    assert [a.path for a in rendered_reverse.attachments] == ["a.md", "b.md"]
    assert rendered_forward.attachments == rendered_reverse.attachments
    assert rendered_forward.skill_md == rendered_reverse.skill_md


# -- Frontmatter --------------------------------------------------------------


def test_frontmatter_carries_name_description_and_metadata(tmp_path):
    """Spec 'Frontmatter carries name, description, and metadata'."""
    rendered = _transversal(_published(), tmp_path)
    frontmatter = _frontmatter(rendered)
    assert frontmatter["name"] == "demiurgos-story-weaver"
    assert frontmatter["description"] == "Craft a coherent story with the author"
    assert frontmatter["metadata"] == {"version": "1.0.0", "scope": "transversal"}
    # Stable key order: name, description, metadata.
    assert list(frontmatter) == ["name", "description", "metadata"]


def test_world_scope_renders_world_token_and_scope(tmp_path):
    """Spec 'World-specific method renders its world scope'."""
    rendered = render_skill(
        _published(),
        scope="Aldoria",
        world_token="Aldoria",
        carrier_root=tmp_path,
    )
    assert rendered.directory_name == "demiurgos-Aldoria-story-weaver@1.0.0"
    assert rendered.skill_name == "demiurgos-Aldoria-story-weaver"
    assert rendered.scope == "Aldoria"
    frontmatter = _frontmatter(rendered)
    assert frontmatter["name"] == "demiurgos-Aldoria-story-weaver"
    assert frontmatter["metadata"]["scope"] == "Aldoria"


# -- Description bound --------------------------------------------------------


def test_description_within_bound_renders_verbatim(tmp_path):
    """Spec 'Description within the render bound renders verbatim'."""
    exact = "d" * DESCRIPTION_RENDER_LIMIT
    rendered = _transversal(_published(description=exact), tmp_path)
    assert _frontmatter(rendered)["description"] == exact
    assert rendered.issues == ()


def test_description_between_58_and_60_is_bounded_and_flagged(tmp_path):
    """Spec 'Description between 58 and 60 characters is bounded and flagged'."""
    authored = "e" * DESCRIPTION_INTAKE_LIMIT
    rendered = _transversal(_published(description=authored), tmp_path)
    bounded = _frontmatter(rendered)["description"]
    assert len(bounded) <= DESCRIPTION_RENDER_LIMIT
    assert bounded == "e" * (DESCRIPTION_RENDER_LIMIT - 1) + "…"
    assert [issue.code for issue in rendered.issues] == ["description-overflow"]


def test_description_over_intake_bound_is_bounded_and_flagged(tmp_path):
    """Spec 'Description over the intake bound is bounded and flagged'."""
    rendered = _transversal(_published(description="f" * 200), tmp_path)
    bounded = _frontmatter(rendered)["description"]
    assert len(bounded) <= DESCRIPTION_RENDER_LIMIT
    assert [issue.code for issue in rendered.issues] == ["description-too-long"]


def test_empty_description_is_flagged_without_raising(tmp_path):
    """Spec 'Empty description is an issue': the renderer never raises."""
    rendered = _transversal(_published(description="   "), tmp_path)
    assert _frontmatter(rendered)["description"] == ""
    assert [issue.code for issue in rendered.issues] == ["description-missing"]


# -- Co-creation rules block --------------------------------------------------


def test_co_creation_block_present_with_non_empty_source(tmp_path):
    """Spec 'Rules block present with a non-empty method'."""
    rendered = _transversal(_published(source="# Method\n\nGuidance."), tmp_path)
    text = rendered.skill_md.decode("utf-8")
    assert "# Method" in text
    assert CO_CREATION_RULES_BLOCK in text


def test_co_creation_block_present_with_empty_source(tmp_path):
    """Spec 'Rules block present with an empty method': the renderer does not
    raise and the block is still present."""
    rendered = _transversal(_published(source=""), tmp_path)
    text = rendered.skill_md.decode("utf-8")
    assert CO_CREATION_RULES_BLOCK in text


# -- Attachments --------------------------------------------------------------


def test_verifiable_pins_are_emitted_as_siblings(tmp_path):
    """Spec 'Verifiable pins are emitted as sibling files'."""
    pin = _pin(tmp_path, "examples/sample.md", b"# Sample\n")
    rendered = _transversal(_published(adjuntos=(pin,)), tmp_path)
    assert rendered.attachments == (AttachmentOutput(path="examples/sample.md", bytes=b"# Sample\n"),)
    assert rendered.issues == ()


def test_drifted_pin_is_omitted_and_flagged(tmp_path):
    """Spec 'Drifted pin is omitted and flagged': remaining pins still emit."""
    good = _pin(tmp_path, "good.md", b"good bytes")
    drifted = _pin(tmp_path, "drifted.md", b"original")
    # Corrupt the carrier file after pinning so its SHA-256 no longer matches.
    (tmp_path / "drifted.md").write_bytes(b"tampered")
    rendered = _transversal(_published(adjuntos=(good, drifted)), tmp_path)
    assert [a.path for a in rendered.attachments] == ["good.md"]
    codes = [issue.code for issue in rendered.issues]
    assert codes == ["attachment-unavailable"]
    assert rendered.issues[0].field == "adjuntos"


def test_attachment_size_mismatch_is_omitted(tmp_path):
    """A pin whose recorded size disagrees with the bytes is omitted."""
    pin = _pin(tmp_path, "a.md", b"alpha")
    oversized_pin = dataclasses.replace(pin, bytes=pin.bytes + 1)
    rendered = _transversal(_published(adjuntos=(oversized_pin,)), tmp_path)
    assert rendered.attachments == ()
    assert [issue.code for issue in rendered.issues] == ["attachment-unavailable"]


# -- Namespace ----------------------------------------------------------------


def test_namespaced_identity_never_reuses_bare_name(tmp_path):
    """Spec 'Rendered identity is namespaced': the bare external name is never
    reused; the folder/name are product-qualified."""
    rendered = _transversal(_published(skill_id="external-skill"), tmp_path)
    assert rendered.directory_name == "demiurgos-external-skill@1.0.0"
    assert rendered.skill_name == "demiurgos-external-skill"
    assert rendered.skill_name != "external-skill"
    assert rendered.directory_name.startswith("demiurgos-")


def test_unsafe_world_token_falls_back_to_slug_and_flags(tmp_path):
    """T4: an unsafe world identity falls back to a local slug + surfaced issue."""
    rendered = render_skill(
        _published(),
        scope="Nueva Aldoria",
        world_token=None,
        carrier_root=tmp_path,
    )
    assert rendered.directory_name == "demiurgos-Nueva-Aldoria-story-weaver@1.0.0"
    assert rendered.skill_name == "demiurgos-Nueva-Aldoria-story-weaver"
    assert [issue.code for issue in rendered.issues] == ["world-token-fallback"]


# -- Template discipline (brace safety) ---------------------------------------


def test_braces_and_dollar_signs_survive_verbatim(tmp_path):
    """Spec 'Braces and dollar signs in author content survive verbatim'."""
    source = "Uses {name}, {{ }}, and $HOME literally."
    description = "Keeps {name} and $HOME"
    rendered = _transversal(_published(source=source, description=description), tmp_path)
    text = rendered.skill_md.decode("utf-8")
    assert "{name}" in text
    assert "{{ }}" in text
    assert "$HOME" in text
    # No template placeholder is left unresolved or re-expanded.
    assert "{{FM}}" not in text
    assert "{{BODY}}" not in text
    assert _frontmatter(rendered)["description"] == "Keeps {name} and $HOME"


def test_module_uses_no_reflective_formatting():
    """The module composes with sequential plain-string substitution only: it
    must not use the reflective string formatting method or the Template
    substituter."""
    source = _MODULE_PATH.read_text(encoding="utf-8")
    assert "str.format" not in source
    assert "Template.substitute" not in source
    # The composition template is applied with plain .replace only.
    assert "{{FM}}" in SKILL_MD_TEMPLATE and "{{BODY}}" in SKILL_MD_TEMPLATE
