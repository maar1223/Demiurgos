# -*- coding: utf-8 -*-
"""Pure, deterministic methodology -> native Hermes ``SKILL.md`` renderer.

Etapa 1 (additive) turns one compiled/published methodology (``PublishedVersion``)
plus its pinned attachments into the bytes of ONE native Hermes skill folder:
a ``SKILL.md`` with frontmatter (``name``, ``description``, ``metadata``) and a
body (method source + an always-present co-creation rules block), plus any
verifiable attachments as sibling files.

This module is a PURE function boundary (design ``methodology-skill-renderer``):

- It never writes to disk and never mutates the library — it reads inputs and
  returns ``RenderedSkill`` bytes/entries.
- Given identical inputs it is byte-identical across calls: no wall clock, no
  environment, no process state, no filesystem iteration order.
- The rendered ``description`` is hard-bounded to
  ``DESCRIPTION_RENDER_LIMIT`` characters (the Hermes skills-index truncation
  bound, design doc §11 P1), with the authored intake bound at
  ``DESCRIPTION_INTAKE_LIMIT``; every breach surfaces a ``RenderIssue`` and
  never raises.
- Composition uses sequential plain-string substitution, so author content
  containing braces or ``$`` survives verbatim and can never be re-expanded as
  a placeholder (mirrors ``co_creation_materializer.render_source``).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

from convergence_injection import read_adjunto_bytes
from methodology_library import PublishedVersion, normalized_trigger_digest
from methodology_trust import FOUNDATIONAL
from world_authority import normalize_world_name

# The Hermes skills-index truncation bound (design doc §11 P1).
DESCRIPTION_RENDER_LIMIT = 57
# The authored intake bound: values above this are flagged as too long.
DESCRIPTION_INTAKE_LIMIT = 60

# The scope label that marks a transversal (always-active) skill.
TRANSVERSAL_SCOPE = "transversal"

# The single composition template. Placeholders are substituted sequentially
# as plain strings — never through reflective formatting — so braces/dollars in
# author content are always data, never placeholders.
SKILL_MD_TEMPLATE = "---\n{{FM}}---\n\n{{BODY}}"

# Product-authored co-creation rules (design #3644): the assistant co-creates
# with the author instead of dumping information. Fixed and deterministic; the
# body always carries this block, also when the method source is empty.
CO_CREATION_RULES_BLOCK = """## Reglas de co-creación (siempre vigentes)

Co-creas el mundo CON la persona autora; nunca le vuelcas información encima.

- Prefiere una sola pregunta enfocada por turno antes que un muro de opciones o exposición.
- Respeta el ancla 40/60: la persona autora decide el 60% del mundo; tú propones, no decides.
- Nunca reclames autoría del kernel del mundo ni pases por encima del canon de la persona autora: no tienes autoridad de kernel.
- Ante una idea ambigua, propón unas pocas alternativas concretas y deja que la persona autora elija.
- Falla abierto: fuera del alcance declarado de este método, devuelve el control a la persona autora en vez de improvisar canon.
"""

# Deterministic local slug for a world identity ``normalize_world_name`` cannot
# accept (NFC; keep ``[A-Za-z0-9._-]``, replace anything else with ``-``).
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True)
class RenderIssue:
    """A surfaced renderer problem.

    Codes: ``description-missing`` | ``description-overflow`` |
    ``description-too-long`` | ``trigger-unapproved`` | ``trigger-mismatch`` |
    ``attachment-unavailable`` | ``world-token-fallback``.
    """

    code: str
    message: str
    field: str


@dataclass(frozen=True)
class AttachmentOutput:
    """One verified attachment emitted as a sibling of the ``SKILL.md``."""

    path: str
    bytes: bytes


@dataclass(frozen=True)
class RenderedSkill:
    """The complete immutable render of one methodology version.

    ``directory_name`` is the namespaced folder; ``skill_name`` is the same
    stem without the ``@<version>`` suffix; ``skill_md`` is the exact
    ``SKILL.md`` byte content and ``skill_md_sha256`` its digest.
    """

    skill_id: str
    version: str
    scope: str
    directory_name: str
    skill_name: str
    skill_md: bytes
    attachments: tuple[AttachmentOutput, ...]
    issues: tuple[RenderIssue, ...]
    skill_md_sha256: str


def _slugify(raw: str) -> str:
    """Deterministic local slug used only when ``normalize_world_name`` fails."""
    normalized = unicodedata.normalize("NFC", raw)
    slug = _SLUG_RE.sub("-", normalized)
    return slug or "world"


def _resolve_world_token(raw: str | None) -> tuple[str, RenderIssue | None]:
    """Resolve a safe world token, surfacing a fallback issue when needed.

    Never raises. A value ``normalize_world_name`` accepts is used verbatim;
    otherwise a local deterministic slug is used and an issue is returned so
    the caller can surface it.
    """
    if isinstance(raw, str) and raw.strip():
        normalized = normalize_world_name(raw)
        if normalized is not None:
            return normalized, None
        return _slugify(raw), RenderIssue(
            code="world-token-fallback",
            message=(
                f"World name {raw!r} is not a safe token; "
                "a local deterministic slug was used instead."
            ),
            field="scope",
        )
    return "world", RenderIssue(
        code="world-token-fallback",
        message="No usable world token was provided; a local slug was used.",
        field="scope",
    )


def _bound_description(raw: str | None) -> tuple[str, tuple[RenderIssue, ...]]:
    """Normalize and hard-bound an authored description; never raise.

    Collapses whitespace with ``" ".join(raw.split())``. An empty/missing value
    yields the empty string plus a ``description-missing`` issue. A value within
    ``DESCRIPTION_RENDER_LIMIT`` is returned verbatim. A longer value is bounded
    to at most ``DESCRIPTION_RENDER_LIMIT`` chars as
    ``norm[:56].rstrip() + "…"`` and flagged ``description-overflow`` (58..60)
    or ``description-too-long`` (> 60). The result never exceeds the render
    bound under any input.
    """
    normalized = " ".join(raw.split()) if isinstance(raw, str) else ""
    if not normalized:
        return "", (
            RenderIssue(
                code="description-missing",
                message="A skill description trigger is required.",
                field="description",
            ),
        )
    if len(normalized) <= DESCRIPTION_RENDER_LIMIT:
        return normalized, ()
    bounded = normalized[: DESCRIPTION_RENDER_LIMIT - 1].rstrip() + "…"
    if len(normalized) <= DESCRIPTION_INTAKE_LIMIT:
        return bounded, (
            RenderIssue(
                code="description-overflow",
                message=(
                    f"Description is {len(normalized)} characters; it was "
                    f"bounded to {DESCRIPTION_RENDER_LIMIT} for the skills index."
                ),
                field="description",
            ),
        )
    return bounded, (
        RenderIssue(
            code="description-too-long",
            message=(
                f"Description is {len(normalized)} characters, above the "
                f"{DESCRIPTION_INTAKE_LIMIT}-character intake bound; it was "
                f"bounded to {DESCRIPTION_RENDER_LIMIT} for the skills index."
            ),
            field="description",
        ),
    )


def _render_attachments(
    carrier_root: Path, pins: tuple
) -> tuple[tuple[AttachmentOutput, ...], tuple[RenderIssue, ...]]:
    """Emit verified attachments sorted by ``(path, sha256)``; never re-encode.

    Pins are visited in ``path`` order so the outcome is independent of the
    caller's/filesystem's enumeration order. A pin whose bytes are missing or
    do not verify against its SHA-256 and recorded size is omitted and surfaced
    as ``attachment-unavailable``; the remaining pins are still emitted.
    """
    outputs: list[AttachmentOutput] = []
    issues: list[RenderIssue] = []
    for pin in sorted(pins, key=lambda entry: entry.path):
        data = read_adjunto_bytes(carrier_root, pin)
        if data is None or len(data) != pin.bytes:
            issues.append(
                RenderIssue(
                    code="attachment-unavailable",
                    message=(
                        f"Attachment {pin.path!r} could not be verified against "
                        "its pinned bytes and was omitted."
                    ),
                    field="adjuntos",
                )
            )
            continue
        outputs.append(AttachmentOutput(path=pin.path, bytes=data))
    outputs.sort(key=lambda entry: (entry.path, hashlib.sha256(entry.bytes).hexdigest()))
    return tuple(outputs), tuple(issues)


def _trigger_issues(published: PublishedVersion) -> tuple[RenderIssue, ...]:
    """Surface a missing or mismatched trigger approval; never raise (TD-E).

    The renderer consumes an approved description by construction: the approval
    echoed onto the immutable published record is compared against the
    normalized description digest. A matching approval yields no issue. A
    present approval whose digest does not match yields ``trigger-mismatch``. An
    absent approval yields ``trigger-unapproved`` **unless** the record is a
    grandfathered foundational seed (``fundacional`` in ``trust_attributes``),
    which is exempted to avoid flagging every transversal seed (D5/TD-E). In
    every case the bounded description is still rendered and the renderer never
    raises and never exceeds the 57-character render bound.
    """
    approval = published.trigger_approval
    if approval is not None:
        if approval.digest == normalized_trigger_digest(published.description):
            return ()
        return (
            RenderIssue(
                code="trigger-mismatch",
                message=(
                    "The recorded trigger approval does not match the published "
                    "description digest; the bounded description is still "
                    "rendered, but the trigger provenance is stale."
                ),
                field="description",
            ),
        )
    if FOUNDATIONAL in published.trust_attributes:
        return ()
    return (
        RenderIssue(
            code="trigger-unapproved",
            message=(
                "The published record carries no trigger approval; the bounded "
                "description is still rendered, but the trigger is unapproved."
            ),
            field="description",
        ),
    )


def render_skill(
    published: PublishedVersion,
    *,
    scope: str,
    world_token: str | None,
    carrier_root: Path,
) -> RenderedSkill:
    """Render one published methodology version into native skill bytes.

    Pure: identical ``published``/``scope``/``world_token``/``carrier_root``
    inputs always produce byte-identical ``SKILL.md`` bytes and the same ordered
    attachment list. ``scope`` is ``"transversal"`` or the active world name;
    ``world_token`` is the (optional) pre-resolved world token, resolved again
    here so an unsafe or absent value falls back to a deterministic slug and
    surfaces an issue.

    Defense-in-depth (Etapa 2, TD-E): the published record's ``trigger_approval``
    is consumed so an approved description renders normally and a
    missing/mismatched approval surfaces a ``trigger-unapproved`` /
    ``trigger-mismatch`` issue instead of a silent fallback. Foundational seeds
    without an approval are exempt. The renderer never raises either way.
    """
    skill_id = published.skill_id
    version = published.version

    if scope == TRANSVERSAL_SCOPE:
        directory_name = f"demiurgos-{skill_id}@{version}"
        skill_name = f"demiurgos-{skill_id}"
        world_issue: RenderIssue | None = None
    else:
        token, world_issue = _resolve_world_token(world_token or scope)
        directory_name = f"demiurgos-{token}-{skill_id}@{version}"
        skill_name = f"demiurgos-{token}-{skill_id}"

    description, description_issues = _bound_description(published.description)
    trigger_issues = _trigger_issues(published)

    frontmatter = {
        "name": skill_name,
        "description": description,
        "metadata": {"version": version, "scope": scope},
    }
    frontmatter_text = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=10**9,
    )

    body = published.source.rstrip() + "\n\n" + CO_CREATION_RULES_BLOCK
    skill_md = (
        SKILL_MD_TEMPLATE.replace("{{FM}}", frontmatter_text).replace("{{BODY}}", body)
    ).encode("utf-8")

    attachments, attachment_issues = _render_attachments(carrier_root, published.adjuntos)

    issues: tuple[RenderIssue, ...] = description_issues + trigger_issues
    if world_issue is not None:
        issues = issues + (world_issue,)
    issues = issues + attachment_issues

    return RenderedSkill(
        skill_id=skill_id,
        version=version,
        scope=scope,
        directory_name=directory_name,
        skill_name=skill_name,
        skill_md=skill_md,
        attachments=attachments,
        issues=issues,
        skill_md_sha256=hashlib.sha256(skill_md).hexdigest(),
    )
