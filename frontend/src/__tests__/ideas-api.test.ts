import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createIdea,
  deleteIdea,
  getIdea,
  listIdeas,
  materializeIdea,
  updateIdea,
} from "@/api/ideas";
import type { IdeaDetail } from "@/api/ideas";

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
    headers: new Headers(),
  };
}

const detail: IdeaDetail = {
  id: "a1b2c3d4",
  slug: "arquero-ciego",
  timestamp: "2026-08-25T15:00:00Z",
  source: "manual",
  type: "personaje",
  title: "El Arquero Ciego",
  tags: ["arquero"],
  status: "fresh",
  used_in: [],
  based_on: null,
  body: "Un arquero que no ve.",
};

describe("ideas bank API", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lists ideas with type/status/source filters as query params", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ ideas: [detail], total: 1 }));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await listIdeas({ type: "personaje", status: "fresh" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/ideas?type=personaje&status=fresh",
      expect.objectContaining({ credentials: "same-origin" }),
    );
    expect(result.total).toBe(1);
  });

  it("lists without query params when no filters are given", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ ideas: [], total: 0 }));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await listIdeas();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/ideas",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("reads a single idea by slug", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(detail));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await getIdea("arquero-ciego");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/ideas/arquero-ciego",
      expect.objectContaining({ credentials: "same-origin" }),
    );
    expect(result.body).toBe("Un arquero que no ve.");
  });

  it("creates a manual idea with POST and the source defaulting to manual", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(detail, 201));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await createIdea({
      slug: "arquero-ciego",
      type: "personaje",
      body: "Un arquero que no ve.",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/ideas",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        body: JSON.stringify({
          slug: "arquero-ciego",
          type: "personaje",
          body: "Un arquero que no ve.",
        }),
      }),
    );
    expect(result.slug).toBe("arquero-ciego");
  });

  it("updates an idea with PATCH (type correction)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ...detail, type: "concepto" }));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await updateIdea("arquero-ciego", { type: "concepto" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/ideas/arquero-ciego",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ type: "concepto" }),
      }),
    );
    expect(result.type).toBe("concepto");
  });

  it("deletes an idea with DELETE", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ ok: true, slug: "arquero-ciego" }));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await deleteIdea("arquero-ciego");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/ideas/arquero-ciego",
      expect.objectContaining({ method: "DELETE", credentials: "same-origin" }),
    );
    expect(result.ok).toBe(true);
  });

  it("materializes an idea with POST /materialize and the world payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ ok: true, used_in: ["vibrantes"], canon_path: null }),
    );
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await materializeIdea("arquero-ciego", "vibrantes");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/ideas/arquero-ciego/materialize",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ world: "vibrantes" }),
      }),
    );
    expect(result.used_in).toEqual(["vibrantes"]);
  });

  it("materialize includes canon_rel when provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ ok: true, used_in: ["vibrantes"], canon_path: "personajes/x.md" }),
    );
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    await materializeIdea("arquero-ciego", "vibrantes", "personajes/arquero.md");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/ideas/arquero-ciego/materialize",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ world: "vibrantes", canon_rel: "personajes/arquero.md" }),
      }),
    );
  });
});