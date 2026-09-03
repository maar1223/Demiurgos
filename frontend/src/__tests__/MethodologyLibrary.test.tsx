import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
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

function renderLibrary(world?: string, activeTaller = "Herramientas") {
  return render(
    <MethodologyLibrary world={world} activeTaller={activeTaller} />,
  );
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

  it("renders tree groups in TW3 order with the correct badge variants", async () => {
    const fullStatus: MethodologyStatus = {
      published: [
        {
          skill_id: "sk-activa",
          version: "1.0.0",
          name: "Skill activa",
          description: "",
          digest: "a",
          published_at: "2026-01-01",
          taller: "Herramientas",
          talleres_compatibles: [],
        },
        {
          skill_id: "sk-otra-inactiva",
          version: "1.0.0",
          name: "Skill otra inactiva",
          description: "",
          digest: "b",
          published_at: "2026-01-01",
          taller: "Herramientas",
          talleres_compatibles: [],
        },
        {
          skill_id: "sk-trans-inactiva",
          version: "1.0.0",
          name: "Skill transversal inactiva",
          description: "",
          digest: "c",
          published_at: "2026-01-01",
          taller: "Mundo",
          talleres_compatibles: ["Herramientas"],
        },
        {
          skill_id: "sk-idea-oculta",
          version: "1.0.0",
          name: "Skill idea oculta",
          description: "",
          digest: "d",
          published_at: "2026-01-01",
          taller: "Ideas",
          talleres_compatibles: [],
        },
        {
          skill_id: "sk-sin-taller",
          version: "1.0.0",
          name: "Skill sin taller",
          description: "",
          digest: "e",
          published_at: "2026-01-01",
        },
      ],
      activations: {
        nec: {
          world: "nec",
          skill_id: "sk-activa",
          version: "1.0.0",
          digest: "a",
          activated_at: "2026-01-01",
        },
      },
      drafts: [],
    };
    mockGetStatus.mockResolvedValue(fullStatus);
    renderLibrary("nec");

    await waitFor(() => {
      expect(screen.getByText("Skill activa")).toBeInTheDocument();
    });

    // TW3 order (spec REQ-TRE-3 S1): Activas → Inactivas → Transversales
    // inactivas → Sin taller. Transversales activas and Bloqueadas are empty
    // → hidden (REQ-TRE-3 S3).
    const headings = screen.getAllByRole("heading", {
      name: /Activas del Taller|Inactivas del Taller|Transversales inactivas|Sin taller/,
    });
    expect(headings.map((h) => h.textContent)).toEqual([
      "Activas del Taller",
      "Inactivas del Taller",
      "Transversales inactivas",
      "Sin taller",
    ]);

    // Not a transversal of Herramientas → hidden (TW2, REQ-TRE-5 S6).
    expect(screen.queryByText("Skill idea oculta")).not.toBeInTheDocument();

    // Badge variants (spec REQ-TRE-4 S1): Activa → success, Inactiva →
    // default, Transversal → info.
    const activaRow = screen.getByText("Skill activa").closest(
      "li",
    ) as HTMLElement;
    expect(within(activaRow).getByText("Activa")).toHaveClass(
      "text-status-success",
    );

    const inactivaRow = screen.getByText("Skill otra inactiva").closest(
      "li",
    ) as HTMLElement;
    expect(within(inactivaRow).getByText("Inactiva")).toHaveClass(
      "text-primary",
    );

    const transRow = screen.getByText("Skill transversal inactiva").closest(
      "li",
    ) as HTMLElement;
    expect(within(transRow).getByText("Transversal")).toHaveClass(
      "text-icon-muted",
    );
  });

  it("shows the blocked explanation and a disabled Adaptar action", async () => {
    const blockedStatus: MethodologyStatus = {
      published: [
        {
          skill_id: "sk-mundo-activa",
          version: "1.0.0",
          name: "Skill mundo activa",
          description: "",
          digest: "f",
          published_at: "2026-01-01",
          taller: "Mundo",
          talleres_compatibles: ["Herramientas"],
        },
        {
          skill_id: "sk-mundo-bloqueada",
          version: "1.0.0",
          name: "Skill mundo bloqueada",
          description: "",
          digest: "g",
          published_at: "2026-01-01",
          taller: "Mundo",
          talleres_compatibles: ["Herramientas"],
        },
      ],
      activations: {
        nec: {
          world: "nec",
          skill_id: "sk-mundo-activa",
          version: "1.0.0",
          digest: "f",
          activated_at: "2026-01-01",
        },
      },
      drafts: [],
    };
    mockGetStatus.mockResolvedValue(blockedStatus);
    renderLibrary("nec");

    await waitFor(() => {
      expect(screen.getByText("Skill mundo bloqueada")).toBeInTheDocument();
    });

    // Transversales activas comes before Bloqueadas (TW3 order + 5th group).
    const headings = screen.getAllByRole("heading", {
      name: /Transversales activas|Bloqueadas/,
    });
    expect(headings.map((h) => h.textContent)).toEqual([
      "Transversales activas",
      "Bloqueadas",
    ]);

    // Exact conflict copy from spec REQ-TRE-6 S1, taller names interpolated
    // via CORE_TALLER_LABELS (display labels, not short keys).
    expect(
      screen.getByText(
        "This skill is a transversal of Taller de Herramientas but its primary taller (Taller de Mundo) already has an active skill in this world. Adapt the skill to resolve the conflict or activate it in a different world.",
      ),
    ).toBeInTheDocument();

    const blockedRow = screen.getByText("Skill mundo bloqueada").closest(
      "li",
    ) as HTMLElement;
    expect(within(blockedRow).getByText("Bloqueada")).toHaveClass(
      "text-status-error",
    );

    // Adaptar is disabled with the future-phase tooltip (REQ-TRE-6 S2).
    const adaptar = screen.getByRole("button", { name: "Adaptar" });
    expect(adaptar).toBeDisabled();
    expect(adaptar).toHaveAttribute(
      "title",
      "Adaptation available in future phase",
    );
  });
});
