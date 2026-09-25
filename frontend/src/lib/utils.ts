import { ApiError, type AppLanguage } from "@/api/types";
import { readCachedLocale } from "@/hooks/useAppLocale";
import { localizeApiError } from "@/i18n/errors";
import { translate, type TFunction } from "@/i18n/messages";

/**
 * Merges class names, filtering out falsy values.
 * A lightweight alternative to clsx + tailwind-merge.
 */
export function cn(...inputs: (string | false | null | undefined)[]): string {
  return inputs.filter(Boolean).join(" ");
}

/**
 * Encodes a single path segment for use in URLs.
 * Preserves forward slashes if the segment contains them.
 */
export function encodePathSegment(segment: string): string {
  return segment
    .split("/")
    .map((s) => encodeURIComponent(s))
    .join("/");
}

/**
 * Decodes a single path segment from URL-encoded form.
 */
export function decodePathSegment(segment: string): string {
  return segment
    .split("/")
    .map((s) => decodeURIComponent(s))
    .join("/");
}

/**
 * Maps backend HTTP errors to localized user-facing copy through the message
 * catalogue (ERR-REQ-3). Code-aware first (stable backend codes such as
 * `import.job_not_found`), then status-based catalogue keys; the raw backend
 * `detail` is NEVER returned as user-facing copy (ERR-REQ-4). The language is
 * resolved synchronously from the cached locale so the module stays
 * context-free; interactive surfaces that must follow an instant language
 * switch should prefer `localizeApiError(error, t)` from the i18n barrel.
 */
export function getErrorMessage(
  status: number,
  detail?: string,
  code?: string,
  params?: Record<string, string | number>,
): string {
  const language: AppLanguage = readCachedLocale().ui === "en" ? "en" : "es";
  const t: TFunction = (key, p) => translate(language, key, p);
  return localizeApiError(
    new ApiError(status, detail ?? `HTTP ${status}`, detail, code, params),
    t,
  );
}