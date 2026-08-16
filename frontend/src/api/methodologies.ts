import { apiFetch } from "@/api/client";
import type {
  MethodologyActivation,
  MethodologyDraft,
  MethodologyDraftInput,
  MethodologyStatus,
  PublishedMethodology,
} from "@/api/types";

const METHODOLOGIES_TIMEOUT_MS = 15_000;

function url(suffix = ""): string {
  return `/api/methodologies${suffix}`;
}

/** GET /api/methodologies/status — published versions, activations, drafts. */
export function getMethodologyStatus(): Promise<MethodologyStatus> {
  return apiFetch<MethodologyStatus>(url("/status"), {
    timeout: METHODOLOGIES_TIMEOUT_MS,
  });
}

/** POST /api/methodologies/drafts — create an editable methodology draft. */
export function createMethodologyDraft(
  input: MethodologyDraftInput,
): Promise<MethodologyDraft> {
  return apiFetch<MethodologyDraft>(url("/drafts"), {
    method: "POST",
    body: JSON.stringify(input),
    timeout: METHODOLOGIES_TIMEOUT_MS,
  });
}

/** POST /api/methodologies/drafts/{draftId}/publish — compile + publish. */
export function publishMethodologyDraft(
  draftId: string,
): Promise<PublishedMethodology> {
  return apiFetch<PublishedMethodology>(
    url(`/drafts/${encodeURIComponent(draftId)}/publish`),
    {
      method: "POST",
      timeout: METHODOLOGIES_TIMEOUT_MS,
    },
  );
}

/** POST /api/methodologies/activate — pin a version to a world. */
export function activateMethodology(
  world: string,
  skillId: string,
  version: string,
): Promise<MethodologyActivation> {
  return apiFetch<MethodologyActivation>(url("/activate"), {
    method: "POST",
    body: JSON.stringify({ world, skill_id: skillId, version }),
    timeout: METHODOLOGIES_TIMEOUT_MS,
  });
}

/** POST /api/methodologies/rollback — restore the previous version for a world. */
export function rollbackMethodology(
  world: string,
): Promise<MethodologyActivation | null> {
  return apiFetch<MethodologyActivation | null>(url("/rollback"), {
    method: "POST",
    body: JSON.stringify({ world }),
    timeout: METHODOLOGIES_TIMEOUT_MS,
  });
}
