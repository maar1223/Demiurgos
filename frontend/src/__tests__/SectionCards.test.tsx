import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  SectionCards,
  fileIconName,
} from "@/components/organisms/SectionCards";
import type { FileNode } from "@/api/types";

const nodes: FileNode[] = [
  {
    name: "capitulos",
    path: "capitulos",
    is_dir: true,
    children: [
      { name: "cap1.md", path: "capitulos/cap1.md", is_dir: false },
      { name: "cap2.md", path: "capitulos/cap2.md", is_dir: false },
      {
        name: "viejos",
        path: "capitulos/viejos",
        is_dir: true,
        children: [
          { name: "cap0.md", path: "capitulos/viejos/cap0.md", is_dir: false },
        ],
      },
    ],
  },
  { name: "notas.md", path: "notas.md", is_dir: false },
  { name: "foto.png", path: "foto.png", is_dir: false },
];

function renderCards(
  cardNodes: FileNode[] = nodes,
  onSelect = vi.fn(),
) {
  render(
    <SectionCards
      nodes={cardNodes}
      mundo="Vibrantes"
      section="lore"
      onSelect={onSelect}
    />,
  );
  return onSelect;
}

describe("SectionCards", () => {
  it("renders directories before files", () => {
    renderCards();

    const cards = screen.getAllByRole("button");
    expect(cards).toHaveLength(3);
    // The directory button's accessible name includes its badge counts
    expect(cards[0]).toHaveAccessibleName(/^capitulos/);
    expect(cards[1]).toHaveAccessibleName("notas.md");
    expect(cards[2]).toHaveAccessibleName("foto.png");
  });

  it("counts files recursively in the directory badge", () => {
    renderCards();

    // 2 direct files + 1 file inside the nested "viejos" subdirectory
    expect(screen.getByText("3 archivos, 1 subcarpeta")).toBeInTheDocument();
  });

  it("shows 'vacía' for an empty directory", () => {
    renderCards([
      { name: "vacia", path: "vacia", is_dir: true, children: [] },
    ]);

    expect(screen.getByText("vacía")).toBeInTheDocument();
  });

  it("calls onSelect with the node path when a card is clicked", async () => {
    const user = userEvent.setup();
    const onSelect = renderCards();

    await user.click(screen.getByRole("button", { name: /^capitulos/ }));
    expect(onSelect).toHaveBeenCalledWith("capitulos");

    await user.click(screen.getByRole("button", { name: "notas.md" }));
    expect(onSelect).toHaveBeenCalledWith("notas.md");
  });

  it("maps file extensions to icons", () => {
    expect(fileIconName("notas.md")).toBe("markdown");
    expect(fileIconName("foto.png")).toBe("image");
    expect(fileIconName("foto.JPG")).toBe("image");
    expect(fileIconName("notas.txt")).toBe("file");
  });
});
