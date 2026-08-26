import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
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
  tags: ["arquero"],
  status: "fresh",
  used_in: [],
  based_on: null,
};

const detail: IdeaDetail = { ...summary, body: "Un arquero que no ve." };

function renderPage() {
  return render(
    <MemoryRouter>
      <IdeasWorkshop />
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
    expect(await screen.findByRole("button", { name: /arquero-ciego/ })).toBeInTheDocument();

    // Right panel: persistent assistant (null-mundo)
    expect(screen.getByTestId("assistant-sidebar")).toBeInTheDocument();

    // Empty detail state before a selection
    expect(screen.getByText("Banco global de ideas")).toBeInTheDocument();
  });

  it("filters the list by type when the filter changes", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("button", { name: /arquero-ciego/ });

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

  it("loads the detail and materializes the idea into a world", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    materializeIdeaMock.mockResolvedValue({
      ok: true,
      used_in: ["vibrantes"],
      canon_path: null,
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /arquero-ciego/ }));

    expect(getIdeaMock).toHaveBeenCalledWith("arquero-ciego");
    expect(
      await screen.findByRole("heading", { name: "arquero-ciego" }),
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

  it("reclassifies the idea type via the classification action", async () => {
    const user = userEvent.setup();
    getIdeaMock.mockResolvedValue(detail);
    updateIdeaMock.mockResolvedValue({ ...detail, type: "concepto" });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /arquero-ciego/ }));
    await screen.findByRole("heading", { name: "arquero-ciego" });

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

    await user.click(await screen.findByRole("button", { name: /arquero-ciego/ }));
    await screen.findByRole("heading", { name: "arquero-ciego" });

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