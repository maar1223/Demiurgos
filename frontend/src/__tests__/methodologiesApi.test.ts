import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  activateMethodology,
  createMethodologyDraft,
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
});
