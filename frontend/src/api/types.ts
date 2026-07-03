/** Info about a single world returned by GET /api/worlds. */
export interface WorldInfo {
  name: string;
  has_lore: boolean;
  has_personajes: boolean;
  has_sagas: boolean;
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
