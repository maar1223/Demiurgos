import { apiFetch } from "@/api/client";
import type {
  EntityLink,
  GraphEntity,
  GraphStatus,
  SearchResult,
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
  const path =
    "/" + segments.map((s) => encodeURIComponent(s)).join("/");
  const url = `${API_BASE_URL}${path}`;
  if (!params) return url;
  const qs = new URLSearchParams(params).toString();
  return `${url}?${qs}`;
}

// ---------------------------------------------------------------------------
// Entity Search
// ---------------------------------------------------------------------------

/** GET /api/{mundo}/graph/search?q=&mundo= — fuzzy search entities. */
export async function searchEntities(
  mundo: string,
  q: string,
): Promise<SearchResult[]> {
  return apiFetch<SearchResult[]>(
    apiUrl(["api", mundo, "graph", "search"], { q, mundo }),
  );
}

// ---------------------------------------------------------------------------
// Entity Detail
// ---------------------------------------------------------------------------

/** GET /api/{mundo}/graph/entity?name=&mundo= — single entity detail. */
export async function getEntity(
  mundo: string,
  name: string,
): Promise<GraphEntity> {
  return apiFetch<GraphEntity>(
    apiUrl(["api", mundo, "graph", "entity"], { name, mundo }),
  );
}

// ---------------------------------------------------------------------------
// Entity Links
// ---------------------------------------------------------------------------

/** GET /api/{mundo}/graph/links?name=&mundo=&kind= — entity connections. */
export async function getLinks(
  mundo: string,
  name: string,
  kind?: string,
): Promise<EntityLink[]> {
  const params: Record<string, string> = { name, mundo };
  if (kind) params.kind = kind;
  return apiFetch<EntityLink[]>(
    apiUrl(["api", mundo, "graph", "links"], params),
  );
}

// ---------------------------------------------------------------------------
// Graph Status
// ---------------------------------------------------------------------------

/** GET /api/{mundo}/graph/status — graph indexing status. */
export async function getGraphStatus(
  mundo: string,
): Promise<GraphStatus> {
  return apiFetch<GraphStatus>(
    apiUrl(["api", mundo, "graph", "status"], { mundo }),
  );
}
