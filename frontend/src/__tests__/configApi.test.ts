import { beforeEach, describe, expect, it, vi } from "vitest";
import { getAppConfig } from "@/api/config";

const mockApiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({ apiFetch: mockApiFetch }));

describe("app config API contract", () => {
  beforeEach(() => {
    mockApiFetch.mockReset().mockResolvedValue({ language: "es" });
  });

  it("GET /api/config returns the normalized language with a bounded timeout", async () => {
    await expect(getAppConfig()).resolves.toEqual({ language: "es" });
    expect(mockApiFetch).toHaveBeenCalledWith("/api/config", { timeout: 3_000 });
  });
});
