import { afterEach, describe, expect, it, vi } from "vitest";
import {
  authorizeChat,
  clearIdeaCaptureToken,
  discoverChatCandidates,
  getIdeaCaptureStatus,
  saveIdeaCaptureConfig,
  setIdeaCaptureToken,
} from "@/api/ideaCapture";
import type { IdeaCaptureConfig, IdeaCaptureStatus } from "@/api/types";

const defaultConfig: IdeaCaptureConfig = {
  private_chat_ids: [],
  approved_groups: {},
  active_world: "",
  limits: { image_mb: 20, audio_mb: 50, audio_minutes: 5, raw_retention_days: 30 },
};

const status: IdeaCaptureStatus = {
  config: defaultConfig,
  has_token: false,
  validation: { ok: true, errors: [] },
  serve: { command: "python -m idea_capture serve", runnable: false, blocked_reasons: [] },
  worlds: ["vibrantes"],
  limitations: [],
};

function jsonResponse(body: unknown) {
  return {
    ok: true,
    status: 200,
    json: vi.fn().mockResolvedValue(body),
    headers: new Headers(),
  };
}

describe("idea capture API", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("reads status with same-origin credentials for the local session cookie", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(status));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await getIdeaCaptureStatus();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/idea-capture/status",
      expect.objectContaining({ credentials: "same-origin" }),
    );
    expect(result.has_token).toBe(false);
  });

  it("saves the config with PUT and the config payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(status));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await saveIdeaCaptureConfig(defaultConfig);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/idea-capture/config",
      expect.objectContaining({
        method: "PUT",
        credentials: "same-origin",
        body: JSON.stringify({ config: defaultConfig }),
      }),
    );
  });

  it("sets the token with POST — the value leaves the browser only in the request body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ has_token: true }));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const token = "123456789:AA-secret";
    const result = await setIdeaCaptureToken(token);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/idea-capture/token",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        body: JSON.stringify({ token }),
      }),
    );
    // The response contract never contains the token value.
    expect(result).toEqual({ has_token: true });
    expect(JSON.stringify(result)).not.toContain(token);
  });

  it("clears the token with DELETE", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ has_token: false }));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await clearIdeaCaptureToken();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/idea-capture/token",
      expect.objectContaining({ method: "DELETE", credentials: "same-origin" }),
    );
    expect(result.has_token).toBe(false);
  });

  it("discovers chats with POST and a generous timeout (Telegram round-trip)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        ok: true,
        candidates: [{ id: 111, type: "private", kind: "private", title: "Ana" }],
        message: "",
      }),
    );
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await discoverChatCandidates();

    // apiFetch turns the timeout option into an AbortController signal.
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/idea-capture/chats/discover",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        signal: expect.any(AbortSignal),
      }),
    );
    expect(result.candidates[0].title).toBe("Ana");
  });

  it("authorizes a private chat with the internal selection id only", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ ...status, message: "Chat privado autorizado." }),
    );
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await authorizeChat({ chat_id: 222, chat_type: "private" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/idea-capture/chats/authorize",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        body: JSON.stringify({ chat_id: 222, chat_type: "private" }),
      }),
    );
    expect(result.message).toBe("Chat privado autorizado.");
  });

  it("authorizes a group only with explicit senders and confirmation", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ ...status, message: "Grupo autorizado con remitentes explícitos." }),
    );
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await authorizeChat({
      chat_id: -100,
      chat_type: "supergroup",
      sender_ids: [5, 6],
      confirm_group: true,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/idea-capture/chats/authorize",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        body: JSON.stringify({
          chat_id: -100,
          chat_type: "supergroup",
          sender_ids: [5, 6],
          confirm_group: true,
        }),
      }),
    );
  });
});
