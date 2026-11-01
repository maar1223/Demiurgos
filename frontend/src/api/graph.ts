import { apiFetch } from "@/api/client";
import type {
  EntityLink,
  GraphEntity,
  GraphStatus,
  RelationCandidatesResponse,
  RelationProposalsResponse,
  RelationQualityReport,
  RelationReconcileApply,
  RelationReconcilePreview,
  RelationResponse,
  RelationSweepResponse,
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

// ---------------------------------------------------------------------------
// Bulk Entities + Links (BLOQUE 4 — Relaciones y Canon)
// ---------------------------------------------------------------------------

/** Status filter for the bulk entities endpoint. */
export type GraphStatusFilter = "all" | "draft" | "stable";

/**
 * GET /api/{mundo}/graph/entities?status= — bulk entities + links for
 * graph consumption. Each entity carries `status` (draft|stable).
 */
export async function fetchGraphEntities(
  mundo: string,
  status: GraphStatusFilter = "all",
): Promise<{ entities: GraphEntity[]; links: EntityLink[] }> {
  return apiFetch<{ entities: GraphEntity[]; links: EntityLink[] }>(
    apiUrl(["api", mundo, "graph", "entities"], { status }),
  );
}

// ---------------------------------------------------------------------------
// Relations (BLOQUE 4 — crear/romper conexiones del grafo)
// ---------------------------------------------------------------------------

/**
 * Shared POST /api/{mundo}/graph/relation — rewrites the source ficha's
 * frontmatter `relaciones:` list (create/break a canonical-id entry).
 */
async function setRelation(
  mundo: string,
  action: "create" | "break",
  sourcePath: string,
  targetId: string,
): Promise<RelationResponse> {
  return apiFetch<RelationResponse>(
    apiUrl(["api", mundo, "graph", "relation"]),
    {
      method: "POST",
      body: JSON.stringify({
        action,
        source_path: sourcePath,
        target_id: targetId,
      }),
    },
  );
}

/** POST /api/{mundo}/graph/relation {action: "create"} — add a connection
 *  from the source ficha (sourcePath) to the target entity (targetId). */
export async function createRelation(
  mundo: string,
  sourcePath: string,
  targetId: string,
): Promise<RelationResponse> {
  return setRelation(mundo, "create", sourcePath, targetId);
}

/** POST /api/{mundo}/graph/relation {action: "break"} — remove the
 *  connection from the source ficha (sourcePath) to the target entity
 *  (targetId). */
export async function breakRelation(
  mundo: string,
  sourcePath: string,
  targetId: string,
): Promise<RelationResponse> {
  return setRelation(mundo, "break", sourcePath, targetId);
}

// ---------------------------------------------------------------------------
// P3 — on-demand relation sweep and its proposal queue
// ---------------------------------------------------------------------------

/** GET /api/{mundo}/relations/candidates — deterministic reviewable work. */
export async function fetchRelationCandidates(
  mundo: string,
): Promise<RelationCandidatesResponse> {
  return apiFetch<RelationCandidatesResponse>(
    apiUrl(["api", mundo, "relations", "candidates"]),
  );
}

/** POST /api/{mundo}/relations/mute — "leave as is": never a candidate again. */
export async function muteRelationCandidate(
  mundo: string,
  path: string,
): Promise<{ success: boolean; muted: boolean }> {
  return apiFetch<{ success: boolean; muted: boolean }>(
    apiUrl(["api", mundo, "relations", "mute"]),
    { method: "POST", body: JSON.stringify({ path }) },
  );
}

/** POST /api/{mundo}/relations/unmute — undo "leave as is". */
export async function unmuteRelationCandidate(
  mundo: string,
  path: string,
): Promise<{ success: boolean; muted: boolean }> {
  return apiFetch<{ success: boolean; muted: boolean }>(
    apiUrl(["api", mundo, "relations", "unmute"]),
    { method: "POST", body: JSON.stringify({ path }) },
  );
}

/**
 * POST /api/{mundo}/relations/sweep — a bounded batch, one model call.
 *
 * `size` is optional: the server defaults to 5 and clamps to 1..10, so callers
 * that omit it still get the batch behavior.
 */
/** A sweep waits on the model: one batch takes 8-20s on a real world. */
const MODEL_CALL_TIMEOUT_MS = 180_000;
/** Preview/apply walk every ficha of the world. */
const WORLD_SCAN_TIMEOUT_MS = 120_000;

export async function sweepRelations(
  mundo: string,
  size?: number,
): Promise<RelationSweepResponse> {
  return apiFetch<RelationSweepResponse>(
    apiUrl(["api", mundo, "relations", "sweep"]),
    {
      method: "POST",
      // The sweep waits on the model (8-20s on a real world), so the 5s
      // default aborted the request while the server kept working: the UI
      // reported a failure and the proposals appeared anyway.
      timeout: MODEL_CALL_TIMEOUT_MS,
      ...(size === undefined ? {} : { body: JSON.stringify({ size }) }),
    },
  );
}

/** GET /api/{mundo}/relations/proposals — the pending proposal queue. */
export async function fetchRelationProposals(
  mundo: string,
): Promise<RelationProposalsResponse> {
  return apiFetch<RelationProposalsResponse>(
    apiUrl(["api", mundo, "relations", "proposals"]),
  );
}

/** POST .../proposals/{id}/accept — write the relation. */
export async function acceptRelationProposal(
  mundo: string,
  proposalId: string,
): Promise<{ success: boolean }> {
  return apiFetch<{ success: boolean }>(
    apiUrl(["api", mundo, "relations", "proposals", proposalId, "accept"]),
    { method: "POST" },
  );
}

/** POST .../proposals/{id}/reject — remember the pair as rejected. */
export async function rejectRelationProposal(
  mundo: string,
  proposalId: string,
): Promise<{ success: boolean }> {
  return apiFetch<{ success: boolean }>(
    apiUrl(["api", mundo, "relations", "proposals", proposalId, "reject"]),
    { method: "POST" },
  );
}

// ---------------------------------------------------------------------------
// P4 — world-wide reconciliation (preview then apply with a pre-image backup)
// ---------------------------------------------------------------------------

/** GET /api/{mundo}/relations/reconcile/preview — read-only plan. */
export async function fetchRelationReconcilePreview(
  mundo: string,
): Promise<RelationReconcilePreview> {
  return apiFetch<RelationReconcilePreview>(
    apiUrl(["api", mundo, "relations", "reconcile", "preview"]),
    // Computes the plan for the whole world; a big world exceeds 5s.
    { timeout: WORLD_SCAN_TIMEOUT_MS },
  );
}

/** POST /api/{mundo}/relations/reconcile — apply after a pre-image backup. */
export async function applyRelationReconcile(
  mundo: string,
): Promise<RelationReconcileApply> {
  return apiFetch<RelationReconcileApply>(
    apiUrl(["api", mundo, "relations", "reconcile"]),
    { method: "POST", timeout: WORLD_SCAN_TIMEOUT_MS },
  );
}

/** GET /api/{mundo}/relations/quality?path= — tags for one saved ficha. */
export async function fetchRelationQuality(
  mundo: string,
  path: string,
): Promise<RelationQualityReport> {
  return apiFetch<RelationQualityReport>(
    apiUrl(["api", mundo, "relations", "quality"], { path }),
  );
}
