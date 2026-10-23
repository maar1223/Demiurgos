import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { TallerTree } from "@/components/organisms/TallerTree";
import { groupSkillsByChat } from "@/lib/tallerStates";
import type { MethodologyCompanion, PublishedMethodology } from "@/api/types";

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

const published = [skillA, skillB, skillC];

function companion(skill_id: string, version: string): MethodologyCompanion {
  return {
    world: "nec",
    skill_id,
    version,
    description: "",
    activated_at: "2026-01-01",
  };
}

function renderTree(
  overrides: Partial<Parameters<typeof TallerTree>[0]> = {},
) {
  const companions = overrides.companions ?? [];
  const props = {
    groups: groupSkillsByChat(published, "Mundo", companions),
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

  it("selects from the whole row card, not only the name button (REQ-TRE-12)", () => {
    // Regression: the row card's padding/badge area used to be inert, so a
    // click there left the previous selection in place and the right-panel
    // "Activar" acted on the wrong skill.
    const onSelect = vi.fn();
    renderTree({ onSelect, selected: null });

    const row = screen.getByText("Skill A").closest("li") as HTMLElement;
    fireEvent.click(row);

    expect(onSelect).toHaveBeenCalledWith("skill-a", "1.0.0");
  });

  it("selects exactly once when the row name is clicked", () => {
    const onSelect = vi.fn();
    renderTree({ onSelect, selected: null });

    fireEvent.click(screen.getByText("Skill A"));

    expect(onSelect).toHaveBeenCalledTimes(1);
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
    expect(selectedRow).toHaveClass("border-action");

    const otherRow = screen.getByText("Skill B").closest("li");
    expect(otherRow).not.toHaveClass("border-action");
  });

  it("highlights the row when the selected version is not the rendered one (REQ-TRE-12)", () => {
    renderTree({
      onSelect: vi.fn(),
      selected: { skill_id: "skill-a", version: "9.9.9" },
    });

    const selectedRow = screen.getByText("Skill A").closest("li");
    expect(selectedRow).toHaveClass("border-action");

    const otherRow = screen.getByText("Skill B").closest("li");
    expect(otherRow).not.toHaveClass("border-action");
  });
});

describe("chat and scope chips (S1)", () => {
  function rowOf(name: string): HTMLElement {
    return screen.getByText(name).closest("li") as HTMLElement;
  }

  it("marks only the skills added to the world's chat", () => {
    renderTree({ companions: [companion("skill-a", "1.0.0")] });

    const chatRow = rowOf("Skill A");
    expect(within(chatRow).getByText("En el chat")).toBeInTheDocument();
    expect(
      within(chatRow).getByText("En el chat").closest("[data-axis]"),
    ).toHaveAttribute("data-axis", "companion");

    const otherRow = rowOf("Skill B");
    expect(within(otherRow).queryByText("En el chat")).not.toBeInTheDocument();
  });

  it("marks a compatible skill of another taller as Transversal", () => {
    renderTree();

    const row = rowOf("Skill C");
    const chip = within(row).getByText("Transversal").closest("[data-axis]");
    expect(chip).toHaveAttribute("data-axis", "scope");
    expect(within(row).queryByText("En el chat")).not.toBeInTheDocument();
  });

  it("never renders activation on/off vocabulary (S2)", () => {
    renderTree({ companions: [companion("skill-a", "1.0.0")] });
    expect(screen.queryByText("Activa")).not.toBeInTheDocument();
    expect(screen.queryByText("Inactiva")).not.toBeInTheDocument();
    expect(screen.queryByText("Método en chat")).not.toBeInTheDocument();
    expect(screen.queryByText(/Activa en nec/)).not.toBeInTheDocument();
  });
});

describe("row actions stay in the right panel", () => {
  it("renders no action buttons on rows", () => {
    renderTree({ companions: [companion("skill-a", "1.0.0")] });

    expect(screen.queryByRole("button", { name: "Activar" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Desactivar" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Adaptar" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Añadir al chat" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Quitar del chat" })).not.toBeInTheDocument();
  });
});

describe("chat version drift", () => {
  function rowOf(name: string): HTMLElement {
    return screen.getByText(name).closest("li") as HTMLElement;
  }

  it("offers a one-click update when the chat uses an older version", () => {
    const onUpdateCompanion = vi.fn();
    renderTree({
      companions: [companion("skill-a", "0.9.0")],
      onUpdateCompanion,
    });

    const row = rowOf("Skill A");
    const update = within(row).getByRole("button", {
      name: /actualizar chat/i,
    });
    fireEvent.click(update);
    expect(onUpdateCompanion).toHaveBeenCalledWith("skill-a", "1.0.0");
  });

  it("does not offer the update when the chat already uses the row version", () => {
    renderTree({
      companions: [companion("skill-a", "1.0.0")],
      onUpdateCompanion: vi.fn(),
    });

    expect(
      screen.queryByRole("button", { name: /actualizar chat/i }),
    ).not.toBeInTheDocument();
  });

  it("never offers the update for a skill that is not in the chat", () => {
    renderTree({ companions: [], onUpdateCompanion: vi.fn() });

    expect(
      screen.queryByRole("button", { name: /actualizar chat/i }),
    ).not.toBeInTheDocument();
  });
});
