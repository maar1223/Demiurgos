import { apiFetch } from "@/api/client";
import { ApiError } from "@/api/types";
import type {
  DiffPreview,
  DuplicateResponse,
  EmptyTrashResponse,
  FichaStatus,
  FileContent,
  FileNode,
  MediaList,
  MoveResponse,
  SuccessResponse,
  TrashEntry,
  TrashListResponse,
  UploadResponse,
  WorldInfo,
} from "@/api/types";
import { API_BASE_URL } from "@/lib/constants";

/**
 * Builds a URL from segments and query params.
 * The base URL is empty when Vite proxies /api in dev via vite.config.ts.
 * Always prepends a leading `/` so the Vite proxy matches `/api/*`.
 */
function apiUrl(
  segments: string[],
  params?: Record<string, string>,
): string {
  const path = "/" + segments
    .map((s) => encodeURIComponent(s))
    .join("/");
  const url = `${API_BASE_URL}${path}`;
  if (!params) return url;
  const qs = new URLSearchParams(params).toString();
  return `${url}?${qs}`;
}

// ---------------------------------------------------------------------------
// Worlds
// ---------------------------------------------------------------------------

/** GET /api/worlds — list all available worlds. */
export async function listWorlds(): Promise<WorldInfo[]> {
  return apiFetch<WorldInfo[]>(apiUrl(["api", "worlds"]));
}

// ---------------------------------------------------------------------------
// File Tree
// ---------------------------------------------------------------------------

/** GET /api/{mundo}/{section}/tree — recursive file tree. */
export async function getFileTree(
  mundo: string,
  section: string,
  opts?: { covers?: boolean },
): Promise<FileNode[]> {
  const params: Record<string, string> = {};
  if (opts?.covers) params.covers = "true";
  return apiFetch<FileNode[]>(
    apiUrl(["api", mundo, section, "tree"], params),
  );
}

// ---------------------------------------------------------------------------
// File Content
// ---------------------------------------------------------------------------

/** GET /api/{mundo}/{section}/file?path= — read file content. */
export async function getFileContent(
  mundo: string,
  section: string,
  path: string,
): Promise<FileContent> {
  return apiFetch<FileContent>(
    apiUrl(["api", mundo, section, "file"], { path }),
  );
}

// ---------------------------------------------------------------------------
// Save
// ---------------------------------------------------------------------------

/** POST /api/{mundo}/{section}/save?path= — write file content. */
export async function saveFile(
  mundo: string,
  section: string,
  path: string,
  content: string,
): Promise<SuccessResponse> {
  return apiFetch<SuccessResponse>(
    apiUrl(["api", mundo, section, "save"], { path }),
    {
      method: "POST",
      body: JSON.stringify({ content }),
    },
  );
}

// ---------------------------------------------------------------------------
// Create
// ---------------------------------------------------------------------------

/** POST /api/{mundo}/{section}/create?path= — create a new file. */
export async function createFile(
  mundo: string,
  section: string,
  path: string,
  content?: string,
): Promise<SuccessResponse> {
  return apiFetch<SuccessResponse>(
    apiUrl(["api", mundo, section, "create"], { path }),
    {
      method: "POST",
      body: JSON.stringify({ content: content ?? "" }),
    },
  );
}

// ---------------------------------------------------------------------------
// Delete
// ---------------------------------------------------------------------------

/** DELETE /api/{mundo}/{section}/file?path= — delete a file. */
export async function deleteFile(
  mundo: string,
  section: string,
  path: string,
): Promise<SuccessResponse> {
  return apiFetch<SuccessResponse>(
    apiUrl(["api", mundo, section, "file"], { path }),
    { method: "DELETE" },
  );
}

// ---------------------------------------------------------------------------
// Move / Duplicate
// ---------------------------------------------------------------------------

/**
 * POST /api/{mundo}/move — rename or move a file/folder.
 * `from` and `to` are mundo-relative paths with forward slashes
 * (e.g. `lore/ciudades/planos.md` → `personajes/planos.md`).
 */
export async function moveNode(
  mundo: string,
  from: string,
  to: string,
): Promise<MoveResponse> {
  return apiFetch<MoveResponse>(apiUrl(["api", mundo, "move"]), {
    method: "POST",
    body: JSON.stringify({ from, to }),
  });
}

/** POST /api/{mundo}/duplicate — copy a file next to the original with an auto-name. */
export async function duplicateFile(
  mundo: string,
  from: string,
): Promise<DuplicateResponse> {
  return apiFetch<DuplicateResponse>(apiUrl(["api", mundo, "duplicate"]), {
    method: "POST",
    body: JSON.stringify({ from }),
  });
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

/**
 * POST /api/{mundo}/{section}/status — rewrite ONLY the frontmatter
 * `status:` line (Borrador → draft, Canon → stable). Instant and
 * independent of the save flow.
 */
export async function setStatus(
  mundo: string,
  section: string,
  path: string,
  status: FichaStatus,
): Promise<SuccessResponse> {
  return apiFetch<SuccessResponse>(
    apiUrl(["api", mundo, section, "status"]),
    {
      method: "POST",
      body: JSON.stringify({ path, status }),
    },
  );
}

// ---------------------------------------------------------------------------
// Diff
// ---------------------------------------------------------------------------

/** POST /api/{mundo}/{section}/diff?path= — compare proposed vs current. */
export async function getDiff(
  mundo: string,
  section: string,
  path: string,
  newContent: string,
): Promise<DiffPreview> {
  return apiFetch<DiffPreview>(
    apiUrl(["api", mundo, section, "diff"], { path }),
    {
      method: "POST",
      body: JSON.stringify({ content: newContent }),
    },
  );
}

// ---------------------------------------------------------------------------
// Media / Images
// ---------------------------------------------------------------------------

/** GET /api/{mundo}/media/list — list all images in a world. */
export async function listImages(mundo: string): Promise<MediaList> {
  return apiFetch<MediaList>(apiUrl(["api", mundo, "media", "list"]));
}

/** POST /api/{mundo}/media/upload — upload an image file. */
export async function uploadImage(
  mundo: string,
  file: File,
  overwrite?: boolean,
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  // Build URL ourselves since this is multipart — apiFetch would set a
  // JSON content-type that breaks multipart boundary parsing.
  const basePath =
    "/" +
    ["api", mundo, "media", "upload"]
      .map((s) => encodeURIComponent(s))
      .join("/");

  let url = `${API_BASE_URL}${basePath}`;
  if (overwrite) {
    url += `?overwrite=true`;
  }

  const response = await fetch(url, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = await response.json();
      detail = body.detail;
    } catch {
      // ignore parse errors
    }
    throw new ApiError(response.status, detail ?? `HTTP ${response.status}`, detail);
  }

  return (await response.json()) as UploadResponse;
}

/** DELETE /api/{mundo}/media?path= — delete an image from wiki/media/. */
export async function deleteImage(
  mundo: string,
  path: string,
): Promise<SuccessResponse> {
  return apiFetch<SuccessResponse>(
    apiUrl(["api", mundo, "media"], { path }),
    { method: "DELETE" },
  );
}

/**
 * Returns the full URL to serve an image.
 * Used directly in <img> tags and for thumbnails.
 */
export function getMediaUrl(mundo: string, path: string): string {
  const encodedMundo = encodeURIComponent(mundo);
  const encodedPath = encodeURIComponent(path);
  return `${API_BASE_URL}/api/${encodedMundo}/media?path=${encodedPath}`;
}

// ---------------------------------------------------------------------------
// Papelera (Trash)
// ---------------------------------------------------------------------------

/** GET /api/{mundo}/papelera — list every trashed entry in a world. */
export async function listTrash(
  mundo: string,
): Promise<{ entries: TrashEntry[]; purged: number }> {
  const res = await apiFetch<TrashListResponse>(
    apiUrl(["api", mundo, "papelera"]),
  );
  // `purged` is OPTIONAL — the backend omits it when the lazy 30-day TTL
  // purge removed nothing (keeps the empty envelope byte-identical).
  return { entries: res.entries, purged: res.purged ?? 0 };
}

/** POST /api/{mundo}/papelera/restore — move a trashed entry back to its original path. */
export async function restoreFromTrash(
  mundo: string,
  entry_id: string,
  section: string,
): Promise<{ restored_to: string }> {
  return apiFetch<{ restored_to: string }>(
    apiUrl(["api", mundo, "papelera", "restore"]),
    {
      method: "POST",
      body: JSON.stringify({ entry_id, section }),
    },
  );
}

/** DELETE /api/{mundo}/papelera?entry_id=&section= — permanently purge a single entry. */
export async function purgeTrashItem(
  mundo: string,
  entry_id: string,
  section: string,
): Promise<void> {
  await apiFetch(
    apiUrl(["api", mundo, "papelera"], { entry_id, section }),
    { method: "DELETE" },
  );
}

/** DELETE /api/{mundo}/papelera — permanently empty the whole trash. */
export async function emptyTrash(mundo: string): Promise<EmptyTrashResponse> {
  return apiFetch<EmptyTrashResponse>(apiUrl(["api", mundo, "papelera"]), {
    method: "DELETE",
  });
}
