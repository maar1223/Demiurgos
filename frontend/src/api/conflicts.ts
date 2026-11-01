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
  | "canon-state-mismatch";

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
}

/** Counts the panel header shows. */
export interface ConflictSummary {
  total: number;
  errors: number;
  warnings: number;
  by_code: Partial<Record<ConflictCode, number>>;
}

/** GET /api/{mundo}/conflicts payload (S5). */
export interface ConflictsResponse {
  indexed: boolean;
  conflicts: WorldConflict[];
  summary: ConflictSummary;
}

/**
 * GET /api/{mundo}/conflicts — deterministic, read-only, model-free.
 * An unknown world answers the soft-empty payload, never an error.
 */
export async function fetchConflicts(mundo: string): Promise<ConflictsResponse> {
  const path = `/api/${encodeURIComponent(mundo)}/conflicts`;
  return apiFetch<ConflictsResponse>(`${API_BASE_URL}${path}`);
}
