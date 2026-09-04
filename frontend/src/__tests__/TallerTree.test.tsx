import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TallerTree } from "@/components/organisms/TallerTree";
import type { GroupedSkills } from "@/lib/tallerStates";
import type { PublishedMethodology } from "@/api/types";

const skillA: PublishedMethodology = {
  skill_id: "skill-a",
  version: "1.0.0",
  name: "Skill A",
  description: "",
  digest: "abc",
  published_at: "2026-01-01",
  taller: "Herramientas",
};

const skillB: PublishedMethodology = {
  skill_id: "skill-b",
  version: "2.0.0",
  name: "Skill B",
  description: "",
  digest: "def",
  published_at: "2026-01-01",
  taller: "Herramientas",
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
    activeTaller: "Herramientas",
    onActivate: vi.fn(),
    busy: false,
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
});