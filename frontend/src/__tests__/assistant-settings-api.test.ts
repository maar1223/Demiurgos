import { afterEach, describe, expect, it, vi } from "vitest";
import {
  clearAssistantKey,
  discoverAssistantModels,
  getAssistantSettings,
  saveAssistantConfiguration,
  validateAssistantConnection,
} from "@/api/assistantSettings";
import type { AssistantSettingsStatus } from "@/api/types";

const status: AssistantSettingsStatus = {
  provider: "opencode-go",
  base_url: "https://opencode.ai/zen/go/v1",
  model: "gpt-5.6-luna",
  model_metadata: {
    id: "gpt-5.6-luna",
    label: "GPT-5.6 Luna",
    capability: "unknown",
    pricing: null,
  },
  key_configured: true,
  models: [{ id: "gpt-5.6-luna", label: "GPT-5.6 Luna", capability: "unknown", pricing: null }],
  active_profile: "default",
  revision: 2,
  runtime_state: "active",
};

function jsonResponse(body: unknown) {
  return {
    ok: true,
    status: 200,
    json: vi.fn().mockResolvedValue(body),
    headers: new Headers(),
  };
}

describe("assistant settings API", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reads presence-only metadata with same-origin credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(status));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await getAssistantSettings();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/profile/assistant",
      expect.objectContaining({ credentials: "same-origin" }),
    );
    expect(result).toEqual(status);
    expect(JSON.stringify(result)).not.toContain("api_key");
  });

  it("validates a connection without putting credentials in the URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(status));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await validateAssistantConnection({
      provider: "openai",
      base_url: "https://api.openai.com/v1",
      api_key: "",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/profile/assistant/connection/validate",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
      }),
    );
    expect(fetchMock.mock.calls[0][0]).not.toContain("api_key");
  });

  it("discovers models and saves normalized metadata through provider-neutral routes", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ outcome: "discovered", models: status.models }))
      .mockResolvedValueOnce(jsonResponse(status));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
    const candidate = { provider: "openai", base_url: "https://api.openai.com/v1", api_key: "" };

    await discoverAssistantModels(candidate);
    await saveAssistantConfiguration({
      ...candidate,
      model: status.model_metadata,
      revision: status.revision,
      unknown_ack: true,
    });

    expect(fetchMock.mock.calls[0][0]).toBe("/api/profile/assistant/models/discover");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/profile/assistant/configuration");
    expect(JSON.stringify(status)).not.toContain("api_key");
  });

  it("clears the key with DELETE", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ...status, key_configured: false }));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await clearAssistantKey();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/profile/assistant/configuration/key",
      expect.objectContaining({ method: "DELETE", credentials: "same-origin" }),
    );
    expect(result.key_configured).toBe(false);
  });
});
