import { apiFetch } from "@/api/client";
import type { WorldTrashEntry } from "@/api/types";
import { API_BASE_URL } from "@/lib/constants";

/**
 * Builds a URL from path segments.
 * The base URL is empty when Vite proxies /api in dev via vite.config.ts.
 * Always prepends a leading `/` so the Vite proxy matches `/api/*`.
 */
function apiUrl(segments: string[]): string {
  const path = "/" + segments.map((s) => encodeURIComponent(s)).join("/");
  return `${API_BASE_URL}${path}`;
}

/**
 * DELETE /api/worlds/{name} — move a world to the recycle bin.
 *
 * Requires local-dev auth. The server refuses unless `confirmName` matches
 * the world name (case-insensitive), the world is not the active world, and
 * it is not the only remaining world. Resolves with the created trash entry.
 */
export async function deleteWorld(
  name: string,
  confirmName: string,
): Promise<WorldTrashEntry> {
  return apiFetch<WorldTrashEntry>(apiUrl(["api", "worlds", name]), {
    method: "DELETE",
    credentials: "same-origin",
    body: JSON.stringify({ confirm_name: confirmName }),
  });
}

/**
 * GET /api/worlds/trash — list trashed worlds, newest first.
 * `days_remaining` counts down to the 30-day automatic purge.
 */
export async function listTrash(): Promise<WorldTrashEntry[]> {
  return apiFetch<WorldTrashEntry[]>(apiUrl(["api", "worlds", "trash"]), {
    credentials: "same-origin",
  });
}

/**
 * POST /api/worlds/{name}/restore — move the most recent trash entry for a
 * world back to `mundos/{name}/`, making the world and its associated data
 * valid again. `newName` (optional) restores it under a DIFFERENT name — the
 * conflict-resolution path when an active world owns `name`.
 */
export async function restoreWorld(name: string, newName?: string): Promise<void> {
  await apiFetch(apiUrl(["api", "worlds", name, "restore"]), {
    method: "POST",
    credentials: "same-origin",
    body: JSON.stringify(
      newName ? { new_name: newName } : {},
    ),
  });
}

/**
 * POST /api/worlds/{name}/rename — rename an active world. Moves the world
 * folder, rewrites the idea-capture active world, and records an alias so old
 * URLs keep resolving.
 */
export async function renameWorld(name: string, newName: string): Promise<void> {
  await apiFetch(apiUrl(["api", "worlds", name, "rename"]), {
    method: "POST",
    credentials: "same-origin",
    body: JSON.stringify({ new_name: newName }),
  });
}

/**
 * GET /api/worlds/aliases — the rename-alias map `{old_name: new_name}`, so the
 * UI can redirect a URL for a renamed world instead of showing "not found".
 */
export async function getWorldAliases(): Promise<Record<string, string>> {
  return apiFetch<Record<string, string>>(apiUrl(["api", "worlds", "aliases"]), {
    credentials: "same-origin",
  });
}

/**
 * DELETE /api/worlds/trash/{name} — permanently purge a trash entry now
 * (no 30-day wait). The backend also cleans the world's associated data.
 */
export async function permanentDelete(name: string): Promise<void> {
  await apiFetch(apiUrl(["api", "worlds", "trash", name]), {
    method: "DELETE",
    credentials: "same-origin",
  });
}