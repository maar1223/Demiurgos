import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within, fireEvent } from "@testing-library/react";
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

// Mock the image hooks — the editor mounts useImageUpload on every render
// and the picker uses useImages; without mocks the real SWR fetches would
// hit the network in tests.
vi.mock("@/hooks/useImages", () => ({
  useImages: vi.fn(),
  useImageUpload: vi.fn().mockReturnValue({
    upload: vi.fn(),
    isUploading: false,
    uploadError: null,
  }),
  useImageDelete: vi.fn(),
}));

// Mock the wiki API — the editor calls saveFile (Guardar), getDiff is no
// longer used by the preview (CodeMirror computes the diff client-side),
// but the module still exports it — keep the mock for parity. getMediaUrl
// is used by the ImagePicker thumbnails. moveNode/duplicateFile/
// getFileContent/createFile/deleteFile back the card ⋯ action flows.
// setStatus backs the file-bar status chip (item 14).
vi.mock("@/api/wiki", () => ({
  getDiff: vi.fn(),
  saveFile: vi.fn(),
  getMediaUrl: vi.fn((_mundo: string, path: string) => `/media/${path}`),
  moveNode: vi.fn(),
  duplicateFile: vi.fn(),
  getFileContent: vi.fn(),
  createFile: vi.fn(),
  deleteFile: vi.fn(),
  setStatus: vi.fn(),
  listTrash: vi.fn(),
  restoreFromTrash: vi.fn(),
  purgeTrashItem: vi.fn(),
  emptyTrash: vi.fn(),
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
import { useImages, useImageUpload } from "@/hooks/useImages";
import { saveFile, moveNode, duplicateFile, getFileContent, createFile, deleteFile, setStatus, listTrash } from "@/api/wiki";
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

// A wiki ficha with agent-only YAML frontmatter — must never surface in the
// editor textarea, the diff, or the viewer, and must be preserved on save.
const frontmatterFile = {
  ...mockFileContent,
  content:
    "---\ntype: Personaje\ntitle: Anisa\n---\n# Anisa\n\nEste es el cuerpo.",
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
    (setStatus as Mock).mockResolvedValue({ success: true, path: "capitulos/cap1.md" });
    (moveNode as Mock).mockResolvedValue({ success: true, path: "renombrada.md" });
    (duplicateFile as Mock).mockResolvedValue({
      success: true,
      path: "notas-copia.md",
    });
    (getFileContent as Mock).mockResolvedValue(mockFileContent);
    (createFile as Mock).mockResolvedValue({ success: true, path: "capitulos/cap3.md" });
    (deleteFile as Mock).mockResolvedValue({ success: true, path: "notas.md" });

    (useEntitySearch as Mock).mockReturnValue({
      results: [],
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    (useImages as Mock).mockReturnValue({
      images: [],
      total: 0,
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

    // Scope to the sidebar nav — the same names now also appear in the
    // central section cards
    const tree = within(
      screen.getByRole("navigation", { name: "File tree" }),
    );
    expect(tree.getByText("capitulos")).toBeInTheDocument();
    expect(tree.getByText("notas.md")).toBeInTheDocument();
  });

  it("shows section cards instead of the placeholder when no file selected", () => {
    renderWikiEditor();

    // The central area shows visual cards (directory + file) instead of
    // the old "Seleccioná un archivo" placeholder — the section contents
    // are browsable directly from the content area
    expect(
      screen.getByRole("heading", { name: "capitulos" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "notas.md" }),
    ).toBeInTheDocument();
    // The directory badge shows the recursive file count
    expect(screen.getByText("2 archivos")).toBeInTheDocument();
    expect(
      screen.queryByText(/Seleccioná un archivo del panel lateral/i),
    ).not.toBeInTheDocument();
  });

  it("navigates into a directory when its card is clicked and shows its children", async () => {
    const user = userEvent.setup();
    renderWikiEditor();

    // The directory card heading is unique — the sidebar tree node is a
    // button with a plain span
    await user.click(screen.getByRole("heading", { name: "capitulos" }));

    // The central area now shows the directory's children as cards
    expect(
      screen.getByRole("heading", { name: "cap1.md" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "cap2.md" }),
    ).toBeInTheDocument();
    // "capitulos" survives in the sidebar tree AND the breadcrumb segment
    expect(screen.getAllByText("capitulos").length).toBeGreaterThanOrEqual(2);
  });

  it("opens a file when its card is clicked", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    const user = userEvent.setup();
    renderWikiEditor();

    await user.click(screen.getByRole("heading", { name: "notas.md" }));

    // Navigated to the file — the viewer replaces the cards with the
    // mocked file content
    expect(screen.getByText("Capítulo 1")).toBeInTheDocument();
    expect(screen.queryByText("2 archivos")).not.toBeInTheDocument();
  });

  it("shows breadcrumb with mundo and section", () => {
    renderWikiEditor();

    // Breadcrumb shows mundo and section names — scoped to the nav so the
    // invisible measurement layer (sibling of the nav) cannot match
    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(breadcrumb).getByText("lore")).toBeInTheDocument();
  });

  it("shows breadcrumb with file path when file is selected", () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(breadcrumb).getByText("lore")).toBeInTheDocument();
    // "capitulos" and "cap1.md" appear both in breadcrumb AND in the
    // file tree sidebar — scope to the breadcrumb nav for exact assertions
    expect(within(breadcrumb).getByText("capitulos")).toBeInTheDocument();
    expect(within(breadcrumb).getByText("cap1.md")).toBeInTheDocument();
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

    // Both the sidebar tree and the central cards area show a spinner
    // while the tree loads
    expect(screen.getAllByRole("status")).toHaveLength(2);
  });

  it("shows error banner when tree fetch fails", () => {
    (useFileTree as Mock).mockReturnValue({
      nodes: [],
      isLoading: false,
      error: new Error("Failed to fetch"),
      mutate: vi.fn(),
    });

    renderWikiEditor();

    // Sidebar tree error banner
    expect(
      screen.getByText(/No se pudo cargar el árbol de archivos/i),
    ).toBeInTheDocument();
    // Central cards area error banner
    expect(
      screen.getByText(/No se pudo cargar el contenido de la sección/i),
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

    // Sidebar tree empty state
    expect(
      screen.getByText(/Esta sección está vacía/i),
    ).toBeInTheDocument();
    // Central cards area empty state
    expect(
      screen.getByText("La sección está vacía"),
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
    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    const loreButton = within(breadcrumb).getByText("lore");
    await user.click(loreButton);

    // After navigation, the breadcrumb should still show "lore"
    expect(within(breadcrumb).getByText("lore")).toBeInTheDocument();
  });

  it("navigates to the world page when the world breadcrumb chip is clicked", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/wiki/Vibrantes/lore"]}>
        <Routes>
          <Route path="/wiki/:mundo/:section/*" element={<WikiEditor />} />
          <Route
            path="/wiki/:mundo"
            element={<div data-testid="world-page">World page</div>}
          />
        </Routes>
      </MemoryRouter>,
    );

    // The world chip is inside the breadcrumb nav — scope the query so the
    // Navbar world selector ("Vibrantes") cannot match.
    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    await user.click(within(breadcrumb).getByRole("button", { name: "Vibrantes" }));

    expect(screen.getByTestId("world-page")).toBeInTheDocument();
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

  it("hides the YAML frontmatter from the editor textarea", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: frontmatterFile,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    await user.click(screen.getByRole("button", { name: /editar/i }));
    const textarea = screen.getByRole("textbox", {
      name: /editor de contenido/i,
    });

    // Only the body is editable — the YAML never reaches the textarea
    const value = (textarea as HTMLTextAreaElement).value;
    expect(value).toBe("# Anisa\n\nEste es el cuerpo.");
    expect(value).not.toContain("type: Personaje");
    expect(value).not.toContain("title: Anisa");
  });

  it("Guardar re-merges the frontmatter with the edited body", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: frontmatterFile,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    await user.click(screen.getByRole("button", { name: /editar/i }));
    const textarea = screen.getByRole("textbox", {
      name: /editor de contenido/i,
    });
    await user.type(textarea, " editado");

    await user.click(screen.getByRole("button", { name: /guardar/i }));

    // The on-disk file must stay byte-identical: frontmatter block +
    // edited body, exactly as loaded
    await waitFor(() => {
      expect(saveFile).toHaveBeenCalledWith(
        "Vibrantes",
        "lore",
        "capitulos/cap1.md",
        "---\ntype: Personaje\ntitle: Anisa\n---\n# Anisa\n\nEste es el cuerpo. editado",
      );
    });
  });

  it("saves a file without frontmatter unchanged", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    await user.click(screen.getByRole("button", { name: /editar/i }));
    const textarea = screen.getByRole("textbox", {
      name: /editor de contenido/i,
    });
    await user.type(textarea, " modificado");

    await user.click(screen.getByRole("button", { name: /guardar/i }));

    // No frontmatter → no block injected; the body is saved as-is
    await waitFor(() => {
      expect(saveFile).toHaveBeenCalledWith(
        "Vibrantes",
        "lore",
        "capitulos/cap1.md",
        "# Capítulo 1\n\nEste es el contenido del **capítulo 1**. modificado",
      );
    });
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

  // ── Image gallery flow: picker only from the editing toolbar ──

  const mockGalleryImage = {
    path: "wiki/media/foto.jpg",
    name: "foto.jpg",
    size_bytes: 2048,
    extension: ".jpg",
  };

  function mockGalleryWithImage() {
    (useImages as Mock).mockReturnValue({
      images: [mockGalleryImage],
      total: 1,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
  }

  it("does not show the Imagen button in view mode", () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    expect(
      screen.queryByRole("button", { name: /^imagen$/i }),
    ).not.toBeInTheDocument();
  });

  it("Imagen toolbar button opens the image picker in edit mode", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
    mockGalleryWithImage();

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    await user.click(screen.getByRole("button", { name: /editar/i }));
    await user.click(screen.getByRole("button", { name: /^imagen$/i }));

    expect(
      screen.getByRole("dialog", { name: /seleccionar imagen/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("foto.jpg")).toBeInTheDocument();
  });

  it("selecting an image inserts ![alt](path) at the caret", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
    mockGalleryWithImage();

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    await user.click(screen.getByRole("button", { name: /editar/i }));
    const textarea = screen.getByRole("textbox", {
      name: /editor de contenido/i,
    });
    await user.clear(textarea);
    await user.type(textarea, "Hola mundo");
    // Place the caret after "Hola " — the markdown must splice exactly there
    (textarea as HTMLTextAreaElement).setSelectionRange(5, 5);

    await user.click(screen.getByRole("button", { name: /^imagen$/i }));
    await user.click(screen.getByRole("button", { name: /foto\.jpg/i }));
    await user.click(screen.getByRole("button", { name: /^aceptar$/i }));

    expect(textarea).toHaveValue(
      "Hola ![foto](wiki/media/foto.jpg)mundo",
    );
    expect(
      screen.queryByRole("dialog", { name: /seleccionar imagen/i }),
    ).not.toBeInTheDocument();
  });

  it("inserts image markdown with suffix via liveDiffRef when preview is open", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
    mockGalleryWithImage();

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    await user.click(screen.getByRole("button", { name: /editar/i }));
    const textarea = screen.getByRole("textbox", {
      name: /editor de contenido/i,
    });
    await user.type(textarea, " modificado");

    await user.click(screen.getByRole("button", { name: /vista previa/i }));
    expect(await screen.findByTestId("live-diff-editor")).toBeInTheDocument();

    // Open the picker, choose the image, pick "← Izquierda" — the markdown
    // must go through the live diff's imperative handle with the #left suffix
    await user.click(screen.getByRole("button", { name: /^imagen$/i }));
    await user.click(screen.getByRole("button", { name: /foto\.jpg/i }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: /alineación/i }),
      "left",
    );
    await user.click(screen.getByRole("button", { name: /^aceptar$/i }));

    expect(insertTextMock).toHaveBeenCalledWith(
      "![foto](wiki/media/foto.jpg#left)",
    );
  });

  // ── Unified file bar + Import Image modal ──

  it("shows 'Importar Imagen' in the file bar and opens the modal", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    // View mode: the bar offers Importar Imagen next to Editar
    expect(
      screen.getByRole("button", { name: /importar imagen/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /editar/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /importar imagen/i }));

    // The modal opens with the DropZone inside
    expect(
      screen.getByRole("dialog", { name: /importar imagen/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/arrastrá una imagen o hacé clic para seleccionar/i),
    ).toBeInTheDocument();
  });

  it("closes the import modal via the close button and Escape", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    await user.click(screen.getByRole("button", { name: /importar imagen/i }));

    // Close button (header X) dismisses the modal
    await user.click(screen.getByRole("button", { name: "Cerrar" }));
    expect(
      screen.queryByRole("dialog", { name: /importar imagen/i }),
    ).not.toBeInTheDocument();

    // Reopen — Escape dismisses it too
    await user.click(screen.getByRole("button", { name: /importar imagen/i }));
    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("dialog", { name: /importar imagen/i }),
    ).not.toBeInTheDocument();
  });

  it("does not render the dropzone in the central view without the modal", () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    expect(
      screen.queryByText(/arrastrá una imagen/i),
    ).not.toBeInTheDocument();
  });

  it("uploads a dropped image and shows success feedback in the modal", async () => {
    const uploadMock = vi
      .fn()
      .mockResolvedValue({ path: "wiki/media/foto.jpg" });
    (useImageUpload as Mock).mockReturnValue({
      upload: uploadMock,
      isUploading: false,
      uploadError: null,
    });
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    await user.click(screen.getByRole("button", { name: /importar imagen/i }));

    const file = new File(["img"], "foto.jpg", { type: "image/jpeg" });
    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    await user.upload(fileInput, file);

    expect(uploadMock).toHaveBeenCalledWith(file);
    expect(await screen.findByText(/imagen subida ✓/i)).toBeInTheDocument();
    expect(screen.getByText("foto.jpg")).toBeInTheDocument();
  });

  it("shows an upload error banner in the modal when the upload fails", async () => {
    (useImageUpload as Mock).mockReturnValue({
      upload: vi.fn().mockRejectedValue(new Error("boom")),
      isUploading: false,
      uploadError: new Error("boom"),
    });
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    await user.click(screen.getByRole("button", { name: /importar imagen/i }));

    const file = new File(["img"], "foto.jpg", { type: "image/jpeg" });
    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    await user.upload(fileInput, file);

    expect(
      await screen.findByText(/error al subir imagen: boom/i),
    ).toBeInTheDocument();
  });

  // ── Card ⋯ action flows (T16) ───────────────────────────────────────

  it("open: the ⋯ menu 'Abrir' navigates like a card click", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    const user = userEvent.setup();
    renderWikiEditor();

    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Abrir" }));

    // Navigated to the file — the viewer shows the mocked content
    expect(await screen.findByText("Capítulo 1")).toBeInTheDocument();
  });

  it("rename: inline commit calls moveNode with the same-parent path", async () => {
    const user = userEvent.setup();
    renderWikiEditor();

    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Renombrar" }));

    const input = screen.getByRole("textbox", { name: "Nuevo nombre" });
    expect(input).toHaveValue("notas.md");
    await user.clear(input);
    await user.type(input, "renombrada.md{Enter}");

    await waitFor(() => {
      expect(moveNode).toHaveBeenCalledWith(
        "Vibrantes",
        "notas.md",
        "renombrada.md",
      );
    });
  });

  it("duplicate: ⋯ menu action calls duplicateFile", async () => {
    const user = userEvent.setup();
    renderWikiEditor();

    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Duplicar" }));

    await waitFor(() => {
      expect(duplicateFile).toHaveBeenCalledWith("Vibrantes", "notas.md");
    });
  });

  it("move: modal shows 4 sections and Mover aquí calls moveNode with the dest", async () => {
    const user = userEvent.setup();
    renderWikiEditor();

    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Mover a…" }));

    const dialog = screen.getByRole("dialog", { name: /mover a/i });
    // 4 destination tabs including referencias (decision (b))
    expect(
      within(dialog).getByRole("tab", { name: "Referencias" }),
    ).toBeInTheDocument();

    await user.click(within(dialog).getByRole("tab", { name: "Referencias" }));
    await user.click(
      within(dialog).getByRole("button", { name: "Mover aquí" }),
    );

    await waitFor(() => {
      // The modal emits a destination DIRECTORY; the handler appends the
      // source basename so the backend gets the final target path.
      expect(moveNode).toHaveBeenCalledWith(
        "Vibrantes",
        "lore/notas.md",
        "referencias/notas.md",
      );
    });
  });

  it("move: confirming a same-folder destination is a no-op (no 409)", async () => {
    const user = userEvent.setup();
    renderWikiEditor();

    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Mover a…" }));

    const dialog = screen.getByRole("dialog", { name: /mover a/i });
    // Root of the current section == the file's current folder → no-op.
    await user.click(within(dialog).getByRole("tab", { name: "Lore" }));
    await user.click(
      within(dialog).getByRole("button", { name: "Mover aquí" }),
    );

    expect(moveNode).not.toHaveBeenCalled();
    expect(
      await screen.findByText(/ya está en esa carpeta/i),
    ).toBeInTheDocument();
  });

  it("Mover a sección…: dialog lists sections, confirms → cross-section moveNode", async () => {
    const user = userEvent.setup();
    renderWikiEditor();

    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Mover a sección…" }));

    const dialog = screen.getByRole("dialog", { name: /mover a sección/i });
    // Current section (Lore) is excluded; the rest are offered
    expect(within(dialog).queryByRole("radio", { name: "Lore" })).not.toBeInTheDocument();
    expect(
      within(dialog).getByRole("radio", { name: "Personajes" }),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("radio", { name: "Sagas" })).toBeInTheDocument();
    expect(
      within(dialog).getByRole("radio", { name: "Referencias" }),
    ).toBeInTheDocument();
    // Irreversibility warning is visible
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      /no se puede deshacer/i,
    );
    // Confirm stays disabled until a section is chosen
    expect(
      within(dialog).getByRole("button", { name: "Confirmar" }),
    ).toBeDisabled();

    await user.click(within(dialog).getByRole("radio", { name: "Personajes" }));
    await user.click(
      within(dialog).getByRole("button", { name: "Confirmar" }),
    );

    await waitFor(() => {
      expect(moveNode).toHaveBeenCalledWith(
        "Vibrantes",
        "lore/notas.md",
        "personajes/notas.md",
      );
    });
    // Success toast names the destination section
    expect(await screen.findByText(/Movido a Personajes\//)).toBeInTheDocument();
  });

  it("Mover a sección…: Cancelar closes without calling moveNode", async () => {
    const user = userEvent.setup();
    renderWikiEditor();

    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Mover a sección…" }));

    const dialog = screen.getByRole("dialog", { name: /mover a sección/i });
    await user.click(within(dialog).getByRole("button", { name: "Cancelar" }));

    expect(moveNode).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("dialog", { name: /mover a sección/i }),
    ).not.toBeInTheDocument();
  });

  it("tree drag & drop: dropping a node onto a folder calls moveNode and toasts", async () => {
    renderWikiEditor();

    const tree = within(
      screen.getByRole("navigation", { name: "File tree" }),
    );

    const dt = new DataTransfer();
    fireEvent.dragStart(tree.getByRole("button", { name: "notas.md" }), {
      dataTransfer: dt,
    });
    fireEvent.drop(tree.getByRole("button", { name: "capitulos" }), {
      dataTransfer: dt,
    });

    // Absorption animation (~150ms) precedes the move request
    await waitFor(() => {
      expect(moveNode).toHaveBeenCalledWith(
        "Vibrantes",
        "lore/notas.md",
        "lore/capitulos/notas.md",
      );
    });
    expect(await screen.findByText(/Movido a capitulos\//)).toBeInTheDocument();
  });

  it("tree drag & drop: dropping onto a file node does nothing", async () => {
    renderWikiEditor();

    const tree = within(
      screen.getByRole("navigation", { name: "File tree" }),
    );

    const dt = new DataTransfer();
    fireEvent.dragStart(tree.getByRole("button", { name: "capitulos" }), {
      dataTransfer: dt,
    });
    fireEvent.drop(tree.getByRole("button", { name: "notas.md" }), {
      dataTransfer: dt,
    });

    expect(moveNode).not.toHaveBeenCalled();
  });

  it("delete: confirmation shows the target name and Cancel aborts (S12)", async () => {
    const user = userEvent.setup();
    renderWikiEditor();

    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Eliminar" }));

    const dialog = screen.getByRole("dialog", { name: /eliminar/i });
    expect(within(dialog).getByText(/notas\.md/i)).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Cancelar" }));

    expect(deleteFile).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("dialog", { name: /eliminar/i }),
    ).not.toBeInTheDocument();
  });

  it("delete: confirming moves the file to the trash", async () => {
    const user = userEvent.setup();
    renderWikiEditor();

    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Eliminar" }));

    await user.click(
      within(screen.getByRole("dialog", { name: /eliminar/i })).getByRole(
        "button",
        { name: /^eliminar$/i },
      ),
    );

    await waitFor(() => {
      expect(deleteFile).toHaveBeenCalledWith("Vibrantes", "lore", "notas.md");
    });
    expect(
      screen.queryByRole("dialog", { name: /eliminar/i }),
    ).not.toBeInTheDocument();
  });

  it("file bar: new-file button creates at the section root (item 14)", async () => {
    const user = userEvent.setup();
    renderWikiEditor();

    await user.click(screen.getByRole("button", { name: "Nuevo archivo" }));

    const input = screen.getByRole("textbox", { name: "Nombre del archivo…" });
    await user.type(input, "nota2.md{Enter}");

    await waitFor(() => {
      expect(createFile).toHaveBeenCalledWith("Vibrantes", "lore", "nota2.md");
    });
  });

  it("file bar: new-folder button creates via the _README placeholder (item 14)", async () => {
    const user = userEvent.setup();
    renderWikiEditor();

    await user.click(screen.getByRole("button", { name: "Nueva carpeta" }));

    const input = screen.getByRole("textbox", {
      name: "Nombre de la subcarpeta…",
    });
    await user.type(input, "nueva{Enter}");

    await waitFor(() => {
      expect(createFile).toHaveBeenCalledWith(
        "Vibrantes",
        "lore",
        "nueva/_README.md",
      );
    });
  });

  it("file bar: creation inside an open directory keeps the directory prefix (item 14)", async () => {
    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos"]);

    // File-only actions must not leak into the directory screen
    expect(
      screen.queryByRole("button", { name: "Importar Imagen" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Editar" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Nuevo archivo" }));

    const input = screen.getByRole("textbox", { name: "Nombre del archivo…" });
    await user.type(input, "cap3.md{Enter}");

    await waitFor(() => {
      expect(createFile).toHaveBeenCalledWith(
        "Vibrantes",
        "lore",
        "capitulos/cap3.md",
      );
    });
  });

  it("file bar: creation buttons hide while a file is open (item 14)", () => {
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    expect(
      screen.queryByRole("button", { name: "Nuevo archivo" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Nueva carpeta" }),
    ).not.toBeInTheDocument();
  });

  // ── Status chip (item 14): Borrador/Canon badge in the file bar ──

  // A wiki ficha whose frontmatter carries the OKF draft status
  const draftFile = {
    ...mockFileContent,
    content:
      "---\ntype: Personaje\ntitle: Anisa\nstatus: draft\n---\n# Anisa\n\nCuerpo.",
  };

  function mockOpenFile(file = mockFileContent) {
    (useFileContent as Mock).mockReturnValue({
      file,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
  }

  it("status chip: hidden while browsing (no file open)", () => {
    renderWikiEditor();

    expect(
      screen.queryByRole("button", { name: /estado:/i }),
    ).not.toBeInTheDocument();
  });

  it("status chip: hidden on directory screens", () => {
    mockOpenFile();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos"]);

    expect(
      screen.queryByRole("button", { name: /estado:/i }),
    ).not.toBeInTheDocument();
  });

  it("status chip: shows Canon by default for files without a status field", () => {
    mockOpenFile();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    expect(
      screen.getByRole("button", { name: "Estado: Canon" }),
    ).toBeInTheDocument();
  });

  it("status chip: shows Borrador when the ficha frontmatter is draft", () => {
    mockOpenFile(draftFile);
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    expect(
      screen.getByRole("button", { name: "Estado: Borrador" }),
    ).toBeInTheDocument();
  });

  it("status chip: selecting a status calls setStatus and revalidates the content", async () => {
    const mutate = vi.fn();
    (useFileContent as Mock).mockReturnValue({
      file: draftFile,
      isLoading: false,
      error: null,
      mutate,
    });

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    await user.click(
      screen.getByRole("button", { name: "Estado: Borrador" }),
    );
    await user.click(
      within(screen.getByRole("menu")).getByRole("menuitemradio", {
        name: /canon/i,
      }),
    );

    await waitFor(() => {
      expect(setStatus).toHaveBeenCalledWith(
        "Vibrantes",
        "lore",
        "capitulos/cap1.md",
        "stable",
      );
    });
    expect(mutate).toHaveBeenCalled();
  });

  it("status chip: failed mutation shows the error and keeps the chip unchanged", async () => {
    (setStatus as Mock).mockRejectedValue({
      status: 500,
      detail: "Error interno del servidor. Revisá los logs del backend.",
    });
    mockOpenFile();
    const mutate = vi.fn();
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate,
    });

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    await user.click(screen.getByRole("button", { name: "Estado: Canon" }));
    await user.click(
      within(screen.getByRole("menu")).getByRole("menuitemradio", {
        name: /borrador/i,
      }),
    );

    expect(
      await screen.findByRole("alert"),
    ).toHaveTextContent(/error interno del servidor/i);
    // Chip unchanged and content NOT revalidated (state untouched on failure)
    expect(
      screen.getByRole("button", { name: "Estado: Canon" }),
    ).toBeInTheDocument();
    expect(mutate).not.toHaveBeenCalled();
  });

  it("set-cover: raw picker → getFileContent → saveFile with the portada applied (S32)", async () => {
    (getFileContent as Mock).mockResolvedValue({
      path: "notas.md",
      name: "notas.md",
      content: "---\ntype: Nota\ntitle: X\n---\nCuerpo",
      size_bytes: 30,
      modified: "2024-01-01T00:00:00Z",
      extension: ".md",
    });
    mockGalleryWithImage();

    const user = userEvent.setup();
    renderWikiEditor();

    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    await user.click(
      screen.getByRole("menuitem", { name: "Establecer portada…" }),
    );

    const picker = screen.getByRole("dialog", { name: /seleccionar imagen/i });
    // rawMode: no alignment/size dropdowns in cover mode
    expect(
      within(picker).queryByRole("combobox", { name: /alineación/i }),
    ).not.toBeInTheDocument();

    await user.click(within(picker).getByRole("button", { name: /foto\.jpg/i }));
    await user.click(within(picker).getByRole("button", { name: /aceptar/i }));

    await waitFor(() => {
      expect(getFileContent).toHaveBeenCalledWith("Vibrantes", "lore", "notas.md");
    });
    await waitFor(() => {
      expect(saveFile).toHaveBeenCalledWith(
        "Vibrantes",
        "lore",
        "notas.md",
        "---\ntype: Nota\ntitle: X\nportada: wiki/media/foto.jpg\n---\nCuerpo",
      );
    });
  });

  it("set-cover failure: detail visible and the tree is NOT refreshed (S34)", async () => {
    (getFileContent as Mock).mockResolvedValue({
      path: "notas.md",
      name: "notas.md",
      content: "---\ntype: Nota\n---\nCuerpo",
      size_bytes: 30,
      modified: "2024-01-01T00:00:00Z",
      extension: ".md",
    });
    (saveFile as Mock).mockRejectedValue({
      status: 500,
      detail: "Error interno del servidor. Revisá los logs del backend.",
    });
    mockGalleryWithImage();
    const mutate = vi.fn();
    (useFileTree as Mock).mockReturnValue({
      nodes: mockTreeNodes,
      isLoading: false,
      error: null,
      mutate,
    });

    const user = userEvent.setup();
    renderWikiEditor();

    await user.click(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    );
    await user.click(
      screen.getByRole("menuitem", { name: "Establecer portada…" }),
    );

    const picker = screen.getByRole("dialog", { name: /seleccionar imagen/i });
    await user.click(within(picker).getByRole("button", { name: /foto\.jpg/i }));
    await user.click(within(picker).getByRole("button", { name: /aceptar/i }));

    // The error surfaces inline (S36); the tree stays untouched (S34)
    expect(
      await screen.findByRole("alert"),
    ).toHaveTextContent(/error interno del servidor/i);
    expect(mutate).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Acciones de notas.md" }),
    ).toBeInTheDocument();
  });

  it("file bar: 'Eliminar Ficha' sends the open ficha to the trash (item 10)", async () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    const user = userEvent.setup();
    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    // 'Eliminar Ficha' lives inside the ⋯ options dropdown (file bar).
    await user.click(screen.getByRole("button", { name: /opciones de ficha/i }));
    await user.click(screen.getByRole("menuitem", { name: /eliminar ficha/i }));

    const dialog = screen.getByRole("dialog", { name: /eliminar/i });
    expect(within(dialog).getByText(/cap1\.md/i)).toBeInTheDocument();

    await user.click(
      within(dialog).getByRole("button", { name: /^eliminar$/i }),
    );

    await waitFor(() => {
      expect(deleteFile).toHaveBeenCalledWith(
        "Vibrantes",
        "lore",
        "capitulos/cap1.md",
      );
    });
    expect(
      screen.queryByRole("dialog", { name: /eliminar/i }),
    ).not.toBeInTheDocument();
  });

  it("file bar: 'Papelera' shows while browsing, 'Eliminar Ficha' does not (item 10)", () => {
    renderWikiEditor();

    // Cards/browsing view: trash management is reachable, but there is no
    // open ficha to delete — the two are mutually exclusive. The ⋯ options
    // dropdown (houses 'Eliminar Ficha') only renders on an open ficha.
    expect(
      screen.getByRole("button", { name: /papelera/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /opciones de ficha/i }),
    ).toBeNull();
  });

  it("file bar: 'Eliminar Ficha' shows on an open ficha, 'Papelera' does not (item 10)", () => {
    (useFileContent as Mock).mockReturnValue({
      file: mockFileContent,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    renderWikiEditor(["/wiki/Vibrantes/lore/capitulos/cap1.md"]);

    // Open ficha: the ⋯ options dropdown is reachable (houses 'Eliminar
    // Ficha'), but the trash-management entry point lives only in the
    // cards view — mutually exclusive.
    expect(
      screen.getByRole("button", { name: /opciones de ficha/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /papelera/i })).toBeNull();
  });

  // ── Papelera TTL (item 8): lazy 30-day purge surfaced as a toast ──

  it("Papelera: TTL purge result surfaces as a toast when listTrash returns purged > 0", async () => {
    (listTrash as Mock).mockResolvedValue({
      entries: [
        {
          entry_id: "e1",
          section: "lore",
          original_path: "lore/old.md",
          kind: "file",
          deleted_at: "2026-01-01T10:00:00Z",
          size: 128,
        },
      ],
      purged: 3,
    });

    const user = userEvent.setup();
    renderWikiEditor();

    await user.click(screen.getByRole("button", { name: /papelera/i }));

    // The lazy TTL purge (GET /papelera) removed 3 expired entries — the
    // panel surfaces the count through the editor's toast.
    expect(
      await screen.findByText("3 expired entries auto-purged (30-day TTL)."),
    ).toBeInTheDocument();
  });

  it("Papelera: no TTL toast when listTrash reports purged 0", async () => {
    (listTrash as Mock).mockResolvedValue({
      entries: [],
      purged: 0,
    });

    const user = userEvent.setup();
    renderWikiEditor();

    await user.click(screen.getByRole("button", { name: /papelera/i }));

    // The panel loads the (empty) list normally — no purge, no toast.
    expect(
      await screen.findByText("La papelera está vacía"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/auto-purged/i)).not.toBeInTheDocument();
  });
});
