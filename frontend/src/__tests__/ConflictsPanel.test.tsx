import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ConflictsPanel from "@/components/organisms/ConflictsPanel";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { translate } from "@/i18n/messages";
import { fetchConflicts } from "@/api/conflicts";
import type { ConflictsResponse, WorldConflict } from "@/api/conflicts";

vi.mock("@/hooks/useAppLanguage", () => ({ useAppLanguage: vi.fn() }));
vi.mock("@/api/conflicts", () => ({ fetchConflicts: vi.fn() }));

const useAppLanguageMock = vi.mocked(useAppLanguage);
const fetchConflictsMock = vi.mocked(fetchConflicts);

const lang = (language: "es" | "en") => ({
  language,
  t: (
    key: Parameters<typeof translate>[1],
    params?: Parameters<typeof translate>[2],
  ) => translate(language, key, params),
});

function conflict(overrides: Partial<WorldConflict> = {}): WorldConflict {
  return {
    id: "unresolved-reference:lore/alfa.md:Fantasma",
    code: "unresolved-reference",
    severity: "error",
    path: "lore/alfa.md",
    name: "Alfa",
    message: "Wikilink [[Fantasma]] does not resolve to any entity.",
    field: null,
    reference: "Fantasma",
    ...overrides,
  };
}

function response(conflicts: WorldConflict[]): ConflictsResponse {
  return {
    indexed: true,
    conflicts,
    summary: {
      total: conflicts.length,
      errors: conflicts.filter((item) => item.severity === "error").length,
      warnings: conflicts.filter((item) => item.severity === "warning").length,
      by_code: {},
    },
  };
}

function renderPanel() {
  return render(
    <MemoryRouter initialEntries={["/taller-mundo/vibrantes/relaciones-canon"]}>
      <Routes>
        <Route
          path="/taller-mundo/:mundo/relaciones-canon"
          element={<ConflictsPanel mundo="vibrantes" />}
        />
        <Route
          path="/wiki/:mundo/entity/:name"
          element={<div data-testid="ficha-page">ficha</div>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ConflictsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAppLanguageMock.mockReturnValue(lang("es"));
  });

  it("groups errors and warnings and shows the summary", async () => {
    fetchConflictsMock.mockResolvedValue(
      response([
        conflict(),
        conflict({
          id: "missing-minimum:lore/beta.md:origen",
          code: "missing-minimum",
          severity: "warning",
          path: "lore/beta.md",
          name: "Beta",
          message: "Missing minimum.",
          field: "origen, fuente",
          reference: null,
        }),
      ]),
    );

    renderPanel();

    expect(await screen.findByTestId("conflicts-panel")).toBeInTheDocument();
    expect(screen.getByTestId("conflict-summary")).toHaveTextContent(
      "Errores: 1 · Advertencias: 1",
    );
    expect(screen.getByTestId("conflicts-errors")).toBeInTheDocument();
    expect(screen.getByTestId("conflicts-warnings")).toBeInTheDocument();
    expect(screen.getAllByTestId("conflict-item")).toHaveLength(2);
  });

  it("renders the ficha path and the translated message", async () => {
    fetchConflictsMock.mockResolvedValue(response([conflict()]));

    renderPanel();

    const item = await screen.findByTestId("conflict-item");
    expect(item).toHaveTextContent("lore/alfa.md");
    expect(item).toHaveTextContent(
      "La referencia [[Fantasma]] no resuelve a ninguna ficha.",
    );
  });

  it("shows the empty state when the world has no conflicts", async () => {
    fetchConflictsMock.mockResolvedValue(response([]));

    renderPanel();

    expect(await screen.findByTestId("conflicts-empty")).toBeInTheDocument();
    expect(
      screen.getByText("Este mundo no tiene conflictos estructurales."),
    ).toBeInTheDocument();
  });

  it("shows a retryable error when the request fails", async () => {
    fetchConflictsMock.mockRejectedValue(new Error("boom"));

    renderPanel();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No se pudieron cargar los conflictos.",
    );
    fetchConflictsMock.mockResolvedValueOnce(response([]));
    await userEvent.click(screen.getByTestId("conflicts-retry"));
    expect(await screen.findByTestId("conflicts-empty")).toBeInTheDocument();
  });

  it("opens the ficha when an item is clicked", async () => {
    fetchConflictsMock.mockResolvedValue(response([conflict()]));

    renderPanel();

    const item = await screen.findByTestId("conflict-item");
    await userEvent.click(item.querySelector("button")!);

    expect(await screen.findByTestId("ficha-page")).toBeInTheDocument();
  });
});
