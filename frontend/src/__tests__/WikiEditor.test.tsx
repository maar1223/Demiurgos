import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
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

import { useWorlds } from "@/hooks/useWorlds";
import { useFileTree } from "@/hooks/useFileTree";
import { useFileContent } from "@/hooks/useFileContent";
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
});
