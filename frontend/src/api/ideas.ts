import { apiFetch } from "@/api/client";
import { ApiError } from "@/api/types";
import { API_BASE_URL } from "@/lib/constants";

/**
 * Client for the global ideas bank — `/api/ideas` (backend: wiki
 * `ideas_bank_router`, R-IB-03). Ideas are world-agnostic archetypes stored
 * at the top-level `ideas/` dir; the frontend consumes the same REST contract
 * for list/detail/create/update/delete/materialize.
 */

export const IDEA_TYPES = [
  "personaje",
  "relacion",
  "ambientacion",
  "trama",
  "concepto",
  "sin_clasificar",
] as const;
export type IdeaType = (typeof IDEA_TYPES)[number];

export const IDEA_SOURCES = ["telegram", "manual", "assistant"] as const;
export type IdeaSource = (typeof IDEA_SOURCES)[number];

export const IDEA_STATUSES = ["fresh", "used"] as const;
export type IdeaStatus = (typeof IDEA_STATUSES)[number];

/** List entry — the backend summary omits `body` (R-IB-03). */
export interface IdeaSummary {
  id: string;
  slug: string;
  timestamp: string;
  /** Server-managed last-change stamp; falls back to `timestamp` for legacy ideas. */
  updated_at: string;
  source: IdeaSource;
  type: IdeaType;
  title: string;
  tags: string[];
  status: IdeaStatus;
  used_in: string[];
  based_on: string | null;
  /** Relative path under the ideas bank, e.g. `media/{slug}.png` (null = no image). */
  media_path: string | null;
}

/** Detail — includes the free-text body. */
export interface IdeaDetail extends IdeaSummary {
  body: string;
}

export interface IdeaListResponse {
  ideas: IdeaSummary[];
  total: number;
}

export interface IdeaListFilters {
  type?: IdeaType;
  status?: IdeaStatus;
  source?: IdeaSource;
}

export interface IdeaCreateInput {
  slug: string;
  type: IdeaType;
  body: string;
  tags?: string[];
  source?: IdeaSource;
  /** Human-readable title; empty/omitted falls back to the slug in the UI. */
  title?: string;
}

export interface IdeaUpdateInput {
  type?: IdeaType;
  status?: IdeaStatus;
  source?: IdeaSource;
  tags?: string[];
  used_in?: string[];
  based_on?: string | null;
  title?: string;
  body?: string;
}

export interface IdeaDeleteResult {
  ok: boolean;
  slug: string;
}

export interface IdeaMaterializeResult {
  ok: boolean;
  used_in: string[];
  canon_path: string | null;
}

/** Graph-indexed sections a ficha can be materialized into (R-IM-01). */
export const MATERIALIZE_SECTIONS = ["lore", "personajes", "referencias"] as const;
export type MaterializeSection = (typeof MATERIALIZE_SECTIONS)[number];

/** POST /api/ideas/{slug}/materialize-preview payload (R-IM-01). */
export interface IdeaMaterializePreviewInput {
  world: string;
  section: MaterializeSection;
  /** Section-relative folder path; "" = the section root. */
  folder: string;
  title_hint?: string;
}

/** Resolved target of a materialize preview; `path` is section-relative
 *  (e.g. `subdir/arquero-ciego.md` or `arquero-ciego.md` for the root). */
export interface IdeaMaterializeTarget {
  world: string;
  section: string;
  folder: string;
  slug: string;
  path: string;
}

/** One AI-proposed relation that survived target/vocabulary validation. */
export interface ProposedMaterializeRelation {
  target_id: string;
  title: string;
  rel_type: string;
}

/** One AI-proposed relation dropped before the preview (R-IM-03). */
export interface DiscardedMaterializeRelation {
  target_id: string;
  reason: "target_not_found" | "rel_type_out_of_vocabulary";
}

/** 409 collision suggestion (AD5): `suggested_slug` follows the -2 rule. */
export interface MaterializeCollision {
  target: string;
  suggested_slug: string;
  suggested_target: string;
}

/** POST /api/ideas/{slug}/materialize-preview response (200). */
export interface IdeaMaterializePreviewResult {
  proposal_id: string;
  target: IdeaMaterializeTarget;
  content: string;
  proposed_relations: ProposedMaterializeRelation[];
  discarded_relations: DiscardedMaterializeRelation[];
  collision?: MaterializeCollision;
}

/** One archived version of an idea (R-10) — number + archive path. */
export interface IdeaVersionSummary {
  version: number;
  path: string;
}

/** GET /api/ideas/{slug}/versions response (R-10, S-10.2). */
export interface IdeaVersionsResponse {
  slug: string;
  versions: IdeaVersionSummary[];
}

/** Same-origin credentials so the local-dev session cookie authorizes reads. */
const CREDENTIALS = { credentials: "same-origin" as const };

/** Build an `/api/ideas` URL, optionally appending query params. */
function ideasUrl(segments: string[], params?: Record<string, string>): string {
  const path =
    "/" + ["api", "ideas", ...segments].map((s) => encodeURIComponent(s)).join("/");
  const url = `${API_BASE_URL}${path}`;
  if (!params || Object.keys(params).length === 0) return url;
  const qs = new URLSearchParams(params).toString();
  return `${url}?${qs}`;
}

/** GET /api/ideas — list with optional type/status/source filters. */
export function listIdeas(filters: IdeaListFilters = {}): Promise<IdeaListResponse> {
  const params: Record<string, string> = {};
  if (filters.type) params.type = filters.type;
  if (filters.status) params.status = filters.status;
  if (filters.source) params.source = filters.source;
  return apiFetch<IdeaListResponse>(ideasUrl([], params), CREDENTIALS);
}

/** GET /api/ideas/{slug} — full detail including body. */
export function getIdea(slug: string): Promise<IdeaDetail> {
  return apiFetch<IdeaDetail>(ideasUrl([slug]), CREDENTIALS);
}

/** POST /api/ideas — create a manual idea (defaults to `source: manual`). */
export function createIdea(input: IdeaCreateInput): Promise<IdeaDetail> {
  return apiFetch<IdeaDetail>(ideasUrl([]), {
    method: "POST",
    body: JSON.stringify(input),
    ...CREDENTIALS,
  });
}

/** PATCH /api/ideas/{slug} — partial update (type correction, status, ...). */
export function updateIdea(slug: string, input: IdeaUpdateInput): Promise<IdeaDetail> {
  return apiFetch<IdeaDetail>(ideasUrl([slug]), {
    method: "PATCH",
    body: JSON.stringify(input),
    ...CREDENTIALS,
  });
}

/** DELETE /api/ideas/{slug} — remove an idea from the global bank. */
export function deleteIdea(slug: string): Promise<IdeaDeleteResult> {
  return apiFetch<IdeaDeleteResult>(ideasUrl([slug]), {
    method: "DELETE",
    ...CREDENTIALS,
  });
}

/**
 * GET /api/ideas/{slug}/versions — archived version history, ascending by
 * version number (R-10, S-10.2).
 */
export function getIdeaVersions(slug: string): Promise<IdeaVersionsResponse> {
  return apiFetch<IdeaVersionsResponse>(
    ideasUrl([slug, "versions"]),
    CREDENTIALS,
  );
}

/**
 * POST /api/ideas/{slug}/materialize — record that a world used this idea:
 * appends the world slug to `used_in[]` and sets `status: used` (R-CG-04).
 */
export function materializeIdea(
  slug: string,
  world: string,
  canonRel?: string,
): Promise<IdeaMaterializeResult> {
  return apiFetch<IdeaMaterializeResult>(ideasUrl([slug, "materialize"]), {
    method: "POST",
    body: JSON.stringify({ world, ...(canonRel ? { canon_rel: canonRel } : {}) }),
    ...CREDENTIALS,
  });
}

/**
 * POST /api/ideas/{slug}/materialize-preview — preview an AI-authored ficha
 * for this idea in a world folder. Read-only: zero canon writes (R-IM-04).
 *
 * Uses raw fetch on purpose: the 409 collision payload sits at the TOP level
 * of the error body (`{detail, collision}`) and apiFetch would drop it; the
 * collision is attached to the thrown ApiError so the picker can offer the
 * `suggested_slug` (AD5). The provider-unavailable 503 body
 * (`{status:"unavailable", retryable:true}`) is likewise mapped to a
 * readable message instead of a bare `HTTP 503`.
 */
export async function previewMaterialize(
  slug: string,
  input: IdeaMaterializePreviewInput,
): Promise<IdeaMaterializePreviewResult> {
  const response = await fetch(ideasUrl([slug, "materialize-preview"]), {
    method: "POST",
    body: JSON.stringify(input),
    ...CREDENTIALS,
  });

  if (!response.ok) {
    let detail: string | undefined;
    let collision: MaterializeCollision | undefined;
    let unavailable = false;
    try {
      const body = await response.json();
      detail = body.detail;
      collision = body.collision;
      unavailable = body.status === "unavailable";
    } catch {
      // ignore parse errors on error responses
    }
    const error = new ApiError(
      response.status,
      detail ??
        (unavailable
          ? "Materialization provider is unavailable."
          : `HTTP ${response.status}`),
      detail,
    );
    if (collision) {
      (error as ApiError & { collision?: MaterializeCollision }).collision =
        collision;
    }
    throw error;
  }

  return (await response.json()) as IdeaMaterializePreviewResult;
}

/**
 * POST /api/ideas/{slug}/media — attach an image to an existing idea
 * (multipart, versioned). Uses raw fetch on purpose: apiFetch would set a
 * JSON content-type that breaks the multipart boundary — same pattern as
 * `uploadImage` in `@/api/wiki`.
 */
export async function attachIdeaMedia(
  slug: string,
  file: File,
): Promise<IdeaDetail> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(ideasUrl([slug, "media"]), {
    method: "POST",
    body: formData,
    credentials: "same-origin",
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

  return (await response.json()) as IdeaDetail;
}

/**
 * Pending-capture review queue — `/api/idea-capture/pending` (backend: wiki
 * `idea_capture_ui`, R-7). Text captures the capture guidance parked in
 * AWAITING_CONFIRM (uncertain ideas) are listed here so the author can save
 * them to the global bank or discard them from the web Taller. Every call
 * carries the local-dev session cookie like the rest of the idea-capture API.
 */

/** A capture parked in AWAITING_CONFIRM awaiting a Guardar/Descartar decision. */
export interface PendingCapture {
  capture_id: string;
  slug: string;
  raw_text: string;
  created_at: string;
  event_ts: string;
  media_kind: string;
}

export interface PendingListResponse {
  captures: PendingCapture[];
  count: number;
}

/** Build an `/api/idea-capture/pending` URL. */
function pendingUrl(segments: string[]): string {
  const path =
    "/" +
    ["api", "idea-capture", "pending", ...segments]
      .map((s) => encodeURIComponent(s))
      .join("/");
  return `${API_BASE_URL}${path}`;
}

/** GET /api/idea-capture/pending — parked captures + count (S-7.1, S-8.1). */
export function listPendingCaptures(): Promise<PendingListResponse> {
  return apiFetch<PendingListResponse>(pendingUrl([]), CREDENTIALS);
}

/** POST /api/idea-capture/pending/{id}/confirm — save as a global idea. */
export function confirmCapture(id: string): Promise<{ ok: true }> {
  return apiFetch<{ ok: true }>(pendingUrl([id, "confirm"]), {
    method: "POST",
    ...CREDENTIALS,
  });
}

/** POST /api/idea-capture/pending/{id}/discard — cancel the parked capture. */
export function discardCapture(id: string): Promise<{ ok: true }> {
  return apiFetch<{ ok: true }>(pendingUrl([id, "discard"]), {
    method: "POST",
    ...CREDENTIALS,
  });
}

/**
 * GET /api/ideas/{slug}/export/docx — download an idea's body (embedded
 * images rewritten to disk paths server-side) as a `.docx` blob. The
 * endpoint is principal-gated, so the local-dev session cookie is carried
 * like the rest of the ideas API. The caller triggers the download with
 * `downloadBlob`.
 */
export async function exportIdeaDocx(slug: string): Promise<Blob> {
  const response = await fetch(ideasUrl([slug, "export", "docx"]), CREDENTIALS);

  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = await response.json();
      detail = body.detail;
    } catch {
      // ignore parse errors on error responses
    }
    throw new ApiError(response.status, detail ?? `HTTP ${response.status}`, detail);
  }

  return response.blob();
}