import type { ApiError } from "@/api/types";
import {
  CATALOGUE,
  type MessageKey,
  type TFunction,
  type TParams,
} from "@/i18n/messages";

/**
 * Client-side localization of backend error codes (AD-4, ERR-REQ-2).
 *
 * The backend emits `{detail, code, params}`; the UI never renders the raw
 * `detail` (ERR-REQ-3/ERR-REQ-4). Known codes resolve through the message
 * catalogue with their structured params filled in by the active language's
 * `t`; unknown codes fall back to a status-based catalogue key, and a bare
 * status-0 transport failure falls back to the network copy. Every path
 * lands on localized catalogue copy — never on a raw backend string.
 */

const CODE_PREFIX = "error.";

/** `"import.job_not_found"` → `"error.import.job_not_found"`, or null when the
 *  catalogue does not define the code (unknown code → safe fallback). */
export function errorKey(code: string): MessageKey | null {
  const key = `${CODE_PREFIX}${code}`;
  return key in CATALOGUE.es ? (key as MessageKey) : null;
}

/** Status-based catalogue fallback for errors without a known code. */
const STATUS_FALLBACK: Record<number, MessageKey> = {
  400: "error.status.400",
  401: "error.status.401",
  403: "error.status.403",
  404: "error.status.404",
  409: "error.status.409",
  422: "error.status.422",
  500: "error.status.500",
};

/** Resolve a structured backend error into localized user-facing copy. */
export function localizeApiError(error: ApiError, t: TFunction): string {
  if (typeof error.code === "string" && error.code.length > 0) {
    const key = errorKey(error.code);
    if (key) return t(key, error.params);
  }
  if (error.status === 0) return t("error.network.unreachable");
  const statusKey = STATUS_FALLBACK[error.status];
  if (statusKey) return t(statusKey);
  return t("error.unknown");
}

/** Convenience for callers that hold a bare code + params (not an ApiError). */
export function localizeErrorCode(
  code: string | undefined,
  status: number,
  params: TParams | undefined,
  t: TFunction,
): string {
  if (typeof code === "string" && code.length > 0) {
    const key = errorKey(code);
    if (key) return t(key, params);
  }
  if (status === 0) return t("error.network.unreachable");
  const statusKey = STATUS_FALLBACK[status];
  if (statusKey) return t(statusKey);
  return t("error.unknown");
}