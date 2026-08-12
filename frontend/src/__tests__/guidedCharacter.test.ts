import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  acceptGuidedCharacterProposal,
  continueGuidedCharacter,
  recoverGuidedCharacter,
  rejectGuidedCharacterProposal,
  retryGuidedCharacterIndex,
  startGuidedCharacter,
} from "@/api/guidedCharacter";

const session = {
  protocol_version: "guided-character-v1",
  session_id: "s1",
  world: "nec",
  phase: "conversation" as const,
  revision: 1,
  pending_question: null,
  messages: [],
  candidate: { accepted_canon: {}, proposals: {}, unresolved_references: [], conflicts: [] },
  proposal: null,
};

describe("guided character API compatibility", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => session }));
  });

  it("uses the six backend calls and their public envelope", async () => {
    await recoverGuidedCharacter("world with spaces", "s1");
    await startGuidedCharacter("world with spaces", "Create a character");
    await continueGuidedCharacter("world with spaces", "s1", 1, "freedom");
    await acceptGuidedCharacterProposal("world with spaces", "s1", 1, "desire");
    await rejectGuidedCharacterProposal("world with spaces", "s1", 1, "desire");
    await retryGuidedCharacterIndex("world with spaces", "s1", 1);

    const calls = vi.mocked(fetch).mock.calls;
    expect(calls.map(([url, options]) => [url, options?.method ?? "GET"])).toEqual([
      ["/api/world%20with%20spaces/guided-character/session/s1", "GET"],
      ["/api/world%20with%20spaces/guided-character/session", "POST"],
      ["/api/world%20with%20spaces/guided-character/turn", "POST"],
      ["/api/world%20with%20spaces/guided-character/proposal/accept", "POST"],
      ["/api/world%20with%20spaces/guided-character/proposal/reject", "POST"],
      ["/api/world%20with%20spaces/guided-character/index/retry", "POST"],
    ]);
    expect(calls.slice(1).map(([, options]) => options?.body)).toEqual([
      JSON.stringify({ author_input: "Create a character" }),
      JSON.stringify({ session_id: "s1", base_revision: 1, author_input: "freedom" }),
      JSON.stringify({ session_id: "s1", base_revision: 1, key: "desire" }),
      JSON.stringify({ session_id: "s1", base_revision: 1, key: "desire" }),
      JSON.stringify({ session_id: "s1", base_revision: 1 }),
    ]);
    expect(await startGuidedCharacter("nec", "x")).toEqual(session);
  });

  it("preserves backend fail-closed error code and retryability", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 503,
      json: async () => ({ detail: "Guided character creation is unavailable.", code: "capability_unavailable", retryable: true }),
    }));
    await expect(startGuidedCharacter("nec", "Create a character")).rejects.toMatchObject({
      status: 503, code: "capability_unavailable", detail: "Guided character creation is unavailable.",
    });
  });
});
