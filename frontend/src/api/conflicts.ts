import { apiFetch } from "@/api/client";
import { API_BASE_URL } from "@/lib/constants";

/** Severity of a deterministic conflict (S4): graph-breaking vs incomplete. */
export type ConflictSeverity = "error" | "warning";

/** Closed deterministic code set (S3). */
export type ConflictCode =
  | "version"
  | "missing-minimum"
  | "unresolved-reference"
  | "ambiguous-reference"
  | "duplicate-id"
  | "dangling-relation"
  | "self-relation"
  | "canon-state-mismatch"
  | "semantic-contradiction";

/** The Author's answer to a conflict (S10). */
export type ConflictDecisionKind = "intentional" | "muted" | "structural";

/** Where the conflict comes from: computed structure or a semantic sweep. */
export type ConflictOrigin = "deterministic" | "semantic";

/** Review state of a conflict. */
export type ConflictState = "computed" | "proposed" | "decided";

/** One conflict attached to a ficha. */
export interface WorldConflict {
  id: string;
  code: ConflictCode;
  severity: ConflictSeverity;
  path: string;
  name: string;
  message: string;
  field: string | null;
  reference: string | null;
  decision: ConflictDecisionKind | null;
  state: ConflictState;
  origin: ConflictOrigin;
  /** Both sides of a semantic contradiction (null for deterministic ones). */
  evidence_a: string | null;
  evidence_b: string | null;
  source_a: string | null;
  source_b: string | null;
}

/** Coverage of the semantic review, by current body text. */
export interface ReviewProgress {
  total: number;
  reviewed: number;
  pending: number;
}

/** Counts the panel header shows. */
export interface ConflictSummary {
  total: number;
  errors: number;
  warnings: number;
  known: number;
  muted: number;
  proposed: number;
  by_code: Partial<Record<ConflictCode, number>>;
  review: ReviewProgress;
}

/** GET /api/{mundo}/conflicts payload (S5). */
export interface ConflictsResponse {
  indexed: boolean;
  conflicts: WorldConflict[];
  summary: ConflictSummary;
}

/** Body of POST /api/{mundo}/conflicts/decision. */
export interface ConflictDecisionRequest {
  conflict_id: string;
  decision: ConflictDecisionKind | "clear";
  note?: string;
}

/**
 * GET /api/{mundo}/conflicts — deterministic, read-only, model-free.
 * An unknown world answers the soft-empty payload, never an error.
 */
export async function fetchConflicts(mundo: string): Promise<ConflictsResponse> {
  const path = `/api/${encodeURIComponent(mundo)}/conflicts`;
  return apiFetch<ConflictsResponse>(`${API_BASE_URL}${path}`);
}

/**
 * POST /api/{mundo}/conflicts/decision — records, updates or clears one
 * decision and answers the refreshed payload.
 */
export async function setConflictDecision(
  mundo: string,
  body: ConflictDecisionRequest,
): Promise<ConflictsResponse> {
  const path = `/api/${encodeURIComponent(mundo)}/conflicts/decision`;
  return apiFetch<ConflictsResponse>(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Body of POST /api/{mundo}/conflicts/sweep. */
export interface ConflictSweepRequest {
  size?: number;
}

/** Result of one semantic sweep batch. */
export interface ConflictSweepResponse {
  status: "swept" | "done" | "unavailable";
  swept: number;
  created: number;
  /** Semantic proposals waiting for the Author (not fichas left to review). */
  proposals: number;
  paths: string[];
  message: string;
}

/**
 * POST /api/{mundo}/conflicts/sweep — reviews a bounded batch of fichas with
 * the semantic provider. It only proposes; an outage marks nothing swept.
 */
export async function sweepConflicts(
  mundo: string,
  body: ConflictSweepRequest = {},
): Promise<ConflictSweepResponse> {
  const path = `/api/${encodeURIComponent(mundo)}/conflicts/sweep`;
  return apiFetch<ConflictSweepResponse>(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/**
 * POST /api/{mundo}/conflicts/proposal/reject — marks a semantic proposal as a
 * model mistake and answers the refreshed payload.
 */
export async function rejectConflictProposal(
  mundo: string,
  conflictId: string,
  note = "",
): Promise<ConflictsResponse> {
  const path = `/api/${encodeURIComponent(mundo)}/conflicts/proposal/reject`;
  return apiFetch<ConflictsResponse>(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conflict_id: conflictId, note }),
  });
}
