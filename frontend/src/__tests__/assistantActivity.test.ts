import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  parseAssistantActivityEvent,
  streamAssistantActivity,
} from "@/api/assistantActivity";
import { useAIAssistantSessions } from "@/hooks/useAIAssistantSessions";
import { semanticBlockedText } from "@/lib/semanticIntent";

vi.mock("@/hooks/useAppLanguage", () => ({
  useAppLanguage: vi.fn(() => ({ language: "es", t: (key: string) => key })),
}));

function streamResponse(events: string, requestId = "request-1"): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(events));
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "X-Assistant-Activity-Request-Id": requestId,
    },
  });
}

describe("assistant activity transport", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("accepts only normalized fields and strips unsafe evidence", () => {
    expect(
      parseAssistantActivityEvent({
        kind: "activity",
        request_id: "request-1",
        item_id: "item-1",
        operation: "Read world",
        status: "succeeded",
        path: "/absolute/secret",
        preview: "provider output",
        arguments: { secret: true },
      }, "request-1"),
    ).toEqual({
      kind: "activity",
      request_id: "request-1",
      item_id: "item-1",
      operation: "Read world",
      status: "succeeded",
    });
    expect(
      parseAssistantActivityEvent(
        { kind: "terminal", request_id: "other", status: "succeeded" },
        "request-1",
      ),
    ).toBeNull();
  });

  it("parses a valid semantic_decision event with backend-exact fields", () => {
    expect(parseAssistantActivityEvent({
      kind: "semantic_decision",
      request_id: "request-1",
      state: "allow",
      action: "answer",
      unavailable: false,
      continuation: null,
    }, "request-1")).toEqual({
      kind: "semantic_decision",
      request_id: "request-1",
      state: "allow",
      action: "answer",
      unavailable: false,
      continuation: null,
    });
  });

  it("parses typed continuation question and delta outcomes", () => {
    const question = parseAssistantActivityEvent({
      kind: "semantic_decision",
      request_id: "request-1",
      state: "require_confirmation",
      action: "request_confirmation",
      unavailable: false,
      continuation: { outcome: "question", question: "¿Creo este personaje?" },
    }, "request-1");
    expect(question).toEqual({
      kind: "semantic_decision",
      request_id: "request-1",
      state: "require_confirmation",
      action: "request_confirmation",
      unavailable: false,
      continuation: { outcome: "question", question: "¿Creo este personaje?" },
    });

    const delta = parseAssistantActivityEvent({
      kind: "semantic_decision",
      request_id: "request-1",
      state: "proposal_ready",
      action: "show_proposal",
      unavailable: false,
      continuation: { outcome: "delta", delta: { name: "Rhyz", desire: "freedom" } },
    }, "request-1");
    expect(delta?.kind).toBe("semantic_decision");
    if (delta?.kind !== "semantic_decision") return;
    expect(delta.continuation).toEqual({
      outcome: "delta",
      delta: { name: "Rhyz", desire: "freedom" },
    });
  });

  it.each([
    { kind: "semantic_decision", request_id: "request-1", state: "approve", action: "answer", unavailable: false, continuation: null },
    { kind: "semantic_decision", request_id: "request-1", state: "allow", action: "answer", unavailable: "yes", continuation: null },
    { kind: "semantic_decision", request_id: "request-1", state: "allow", action: "answer", unavailable: false, continuation: { outcome: "question" } },
    { kind: "semantic_decision", request_id: "request-1", state: "allow", action: "answer", unavailable: false, continuation: { outcome: "delta", delta: {} } },
    { kind: "semantic_decision", request_id: "request-1", state: "allow", action: "answer", unavailable: false, continuation: { outcome: "delta", delta: { target: "lore/x.md" } } },
    { kind: "semantic_decision", request_id: "request-1", state: "allow", action: "", unavailable: false, continuation: null },
    { kind: "semantic_decision", request_id: "request-1", state: "allow", action: "answer", unavailable: false, continuation: "nope" },
  ])("rejects unknown/malformed semantic_decision events fail-closed (%#)", (event) => {
    expect(parseAssistantActivityEvent(event, "request-1")).toBeNull();
  });

  it("keeps the legacy answer/terminal parsing functional alongside semantic_decision", () => {
    expect(parseAssistantActivityEvent(
      { kind: "answer", request_id: "request-1", response: "legacy" },
      "request-1",
    )).toEqual({ kind: "answer", request_id: "request-1", response: "legacy" });
    expect(parseAssistantActivityEvent(
      { kind: "terminal", request_id: "request-1", status: "failed" },
      "request-1",
    )).toEqual({ kind: "terminal", request_id: "request-1", status: "failed" });
  });

  it("streams the authoritative semantic decision before compatible events", async () => {
    const onEvent = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      streamResponse([
        `data: {"kind":"semantic_decision","request_id":"request-1","state":"allow","action":"answer","unavailable":false,"continuation":null}`,
        `data: {"kind":"activity","request_id":"request-1","item_id":"item-1","operation":"Search world","status":"running"}`,
        `data: {"kind":"answer","request_id":"request-1","response":"answer"}`,
        `data: {"kind":"terminal","request_id":"request-1","status":"succeeded"}`,
        "",
      ].join("\n\n"),
    )));

    const result = await streamAssistantActivity("vibrantes", {
      prompt: "hello",
      session_id: "session-1",
    }, { onEvent });

    expect(result.events[0]?.kind).toBe("semantic_decision");
    if (result.events[0]?.kind !== "semantic_decision") return;
    expect(result.events[0].state).toBe("allow");
    expect(result.semanticDecision?.state).toBe("allow");
    expect(result.answer).toBe("answer");
    expect(result.terminalStatus).toBe("succeeded");
    expect(onEvent).toHaveBeenCalledTimes(4);
  });

  it("fails closed when the semantic decision is missing from the stream", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      streamResponse([
        `data: {"kind":"answer","request_id":"request-1","response":"answer"}`,
        `data: {"kind":"terminal","request_id":"request-1","status":"succeeded"}`,
        "",
      ].join("\n\n"),
    )));

    const result = await streamAssistantActivity("vibrantes", {
      prompt: "hello",
      session_id: "session-1",
    });

    expect(result.semanticDecision).toBeNull();
  });

  it("fails closed when an answer precedes the semantic decision", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      streamResponse([
        `data: {"kind":"answer","request_id":"request-1","response":"answer"}`,
        `data: {"kind":"semantic_decision","request_id":"request-1","state":"allow","action":"answer","unavailable":false,"continuation":null}`,
        `data: {"kind":"terminal","request_id":"request-1","status":"succeeded"}`,
        "",
      ].join("\n\n"),
    )));

    const result = await streamAssistantActivity("vibrantes", {
      prompt: "hello",
      session_id: "session-1",
    });

    expect(result.semanticDecision).toBeNull();
  });

  it("streams correlated normalized events and ignores malformed records", async () => {
    const onEvent = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      streamResponse(
        [
          `data: {"kind":"semantic_decision","request_id":"request-1","state":"clarify","action":"ask_question","unavailable":false,"continuation":null}`,
          `data: {"kind":"activity","request_id":"request-1","item_id":"item-1","operation":"Search world","status":"running","tool_name":"secret"}`,
          `data: not-json`,
          `data: {"kind":"answer","request_id":"other","response":"ignore"}`,
          `data: {"kind":"answer","request_id":"request-1","response":"answer"}`,
          `data: {"kind":"terminal","request_id":"request-1","status":"succeeded"}`,
          "",
        ].join("\n\n"),
      ),
    ));

    const result = await streamAssistantActivity("vibrantes", {
      prompt: "hello",
      session_id: "session-1",
    }, { onEvent });

    expect(result.semanticDecision?.state).toBe("clarify");
    expect(result.answer).toBe("answer");
    expect(result.terminalStatus).toBe("succeeded");
    expect(onEvent).toHaveBeenCalledTimes(4);
    expect(JSON.stringify(result)).not.toContain("tool_name");
  });

  it.each([404, 501, 503])("reports neutral fallback for HTTP %s", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status })));

    await expect(
      streamAssistantActivity("vibrantes", { prompt: "hello", session_id: "session-1" }),
    ).rejects.toMatchObject({ status });
  });

  it("preserves active ficha and guided revision in the assistant request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 503 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(streamAssistantActivity("vibrantes", {
      prompt: "Remind me what Rhyz is like",
      session_id: "chat-1",
      section: "personajes",
      file_path: "rhyz.md",
      guided_session_id: "guided-1",
      guided_revision: 2,
    })).rejects.toMatchObject({ reasonCode: "provider_activity_unavailable" });

    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
      prompt: "Remind me what Rhyz is like",
      session_id: "chat-1",
      section: "personajes",
      file_path: "rhyz.md",
      guided_session_id: "guided-1",
      guided_revision: 2,
    });
  });

  it("accepts only the safe capability diagnostic from the activity endpoint", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json(
          {
            detail: "Assistant activity is unavailable",
            code: "activity_unavailable",
            reason_code: "file_evidence_contract_unverified",
          },
          { status: 503 },
        ),
      ),
    );

    await expect(
      streamAssistantActivity("vibrantes", { prompt: "hello", session_id: "session-1" }),
    ).rejects.toMatchObject({
      reasonCode: "file_evidence_contract_unverified",
    });
  });

  it("does not expose an unrecognized capability diagnostic", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json({ reason_code: "provider-secret" }, { status: 503 }),
      ),
    );

    await expect(
      streamAssistantActivity("vibrantes", { prompt: "hello", session_id: "session-1" }),
    ).rejects.toMatchObject({
      reasonCode: "provider_activity_unavailable",
    });
  });

  it("falls back to the legacy answer without persisting activity state", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 503 }))
      .mockResolvedValueOnce(Response.json({ response: "legacy answer" }));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useAIAssistantSessions("vibrantes"));

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toContain("/ai/ask");
    const legacyMessages = result.current.activeSession?.messages ?? [];
    expect(legacyMessages[legacyMessages.length - 1]?.content).toBe("legacy answer");
    expect(localStorage.getItem("demiurgos-ai-sessions")).not.toContain("activity");
    expect(result.current.evidence.status).toBe("neutral");
    expect(result.current.activity.availability).toBe("unavailable");
  });

  it("keeps accepted activity request-scoped and exposes only confirmed sources", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      streamResponse([
        `data: {"kind":"semantic_decision","request_id":"request-1","state":"allow","action":"answer","unavailable":false,"continuation":null}`,
        `data: {"kind":"activity","request_id":"request-1","item_id":"item-1","operation":"Read world","status":"running"}`,
        `data: {"kind":"activity","request_id":"request-1","item_id":"item-1","operation":"Read world","status":"succeeded","path":"lore/inicio.md"}`,
        `data: {"kind":"answer","request_id":"request-1","response":"answer"}`,
        `data: {"kind":"terminal","request_id":"request-1","status":"succeeded"}`,
        "",
      ].join("\n\n"),
    )));
    const { result } = renderHook(() => useAIAssistantSessions("vibrantes"));

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    expect(result.current.activity.items).toEqual([{
      item_id: "item-1",
      operation: "Read world",
      status: "succeeded",
      path: "lore/inicio.md",
    }]);
    expect(result.current.evidence.sources).toEqual(["lore/inicio.md"]);
    const activityMessages = result.current.activeSession?.messages ?? [];
    expect(activityMessages[activityMessages.length - 1]?.content).toBe("answer");
  });

  it("applies an allowed semantic decision as the assistant answer", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      streamResponse([
        `data: {"kind":"semantic_decision","request_id":"request-1","state":"allow","action":"answer","unavailable":false,"continuation":null}`,
        `data: {"kind":"answer","request_id":"request-1","response":"answer"}`,
        `data: {"kind":"terminal","request_id":"request-1","status":"succeeded"}`,
        "",
      ].join("\n\n"),
    )));
    const { result } = renderHook(() => useAIAssistantSessions("vibrantes"));

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    const messages = result.current.activeSession?.messages ?? [];
    expect(messages[messages.length - 1]?.content).toBe("answer");
    expect(result.current.activity.blocked).toBeUndefined();
  });

  it("applies a blocked semantic decision as the safe copy without a normal answer", async () => {
    const blockedCopy = "El Asistente IA no pudo completar la solicitud en este momento. No se realizó ninguna acción ni escritura.";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      streamResponse([
        `data: {"kind":"semantic_decision","request_id":"request-1","state":"blocked","action":"blocked_explanation","unavailable":true,"continuation":null}`,
        `data: {"kind":"answer","request_id":"request-1","response":"${blockedCopy}"}`,
        `data: {"kind":"terminal","request_id":"request-1","status":"failed"}`,
        "",
      ].join("\n\n"),
    )));
    const { result } = renderHook(() => useAIAssistantSessions("vibrantes"));

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    const messages = result.current.activeSession?.messages ?? [];
    expect(messages[messages.length - 1]?.content).toBe(blockedCopy);
    expect(result.current.activity.blocked).toBe(true);
    expect(result.current.activity.availability).toBe("unavailable");
  });

  it("fails closed to localized copy when the semantic decision is missing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      streamResponse([
        `data: {"kind":"answer","request_id":"request-1","response":"looks harmless"}`,
        `data: {"kind":"terminal","request_id":"request-1","status":"succeeded"}`,
        "",
      ].join("\n\n"),
    )));
    const { result } = renderHook(() => useAIAssistantSessions("vibrantes"));

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    const messages = result.current.activeSession?.messages ?? [];
    expect(messages[messages.length - 1]?.content).toBe(semanticBlockedText("es"));
    expect(messages.some((message) => message.content === "looks harmless")).toBe(false);
    expect(result.current.activity.blocked).toBe(true);
    expect(result.current.activity.availability).toBe("unavailable");
  });

  it("fails closed to localized copy on a malformed semantic decision", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      streamResponse([
        `data: {"kind":"semantic_decision","request_id":"request-1","state":"approve","action":"answer","unavailable":false,"continuation":null}`,
        `data: {"kind":"answer","request_id":"request-1","response":"looks harmless"}`,
        `data: {"kind":"terminal","request_id":"request-1","status":"succeeded"}`,
        "",
      ].join("\n\n"),
    )));
    const { result } = renderHook(() => useAIAssistantSessions("vibrantes"));

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    const messages = result.current.activeSession?.messages ?? [];
    expect(messages[messages.length - 1]?.content).toBe(semanticBlockedText("es"));
    expect(messages.some((message) => message.content === "looks harmless")).toBe(false);
    expect(result.current.activity.blocked).toBe(true);
  });

  it("keeps the fallback to the legacy ask path without raw error leakage", async () => {
    const safeCopy = "El Asistente IA no pudo completar la solicitud en este momento. No se realizó ninguna acción ni escritura.";
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 503 }))
      .mockResolvedValueOnce(Response.json({
        state: "blocked",
        response: safeCopy,
        action: "blocked_explanation",
        request_id: "request-1",
        attempts: 3,
        unavailable: true,
      }));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useAIAssistantSessions("vibrantes"));

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const messages = result.current.activeSession?.messages ?? [];
    expect(messages[messages.length - 1]?.content).toBe(safeCopy);
    expect(result.current.activity.blocked).toBe(true);
    expect(JSON.stringify(messages)).not.toMatch(/Error:/);
  });

  it("aborts the request without creating a second legacy run", async () => {
    let requestSignal: AbortSignal | undefined;
    vi.stubGlobal("fetch", vi.fn((_url: string, options: RequestInit) => {
      requestSignal = options.signal ?? undefined;
      return new Promise<Response>((_, reject) => {
        options.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      });
    }));
    const { result } = renderHook(() => useAIAssistantSessions("vibrantes"));
    let pending: Promise<void>;

    act(() => {
      pending = result.current.sendMessage("hello");
    });
    act(() => result.current.cancelSend());
    await act(async () => pending);

    expect(requestSignal?.aborted).toBe(true);
    expect(result.current.activeSession?.messages).toHaveLength(1);
  });
});
