import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/api/client", () => ({
  apiFetch: vi.fn(),
}));

// The REAL graph module runs against the mocked transport: the tests prove
// the URL and query params without a server.
import { apiFetch } from "@/api/client";
import { fetchGraphEntities } from "@/api/graph";

const mockApiFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

describe("graph API — fetchGraphEntities (BLOQUE 4)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("defaults the status filter to all", async () => {
    mockApiFetch.mockResolvedValue({ entities: [], links: [] });
    await fetchGraphEntities("vibrantes");
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/vibrantes/graph/entities?status=all",
    );
  });

  it("passes the status filter through as a query param", async () => {
    mockApiFetch.mockResolvedValue({ entities: [], links: [] });
    await fetchGraphEntities("vibrantes", "stable");
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/vibrantes/graph/entities?status=stable",
    );
  });

  it("resolves the full entities + links payload", async () => {
    const payload = {
      entities: [
        {
          id: "Sistema Stal::Rhyz",
          name: "Rhyz",
          type: "personaje",
          path: "personajes/Rhyz.md",
          status: "stable",
          description: "",
          tags: [],
          forward_links: [],
          backlinks: [],
        },
      ],
      links: [],
    };
    mockApiFetch.mockResolvedValue(payload);
    const result = await fetchGraphEntities("vibrantes", "draft");
    expect(result).toEqual(payload);
    expect(result.entities[0].status).toBe("stable");
  });
});