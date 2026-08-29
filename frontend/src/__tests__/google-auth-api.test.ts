import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getAuthStatus,
  logoutSession,
  rotateEmergencyKey,
  startEmergencySession,
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

/**
 * LEGACY suite (auth-vault-credentials PR3): the Google auth flow is removed
 * from the app (getGoogleNonce/startGoogleSession deleted from wiki.ts), but
 * this file is only fully deleted in PR4. It now covers the still-exported
 * unified status, logout and the (dead) emergency-key functions, which the
 * cleanup PR removes together with the file.
 */
describe("vault auth API (legacy google/emergency leftovers)", () => {
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