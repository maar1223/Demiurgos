import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MethodologyLibrary } from "@/components/organisms/MethodologyLibrary";
import { conflictExplanation } from "@/lib/vocabularyAxes";
import { tEs } from "@/__tests__/i18nTestUtils";
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

/** Multi-version fixture (REQ-TRE-9/10): one skill published at 1.0/1.1/1.2
 *  with 1.2 active in "nec" — the explorer must render a single row @1.2. */
const multiVersionStatus: MethodologyStatus = {
  published: [
    {
      skill_id: "multi-skill",
      version: "1.0",
      name: "Multi skill",
      description: "",
      digest: "a",
      published_at: "2026-01-01",
      taller: "Mundo",
      talleres_compatibles: [],
    },
    {
      skill_id: "multi-skill",
      version: "1.1",
      name: "Multi skill",
      description: "",
      digest: "b",
      published_at: "2026-01-01",
      taller: "Mundo",
      talleres_compatibles: [],
    },
    {
      skill_id: "multi-skill",
      version: "1.2",
      name: "Multi skill",
      description: "",
      digest: "c",
      published_at: "2026-01-01",
      taller: "Mundo",
      talleres_compatibles: [],
    },
  ],
  activations: {
    nec: {
      world: "nec",
      skill_id: "multi-skill",
      version: "1.2",
      digest: "c",
      activated_at: "2026-01-01",
    },
  },
  drafts: [],
};

/** Slimmed contract (task 2.3): the component no longer fetches — status and
 *  the selection/activation handlers come from the page. */
function renderLibrary(
  overrides: Partial<Parameters<typeof MethodologyLibrary>[0]> = {},
) {
  const props = {
    world: "nec",
    activeTaller: "Mundo",
    status,
    selected: null,
    onSelect: vi.fn(),
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

  it("shows the active info line once a version is active for the world", async () => {
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
          taller: "Mundo",
          talleres_compatibles: [],
        },
        {
          skill_id: "sk-otra-inactiva",
          version: "1.0.0",
          name: "Skill otra inactiva",
          description: "",
          digest: "b",
          published_at: "2026-01-01",
          taller: "Mundo",
          talleres_compatibles: [],
        },
        {
          skill_id: "sk-trans-inactiva",
          version: "1.0.0",
          name: "Skill transversal inactiva",
          description: "",
          digest: "c",
          published_at: "2026-01-01",
          taller: "Ideas",
          talleres_compatibles: ["Mundo"],
        },
        {
          skill_id: "sk-heredada-herramientas",
          version: "1.0.0",
          name: "Skill heredada herramientas",
          description: "",
          digest: "d",
          published_at: "2026-01-01",
          taller: "Herramientas",
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

    // A legacy Herramientas-tagged record lands in "Sin taller", never hidden
    // (REQ-TRE-5 S8 / OC-4 S3).
    expect(screen.getByText("Skill heredada herramientas")).toBeInTheDocument();

    // Attributed axis-1 chips (spec REQ-TRE-4 S1 + axis-binding-ui R1):
    // Activa → success, Inactiva → default. Scope vocabulary is no longer a
    // primary badge (R3) — the group label carries the scope.
    const activaRow = screen.getByText("Skill activa").closest(
      "li",
    ) as HTMLElement;
    expect(within(activaRow).getByText("Activa")).toHaveClass(
      "text-status-success",
    );
    expect(
      within(activaRow).getByText("Activa").closest("[data-axis]"),
    ).toHaveAttribute("data-axis", "activation");

    const inactivaRow = screen.getByText("Skill otra inactiva").closest(
      "li",
    ) as HTMLElement;
    expect(within(inactivaRow).getByText("Inactiva")).toHaveClass(
      "text-primary",
    );
    expect(
      within(inactivaRow).getByText("Inactiva").closest("[data-axis]"),
    ).toHaveAttribute("data-axis", "activation");

    const transRow = screen.getByText("Skill transversal inactiva").closest(
      "li",
    ) as HTMLElement;
    expect(within(transRow).getByText("Inactiva")).toHaveClass(
      "text-primary",
    );
    expect(
      within(transRow).getByText("Inactiva").closest("[data-axis]"),
    ).toHaveAttribute("data-axis", "activation");
    expect(within(transRow).queryByText("Transversal")).not.toBeInTheDocument();
  });

  it("shows the blocked explanation tooltip — no row action renders (REQ-TRE-6 S1)", async () => {
    const blockedStatus: MethodologyStatus = {
      published: [
        {
          skill_id: "sk-ideas-activa",
          version: "1.0.0",
          name: "Skill ideas activa",
          description: "",
          digest: "f",
          published_at: "2026-01-01",
          taller: "Ideas",
          talleres_compatibles: ["Mundo"],
        },
        {
          skill_id: "sk-ideas-bloqueada",
          version: "1.0.0",
          name: "Skill ideas bloqueada",
          description: "",
          digest: "g",
          published_at: "2026-01-01",
          taller: "Ideas",
          talleres_compatibles: ["Mundo"],
        },
      ],
      activations: {
        nec: {
          world: "nec",
          skill_id: "sk-ideas-activa",
          version: "1.0.0",
          digest: "f",
          activated_at: "2026-01-01",
        },
      },
      drafts: [],
    };
    renderLibrary({ status: blockedStatus });

    await waitFor(() => {
      expect(screen.getByText("Skill ideas bloqueada")).toBeInTheDocument();
    });

    // En uso de otros talleres comes before En conflicto (TW3 order + 5th group).
    const headings = screen.getAllByRole("heading", {
      name: /En uso · funciona también en otros talleres|En conflicto · su taller de origen ya tiene una activa/,
    });
    expect(headings.map((h) => h.textContent)).toEqual([
      "En uso · funciona también en otros talleres",
      "En conflicto · su taller de origen ya tiene una activa",
    ]);

    // Conflict copy bound to the registry builder (the shared tooltip + panel
    // source, REQ-TRE-6 S1 + axis-binding-ui R3): taller names interpolated
    // via OPERATIONAL_TALLER_LABELS (display labels, not short keys) — this
    // row-surface assertion breaks if the registry copy drifts from spec.
    const blockedRow = screen.getByText("Skill ideas bloqueada").closest(
      "li",
    ) as HTMLElement;
    const blockedTooltip = blockedRow.querySelector(
      '[role="tooltip"]',
    ) as HTMLElement | null;
    expect(blockedTooltip).not.toBeNull();
    expect(
      within(blockedTooltip as HTMLElement).getByText(
        conflictExplanation("Mundo", "Ideas", tEs),
      ),
    ).toBeInTheDocument();

    // No "Bloqueada" primary badge (R3): conflict vocabulary lives in the
    // tooltip only.
    expect(within(blockedRow).queryByText("Bloqueada")).not.toBeInTheDocument();

    // Rows are selection + information only: no disabled Adaptar action
    // renders on the tree (actions live in the right MethodologyStatePanel).
    expect(
      within(blockedRow).queryByRole("button", { name: "Adaptar" }),
    ).not.toBeInTheDocument();
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

  it("renders exactly one row per skill_id with the representative version (REQ-TRE-9/10)", async () => {
    renderLibrary({ status: multiVersionStatus });

    await waitFor(() => {
      expect(screen.getByText("Multi skill")).toBeInTheDocument();
    });

    // One row, not one per published version.
    expect(screen.getAllByText("Multi skill")).toHaveLength(1);
    const row = screen.getByText("Multi skill").closest("li") as HTMLElement;
    expect(within(row).getByText(/multi-skill@1\.2/)).toBeInTheDocument();
    expect(screen.getAllByText("Activa")).toHaveLength(1);
    expect(within(row).getByText(/Activa en nec/)).toBeInTheDocument();
  });

  it("keeps a non-representative selection and its row highlight while filtered in (REQ-TRE-12 S8)", async () => {
    const user = userEvent.setup();
    const props = renderLibrary({
      status: multiVersionStatus,
      selected: { skill_id: "multi-skill", version: "1.0" },
    });
    await waitFor(() => {
      expect(screen.getByText("Multi skill")).toBeInTheDocument();
    });

    // A query that keeps the selected skill visible must NOT reset selection,
    // and the single representative row stays highlighted (skill-level match).
    await user.type(screen.getByRole("searchbox"), "Multi");
    const row = screen.getByText("Multi skill").closest("li") as HTMLElement;
    expect(row).toHaveClass("border-action");
    expect(row).toHaveClass("ring-1");
    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it("clears a filtered-out multi-version selection (REQ-TRE-12 S9)", async () => {
    const user = userEvent.setup();
    const props = renderLibrary({
      status: multiVersionStatus,
      selected: { skill_id: "multi-skill", version: "1.0" },
    });
    await waitFor(() => {
      expect(screen.getByText("Multi skill")).toBeInTheDocument();
    });

    await user.type(screen.getByRole("searchbox"), "zzz");
    expect(await screen.findByText("Sin resultados")).toBeInTheDocument();
    await waitFor(() => {
      expect(props.onSelect).toHaveBeenCalledWith(null);
    });
  });

  it("keeps the single-version selection behavior unchanged (REQ-TRE-12 S10)", async () => {
    const user = userEvent.setup();
    const props = renderLibrary({
      selected: { skill_id: "guided-character-v1", version: "1.2.0" },
    });
    await waitFor(() => {
      expect(screen.getByText("Guided character methodology")).toBeInTheDocument();
    });

    await user.type(screen.getByRole("searchbox"), "Guided");
    const row = screen.getByText("Guided character methodology").closest(
      "li",
    ) as HTMLElement;
    expect(row).toHaveClass("border-action");
    expect(row).toHaveClass("ring-1");
    expect(props.onSelect).not.toHaveBeenCalled();
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