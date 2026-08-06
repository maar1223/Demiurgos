import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CardMenu, type CardAction } from "@/components/organisms/CardMenu";
import type { FileNode } from "@/api/types";

const fileNode: FileNode = { name: "notas.md", path: "notas.md", is_dir: false };
const dirNode: FileNode = {
  name: "capitulos",
  path: "capitulos",
  is_dir: true,
  children: [],
};

interface RenderOptions {
  open?: boolean;
  onOpenChange?: ReturnType<typeof vi.fn>;
  onAction?: ReturnType<typeof vi.fn>;
  busyPath?: string | null;
  error?: string | null;
}

function renderMenu(node: FileNode, options: RenderOptions = {}) {
  const {
    open = false,
    onOpenChange = vi.fn(),
    onAction = vi.fn(),
    busyPath = null,
    error = null,
  } = options;
  render(
    <CardMenu
      node={node}
      open={open}
      onOpenChange={onOpenChange}
      onAction={onAction}
      busyPath={busyPath}
      error={error}
    />,
  );
  return { onOpenChange, onAction };
}

describe("CardMenu", () => {
  it("S2: the ⋯ trigger exposes the a11y contract", () => {
    renderMenu(fileNode);

    const trigger = screen.getByRole("button", { name: "Acciones de notas.md" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("opens when the ⋯ trigger is clicked", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderMenu(fileNode);

    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    expect(onOpenChange).toHaveBeenCalledWith(true);
  });

  it("S3: file menu shows the full file action set", () => {
    renderMenu(fileNode, { open: true });

    expect(screen.getByRole("menuitem", { name: "Abrir" })).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: "Establecer portada…" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Renombrar" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Mover a…" })).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: "Mover a sección…" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Duplicar" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Eliminar" })).toBeInTheDocument();

    // S14: no folder-only actions for files
    expect(
      screen.queryByRole("menuitem", { name: "Nuevo archivo" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", { name: "Nueva subcarpeta" }),
    ).not.toBeInTheDocument();
  });

  it("Mover a sección… emits the move-section action", async () => {
    const user = userEvent.setup();
    const { onAction } = renderMenu(fileNode, { open: true });

    await user.click(
      screen.getByRole("menuitem", { name: "Mover a sección…" }),
    );

    expect(onAction).toHaveBeenCalledWith("move-section", fileNode);
  });

  it("S3/S14: directory menu excludes creation actions and Duplicate", () => {
    renderMenu(dirNode, { open: true });

    expect(screen.getByRole("menuitem", { name: "Abrir" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Renombrar" })).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: "Mover a sección…" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Eliminar" })).toBeInTheDocument();

    // Folders cannot move within the same section via the menu (no "Mover a…"
    // — same-section moves are drag & drop only for folders)
    expect(
      screen.queryByRole("menuitem", { name: "Mover a…" }),
    ).not.toBeInTheDocument();

    // Creation actions moved to the file bar (item 14) — a card menu would
    // suggest "create inside this card", which is not how directory scope works
    expect(
      screen.queryByRole("menuitem", { name: "Nuevo archivo" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", { name: "Nueva subcarpeta" }),
    ).not.toBeInTheDocument();

    // S14: folders have no Duplicate / Set cover
    expect(
      screen.queryByRole("menuitem", { name: "Duplicar" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", { name: "Establecer portada…" }),
    ).not.toBeInTheDocument();
  });

  it("S4: trigger click stops propagation to a parent handler", async () => {
    const user = userEvent.setup();
    const onWrapperClick = vi.fn();
    render(
      <div onClick={onWrapperClick}>
        <CardMenu
          node={fileNode}
          open={false}
          onOpenChange={vi.fn()}
          onAction={vi.fn()}
        />
      </div>,
    );

    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    expect(onWrapperClick).not.toHaveBeenCalled();
  });

  it("S7: menu item click emits (action, node) and closes", async () => {
    const user = userEvent.setup();
    const { onOpenChange, onAction } = renderMenu(fileNode, { open: true });

    await user.click(screen.getByRole("menuitem", { name: "Duplicar" }));

    expect(onAction).toHaveBeenCalledWith(
      "duplicate" as CardAction,
      fileNode,
    );
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("S6: Escape closes the open menu", async () => {
    const { onOpenChange } = renderMenu(fileNode, { open: true });

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("S6: document mousedown outside closes the menu", async () => {
    const { onOpenChange } = renderMenu(fileNode, { open: true });

    fireEvent.mouseDown(document.body);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("S6: mousedown INSIDE the menu does not close it before the click", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderMenu(fileNode, { open: true });

    const item = screen.getByRole("menuitem", { name: "Renombrar" });
    fireEvent.mouseDown(item);
    // The mousedown itself must NOT close — the item click handles it
    expect(onOpenChange).not.toHaveBeenCalledWith(false);

    await user.click(item);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("S14: all actions are disabled while busyPath matches the node", () => {
    renderMenu(fileNode, { open: true, busyPath: "notas.md" });

    expect(
      screen.getByRole("menuitem", { name: "Duplicar" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("menuitem", { name: "Renombrar" }),
    ).toBeDisabled();
  });

  it("S34/S36: renders the API error detail inside the open menu", () => {
    renderMenu(fileNode, { open: true, error: "El archivo ya existe" });

    expect(screen.getByRole("alert")).toHaveTextContent(/el archivo ya existe/i);
  });
});
