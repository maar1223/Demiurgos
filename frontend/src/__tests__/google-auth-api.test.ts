import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getAuthStatus,
  getGoogleNonce,
  logoutSession,
  rotateEmergencyKey,
  startEmergencySession,
  startGoogleSession,
} from "@/api/wiki";

const status = {
  mode: "google",
  enabled: true,
  authenticated: false,
  label: null,
};

function mockStatusResponse() {
  return {
    ok: true,
    status: 200,
    json: vi.fn().mockResolvedValue(status),
    headers: new Headers(),
  };
}

describe("google vault auth API", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("reads the unified status with same-origin credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockStatusResponse());
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await getAuthStatus();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/session/status",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("fetches the browser-bound login nonce", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ nonce: "nonce-abc" }),
      headers: new Headers(),
    });
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await expect(getGoogleNonce()).resolves.toEqual({ nonce: "nonce-abc" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/google/nonce",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("starts a google session posting id_token and remember_me", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockStatusResponse());
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await startGoogleSession("id-token-1", true);

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body as string)).toEqual({
      id_token: "id-token-1",
      remember_me: true,
    });
    expect(options.credentials).toBe("same-origin");
  });

  it("starts an emergency session posting the recovery key", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockStatusResponse());
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await startEmergencySession("clave-de-emergencia");

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body as string)).toEqual({
      key: "clave-de-emergencia",
    });
  });

  it("rotates the emergency key", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ new_key: "nueva clave" }),
      headers: new Headers(),
    });
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await expect(rotateEmergencyKey()).resolves.toEqual({ new_key: "nueva clave" });

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("same-origin");
  });

  it("logs out through the unified session endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockStatusResponse());
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await logoutSession();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/session",
      expect.objectContaining({
        method: "DELETE",
        credentials: "same-origin",
      }),
    );
  });
});