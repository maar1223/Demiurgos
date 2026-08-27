import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { SWRConfig } from "swr";
import IdeasWorkshop from "@/pages/IdeasWorkshop";
import App from "@/App";
import * as ideasApi from "@/api/ideas";
import type { IdeaDetail } from "@/api/ideas";

vi.mock("@/api/ideas", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/ideas")>();
  return {
    ...actual,
    listIdeas: vi.fn(),
    getIdea: vi.fn(),
    createIdea: vi.fn(),
    updateIdea: vi.fn(),
    deleteIdea: vi.fn(),
    materializeIdea: vi.fn(),
  };
});

vi.mock("@/components/organisms/Navbar", () => ({
  Navbar: () => <div aria-label="navbar" />,
}));

vi.mock("@/components/organisms/AIAssistantSidebar", () => ({
  AIAssistantSidebar: () => <div data-testid="assistant-sidebar" />,
}));

vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: () => ({
    worlds: [{ name: "vibrantes", path: "/vibrantes" }],
    isLoading: false,
    isValidating: false,
    error: null,
    mutate: vi.fn(),
  }),
}));

vi.mock("@/hooks/useAuthGate", () => ({
  useAuthGate: () => ({
    loading: false,
    needsLogin: false,
    authEnabled: false,
  }),
}));

vi.mock("@/hooks/useOnboardingGate", () => ({
  useOnboardingGate: () => ({ loading: false, needsOnboarding: false }),
}));

const listIdeasMock = vi.mocked(ideasApi.listIdeas);
const getIdeaMock = vi.mocked(ideasApi.getIdea);
const createIdeaMock = vi.mocked(ideasApi.createIdea);
const updateIdeaMock = vi.mocked(ideasApi.updateIdea);
const deleteIdeaMock = vi.mocked(ideasApi.deleteIdea);
const materializeIdeaMock = vi.mocked(ideasApi.materializeIdea);

const summary: ideasApi.IdeaSummary = {
  id: "a1",
  slug: "arquero-ciego",
  timestamp: "2026-08-25T15:00:00Z",
  source: "manual",
  type: "personaje",
  title: "El Arquero Ciego",
  tags: ["arquero"],
  status: "fresh",
  used_in: [],
  based_on: null,
};

const detail: IdeaDetail = { ...summary, body: "Un arquero que no ve." };

function renderPage() {
  // Fresh SWR cache per render — SWR's module-level cache would otherwise
  // leak stale list/detail responses between tests (order-dependent).
  return render(
    <MemoryRouter>
      <SWRConfig value={{ provider: () => new Map() }}>
        <IdeasWorkshop />
      </SWRConfig>
    </MemoryRouter>,
  );
}

describe("IdeasWorkshop", () => {
  beforeEach(() => {
    listIdeasMock.mockReset();
    getIdeaMock.mockReset();
    createIdeaMock.mockReset();
    updateIdeaMock.mockReset();
    deleteIdeaMock.mockReset();
    materializeIdeaMock.mockReset();
    listIdeasMock.mockResolvedValue({ ideas: [summary], total: 1 });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the two-panel structure: filterable list + detail + assistant", async () => {
    renderPage();

    // Left panel: filter controls + idea list
    expect(screen.getByRole("heading", { name: "Ideas" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filtrar por tipo" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filtrar por estado" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filtrar por origen" })).toBeInTheDocument();
    // The list shows the human-readable title (falls back to slug).
    expect(await screen.findByRole("button", { name: /El Arquero Ciego/ })).toBeInTheDocument();

    // Right panel: persistent assistant (null-mundo)
    expect(screen.getByTestId("assistant-sidebar")).toBeInTheDocument();

    // Empty detail state before a selection
    expect(screen.getByText("Banco global de ideas")).toBeInTheDocument();
  });

  it("falls back to the slug when the title is empty (list + detail header)", async () => {
    const user = userEvent.setup();
    listIdeasMock.mockResolvedValue({
      ideas: [{ ...summary, title: "" }],
      total: 1,
    });
    getIdeaMock.mockResolvedValue({ ...detail, title: "" });
    renderPage();

    // List item primary line shows the slug when title is empty.
    expect(await screen.findByRole("button", { name: /arquero-ciego/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /arquero-ciego/ }));
    // Detail header falls back to the slug too.
    expect(
      await screen.findByRole("heading", { name: "arquero-ciego" }),
    ).toBeInTheDocument();
  });

  it("filters the list by type when the filter changes", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("button", { name: /El Arquero Ciego/ });

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Filtrar por tipo" }),
      "personaje",
    );

    await waitFor(() =>
      expect(listIdeasMock).toHaveBeenCalledWith({
        type: "personaje",
        status: undefined,
        source: undefined,
      }),
    );
  });

  it("creates a manual idea from the form", async () => {
    const user = userEvent.setup();
    createIdeaMock.mockResolvedValue({ ...detail, slug: "nueva-idea" });
    renderPage();

    await user.click(screen.getByRole("button", { name: "Nueva idea" }));

    const form = screen.getByRole("group", { name: "Crear idea" });
    await user.type(within(form).getByLabelText("Slug"), "nueva-idea");
    await user.type(
      within(form).getByLabelText("Etiquetas (separadas por coma)"),
      "arquetipo",
    );
    await user.type(within(form).getByLabelText("Cuerpo"), "Una idea nueva.");
    await user.click(within(form).getByRole("button", { name: "Crear idea" }));

    await waitFor(() =>
      expect(createIdeaMock).toHaveBeenCalledWith({
        slug: "nueva-idea",
        type: "sin_clasificar",
        body: "Una idea nueva.",
        tags: ["arquetipo"],
      }),
    );
  });

  it("creates a manual idea with an optional title", async () => {
    const user = userEvent.setup();
    createIdeaMock.mockResolvedValue({ ...detail, slug: "prototipo", title: "Prototipo de diosa" });
    renderPage();

    await user.click(screen.getByRole("button", { name: "Nueva idea" }));

    const form = screen.getByRole("group", { name: "Crear idea" });
    await user.type(within(form).getByLabelText("Slug"), "prototipo");
    await user.type(within(form).getByLabelText("Título (opcional)"), "Prototipo de diosa");
    await user.type(within(form).getByLabelText("Cuerpo"), "Una idea nueva.");
    await user.click(within(form).getByRole("button", { name: "Crear idea" }));

    await waitFor(() =>
      expect(createIdeaMock).toHaveBeenCalledWith({
        slug: "prototipo",
        type: "sin_clasificar",
        body: "Una idea nueva.",
        tags: [],
        title: "Prototipo de diosa",
      }),
    );
  });

  it("loads the detail and materializes the idea into a world", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    materializeIdeaMock.mockResolvedValue({
      ok: true,
      used_in: ["vibrantes"],
      canon_path: null,
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));

    expect(getIdeaMock).toHaveBeenCalledWith("arquero-ciego");
    expect(
      await screen.findByRole("heading", { name: "El Arquero Ciego" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Un arquero que no ve.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Materializar" }));
    await user.selectOptions(
      screen.getByLabelText("Mundo"),
      "vibrantes",
    );
    await user.click(screen.getByRole("button", { name: "Materializar" }));

    await waitFor(() =>
      expect(materializeIdeaMock).toHaveBeenCalledWith(
        "arquero-ciego",
        "vibrantes",
        undefined,
      ),
    );
  });

  it("renders the idea body as markdown with frontmatter hidden (R-1, S-1.1)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue({
      ...detail,
      body: "---\ntype: personaje\n---\n## Summary\n\nThis is a **test** idea.",
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));

    // Markdown structure renders (heading from `## Summary`).
    expect(
      await screen.findByRole("heading", { name: "Summary" }),
    ).toBeInTheDocument();
    // Raw markdown syntax must NOT leak.
    expect(screen.queryByText("**test**")).not.toBeInTheDocument();
    // YAML frontmatter must stay hidden.
    expect(screen.queryByText(/type: personaje/)).not.toBeInTheDocument();
  });

  it("renders embedded idea images from the media API (R-1, S-1.2)", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue({
      ...detail,
      body: "---\nmedia_path: media/arquero-ciego.png\n---\n![idea image](/api/ideas/media/arquero-ciego.png)\n\nUn arquero ciego.",
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));

    // The /api/ path passes through as-is (no mundo prop → default <img>).
    expect(
      await screen.findByRole("img", { name: "idea image" }),
    ).toHaveAttribute("src", "/api/ideas/media/arquero-ciego.png");
    // Frontmatter (media_path line) stays hidden.
    expect(screen.queryByText(/media_path:/)).not.toBeInTheDocument();
  });

  it("edits the idea title from the detail panel", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    updateIdeaMock.mockResolvedValue({ ...detail, title: "Nuevo Título" });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await screen.findByRole("heading", { name: "El Arquero Ciego" });

    const titleInput = screen.getByPlaceholderText("Sin título — se muestra el slug");
    await user.clear(titleInput);
    await user.type(titleInput, "Nuevo Título");
    await user.click(screen.getByRole("button", { name: "Guardar título" }));

    await waitFor(() =>
      expect(updateIdeaMock).toHaveBeenCalledWith("arquero-ciego", { title: "Nuevo Título" }),
    );
  });

  it("reclassifies the idea type via the classification action", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    updateIdeaMock.mockResolvedValue({ ...detail, type: "concepto" });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await screen.findByRole("heading", { name: "El Arquero Ciego" });

    await user.selectOptions(screen.getByLabelText("Tipo de la idea"), "concepto");
    await user.click(screen.getByRole("button", { name: "Guardar tipo" }));

    await waitFor(() =>
      expect(updateIdeaMock).toHaveBeenCalledWith("arquero-ciego", { type: "concepto" }),
    );
  });

  it("deletes the idea after confirmation", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    deleteIdeaMock.mockResolvedValue({ ok: true, slug: "arquero-ciego" });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();

    await user.click(await screen.findByRole("button", { name: /El Arquero Ciego/ }));
    await screen.findByRole("heading", { name: "El Arquero Ciego" });

    await user.click(screen.getByRole("button", { name: "Eliminar idea arquero-ciego" }));

    await waitFor(() => expect(deleteIdeaMock).toHaveBeenCalledWith("arquero-ciego"));
  });
});

describe("IdeasWorkshop route", () => {
  beforeEach(() => {
    listIdeasMock.mockReset();
    listIdeasMock.mockResolvedValue({ ideas: [], total: 0 });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders at /ideas inside the auth and first-run gates", async () => {
    window.history.pushState({}, "", "/ideas");
    render(<App />);

    // The lazy route resolves through the Suspense boundary.
    expect(
      await screen.findByRole("heading", { name: "Ideas" }),
    ).toBeInTheDocument();
  });
});