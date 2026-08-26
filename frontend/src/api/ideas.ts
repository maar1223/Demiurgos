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
}

export interface IdeaUpdateInput {
  type?: IdeaType;
  status?: IdeaStatus;
  source?: IdeaSource;
  tags?: string[];
  used_in?: string[];
  based_on?: string | null;
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