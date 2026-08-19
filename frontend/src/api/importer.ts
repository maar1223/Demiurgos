import { apiFetch } from "@/api/client";
import type {
  ImportAnalyzeResponse,
  ImportApprovalResponse,
  ImportCreateJobInput,
  ImportExecuteResponse,
  ImportJobResponse,
  ImportReviewResponse,
  JobPage,
} from "@/api/types";

/**
 * World Importer — typed REST lifecycle client (world-importer slice 3).
 *
 * Mirrors the server-owned import-job contract in
 * `src/tools/demiurgos-suite/wiki/import_router.py`: create a job from a
 * source selection (folders/loose/ZIP), stream durable base64 chunks with
 * resumable offsets, analyze (fail-closed), review candidates with the
 * immutable digest, approve groups, execute with the single-use token, and
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

/** POST /api/{mundo}/imports/{id}/analyze — read-only analysis → REVIEW. */
export function analyzeImportJob(
  mundo: string,
  jobId: string,
): Promise<ImportAnalyzeResponse> {
  return apiFetch<ImportAnalyzeResponse>(importsUrl(mundo, jobId, "/analyze"), {
    method: "POST",
    timeout: 120_000,
  });
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

/** POST /api/{mundo}/imports/{id}/approve — issue a digest-bound token. */
export function approveImportGroups(
  mundo: string,
  jobId: string,
  groupIds: string[],
): Promise<ImportApprovalResponse> {
  return apiFetch<ImportApprovalResponse>(importsUrl(mundo, jobId, "/approve"), {
    method: "POST",
    body: JSON.stringify({ group_ids: groupIds }),
  });
}

/** POST /api/{mundo}/imports/{id}/execute — gated writes with token+digest. */
export function executeImport(
  mundo: string,
  jobId: string,
  digest: string,
  token: string,
): Promise<ImportExecuteResponse> {
  return apiFetch<ImportExecuteResponse>(importsUrl(mundo, jobId, "/execute"), {
    method: "POST",
    body: JSON.stringify({ digest, token }),
    timeout: 120_000,
  });
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