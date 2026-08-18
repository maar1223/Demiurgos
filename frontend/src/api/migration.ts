import { apiFetch } from "@/api/client";
import type { MigrationExecuteResult } from "@/api/types";

// ONB-4.3 (WU-4c2) — Legacy migration approval API. The backend owns the
// transactional engine: this module sends ONLY the explicit approval payload
// (world + the exact legacy folders) to the single authenticated endpoint.
// Nothing is ever planned or moved without an explicit user confirmation in
// the UI — this API is never called on panel mount or by any background
// refresh. The payload carries no secrets and the response is the evidence
// record (hashes are integrity digests, never displayed as a cosmetic table).

const CREDENTIALS = { credentials: "same-origin" as const };

/**
 * POST /api/migration/execute — run the explicitly approved migration for one
 * world. `folders` must be the exact legacy folder names detected by the
 * backend (e.g. `["Lore", "Personajes"]`); the server re-validates every
 * destination before moving anything and maps failures to machine-readable
 * error codes (ApiError.code: collision, empty_approval, unknown_folder,
 * invalid_world, symlink_escape, io_error; 401 when no local session).
 */
export function executeMigration(
  world: string,
  folders: string[],
): Promise<MigrationExecuteResult> {
  return apiFetch<MigrationExecuteResult>("/api/migration/execute", {
    method: "POST",
    body: JSON.stringify({ world, folders }),
    // Folder moves + content hashing can take longer than the default 5s.
    timeout: 60_000,
    ...CREDENTIALS,
  });
}
