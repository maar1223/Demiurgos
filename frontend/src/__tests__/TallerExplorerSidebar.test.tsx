import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { TallerExplorerSidebar } from "@/components/organisms/TallerExplorerSidebar";
import type { MethodologyStatus, WorldInfo } from "@/api/types";

const worlds: WorldInfo[] = [
  {
    name: "Vibrantes",
    path: "/vibrantes",
    lore_count: 1,
    character_count: 0,
    reference_count: 0,
  },
];

/** One published skill that is ON as a companion in "Vibrantes" (no slot
 *  activation — the companion badge is independent of it). */
const status: MethodologyStatus = {
  published: [
    {
      skill_id: "eneagrama",
      version: "1.2.0",
      name: "Eneagrama",
      description: "",
      digest: "abc",
      published_at: "2026-01-01",
      taller: "Mundo",
      talleres_compatibles: [],
    },
  ],
  activations: {},
  drafts: [],
  companions: {
    Vibrantes: [
      {
        world: "Vibrantes",
        skill_id: "eneagrama",
        version: "1.2.0",
        description: "",
        activated_at: "2026-01-02",
      },
    ],
  },
};

function renderSidebar(
  overrides: Partial<Parameters<typeof TallerExplorerSidebar>[0]> = {},
) {
  const props = {
    lens: "mi-mundo" as const,
    onLensChange: vi.fn(),
    world: "Vibrantes",
    worlds,
    activeTaller: "Mundo",
    onWorldChange: vi.fn(),
    onTallerChange: vi.fn(),
    onRequestCreateWorld: vi.fn(),
    status,
    statusError: null,
    onStatusRetry: vi.fn(),
    selected: null,
    onSelect: vi.fn(),
    compareSelection: [],
    ...overrides,
  };
  render(<TallerExplorerSidebar {...props} />);
  return props;
}

describe("TallerExplorerSidebar companion badge (R-UI chips)", () => {
  it("marks ON rows whose skill is an active companion in the current world", () => {
    renderSidebar();

    expect(screen.getByText("Eneagrama")).toBeInTheDocument();
    // "Método en chat" renders as an attributed axis-2 chip (axis-binding-ui R1) —
    // copy committed in ⑥, the assertion targets the attributed surface.
    const companionChip = screen.getByText("Método en chat").closest("[data-axis]");
    expect(companionChip).toHaveAttribute("data-axis", "companion");
  });

  it("leaves rows unmarked when the world has no companions", () => {
    renderSidebar({ status: { ...status, companions: {} } });

    expect(screen.getByText("Eneagrama")).toBeInTheDocument();
    expect(screen.queryByText("Método en chat")).not.toBeInTheDocument();
  });

  it("renders the lens toggle above the world selector (header order)", () => {
    renderSidebar();

    // The toggle carries no visible heading (self-labeling), so anchor the
    // order assertion on its accessible name.
    const lens = screen.getByRole("tablist", { name: "Lente de la biblioteca" });
    const mundo = screen.getByText("Mundo");
    // The lens decides which context controls apply, so it leads the header.
    expect(
      lens.compareDocumentPosition(mundo) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("never truncates the skill name or its id line (full data stays visible)", () => {
    renderSidebar();

    const name = screen.getByText("Eneagrama");
    expect(name).toHaveClass("break-words");
    expect(name).not.toHaveClass("truncate");
    expect(screen.getByText("eneagrama@1.2.0")).not.toHaveClass("truncate");
  });
});