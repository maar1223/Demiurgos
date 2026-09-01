import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FileTree } from "@/components/organisms/FileTree";
import { DND_NODE_MIME } from "@/lib/dnd";
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

const deeplyNested: FileNode[] = [
  {
    name: "capitulos",
    path: "capitulos",
    is_dir: true,
    children: [
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

  it("panel background drops a one-level-deep node up to the section root", async () => {
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

  it("panel background drops a deeper node one level up (not to the root)", async () => {
    const onMove = vi.fn();
    render(<FileTree nodes={deeplyNested} onMove={onMove} />);

    await userEvent.click(screen.getByRole("button", { name: "capitulos" }));
    await userEvent.click(screen.getByRole("button", { name: "viejos" }));

    const dt = startDrag(
      screen.getByRole("button", { name: "cap0.md" }),
    );
    fireEvent.drop(screen.getByTestId("file-tree-drop-area"), {
      dataTransfer: dt,
    });

    await waitFor(() => {
      expect(onMove).toHaveBeenCalledWith(
        "capitulos/viejos/cap0.md",
        "capitulos/cap0.md",
      );
    });
  });

  it("'Subir un nivel' bar appears only while dragging a nested node", async () => {
    render(<FileTree nodes={nested} onMove={vi.fn()} />);

    // No bar before a drag
    expect(
      screen.queryByTestId("file-tree-up-one-level"),
    ).not.toBeInTheDocument();

    // A root-level node drag does not render the bar
    startDrag(screen.getByRole("button", { name: "notas.md" }));
    expect(
      screen.queryByTestId("file-tree-up-one-level"),
    ).not.toBeInTheDocument();

    // A nested node drag renders the bar
    await userEvent.click(screen.getByRole("button", { name: "capitulos" }));
    startDrag(screen.getByRole("button", { name: "cap1.md" }));
    expect(screen.getByTestId("file-tree-up-one-level")).toBeInTheDocument();
  });

  it("dropping on the 'Subir un nivel' bar moves the node one level up", async () => {
    const onMove = vi.fn();
    render(<FileTree nodes={deeplyNested} onMove={onMove} />);

    await userEvent.click(screen.getByRole("button", { name: "capitulos" }));
    await userEvent.click(screen.getByRole("button", { name: "viejos" }));

    const dt = startDrag(
      screen.getByRole("button", { name: "cap0.md" }),
    );
    fireEvent.drop(screen.getByTestId("file-tree-up-one-level"), {
      dataTransfer: dt,
    });

    await waitFor(() => {
      expect(onMove).toHaveBeenCalledWith(
        "capitulos/viejos/cap0.md",
        "capitulos/cap0.md",
      );
    });
  });

  it("dragenter over the panel activates the up-zone even when the dataTransfer data is unreadable", async () => {
    // Browsers run dragenter in "protected mode": getData() returns "" there,
    // so the up-zone highlight must come from React state, not from the
    // dataTransfer. The MIME is still advertised in `types`.
    const onMove = vi.fn();
    render(<FileTree nodes={deeplyNested} onMove={onMove} />);

    await userEvent.click(screen.getByRole("button", { name: "capitulos" }));
    await userEvent.click(screen.getByRole("button", { name: "viejos" }));

    startDrag(screen.getByRole("button", { name: "cap0.md" }));

    const protectedDt = new DataTransfer();
    protectedDt.setData(DND_NODE_MIME, "");

    fireEvent.dragEnter(screen.getByTestId("file-tree-drop-area"), {
      dataTransfer: protectedDt,
    });
    fireEvent.drop(screen.getByTestId("file-tree-up-one-level"), {
      dataTransfer: protectedDt,
    });

    await waitFor(() => {
      expect(onMove).toHaveBeenCalledWith(
        "capitulos/viejos/cap0.md",
        "capitulos/cap0.md",
      );
    });
  });

  it("drop with unreadable dataTransfer data still moves via the drag-state fallback", async () => {
    // Chrome can return "" from getData() during drop under heavy memory
    // pressure; the React drag state must carry the move.
    const onMove = vi.fn();
    render(<FileTree nodes={nested} onMove={onMove} />);

    await userEvent.click(screen.getByRole("button", { name: "capitulos" }));

    startDrag(screen.getByRole("button", { name: "cap1.md" }));

    const corruptedDt = new DataTransfer();
    corruptedDt.setData(DND_NODE_MIME, "");
    fireEvent.drop(screen.getByTestId("file-tree-up-one-level"), {
      dataTransfer: corruptedDt,
    });

    await waitFor(() => {
      expect(onMove).toHaveBeenCalledWith("capitulos/cap1.md", "cap1.md");
    });
  });

  it("a foreign drag (no custom MIME) never triggers a move", async () => {
    // The drag-state fallback must not leak into foreign drops.
    const onMove = vi.fn();
    render(<FileTree nodes={nested} onMove={onMove} />);

    await userEvent.click(screen.getByRole("button", { name: "capitulos" }));

    startDrag(screen.getByRole("button", { name: "cap1.md" }));

    const foreignDt = new DataTransfer();
    foreignDt.setData("text/plain", "external");
    fireEvent.drop(screen.getByTestId("file-tree-up-one-level"), {
      dataTransfer: foreignDt,
    });

    expect(onMove).not.toHaveBeenCalled();
  });

  it("'Subir un nivel' bar shows where the node will land", async () => {
    render(<FileTree nodes={deeplyNested} onMove={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: "capitulos" }));
    await userEvent.click(screen.getByRole("button", { name: "viejos" }));

    startDrag(screen.getByRole("button", { name: "cap0.md" }));

    expect(screen.getByTestId("file-tree-up-one-level")).toHaveTextContent(
      "capitulos/cap0.md",
    );
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
