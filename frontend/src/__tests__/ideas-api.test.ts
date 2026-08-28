import { afterEach, describe, expect, it, vi } from "vitest";
import {
  attachIdeaMedia,
  confirmCapture,
  createIdea,
  deleteIdea,
  discardCapture,
  getIdea,
  getIdeaVersions,
  listIdeas,
  listPendingCaptures,
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
  updated_at: "2026-08-25T15:00:00Z",
  source: "manual",
  type: "personaje",
  title: "El Arquero Ciego",
  tags: ["arquero"],
  status: "fresh",
  used_in: [],
  based_on: null,
  media_path: null,
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

  it("fetches version history from GET /{slug}/versions (R-10, S-10.2)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        slug: "arquero-ciego",
        versions: [
          { version: 1, path: "/ideas/versions/arquero-ciego-v1.md" },
          { version: 2, path: "/ideas/versions/arquero-ciego-v2.md" },
        ],
      }),
    );
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await getIdeaVersions("arquero-ciego");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/ideas/arquero-ciego/versions",
      expect.objectContaining({ credentials: "same-origin" }),
    );
    expect(result.slug).toBe("arquero-ciego");
    expect(result.versions).toEqual([
      { version: 1, path: "/ideas/versions/arquero-ciego-v1.md" },
      { version: 2, path: "/ideas/versions/arquero-ciego-v2.md" },
    ]);
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

  it("lists pending captures from the idea-capture queue (S-7.1)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        captures: [
          {
            capture_id: "cap-1",
            slug: "2026-08-27-idea",
            raw_text: "Una idea.",
            created_at: "2026-08-27T13:00:00Z",
            event_ts: "",
            media_kind: "text",
          },
        ],
        count: 1,
      }),
    );
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await listPendingCaptures();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/idea-capture/pending",
      expect.objectContaining({ credentials: "same-origin" }),
    );
    expect(result.count).toBe(1);
    expect(result.captures[0].capture_id).toBe("cap-1");
  });

  it("confirms a pending capture with POST /confirm (S-7.2)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await confirmCapture("cap-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/idea-capture/pending/cap-1/confirm",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
      }),
    );
    expect(result.ok).toBe(true);
  });

  it("discards a pending capture with POST /discard (S-7.3)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const result = await discardCapture("cap-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/idea-capture/pending/cap-1/discard",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
      }),
    );
    expect(result.ok).toBe(true);
  });

  it("attaches media with POST /{slug}/media as multipart (raw fetch)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ ...detail, media_path: "media/arquero-ciego.png" }, 201),
    );
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const file = new File(["fakedata"], "img.png", { type: "image/png" });
    const result = await attachIdeaMedia("arquero-ciego", file);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/ideas/arquero-ciego/media");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("same-origin");
    // Multipart: body must be a FormData, never a JSON content-type.
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.headers).toBeUndefined();
    expect(result.media_path).toBe("media/arquero-ciego.png");
  });

  it("attachIdeaMedia surfaces the backend detail on error", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ detail: "El archivo está vacío." }, 400),
    );
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;

    const file = new File([], "img.png", { type: "image/png" });
    await expect(attachIdeaMedia("arquero-ciego", file)).rejects.toMatchObject({
      status: 400,
      detail: "El archivo está vacío.",
    });
  });
});