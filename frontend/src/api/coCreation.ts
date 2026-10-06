import { apiFetch } from "@/api/client";
import { ApiError } from "@/api/types";
import type {
  CoCreationActivateResult,
  CoCreationCanvasResult,
  CoCreationDeriveResult,
  CoCreationHistoryList,
  CoCreationMaterializeMetadata,
  CoCreationMaterializeResult,
  CoCreationPendingQuestionList,
  CoCreationProgress,
  CoCreationPublishResult,
  CoCreationRestoreResult,
  CoCreationSession,
  CoCreationValidationResult,
  CoCreationWarningList,
  DraftPayload,
  MethodologyAdjunto,
  PublishedMethodologyDetail,
  TriggerApproval,
  WarningState,
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

/** POST /api/co-creation/sessions/{id}/trigger/approve — record the Author's
 *  explicit approval of the session trigger (Etapa 2). The server validates the
 *  bound BEFORE mutating (server-authoritative), writes the approved value into
 *  the session canvas, and — when a draft is materialized — records the approval
 *  on the library draft so the approved value equals the value publish will use. */
export function approveSessionTrigger(
  sessionId: string,
  baseRevision: number,
  description: string,
): Promise<{ trigger_approval: TriggerApproval | null; revision: number }> {
  return apiFetch<{
    trigger_approval: TriggerApproval | null;
    revision: number;
  }>(url(`/sessions/${encodeURIComponent(sessionId)}/trigger/approve`), {
    method: "POST",
    body: JSON.stringify({ base_revision: baseRevision, description }),
    timeout: CO_CREATION_TIMEOUT_MS,
  });
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

// ---------------------------------------------------------------------------
// TW12 canvas data layer — structured draft editing (REQ-CC-11/13/14/15)
// ---------------------------------------------------------------------------

/** PUT /api/co-creation/sessions/{id}/canvas — debounced Author canvas
 *  autosave (REQ-CC-11). The envelope keys (`base_revision`/`payload`) stay
 *  OUTSIDE the 8-key authority set (REQ-CC-23); authority keys inside the
 *  payload are rejected server-side with zero state changes (REQ-CC-7). The
 *  payload NEVER carries `derived_from` or any authority key — it is
 *  Author-originated structured content only. */
export function updateCanvas(
  sessionId: string,
  baseRevision: number,
  payload: DraftPayload,
): Promise<CoCreationCanvasResult> {
  return apiFetch<CoCreationCanvasResult>(
    url(`/sessions/${encodeURIComponent(sessionId)}/canvas`),
    {
      method: "PUT",
      body: JSON.stringify({ base_revision: baseRevision, payload }),
      timeout: CO_CREATION_TIMEOUT_MS,
    },
  );
}

/** POST /api/co-creation/sessions/{id}/validate — pure render+compile preview.
 *  Returns compiler issues, a fresh Pendiente warning projection, and the
 *  rendered source. NEVER creates or publishes anything (REQ-CC-13). */
export function validatePayload(
  sessionId: string,
  payload: DraftPayload,
): Promise<CoCreationValidationResult> {
  return apiFetch<CoCreationValidationResult>(
    url(`/sessions/${encodeURIComponent(sessionId)}/validate`),
    {
      method: "POST",
      body: JSON.stringify({ payload }),
      timeout: CO_CREATION_TIMEOUT_MS,
    },
  );
}

/** GET /api/co-creation/sessions/{id}/history — immutable autosave snapshots
 *  (REQ-CC-15). Payloads are excluded from the list; restore returns them. */
export function listHistory(
  sessionId: string,
): Promise<CoCreationHistoryList> {
  return apiFetch<CoCreationHistoryList>(
    url(`/sessions/${encodeURIComponent(sessionId)}/history`),
    { timeout: CO_CREATION_TIMEOUT_MS },
  );
}

/** POST /api/co-creation/sessions/{id}/history/restore — revision-guarded
 *  snapshot restore (REQ-CC-15). Fails closed (REVISION_CONFLICT) when the
 *  session's current revision does not match `base_revision`. */
export function restoreHistory(
  sessionId: string,
  baseRevision: number,
  revision: number,
): Promise<CoCreationRestoreResult> {
  return apiFetch<CoCreationRestoreResult>(
    url(`/sessions/${encodeURIComponent(sessionId)}/history/restore`),
    {
      method: "POST",
      body: JSON.stringify({ base_revision: baseRevision, revision }),
      timeout: CO_CREATION_TIMEOUT_MS,
    },
  );
}

/** POST /api/co-creation/sessions/{id}/warnings/{idx}/status — Author-only
 *  warning transition (REQ-CC-13): only `Pendiente -> Resuelta |
 *  Aceptada_por_Autor`. Pending warnings never auto-clear. */
export function setWarningStatus(
  sessionId: string,
  baseRevision: number,
  idx: number,
  state: WarningState,
): Promise<CoCreationWarningList> {
  return apiFetch<CoCreationWarningList>(
    url(`/sessions/${encodeURIComponent(sessionId)}/warnings/${idx}/status`),
    {
      method: "POST",
      body: JSON.stringify({ base_revision: baseRevision, state }),
      timeout: CO_CREATION_TIMEOUT_MS,
    },
  );
}

/** POST /api/co-creation/sessions/{id}/pending-questions/{idx}/status —
 *  Author-only pending-question transition (REQ-CC-14): entries are
 *  chat-appended and read-only on the canvas; only the Author transitions
 *  `Pendiente -> Resuelta | Aceptada_por_Autor`. */
export function setPendingQuestionStatus(
  sessionId: string,
  baseRevision: number,
  idx: number,
  state: WarningState,
): Promise<CoCreationPendingQuestionList> {
  return apiFetch<CoCreationPendingQuestionList>(
    url(
      `/sessions/${encodeURIComponent(sessionId)}/pending-questions/${idx}/status`,
    ),
    {
      method: "POST",
      body: JSON.stringify({ base_revision: baseRevision, state }),
      timeout: CO_CREATION_TIMEOUT_MS,
    },
  );
}

// ---------------------------------------------------------------------------
// TW13/TW14 — adaptation + provenance
// ---------------------------------------------------------------------------

/** GET /api/methodologies/published/{skill_id}/{version} — full published
 *  version + source (auth-required) for the TW13 adaptation compare. Also
 *  exposes the TW14 provenance (`parent_skill_id`/`parent_version`) when the
 *  version is itself a derived publish (REQ-CC-21). */
export function getPublishedDetail(
  skillId: string,
  version: string,
): Promise<PublishedMethodologyDetail> {
  return apiFetch<PublishedMethodologyDetail>(
    `/api/methodologies/published/${encodeURIComponent(skillId)}/${encodeURIComponent(version)}`,
    { timeout: CO_CREATION_TIMEOUT_MS },
  );
}

/** POST /api/co-creation/derive — derive an adaptation draft from a PUBLISHED
 *  skill (TW13). The client sends ONLY the original identity
 *  (`skill_id`/`version`/`world`); the server reads the PUBLISHED record,
 *  injects provenance (REQ-CC-20, client-supplied `derived_from` ignored),
 *  and opens the adaptation session bound to the derived draft (REQ-CC-17).
 *  `clasificacion="Oficiales"` originals REQUIRE this path (REQ-CC-16). */
export function deriveDraft(
  skillId: string,
  version: string,
  world?: string | null,
): Promise<CoCreationDeriveResult> {
  return apiFetch<CoCreationDeriveResult>(url("/derive"), {
    method: "POST",
    body: JSON.stringify({
      skill_id: skillId,
      version,
      ...(world ? { world } : {}),
    }),
    timeout: CO_CREATION_TIMEOUT_MS,
  });
}

// ---------------------------------------------------------------------------
// S3 — exemplar staging (AE-1 / REQ-CC-25)
// ---------------------------------------------------------------------------

/** POST /api/co-creation/sessions/{id}/adjuntos — stage ONE exemplar for a
 *  principal-owned session. Multipart `file` + `nivel`; the server computes
 *  `sha256`/`bytes` and returns the pin `{path, sha256, bytes, nivel}`. Bytes
 *  stay in the per-session staging dir until materialize moves them.
 *
 *  Uses raw `fetch` on purpose: `apiFetch` sets a JSON content-type that
 *  breaks the multipart boundary (same pattern as `attachIdeaMedia` in
 *  `@/api/ideas`). Error semantics mirror `apiFetch`: 4xx/5xx parse
 *  `{detail, code}` into an `ApiError`. */
export async function uploadCoCreationAdjunto(
  sessionId: string,
  file: File,
  nivel: string,
): Promise<MethodologyAdjunto> {
  const form = new FormData();
  form.append("file", file);
  form.append("nivel", nivel);

  const response = await fetch(
    url(`/sessions/${encodeURIComponent(sessionId)}/adjuntos`),
    { method: "POST", body: form, credentials: "same-origin" },
  );

  if (!response.ok) {
    let detail: string | undefined;
    let code: string | undefined;
    try {
      const body = await response.json();
      detail = body.detail;
      if (typeof body.code === "string") {
        code = body.code;
      }
    } catch {
      // ignore parse errors on error responses
    }
    throw new ApiError(
      response.status,
      detail ?? `HTTP ${response.status}`,
      detail,
      code,
    );
  }

  const body = (await response.json()) as { adjunto: MethodologyAdjunto };
  return body.adjunto;
}