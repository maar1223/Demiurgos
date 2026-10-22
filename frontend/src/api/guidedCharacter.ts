import { apiFetch } from "@/api/client";
import type {
  EditProposal,
  GuidedCharacterSession,
  SemanticDecisionEnvelope,
} from "@/api/types";

const GUIDED_CHARACTER_TIMEOUT_MS = 35_000;

function url(world: string, suffix = ""): string {
  return `/api/${encodeURIComponent(world)}/guided${suffix}`;
}

/** Per-session guided method (S6). `skill_id: "factory"` selects the builtin
 *  contract; any other id carries the exact published version. */
export interface GuidedMethodChoice {
  skill_id: string;
  version?: string;
}

function methodPayload(method?: GuidedMethodChoice): Record<string, string> {
  if (!method) return {};
  const payload: Record<string, string> = { method_skill_id: method.skill_id };
  if (method.version) payload.method_version = method.version;
  return payload;
}

export function recoverGuidedCharacter(
  world: string,
  sessionId: string,
): Promise<GuidedCharacterSession> {
  return apiFetch<GuidedCharacterSession>(url(world, `/session/${encodeURIComponent(sessionId)}`), {
    timeout: GUIDED_CHARACTER_TIMEOUT_MS,
  });
}

export function startGuidedFlow(
  world: string,
  authorInput: string,
  flowId = "guided-character",
  method?: GuidedMethodChoice,
): Promise<GuidedCharacterSession> {
  return apiFetch<GuidedCharacterSession>(url(world, "/session"), {
    method: "POST",
    body: JSON.stringify({
      author_input: authorInput,
      flow_id: flowId,
      ...methodPayload(method),
    }),
    timeout: GUIDED_CHARACTER_TIMEOUT_MS,
  });
}

/** Character-flow convenience wrapper over `startGuidedFlow`. */
export function startGuidedCharacter(
  world: string,
  authorInput: string,
  method?: GuidedMethodChoice,
): Promise<GuidedCharacterSession> {
  return startGuidedFlow(world, authorInput, "guided-character", method);
}

export function continueGuidedCharacter(
  world: string,
  sessionId: string,
  baseRevision: number,
  authorInput: string,
): Promise<GuidedCharacterSession> {
  return apiFetch<GuidedCharacterSession>(url(world, "/turn"), {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, base_revision: baseRevision, author_input: authorInput }),
    timeout: GUIDED_CHARACTER_TIMEOUT_MS,
  });
}

export function acceptGuidedCharacterProposal(
  world: string,
  sessionId: string,
  baseRevision: number,
  key: string,
): Promise<GuidedCharacterSession> {
  return apiFetch<GuidedCharacterSession>(url(world, "/proposal/accept"), {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, base_revision: baseRevision, key }),
    timeout: GUIDED_CHARACTER_TIMEOUT_MS,
  });
}

export function serializeGuidedCharacter(
  world: string,
  sessionId: string,
  baseRevision: number,
): Promise<EditProposal> {
  return apiFetch<EditProposal>(url(world, "/proposal/serialize"), {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, base_revision: baseRevision }),
    timeout: GUIDED_CHARACTER_TIMEOUT_MS,
  });
}

export function rejectGuidedCharacterProposal(
  world: string,
  sessionId: string,
  baseRevision: number,
  key: string,
): Promise<GuidedCharacterSession> {
  return apiFetch<GuidedCharacterSession>(url(world, "/proposal/reject"), {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, base_revision: baseRevision, key }),
    timeout: GUIDED_CHARACTER_TIMEOUT_MS,
  });
}

export function retryGuidedCharacterIndex(
  world: string,
  sessionId: string,
  baseRevision: number,
): Promise<GuidedCharacterSession> {
  return apiFetch<GuidedCharacterSession>(url(world, "/index/retry"), {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, base_revision: baseRevision }),
    timeout: GUIDED_CHARACTER_TIMEOUT_MS,
  });
}

/**
 * Consume a one-shot consent token and open the deferred guided flow. The
 * click IS the imperative: the server replays the token-bound continuation
 * with no second Hermes run. Expired/replayed/foreign tokens fail closed.
 *
 * The server answers with a semantic decision envelope whose bare guided
 * session lives in `guided_state`; callers must unwrap it (see
 * `resolveGuidedConsent`). This endpoint never returns the bare session
 * directly.
 */
export function acceptGuidedConsent(
  world: string,
  token: string,
  method?: GuidedMethodChoice,
  flowId?: string,
): Promise<SemanticDecisionEnvelope> {
  return apiFetch<SemanticDecisionEnvelope>(url(world, "/consent/accept"), {
    method: "POST",
    body: JSON.stringify({
      token,
      ...(flowId ? { flow_id: flowId } : {}),
      ...methodPayload(method),
    }),
    timeout: GUIDED_CHARACTER_TIMEOUT_MS,
  });
}

/** Consume a consent token and persist a durable per-session decline. */
export function declineGuidedConsent(world: string, token: string): Promise<{ consent: string }> {
  return apiFetch<{ consent: string }>(url(world, "/consent/decline"), {
    method: "POST",
    body: JSON.stringify({ token }),
    timeout: GUIDED_CHARACTER_TIMEOUT_MS,
  });
}
