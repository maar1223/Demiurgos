import { apiFetch } from "@/api/client";
import type { GuidedCharacterSession } from "@/api/types";

function url(world: string, suffix = ""): string {
  return `/api/${encodeURIComponent(world)}/guided-character${suffix}`;
}

export function recoverGuidedCharacter(
  world: string,
  sessionId: string,
): Promise<GuidedCharacterSession> {
  return apiFetch<GuidedCharacterSession>(url(world, `/session/${encodeURIComponent(sessionId)}`));
}

export function startGuidedCharacter(
  world: string,
  authorInput: string,
): Promise<GuidedCharacterSession> {
  return apiFetch<GuidedCharacterSession>(url(world, "/session"), {
    method: "POST",
    body: JSON.stringify({ author_input: authorInput }),
  });
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
  });
}
