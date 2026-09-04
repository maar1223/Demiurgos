import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  activateCoCreationSession,
  createCoCreationSession,
  deriveDraft,
  materializeCoCreationSession,
  publishCoCreationSession,
  recoverCoCreationSession,
  restoreHistory,
  setPendingQuestionStatus,
  setWarningStatus,
  turnCoCreationSession,
  updateCanvas,
  validatePayload,
} from "@/api/coCreation";
import { useCoCreation } from "@/hooks/useCoCreation";
import type {
  CoCreationSession,
  DraftPayload,
  PendingQuestion,
} from "@/api/types";

vi.mock("@/api/coCreation", () => ({
  activateCoCreationSession: vi.fn(),
  createCoCreationSession: vi.fn(),
  deriveDraft: vi.fn(),
  listHistory: vi.fn(),
  materializeCoCreationSession: vi.fn(),
  publishCoCreationSession: vi.fn(),
  recoverCoCreationSession: vi.fn(),
  restoreHistory: vi.fn(),
  setPendingQuestionStatus: vi.fn(),
  setWarningStatus: vi.fn(),
  turnCoCreationSession: vi.fn(),
  updateCanvas: vi.fn(),
  validatePayload: vi.fn(),
  getPublishedDetail: vi.fn(),
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
  draft_payload: null,
  warnings: [],
  history_count: 0,
  derived_from: null,
  ...overrides,
});

/** A session carrying a structured canvas payload (TW12). */
const canvasPayload: DraftPayload = {
  name: "Eneagrama",
  description: "Tipos de personalidad",
  purpose: "Modelar los nueve eneatipos",
  scope: "Personajes",
  main_flow: "Clasificar y derivar arcos",
  branches: ["Rama 1"],
  rules: ["Regla 1"],
  pending_questions: [] as PendingQuestion[],
  world: null,
};

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

  // -- TW12 canvas: debounced autosave, undo/redo, validation, history -------

  it("autosaves a canvas edit after the debounce with the current revision", async () => {
    localStorage.setItem(
      "demiurgos-co-creation-session",
      JSON.stringify({ sessionId: "server-session" }),
    );
    vi.mocked(recoverCoCreationSession).mockResolvedValue(
      sessionFixture({ revision: 5, draft_payload: canvasPayload }),
    );
    vi.mocked(updateCanvas).mockResolvedValue({
      revision: 6,
      issues: [],
      warnings: [],
      ok: true,
    });

    const { result } = renderHook(() =>
      useCoCreation({ autosaveDebounceMs: 20 }),
    );
    await waitFor(() => expect(result.current.session).not.toBeNull());
    expect(result.current.draftPayload).toEqual(canvasPayload);

    act(() => result.current.editCanvas({ purpose: "Nuevo propósito" }));

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });

    expect(updateCanvas).toHaveBeenCalledWith(
      "server-session",
      5,
      expect.objectContaining({ purpose: "Nuevo propósito" }),
    );
    await waitFor(() => expect(result.current.session?.revision).toBe(6));
  });

  it("coalesces rapid edits into a single debounced autosave", async () => {
    localStorage.setItem(
      "demiurgos-co-creation-session",
      JSON.stringify({ sessionId: "server-session" }),
    );
    vi.mocked(recoverCoCreationSession).mockResolvedValue(
      sessionFixture({ revision: 5, draft_payload: canvasPayload }),
    );
    vi.mocked(updateCanvas).mockResolvedValue({
      revision: 6,
      issues: [],
      warnings: [],
      ok: true,
    });

    const { result } = renderHook(() =>
      useCoCreation({ autosaveDebounceMs: 20 }),
    );
    await waitFor(() => expect(result.current.session).not.toBeNull());

    act(() => result.current.editCanvas({ scope: "Primero" }));
    act(() => result.current.editCanvas({ scope: "Segundo" }));
    act(() => result.current.editCanvas({ scope: "Tercero" }));

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });

    // Exactly one PUT with the LATEST payload (debounce, REQ-CC-15).
    expect(updateCanvas).toHaveBeenCalledTimes(1);
    expect(updateCanvas).toHaveBeenCalledWith(
      "server-session",
      5,
      expect.objectContaining({ scope: "Tercero" }),
    );
  });

  it("traverses the in-memory undo/redo edit stack (REQ-CC-15)", async () => {
    localStorage.setItem(
      "demiurgos-co-creation-session",
      JSON.stringify({ sessionId: "server-session" }),
    );
    vi.mocked(recoverCoCreationSession).mockResolvedValue(
      sessionFixture({ revision: 5, draft_payload: canvasPayload }),
    );
    vi.mocked(updateCanvas).mockResolvedValue({
      revision: 6,
      issues: [],
      warnings: [],
      ok: true,
    });

    const { result } = renderHook(() => useCoCreation());
    await waitFor(() => expect(result.current.session).not.toBeNull());

    act(() => result.current.editCanvas({ purpose: "Propósito A" }));
    expect(result.current.canUndo).toBe(true);
    expect(result.current.draftPayload?.purpose).toBe("Propósito A");

    act(() => result.current.undo());
    expect(result.current.draftPayload?.purpose).toBe(canvasPayload.purpose);
    expect(result.current.canRedo).toBe(true);

    act(() => result.current.redo());
    expect(result.current.draftPayload?.purpose).toBe("Propósito A");
    expect(result.current.canRedo).toBe(false);
  });

  it("syncs the canvas when the server merges a payload we did not send (REQ-CC-12)", async () => {
    localStorage.setItem(
      "demiurgos-co-creation-session",
      JSON.stringify({ sessionId: "server-session" }),
    );
    vi.mocked(recoverCoCreationSession).mockResolvedValue(
      sessionFixture({ revision: 5, draft_payload: canvasPayload }),
    );
    const chatMerged = {
      ...canvasPayload,
      purpose: "Propósito desde el chat",
    };
    vi.mocked(turnCoCreationSession).mockResolvedValue(
      sessionFixture({ revision: 6, draft_payload: chatMerged }),
    );

    const { result } = renderHook(() => useCoCreation());
    await waitFor(() => expect(result.current.session).not.toBeNull());

    await act(async () => {
      await result.current.send("Aclaración del propósito");
    });

    expect(result.current.draftPayload?.purpose).toBe(
      "Propósito desde el chat",
    );
  });

  it("runs a pure validation preview without mutating the session", async () => {
    localStorage.setItem(
      "demiurgos-co-creation-session",
      JSON.stringify({ sessionId: "server-session" }),
    );
    vi.mocked(recoverCoCreationSession).mockResolvedValue(
      sessionFixture({ revision: 5, draft_payload: canvasPayload }),
    );
    vi.mocked(validatePayload).mockResolvedValue({
      issues: [],
      warnings: [],
      source_preview: "# Eneagrama\n",
      ok: true,
    });

    const { result } = renderHook(() => useCoCreation());
    await waitFor(() => expect(result.current.session).not.toBeNull());

    await act(async () => {
      await result.current.validateCanvas();
    });

    expect(validatePayload).toHaveBeenCalledWith(
      "server-session",
      expect.objectContaining({ name: "Eneagrama" }),
    );
    expect(result.current.validation?.source_preview).toBe("# Eneagrama\n");
    expect(result.current.session?.revision).toBe(5);
  });

  it("restores a persisted snapshot through the revision-guarded API", async () => {
    localStorage.setItem(
      "demiurgos-co-creation-session",
      JSON.stringify({ sessionId: "server-session" }),
    );
    vi.mocked(recoverCoCreationSession).mockResolvedValue(
      sessionFixture({ revision: 5, draft_payload: canvasPayload }),
    );
    const restored = {
      ...canvasPayload,
      main_flow: "Flujo restaurado",
    };
    vi.mocked(restoreHistory).mockResolvedValue({
      revision: 6,
      payload: restored,
    });

    const { result } = renderHook(() => useCoCreation());
    await waitFor(() => expect(result.current.session).not.toBeNull());

    await act(async () => {
      await result.current.restoreSnapshot(2);
    });

    expect(restoreHistory).toHaveBeenCalledWith("server-session", 5, 2);
    expect(result.current.draftPayload?.main_flow).toBe("Flujo restaurado");
    expect(result.current.session?.revision).toBe(6);
  });

  it("applies Author-only warning transitions (REQ-CC-13)", async () => {
    localStorage.setItem(
      "demiurgos-co-creation-session",
      JSON.stringify({ sessionId: "server-session" }),
    );
    vi.mocked(recoverCoCreationSession).mockResolvedValue(
      sessionFixture({
        draft_payload: canvasPayload,
        warnings: [
          { code: "W1", message: "Campo opcional vacío", field: "purpose", state: "pendiente" },
        ],
      }),
    );
    vi.mocked(setWarningStatus).mockResolvedValue({
      warnings: [
        { code: "W1", message: "Campo opcional vacío", field: "purpose", state: "resuelta" },
      ],
    });

    const { result } = renderHook(() => useCoCreation());
    await waitFor(() => expect(result.current.session).not.toBeNull());

    await act(async () => {
      await result.current.setWarningStatus(0, "resuelta");
    });

    expect(setWarningStatus).toHaveBeenCalledWith("server-session", 3, 0, "resuelta");
    expect(result.current.session?.warnings[0].state).toBe("resuelta");
  });

  it("applies Author-only pending-question transitions (REQ-CC-14)", async () => {
    localStorage.setItem(
      "demiurgos-co-creation-session",
      JSON.stringify({ sessionId: "server-session" }),
    );
    vi.mocked(recoverCoCreationSession).mockResolvedValue(
      sessionFixture({
        draft_payload: {
          ...canvasPayload,
          pending_questions: [
            { text: "¿Aplica a mundos con magia?", state: "pendiente" },
          ],
        },
      }),
    );
    vi.mocked(setPendingQuestionStatus).mockResolvedValue({
      pending_questions: [
        { text: "¿Aplica a mundos con magia?", state: "aceptada_por_autor" },
      ],
    });

    const { result } = renderHook(() => useCoCreation());
    await waitFor(() => expect(result.current.session).not.toBeNull());

    await act(async () => {
      await result.current.setPendingQuestionStatus(0, "aceptada_por_autor");
    });

    expect(setPendingQuestionStatus).toHaveBeenCalledWith(
      "server-session",
      3,
      0,
      "aceptada_por_autor",
    );
    expect(
      result.current.session?.draft_payload?.pending_questions[0].state,
    ).toBe("aceptada_por_autor");
  });

  // -- TW13/TW14 adaptation + provenance ------------------------------------

  it("derives a draft from a published skill and loads the adaptation session", async () => {
    localStorage.setItem(
      "demiurgos-co-creation-session",
      JSON.stringify({ sessionId: "old-session" }),
    );
    vi.mocked(recoverCoCreationSession).mockResolvedValue(sessionFixture());
    const derivedFrom = { skill_id: "eneagrama", version: "1.2.0" };
    vi.mocked(deriveDraft).mockResolvedValue({
      session_id: "adaptation-session",
      draft_id: "draft-derivado",
      derived_from: derivedFrom,
    });
    vi.mocked(recoverCoCreationSession).mockResolvedValue(
      sessionFixture({
        session_id: "adaptation-session",
        draft_id: "draft-derivado",
        draft_payload: canvasPayload,
        derived_from: derivedFrom,
      }),
    );

    const { result } = renderHook(() => useCoCreation());
    await waitFor(() => expect(result.current.session).not.toBeNull());

    await act(async () => {
      await result.current.derive("eneagrama", "1.2.0", null);
    });

    expect(deriveDraft).toHaveBeenCalledWith("eneagrama", "1.2.0", null);
    expect(result.current.session?.session_id).toBe("adaptation-session");
    expect(result.current.session?.derived_from).toEqual(derivedFrom);
    expect(result.current.derivedFrom).toEqual(derivedFrom);
    expect(result.current.draftPayload).toEqual(canvasPayload);
  });
});