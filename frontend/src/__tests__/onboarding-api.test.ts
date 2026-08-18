import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  createWorld,
  getOnboardingStatus,
  getReadiness,
  submitStep0,
} from "@/api/onboarding";
import { getLocale } from "@/api/config";

const BASE = "";

function jsonFetch(response: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => response,
  });
}

describe("onboarding API (Slice 1 contracts)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    globalThis.fetch = vi.fn();
  });

  it("GET /api/onboarding/status returns the first-run gate state", async () => {
    const body = {
      completed: false,
      current_step: "step0",
      completed_steps: [],
      pending_steps: ["step0", "ai", "telegram", "world", "backup_handoff", "ready"],
      remote_pending: ["ai", "telegram", "backup_handoff"],
      blocking_pending: ["step0"],
    };
    globalThis.fetch = jsonFetch(body);
    await expect(getOnboardingStatus()).resolves.toEqual(body);
    expect(fetch).toHaveBeenCalledWith(
      `${BASE}/api/onboarding/status`,
      expect.objectContaining({}),
    );
  });

  it("POST /api/onboarding/step0 sends the three independent languages + IANA zone", async () => {
    globalThis.fetch = jsonFetch({ completed: true, current_step: "ready" });
    await submitStep0({
      ui: "es",
      conversation: "en",
      content: "es",
      region: "AR",
      region_explicit: true,
      iana_timezone: "America/Argentina/Buenos_Aires",
    });
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe(`${BASE}/api/onboarding/step0`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      ui: "es",
      conversation: "en",
      content: "es",
      region: "AR",
      region_explicit: true,
      iana_timezone: "America/Argentina/Buenos_Aires",
    });
  });

  it("POST /api/worlds sends the name and lore_skeleton flag", async () => {
    globalThis.fetch = jsonFetch({ kind: "created", name: "x", path: null, message: "" });
    await createWorld("x", true);
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe(`${BASE}/api/worlds`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ name: "x", lore_skeleton: true });
  });

  it("GET /api/onboarding/readiness returns probe + card states", async () => {
    const body = {
      local_editor: { probe: "local_editor", ok: true, detail: "storage round-trip ok" },
      cards: { world: "pending", identity: "pending", telegram: "pending" },
    };
    globalThis.fetch = jsonFetch(body);
    await expect(getReadiness()).resolves.toEqual(body);
  });

  it("GET /api/locale returns independent UI/conversation/content languages", async () => {
    const body = {
      ui: "es",
      conversation: "en",
      content: "es",
      region: null,
      region_explicit: false,
      iana_timezone: "UTC",
    };
    globalThis.fetch = jsonFetch(body);
    await expect(getLocale()).resolves.toEqual(body);
    expect(fetch).toHaveBeenCalledWith(
      `${BASE}/api/locale`,
      expect.objectContaining({}),
    );
  });
});