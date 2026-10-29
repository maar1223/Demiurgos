import { apiFetch } from "@/api/client";
import type { OnboardingStatus } from "@/api/types";
import { API_BASE_URL } from "@/lib/constants";

/**
 * Content folder API (step 4).
 *
 * `GET /api/data-root` reports the folder the running app uses plus the facts a
 * picker needs; `POST /api/data-root` records a new one. A recorded change moves
 * no bytes and takes effect on the NEXT start, so the response carries
 * `restart_required` and the step must offer a restart instead of continuing.
 */

export interface ContentRootDisk {
  free_bytes: number | null;
  total_bytes: number | null;
  volume: string | null;
}

export interface ContentRootInfo {
  path: string | null;
  origin: "env" | "pointer" | "unconfigured";
  configured: boolean;
  recorded_path: string | null;
  pending_restart: boolean;
  pinned: boolean;
  usable: boolean;
  worlds: number;
  disk: ContentRootDisk;
  mode: "mirrored" | "streaming" | "unknown";
  warning: string | null;
  reason: string | null;
  restart_required?: boolean;
}

/** GET /api/data-root — the folder in use, its disk facts and its usability. */
export function getContentRoot(): Promise<ContentRootInfo> {
  return apiFetch<ContentRootInfo>(`${API_BASE_URL}/api/data-root`);
}

/** POST /api/data-root — record a new folder (takes effect on the next start). */
export function setContentRoot(path: string): Promise<ContentRootInfo> {
  return apiFetch<ContentRootInfo>(`${API_BASE_URL}/api/data-root`, {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

/** POST /api/onboarding/content-folder — mark the step done, nothing moves. */
export function commitContentFolderStep(): Promise<OnboardingStatus> {
  return apiFetch<OnboardingStatus>(
    `${API_BASE_URL}/api/onboarding/content-folder`,
    { method: "POST" },
  );
}

/** A move job, as `GET /api/data-root/move/{id}` reports it. */
export interface ContentMoveJob {
  id: string;
  state: "queued" | "copying" | "done" | "failed" | "cancelled";
  source: string;
  target: string;
  total_files: number;
  total_bytes: number;
  copied_files: number;
  copied_bytes: number;
  skipped: { name: string; reason: string }[];
  error: string | null;
  pointer_written: boolean;
  cancel_requested: boolean;
  started_at: string;
  finished_at: string | null;
}

/** The persisted record of the last move; it is what authorises the cleanup. */
export interface LastContentMove {
  schema_version: number;
  source: string;
  target: string;
  state: "done" | "failed" | "cancelled" | "cleaned";
  pointer_written: boolean;
  source_is_checkout?: boolean;
  source_exists?: boolean;
  finished_at: string;
}

/** POST /api/data-root/move-content — copy, verify and only then publish the new folder. */
export function startContentMove(
  target: string,
): Promise<{ job: ContentMoveJob }> {
  return apiFetch<{ job: ContentMoveJob }>(`${API_BASE_URL}/api/data-root/move-content`, {
    method: "POST",
    body: JSON.stringify({ target }),
  });
}

/** GET /api/data-root/move-content/{id} — state, counters and the failure reason. */
export function getContentMove(
  id: string,
): Promise<{ job: ContentMoveJob; last_move: LastContentMove | null }> {
  return apiFetch(`${API_BASE_URL}/api/data-root/move-content/${encodeURIComponent(id)}`);
}

/** POST /api/data-root/move-content/{id}/cancel — nothing is published if it stops. */
export function cancelContentMove(
  id: string,
): Promise<{ job: ContentMoveJob }> {
  return apiFetch(`${API_BASE_URL}/api/data-root/move-content/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
  });
}

/** GET /api/data-root/last-move — the record that gates the cleanup. */
export function getLastContentMove(): Promise<{ last_move: LastContentMove | null }> {
  return apiFetch(`${API_BASE_URL}/api/data-root/last-move`);
}

/** POST /api/data-root/cleanup — delete the old copy, typed back exactly. */
export function cleanupOldContent(
  confirm: string,
): Promise<{ removed: string; last_move: LastContentMove | null }> {
  return apiFetch(`${API_BASE_URL}/api/data-root/cleanup`, {
    method: "POST",
    body: JSON.stringify({ confirm }),
  });
}

/** A suggested destination: a mounted disk, home, Documents or a sibling. */
export interface ContentDestinationCandidate {
  path: string;
  free_bytes: number | null;
  is_empty: boolean;
  writable: boolean;
}

/** GET /api/data-root/candidates — clickable destinations for the picker. */
export function getContentDestinations(): Promise<{
  candidates: ContentDestinationCandidate[];
  picker: boolean;
  native_dialog: boolean;
}> {
  return apiFetch(`${API_BASE_URL}/api/data-root/candidates`);
}

/**
 * POST /api/data-root/pick-folder — the OS folder dialog, opened by the server.
 *
 * A browser cannot name a server folder; the server runs on the author's machine,
 * so it opens the dialog itself. `cancelled` is a normal answer, not an error.
 */
export function pickFolder(
  initial?: string | null,
): Promise<{ cancelled: boolean; path: string | null }> {
  return apiFetch(`${API_BASE_URL}/api/data-root/pick-folder`, {
    method: "POST",
    body: JSON.stringify({ initial: initial ?? null }),
    timeout: 300_000,
  });
}
