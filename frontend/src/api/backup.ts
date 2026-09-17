import { apiFetch } from "@/api/client";
import type {
  BackupCandidatesResponse,
  BackupDestinationInput,
  BackupRestoreInput,
  BackupRestorePreview,
  BackupRestoreResult,
  BackupRestoreStatus,
  BackupSnapshotList,
  BackupStatus,
} from "@/api/types";

const CREDENTIALS = { credentials: "same-origin" as const };
const BASE = "/api/backup";

/**
 * Typed client for the eight `/api/backup/*` routes (WU-15, REQ-BUI-1).
 *
 * Every route runs behind `require_principal` and fails CLOSED: an
 * unauthenticated call is a 401 before any state is read, like the sibling
 * routers. The client carries the same-origin session cookie and never builds
 * a request body the server did not ask for.
 *
 * Honest-copy contract (REQ-SF-4, REQ-BUI-3): the status payload is LOCAL-WRITE
 * ONLY. This module mirrors the backend's `FORBIDDEN_DELIVERY_VOCABULARY` and
 * exposes {@link findForbiddenVocabulary} / {@link assertHonestCopy} so a test
 * can assert no user-facing string claims cloud delivery.
 */

/** GET /api/backup/status — the honest card state. */
export function getBackupStatus(): Promise<BackupStatus> {
  return apiFetch<BackupStatus>(`${BASE}/status`, CREDENTIALS);
}

/** GET /api/backup/candidates — suggested folders; the picker is always offered. */
export function getBackupCandidates(): Promise<BackupCandidatesResponse> {
  return apiFetch<BackupCandidatesResponse>(`${BASE}/candidates`, CREDENTIALS);
}

/** POST /api/backup/destination — persist the chosen folder. */
export function setBackupDestination(path: string): Promise<BackupStatus> {
  const body: BackupDestinationInput = { path };
  return apiFetch<BackupStatus>(`${BASE}/destination`, {
    method: "POST",
    body: JSON.stringify(body),
    ...CREDENTIALS,
  });
}

/** POST /api/backup/run — one run now, into the chosen folder. */
export function runBackupNow(): Promise<BackupStatus> {
  return apiFetch<BackupStatus>(`${BASE}/run`, {
    method: "POST",
    ...CREDENTIALS,
    // A real run hashes, stages and publishes the whole tree.
    timeout: 300_000,
  });
}

/** GET /api/backup/snapshots — the snapshots actually present. */
export function getBackupSnapshots(): Promise<BackupSnapshotList> {
  return apiFetch<BackupSnapshotList>(`${BASE}/snapshots`, CREDENTIALS);
}

/** POST /api/backup/restore/preview — diff counts + blockers, nothing written. */
export function previewBackupRestore(snapshotId: string): Promise<BackupRestorePreview> {
  const body: BackupRestoreInput = { snapshot_id: snapshotId, confirm: false };
  return apiFetch<BackupRestorePreview>(`${BASE}/restore/preview`, {
    method: "POST",
    body: JSON.stringify(body),
    ...CREDENTIALS,
    timeout: 120_000,
  });
}

/** POST /api/backup/restore — whole-root restore; requires explicit confirmation. */
export function restoreBackup(snapshotId: string): Promise<BackupRestoreResult> {
  const body: BackupRestoreInput = { snapshot_id: snapshotId, confirm: true };
  return apiFetch<BackupRestoreResult>(`${BASE}/restore`, {
    method: "POST",
    body: JSON.stringify(body),
    ...CREDENTIALS,
    timeout: 600_000,
  });
}

/** GET /api/backup/restore/status — maintenance marker + last restore outcome. */
export function getBackupRestoreStatus(): Promise<BackupRestoreStatus> {
  return apiFetch<BackupRestoreStatus>(`${BASE}/restore/status`, CREDENTIALS);
}

/**
 * Delivery claims the system cannot verify, in es-ES and en. Mirrors the
 * backend's `FORBIDDEN_DELIVERY_VOCABULARY` (backup/sync_folder.py); the
 * backend's `uploaded to` is generalized to `uploaded` so a bare claim is
 * caught too. None of these may appear in a user-facing backup string.
 */
export const FORBIDDEN_DELIVERY_VOCABULARY: readonly string[] = [
  "respaldado en la nube",
  "respaldado en Drive",
  "sincronizado con la nube",
  "sincronizado en la nube",
  "subido a Drive",
  "backed up to the cloud",
  "backed up to Drive",
  "synced to the cloud",
  "synced to Drive",
  "uploaded",
  "en la nube",
];

/** Every forbidden delivery phrase present in *text* (case-insensitive). */
export function findForbiddenVocabulary(text: string): string[] {
  const lowered = text.toLocaleLowerCase();
  return FORBIDDEN_DELIVERY_VOCABULARY.filter((term) =>
    lowered.includes(term.toLocaleLowerCase()),
  );
}

/** Throw when *text* claims a delivery Demiurgos cannot verify. */
export function assertHonestCopy(text: string): void {
  const found = findForbiddenVocabulary(text);
  if (found.length > 0) {
    throw new Error("cloud-delivery vocabulary is forbidden: " + found.join(", "));
  }
}
