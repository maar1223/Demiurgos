import { apiFetch } from "@/api/client";
import { ApiError } from "@/api/types";
import type {
  ImportResult,
  MethodologyActivation,
  MethodologyCompanion,
  MethodologyDraft,
  MethodologyDraftInput,
  MethodologyInventoryItem,
  MethodologyStatus,
  PublishedMethodology,
  QuarantineRecord,
  TrustQuarantineResult,
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

/** Conjunctive filters for GET /api/methodologies/inventory (TW7). */
export interface InventoryFilters {
  clasificacion?: string;
  categoria_funcional?: string;
  taller?: string;
  /** Comma-separated tags; all of them must match. */
  etiquetas?: string;
  /** Only server-seeded foundational skills (trust attribute). */
  fundacional?: boolean;
}

/** GET /api/methodologies/inventory — read-only catalog of all loaded skills
 *  (activated or not), filtered conjunctively when filters are provided. */
export function getMethodologyInventory(
  filters?: InventoryFilters,
): Promise<{ items: MethodologyInventoryItem[] }> {
  const params = new URLSearchParams();
  if (filters?.clasificacion) params.set("clasificacion", filters.clasificacion);
  if (filters?.categoria_funcional) params.set("categoria_funcional", filters.categoria_funcional);
  if (filters?.taller) params.set("taller", filters.taller);
  if (filters?.etiquetas) params.set("etiquetas", filters.etiquetas);
  if (filters?.fundacional) params.set("fundacional", "true");
  const query = params.toString();
  return apiFetch<{ items: MethodologyInventoryItem[] }>(
    url(`/inventory${query ? `?${query}` : ""}`),
    { timeout: METHODOLOGIES_TIMEOUT_MS },
  );
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

/** POST /api/methodologies/deactivate — clear the world's activation slot
 *  (idempotent: an already-empty slot echoes the same cleared payload). */
export function deactivateMethodology(
  world: string,
): Promise<{ world: string; flow_type: string }> {
  return apiFetch<{ world: string; flow_type: string }>(url("/deactivate"), {
    method: "POST",
    body: JSON.stringify({ world }),
    timeout: METHODOLOGIES_TIMEOUT_MS,
  });
}

/** POST /api/methodologies/companions/activate — pin a published version as
 *  a companion of a world (several per world; the activation slot is
 *  untouched). */
export function activateCompanion(
  world: string,
  skillId: string,
  version: string,
): Promise<{ world: string; companion: MethodologyCompanion }> {
  return apiFetch<{ world: string; companion: MethodologyCompanion }>(
    url("/companions/activate"),
    {
      method: "POST",
      body: JSON.stringify({ world, skill_id: skillId, version }),
      timeout: METHODOLOGIES_TIMEOUT_MS,
    },
  );
}

/** POST /api/methodologies/companions/deactivate — remove a companion
 *  (idempotent: an unknown companion resolves to `removed: false`). */
export function deactivateCompanion(
  world: string,
  skillId: string,
): Promise<{ world: string; removed: boolean }> {
  return apiFetch<{ world: string; removed: boolean }>(
    url("/companions/deactivate"),
    {
      method: "POST",
      body: JSON.stringify({ world, skill_id: skillId }),
      timeout: METHODOLOGIES_TIMEOUT_MS,
    },
  );
}

// ---------------------------------------------------------------------------
// Skill transfer (Fase 5b, REQ-IMP-1..4): export → import → quarantine → trust
//
// These routes are NOT JSON-request/JSON-response like the rest of the API:
// export streams a `.zip` and import consumes multipart, so they use the
// `rawFetch` helper below (same timeout + ApiError semantics as `apiFetch`,
// but the caller decides how to read the response).
// ---------------------------------------------------------------------------

/** Minimal fetch wrapper for non-JSON bodies (multipart import, zip export).
 *  Mirrors `apiFetch` error semantics: 4xx/5xx parse `{detail, code}` into an
 *  `ApiError`; network failures and timeouts map to `ApiError(status: 0)`. */
async function rawFetch(
  url: string,
  options: RequestInit & { timeout?: number },
): Promise<Response> {
  const { timeout = METHODOLOGIES_TIMEOUT_MS, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, {
      ...fetchOptions,
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
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
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(0, "La petición tardó demasiado");
    }
    throw new ApiError(
      0,
      "No se pudo conectar al servidor. Verificá que esté corriendo.",
    );
  }
}

/** POST /api/methodologies/published/{skillId}/{version}/export — download the
 *  published version as a `.zip` methodology package (REQ-IMP-1). */
export async function exportPublished(
  skillId: string,
  version: string,
): Promise<Blob> {
  const response = await rawFetch(
    url(`/published/${encodeURIComponent(skillId)}/${encodeURIComponent(version)}/export`),
    { method: "POST", timeout: METHODOLOGIES_TIMEOUT_MS },
  );
  return response.blob();
}

/** POST /api/methodologies/import — upload a `.zip` package into mandatory
 *  quarantine (REQ-IMP-2). The library is never mutated by import; the
 *  Author must explicitly trust the package (REQ-IMP-4) to make it an
 *  editable draft. */
export async function importPackage(
  file: File,
  origin = "community",
): Promise<ImportResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("origin", origin);
  const response = await rawFetch(url("/import"), {
    method: "POST",
    body: form,
    timeout: METHODOLOGIES_TIMEOUT_MS,
  });
  return (await response.json()) as ImportResult;
}

/** GET /api/methodologies/quarantine — list quarantined imports with fresh
 *  re-inspected verdicts (REQ-IMP-3). */
export async function listQuarantine(): Promise<{
  entries: QuarantineRecord[];
}> {
  return apiFetch<{ entries: QuarantineRecord[] }>(url("/quarantine"), {
    timeout: METHODOLOGIES_TIMEOUT_MS,
  });
}

/** POST /api/methodologies/quarantine/{packageId}/trust — trust a quarantined
 *  package, promoting it to an editable draft (REQ-IMP-4). Fails closed (422)
 *  when the package no longer re-validates and rejects the reserved Skill
 *  Madre id with 409 (REQ-IMP-6). */
export async function trustQuarantine(
  packageId: string,
): Promise<TrustQuarantineResult> {
  return apiFetch<TrustQuarantineResult>(
    url(`/quarantine/${encodeURIComponent(packageId)}/trust`),
    {
      method: "POST",
      timeout: METHODOLOGIES_TIMEOUT_MS,
    },
  );
}
