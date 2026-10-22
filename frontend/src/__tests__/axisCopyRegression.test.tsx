import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { TallerTree } from "@/components/organisms/TallerTree";
import { AXIS_TERMS, chatChip, scopeChip } from "@/lib/vocabularyAxes";
import { groupSkillsByChat } from "@/lib/tallerStates";
import type { MethodologyCompanion, PublishedMethodology } from "@/api/types";

function skill(id: string, taller: string, compatible: string[] = []): PublishedMethodology {
  return {
    skill_id: id,
    version: "1.0.0",
    name: id,
    description: "",
    digest: "d",
    published_at: "2026-01-01",
    taller,
    talleres_compatibles: compatible,
  };
}

/** Byte-frozen group labels (TallerTree GROUP_ORDER — S1). */
const GROUP_LABELS = ["En el chat", "Fuera del chat", "Sin taller"];

const published = [
  skill("en-chat", "Mundo"),
  skill("fuera", "Mundo"),
  skill("transversal", "Ideas", ["Mundo"]),
  skill("sin-taller", ""),
];

const companions: MethodologyCompanion[] = [
  {
    world: "nec",
    skill_id: "en-chat",
    version: "1.0.0",
    description: "",
    activated_at: "2026-01-01",
  },
];

function renderTree(
  overrides: Partial<Parameters<typeof TallerTree>[0]> = {},
) {
  render(
    <TallerTree
      groups={groupSkillsByChat(published, "Mundo", companions)}
      activeTaller="Mundo"
      companions={companions}
      {...overrides}
    />,
  );
}

describe("axis vocabulary regression (R-REG-1/R-REG-2)", () => {
  it("freezes the 3 GROUP_ORDER labels byte-identical (Labels frozen)", () => {
    renderTree();

    for (const label of GROUP_LABELS) {
      expect(screen.getByRole("heading", { name: label })).toBeInTheDocument();
    }
    expect(screen.getAllByRole("button", { expanded: true })).toHaveLength(
      GROUP_LABELS.length,
    );
  });

  it("renders chat and scope chip text equal to the registry value verbatim", () => {
    renderTree();

    const chatRow = screen.getByText("en-chat").closest("li") as HTMLElement;
    const chat = chatChip();
    const chatChipEl = within(chatRow).getByText(chat.term).closest("[data-axis]");
    expect(chatChipEl).toHaveAttribute("data-axis", chat.axis);
    expect(AXIS_TERMS[chat.term]).toBe(chat.axis);

    const scopeRow = screen.getByText("transversal").closest("li") as HTMLElement;
    const scope = scopeChip();
    const scopeChipEl = within(scopeRow).getByText(scope.term).closest("[data-axis]");
    expect(scopeChipEl).toHaveAttribute("data-axis", scope.axis);
    expect(AXIS_TERMS[scope.term]).toBe(scope.axis);
  });
});
