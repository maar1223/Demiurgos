import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  parseAssistantActivityEvent,
  streamAssistantActivity,
} from "@/api/assistantActivity";
import { useAIAssistantSessions } from "@/hooks/useAIAssistantSessions";

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

  it("streams correlated normalized events and ignores malformed records", async () => {
    const onEvent = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      streamResponse(
        [
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

    expect(result.answer).toBe("answer");
    expect(result.terminalStatus).toBe("succeeded");
    expect(onEvent).toHaveBeenCalledTimes(3);
    expect(JSON.stringify(result)).not.toContain("tool_name");
  });

  it.each([404, 501, 503])("reports neutral fallback for HTTP %s", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status })));

    await expect(
      streamAssistantActivity("vibrantes", { prompt: "hello", session_id: "session-1" }),
    ).rejects.toMatchObject({ status });
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
