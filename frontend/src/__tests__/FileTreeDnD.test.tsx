import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FileTree } from "@/components/organisms/FileTree";
import type { FileNode } from "@/api/types";

const nodes: FileNode[] = [
  { name: "Anisa.md", path: "Anisa.md", is_dir: false },
  { name: "Bira.md", path: "Bira.md", is_dir: false },
];

const nested: FileNode[] = [
  {
    name: "capitulos",
    path: "capitulos",
    is_dir: true,
    children: [
      { name: "cap1.md", path: "capitulos/cap1.md", is_dir: false },
      { name: "viejos", path: "capitulos/viejos", is_dir: true, children: [] },
    ],
  },
  { name: "notas.md", path: "notas.md", is_dir: false },
];

/** Starts a drag of the given tree node button and returns the DataTransfer. */
function startDrag(source: HTMLElement): DataTransfer {
  const dt = new DataTransfer();
  fireEvent.dragStart(source, { dataTransfer: dt });
  return dt;
}

describe("FileTree drag & drop", () => {
  it("drops a node onto a folder node → onMove into that folder", async () => {
    const onMove = vi.fn();
    render(<FileTree nodes={nested} onMove={onMove} />);

    const dt = startDrag(
      screen.getByRole("button", { name: "notas.md" }),
    );
    fireEvent.drop(screen.getByRole("button", { name: "capitulos" }), {
      dataTransfer: dt,
    });

    // Absorption animation (~150ms) precedes the actual move
    await waitFor(() => {
      expect(onMove).toHaveBeenCalledWith("notas.md", "capitulos/notas.md");
    });
  });

  it("dropping a folder onto its own descendant does nothing (cycle)", async () => {
    const onMove = vi.fn();
    render(<FileTree nodes={nested} onMove={onMove} />);

    await userEvent.click(screen.getByRole("button", { name: "capitulos" }));

    const dt = startDrag(
      screen.getByRole("button", { name: "capitulos" }),
    );
    fireEvent.drop(screen.getByRole("button", { name: "viejos" }), {
      dataTransfer: dt,
    });

    expect(onMove).not.toHaveBeenCalled();
  });

  it("dropping a node onto its own parent does nothing", async () => {
    const onMove = vi.fn();
    render(<FileTree nodes={nested} onMove={onMove} />);

    await userEvent.click(screen.getByRole("button", { name: "capitulos" }));

    const dt = startDrag(
      screen.getByRole("button", { name: "cap1.md" }),
    );
    fireEvent.drop(screen.getByRole("button", { name: "capitulos" }), {
      dataTransfer: dt,
    });

    expect(onMove).not.toHaveBeenCalled();
  });

  it("dropping onto a file node does nothing", async () => {
    const onMove = vi.fn();
    render(<FileTree nodes={nested} onMove={onMove} />);

    await userEvent.click(screen.getByRole("button", { name: "capitulos" }));

    const dt = startDrag(
      screen.getByRole("button", { name: "cap1.md" }),
    );
    fireEvent.drop(screen.getByRole("button", { name: "notas.md" }), {
      dataTransfer: dt,
    });

    expect(onMove).not.toHaveBeenCalled();
  });

  it("panel background drops a nested node to the section root", async () => {
    const onMove = vi.fn();
    render(<FileTree nodes={nested} onMove={onMove} />);

    await userEvent.click(screen.getByRole("button", { name: "capitulos" }));

    const dt = startDrag(
      screen.getByRole("button", { name: "cap1.md" }),
    );
    fireEvent.drop(screen.getByTestId("file-tree-drop-area"), {
      dataTransfer: dt,
    });

    await waitFor(() => {
      expect(onMove).toHaveBeenCalledWith("capitulos/cap1.md", "cap1.md");
    });
  });

  it("panel background is not a valid target for root-level nodes", async () => {
    const onMove = vi.fn();
    render(<FileTree nodes={nodes} onMove={onMove} />);

    const dt = startDrag(
      screen.getByRole("button", { name: "Anisa.md" }),
    );
    fireEvent.drop(screen.getByTestId("file-tree-drop-area"), {
      dataTransfer: dt,
    });

    expect(onMove).not.toHaveBeenCalled();
  });
});
