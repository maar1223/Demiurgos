/** Info about a single world returned by GET /api/worlds. */
export interface WorldInfo {
  name: string;
  path: string;
  lore_count: number;
  character_count: number;
  saga_count: number;
}

/** A file or directory node in the section tree. */
export interface FileNode {
  name: string;
  path: string;
  is_dir: boolean;
  children?: FileNode[];
  /**
   * OKF ficha status (draft|stable) parsed from the file's leading
   * frontmatter. Present ONLY when the backend knows a valid status —
   * unknown values (e.g. the idea-bank `synced`) and directories never
   * carry the field.
   */
  status?: FichaStatus;
  /**
   * Mundo-relative cover path (e.g. `wiki/media/x.jpg`).
   * Only present when the tree was requested with `?covers=true`;
   * `null` when the file has no resolvable cover (dirs are always null).
   */
  portada?: string | null;
}

/** Content and metadata of a single file. */
export interface FileContent {
  path: string;
  content: string;
  /** Legacy metadata is optional because the current file endpoint omits it. */
  name?: string;
  /** Current backend response field; legacy metadata remains for consumers. */
  size: number;
  size_bytes?: number;
  modified?: string; // ISO 8601
  extension?: string;
  /** SHA-256 digest of the exact bytes used as the edit base. */
  revision: string;
}

/** Generic success response for save/create/delete. */
export interface SuccessResponse {
  success: boolean;
  path: string;
}

/** Status returned by the explicit loopback-only local development session. */
export interface LocalDevSessionStatus {
  mode: string;
  enabled: boolean;
  authenticated: boolean;
  label: string | null;
}

/** OKF ficha status — UI maps Borrador → draft, Canon → stable. */
export type FichaStatus = "draft" | "stable";

/** Response from POST /api/{mundo}/move — same shape as SuccessResponse. */
export interface MoveResponse {
  success: boolean;
  path: string;
}

/** Response from POST /api/{mundo}/duplicate — same shape as SuccessResponse. */
export interface DuplicateResponse {
  success: boolean;
  path: string;
}

/** A single line in a diff preview. */
export interface DiffLine {
  type: "same" | "added" | "removed";
  text: string;
}

/** Preview of a diff between current and proposed content. */
export interface DiffPreview {
  original_path: string;
  original_content: string;
  new_content: string;
  diff: DiffLine[];
}

// ---------------------------------------------------------------------------
// Secure editing
// ---------------------------------------------------------------------------

export type EditKind = "edit" | "new" | "restore";

/** Validated, diskless proposal returned by the Hermes edit endpoint. */
export interface EditProposal {
  proposal_id: string;
  target: string;
  base_revision: string;
  proposed_content: string;
  proposed_digest: string;
  rationale: string;
  is_new_file: boolean;
}

/** Request body for POST /api/{mundo}/ai/edit-suggest. */
export interface EditSuggestionRequest {
  section: string;
  path: string;
  prompt: string;
  session_id?: string;
}

/** Response envelope for the bounded Hermes proposal flow. */
export interface EditSuggestionResponse {
  proposal: EditProposal | null;
  attempts: number;
  outcome: "proposal" | "fallback";
  fallback_action?: string;
  message?: string;
}

/** Request body for issuing a server-verifiable confirmation token. */
export interface EditConfirmationRequest {
  edit_id: string;
  base_revision?: string;
  proposed_content?: string;
  kind: EditKind;
  snapshot_id?: string;
}

/** Single-use proof returned by the confirmation endpoint. */
export interface EditConfirmation {
  token: string;
  expires_at: string;
  proposed_digest: string;
}

/** Proof fields required by the gated save/create endpoints. */
export interface ConfirmedEditRequest {
  content: string;
  base_revision?: string;
  proposed_digest: string;
  edit_id: string;
  token: string;
}

/** A retained snapshot returned by the history endpoint. */
export interface HistoryEntry {
  id: string;
  snapshot_id: string;
  target: string;
  created_at: string; // ISO 8601
  content: string;
  revision: string;
  size: number;
}

/** Response from GET /api/{mundo}/history?path=. */
export interface HistoryListResponse {
  target: string;
  entries: HistoryEntry[];
}

/** Request body for the confirmation-gated history restore endpoint. */
export interface RestoreFileRequest extends ConfirmedEditRequest {
  path: string;
  snapshot_id: string;
}

// ---------------------------------------------------------------------------
// Graph
// ---------------------------------------------------------------------------

/** Result item from graph entity search. */
export interface SearchResult {
  name: string;
  type: string;
  path: string;
  title: string;
  description: string;
  tags: string[];
  link_count: number;
  score: number;
}

/** Full entity detail from the knowledge graph. */
export interface GraphEntity {
  name: string;
  type: string;
  path: string;
  content: string;
  forward_links: string[];
  backlinks: string[];
  relaciones: Record<string, unknown>[];
}

/** A directed connection between two entities in the graph. */
export interface EntityLink {
  source: string;
  target: string;
  kind: string;
}

/** Graph indexing and health status. */
export interface GraphStatus {
  node_count: number;
  link_count: number;
  indexed: boolean;
}

// ---------------------------------------------------------------------------
// Media / Images
// ---------------------------------------------------------------------------

/** Info about a single image file in a world. */
export interface ImageInfo {
  path: string;
  name: string;
  size_bytes: number;
  extension: string;
  thumbnail_path?: string;
}

/** Response from GET /api/{mundo}/media/list — all images in a world. */
export interface MediaList {
  images: ImageInfo[];
  total: number;
}

/** Response from POST /api/{mundo}/media/upload. */
export interface UploadResponse {
  success: boolean;
  path: string;
  size_bytes: number;
  thumbnail_path?: string;
}

// ---------------------------------------------------------------------------
// Papelera (Trash)
// ---------------------------------------------------------------------------

/** A single entry in a world's trash (papelera). */
export interface TrashEntry {
  entry_id: string;
  section: string;
  original_path: string;
  kind: "file" | "dir";
  deleted_at: string; // ISO 8601
  size: number; // bytes
}

/**
 * Response from GET /api/{mundo}/papelera — the trash list plus the count of
 * expired entries the lazy 30-day TTL purge removed on this call.
 */
export interface TrashListResponse {
  entries: TrashEntry[];
  /**
   * Expired entries auto-purged by the 30-day TTL. OPTIONAL in the response:
   * the backend omits it when zero entries were purged (preserves the
   * byte-identical `{"entries": []}` empty contract) — consumers must
   * normalize with `?? 0`.
   */
  purged?: number;
}

/** Response from DELETE /api/{mundo}/papelera — emptying the whole trash. */
export interface EmptyTrashResponse {
  purged: "all";
  entries: number;
}

/** Structured API error. */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
