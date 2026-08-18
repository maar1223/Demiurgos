import { apiFetch } from "@/api/client";
import type {
  LocaleInput,
  OnboardingStatus,
  ReadinessSnapshot,
  WorldCreateResult,
} from "@/api/types";
import { API_BASE_URL } from "@/lib/constants";

/**
 * First-run onboarding + Configuration Center API (Slice 1).
 *
 * Reads are non-sensitive (onboarding progress, locale, readiness). Writes
 * (step0, world creation) are gated server-side on the authenticated local
 * principal and fail closed with 401 when no session exists.
 */

/** GET /api/onboarding/status — first-run gate state. */
export function getOnboardingStatus(): Promise<OnboardingStatus> {
  return apiFetch<OnboardingStatus>(`${API_BASE_URL}/api/onboarding/status`);
}

/** POST /api/onboarding/step0 — persist G7/OC3 locale. */
export function submitStep0(locale: LocaleInput): Promise<OnboardingStatus> {
  return apiFetch<OnboardingStatus>(`${API_BASE_URL}/api/onboarding/step0`, {
    method: "POST",
    body: JSON.stringify(locale),
  });
}

/** POST /api/worlds — create a canonical new world. */
export function createWorld(
  name: string,
  loreSkeleton: boolean,
): Promise<WorldCreateResult> {
  return apiFetch<WorldCreateResult>(`${API_BASE_URL}/api/worlds`, {
    method: "POST",
    body: JSON.stringify({ name, lore_skeleton: loreSkeleton }),
  });
}

/** GET /api/onboarding/readiness — essential local readiness + card states. */
export function getReadiness(): Promise<ReadinessSnapshot> {
  return apiFetch<ReadinessSnapshot>(`${API_BASE_URL}/api/onboarding/readiness`);
}