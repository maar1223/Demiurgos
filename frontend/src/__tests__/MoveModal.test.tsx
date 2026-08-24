import { describe, it, expect, vi } from "vitest";
import { render, screen, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MoveModal } from "@/components/organisms/MoveModal";
import type { FileNode } from "@/api/types";

vi.mock("@/hooks/useFileTree", () => ({
  useFileTree: vi.fn(),
}));

import { useFileTree } from "@/hooks/useFileTree";
import type { Mock } from "vitest";

const tree: FileNode[] = [
  {
    name: "capitulos",
    path: "capitulos",
    is_dir: true,
    children: [
      { name: "viejos", path: "capitulos/viejos", is_dir: true, children: [] },
      { name: "cap1.md", path: "capitulos/cap1.md", is_dir: false },
    ],
  },
  { name: "otros", path: "otros", is_dir: true, children: [] },
  { name: "nota.md", path: "nota.md", is_dir: false },
];

function mockTree(nodes: FileNode[] = tree) {
  (useFileTree as Mock).mockReturnValue({
    nodes,
    isLoading: false,
    error: null,
    mutate: vi.fn(),
  });
}

function renderModal(
  source: { section: string; path: string } = { section: "lore", path: "capitulos" },
) {
  const onConfirm = vi.fn();
  const onClose = vi.fn();
  render(
    <MoveModal
      mundo="Vibrantes"
      source={source}
      onConfirm={onConfirm}
      onClose={onClose}
    />,
  );
  return { onConfirm, onClose };
}

describe("MoveModal", () => {
  it("renders the four destination section tabs including referencias (decision b)", () => {
    mockTree();
    renderModal();

    const dialog = screen.getByRole("dialog", { name: /mover a/i });
    expect(within(dialog).getByRole("tab", { name: "Lore" })).toBeInTheDocument();
    expect(
      within(dialog).getByRole("tab", { name: "Personajes" }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("tab", { name: "Referencias" }),
    ).toBeInTheDocument();
  });

  it("excludes the source subtree in the source section", async () => {
    mockTree();
    const user = userEvent.setup();
    renderModal({ section: "lore", path: "capitulos" });

    // In "lore", "capitulos" (and its subtree) is excluded — only "otros" remains
    expect(
      screen.queryByRole("button", { name: /seleccionar capitulos/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Seleccionar otros" }),
    ).toBeInTheDocument();

    // In another section the same-named folder IS a valid destination
    await user.click(screen.getByRole("tab", { name: "Personajes" }));
    expect(
      screen.getByRole("button", { name: "Seleccionar capitulos" }),
    ).toBeInTheDocument();
  });

  it("excludes a nested source subtree but keeps the ancestor folder", () => {
    mockTree();
    renderModal({ section: "lore", path: "capitulos/viejos" });

    // "capitulos" stays (it is not inside the source), "viejos" is hidden
    expect(
      screen.getByRole("button", { name: "Seleccionar capitulos" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /seleccionar viejos/i }),
    ).not.toBeInTheDocument();
  });

  it("confirms at the section root with the section name", async () => {
    mockTree();
    const user = userEvent.setup();
    const { onConfirm } = renderModal({ section: "lore", path: "nota.md" });

    await user.click(screen.getByRole("button", { name: "Mover aquí" }));
    expect(onConfirm).toHaveBeenCalledWith("lore");
  });

  it("confirms into a selected folder with the full path", async () => {
    mockTree();
    const user = userEvent.setup();
    const { onConfirm } = renderModal();

    await user.click(
      screen.getByRole("button", { name: "Seleccionar otros" }),
    );
    await user.click(screen.getByRole("button", { name: "Mover aquí" }));
    expect(onConfirm).toHaveBeenCalledWith("lore/otros");
  });

  it("switching section resets the selected folder", async () => {
    mockTree();
    const user = userEvent.setup();
    const { onConfirm } = renderModal();

    await user.click(
      screen.getByRole("button", { name: "Seleccionar otros" }),
    );
    await user.click(screen.getByRole("tab", { name: "Referencias" }));
    await user.click(screen.getByRole("button", { name: "Mover aquí" }));
    expect(onConfirm).toHaveBeenCalledWith("referencias");
  });

  it("closes on Escape", () => {
    mockTree();
    const { onClose } = renderModal();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("closes when the overlay outside the dialog is clicked", async () => {
    mockTree();
    const user = userEvent.setup();
    const { onClose } = renderModal();

    const overlay = document.querySelector(".fixed.inset-0");
    expect(overlay).not.toBeNull();
    await user.click(overlay as HTMLElement);
    expect(onClose).toHaveBeenCalled();
  });
});
