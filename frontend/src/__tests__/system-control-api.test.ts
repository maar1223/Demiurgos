import { afterEach, describe, expect, it, vi } from "vitest";
import { systemControlAction } from "@/api/wiki";

/**
 * System-control API contract (system-control slice 3, PR 3): POST to
 * /api/system/{action} with same-origin credentials and an explicit long
 * timeout (≥90s) instead of the apiFetch 5s default.
 */

function mockResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
    headers: new Headers(),
  };
}

describe("system control API", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("POSTs restart to /api/system/restart with same-origin credentials", async () => {
    const body = { action: "restart", accepted: true };
    const fetchMock = vi.fn().mockResolvedValue(mockResponse(body));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await systemControlAction("restart");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/system/restart",
      expect.objectContaining({ method: "POST", credentials: "same-origin" }),
    );
    expect(result).toEqual(body);
  });

  it("POSTs shutdown to /api/system/shutdown with same-origin credentials", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(mockResponse({ action: "shutdown", accepted: true }));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await systemControlAction("shutdown");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/system/shutdown",
      expect.objectContaining({ method: "POST", credentials: "same-origin" }),
    );
  });

  it("uses an explicit ≥90s timeout instead of the 5s default (S-3.5)", async () => {
    vi.useFakeTimers();
    let signal: AbortSignal | null | undefined;
    const fetchMock = vi.fn((_url: string, opts?: RequestInit) => {
      signal = opts?.signal;
      return new Promise((_resolve, reject) => {
        signal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      });
    });
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const promise = systemControlAction("restart");
    // Attach the rejection handler FIRST so the abort-triggered rejection is
    // never left unhandled while we advance the fake timers.
    const rejection = expect(promise).rejects.toMatchObject({ status: 0 });

    // At the apiFetch default (5s) the request must still be alive…
    await vi.advanceTimersByTimeAsync(5_000);
    expect(signal?.aborted).toBe(false);

    // …and only aborts at the long timeout (≥90s).
    await vi.advanceTimersByTimeAsync(85_000);
    expect(signal?.aborted).toBe(true);

    // The abort surfaces as a timeout ApiError (status 0), not a generic one.
    await rejection;
  });
});