# -*- coding: utf-8 -*-
"""methodology-skill-renderer (WU 1.1) — pure deterministic SKILL.md rendering.

``skill_renderer`` is the pure, no-disk-write boundary that turns one published
methodology version plus its pinned attachments into the bytes of one native
Hermes skill folder. Covered scenarios (spec ``methodology-skill-renderer``):

- Deterministic render (byte-identical across calls; fs-order independent).
- Frontmatter carries name, description, and metadata (transversal/world).
- Description is hard-bounded to 57 characters (verbatim/overflow/too-long/
  missing).
- Trigger approval provenance is consumed (approved renders; a missing or
  mismatched approval is surfaced; foundational seeds are exempt).
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
from methodology_library import (
    PublishedVersion,
    TriggerApproval,
    normalize_trigger,
    normalized_trigger_digest,
)
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
    # Etapa 2 defense-in-depth (WU 2.4): default to a matching trigger approval
    # so the trigger provenance surface does not add issues to scenarios that
    # are not about the trigger. Tests pass ``trigger_approval`` explicitly
    # (including ``None``) to exercise the approved/missing/mismatched paths.
    if "trigger_approval" not in overrides:
        description = base["description"]
        base["trigger_approval"] = TriggerApproval(
            text=normalize_trigger(description),
            digest=normalized_trigger_digest(description),
            approved_by="author",
            approved_at="2026-01-01T00:00:00+00:00",
        )
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


# -- Trigger approval provenance (Etapa 2, TD-E) ------------------------------


def test_approved_description_renders_without_trigger_issue(tmp_path):
    """Spec 'Description within the render bound renders verbatim': a matching
    approval renders normally, with no trigger issue."""
    rendered = _transversal(_published(), tmp_path)
    assert rendered.issues == ()
    assert _frontmatter(rendered)["description"] == (
        "Craft a coherent story with the author"
    )


def test_missing_approval_on_non_seed_is_flagged_without_raising(tmp_path):
    """Spec 'Missing or unapproved trigger is surfaced, never silently
    rendered': a non-seed record without an approval is flagged
    ``trigger-unapproved`` and the render still succeeds."""
    rendered = _transversal(_published(trigger_approval=None), tmp_path)
    assert [issue.code for issue in rendered.issues] == ["trigger-unapproved"]
    assert rendered.issues[0].field == "description"
    # the bounded description is still rendered; the renderer never raises
    assert _frontmatter(rendered)["description"] == (
        "Craft a coherent story with the author"
    )
    assert rendered.skill_md


def test_foundational_seed_without_approval_is_exempt(tmp_path):
    """TD-E seed exemption: a grandfathered foundational record without an
    approval is not flagged (avoids noise on every transversal seed)."""
    rendered = _transversal(
        _published(trust_attributes=("fundacional",), trigger_approval=None),
        tmp_path,
    )
    assert rendered.issues == ()
    assert _frontmatter(rendered)["description"] == (
        "Craft a coherent story with the author"
    )


def test_mismatched_approval_is_flagged_but_still_renders(tmp_path):
    """Spec 'Missing or unapproved trigger is surfaced, never silently
    rendered': a present approval whose digest does not match the published
    description yields ``trigger-mismatch`` while the bounded description still
    renders (never raises, never >57)."""
    stale = TriggerApproval(
        text="stale trigger",
        digest=normalized_trigger_digest("stale trigger"),
        approved_by="author",
        approved_at="2026-01-01T00:00:00+00:00",
    )
    rendered = _transversal(_published(trigger_approval=stale), tmp_path)
    assert [issue.code for issue in rendered.issues] == ["trigger-mismatch"]
    assert rendered.issues[0].field == "description"
    description = _frontmatter(rendered)["description"]
    assert description == "Craft a coherent story with the author"
    assert len(description) <= DESCRIPTION_RENDER_LIMIT


def test_mismatched_approval_never_exceeds_render_bound(tmp_path):
    """The trigger delta never changes the ≤57 hard bound: an over-bound
    description with a stale approval is still bounded to ≤57."""
    stale = TriggerApproval(
        text="stale",
        digest=normalized_trigger_digest("stale"),
        approved_by="author",
        approved_at="2026-01-01T00:00:00+00:00",
    )
    rendered = _transversal(
        _published(description="g" * 200, trigger_approval=stale), tmp_path
    )
    assert [issue.code for issue in rendered.issues] == [
        "description-too-long",
        "trigger-mismatch",
    ]
    assert len(_frontmatter(rendered)["description"]) <= DESCRIPTION_RENDER_LIMIT


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


def test_rendered_skill_md_carries_no_consent_or_session_seam(tmp_path):
    """D6 / REQ-GN-2 (3.3.1): the rendered ``SKILL.md`` is a pure method
    carrier.

    The bytes carry ONLY the method body plus the co-creation rules block; they
    contain no ``consent_token``, no ``_GUIDED_SESSIONS`` reference, and no
    mechanism to open/create a guided session. The consent gate, the one-shot
    token, and session creation stay 100% in ``api_server``; a native skill
    invocation can never open a session (``skill_manage`` is vetoed and the
    read-only ``skill`` tool only loads). The 57-char trigger bound
    (``DESCRIPTION_RENDER_LIMIT``) is asserted here as the other half of the
    design §6 verify-only contract (REQ-GN-1).
    """
    source = (
        "# Creación guiada de personajes\n\n"
        "Método de co-creación: se construye un personaje paso a paso "
        "haciendo una sola pregunta por turno, sin volcar información.\n"
    )
    rendered = _transversal(_published(source=source), tmp_path)
    text = rendered.skill_md.decode("utf-8")

    # The method body and the co-creation rules are the ONLY content blocks.
    assert source.rstrip() in text
    assert CO_CREATION_RULES_BLOCK in text

    # No consent/token/session seam in the rendered bytes (D6).
    for seam in (
        "consent_token",
        "consent token",
        "_GUIDED_SESSIONS",
        "guided_session_id",
        "create_session",
        "opens a session",
        "/guided-character/session",
    ):
        assert seam not in text
    assert "ct-" not in text

    # Trigger bound: the description consumed by the skills index never
    # exceeds the 57-char render limit (REQ-GN-1 scenario 2).
    description = _frontmatter(rendered)["description"]
    assert len(description) <= DESCRIPTION_RENDER_LIMIT


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
