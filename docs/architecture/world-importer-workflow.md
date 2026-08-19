# World Importer — Workflow & Configuration Reference

> Implementation/ops reference for the **world-importer** subsystem (feature-branch-chain slice 4). This document describes the implemented importer's workflow and its bounded-intake / image / merge / replacement configuration. It does **not** restate the product/architecture contract (see `docs/architecture/world-importer.md`); it documents how the implemented subsystem behaves and how to configure and operate it. IM8 (incremental/recurrent imports) and IM9 (restore) remain explicitly **out of scope**.

| Field | Value |
|---|---|
| Status | Implementation reference (slice 4 of the world-importer SDD) |
| Version | 1.0 |
| Date | 2026-08-18 |
| Language | English (technical) |
| Related | `docs/architecture/world-importer.md`, `docs/architecture/world-importer-ui.md`, `src/tools/demiurgos-suite/wiki/import_{models,intake,store,service,router,analysis}.py` |

---

## 1. Workflow overview

The importer is a server-owned, durable, authenticated FastAPI job service. It follows the gated lifecycle:

```
upload / source selection
        │  (create job → stream chunks → analyze)
        ▼
analyze ──────────► review ──────────► approve ──────────► execute ──► result
(read-only)        (diagnosis)         (digest + token)   (gated write)
```

| Step | Endpoint | Effect on the world |
|---|---|---|
| Create job / source selection | `POST /api/{mundo}/imports` | None (read-only) |
| Stream intake (folders / loose / ZIP) | `POST .../{id}/stream` | None (durable spool only) |
| Analyze | `POST .../{id}/analyze` | None (read-only diagnosis) |
| Review | `GET .../{id}/review` | None |
| Approve | `POST .../{id}/approve` | Enables execution (server-issued token + digest) |
| Execute | `POST .../{id}/execute` | **Writes** — only through the gated merge/gallery/reconcile path |
| Cancel / Resume / Rollback | `POST .../{id}/{cancel\|resume\|rollback}` | Cancel/resume none; rollback is state-level (see §6) |

No canon write occurs before an explicit, digest/token-bound approval. Every route requires a trusted principal and resolves the world through the canonical world authority.

---

## 2. Bounded intake configuration

These bounds are **importer-specific** and do **not** relax the generic media cap. They are enforced on the server-owned intake path only.

| Bound | Value | Where |
|---|---|---|
| Per-file limit | **500 MB** (`MAX_FILE_BYTES`) | `import_models.py` |
| Aggregate per-job limit | **5 GB**, including ZIP contents (`MAX_JOB_AGGREGATE_BYTES`) | `import_models.py` |
| ZIP max entries | 10,000 (`ZIP_MAX_ENTRIES`) | `import_intake.py` |
| ZIP max depth | 16 (`ZIP_MAX_DEPTH`) | `import_intake.py` |
| ZIP per-entry size | 500 MB (`ZIP_MAX_ENTRY_SIZE`) | `import_intake.py` |
| ZIP compression-ratio guard | 200:1 (`ZIP_MAX_RATIO`) | `import_intake.py` |

- **Sources**: recursively selected **folders**, **loose multi-file** batches, and optional **ZIPs**. Streaming is chunked (512 KiB base64 in the frontend client) into durable spool offsets with resumable, revalidated offsets — no whole-job buffering.
- **Path safety**: traversal, absolute/backslash paths, dot-segments, hidden segments, system folders (`_context`, `.history`, `.papelera`) and transversal folders (`relaciones`, `canon`, `conflictos`, `propuestas`) are rejected (fail closed) before any write.
- **ZIP-bomb defenses**: entry count, depth, per-entry size, and suspicious compression ratios are validated against the archive header manifest **before** extraction; anything suspicious is rejected with zero extraction.
- **Accounting**: compressed and uncompressed bytes are counted separately per ZIP entry and against the aggregate.
- **Fail-closed**: any unsafe source, oversized file/job, or ZIP bomb causes the intake to fail closed before any canon write.

> MIME/content-type filtering is not enforced by the importer: intake validates by **path safety, size bounds, and ZIP-bomb defenses**. Unsupported or non-OKF content is diagnosed read-only during analysis; only valid candidates become eligible.

---

## 3. Source proximity and contextual image placement

Analysis preserves the source's structure so placements never silently reorder, append wholesale, or detach.

- Each candidate carries provenance: `source_path`, `source_kind`, `source_hash`, `heading_path`, `source_sequence`, `chunk_id`, `nearby_text_anchor`, `image_anchor`, and `source_order`.
- **Image gallery association**: extracted images are registered as **first-class gallery assets** into `mundos/{mundo}/wiki/media/` (the existing media contract), so `useImages`, `ImagePicker`, `MarkdownImage`, and `getMediaUrl` keep working.
- **Current Markdown format**: the ficha references each image with the current relative Markdown path and an optional `#align-size` suffix (e.g. `img.png#left`). The suffix is display metadata; the underlying gallery file is the clean base path.
- **Source-proximity placement**: placement targets a semantically matching ficha/section using heading/section, source sequence, and nearby text/chunk anchors. **Ambiguity requires review** — it is never silently guessed.

---

## 4. Preservation-first merge

The recommended merge mode adds content without overwriting:

| Decision | Behavior |
|---|---|
| `add` | Missing target ficha is created, or missing contextual images/references are added to an existing ficha. Current prose is untouched. |
| `keep` | Incoming content equals current (modulo whitespace) — no-op. |
| `review` | Incoming modifies existing prose or placement is ambiguous — surfaced to the Author; **not** auto-applied. |

- Current fichas are authoritative; modified text is **preserved**.
- Source remains evidence; conflicts require review.
- Blind full-file replacement is **forbidden as the default**.

---

## 5. Automatic 30-day replacement backup

When an **explicit replacement** is authorized, the previous version is automatically snapshotted through the existing `.papelera`/history mechanism:

- Prior ficha bytes are written to `.papelera/{section}/{id12}/` with a `meta.json`, recoverable for **30 days** (`PAPELERA_RETENTION_DAYS`).
- Audit/provenance is **separate** and survives rollback (see §6).
- The existing list/restore/purge endpoints can recover the prior version within the retention window.

---

## 6. Rollback compensation scope (verify S2 resolution)

The verify phase flagged (S2): does `rollback` compensate at **state-only** or **file-level** scope? **Resolved:** compensation is **state-level only** — implemented and documented without inventing file-level revert behavior.

- `ImportService.rollback` transitions an `EXECUTING`/`COMPLETED` job to `ROLLED_BACK` and records an audit event. It does **not** physically revert ficha/gallery writes that already occurred.
- Rationale: automatic file-level revert is unsafe (it could destroy Author edits or other work that landed after the import). The safe, deterministic compensation is the durable **job state + audit trail**, which identifies exactly what was imported (item outcomes) for selective manual revert.
- **Recovery of prior versions** remains available through `.papelera` (30-day retention) for explicit replacements — never through an automatic file-level rollback.
- This is a documented decision, not a hidden behavior change. A future IM9 (restore) must define restore permissions, audit semantics, and file-level rollback separately.

---

## 7. Dependency-outage fail-closed behavior

Execution fails closed when a dependency (graph reconcile, gallery/media registration, or a storage/authorization/integrity fault) is unavailable:

- The affected candidate is recorded as `failed` (tracked item outcome).
- The job transitions to `FAILED` — it is **never** reported `COMPLETED` (no false success).
- The recorded error is **redacted to the exception type** (no raw exception message leaks).
- Any canon write that occurred before the outage remains tracked by the failed job — there is no **untracked** canon write.
- A legacy `lore-index.json` is never read or regenerated during a failed (or any) job.

---

## 8. Legacy `lore-index.json` retirement (IM6)

The legacy `lore-index.json` file artifact is **retired**:

- `sync_lore.persistence.write_lore_index` now raises `RetiredLegacyIndexError`; no caller silently regenerates the orphaned artifact. The CLI builds the in-memory index for reporting and best-effort Engram counts but never writes the file.
- The `engram_sync` `LoreIndexAdapter` and its registration are **removed**; no worker consumes `lore-index.json`.
- The importer's durable **job contract (jobs + provenance)** and the **canonical OKF graph** replace it. Analysis/dry-run surface results through the import-job contract.
- A pre-existing `lore-index.json` is **ignored and never regenerated** (proven by integration test).

---

## 9. Observability (opaque job ID)

- Each import job carries an **opaque token** that keys structured observability. The public REST surface (`model_dump_redacted`) **never** returns this token.
- `ImportJobStore.observability(opaque_token)` returns structured, **redacted** observability: job identity, state, bounds/accounting, timestamps, the event trail, item-outcome counts, and approval count — with **no** content previews, candidate internals, approval tokens, or digests.
- Operators correlate observability out-of-band by the opaque token; the frontend/API never exposes it.

---

## 10. Out of scope

- **IM8 — incremental/recurrent imports**: recurring identity, change detection, and conflict policy require a separate specification.
- **IM9 — restore**: restore permissions, audit semantics, and file-level rollback require a separate specification.
- Neither is implemented or approved here.
