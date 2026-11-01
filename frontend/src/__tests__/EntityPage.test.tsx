import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { Mock } from "vitest";
import EntityPage from "@/pages/EntityPage";
import { useWorlds } from "@/hooks/useWorlds";
import { useBacklinks } from "@/hooks/useBacklinks";
import { fetchConflicts } from "@/api/conflicts";
import type { ConflictsResponse, WorldConflict } from "@/api/conflicts";

vi.mock("@/hooks/useWorlds", () => ({ useWorlds: vi.fn() }));
vi.mock("@/hooks/useBacklinks", () => ({ useBacklinks: vi.fn() }));
vi.mock("@/components/organisms/EntityDetail", () => ({
  EntityDetail: () => <div data-testid="entity-detail" />,
}));
vi.mock("@/components/organisms/AIAssistantSidebar", () => ({
  AIAssistantSidebar: () => <div data-testid="assistant" />,
}));
vi.mock("@/api/conflicts", () => ({ fetchConflicts: vi.fn() }));

const fetchConflictsMock = vi.mocked(fetchConflicts);

function conflict(name: string): WorldConflict {
  return {
    id: `unresolved-reference:lore/${name}.md:Fantasma`,
    code: "unresolved-reference",
    severity: "error",
    path: `lore/${name}.md`,
    name,
    message: "",
    field: null,
    reference: "Fantasma",
    decision: null,
    state: "computed",
    origin: "deterministic",
    evidence_a: null,
    evidence_b: null,
    source_a: null,
    source_b: null,
  };
}

function response(conflicts: WorldConflict[]): ConflictsResponse {
  return {
    indexed: true,
    conflicts,
    summary: {
      total: conflicts.length,
      errors: conflicts.length,
      warnings: 0,
      known: 0,
      muted: 0,
      proposed: 0,
      by_code: {},
    },
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/wiki/vibrantes/entity/Alfa"]}>
      <Routes>
        <Route path="/wiki/:mundo/entity/*" element={<EntityPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("EntityPage conflict indicator", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (useWorlds as Mock).mockReturnValue({
      worlds: [{ name: "vibrantes" }],
      isLoading: false,
      isValidating: false,
      error: null,
      mutate: vi.fn(),
    });
    (useBacklinks as Mock).mockReturnValue({
      links: [],
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
    fetchConflictsMock.mockResolvedValue(response([]));
  });

  it("shows no banner when the ficha has no conflict", async () => {
    renderPage();

    expect(await screen.findByTestId("entity-detail")).toBeInTheDocument();
    expect(
      screen.queryByTestId("entity-conflict-banner"),
    ).not.toBeInTheDocument();
  });

  it("shows the count and a link to the Conflicts section", async () => {
    fetchConflictsMock.mockResolvedValue(
      response([conflict("Alfa"), conflict("Alfa")]),
    );

    renderPage();

    const banner = await screen.findByTestId("entity-conflict-banner");
    expect(banner).toHaveTextContent(
      "Esta ficha tiene 2 conflictos abiertos.",
    );
    expect(banner).toHaveTextContent("Ver en Conflictos");
  });

  it("ignores conflicts that belong to another ficha", async () => {
    fetchConflictsMock.mockResolvedValue(response([conflict("Bravo")]));

    renderPage();

    expect(await screen.findByTestId("entity-detail")).toBeInTheDocument();
    await waitFor(() => expect(fetchConflictsMock).toHaveBeenCalled());
    expect(
      screen.queryByTestId("entity-conflict-banner"),
    ).not.toBeInTheDocument();
  });
});
