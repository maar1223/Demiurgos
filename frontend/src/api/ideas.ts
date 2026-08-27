import { apiFetch } from "@/api/client";
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
  source: IdeaSource;
  type: IdeaType;
  title: string;
  tags: string[];
  status: IdeaStatus;
  used_in: string[];
  based_on: string | null;
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