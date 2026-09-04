import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  activateCoCreationSession,
  createCoCreationSession,
  materializeCoCreationSession,
  publishCoCreationSession,
  recoverCoCreationSession,
  turnCoCreationSession,
} from "@/api/coCreation";
import { useCoCreation } from "@/hooks/useCoCreation";
import type { CoCreationSession } from "@/api/types";

vi.mock("@/api/coCreation", () => ({
  activateCoCreationSession: vi.fn(),
  createCoCreationSession: vi.fn(),
  materializeCoCreationSession: vi.fn(),
  publishCoCreationSession: vi.fn(),
  recoverCoCreationSession: vi.fn(),
  turnCoCreationSession: vi.fn(),
}));

const sessionFixture = (
  overrides: Partial<CoCreationSession> = {},
): CoCreationSession => ({
  protocol_version: "co-creation-v1",
  session_id: "server-session",
  principal_id: "principal-1",
  world: null,
  revision: 3,
  milestone: "alcance",
  progress: [
    { name: "proposito", state: "completado" },
    { name: "alcance", state: "actual" },
    { name: "flujo_principal", state: "pendiente" },
    { name: "ramas_reglas", state: "pendiente" },
    { name: "borrador_listo", state: "pendiente" },
    { name: "revision_publicacion", state: "pendiente" },
  ],
  question_count: 2,
  pending_question: "¿La skill es para un mundo específico o transversal?",
  pending_options: ["Mundo específico", "Transversal"],
  messages: [
    { role: "author", content: "Quiero una skill de eneagrama" },
    { role: "assistant", content: "¿Cuál es el propósito?" },
  ],
  phase: "conversation",
  draft_id: null,
  compile_issues: null,
  ...overrides,
});

describe("useCoCreation", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetAllMocks();
  });

  it("uses backend recovery state from the localStorage hint (backend authoritative)", async () => {
    localStorage.setItem(
      "demiurgos-co-creation-session",
      JSON.stringify({ sessionId: "server-session" }),
    );
    const recovered = sessionFixture();
    vi.mocked(recoverCoCreationSession).mockResolvedValue(recovered);

    const { result } = renderHook(() => useCoCreation());

    await waitFor(() => expect(result.current.session).toEqual(recovered));
    expect(recoverCoCreationSession).toHaveBeenCalledWith("server-session");
  });

  it("clears the hint when the backend no longer knows the session", async () => {
    localStorage.setItem(
      "demiurgos-co-creation-session",
      JSON.stringify({ sessionId: "stale-session" }),
    );
    vi.mocked(recoverCoCreationSession).mockRejectedValue(
      new Error("The co-creation session is unavailable."),
    );

    const { result } = renderHook(() => useCoCreation());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(localStorage.getItem("demiurgos-co-creation-session")).toBeNull();
    expect(result.current.session).toBeNull();
  });

  it("sends the current backend revision and does not persist a failed start", async () => {
    vi.mocked(createCoCreationSession).mockRejectedValue(
      new Error("provider unavailable"),
    );
    const { result } = renderHook(() => useCoCreation());

    await act(async () => {
      await expect(result.current.send("Quiero crear una skill")).rejects.toThrow(
        "provider unavailable",
      );
    });

    expect(result.current.error).toBe("provider unavailable");
    expect(localStorage.getItem("demiurgos-co-creation-session")).toBeNull();
    expect(turnCoCreationSession).not.toHaveBeenCalled();
  });

  it("continues an existing session with its backend revision", async () => {
    localStorage.setItem(
      "demiurgos-co-creation-session",
      JSON.stringify({ sessionId: "server-session" }),
    );
    vi.mocked(recoverCoCreationSession).mockResolvedValue(sessionFixture());
    const next = sessionFixture({ revision: 4, question_count: 3 });
    vi.mocked(turnCoCreationSession).mockResolvedValue(next);

    const { result } = renderHook(() => useCoCreation());
    await waitFor(() => expect(result.current.session).not.toBeNull());

    await act(async () => {
      await result.current.send("Es para un mundo específico");
    });

    expect(turnCoCreationSession).toHaveBeenCalledWith(
      "server-session",
      3,
      "Es para un mundo específico",
    );
    expect(result.current.session?.revision).toBe(4);
  });

  it("surfaces compiler issues and keeps the session at borrador_listo", async () => {
    const draftReady = sessionFixture({
      milestone: "borrador_listo",
      pending_question: null,
      pending_options: [],
      messages: [
        { role: "assistant", content: "El borrador está listo." },
      ],
    });
    localStorage.setItem(
      "demiurgos-co-creation-session",
      JSON.stringify({ sessionId: "server-session" }),
    );
    vi.mocked(recoverCoCreationSession).mockResolvedValue(draftReady);
    const issues = [
      { code: "AUTH_CLAIM", message: "Autoridad no permitida", field: "delta" },
    ];
    vi.mocked(materializeCoCreationSession).mockResolvedValue({
      draft_id: "draft-1",
      ok: false,
      issues,
      compile_issues: issues,
      phase: "conversation",
      milestone: "borrador_listo",
      revision: 3,
    });

    const { result } = renderHook(() => useCoCreation());
    await waitFor(() => expect(result.current.session).not.toBeNull());

    await act(async () => {
      await result.current.materialize({ name: "Eneagrama" });
    });

    expect(result.current.session?.compile_issues).toEqual(issues);
    expect(result.current.session?.phase).toBe("conversation");
    expect(result.current.session?.draft_id).toBeNull();
  });

  it("advances to review when materialization compiles cleanly", async () => {
    const draftReady = sessionFixture({
      milestone: "borrador_listo",
      pending_question: null,
      pending_options: [],
    });
    localStorage.setItem(
      "demiurgos-co-creation-session",
      JSON.stringify({ sessionId: "server-session" }),
    );
    vi.mocked(recoverCoCreationSession).mockResolvedValue(draftReady);
    vi.mocked(materializeCoCreationSession).mockResolvedValue({
      session_id: "server-session",
      draft_id: "draft-1",
      ok: true,
      issues: [],
      compile_issues: [],
      phase: "review",
      milestone: "revision_publicacion",
      revision: 4,
    });

    const { result } = renderHook(() => useCoCreation());
    await waitFor(() => expect(result.current.session).not.toBeNull());

    await act(async () => {
      await result.current.materialize({ name: "Eneagrama" });
    });

    expect(result.current.session?.phase).toBe("review");
    expect(result.current.session?.draft_id).toBe("draft-1");
    expect(result.current.session?.revision).toBe(4);
    expect(result.current.session?.compile_issues).toEqual([]);
  });

  it("records the immutable published version and completes the session", async () => {
    const reviewed = sessionFixture({
      phase: "review",
      milestone: "revision_publicacion",
      draft_id: "draft-1",
      compile_issues: [],
      pending_question: null,
      pending_options: [],
    });
    localStorage.setItem(
      "demiurgos-co-creation-session",
      JSON.stringify({ sessionId: "server-session" }),
    );
    vi.mocked(recoverCoCreationSession).mockResolvedValue(reviewed);
    const publishResult = {
      session_id: "server-session",
      phase: "complete" as const,
      revision: 5,
      published: {
        skill_id: "eneagrama",
        version: "0.1.0",
        name: "Eneagrama",
        description: "",
        digest: "abc123",
        published_at: "2026-09-03T00:00:00Z",
      },
    };
    vi.mocked(publishCoCreationSession).mockResolvedValue(publishResult);

    const { result } = renderHook(() => useCoCreation());
    await waitFor(() => expect(result.current.session).not.toBeNull());

    await act(async () => {
      await result.current.publish();
    });

    expect(result.current.published).toEqual(publishResult);
    expect(result.current.session?.phase).toBe("complete");
  });

  it("pins the published version to a world via activate", async () => {
    const completed = sessionFixture({
      phase: "complete",
      milestone: "revision_publicacion",
      draft_id: "draft-1",
      compile_issues: [],
      pending_question: null,
      pending_options: [],
    });
    localStorage.setItem(
      "demiurgos-co-creation-session",
      JSON.stringify({ sessionId: "server-session" }),
    );
    vi.mocked(recoverCoCreationSession).mockResolvedValue(completed);
    const activationResult = {
      session_id: "server-session",
      phase: "complete" as const,
      revision: 5,
      activation: {
        world: "Vibrantes",
        skill_id: "eneagrama",
        version: "0.1.0",
        digest: "abc123",
        activated_at: "2026-09-03T00:00:00Z",
      },
    };
    vi.mocked(activateCoCreationSession).mockResolvedValue(activationResult);

    const { result } = renderHook(() => useCoCreation());
    await waitFor(() => expect(result.current.session).not.toBeNull());

    await act(async () => {
      await result.current.activate("Vibrantes");
    });

    expect(result.current.activation).toEqual(activationResult);
    expect(activateCoCreationSession).toHaveBeenCalledWith(
      "server-session",
      3,
      "Vibrantes",
    );
  });

  it("reset discards the hint and the local session", async () => {
    localStorage.setItem(
      "demiurgos-co-creation-session",
      JSON.stringify({ sessionId: "server-session" }),
    );
    vi.mocked(recoverCoCreationSession).mockResolvedValue(sessionFixture());

    const { result } = renderHook(() => useCoCreation());
    await waitFor(() => expect(result.current.session).not.toBeNull());

    act(() => result.current.reset());

    expect(result.current.session).toBeNull();
    expect(localStorage.getItem("demiurgos-co-creation-session")).toBeNull();
  });
});