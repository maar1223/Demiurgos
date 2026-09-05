import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MethodologyLibrary } from "@/components/organisms/MethodologyLibrary";
import type { MethodologyStatus } from "@/api/types";

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

/** Slimmed contract (task 2.3): the component no longer fetches — status and
 *  the selection/activation handlers come from the page. */
function renderLibrary(
  overrides: Partial<Parameters<typeof MethodologyLibrary>[0]> = {},
) {
  const props = {
    world: "nec",
    activeTaller: "Herramientas",
    status,
    selected: null,
    onSelect: vi.fn(),
    onActivate: vi.fn(),
    busy: false,
  };
  render(<MethodologyLibrary {...props} {...overrides} />);
  return props;
}

describe("MethodologyLibrary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders published versions from the library status", async () => {
    renderLibrary();
    await waitFor(() => {
      expect(screen.getByText("Guided character methodology")).toBeInTheDocument();
    });
    expect(screen.getByText(/guided-character-v1@1\.2\.0/)).toBeInTheDocument();
  });

  it("shows the empty state when nothing is published", async () => {
    renderLibrary({
      status: { published: [], activations: {}, drafts: [] },
    });
    await waitFor(() => {
      expect(screen.getByText(/Todavía no hay metodologías publicadas/)).toBeInTheDocument();
    });
  });

  it("activates a version for the selected world through the page handler", async () => {
    const user = userEvent.setup();
    const props = renderLibrary();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Activar" })).toBeEnabled();
    });

    await user.click(screen.getByRole("button", { name: "Activar" }));
    await waitFor(() => {
      expect(props.onActivate).toHaveBeenCalledWith(
        "guided-character-v1", "1.2.0",
      );
    });
  });

  it("disables activate without a selected world", async () => {
    renderLibrary({ world: undefined });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Sin mundo" })).toBeDisabled();
    });
  });

  it("shows the active badge once a version is active for the world", async () => {
    renderLibrary({
      status: {
        ...status,
        activations: {
          nec: {
            world: "nec", skill_id: "guided-character-v1", version: "1.2.0",
            digest: "abc", activated_at: "2026-01-01",
          },
        },
      },
    });
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
    renderLibrary({ status: fullStatus });

    await waitFor(() => {
      expect(screen.getByText("Skill activa")).toBeInTheDocument();
    });

    // TW3 order (spec REQ-TRE-3 S1): En uso → Apagada → Apagada de otros
    // talleres → Sin taller. En uso de otros talleres and En conflicto are
    // empty → hidden (REQ-TRE-3 S3).
    const headings = screen.getAllByRole("heading", {
      name: /En uso · funciona solo en este taller|Apagada · funciona solo en este taller|Apagada · funciona también en otros talleres|Sin taller/,
    });
    expect(headings.map((h) => h.textContent)).toEqual([
      "En uso · funciona solo en este taller",
      "Apagada · funciona solo en este taller",
      "Apagada · funciona también en otros talleres",
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
    renderLibrary({ status: blockedStatus });

    await waitFor(() => {
      expect(screen.getByText("Skill mundo bloqueada")).toBeInTheDocument();
    });

    // En uso de otros talleres comes before En conflicto (TW3 order + 5th group).
    const headings = screen.getAllByRole("heading", {
      name: /En uso · funciona también en otros talleres|En conflicto · su taller de origen ya tiene una activa/,
    });
    expect(headings.map((h) => h.textContent)).toEqual([
      "En uso · funciona también en otros talleres",
      "En conflicto · su taller de origen ya tiene una activa",
    ]);

    // Exact conflict copy from spec REQ-TRE-6 S1, taller names interpolated
    // via CORE_TALLER_LABELS (display labels, not short keys).
    expect(
      screen.getByText(
        "Esta skill es transversal de Taller de Herramientas pero su taller primario (Taller de Mundo) ya tiene una skill activa en este mundo. Adaptá la skill para resolver el conflicto o activala en otro mundo.",
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
      "Adaptación disponible en fase futura",
    );
  });

  it("preserves the selection while the filtered row stays visible (SC-SB-2.3)", async () => {
    const user = userEvent.setup();
    const props = renderLibrary({
      selected: { skill_id: "guided-character-v1", version: "1.2.0" },
    });
    await waitFor(() => {
      expect(screen.getByText("Guided character methodology")).toBeInTheDocument();
    });

    // A filter that keeps the selected row visible must NOT reset selection.
    await user.type(screen.getByRole("searchbox"), "Guided");
    expect(screen.getByText("Guided character methodology")).toBeInTheDocument();
    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it("clears the selection when the query filters the selected row out (SC-SB-2.3)", async () => {
    const user = userEvent.setup();
    const props = renderLibrary({
      selected: { skill_id: "guided-character-v1", version: "1.2.0" },
    });
    await waitFor(() => {
      expect(screen.getByText("Guided character methodology")).toBeInTheDocument();
    });

    // A filter that hides the selected row clears the selection.
    await user.type(screen.getByRole("searchbox"), "zzz");
    expect(await screen.findByText("Sin resultados")).toBeInTheDocument();
    await waitFor(() => {
      expect(props.onSelect).toHaveBeenCalledWith(null);
    });
  });

  it("renders the empty-state CTA wired to onGoToCoCrear (UL-5)", async () => {
    const user = userEvent.setup();
    const onGoToCoCrear = vi.fn();
    renderLibrary({
      status: { published: [], activations: {}, drafts: [] },
      onGoToCoCrear,
    });

    // Zero published skills → the empty state offers the "Crear tu primera
    // skill" CTA (spec UL-5 S1); clicking it reports the navigation upward.
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Crear tu primera skill" }),
      ).toBeInTheDocument();
    });
    await user.click(
      screen.getByRole("button", { name: "Crear tu primera skill" }),
    );
    expect(onGoToCoCrear).toHaveBeenCalledTimes(1);
  });
});