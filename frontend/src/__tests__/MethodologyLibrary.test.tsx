import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MethodologyLibrary } from "@/components/organisms/MethodologyLibrary";
import type { MethodologyStatus } from "@/api/types";

const mockGetStatus = vi.hoisted(() => vi.fn());
const mockCreateDraft = vi.hoisted(() => vi.fn());
const mockPublish = vi.hoisted(() => vi.fn());
const mockActivate = vi.hoisted(() => vi.fn());

vi.mock("@/api/methodologies", () => ({
  getMethodologyStatus: mockGetStatus,
  createMethodologyDraft: mockCreateDraft,
  publishMethodologyDraft: mockPublish,
  activateMethodology: mockActivate,
}));

const status: MethodologyStatus = {
  published: [
    {
      skill_id: "guided-character-v1",
      version: "1.2.0",
      name: "Guided character methodology",
      description: "",
      digest: "abc",
      published_at: "2026-01-01",
    },
  ],
  activations: {},
  drafts: [],
};

function renderLibrary(world?: string) {
  return render(<MethodologyLibrary world={world} />);
}

describe("MethodologyLibrary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetStatus.mockResolvedValue(status);
    mockCreateDraft.mockResolvedValue({ draft_id: "draft-1" });
    mockPublish.mockResolvedValue(status.published[0]);
    mockActivate.mockResolvedValue({
      world: "nec", skill_id: "guided-character-v1", version: "1.2.0",
      digest: "abc", activated_at: "2026-01-01",
    });
  });

  it("renders published versions from the library status", async () => {
    renderLibrary("nec");
    await waitFor(() => {
      expect(screen.getByText("Guided character methodology")).toBeInTheDocument();
    });
    expect(screen.getByText(/guided-character-v1@1\.2\.0/)).toBeInTheDocument();
    expect(mockGetStatus).toHaveBeenCalledWith();
  });

  it("shows the empty state when nothing is published", async () => {
    mockGetStatus.mockResolvedValue({ published: [], activations: {}, drafts: [] });
    renderLibrary("nec");
    await waitFor(() => {
      expect(screen.getByText(/Todavía no hay metodologías publicadas/)).toBeInTheDocument();
    });
  });

  it("publishes a draft through create + publish and reloads", async () => {
    const user = userEvent.setup();
    renderLibrary("nec");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Publicar borrador" })).toBeEnabled();
    });

    await user.type(screen.getByLabelText("Skill ID"), "guided-character-v1");
    await user.type(screen.getByLabelText("Versión"), "1.3.0");
    await user.type(screen.getByLabelText("Nombre"), "Nueva metodología");
    await user.type(screen.getByLabelText(/Fuente/), "## Seguro\n");
    await user.click(screen.getByRole("button", { name: "Publicar borrador" }));

    await waitFor(() => {
      expect(mockCreateDraft).toHaveBeenCalledWith({
        skill_id: "guided-character-v1",
        version: "1.3.0",
        name: "Nueva metodología",
        source: "## Seguro\n",
      });
    });
    expect(mockPublish).toHaveBeenCalledWith("draft-1");
    expect(mockGetStatus).toHaveBeenCalledTimes(2);
  });

  it("activates a version for the selected world", async () => {
    const user = userEvent.setup();
    renderLibrary("nec");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Activar" })).toBeEnabled();
    });

    await user.click(screen.getByRole("button", { name: "Activar" }));
    await waitFor(() => {
      expect(mockActivate).toHaveBeenCalledWith(
        "nec", "guided-character-v1", "1.2.0",
      );
    });
    expect(mockGetStatus).toHaveBeenCalledTimes(2);
  });

  it("disables activate without a selected world", async () => {
    renderLibrary();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Sin mundo" })).toBeDisabled();
    });
  });

  it("shows the active badge once a version is active for the world", async () => {
    mockGetStatus.mockResolvedValue({
      ...status,
      activations: {
        nec: {
          world: "nec", skill_id: "guided-character-v1", version: "1.2.0",
          digest: "abc", activated_at: "2026-01-01",
        },
      },
    });
    renderLibrary("nec");
    await waitFor(() => {
      expect(screen.getByText(/Activa en nec/)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Activada" })).toBeDisabled();
  });
});
