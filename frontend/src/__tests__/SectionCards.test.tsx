import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  SectionCards,
  fileIconName,
} from "@/components/organisms/SectionCards";
import type { FichaStatus, FileNode } from "@/api/types";

// SectionCards renders cover <img> via getMediaUrl when a node carries a
// portada — mock the URL builder so no network is hit.
vi.mock("@/api/wiki", () => ({
  getMediaUrl: vi.fn(
    (_mundo: string, path: string) => `/media/${path}`,
  ),
}));

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

interface RenderCardsOptions {
  cardNodes?: FileNode[];
  onSelect?: ReturnType<typeof vi.fn>;
  onAction?: ReturnType<typeof vi.fn>;
  renamingPath?: string | null;
  busyPath?: string | null;
  actionError?: string | null;
  createTarget?: { path: string; kind: "file" | "subfolder" } | null;
  onMove?: ReturnType<typeof vi.fn>;
  browsingDirPath?: string;
  onRenameCommit?: ReturnType<typeof vi.fn>;
  onRenameCancel?: ReturnType<typeof vi.fn>;
  onCreateCommit?: ReturnType<typeof vi.fn>;
  onCreateCancel?: ReturnType<typeof vi.fn>;
}

function renderCards(options: RenderCardsOptions = {}) {
  const {
    cardNodes = nodes,
    onSelect = vi.fn(),
    onAction = vi.fn(),
    renamingPath = null,
    busyPath = null,
    actionError = null,
    createTarget = null,
    onMove = vi.fn(),
    browsingDirPath = "",
    onRenameCommit = vi.fn(),
    onRenameCancel = vi.fn(),
    onCreateCommit = vi.fn(),
    onCreateCancel = vi.fn(),
  } = options;

  render(
    <SectionCards
      nodes={cardNodes}
      mundo="Vibrantes"
      section="lore"
      onSelect={onSelect}
      onAction={onAction}
      renamingPath={renamingPath}
      busyPath={busyPath}
      actionError={actionError}
      createTarget={createTarget}
      onMove={onMove}
      browsingDirPath={browsingDirPath}
      onRenameCommit={onRenameCommit}
      onRenameCancel={onRenameCancel}
      onCreateCommit={onCreateCommit}
      onCreateCancel={onCreateCancel}
    />,
  );
  return {
    onSelect,
    onAction,
    onMove,
    onRenameCommit,
    onRenameCancel,
    onCreateCommit,
    onCreateCancel,
  };
}

/** Starts a drag of the given card and returns the shared DataTransfer. */
function startDrag(source: HTMLElement): DataTransfer {
  const dt = new DataTransfer();
  fireEvent.dragStart(source, { dataTransfer: dt });
  return dt;
}

describe("SectionCards", () => {
  it("renders directories before files with stable accessible names", () => {
    renderCards();

    // S1: each card = 1 card button + 1 sibling ⋯ button (never nested)
    const cardButtons = screen.getAllByRole("button");
    expect(cardButtons).toHaveLength(6);

    // Directory button's accessible name includes its badge counts
    expect(
      screen.getByRole("button", { name: /^capitulos/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "notas.md" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "foto.png" }),
    ).toBeInTheDocument();

    // One ⋯ per card, labelled "Acciones de {name}" (S2)
    expect(
      screen.getAllByRole("button", { name: /acciones de/i }),
    ).toHaveLength(3);
  });

  it("counts files recursively in the directory badge", () => {
    renderCards();

    // 2 direct files + 1 file inside the nested "viejos" subdirectory
    expect(screen.getByText("3 archivos, 1 subcarpeta")).toBeInTheDocument();
  });

  it("shows 'vacía' for an empty directory", () => {
    renderCards({
      cardNodes: [{ name: "vacia", path: "vacia", is_dir: true, children: [] }],
    });

    expect(screen.getByText("vacía")).toBeInTheDocument();
  });

  it("calls onSelect with the node path when a card is clicked", async () => {
    const user = userEvent.setup();
    const { onSelect } = renderCards();

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

  // ── ⋯ menu behavior ────────────────────────────────────────────────

  it("S5: only one menu is open at a time", async () => {
    const user = userEvent.setup();
    renderCards();

    await user.click(
      screen.getByRole("button", { name: "Acciones de capitulos" }),
    );
    // Directory menu: Open/Rename/Move to section/Delete only (creation
    // moved to the file bar), no Duplicate
    expect(screen.getAllByRole("menuitem")).toHaveLength(4);
    expect(
      screen.queryByRole("menuitem", { name: "Duplicar" }),
    ).not.toBeInTheDocument();

    // Opening a second menu closes the first (S5)
    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    // File menu: full set (7 items), so no directory menu is left open
    expect(screen.getAllByRole("menuitem")).toHaveLength(7);
    expect(
      screen.getByRole("menuitem", { name: "Duplicar" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: "Establecer portada…" }),
    ).toBeInTheDocument();
  });

  it("S6: Escape closes the open menu", async () => {
    const user = userEvent.setup();
    renderCards();

    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    expect(
      screen.getByRole("menuitem", { name: "Duplicar" }),
    ).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(
      screen.queryByRole("menuitem", { name: "Duplicar" }),
    ).not.toBeInTheDocument();
  });

  it("S6: document mousedown outside closes the menu", async () => {
    const user = userEvent.setup();
    renderCards();

    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    expect(
      screen.getByRole("menuitem", { name: "Duplicar" }),
    ).toBeInTheDocument();

    fireEvent.mouseDown(document.body);
    expect(
      screen.queryByRole("menuitem", { name: "Duplicar" }),
    ).not.toBeInTheDocument();
  });

  it("S4: ⋯ and menu clicks never fire onSelect", async () => {
    const user = userEvent.setup();
    const { onSelect } = renderCards();

    // ⋯ click must not reach the card button underneath
    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    expect(onSelect).not.toHaveBeenCalled();

    // Menu item click (stopPropagation) also must not fire onSelect
    await user.click(screen.getByRole("menuitem", { name: "Renombrar" }));
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("S7: menu action emits the discriminated action + node", async () => {
    const user = userEvent.setup();
    const { onAction } = renderCards();

    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Duplicar" }));

    expect(onAction).toHaveBeenCalledWith(
      "duplicate",
      expect.objectContaining({ path: "notas.md" }),
    );
  });

  it("S14: actions are disabled while the node's request is in flight", async () => {
    const user = userEvent.setup();
    renderCards({ busyPath: "notas.md" });

    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    expect(screen.getByRole("menuitem", { name: "Duplicar" })).toBeDisabled();
    // A node not in flight stays enabled
    await user.click(
      screen.getByRole("button", { name: "Acciones de capitulos" }),
    );
    expect(
      screen.getByRole("menuitem", { name: "Renombrar" }),
    ).toBeEnabled();
  });

  it("S36: shows the action error inline above the grid", () => {
    renderCards({ actionError: "El archivo ya existe" });

    expect(screen.getByRole("alert")).toHaveTextContent(/el archivo ya existe/i);
  });

  // ── Drag & drop (same-section moves) ────────────────────────────────

  it("drops a file card onto a folder card → onMove into that folder", async () => {
    const { onMove } = renderCards();
    const dt = startDrag(
      screen.getByRole("button", { name: /^notas\.md$/ }),
    );

    fireEvent.drop(
      screen.getByRole("button", { name: /^capitulos/ }),
      { dataTransfer: dt },
    );

    // Absorption animation (~150ms) precedes the actual move
    await waitFor(() => {
      expect(onMove).toHaveBeenCalledWith("notas.md", "capitulos/notas.md");
    });
  });

  it("drops a directory card onto a sibling folder card", async () => {
    const { onMove } = renderCards({
      cardNodes: [
        { name: "a", path: "a", is_dir: true, children: [] },
        { name: "b", path: "b", is_dir: true, children: [] },
      ],
    });
    const dt = startDrag(screen.getByRole("button", { name: /^a( vacía)?$/ }));

    fireEvent.drop(screen.getByRole("button", { name: /^b( vacía)?$/ }), {
      dataTransfer: dt,
    });

    await waitFor(() => {
      expect(onMove).toHaveBeenCalledWith("a", "b/a");
    });
  });

  it("dropping onto a file card does nothing", async () => {
    const { onMove } = renderCards();
    const dt = startDrag(
      screen.getByRole("button", { name: /^notas\.md$/ }),
    );

    fireEvent.drop(screen.getByRole("button", { name: "foto.png" }), {
      dataTransfer: dt,
    });

    expect(onMove).not.toHaveBeenCalled();
  });

  it("dropping a folder onto itself does nothing", async () => {
    const { onMove } = renderCards();
    const dt = startDrag(screen.getByRole("button", { name: /^capitulos/ }));

    fireEvent.drop(screen.getByRole("button", { name: /^capitulos/ }), {
      dataTransfer: dt,
    });

    expect(onMove).not.toHaveBeenCalled();
  });

  it("grid background while browsing a subdir → onMove one level up", async () => {
    const { onMove } = renderCards({ browsingDirPath: "capitulos" });
    const dt = startDrag(
      screen.getByRole("button", { name: /^notas\.md$/ }),
    );

    fireEvent.drop(screen.getByTestId("section-cards-drop-area"), {
      dataTransfer: dt,
    });

    await waitFor(() => {
      expect(onMove).toHaveBeenCalledWith("notas.md", "notas.md");
    });
  });

  it("grid background while browsing a nested subdir → parent folder target", async () => {
    const { onMove } = renderCards({ browsingDirPath: "capitulos/viejos" });
    const dt = startDrag(
      screen.getByRole("button", { name: /^notas\.md$/ }),
    );

    fireEvent.drop(screen.getByTestId("section-cards-drop-area"), {
      dataTransfer: dt,
    });

    await waitFor(() => {
      expect(onMove).toHaveBeenCalledWith("notas.md", "capitulos/notas.md");
    });
  });

  it("grid background at the section root is not a valid target", async () => {
    const { onMove } = renderCards({ browsingDirPath: "" });
    const dt = startDrag(
      screen.getByRole("button", { name: /^notas\.md$/ }),
    );

    fireEvent.drop(screen.getByTestId("section-cards-drop-area"), {
      dataTransfer: dt,
    });

    expect(onMove).not.toHaveBeenCalled();
  });

  // ── Cover rendering ────────────────────────────────────────────────

  it("renders a cover image when the node carries a portada", () => {
    renderCards({
      cardNodes: [
        {
          name: "con-portada.md",
          path: "con-portada.md",
          is_dir: false,
          portada: "wiki/media/x.jpg",
        },
      ],
    });

    const img = screen.getByRole("img", { name: "con-portada.md" });
    expect(img).toHaveAttribute("src", "/media/wiki/media/x.jpg");
  });

  it("falls back to the icon when no portada is resolved", () => {
    renderCards({
      cardNodes: [{ name: "sin-portada.md", path: "sin-portada.md", is_dir: false }],
    });

    expect(
      screen.queryByRole("img", { name: "sin-portada.md" }),
    ).not.toBeInTheDocument();
  });

  // ── Status dot (item 14 follow-up) ────────────────────────────────

  it("shows the draft dot with amber dashed classes and its tooltip", () => {
    renderCards({
      cardNodes: [
        { name: "borrador.md", path: "borrador.md", is_dir: false, status: "draft" },
      ],
    });

    // Dot: top-right corner of the card, readable via aria-label (the
    // native `title` tooltip was removed in favour of the instant CSS one)
    const dot = screen.getByLabelText("Borrador");
    expect(dot).toHaveClass(
      "border-dashed",
      "border-amber-400/50",
      "bg-amber-400/10",
      "h-3",
      "w-3",
      "rounded-full",
      "border-2",
    );
    const wrapper = dot.parentElement;
    expect(wrapper).toHaveClass("top-3", "right-3", "absolute");

    // Instant CSS tooltip: hidden by default, plain text for screen readers
    const tooltip = screen.getByText("Borrador");
    expect(tooltip).toHaveAttribute("aria-hidden", "true");
    expect(tooltip).toHaveClass(
      "opacity-0",
      "pointer-events-none",
      "whitespace-nowrap",
    );
    expect(wrapper).toHaveClass("group");
  });

  it("shows the stable dot with emerald solid classes and its tooltip", () => {
    renderCards({
      cardNodes: [
        { name: "canon.md", path: "canon.md", is_dir: false, status: "stable" },
      ],
    });

    const dot = screen.getByLabelText("Canon");
    expect(dot).toHaveClass(
      "border-solid",
      "border-emerald-500/60",
      "bg-emerald-500/15",
      "h-3",
      "w-3",
      "rounded-full",
      "border-2",
    );
    const wrapper = dot.parentElement;
    expect(wrapper).toHaveClass("top-3", "right-3", "absolute");

    const tooltip = screen.getByText("Canon");
    expect(tooltip).toHaveAttribute("aria-hidden", "true");
    expect(tooltip).toHaveClass(
      "opacity-0",
      "pointer-events-none",
      "whitespace-nowrap",
    );
    expect(wrapper).toHaveClass("group");
  });

  it("shows no dot when the status is missing or unknown", () => {
    renderCards({
      cardNodes: [
        { name: "sin-status.md", path: "sin-status.md", is_dir: false },
        {
          name: "synced.md",
          path: "synced.md",
          is_dir: false,
          status: "synced" as FichaStatus,
        },
      ],
    });

    expect(
      screen.queryByLabelText(/borrador|canon/i),
    ).not.toBeInTheDocument();
  });

  it("never shows a dot for directories", () => {
    renderCards({
      cardNodes: [
        {
          name: "carpeta",
          path: "carpeta",
          is_dir: true,
          children: [],
          // The backend never sends status on dirs — the guard must hold
          // even if a stale payload carries it.
          status: "stable" as FichaStatus,
        },
      ],
    });

    expect(
      screen.queryByLabelText(/borrador|canon/i),
    ).not.toBeInTheDocument();
  });

  // ── Inline rename (S8) ─────────────────────────────────────────────

  it("S8: Enter commits the new name via onRenameCommit", async () => {
    const user = userEvent.setup();
    const { onRenameCommit } = renderCards({ renamingPath: "notas.md" });

    const input = screen.getByRole("textbox", { name: "Nuevo nombre" });
    expect(input).toHaveValue("notas.md");

    await user.clear(input);
    await user.type(input, "renombrada.md{Enter}");

    expect(onRenameCommit).toHaveBeenCalledWith(
      expect.objectContaining({ path: "notas.md" }),
      "renombrada.md",
    );
  });

  it("S8: Escape cancels without committing", async () => {
    const user = userEvent.setup();
    const { onRenameCommit, onRenameCancel } = renderCards({
      renamingPath: "notas.md",
    });

    const input = screen.getByRole("textbox", { name: "Nuevo nombre" });
    await user.type(input, "{Escape}");

    expect(onRenameCancel).toHaveBeenCalled();
    expect(onRenameCommit).not.toHaveBeenCalled();
  });

  it("S8: empty name shows an inline error and fires no request", async () => {
    const user = userEvent.setup();
    const { onRenameCommit } = renderCards({ renamingPath: "notas.md" });

    const input = screen.getByRole("textbox", { name: "Nuevo nombre" });
    await user.clear(input);
    await user.type(input, "{Enter}");

    expect(screen.getByRole("alert")).toHaveTextContent(/no puede estar vacío/i);
    expect(onRenameCommit).not.toHaveBeenCalled();
  });

  it("S8: sibling collision shows an inline error and fires no request", async () => {
    const user = userEvent.setup();
    const { onRenameCommit } = renderCards({ renamingPath: "notas.md" });

    const input = screen.getByRole("textbox", { name: "Nuevo nombre" });
    await user.clear(input);
    await user.type(input, "capitulos{Enter}");

    expect(screen.getByRole("alert")).toHaveTextContent(/ya existe/i);
    expect(onRenameCommit).not.toHaveBeenCalled();
  });

  // ── New file / new subfolder (S10) ─────────────────────────────────

  it("S10: Enter commits the new file name via onCreateCommit", async () => {
    const user = userEvent.setup();
    const { onCreateCommit } = renderCards({
      createTarget: { path: "capitulos", kind: "file" },
    });

    const input = screen.getByRole("textbox", { name: "Nombre del archivo…" });
    await user.type(input, "cap3.md{Enter}");

    expect(onCreateCommit).toHaveBeenCalledWith("cap3.md");
  });

  it("S10: sibling collision inside the target dir blocks creation", async () => {
    const user = userEvent.setup();
    const { onCreateCommit } = renderCards({
      createTarget: { path: "capitulos", kind: "file" },
    });

    const input = screen.getByRole("textbox", { name: "Nombre del archivo…" });
    await user.type(input, "cap1.md{Enter}");

    expect(screen.getByRole("alert")).toHaveTextContent(/ya existe/i);
    expect(onCreateCommit).not.toHaveBeenCalled();
  });

  it("S10: a name with a path separator is rejected inline", async () => {
    const user = userEvent.setup();
    const { onCreateCommit } = renderCards({
      createTarget: { path: "capitulos", kind: "subfolder" },
    });

    const input = screen.getByRole("textbox", { name: "Nombre de la subcarpeta…" });
    await user.type(input, "a/b{Enter}");

    expect(screen.getByRole("alert")).toHaveTextContent(/\//i);
    expect(onCreateCommit).not.toHaveBeenCalled();
  });
});
