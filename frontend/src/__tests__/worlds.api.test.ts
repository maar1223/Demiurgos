import { afterEach, describe, expect, it, vi } from "vitest";
import {
  deleteWorld,
  listTrash,
  permanentDelete,
  restoreWorld,
} from "@/api/worlds";
import { ApiError, type WorldTrashEntry } from "@/api/types";

const entry: WorldTrashEntry = {
  world_name: "Avalor",
  deleted_at: "2026-08-22T10:00:00Z",
  size_bytes: 1024000,
  lore_count: 42,
  character_count: 15,
  days_remaining: 28,
};

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
    headers: new Headers(),
  };
}

describe("worlds API client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("deletes a world with DELETE and the confirm_name body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(entry));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await deleteWorld("Avalor", "AVALOR");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/worlds/Avalor",
      expect.objectContaining({
        method: "DELETE",
        credentials: "same-origin",
        body: JSON.stringify({ confirm_name: "AVALOR" }),
      }),
    );
    expect(result).toEqual(entry);
  });

  it("encodes the world name in the delete URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(entry));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await deleteWorld("Mi Mundo", "MI MUNDO");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/worlds/Mi%20Mundo",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("propagates a confirm_name mismatch as a typed ApiError with the backend code", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        { detail: "El nombre de confirmación no coincide", code: "confirm_name_mismatch" },
        400,
      ),
    );
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await expect(deleteWorld("Avalor", "WRONG")).rejects.toMatchObject({
      name: "ApiError",
      status: 400,
      code: "confirm_name_mismatch",
    });
  });

  it("lists trash entries from GET /api/worlds/trash", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([entry]));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await listTrash();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/worlds/trash",
      expect.objectContaining({ credentials: "same-origin" }),
    );
    expect(result).toEqual([entry]);
  });

  it("restores a world with POST /api/worlds/{name}/restore", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ status: "restored", world_name: "Avalor" }));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await expect(restoreWorld("Avalor")).resolves.toEqual({
      status: "restored",
      world_name: "Avalor",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/worlds/Avalor/restore",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
      }),
    );
  });

  it("permanently deletes with DELETE /api/worlds/trash/{name}", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ status: "purged", world_name: "Avalor" }));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await expect(permanentDelete("Avalor")).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/worlds/trash/Avalor",
      expect.objectContaining({
        method: "DELETE",
        credentials: "same-origin",
      }),
    );
  });

  it("rejects with ApiError when the server is unreachable", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await expect(listTrash()).rejects.toBeInstanceOf(ApiError);
  });
});