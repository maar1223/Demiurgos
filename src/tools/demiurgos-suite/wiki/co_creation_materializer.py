"""Deterministic server-side draft materialization for co-created skills.

At ``borrador_listo`` (Author-confirmed) the backend assembles the source
Markdown from the session's structured ``draft_payload`` through a fixed
server-side template — Hermes never generates source, which eliminates the
authority-claim risk in compiled source (REQ-CC-5 / REQ-CC-7). This module
calls ``create_draft`` + ``compile_draft`` only, and NEVER calls ``publish``:
publishing happens exclusively through explicit Author approval via the API
layer in a later slice.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from co_creation_attachments import move_staged
from co_creation_protocol import DerivedFrom
from convergence_injection import carrier_root_for, read_adjunto_bytes
from methodology_compiler import AttachmentEntry, MethodologyIssue, compile_methodology
from methodology_library import MethodologyLibrary


# Deterministic kernel template: fixed shape, plain-string substitution.
DEFAULT_SOURCE_TEMPLATE = """# {name}
{description}

## Propósito
{purpose}

## Alcance
{scope} {world_binding}

## Flujo principal
{main_flow}

## Ramas y reglas
{branches}
{rules}"""

_TEMPLATE_KEYS = (
    "name",
    "description",
    "purpose",
    "scope",
    "main_flow",
    "branches",
    "rules",
    "world_binding",
)

_SECTION_HEADERS = (
    "## Propósito",
    "## Alcance",
    "## Flujo principal",
    "## Ramas y reglas",
)


class AttachmentMaterializationError(Exception):
    """A staged-carrier failure at materialize time (missing/drifted bytes).

    The API maps this to a structured JSON error WITHOUT creating a draft and
    WITHOUT leaving a partial ``attachments/`` tree: a failed move is rolled
    back before this surfaces.
    """

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _coerce_bytes(value: object) -> int:
    """Lenient ``bytes`` coercion.

    A malformed value becomes 0 so the compiler — not an exception — owns the
    failure accounting (it flags ``bytes`` below 1 as an invalid value).
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _payload_adjuntos(payload: Mapping[str, Any]) -> tuple[AttachmentEntry, ...]:
    """Read the canvas ``adjuntos`` pins into typed entries (REQ-CC-25).

    Shape validation happens at the canvas boundary (``canvas_payload_issues``)
    and again in the compiler; this parser only normalizes mappings so the SAME
    pins flow through ``validate_payload`` and ``materialize``. Non-mapping
    entries are skipped and malformed fields coerce to empty values, so a bad
    payload surfaces compiler issues instead of raising here.
    """
    raw = payload.get("adjuntos")
    if not isinstance(raw, list):
        return ()
    entries: list[AttachmentEntry] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        entries.append(AttachmentEntry(
            path=str(item.get("path") or "").strip(),
            sha256=str(item.get("sha256") or "").strip(),
            bytes=_coerce_bytes(item.get("bytes")),
            nivel=str(item.get("nivel") or "").strip(),
        ))
    return tuple(entries)


def _validate_staged_pins(
    staging_dir: Path,
    entries: tuple[AttachmentEntry, ...],
) -> None:
    """Verify every staged file exists and matches its pin (D3).

    Fails closed with ``attachment_unavailable`` on an unsafe basename, a
    missing file, or a sha256/bytes mismatch — every check runs BEFORE the
    first byte is moved, so a rejection never leaves a partial tree.
    """
    for entry in entries:
        name = entry.path
        if (
            not name
            or name != os.path.basename(name)
            or "/" in name
            or "\\" in name
            or ".." in name
        ):
            raise AttachmentMaterializationError(
                422, "attachment_unavailable",
                f"The staged attachment {name!r} is invalid.",
            )
        staged = staging_dir / name
        try:
            if not staged.is_file():
                raise AttachmentMaterializationError(
                    422, "attachment_unavailable",
                    f"The staged attachment {name!r} is unavailable.",
                )
            data = staged.read_bytes()
        except AttachmentMaterializationError:
            raise
        except OSError:
            raise AttachmentMaterializationError(
                422, "attachment_unavailable",
                f"The staged attachment {name!r} is unavailable.",
            ) from None
        if hashlib.sha256(data).hexdigest() != entry.sha256 or len(data) != entry.bytes:
            raise AttachmentMaterializationError(
                422, "attachment_unavailable",
                f"The staged attachment {name!r} does not match its pin.",
            )


def _rollback_moved(moved: list[Path], dest_dir: Path) -> None:
    """Remove the files this call already moved and drop the skill dir when it
    was left empty. Pre-existing carrier files are never touched."""
    for path in moved:
        try:
            path.unlink()
        except OSError:
            pass
    try:
        if dest_dir.is_dir() and not any(dest_dir.iterdir()):
            dest_dir.rmdir()
    except OSError:
        pass


def _remove_staging_dir(staging_dir: Path) -> None:
    """Best-effort removal of the now-consumed session staging dir (AE-3)."""
    shutil.rmtree(staging_dir, ignore_errors=True)


def move_publish_pins(
    entries: tuple[AttachmentEntry, ...],
    *,
    skill_id: str,
    staging_dir: Path,
    attachments_root: Path,
    project_root: Path,
) -> list[Path]:
    """Materialize ONLY the canvas pins still pending at the carrier root (D4).

    A pin whose bytes already resolve at ``carrier_root_for(skill_id)`` is
    already published and is skipped, so a preserve-only publish mutates
    nothing. Guards run BEFORE any move: a seeded carrier refuses a pending pin
    with 422 ``attachment_seed_immutable`` (EP-6/D5); an existing destination
    with differing bytes is refused with 422 ``attachment_overwrite_refused``
    (EP-5). ``_validate_staged_pins`` then verifies and ``move_staged`` moves
    the pending bytes. Returns the moved paths so the caller can roll them back
    if a later ``update_draft`` fails; ``[]`` means nothing was mutated.
    """
    carrier_root = carrier_root_for(skill_id, project_root=project_root)
    pending = [
        entry for entry in entries
        if read_adjunto_bytes(carrier_root, entry) is None
    ]
    if not pending:
        return []
    seed_dir = Path(project_root) / "data" / "methodology" / "seeds" / skill_id
    if seed_dir.is_dir():
        raise AttachmentMaterializationError(
            422, "attachment_seed_immutable",
            f"The skill {skill_id!r} is a seeded skill; its exemplars cannot "
            "be replaced, only preserved.",
        )
    dest_dir = Path(attachments_root) / skill_id
    for entry in pending:
        dest = dest_dir / entry.path
        if not dest.is_file():
            continue
        try:
            existing = dest.read_bytes()
        except OSError:
            existing = None
        if existing is None or hashlib.sha256(existing).hexdigest() != entry.sha256:
            raise AttachmentMaterializationError(
                422, "attachment_overwrite_refused",
                f"The attachment {entry.path!r} already exists with different bytes.",
            )
    staging = Path(staging_dir)
    _validate_staged_pins(staging, tuple(pending))
    moved: list[Path] = []
    try:
        moved = move_staged(staging, Path(attachments_root), skill_id, tuple(pending))
    except Exception:
        _rollback_moved(moved, dest_dir)
        raise
    return moved


def parse_rendered_source(source: str) -> dict[str, Any]:
    """Best-effort reverse of ``render_source`` (TW13 adaptation seed).

    Splits the deterministic template output back into structured payload
    keys so a published original can seed an adaptation session's canvas
    (REQ-CC-17/REQ-CC-18). Only keys it can identify are returned and it
    NEVER raises: a source that does not match the template shape yields an
    empty mapping (the caller falls back to metadata-only seeding).

    Known lossiness: the template renders ``branches`` and ``rules`` as two
    adjacent bullet lists with no separator, so their combined bullets seed
    into ``branches`` only (``rules`` is left empty for the Author to
    classify in the canvas).
    """
    parsed: dict[str, Any] = {}
    if not isinstance(source, str) or not source.strip():
        return parsed
    lines = source.split("\n")
    headers: dict[str, int] = {}
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped in _SECTION_HEADERS and stripped not in headers:
            headers[stripped] = index
    first = lines[0].strip() if lines else ""
    if first.startswith("# "):
        parsed["name"] = first[2:]
    if "## Propósito" in headers:
        parsed["description"] = "\n".join(lines[1:headers["## Propósito"]]).strip()
    if "## Propósito" in headers and "## Alcance" in headers:
        parsed["purpose"] = "\n".join(
            lines[headers["## Propósito"] + 1:headers["## Alcance"]]
        ).strip()
    if "## Alcance" in headers and "## Flujo principal" in headers:
        scope_block = "\n".join(
            lines[headers["## Alcance"] + 1:headers["## Flujo principal"]]
        ).strip()
        world: str | None = None
        binding = ""
        marker = "(mundo: "
        if marker in scope_block:
            start = scope_block.rfind(marker)
            end = scope_block.find(")", start)
            if end != -1:
                world = scope_block[start + len(marker):end].strip() or None
                binding = scope_block[start:end + 1]
        if not binding and "(transversal)" in scope_block:
            binding = "(transversal)"
        parsed["scope"] = scope_block.replace(binding, "").strip() if binding else scope_block
        if world:
            parsed["world"] = world
    if "## Flujo principal" in headers and "## Ramas y reglas" in headers:
        parsed["main_flow"] = "\n".join(
            lines[headers["## Flujo principal"] + 1:headers["## Ramas y reglas"]]
        ).strip()
    if "## Ramas y reglas" in headers:
        tail = "\n".join(lines[headers["## Ramas y reglas"] + 1:]).strip()
        bullets = [
            line[2:].strip()
            for line in tail.split("\n")
            if line.startswith("- ")
        ]
        if bullets:
            parsed["branches"] = bullets
    return parsed


def _render_value(value: object) -> str:
    """Render one template value deterministically.

    Lists (``branches``/``rules`` in the TW12 canvas shape) render as a
    Markdown bullet join — deterministic by construction. Plain strings render
    verbatim (Fase 4 backward compatibility); ``None`` renders empty.
    """
    if isinstance(value, list):
        return "\n".join(f"- {item}" for item in value)
    return str(value) if value is not None else ""


@dataclass(frozen=True)
class MaterializationResult:
    draft_id: str
    issues: tuple[MethodologyIssue, ...]
    ok: bool

    @property
    def compile_issues(self) -> tuple[MethodologyIssue, ...]:
        """Alias used by the validation panel (REQ-CC-5)."""
        return self.issues


@dataclass(frozen=True)
class ValidateResult:
    """Pre-materialization validation: render + compile, NO draft created."""

    source: str
    issues: tuple[MethodologyIssue, ...]
    ok: bool

    @property
    def compile_issues(self) -> tuple[MethodologyIssue, ...]:
        """Alias used by the validation panel (REQ-CC-13)."""
        return self.issues


class CoCreationMaterializer:
    """Assemble a library draft from structured co-creation answers."""

    def __init__(
        self,
        library: MethodologyLibrary,
        template: str = DEFAULT_SOURCE_TEMPLATE,
    ) -> None:
        self._library = library
        self._template = template

    def render_source(self, payload: Mapping[str, Any]) -> str:
        """Render the deterministic source Markdown for a structured payload.

        Uses sequential plain-string substitution (never ``str.format``) so
        arbitrary author content containing braces or ``$`` cannot break or
        alter the template. Missing fields render as empty sections; list
        fields (``branches``/``rules``) render as a deterministic bullet join.
        """
        values = {key: _render_value(payload.get(key)) for key in _TEMPLATE_KEYS}
        world = payload.get("world")
        values["world_binding"] = f"(mundo: {world})" if world else "(transversal)"
        source = self._template
        for key in _TEMPLATE_KEYS:
            source = source.replace("{" + key + "}", values[key])
        return source.strip() + "\n"

    def validate_payload(self, payload: Mapping[str, Any]) -> ValidateResult:
        """Render + compile a payload WITHOUT creating a library draft.

        REQ-CC-5 / REQ-CC-7 / REQ-CC-12: canvas edits run through the SAME
        deterministic template and compiler as materialization, so validation
        and materialization can never disagree. The manifest is synthesized
        from the payload with the same defaults the materialize route applies;
        nothing is created and nothing is published here.
        """
        source = self.render_source(payload)
        manifest = {
            "skill_id": payload.get("skill_id") or "co-created-skill",
            "version": payload.get("version") or "0.1.0",
            "name": payload.get("name") or "Co-created skill",
            "description": payload.get("description") or "",
            "phases": list(payload.get("phases") or ()),
            "language": payload.get("language"),
            "taller": payload.get("taller"),
            "talleres_compatibles": list(payload.get("talleres_compatibles") or ()),
            "categoria_funcional": payload.get("categoria_funcional"),
            "etiquetas": list(payload.get("etiquetas") or ()),
            "adjuntos": [entry.as_dict() for entry in _payload_adjuntos(payload)],
        }
        compiled = compile_methodology(manifest, source)
        return ValidateResult(
            source=source,
            issues=tuple(compiled.issues),
            ok=compiled.ok,
        )

    def seed_payload(
        self,
        source: str,
        *,
        name: str,
        description: str,
        world: str | None = None,
        adjuntos: tuple[AttachmentEntry, ...] = (),
    ) -> dict[str, Any]:
        """Build the adaptation session's initial canvas payload (TW13).

        Seeded from a PUBLISHED original (REQ-CC-17/REQ-CC-18): structured
        sections are best-effort parsed from the rendered source
        (``parse_rendered_source``) and the published metadata is folded in.
        The session's ``world`` binding overrides any parsed binding.

        D2/DP-1: the parent's exemplar pins are seeded into the canvas so the
        derived "Ejemplares" section is visible and removable. The key is
        emitted ONLY when non-empty, keeping a zero-exemplar payload
        byte-identical to the pre-change seed (EP-1 no-regression).
        """
        payload = parse_rendered_source(source)
        payload["name"] = name
        payload["description"] = description
        payload["world"] = world
        if adjuntos:
            payload["adjuntos"] = [entry.as_dict() for entry in adjuntos]
        return payload

    def inject_derived_from(
        self,
        payload: Mapping[str, Any],
        skill_id: str,
        version: str,
    ) -> tuple[dict[str, Any], DerivedFrom]:
        """Server-inject TW14 provenance into a derived session (REQ-CC-20).

        The caller reads ``skill_id``/``version`` from the PUBLISHED record —
        the client NEVER supplies provenance. Any client-supplied
        ``derived_from`` in the payload is DROPPED (ignored) and replaced with
        the server identity. Returns ``(clean_payload, DerivedFrom)``: the
        clean payload never carries the provenance key (so it cannot leak into
        the canvas payload, manifest, or digest) and the ``DerivedFrom``
        marker is persisted on the session state (``derived_from_json``).
        """
        clean = {
            key: deepcopy(value)
            for key, value in payload.items()
            if key != "derived_from"
        }
        return clean, DerivedFrom(skill_id=skill_id, version=version)

    def materialize(
        self,
        payload: Mapping[str, Any],
        *,
        skill_id: str,
        version: str,
        name: str,
        description: str = "",
        taller: str | None = None,
        etiquetas: tuple[str, ...] = (),
        categoria_funcional: str | None = None,
        language: str | None = None,
        staging_dir: Path | None = None,
        attachments_root: Path | None = None,
    ) -> MaterializationResult:
        """Create the draft and surface compiler issues.

        Returns the ``draft_id`` plus ``CompileResult.issues`` so the
        validation panel can list each code+message (REQ-CC-5). The draft is
        stored but never published or activated here.

        When the payload pins exemplars (REQ-CC-25/AE-3), the staged bytes are
        validated against their pins and MOVED into
        ``attachments/{skill_id}/`` BEFORE ``create_draft`` (D3), so the draft
        never carries a pin whose bytes are absent. A failed move — or a
        ``create_draft`` failure after a successful move — rolls every moved
        file back, leaving no partial tree and no draft. The consumed staging
        dir is removed only after the draft exists.
        """
        source = self.render_source(payload)
        entries = _payload_adjuntos(payload)
        draft_kwargs = {
            "skill_id": skill_id, "version": version, "name": name,
            "source": source, "description": description, "taller": taller,
            "etiquetas": tuple(etiquetas),
            "categoria_funcional": categoria_funcional, "language": language,
        }
        if entries:
            if staging_dir is None or attachments_root is None:
                raise AttachmentMaterializationError(
                    422, "attachment_unavailable",
                    "Staged attachments require a staging and attachments root.",
                )
            staging = Path(staging_dir)
            dest_dir = Path(attachments_root) / skill_id
            _validate_staged_pins(staging, entries)
            moved = move_staged(staging, Path(attachments_root), skill_id, entries)
            try:
                draft_id = self._library.create_draft(**draft_kwargs, adjuntos=entries)
            except Exception:
                _rollback_moved(moved, dest_dir)
                raise
            _remove_staging_dir(staging)
        else:
            draft_id = self._library.create_draft(**draft_kwargs)
        compiled = self._library.compile_draft(draft_id)
        return MaterializationResult(
            draft_id=draft_id,
            issues=tuple(compiled.issues),
            ok=compiled.ok,
        )