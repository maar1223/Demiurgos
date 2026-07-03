import { apiFetch } from "@/api/client";
import type {
  DiffPreview,
  FileContent,
  FileNode,
  SuccessResponse,
  WorldInfo,
} from "@/api/types";
import { API_BASE_URL } from "@/lib/constants";

/**
 * Builds a URL from segments and query params.
 * The base URL is empty when Vite proxies /api in dev via vite.config.ts.
 */
function apiUrl(
  segments: string[],
  params?: Record<string, string>,
): string {
  const path = segments
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
): Promise<FileNode[]> {
  return apiFetch<FileNode[]>(
    apiUrl(["api", mundo, section, "tree"]),
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
