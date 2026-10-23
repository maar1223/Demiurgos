import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  acceptGuidedCharacterProposal,
  startGuidedFlow,
  acceptGuidedConsent,
  continueGuidedCharacter,
  declineGuidedConsent,
  recoverGuidedCharacter,
  rejectGuidedCharacterProposal,
  retryGuidedCharacterIndex,
  serializeGuidedCharacter,
  startGuidedCharacter,
} from "@/api/guidedCharacter";
import { ApiError } from "@/api/types";
import type { GuidedCharacterSession, SemanticDecisionEnvelope } from "@/api/types";

const mockApiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({ apiFetch: mockApiFetch }));

const session: GuidedCharacterSession = {
  protocol_version: "guided-character-v1",
  session_id: "s1",
  world: "nec",
  phase: "conversation",
  mode: "full",
  depth: "standard",
  revision: 1,
  pending_question: null,
  messages: [],
  candidate: { accepted_canon: {}, proposals: {}, unresolved_references: [], conflicts: [] },
  proposal: null,
};

describe("guided character API compatibility", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockApiFetch.mockReset().mockResolvedValue(session);
  });

  it("uses the guided backend calls and their public envelope", async () => {
    await recoverGuidedCharacter("world with spaces", "s1");
    await startGuidedCharacter("world with spaces", "Create a character");
    await continueGuidedCharacter("world with spaces", "s1", 1, "freedom");
    await acceptGuidedCharacterProposal("world with spaces", "s1", 1, "desire");
    await rejectGuidedCharacterProposal("world with spaces", "s1", 1, "desire");
    await serializeGuidedCharacter("world with spaces", "s1", 1);
    await retryGuidedCharacterIndex("world with spaces", "s1", 1);

    const calls = mockApiFetch.mock.calls;
    expect(calls.map(([url, options]) => [url, options?.method ?? "GET"])).toEqual([
      ["/api/world%20with%20spaces/guided/session/s1", "GET"],
      ["/api/world%20with%20spaces/guided/session", "POST"],
      ["/api/world%20with%20spaces/guided/turn", "POST"],
      ["/api/world%20with%20spaces/guided/proposal/accept", "POST"],
      ["/api/world%20with%20spaces/guided/proposal/reject", "POST"],
      ["/api/world%20with%20spaces/guided/proposal/serialize", "POST"],
      ["/api/world%20with%20spaces/guided/index/retry", "POST"],
    ]);
    expect(calls.map(([, options]) => options?.timeout)).toEqual(Array(7).fill(35_000));
    expect(calls.slice(1).map(([, options]) => options?.body)).toEqual([
      JSON.stringify({ author_input: "Create a character", flow_id: "guided-character" }),
      JSON.stringify({ session_id: "s1", base_revision: 1, author_input: "freedom" }),
      JSON.stringify({ session_id: "s1", base_revision: 1, key: "desire" }),
      JSON.stringify({ session_id: "s1", base_revision: 1, key: "desire" }),
      JSON.stringify({ session_id: "s1", base_revision: 1 }),
      JSON.stringify({ session_id: "s1", base_revision: 1 }),
    ]);
    expect(await startGuidedCharacter("nec", "x")).toEqual(session);
  });

  it("opens a declared flow with its flow id (S1/S3)", async () => {
    await startGuidedFlow("nec", "Quiero crear un sistema", "guided-system", {
      skill_id: "narrative-system-creation",
      version: "1.1",
    });
    await acceptGuidedConsent("nec", "ct-1", undefined, "guided-system");
    expect(
      mockApiFetch.mock.calls.map(([, options]) => options?.body),
    ).toEqual([
      JSON.stringify({
        author_input: "Quiero crear un sistema",
        flow_id: "guided-system",
        method_skill_id: "narrative-system-creation",
        method_version: "1.1",
      }),
      JSON.stringify({ token: "ct-1", flow_id: "guided-system" }),
    ]);
  });

  it("wires the one-shot consent accept/decline calls with the token body", async () => {
    const consentEnvelope: SemanticDecisionEnvelope = {
      state: "require_confirmation",
      action: "request_confirmation",
      response: "¿Creo este personaje?",
      request_id: "r-consent",
      attempts: 1,
      fallback: false,
      guided: true,
      guided_explicitness: "imperative",
      session_id: "guided-1",
      guided_session_id: "guided-1",
      guided_revision: 1,
      guided_state: session,
    };
    mockApiFetch
      .mockReset()
      .mockResolvedValueOnce(consentEnvelope)
      .mockResolvedValueOnce({ consent: "declined" });

    await expect(acceptGuidedConsent("world with spaces", "ct-1")).resolves.toEqual(
      consentEnvelope,
    );
    await declineGuidedConsent("world with spaces", "ct-1");

    const calls = mockApiFetch.mock.calls;
    expect(calls.map(([url, options]) => [url, options?.method ?? "GET"])).toEqual([
      ["/api/world%20with%20spaces/guided/consent/accept", "POST"],
      ["/api/world%20with%20spaces/guided/consent/decline", "POST"],
    ]);
    expect(calls.map(([, options]) => options?.body)).toEqual([
      JSON.stringify({ token: "ct-1" }),
      JSON.stringify({ token: "ct-1" }),
    ]);
  });

  it("preserves backend fail-closed error code and retryability", async () => {
    mockApiFetch.mockRejectedValue(new ApiError(
      503,
      "Guided character creation is unavailable.",
      "Guided character creation is unavailable.",
      "capability_unavailable",
    ));
    await expect(startGuidedCharacter("nec", "Create a character")).rejects.toMatchObject({
      status: 503, code: "capability_unavailable", detail: "Guided character creation is unavailable.",
    });
  });
});

describe("guided character per-session method (S6)", () => {
  beforeEach(() => {
    mockApiFetch.mockReset().mockResolvedValue(session);
  });

  it("sends method_skill_id/method_version and the factory token", async () => {
    await startGuidedCharacter("nec", "x", { skill_id: "factory" });
    await startGuidedCharacter("nec", "y", {
      skill_id: "narrative-character-creation",
      version: "1.2",
    });
    await acceptGuidedConsent("nec", "ct-1", {
      skill_id: "narrative-character-creation",
      version: "1.2",
    });

    expect(
      mockApiFetch.mock.calls.map(([, options]) => options?.body),
    ).toEqual([
      JSON.stringify({ author_input: "x", flow_id: "guided-character", method_skill_id: "factory" }),
      JSON.stringify({
        author_input: "y",
        flow_id: "guided-character",
        method_skill_id: "narrative-character-creation",
        method_version: "1.2",
      }),
      JSON.stringify({
        token: "ct-1",
        method_skill_id: "narrative-character-creation",
        method_version: "1.2",
      }),
    ]);
  });

  it("omits the method when no choice is supplied (legacy default)", async () => {
    await startGuidedCharacter("nec", "x");
    await acceptGuidedConsent("nec", "ct-1");
    expect(
      mockApiFetch.mock.calls.map(([, options]) => options?.body),
    ).toEqual([
      JSON.stringify({ author_input: "x", flow_id: "guided-character" }),
      JSON.stringify({ token: "ct-1" }),
    ]);
  });
});
