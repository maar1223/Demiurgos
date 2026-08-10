import { ApiError } from "@/api/types";

const DEFAULT_TIMEOUT_MS = 5_000;

/**
 * Base fetch wrapper with timeout, JSON parsing, and typed error handling.
 *
 * - Adds `Content-Type: application/json` by default.
 * - On HTTP errors (4xx/5xx), parses `{detail}` from FastAPI and throws `ApiError`.
 * - On network error, throws `ApiError(status: 0)`.
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
      throw new ApiError(0, "La petición tardó demasiado");
    }

    // Network error (server down, DNS failure, etc.)
    throw new ApiError(
      0,
      "No se pudo conectar al servidor. Verificá que esté corriendo.",
    );
  }
}
