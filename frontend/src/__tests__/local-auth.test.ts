import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getLocalDevSession,
  logoutLocalDevSession,
  startLocalDevSession,
} from "@/api/wiki";

const status = {
  mode: "local-dev",
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

describe("local development auth API", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("reads status with same-origin credentials for the HttpOnly cookie", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockStatusResponse());
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await getLocalDevSession();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/local-dev/session",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("starts a session without accepting a client principal", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockStatusResponse());
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await startLocalDevSession();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/local-dev/session",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
      }),
    );
  });

  it("logs out with same-origin credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockStatusResponse());
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await logoutLocalDevSession();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/local-dev/session",
      expect.objectContaining({
        method: "DELETE",
        credentials: "same-origin",
      }),
    );
  });
});
