import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { TallerTree } from "@/components/organisms/TallerTree";
import type { GroupedSkills } from "@/lib/tallerStates";
import type { PublishedMethodology } from "@/api/types";
import { NO_ACTIVATION_PLACEHOLDER } from "@/lib/vocabularyAxes";

const skillA: PublishedMethodology = {
  skill_id: "skill-a",
  version: "1.0.0",
  name: "Skill A",
  description: "",
  digest: "abc",
  published_at: "2026-01-01",
  taller: "Mundo",
};

const skillB: PublishedMethodology = {
  skill_id: "skill-b",
  version: "2.0.0",
  name: "Skill B",
  description: "",
  digest: "def",
  published_at: "2026-01-01",
  taller: "Mundo",
};

const skillC: PublishedMethodology = {
  skill_id: "skill-c",
  version: "3.0.0",
  name: "Skill C",
  description: "",
  digest: "ghi",
  published_at: "2026-01-01",
  taller: "Ideas",
  talleres_compatibles: ["Mundo"],
};

const skillD: PublishedMethodology = {
  skill_id: "skill-d",
  version: "4.0.0",
  name: "Skill D",
  description: "",
  digest: "jkl",
  published_at: "2026-01-01",
  taller: "Ideas",
  talleres_compatibles: ["Mundo"],
};

const groups: GroupedSkills = {
  activas: [skillA],
  transversalesActivas: [],
  inactivas: [skillB],
  transversalesInactivas: [],
  bloqueadas: [],
  sinTaller: [],
};

function renderTree(
  overrides: Partial<Parameters<typeof TallerTree>[0]> = {},
) {
  const props = {
    groups,
    world: "nec",
    activeTaller: "Mundo",
    ...overrides,
  };
  render(<TallerTree {...props} />);
  return props;
}

describe("TallerTree selection (SC-SB-2.1)", () => {
  it("calls onSelect with skill_id and version when a row is clicked", () => {
    const onSelect = vi.fn();
    renderTree({ onSelect, selected: null });

    fireEvent.click(screen.getByText("Skill A"));
    expect(onSelect).toHaveBeenCalledWith("skill-a", "1.0.0");

    fireEvent.click(screen.getByText("Skill B"));
    expect(onSelect).toHaveBeenCalledWith("skill-b", "2.0.0");
  });

  it("stays non-interactive when onSelect is omitted", () => {
    renderTree();
    expect(() => fireEvent.click(screen.getByText("Skill A"))).not.toThrow();
  });

  it("highlights the row matching the selected prop", () => {
    renderTree({
      onSelect: vi.fn(),
      selected: { skill_id: "skill-a", version: "1.0.0" },
    });

    const selectedRow = screen.getByText("Skill A").closest("li");
    expect(selectedRow).toHaveClass("border-action/50");

    const otherRow = screen.getByText("Skill B").closest("li");
    expect(otherRow).not.toHaveClass("border-action/50");
  });

  it("highlights the row when the selected version is not the rendered one (REQ-TRE-12)", () => {
    renderTree({
      onSelect: vi.fn(),
      selected: { skill_id: "skill-a", version: "9.9.9" },
    });

    const selectedRow = screen.getByText("Skill A").closest("li");
    expect(selectedRow).toHaveClass("border-action/50");

    const otherRow = screen.getByText("Skill B").closest("li");
    expect(otherRow).not.toHaveClass("border-action/50");
  });

  it("omits the active info line when the activation version is stale (REQ-TRE-10 S5)", () => {
    renderTree({
      active: {
        world: "nec",
        skill_id: "skill-a",
        version: "9.9.9",
        digest: "abc",
        activated_at: "2026-01-01",
      },
    });

    // `isActive` stays version-exact: a stale activation never renders
    // "• Activa en nec" on the representative row.
    expect(screen.queryByText(/Activa en nec/)).not.toBeInTheDocument();
  });
});

describe("axis-attributed row chips (axis-binding-ui R1/R2/R3)", () => {
  const activeA = {
    world: "nec",
    skill_id: "skill-a",
    version: "1.0.0",
    digest: "abc",
    activated_at: "2026-01-01",
  };

  function rowOf(name: string): HTMLElement {
    return screen.getByText(name).closest("li") as HTMLElement;
  }

  it("renders slot and companion as separate attributed chips (Row inspection)", () => {
    renderTree({
      active: activeA,
      companions: [
        {
          world: "nec",
          skill_id: "skill-a",
          version: "1.0.0",
          description: "",
          activated_at: "2026-01-01",
        },
      ],
    });

    const row = rowOf("Skill A");
    const slotChip = within(row).getByText("Activa").closest("[data-axis]");
    expect(slotChip).toHaveAttribute("data-axis", "activation");

    const companionChip = within(row)
      .getByText("Método en chat")
      .closest("[data-axis]");
    expect(companionChip).toHaveAttribute("data-axis", "companion");
  });

  it("separates slot and companion attribution — bare Inactiva + Método en chat impossible (Companion not active)", () => {
    renderTree({
      active: activeA,
      companions: [
        {
          world: "nec",
          skill_id: "skill-b",
          version: "2.0.0",
          description: "",
          activated_at: "2026-01-01",
        },
      ],
    });

    const row = rowOf("Skill B");
    const slotChip = within(row).getByText("Inactiva").closest("[data-axis]");
    expect(slotChip).toHaveAttribute("data-axis", "activation");

    const companionChip = within(row)
      .getByText("Método en chat")
      .closest("[data-axis]");
    expect(companionChip).toHaveAttribute("data-axis", "companion");

    // The two axis terms never merge into a single mixed badge (§5:122).
    expect(screen.queryByText("Inactiva Método en chat")).not.toBeInTheDocument();
  });

  it("renders the conflict copy only inside the row tooltip — no Bloqueada badge (Blocked conflict via tooltip)", () => {
    renderTree({
      groups: { ...groups, activas: [], inactivas: [], bloqueadas: [skillC] },
      active: activeA,
    });

    const row = rowOf("Skill C");
    expect(within(row).queryByText("Bloqueada")).not.toBeInTheDocument();

    const tooltip = row.querySelector('[role="tooltip"]') as HTMLElement;
    expect(tooltip).not.toBeNull();
    expect(
      within(tooltip).getByText(
        "Esta skill es transversal de Taller de Mundo pero su taller primario (Taller de Ideas) ya tiene una skill activa en este mundo. Adapta la skill para resolver el conflicto o actívala en otro mundo.",
      ),
    ).toBeInTheDocument();
  });

  it("maps each state to an attributed axis-1/2 chip; scope/conflict never a primary badge (S1 — Badge variant mapping)", () => {
    renderTree({
      groups: {
        ...groups,
        inactivas: [skillB],
        transversalesInactivas: [skillD],
      },
      active: activeA,
    });

    const activaRow = rowOf("Skill A");
    expect(within(activaRow).getByText("Activa")).toHaveClass(
      "text-status-success",
    );
    expect(
      within(activaRow).getByText("Activa").closest("[data-axis]"),
    ).toHaveAttribute("data-axis", "activation");

    const inactivaRow = rowOf("Skill B");
    expect(within(inactivaRow).getByText("Inactiva")).toHaveClass(
      "text-primary",
    );
    expect(
      within(inactivaRow).getByText("Inactiva").closest("[data-axis]"),
    ).toHaveAttribute("data-axis", "activation");

    const transversalRow = rowOf("Skill D");
    expect(within(transversalRow).getByText("Inactiva")).toHaveClass(
      "text-primary",
    );
    expect(
      within(transversalRow).getByText("Inactiva").closest("[data-axis]"),
    ).toHaveAttribute("data-axis", "activation");
    expect(within(transversalRow).queryByText("Transversal")).not.toBeInTheDocument();
  });

  it("reads flow_type at model level without committing per-flow copy (Flow attribution without copy)", () => {
    renderTree({
      active: { ...activeA, flow_type: "guided-character" },
    });

    const row = rowOf("Skill A");
    expect(within(row).getByText("Activa").closest("[data-axis]")).toHaveAttribute(
      "data-axis",
      "activation",
    );

    // The flow value is model-level only — never rendered as display copy (R6).
    expect(screen.queryByText("guided-character")).not.toBeInTheDocument();
  });
});

describe("no-activation slot and row actions removed (axis-binding-ui R4 / actions live in the right panel)", () => {
  it("renders a neutral placeholder for the no-activation slot — never Inactiva (No-activation slot renders)", () => {
    renderTree();

    const row = screen.getByText("Skill B").closest("li") as HTMLElement;
    expect(within(row).queryByText("Inactiva")).not.toBeInTheDocument();

    const placeholder = within(row)
      .getByText(NO_ACTIVATION_PLACEHOLDER)
      .closest("[data-axis]");
    expect(placeholder).toHaveAttribute("data-axis", "activation");
  });

  it("renders no action buttons on rows — Activar/Activada/Sin mundo/Adaptar live in the right panel", () => {
    renderTree({
      groups: { ...groups, activas: [], inactivas: [], bloqueadas: [skillC] },
      active: {
        world: "nec",
        skill_id: "skill-a",
        version: "1.0.0",
        digest: "abc",
        activated_at: "2026-01-01",
      },
    });

    // Blocked rows keep the conflict tooltip but no Adaptar action...
    const blockedRow = screen.getByText("Skill C").closest("li") as HTMLElement;
    expect(blockedRow.querySelector('[role="tooltip"]')).not.toBeNull();

    // ...and no row offers any activation/adapt action (single home: the
    // right MethodologyStatePanel).
    expect(
      screen.queryByRole("button", { name: "Activar" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Activada" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Sin mundo" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Adaptar" }),
    ).not.toBeInTheDocument();
  });
});