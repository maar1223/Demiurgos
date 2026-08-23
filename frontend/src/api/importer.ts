import { apiFetch } from "@/api/client";
import { ApiError } from "@/api/types";
import type {
  AnalyzeImportRequest,
  ImportAnalyzeResponse,
  ImportApprovalResponse,
  ImportCreateJobInput,
  ImportDecisionsRequest,
  ImportDecisionsResponse,
  ImportExecuteResponse,
  ImportJob,
  ImportJobResponse,
  ImportJobState,
  ImportReviewResponse,
  JobPage,
} from "@/api/types";

/**
 * World Importer — typed REST lifecycle client (world-importer slice 3 +
 * slice 2 enrichment opt-in).
 *
 * Mirrors the server-owned import-job contract in
 * `src/tools/demiurgos-suite/wiki/import_router.py`: create a job from a
 * source selection (folders/loose/ZIP), stream durable base64 chunks with
 * resumable offsets, analyze (fail-closed) — optionally opt into Hermes
 * advisory enrichment — review candidates with the immutable digest,
 * toggle per-suggestion decisions, approve groups (optionally bound to a
 * suggestion-IDs commitment), execute with the single-use token, and
 * cancel/resume/rollback. Every call requires the local session cookie
 * (same-origin fetch default).
 */

/** Client chunk size for streaming uploads (512 KiB binary per request). */
export const IMPORT_CHUNK_BYTES = 512 * 1024;

/** Server-enforced bounds mirrored for honest pre-flight UX. The server is
 *  the authority — these only prevent obviously oversized selections. */
export const IMPORT_MAX_FILE_BYTES = 500 * 1024 * 1024;
export const IMPORT_MAX_JOB_BYTES = 5 * 1024 * 1024 * 1024;

/** System/transversal folders never imported as content (W10/UI2). */
export const IMPORT_SYSTEM_DIRS = [
  "_context",
  ".history",
  ".papelera",
  "relaciones",
  "canon",
  "conflictos",
  "propuestas",
] as const;

function importsUrl(mundo: string, jobId?: string, suffix = ""): string {
  const segments = ["api", mundo, "imports"];
  if (jobId) segments.push(jobId);
  const path = "/" + segments.map((s) => encodeURIComponent(s)).join("/");
  return `${path}${suffix}`;
}

/** POST /api/{mundo}/imports — create a job from a source selection. */
export function createImportJob(
  mundo: string,
  input: ImportCreateJobInput,
): Promise<ImportJobResponse> {
  return apiFetch<ImportJobResponse>(importsUrl(mundo), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

/** POST /api/{mundo}/imports/{id}/stream — one durable chunk at `offset`. */
export function streamImportChunk(
  mundo: string,
  jobId: string,
  relative: string,
  offset: number,
  dataB64: string,
): Promise<{ job_id: string; offset: number }> {
  return apiFetch<{ job_id: string; offset: number }>(
    importsUrl(mundo, jobId, "/stream"),
    {
      method: "POST",
      body: JSON.stringify({ relative, offset, data_b64: dataB64 }),
      timeout: 60_000,
    },
  );
}

/**
 * POST /api/{mundo}/imports/{id}/analyze — read-only analysis → REVIEW.
 *
 * Pass ``enrich: true`` in the request body to opt into the optional Hermes
 * advisory enrichment (slice 2). Absent/``false`` preserves the legacy
 * deterministic flow — no Hermes call, no suggestions.
 *
 * The server performs the work synchronously and reports ``analyzing`` +
 * progress while it runs, so the client waits a generous bounded window
 * (30 min) for very large lore documents. If the request still times out or
 * the connection drops, the caller MUST poll ``getImportJob`` instead of
 * treating the job as failed (see ``waitForJobTerminal``).
 */
export function analyzeImportJob(
  mundo: string,
  jobId: string,
  options?: AnalyzeImportRequest,
): Promise<ImportAnalyzeResponse> {
  // Always send an explicit body so the server honors the flags; an absent
  // body would default EVERYTHING ON (enrich=true, vision=true). Sending the
  // full envelope keeps a text-only re-import (vision=false) faithful.
  const body = JSON.stringify({
    enrich: options?.enrich ?? true,
    vision: options?.vision ?? true,
  });
  return apiFetch<ImportAnalyzeResponse>(importsUrl(mundo, jobId, "/analyze"), {
    method: "POST",
    body,
    timeout: 30 * 60_000,
  });
}

/** A non-terminal, still-processing analysis state. */
function isProcessing(state: ImportJobState): boolean {
  return state === "pending" || state === "intaking" || state === "analyzing";
}

/**
 * Poll GET /api/{mundo}/imports/{id} until the job leaves the processing
 * states (``pending``/``intaking``/``analyzing``).
 *
 * Used after an analyze POST times out or loses connection so the live Web
 * App keeps monitoring a job the server is still working on, instead of
 * declaring a false server failure. ``onProgress`` receives each poll so the
 * UI can render the server-owned stage/percentage. Throws the last network
 * error only when polling itself fails; a terminal ``failed`` job returns
 * the job (the caller surfaces ``job.error``).
 */
export async function waitForJobTerminal(
  mundo: string,
  jobId: string,
  onProgress?: (job: ImportJob) => void,
  opts?: { intervalMs?: number; maxWaitMs?: number },
): Promise<ImportJob> {
  const intervalMs = opts?.intervalMs ?? 2_000;
  const maxWaitMs = opts?.maxWaitMs ?? 30 * 60_000;
  const deadline = Date.now() + maxWaitMs;
  let lastError: unknown = null;
  for (;;) {
    if (Date.now() >= deadline) {
      throw lastError ?? new ApiError(0, "El análisis sigue en curso en el servidor");
    }
    try {
      const { job } = await getImportJob(mundo, jobId);
      lastError = null;
      if (isProcessing(job.state)) {
        onProgress?.(job);
      } else {
        return job;
      }
    } catch (err) {
      // Transient polling failure: keep the deadline, keep waiting. Only the
      // deadline exhaustion surfaces an error.
      lastError = err;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

/** GET /api/{mundo}/imports/{id} — current job state. */
export function getImportJob(
  mundo: string,
  jobId: string,
): Promise<ImportJobResponse> {
  return apiFetch<ImportJobResponse>(importsUrl(mundo, jobId));
}

/**
 * GET /api/{mundo}/imports — list the caller's jobs in this world (newest
 * first). The server enforces principal scoping: foreign jobs are never
 * returned. ``cursor`` is opaque (echoed back from ``JobPage.next_cursor``);
 * clients MUST NOT parse or mutate it.
 */
export function listImportJobs(
  mundo: string,
  options?: { limit?: number; cursor?: string | null },
): Promise<JobPage> {
  const params = new URLSearchParams();
  if (options?.limit !== undefined) params.set("limit", String(options.limit));
  if (options?.cursor) params.set("cursor", options.cursor);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return apiFetch<JobPage>(importsUrl(mundo) + suffix);
}

/** GET /api/{mundo}/imports/{id}/review — candidates + immutable digest. */
export function getImportReview(
  mundo: string,
  jobId: string,
): Promise<ImportReviewResponse> {
  return apiFetch<ImportReviewResponse>(importsUrl(mundo, jobId, "/review"));
}

/**
 * POST /api/{mundo}/imports/{id}/approve — issue a digest-bound token.
 *
 * Pass ``suggestionIds`` to bind the approval to a specific set of approved
 * suggestion IDs (slice 2). Absent/empty preserves the legacy (no
 * enrichment) execute path; ``issue_approval`` rejects any suggestion ID
 * whose ``review_state`` is not ``approved`` or whose candidate's digest
 * changed (replay protection comes from the existing consumed flag).
 */
export function approveImportGroups(
  mundo: string,
  jobId: string,
  groupIds: string[],
  suggestionIds: string[] = [],
): Promise<ImportApprovalResponse> {
  const body: { group_ids: string[]; suggestion_ids?: string[] } = {
    group_ids: groupIds,
  };
  if (suggestionIds.length > 0) {
    body.suggestion_ids = suggestionIds;
  }
  return apiFetch<ImportApprovalResponse>(importsUrl(mundo, jobId, "/approve"), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/**
 * POST /api/{mundo}/imports/{id}/execute — gated writes with token+digest.
 *
 * Pass ``suggestionIds`` so the executor applies the approved suggestions
 * (type/tags patch + deduplicated ``[[target]]`` entries) before the
 * existing canon write. Absent/empty preserves the legacy deterministic
 * execute path.
 */
export function executeImport(
  mundo: string,
  jobId: string,
  digest: string,
  token: string,
  suggestionIds: string[] = [],
): Promise<ImportExecuteResponse> {
  const body: { digest: string; token: string; suggestion_ids?: string[] } = {
    digest,
    token,
  };
  if (suggestionIds.length > 0) {
    body.suggestion_ids = suggestionIds;
  }
  return apiFetch<ImportExecuteResponse>(importsUrl(mundo, jobId, "/execute"), {
    method: "POST",
    body: JSON.stringify(body),
    timeout: 120_000,
  });
}

/**
 * POST /api/{mundo}/imports/{id}/review/decisions — toggle review_state on
 * one or more suggestions (slice 2). Each decision updates the JSON list on
 * its candidate. A missing candidate or unknown suggestion_id is silently
 * skipped (idempotent round-trip across retries); the response reports the
 * count of accepted decisions for observability. The deterministic digest
 * is NOT recomputed because review is read-only until execute.
 */
export function postReviewDecisions(
  mundo: string,
  jobId: string,
  decisions: ImportDecisionsRequest["decisions"],
): Promise<ImportDecisionsResponse> {
  return apiFetch<ImportDecisionsResponse>(
    importsUrl(mundo, jobId, "/review/decisions"),
    {
      method: "POST",
      body: JSON.stringify({ decisions }),
    },
  );
}

/** POST /api/{mundo}/imports/{id}/cancel — cancel at item boundaries. */
export function cancelImportJob(
  mundo: string,
  jobId: string,
): Promise<ImportJobResponse> {
  return apiFetch<ImportJobResponse>(importsUrl(mundo, jobId, "/cancel"), {
    method: "POST",
  });
}

/** POST /api/{mundo}/imports/{id}/resume — revalidate and resume. */
export function resumeImportJob(
  mundo: string,
  jobId: string,
): Promise<ImportJobResponse> {
  return apiFetch<ImportJobResponse>(importsUrl(mundo, jobId, "/resume"), {
    method: "POST",
  });
}

/** POST /api/{mundo}/imports/{id}/rollback — compensate importer changes. */
export function rollbackImportJob(
  mundo: string,
  jobId: string,
): Promise<ImportJobResponse> {
  return apiFetch<ImportJobResponse>(importsUrl(mundo, jobId, "/rollback"), {
    method: "POST",
  });
}

/**
 * DELETE /api/{mundo}/imports/{id} — manually delete a terminal job.
 *
 * Allowed server-side for ``completed`` / ``failed`` / ``rolled_back`` jobs
 * and an empty ``review`` (no candidates). A ``review`` with candidates is
 * never deletable — the review is pending approval.
 */
export function deleteImportJob(
  mundo: string,
  jobId: string,
): Promise<{ success: boolean }> {
  return apiFetch<{ success: boolean }>(importsUrl(mundo, jobId), {
    method: "DELETE",
  });
}

/** Encode an ArrayBuffer as base64 (used per 512 KiB chunk, no whole-job
 *  buffering — the server spool persists each chunk at its offset). */
export function bytesToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

/**
 * Stream one local File into a job in durable, resumable chunks.
 *
 * Chunks are sent sequentially at contiguous offsets; the server returns the
 * next offset (idempotent at the same offset for the same bytes, so a
 * re-stream after an interruption never duplicates data). Returns the final
 * offset (equals the file size). `onProgress` reports (streamed, total).
 */
export async function streamImportFile(
  mundo: string,
  jobId: string,
  file: File,
  relative: string,
  onProgress?: (streamed: number, total: number) => void,
): Promise<number> {
  const total = file.size;
  let offset = 0;
  while (offset < total) {
    const chunk = file.slice(offset, offset + IMPORT_CHUNK_BYTES);
    const buffer = await chunk.arrayBuffer();
    const result = await streamImportChunk(
      mundo,
      jobId,
      relative,
      offset,
      bytesToBase64(buffer),
    );
    offset = result.offset;
    onProgress?.(offset, total);
  }
  return offset;
}