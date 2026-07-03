import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { apiFetch } from "@/api/client";
import { ApiError } from "@/api/types";

function mockFetch(response: {
  ok: boolean;
  status: number;
  body?: unknown;
}) {
  return vi.fn().mockResolvedValue({
    ok: response.ok,
    status: response.status,
    json: vi.fn().mockResolvedValue(response.body),
    headers: new Headers(),
  }) as unknown as typeof globalThis.fetch;
}

describe("apiFetch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("parses a successful JSON response", async () => {
    const data = { name: "vibrantes", has_lore: true };
    globalThis.fetch = mockFetch({ ok: true, status: 200, body: data });

    const result = await apiFetch<typeof data>("/api/worlds");
    expect(result).toEqual(data);
  });

  it("throws ApiError on 400 with detail", async () => {
    globalThis.fetch = mockFetch({
      ok: false,
      status: 400,
      body: { detail: "Path traversal detectado" },
    });

    await expect(apiFetch("/test")).rejects.toThrow(ApiError);
    await expect(apiFetch("/test")).rejects.toMatchObject({
      status: 400,
      message: "Path traversal detectado",
      detail: "Path traversal detectado",
    });
  });

  it("throws ApiError on 404 with detail", async () => {
    globalThis.fetch = mockFetch({
      ok: false,
      status: 404,
      body: { detail: "Archivo no encontrado" },
    });

    await expect(apiFetch("/test")).rejects.toMatchObject({
      status: 404,
      detail: "Archivo no encontrado",
    });
  });

  it("throws ApiError on 409 with detail", async () => {
    globalThis.fetch = mockFetch({
      ok: false,
      status: 409,
      body: { detail: "El archivo ya existe" },
    });

    await expect(apiFetch("/test")).rejects.toMatchObject({
      status: 409,
      detail: "El archivo ya existe",
    });
  });

  it("throws ApiError on 422 with detail", async () => {
    globalThis.fetch = mockFetch({
      ok: false,
      status: 422,
      body: { detail: "Error de encoding" },
    });

    await expect(apiFetch("/test")).rejects.toMatchObject({
      status: 422,
      detail: "Error de encoding",
    });
  });

  it("throws ApiError on 500 without detail", async () => {
    globalThis.fetch = mockFetch({ ok: false, status: 500, body: {} });

    await expect(apiFetch("/test")).rejects.toMatchObject({
      status: 500,
    });
  });

  it("throws ApiError(status: 0) on network error", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError("fetch failed")) as unknown as typeof globalThis.fetch;

    await expect(apiFetch("/test")).rejects.toMatchObject({
      status: 0,
      message: expect.stringContaining("No se pudo conectar"),
    });
  });

  it("throws ApiError(status: 0) on timeout", async () => {
    globalThis.fetch = vi.fn(
      () =>
        new Promise((_, reject) => {
          // Simulate abort by rejecting with AbortError
          const error = new DOMException("The operation was aborted", "AbortError");
          reject(error);
        }),
    ) as unknown as typeof globalThis.fetch;

    // Fake timers won't help here since the promise rejects immediately.
    // Test the timeout mechanism by checking that AbortError maps correctly.
    await expect(apiFetch("/test", { timeout: 100 })).rejects.toMatchObject({
      status: 0,
      message: "La petición tardó demasiado",
    });
  });

  it("returns undefined on 204 No Content", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: vi.fn().mockRejectedValue(new Error("no body")),
      headers: new Headers(),
    }) as unknown as typeof globalThis.fetch;

    const result = await apiFetch("/test");
    expect(result).toBeUndefined();
  });
});
