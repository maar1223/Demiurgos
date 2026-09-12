import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { TallerTree } from "@/components/organisms/TallerTree";
import {
  AXIS_TERMS,
  activationChip,
  companionChip,
} from "@/lib/vocabularyAxes";
import type { GroupedSkills } from "@/lib/tallerStates";
import type { PublishedMethodology } from "@/api/types";

function skill(id: string, taller: string): PublishedMethodology {
  return {
    skill_id: id,
    version: "1.0.0",
    name: id,
    description: "",
    digest: "d",
    published_at: "2026-01-01",
    taller,
  };
}

/** Byte-frozen TW3 group labels (TallerTree GROUP_ORDER — spec REQ-TRE-3,
 *  regression-locked by R-REG-1). */
const GROUP_LABELS = [
  "En uso · funciona solo en este taller",
  "En uso · funciona también en otros talleres",
  "Apagada · funciona solo en este taller",
  "Apagada · funciona también en otros talleres",
  "En conflicto · su taller de origen ya tiene una activa",
  "Sin taller",
];

const allGroups: GroupedSkills = {
  activas: [skill("activa", "Mundo")],
  transversalesActivas: [skill("trans-activa", "Mundo")],
  inactivas: [skill("inactiva", "Mundo")],
  transversalesInactivas: [skill("trans-inactiva", "Mundo")],
  bloqueadas: [skill("bloqueada", "Ideas")],
  sinTaller: [skill("sin-taller", "Mundo")],
};

function renderTree(
  overrides: Partial<Parameters<typeof TallerTree>[0]> = {},
) {
  render(
    <TallerTree
      groups={allGroups}
      world="nec"
      activeTaller="Mundo"
      onActivate={vi.fn()}
      busy={false}
      {...overrides}
    />,
  );
}

describe("axis vocabulary regression (R-REG-1/R-REG-2)", () => {
  it("freezes the 6 GROUP_ORDER labels byte-identical (Labels frozen)", () => {
    renderTree();

    for (const label of GROUP_LABELS) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    // Exactly six collapsible group headings render — no seventh drifted in.
    expect(screen.getAllByRole("button", { expanded: true })).toHaveLength(
      GROUP_LABELS.length,
    );
  });

  it("renders row chip text equal to the registry value verbatim (Registry-sourced chips)", () => {
    renderTree({
      active: {
        world: "nec",
        skill_id: "activa",
        version: "1.0.0",
        digest: "d",
        activated_at: "2026-01-01",
      },
      companions: [
        {
          world: "nec",
          skill_id: "activa",
          version: "1.0.0",
          description: "",
          activated_at: "2026-01-01",
        },
      ],
    });

    const row = screen.getByText("activa").closest("li") as HTMLElement;
    const slot = activationChip({ state: "activa", hasActivation: true });
    const companion = companionChip();

    const slotChip = within(row).getByText(slot.term).closest("[data-axis]");
    const companionChipEl = within(row)
      .getByText(companion.term)
      .closest("[data-axis]");
    expect(slotChip).toHaveAttribute("data-axis", slot.axis);
    expect(companionChipEl).toHaveAttribute("data-axis", companion.axis);

    // Every rendered chip term is a registered AXIS_TERMS key (spec R1): the
    // visible text equals the registry value verbatim.
    expect(AXIS_TERMS[slot.term]).toBe(slot.axis);
    expect(AXIS_TERMS[companion.term]).toBe(companion.axis);
  });
});
