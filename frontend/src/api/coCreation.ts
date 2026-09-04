import { apiFetch } from "@/api/client";
import type {
  CoCreationActivateResult,
  CoCreationMaterializeMetadata,
  CoCreationMaterializeResult,
  CoCreationProgress,
  CoCreationPublishResult,
  CoCreationSession,
} from "@/api/types";

const CO_CREATION_TIMEOUT_MS = 35_000;

function url(suffix = ""): string {
  return `/api/co-creation${suffix}`;
}

/** POST /api/co-creation/sessions — create a principal-bound session and run
 *  the first Skill Madre turn immediately. `world` binds the session to that
 *  world (world-specific scope); omitting it creates a transversal session. */
export function createCoCreationSession(
  authorInput: string,
  world?: string | null,
): Promise<CoCreationSession> {
  return apiFetch<CoCreationSession>(url("/sessions"), {
    method: "POST",
    body: JSON.stringify({
      author_input: authorInput,
      ...(world ? { world } : {}),
    }),
    timeout: CO_CREATION_TIMEOUT_MS,
  });
}

/** POST /api/co-creation/sessions/{id}/turn — one Author answer, one Skill
 *  Madre question (REQ-CC-3). The base_revision guards against stale writes. */
export function turnCoCreationSession(
  sessionId: string,
  baseRevision: number,
  authorInput: string,
): Promise<CoCreationSession> {
  return apiFetch<CoCreationSession>(
    url(`/sessions/${encodeURIComponent(sessionId)}/turn`),
    {
      method: "POST",
      body: JSON.stringify({ base_revision: baseRevision, author_input: authorInput }),
      timeout: CO_CREATION_TIMEOUT_MS,
    },
  );
}

/** GET /api/co-creation/sessions/{id} — recover a principal-bound session
 *  (the backend is authoritative; localStorage is only a hint). */
export function recoverCoCreationSession(
  sessionId: string,
): Promise<CoCreationSession> {
  return apiFetch<CoCreationSession>(
    url(`/sessions/${encodeURIComponent(sessionId)}`),
    { timeout: CO_CREATION_TIMEOUT_MS },
  );
}

/** GET /api/co-creation/sessions/{id}/progress — milestone progress projection. */
export function coCreationProgress(
  sessionId: string,
): Promise<CoCreationProgress> {
  return apiFetch<CoCreationProgress>(
    url(`/sessions/${encodeURIComponent(sessionId)}/progress`),
    { timeout: CO_CREATION_TIMEOUT_MS },
  );
}

/** POST /api/co-creation/sessions/{id}/materialize — Author confirms Borrador
 *  listo; the backend assembles the draft deterministically and compiles it.
 *  Compiler issues surface in the response; this call NEVER publishes. */
export function materializeCoCreationSession(
  sessionId: string,
  baseRevision: number,
  metadata?: CoCreationMaterializeMetadata,
): Promise<CoCreationMaterializeResult> {
  return apiFetch<CoCreationMaterializeResult>(
    url(`/sessions/${encodeURIComponent(sessionId)}/materialize`),
    {
      method: "POST",
      body: JSON.stringify({ base_revision: baseRevision, ...metadata }),
      timeout: CO_CREATION_TIMEOUT_MS,
    },
  );
}

/** POST /api/co-creation/sessions/{id}/publish — the POST itself is the
 *  Author's explicit approval; publishing is immutable (REQ-CC-6). */
export function publishCoCreationSession(
  sessionId: string,
  baseRevision: number,
): Promise<CoCreationPublishResult> {
  return apiFetch<CoCreationPublishResult>(
    url(`/sessions/${encodeURIComponent(sessionId)}/publish`),
    {
      method: "POST",
      body: JSON.stringify({ base_revision: baseRevision }),
      timeout: CO_CREATION_TIMEOUT_MS,
    },
  );
}

/** POST /api/co-creation/sessions/{id}/activate — pin the published version
 *  to a world (one active version per world). Requires a PUBLISHED version;
 *  this route never auto-publishes. */
export function activateCoCreationSession(
  sessionId: string,
  baseRevision: number,
  world: string,
): Promise<CoCreationActivateResult> {
  return apiFetch<CoCreationActivateResult>(
    url(`/sessions/${encodeURIComponent(sessionId)}/activate`),
    {
      method: "POST",
      body: JSON.stringify({ base_revision: baseRevision, world }),
      timeout: CO_CREATION_TIMEOUT_MS,
    },
  );
}