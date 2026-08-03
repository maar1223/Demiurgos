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
}

/** Content and metadata of a single file. */
export interface FileContent {
  path: string;
  name: string;
  content: string;
  size_bytes: number;
  modified: string; // ISO 8601
  extension: string;
}

/** Generic success response for save/create/delete. */
export interface SuccessResponse {
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
