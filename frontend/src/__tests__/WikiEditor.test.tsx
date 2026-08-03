import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { forwardRef, useImperativeHandle } from "react";
import WikiEditor from "@/pages/WikiEditor";

// Mock all hooks
vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: vi.fn(),
}));

vi.mock("@/hooks/useFileTree", () => ({
  useFileTree: vi.fn(),
}));

vi.mock("@/hooks/useFileContent", () => ({
  useFileContent: vi.fn(),
}));

// Mock the entity search hook — the real hook debounces 300ms per keystroke,
// which would slow the wikilink-insertion test; the module mock returns
// results synchronously.
vi.mock("@/hooks/useEntitySearch", () => ({
  useEntitySearch: vi.fn(),
}));

// Mock the wiki API — the editor calls saveFile (Guardar). getDiff is no
// longer used by the preview (CodeMirror computes the diff client-side),
// but the module still exports it — keep the mock for parity.
vi.mock("@/api/wiki", () => ({
  getDiff: vi.fn(),
  saveFile: vi.fn(),
}));

// The diff view is lazy-loaded; a lightweight stub is enough for these
// tests. The real component renders one auto-resized textarea per right
// line (covered by its own test file); here the imperative handle is what
// matters — WikiEditor routes wikilink insertion through it while the
// preview is open. `insertTextMock` is shared via vi.hoisted so the test
// can assert on it directly (the factory cannot close over module scope).
const { insertTextMock } = vi.hoisted(() => ({ insertTextMock: vi.fn() }));

vi.mock("@/components/organisms/LiveDiffEditor", () => ({
  default: forwardRef<unknown, Record<string, never>>((_props, ref) => {
    useImperativeHandle(ref, () => ({ insertText: insertTextMock }));
    return <div data-testid="live-diff-editor" />;
  }),
}));

import { useWorlds } from "@/hooks/useWorlds";
import { useFileTree } from "@/hooks/useFileTree";
import { useFileContent } from "@/hooks/useFileContent";
import { useEntitySearch } from "@/hooks/useEntitySearch";
import { saveFile } from "@/api/wiki";
import type { Mock } from "vitest";

const mockWorlds = [
  { name: "Vibrantes", path: "/vibrantes", lore_count: 77, character_count: 10, saga_count: 4 },
];

const mockTreeNodes = [
  {
    name: "capitulos",
    path: "capitulos",
    is_dir: true,
    children: [
      { name: "cap1.md", path: "capitulos/cap1.md", is_dir: false },
      { name: "cap2.md", path: "capitulos/cap2.md", is_dir: false },
    ],
  },
  { name: "notas.md", path: "notas.md", is_dir: false },
];

const mockFileContent = {
  path: "capitulos/cap1.md",
  name: "cap1.md",
  content: "# Capítulo 1\n\nEste es el contenido del **capítulo 1**.",
  size_bytes: 48,
  modified: "2024-01-15T10:30:00Z",
  extension: ".md",
};

function renderWikiEditor(initialEntries: string[] = ["/wiki/Vibrantes/lore"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Routes>
        <Route path="/wiki/:mundo/:section/*" element={<WikiEditor />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("WikiEditor", () => {
  beforeEach(() => {
    (useWorlds as Mock).mockReturnValue({
      worlds: mockWorlds,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    (useFileTree as Mock).mockReturnValue({
      nodes: mockTreeNodes,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    (useFileContent as Mock).mockReturnValue({
      file: null,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    (saveFile as Mock).mockResolvedValue({ success: true, path: "capitulos/cap1.md" });

    (useEntitySearch as Mock).mockReturnValue({
      results: [],
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the file tree in sidebar", () => {
    renderWikiEditor();

    expect(screen.getByText("capitulos")).toBeInTheDocument();
    expect(screen.getByText("notas.md")).toBeInTheDocument();
  });

  it("shows 'Seleccioná un archivo' placeholder when no file selected", () => {
    renderWikiEditor();

    expect(
      screen.getByText(/Seleccioná un archivo del panel lateral/i),
    ).toBeInTheDocument();
  });

  it("shows breadcrumb with mundo and section", () => {
    renderWikiEditor();

    // Breadcrumb shows mundo and section names
    expect(screen.getByText("lore")).toBeInTheDocument();
  });

  it("shows breadcrumb with file path when file is selected", () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    expect(screen.getByText("lore")).toBeInTheDocument();
    // "capitulos" and "cap1.md" appear both in breadcrumb AND in the
    // file tree sidebar — use getAllByText for duplicate-safe assertions
    expect(screen.getAllByText("capitulos").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("cap1.md").length).toBeGreaterThanOrEqual(1);
  });

  it("renders markdown content when file is selected", () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    // The markdown content should be rendered
    expect(screen.getByText("Capítulo 1")).toBeInTheDocument();
  });

  it("shows 'Invalid section' for unknown sections", () => {
    renderWikiEditor(["/wiki/Vibrantes/unknown-section"]);

    expect(screen.getByText(/Sección no válida/i)).toBeInTheDocument();
  });

  it("shows 'Mundo no encontrado' for unknown worlds", () => {
    renderWikiEditor(["/wiki/UnknownWorld/lore"]);

    expect(screen.getByText(/Mundo no encontrado/i)).toBeInTheDocument();
  });

  it("shows loading spinner when tree is loading", () => {
    (useFileTree as Mock).mockReturnValue({
      nodes: [],
      isLoading: true,
      error: null,
      mutate: vi.fn(),
    });

    renderWikiEditor();

    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows error banner when tree fetch fails", () => {
    (useFileTree as Mock).mockReturnValue({
      nodes: [],
      isLoading: false,
      error: new Error("Failed to fetch"),
      mutate: vi.fn(),
    });

    renderWikiEditor();

    expect(
      screen.getByText(/No se pudo cargar el árbol de archivos/i),
    ).toBeInTheDocument();
  });

  it("shows empty state when tree is empty", () => {
    (useFileTree as Mock).mockReturnValue({
      nodes: [],
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    renderWikiEditor();

    expect(
      screen.getByText(/Esta sección está vacía/i),
    ).toBeInTheDocument();
  });

  it("renders Navbar with worlds", () => {
    renderWikiEditor();

    // "Vibrantes" appears both in the breadcrumb AND the world selector
    // — use getAllByText for duplicate-safe assertions
    expect(screen.getAllByText("Vibrantes").length).toBeGreaterThanOrEqual(1);
    // Navbar should also show the Wiki nav link
    expect(screen.getByText("Wiki")).toBeInTheDocument();
  });

  it("has breadcrumb segment clickable", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    // Click on 'lore' breadcrumb segment — this navigates back
    // to the section root, which triggers a re-render
    const loreButton = screen.getByText("lore");
    await user.click(loreButton);

    // After navigation, the breadcrumb should still show "lore"
    expect(screen.getByText("lore")).toBeInTheDocument();
  });

  it("renders section tabs above the file tree", () => {
    renderWikiEditor();

    expect(screen.getByRole("tab", { name: "Lore" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Personajes" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Sagas" })).toBeInTheDocument();
  });

  it("marks the current URL section as the active tab", () => {
    renderWikiEditor(["/wiki/Vibrantes/personajes"]);

    expect(screen.getByRole("tab", { name: "Personajes" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "Lore" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("navigates to the section root when a tab is clicked", async () => {
    const user = userEvent.setup();
    renderWikiEditor();

    await user.click(screen.getByRole("tab", { name: "Sagas" }));

    // Section change re-invokes the tree hook with the new section
    // (SWR key includes section → triggers re-fetch)
    expect(useFileTree).toHaveBeenCalledWith("Vibrantes", "sagas");
    expect(screen.getByRole("tab", { name: "Sagas" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  // ── New edit-flow tests: Guardar / Vista previa live diff / Guardar ──

  it("shows toolbar buttons when editing: Cancelar, Vista previa, Guardar", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    // View mode: only "Editar"
    expect(screen.getByRole("button", { name: /editar/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /guardar/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /editar/i }));
    const textarea = screen.getByRole("textbox", { name: /editor de contenido/i });

    // No changes yet → only Cancelar
    expect(screen.getByRole("button", { name: /cancelar/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /vista previa/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /guardar/i })).not.toBeInTheDocument();

    await user.type(textarea, " modificado");

    // With changes → Cancelar + Vista previa + Guardar
    expect(screen.getByRole("button", { name: /cancelar/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /vista previa/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /guardar/i })).toBeInTheDocument();
  });

  it("Guardar calls saveFile, exits edit mode and shows success feedback", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    await user.click(screen.getByRole("button", { name: /editar/i }));
    const textarea = screen.getByRole("textbox", { name: /editor de contenido/i });
    await user.type(textarea, " modificado");

    await user.click(screen.getByRole("button", { name: /guardar/i }));

    await waitFor(() => {
      expect(saveFile).toHaveBeenCalledWith(
        "Vibrantes",
        "lore",
        "capitulos/cap1.md",
        expect.stringContaining("modificado"),
      );
    });

    // Edit mode exited → Editar button back, no textarea
    expect(screen.getByRole("button", { name: /editar/i })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /editor de contenido/i })).not.toBeInTheDocument();

    // Success feedback
    expect(screen.getByText(/Guardado/i)).toBeInTheDocument();
  });

  it("shows an error banner when saveFile fails", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
    (saveFile as Mock).mockRejectedValue({ status: 500, detail: "Error interno del servidor. Revisá los logs del backend." });

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    await user.click(screen.getByRole("button", { name: /editar/i }));
    const textarea = screen.getByRole("textbox", { name: /editor de contenido/i });
    await user.type(textarea, " modificado");

    await user.click(screen.getByRole("button", { name: /guardar/i }));

    // Error banner shown, still editing (edits preserved)
    expect(await screen.findByText(/Error interno del servidor/i)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /editor de contenido/i })).toBeInTheDocument();
  });

  it("Vista previa replaces the textarea with the live diff", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    await user.click(screen.getByRole("button", { name: /editar/i }));
    const textarea = screen.getByRole("textbox", { name: /editor de contenido/i });
    await user.type(textarea, " modificado");

    await user.click(screen.getByRole("button", { name: /vista previa/i }));

    // The diff view REPLACES the textarea — the right side of the diff is
    // the writing surface while the preview is open
    expect(
      await screen.findByTestId("live-diff-editor"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: /editor de contenido/i }),
    ).not.toBeInTheDocument();
  });

  it("Vista previa toggles closed without saving, edits preserved", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    await user.click(screen.getByRole("button", { name: /editar/i }));
    const textarea = screen.getByRole("textbox", { name: /editor de contenido/i });
    await user.type(textarea, " modificado");

    await user.click(screen.getByRole("button", { name: /vista previa/i }));
    expect(await screen.findByTestId("live-diff-editor")).toBeInTheDocument();

    // Clicking Vista previa again closes the merge view — no save happened,
    // and the edits survive back in the textarea
    await user.click(screen.getByRole("button", { name: /vista previa/i }));

    expect(saveFile).not.toHaveBeenCalled();
    expect(
      screen.queryByTestId("live-diff-editor"),
    ).not.toBeInTheDocument();
    const backToTextarea = screen.getByRole("textbox", {
      name: /editor de contenido/i,
    });
    expect(backToTextarea).toHaveValue(`${mockFileContent.content} modificado`);
  });

  it("Guardar works while the live diff preview is open", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    await user.click(screen.getByRole("button", { name: /editar/i }));
    const textarea = screen.getByRole("textbox", { name: /editor de contenido/i });
    await user.type(textarea, " modificado");

    await user.click(screen.getByRole("button", { name: /vista previa/i }));
    expect(await screen.findByTestId("live-diff-editor")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /guardar/i }));

    await waitFor(() => {
      expect(saveFile).toHaveBeenCalledWith(
        "Vibrantes",
        "lore",
        "capitulos/cap1.md",
        expect.stringContaining("modificado"),
      );
    });

    // Preview closed, edit mode exited
    expect(
      screen.queryByTestId("live-diff-editor"),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /editar/i })).toBeInTheDocument();
  });

  it("inserts a wikilink from the Contexto panel while the preview is open", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
    (useEntitySearch as Mock).mockReturnValue({
      results: [
        {
          name: "Kael Thornwood",
          path: "personajes/kael.md",
          type: "personaje",
          title: "Kael Thornwood",
          description: "",
          tags: [],
          link_count: 1,
          score: 1,
        },
      ],
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    // TabBar persists the active tab to sessionStorage under "sidebar-tab" —
    // reset so the default tab is "asistente" and clicking "Contexto" is
    // deterministic
    sessionStorage.clear();

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    await user.click(screen.getByRole("button", { name: /editar/i }));
    const textarea = screen.getByRole("textbox", { name: /editor de contenido/i });
    await user.type(textarea, " modificado");

    // Open the preview — the textarea is replaced by the live diff
    await user.click(screen.getByRole("button", { name: /vista previa/i }));
    expect(await screen.findByTestId("live-diff-editor")).toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: /editor de contenido/i }),
    ).not.toBeInTheDocument();

    // Switch to the Contexto panel and search for an entity
    await user.click(screen.getByRole("tab", { name: "Contexto" }));
    const searchInput = screen.getByRole("textbox", { name: /buscar entidad/i });
    await user.type(searchInput, "Kael");

    // Click the result — the wikilink must go through the live diff's
    // imperative handle (regression: it used to be a no-op while the
    // preview replaced the textarea).
    await user.click(screen.getByRole("option", { name: /kael thornwood/i }));
    expect(insertTextMock).toHaveBeenCalledWith("[[Kael Thornwood]]");
  });
});
