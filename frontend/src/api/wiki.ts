import { apiFetch } from "@/api/client";
import { ApiError } from "@/api/types";
import type {
  AiAskResponse,
  AuthSessionStatus,
  DiffPreview,
  DuplicateResponse,
  EmergencyKeyRotationResponse,
  EmptyTrashResponse,
  EditConfirmation,
  EditConfirmationRequest,
  EditSuggestionRequest,
  EditSuggestionResponse,
  FichaStatus,
  FileContent,
  FileNode,
  GoogleNonceResponse,
  HistoryListResponse,
  LocalDevSessionStatus,
  MediaList,
  MoveResponse,
  ConfirmedEditRequest,
  RestoreFileRequest,
  SuccessResponse,
  SystemControlResponse,
  TrashEntry,
  TrashListResponse,
  UploadResponse,
  WorldInfo,
} from "@/api/types";
import { API_BASE_URL } from "@/lib/constants";

// ---------------------------------------------------------------------------
// Local development authentication
// ---------------------------------------------------------------------------

/** GET /api/auth/local-dev/session — inspect the local session status. */
export function getLocalDevSession(): Promise<LocalDevSessionStatus> {
  return apiFetch<LocalDevSessionStatus>(
    apiUrl(["api", "auth", "local-dev", "session"]),
    { credentials: "same-origin" },
  );
}

/** POST /api/auth/local-dev/session — start a server-issued local session. */
export function startLocalDevSession(): Promise<LocalDevSessionStatus> {
  return apiFetch<LocalDevSessionStatus>(
    apiUrl(["api", "auth", "local-dev", "session"]),
    { method: "POST", credentials: "same-origin" },
  );
}

/** DELETE /api/auth/local-dev/session — clear the local session cookie. */
export function logoutLocalDevSession(): Promise<LocalDevSessionStatus> {
  return apiFetch<LocalDevSessionStatus>(
    apiUrl(["api", "auth", "local-dev", "session"]),
    { method: "DELETE", credentials: "same-origin" },
  );
}

// ---------------------------------------------------------------------------
// Vault authentication (google mode — DEMIURGOS_AUTH_MODE=google)
// ---------------------------------------------------------------------------

/** GET /api/auth/session/status — unified mode-aware session status. */
export function getAuthStatus(): Promise<AuthSessionStatus> {
  return apiFetch<AuthSessionStatus>(
    apiUrl(["api", "auth", "session", "status"]),
    { credentials: "same-origin" },
  );
}

/** GET /api/auth/google/nonce — short-lived nonce bound to this browser. */
export function getGoogleNonce(): Promise<GoogleNonceResponse> {
  return apiFetch<GoogleNonceResponse>(
    apiUrl(["api", "auth", "google", "nonce"]),
    { credentials: "same-origin" },
  );
}

/**
 * POST /api/auth/google/session — verify the GIS id_token (iss, aud, exp,
 * nonce) and issue the HttpOnly vault session cookie. `remember_me` extends
 * the session TTL from 8h to 14d.
 */
export function startGoogleSession(
  id_token: string,
  remember_me: boolean,
): Promise<AuthSessionStatus> {
  return apiFetch<AuthSessionStatus>(
    apiUrl(["api", "auth", "google", "session"]),
    {
      method: "POST",
      credentials: "same-origin",
      body: JSON.stringify({ id_token, remember_me }),
    },
  );
}

/** POST /api/auth/emergency/session — offline recovery-key login. */
export function startEmergencySession(key: string): Promise<AuthSessionStatus> {
  return apiFetch<AuthSessionStatus>(
    apiUrl(["api", "auth", "emergency", "session"]),
    {
      method: "POST",
      credentials: "same-origin",
      body: JSON.stringify({ key }),
    },
  );
}

/** POST /api/auth/emergency/rotate — rotate the recovery key (requires an
 *  active session). Returns the new plaintext key exactly once. */
export function rotateEmergencyKey(): Promise<EmergencyKeyRotationResponse> {
  return apiFetch<EmergencyKeyRotationResponse>(
    apiUrl(["api", "auth", "emergency", "rotate"]),
    { method: "POST", credentials: "same-origin" },
  );
}

/** DELETE /api/auth/session — unified logout for any provider. */
export function logoutSession(): Promise<AuthSessionStatus> {
  return apiFetch<AuthSessionStatus>(
    apiUrl(["api", "auth", "session"]),
    { method: "DELETE", credentials: "same-origin" },
  );
}

/**
 * POST /api/system/{action} — dispatch a launcher-driven restart or shutdown
 * of the whole Demiurgos stack. The launcher takes a while to tear services
 * down and (for restart) bring them back, so this call MUST use an explicit
 * long timeout (≥90s) instead of the apiFetch default 5s. The local session
 * is expected to be closed (logout) BEFORE this call — the session does not
 * survive a restart.
 */
export function systemControlAction(
  action: "restart" | "shutdown",
): Promise<SystemControlResponse> {
  return apiFetch<SystemControlResponse>(
    apiUrl(["api", "system", action]),
    { method: "POST", credentials: "same-origin", timeout: 90_000 },
  );
}

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
// Assistant ask
// ---------------------------------------------------------------------------

/**
 * POST /api/{mundo}/ai/ask — the AI assistant turn boundary.
 *
 * Returns either a legacy chat answer, a guided handoff envelope, or the
 * validated semantic decision envelope emitted by the server seam. The client
 * never interprets raw provider output: every state and continuation field is
 * server-owned and strictly validated on the backend.
 */
export async function askAssistant(
  mundo: string,
  request: {
    prompt: string;
    session_id: string;
    section?: string;
    file_path?: string;
    guided_session_id?: string;
    guided_revision?: number;
  },
  signal?: AbortSignal,
): Promise<AiAskResponse> {
  const response = await fetch(
    `/api/${encodeURIComponent(mundo)}/ai/ask`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal,
    },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = isRecord(body) && typeof body.detail === "string" ? body.detail : undefined;
    throw new ApiError(response.status, detail ?? `HTTP ${response.status}`, detail);
  }
  return (await response.json()) as AiAskResponse;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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
// Secure editing
// ---------------------------------------------------------------------------

/** POST /api/{mundo}/ai/edit-suggest — request a validated diskless proposal. */
export async function suggestEdit(
  mundo: string,
  request: EditSuggestionRequest,
): Promise<EditSuggestionResponse> {
  return apiFetch<EditSuggestionResponse>(
    apiUrl(["api", mundo, "ai", "edit-suggest"]),
    {
      method: "POST",
      body: JSON.stringify(request),
    },
  );
}

/**
 * POST /api/{mundo}/{section}/edit-confirmation?path= — issue a single-use
 * confirmation proof for a reviewed candidate.
 */
export async function requestConfirmation(
  mundo: string,
  section: string,
  path: string,
  request: EditConfirmationRequest,
): Promise<EditConfirmation> {
  return apiFetch<EditConfirmation>(
    apiUrl(["api", mundo, section, "edit-confirmation"], { path }),
    {
      method: "POST",
      body: JSON.stringify(request),
    },
  );
}

/** POST /api/{mundo}/{section}/save?path= — persist an existing reviewed edit. */
export async function saveFileConfirmed(
  mundo: string,
  section: string,
  path: string,
  request: ConfirmedEditRequest,
): Promise<SuccessResponse> {
  return apiFetch<SuccessResponse>(
    apiUrl(["api", mundo, section, "save"], { path }),
    {
      method: "POST",
      body: JSON.stringify(request),
    },
  );
}

/** POST /api/{mundo}/{section}/create?path= — create a reviewed new file. */
export async function createFileConfirmed(
  mundo: string,
  section: string,
  path: string,
  request: ConfirmedEditRequest,
): Promise<SuccessResponse> {
  return apiFetch<SuccessResponse>(
    apiUrl(["api", mundo, section, "create"], { path }),
    {
      method: "POST",
      body: JSON.stringify(request),
    },
  );
}

/** GET /api/{mundo}/history?path= — list valid snapshots newest first. */
export async function listHistory(
  mundo: string,
  path: string,
): Promise<HistoryListResponse> {
  return apiFetch<HistoryListResponse>(
    apiUrl(["api", mundo, "history"], { path }),
  );
}

/** POST /api/{mundo}/history/restore — restore through the gated pipeline. */
export async function restoreFile(
  mundo: string,
  request: RestoreFileRequest,
): Promise<SuccessResponse> {
  return apiFetch<SuccessResponse>(
    apiUrl(["api", mundo, "history", "restore"]),
    {
      method: "POST",
      body: JSON.stringify(request),
    },
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
