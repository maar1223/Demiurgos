"""Methodology compiler boundary — bounded runtime contract.

The compiler turns an author-authored methodology (a bounded manifest plus a
Markdown source) into an immutable ``CompiledMethodology`` runtime contract.
It is the *only* seam through which author methodology becomes runtime
content: unvalidated Markdown is never loaded directly.

Two classes of input are rejected:

- **Malformed manifests** — missing/invalid required fields, unknown fields,
  oversized source, or unparseable YAML.
- **Authority-claiming content** — any manifest field or source marker that
  attempts to take over kernel-owned concerns (authorization, permissions,
  allowlisted targets, minimums, phase safety, compatibility, persistence,
  approvals, gates, execution). Those fields remain server-owned; a
  methodology can never claim them.

The compiler is pure and read-only: it reads strings and returns a result,
and never writes to the filesystem, canon, or the runtime.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

import yaml

# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------

MAX_SKILL_ID_LEN = 64
MAX_VERSION_LEN = 32
MAX_NAME_LEN = 120
MAX_DESCRIPTION_LEN = 2_000
MAX_PHASES = 12
MAX_PHASE_LEN = 64
MAX_LANGUAGE_LEN = 16
MAX_SOURCE_CHARS = 200_000

# Inventory metadata (Taller de Herramientas, Fase 1): optional, bounded,
# and explicitly EXCLUDED from the digest canonical (metadata, not identity).
MAX_TALLER_LEN = 64
MAX_TALLERES_COMPATIBLES = 16
MAX_ETIQUETAS = 32
MAX_ETIQUETA_LEN = 64

# Attachment entries (contract §4, SR4): bounded, SHA-256-pinned metadata.
# Also excluded from the digest canonical — the per-attachment ``sha256`` IS
# the contract pin (locked decision D1, discovery #3173).
MAX_ADJUNTOS = 8
MAX_ADJUNTO_BYTES = 12_288
MAX_NIVEL_LEN = 64

# The single functional category a skill may claim (TW6). System-derived
# classification (Oficiales/Personalizadas/Comunitarias) is NOT claimable:
# ``clasificacion`` stays an unknown field and is rejected.
CATEGORIA_FUNCIONAL_ALLOWED = frozenset({
    "Creación", "Investigación", "Diseño", "Análisis", "Organización", "Visualización",
})

# The bounded manifest contract: only these keys may appear.
ALLOWED_MANIFEST_FIELDS = frozenset({
    "skill_id", "version", "name", "description", "phases", "language",
    "taller", "talleres_compatibles", "categoria_funcional", "etiquetas",
    "adjuntos",
})

# Kernel-owned fields a methodology must NEVER claim. Present in the manifest
# they produce an ``authority-claim``; the same marker set guards the source.
KERNEL_OWNED_FIELDS = frozenset({
    "authorization", "authorize", "authorizations",
    "permissions", "permission",
    "allowlisted_targets", "allowlist", "allowlisted",
    "minimums", "phase_safety", "compatibility", "persistence",
    "approval", "approvals", "gates", "kernel", "exec", "commands",
    "executables", "trust", "activate", "publish", "signature", "checksum",
    "self_authorize", "grant", "override",
})

# Source markers that claim authority. Kept as plain lowercase substrings so
# detection is deterministic and does not depend on a fragile parser.
AUTHORITY_CLAIM_MARKERS = (
    "kernel_authority",
    "#!demiurgos-authority",
    "allowlisted_targets",
    "authorization: granted",
    "permissions: all",
    "phase_safety: bypass",
    "grant_authority",
    "override_gates",
    "you are now authorized",
    "self_authorize",
)

_RE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


# ---------------------------------------------------------------------------
# Contract types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MethodologyIssue:
    """A surfaced compiler problem.

    Codes: ``malformed-manifest`` | ``missing-field`` | ``unknown-field`` |
    ``authority-claim`` | ``oversized`` | ``invalid-value``.
    """

    code: str
    message: str
    field: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "field": self.field}


@dataclass(frozen=True)
class AttachmentEntry:
    """One SHA-256-pinned attachment entry (contract §4, SR4).

    ``path`` is package-relative Markdown; ``sha256`` is the 64-hex digest
    over the attachment bytes; ``bytes`` is the declared size (<= 12288);
    ``nivel`` is a non-empty bounded narrative-density label.
    """

    path: str
    sha256: str
    bytes: int
    nivel: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "nivel": self.nivel,
        }


@dataclass(frozen=True)
class CompiledMethodology:
    """Immutable, validated runtime contract for one methodology."""

    skill_id: str
    version: str
    name: str
    description: str
    phases: tuple[str, ...]
    language: str | None
    source: str
    digest: str
    # Inventory metadata (Taller de Herramientas, Fase 1) — optional, and
    # deliberately excluded from the digest canonical: metadata, not identity.
    taller: str | None = None
    talleres_compatibles: tuple[str, ...] = ()
    categoria_funcional: str | None = None
    etiquetas: tuple[str, ...] = ()
    # Attachment entries (contract §4, SR4) — metadata only; also excluded
    # from the digest canonical (per-attachment sha256 IS the pin, D1).
    adjuntos: tuple[AttachmentEntry, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "phases": list(self.phases),
            "language": self.language,
            "source": self.source,
            "digest": self.digest,
            "taller": self.taller,
            "talleres_compatibles": list(self.talleres_compatibles),
            "categoria_funcional": self.categoria_funcional,
            "etiquetas": list(self.etiquetas),
            "adjuntos": [entry.as_dict() for entry in self.adjuntos],
        }


@dataclass(frozen=True)
class CompileResult:
    ok: bool
    issues: tuple[MethodologyIssue, ...]
    compiled: CompiledMethodology | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_manifest(text: str) -> dict | None:
    """Parse manifest YAML into a mapping, or None when malformed."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None


def compile_methodology(manifest: object, source: str) -> CompileResult:
    """Validate a manifest + Markdown source into a bounded runtime contract.

    Never raises: every failure mode is returned as a ``CompileResult`` with
    issues. Never writes anywhere. Authority-claiming manifest fields and
    source markers are rejected with an ``authority-claim`` issue.
    """
    issues: list[MethodologyIssue] = []

    if not isinstance(source, str):
        return CompileResult(False, (
            MethodologyIssue("malformed-manifest", "Source must be text.", "source"),
        ))
    if len(source) > MAX_SOURCE_CHARS:
        issues.append(MethodologyIssue(
            "oversized", f"Source exceeds {MAX_SOURCE_CHARS} characters.", "source",
        ))

    if not isinstance(manifest, Mapping):
        issues.append(MethodologyIssue(
            "malformed-manifest", "Manifest must be a mapping.", "manifest",
        ))
        return CompileResult(False, tuple(issues))

    _collect_manifest_issues(manifest, issues)
    _collect_source_authority_issues(source, issues)
    if issues:
        return CompileResult(False, tuple(issues))

    skill_id = str(manifest["skill_id"]).strip()
    version = str(manifest["version"]).strip()
    name = str(manifest["name"]).strip()
    description = str(manifest.get("description") or "").strip()
    raw_phases = manifest.get("phases") or []
    phases = tuple(str(p).strip() for p in raw_phases)
    language_raw = manifest.get("language")
    language = str(language_raw).strip() if language_raw is not None else None

    # Inventory metadata (optional; validation happened in the issue pass).
    taller_raw = manifest.get("taller")
    taller = str(taller_raw).strip() if taller_raw is not None else None
    talleres_compatibles = tuple(
        str(t).strip() for t in (manifest.get("talleres_compatibles") or [])
    )
    categoria_raw = manifest.get("categoria_funcional")
    categoria_funcional = (
        str(categoria_raw).strip() if categoria_raw is not None else None
    )
    etiquetas = tuple(
        str(e).strip() for e in (manifest.get("etiquetas") or [])
    )
    # Attachment entries (contract §4, SR4): validation happened in the issue
    # pass, so a clean result guarantees every entry is well-formed.
    raw_adjuntos = manifest.get("adjuntos")
    adjuntos = tuple(
        AttachmentEntry(
            path=str(entry["path"]).strip(),
            sha256=str(entry["sha256"]).strip(),
            bytes=int(entry["bytes"]),
            nivel=str(entry["nivel"]).strip(),
        )
        for entry in (raw_adjuntos or [])
    )

    # Digest canonical: STABLE. Inventory fields are metadata, not content
    # identity, so they must never change a digest. Attachment entries are
    # likewise excluded — the per-attachment sha256 IS the contract pin (D1).
    canonical = {
        "skill_id": skill_id,
        "version": version,
        "name": name,
        "description": description,
        "phases": list(phases),
        "language": language,
        "source": source,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    compiled = CompiledMethodology(
        skill_id=skill_id,
        version=version,
        name=name,
        description=description,
        phases=phases,
        language=language,
        source=source,
        digest=digest,
        taller=taller,
        talleres_compatibles=talleres_compatibles,
        categoria_funcional=categoria_funcional,
        etiquetas=etiquetas,
        adjuntos=adjuntos,
    )
    return CompileResult(True, (), compiled)


# ---------------------------------------------------------------------------
# Internal validation
# ---------------------------------------------------------------------------


def _collect_manifest_issues(manifest: Mapping, issues: list[MethodologyIssue]) -> None:
    unknown = set(manifest) - ALLOWED_MANIFEST_FIELDS
    claimed = set(manifest) & KERNEL_OWNED_FIELDS
    for field in sorted(claimed):
        issues.append(MethodologyIssue(
            "authority-claim",
            f"Field {field!r} is kernel-owned and cannot be claimed by a methodology.",
            field,
        ))
    for field in sorted(unknown - claimed):
        issues.append(MethodologyIssue(
            "unknown-field", f"Unknown manifest field {field!r}.", field,
        ))

    for field in ("skill_id", "version", "name"):
        value = manifest.get(field)
        if value is None or not isinstance(value, str) or not value.strip():
            issues.append(MethodologyIssue(
                "missing-field", f"Required field {field!r} is missing.", field,
            ))
            continue
        limit = {
            "skill_id": MAX_SKILL_ID_LEN,
            "version": MAX_VERSION_LEN,
            "name": MAX_NAME_LEN,
        }[field]
        if len(value) > limit:
            issues.append(MethodologyIssue(
                "oversized", f"Field {field!r} exceeds {limit} characters.", field,
            ))
        if field in {"skill_id", "version"} and not _RE_IDENTIFIER.match(value):
            issues.append(MethodologyIssue(
                "invalid-value",
                f"Field {field!r} must be a bounded identifier "
                "(letters, digits, dot, dash, underscore).",
                field,
            ))

    description = manifest.get("description")
    if description is not None and (not isinstance(description, str) or len(description) > MAX_DESCRIPTION_LEN):
        issues.append(MethodologyIssue(
            "invalid-value", "description must be text within bounds.", "description",
        ))

    language = manifest.get("language")
    if language is not None and (
        not isinstance(language, str) or not language.strip() or len(language) > MAX_LANGUAGE_LEN
    ):
        issues.append(MethodologyIssue(
            "invalid-value", "language must be a short text tag.", "language",
        ))

    phases = manifest.get("phases")
    if phases is not None:
        if not isinstance(phases, list) or not all(isinstance(p, str) for p in phases):
            issues.append(MethodologyIssue(
                "invalid-value", "phases must be a list of strings.", "phases",
            ))
        elif len(phases) > MAX_PHASES or any(len(p.strip()) > MAX_PHASE_LEN for p in phases):
            issues.append(MethodologyIssue(
                "invalid-value",
                f"phases exceeds {MAX_PHASES} entries or a phase exceeds {MAX_PHASE_LEN} characters.",
                "phases",
            ))

    # --- Inventory metadata (Taller de Herramientas, Fase 1) -------------
    taller = manifest.get("taller")
    if taller is not None and not isinstance(taller, str):
        issues.append(MethodologyIssue(
            "invalid-value", "taller must be a short text tag.", "taller",
        ))
    elif taller is not None and len(taller.strip()) > MAX_TALLER_LEN:
        issues.append(MethodologyIssue(
            "oversized", f"taller exceeds {MAX_TALLER_LEN} characters.", "taller",
        ))

    _collect_string_list_issues(
        manifest.get("talleres_compatibles"), "talleres_compatibles",
        MAX_TALLERES_COMPATIBLES, MAX_TALLER_LEN, issues,
    )

    categoria_funcional = manifest.get("categoria_funcional")
    if categoria_funcional is not None:
        if not isinstance(categoria_funcional, str):
            issues.append(MethodologyIssue(
                "invalid-value",
                "categoria_funcional must be one of "
                f"{sorted(CATEGORIA_FUNCIONAL_ALLOWED)}.",
                "categoria_funcional",
            ))
        elif categoria_funcional.strip() not in CATEGORIA_FUNCIONAL_ALLOWED:
            issues.append(MethodologyIssue(
                "invalid-value",
                "categoria_funcional must be one of "
                f"{sorted(CATEGORIA_FUNCIONAL_ALLOWED)}.",
                "categoria_funcional",
            ))

    _collect_string_list_issues(
        manifest.get("etiquetas"), "etiquetas",
        MAX_ETIQUETAS, MAX_ETIQUETA_LEN, issues,
    )

    _collect_adjuntos_issues(manifest.get("adjuntos"), issues)


def _collect_string_list_issues(
    value: object,
    field: str,
    max_items: int,
    max_item_len: int,
    issues: list[MethodologyIssue],
) -> None:
    """Validate an optional string-list manifest field (inventory metadata).

    Missing/None is valid (defaults to empty). Otherwise the value must be a
    list of non-empty strings within bounds; each stored item is stripped.
    """
    if value is None:
        return
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        issues.append(MethodologyIssue(
            "invalid-value", f"{field} must be a list of strings.", field,
        ))
        return
    if len(value) > max_items:
        issues.append(MethodologyIssue(
            "invalid-value", f"{field} exceeds {max_items} items.", field,
        ))
        return
    for item in value:
        stripped = item.strip()
        if not stripped:
            issues.append(MethodologyIssue(
                "invalid-value", f"{field} items must not be empty.", field,
            ))
        elif len(stripped) > max_item_len:
            issues.append(MethodologyIssue(
                "oversized",
                f"An item in {field} exceeds {max_item_len} characters.",
                field,
            ))


# Attachment entry keys (contract §4, SR4): exactly these four may appear.
_ATTACHMENT_ENTRY_FIELDS = frozenset({"path", "sha256", "bytes", "nivel"})

# Path prefixes that would contaminate the graph indexer: attachments never
# live under ``mundos/**`` or ``referencias/**`` (contract §4, D5/D6).
_RESERVED_ATTACHMENT_PREFIXES = ("mundos/", "referencias/")

_RE_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _collect_adjuntos_issues(value: object, issues: list[MethodologyIssue]) -> None:
    """Validate the optional ``adjuntos`` manifest field (contract §4, SR4).

    Missing/None is valid (defaults to empty). Otherwise the value must be a
    list of at most ``MAX_ADJUNTOS`` entry mappings carrying exactly
    ``path``/``sha256``/``bytes``/``nivel``; every violation surfaces as a
    house-style ``MethodologyIssue`` naming the ``adjuntos`` field, and the
    compiler never raises on bad manifests.
    """
    if value is None:
        return
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        issues.append(MethodologyIssue(
            "invalid-value", "adjuntos must be a list of entries.", "adjuntos",
        ))
        return
    if len(value) > MAX_ADJUNTOS:
        issues.append(MethodologyIssue(
            "invalid-value", f"adjuntos exceeds {MAX_ADJUNTOS} entries.", "adjuntos",
        ))
        return

    for entry in value:
        for key in sorted(set(entry) - _ATTACHMENT_ENTRY_FIELDS):
            issues.append(MethodologyIssue(
                "unknown-field", f"Unknown adjuntos entry key {key!r}.", "adjuntos",
            ))
        for key in sorted(_ATTACHMENT_ENTRY_FIELDS - set(entry)):
            issues.append(MethodologyIssue(
                "missing-field", f"adjuntos entry is missing {key!r}.", "adjuntos",
            ))

        path = entry.get("path")
        if not isinstance(path, str) or not path.strip():
            issues.append(MethodologyIssue(
                "invalid-value", "adjuntos path must be a package-relative .md path.",
                "adjuntos",
            ))
        elif (
            path.startswith("/")
            or not path.endswith(".md")
            or path.startswith(_RESERVED_ATTACHMENT_PREFIXES)
        ):
            issues.append(MethodologyIssue(
                "invalid-value",
                "adjuntos path must be a package-relative .md outside "
                "mundos/** and referencias/**.",
                "adjuntos",
            ))

        sha256 = entry.get("sha256")
        if not isinstance(sha256, str) or not _RE_SHA256.match(sha256):
            issues.append(MethodologyIssue(
                "invalid-value", "adjuntos sha256 must be a 64-hex digest.",
                "adjuntos",
            ))

        byte_count = entry.get("bytes")
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 1:
            issues.append(MethodologyIssue(
                "invalid-value", "adjuntos bytes must be a positive integer.",
                "adjuntos",
            ))
        elif byte_count > MAX_ADJUNTO_BYTES:
            issues.append(MethodologyIssue(
                "oversized",
                f"adjuntos entry exceeds {MAX_ADJUNTO_BYTES} bytes.",
                "adjuntos",
            ))

        nivel = entry.get("nivel")
        if not isinstance(nivel, str) or not nivel.strip():
            issues.append(MethodologyIssue(
                "invalid-value", "adjuntos nivel must be a non-empty label.",
                "adjuntos",
            ))
        elif len(nivel.strip()) > MAX_NIVEL_LEN:
            issues.append(MethodologyIssue(
                "oversized",
                f"adjuntos nivel exceeds {MAX_NIVEL_LEN} characters.",
                "adjuntos",
            ))


def _collect_source_authority_issues(source: str, issues: list[MethodologyIssue]) -> None:
    lowered = source.lower()
    for marker in AUTHORITY_CLAIM_MARKERS:
        if marker.lower() in lowered:
            issues.append(MethodologyIssue(
                "authority-claim",
                f"Source contains an authority-claiming marker ({marker!r}); "
                "kernel authority cannot be claimed by methodology content.",
                "source",
            ))
