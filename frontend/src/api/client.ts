import { ApiError } from "@/api/types";

const DEFAULT_TIMEOUT_MS = 5_000;

/** Stable codes for transport-level failures (AD-4, ERR-REQ-3). */
const NETWORK_UNREACHABLE_CODE = "network.unreachable";
const NETWORK_TIMEOUT_CODE = "network.timeout";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Parse the structured error body `{detail, code, params}` (AD-5) into an
 * `ApiError`. `detail` stays available for logging; the UI never renders it.
 */
function parseErrorBody(body: unknown): {
  detail?: string;
  code?: string;
  params?: Record<string, string | number>;
} {
  if (!isRecord(body)) return {};
  const detail = typeof body.detail === "string" ? body.detail : undefined;
  const code = typeof body.code === "string" && body.code.length > 0 ? body.code : undefined;
  let params: Record<string, string | number> | undefined;
  if (isRecord(body.params)) {
    const cleaned: Record<string, string | number> = {};
    for (const [key, value] of Object.entries(body.params)) {
      if (typeof value === "string" || typeof value === "number") {
        cleaned[key] = value;
      }
    }
    if (Object.keys(cleaned).length > 0) params = cleaned;
  }
  return { detail, code, params };
}

/**
 * Base fetch wrapper with timeout, JSON parsing, and typed error handling.
 *
 * - Adds `Content-Type: application/json` by default.
 * - On HTTP errors (4xx/5xx), parses `{detail, code, params}` from FastAPI
 *   and throws `ApiError`.
 * - On network error, throws `ApiError(status: 0, code: "network.unreachable")`.
 * - On timeout, throws `ApiError(status: 0, code: "network.timeout")`.
 * - Uses AbortController for timeout.
 */
export async function apiFetch<T>(
  url: string,
  options?: RequestInit & { timeout?: number },
): Promise<T> {
  const { timeout = DEFAULT_TIMEOUT_MS, ...fetchOptions } = options ?? {};

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url, {
      ...fetchOptions,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...fetchOptions.headers,
      },
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      let body: unknown;
      try {
        body = await response.json();
      } catch {
        // ignore parse errors on error responses
      }
      const { detail, code, params } = parseErrorBody(body);

      throw new ApiError(
        response.status,
        detail ?? `HTTP ${response.status}`,
        detail,
        code,
        params,
      );
    }

    // Handle 204 No Content
    if (response.status === 204) {
      return undefined as T;
    }

    return (await response.json()) as T;
  } catch (error) {
    clearTimeout(timeoutId);

    if (error instanceof ApiError) {
      throw error;
    }

    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(0, "La petición tardó demasiado", undefined, NETWORK_TIMEOUT_CODE);
    }

    // Network error (server down, DNS failure, etc.)
    throw new ApiError(
      0,
      "No se pudo conectar al servidor. Verifica que esté corriendo.",
      undefined,
      NETWORK_UNREACHABLE_CODE,
    );
  }
}