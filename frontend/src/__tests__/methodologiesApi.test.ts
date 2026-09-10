import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  activateCompanion,
  activateMethodology,
  createMethodologyDraft,
  deactivateCompanion,
  getMethodologyInventory,
  getMethodologyStatus,
  publishMethodologyDraft,
  rollbackMethodology,
} from "@/api/methodologies";
import { ApiError } from "@/api/types";

const mockApiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({ apiFetch: mockApiFetch }));

describe("methodologies API contract", () => {
  beforeEach(() => {
    mockApiFetch.mockReset().mockResolvedValue({ published: [], activations: {}, drafts: [] });
  });

  it("GET /api/methodologies/status lists published, activations and drafts", async () => {
    await getMethodologyStatus();
    expect(mockApiFetch).toHaveBeenCalledWith("/api/methodologies/status", {
      timeout: 15_000,
    });
  });

  it("POST /api/methodologies/drafts creates a draft with bounded input", async () => {
    await createMethodologyDraft({
      skill_id: "guided-character-v1",
      version: "1.2.0",
      name: "Guided character methodology",
      source: "## Construcción segura\n",
    });
    expect(mockApiFetch).toHaveBeenCalledWith("/api/methodologies/drafts", {
      method: "POST",
      body: JSON.stringify({
        skill_id: "guided-character-v1",
        version: "1.2.0",
        name: "Guided character methodology",
        source: "## Construcción segura\n",
      }),
      timeout: 15_000,
    });
  });

  it("draft-create never sends clasificacion or trust_attributes (server 400-rejects client trust claims)", async () => {
    await createMethodologyDraft({
      skill_id: "guided-character-v1",
      version: "1.2.0",
      name: "Guided character methodology",
      source: "## Construcción segura\n",
    });
    const [, options] = mockApiFetch.mock.calls[0] as [
      string,
      { body: string },
    ];
    const sentBody = JSON.parse(options.body) as Record<string, unknown>;
    // The client contract is bounded to the four editable fields — trust
    // fields are server-derived only, so the 400-reject path can never fire
    // on the real client (foundational-skills-seeding compatibility).
    expect(Object.keys(sentBody).sort()).toEqual([
      "name",
      "skill_id",
      "source",
      "version",
    ]);
    expect(sentBody).not.toHaveProperty("clasificacion");
    expect(sentBody).not.toHaveProperty("trust_attributes");
  });

  it("POST publish compiles and publishes an immutable version", async () => {
    await publishMethodologyDraft("draft-1");
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/methodologies/drafts/draft-1/publish",
      { method: "POST", timeout: 15_000 },
    );
  });

  it("POST activate pins a version to a world", async () => {
    await activateMethodology("nec", "guided-character-v1", "1.2.0");
    expect(mockApiFetch).toHaveBeenCalledWith("/api/methodologies/activate", {
      method: "POST",
      body: JSON.stringify({
        world: "nec",
        skill_id: "guided-character-v1",
        version: "1.2.0",
      }),
      timeout: 15_000,
    });
  });

  it("POST rollback restores the previous version for a world", async () => {
    await rollbackMethodology("nec");
    expect(mockApiFetch).toHaveBeenCalledWith("/api/methodologies/rollback", {
      method: "POST",
      body: JSON.stringify({ world: "nec" }),
      timeout: 15_000,
    });
  });

  it("POST companions/activate pins a published version as a world companion", async () => {
    await activateCompanion("nec", "eneagrama", "1.2.0");
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/methodologies/companions/activate",
      {
        method: "POST",
        body: JSON.stringify({
          world: "nec",
          skill_id: "eneagrama",
          version: "1.2.0",
        }),
        timeout: 15_000,
      },
    );
  });

  it("POST companions/deactivate removes a companion idempotently", async () => {
    await deactivateCompanion("nec", "eneagrama");
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/methodologies/companions/deactivate",
      {
        method: "POST",
        body: JSON.stringify({ world: "nec", skill_id: "eneagrama" }),
        timeout: 15_000,
      },
    );
  });

  it("preserves backend fail-closed errors", async () => {
    mockApiFetch.mockRejectedValue(new ApiError(
      422,
      "The draft failed compiler validation.",
      "The draft failed compiler validation.",
      "validation_error",
    ));
    await expect(publishMethodologyDraft("draft-1")).rejects.toMatchObject({
      status: 422, code: "validation_error",
    });
  });

  it("GET /api/methodologies/inventory fetches the read-only catalog", async () => {
    mockApiFetch.mockResolvedValue({ items: [] });
    await getMethodologyInventory();
    expect(mockApiFetch).toHaveBeenCalledWith("/api/methodologies/inventory", {
      timeout: 15_000,
    });
  });

  it("GET inventory appends ?clasificacion=Oficiales when filtered", async () => {
    mockApiFetch.mockResolvedValue({ items: [] });
    await getMethodologyInventory({ clasificacion: "Oficiales" });
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/methodologies/inventory?clasificacion=Oficiales",
      { timeout: 15_000 },
    );
  });

  it("GET inventory appends comma-separated ?etiquetas=lore,npc", async () => {
    mockApiFetch.mockResolvedValue({ items: [] });
    await getMethodologyInventory({ etiquetas: "lore,npc" });
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/methodologies/inventory?etiquetas=lore%2Cnpc",
      { timeout: 15_000 },
    );
  });

  it("GET inventory combines filters conjunctively", async () => {
    mockApiFetch.mockResolvedValue({ items: [] });
    await getMethodologyInventory({
      clasificacion: "Comunitarias",
      taller: "Investigación",
    });
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/methodologies/inventory?clasificacion=Comunitarias&taller=Investigaci%C3%B3n",
      { timeout: 15_000 },
    );
  });
});
