import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import RelacionesCanon from "@/pages/RelacionesCanon";
import type { Mock } from "vitest";

vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: vi.fn(),
}));

vi.mock("@/components/GraphView", () => ({
  default: () => <div data-testid="graph-view">GraphView</div>,
}));

vi.mock("@/api/conflicts", () => ({
  fetchConflicts: vi.fn(),
  setConflictDecision: vi.fn(),
}));

vi.mock("@/api/graph", () => ({
  fetchRelationCandidates: vi.fn(),
  fetchRelationReconcilePreview: vi.fn(),
  applyRelationReconcile: vi.fn(),
  fetchRelationProposals: vi.fn(),
  sweepRelations: vi.fn(),
  acceptRelationProposal: vi.fn(),
  rejectRelationProposal: vi.fn(),
  muteRelationCandidate: vi.fn(),
  unmuteRelationCandidate: vi.fn(),
}));

import { fetchConflicts } from "@/api/conflicts";
import { useWorlds } from "@/hooks/useWorlds";
import {
  applyRelationReconcile,
  fetchRelationCandidates,
  fetchRelationProposals,
  fetchRelationReconcilePreview,
  muteRelationCandidate,
  sweepRelations,
} from "@/api/graph";

const fetchConflictsMock = vi.mocked(fetchConflicts);

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderPage(
  entry = "/taller-mundo/vibrantes/relaciones-canon",
) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <LocationProbe />
      <Routes>
        <Route
          path="/taller-mundo/:mundo/relaciones-canon/:tab?"
          element={<RelacionesCanon />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RelacionesCanon", () => {
  it("gives the graph tab a definite viewport height and no width cap", () => {
    // Regression: the bleed page used min-height, so every ``h-full`` below it
    // resolved to zero and the canvas rendered empty.
    const { container } = renderPage();
    const main = container.querySelector("main")!;
    expect(main.className).not.toContain("max-w-7xl");

    const page = main.parentElement!;
    expect(page.className).toContain("h-[calc(100vh-3.5rem-1px)]");
    expect(page.className).not.toContain("min-h-[calc(100vh-3.5rem-1px)]");
  });

  beforeEach(() => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [],
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
    vi.mocked(fetchRelationCandidates).mockResolvedValue({
      count: 1,
      muted: [],
      items: [
        {
          path: "lore/alpha.md",
          id: "lore::alpha",
          title: "Alpha",
          digest: "d1",
          mentions: ["lore::beta"],
          missing: ["lore::beta"],
        },
      ],
    });
    vi.mocked(fetchRelationProposals).mockResolvedValue({
      count: 0,
      items: [],
    });
    vi.mocked(sweepRelations).mockResolvedValue({
      status: "swept",
      path: "lore/alpha.md",
      created: 1,
      pending: 1,
      message: "",
    });
    vi.mocked(muteRelationCandidate).mockResolvedValue({
      success: true,
      muted: true,
    });
    vi.mocked(fetchRelationReconcilePreview).mockResolvedValue({
      files: 1,
      additions: 1,
      removals: 1,
      unresolved: 0,
      items: [
        {
          path: "lore/alpha.md",
          add: ["lore::beta"],
          remove: [
            { key: "lore::gamma", target_id: "lore::gamma", reason: "ungrounded" },
          ],
        },
      ],
    });
    vi.mocked(applyRelationReconcile).mockResolvedValue({
      applied: 1,
      failed: [],
      backup: ".relations/preimages/20261031T220000Z",
      files: 1,
      additions: 1,
      removals: 1,
    });
  });

  it("renders three tabs with Grafo active and the graph visible by default", () => {
    renderPage();

    const grafo = screen.getByRole("tab", { name: "Grafo" });
    expect(grafo).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByRole("tab", { name: "Conflictos" }),
    ).toHaveAttribute("aria-selected", "false");
    expect(
      screen.getByRole("tab", { name: "Propuestas" }),
    ).toHaveAttribute("aria-selected", "false");
    expect(screen.getByTestId("graph-view")).toBeInTheDocument();
  });

  it("opens the tab named in the URL", async () => {
    fetchConflictsMock.mockResolvedValue({
      indexed: true,
      conflicts: [],
      summary: {
        total: 0,
        errors: 0,
        warnings: 0,
        known: 0,
        muted: 0,
        proposed: 0,
        by_code: {},
        review: { total: 0, reviewed: 0, pending: 0 },
      },
    });

    renderPage("/taller-mundo/vibrantes/relaciones-canon/conflictos");

    expect(
      screen.getByRole("tab", { name: "Conflictos" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByTestId("conflicts-empty")).toBeInTheDocument();
  });

  it("canonicalises the bare path to the graph route", async () => {
    renderPage();

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/taller-mundo/vibrantes/relaciones-canon/grafo",
      ),
    );
  });

  it("navigates to the tab's own route", async () => {
    fetchConflictsMock.mockResolvedValue({
      indexed: true,
      conflicts: [],
      summary: {
        total: 0,
        errors: 0,
        warnings: 0,
        known: 0,
        muted: 0,
        proposed: 0,
        by_code: {},
        review: { total: 0, reviewed: 0, pending: 0 },
      },
    });
    const user = userEvent.setup();

    renderPage();
    await user.click(screen.getByRole("tab", { name: "Conflictos" }));

    expect(screen.getByTestId("location")).toHaveTextContent(
      "/taller-mundo/vibrantes/relaciones-canon/conflictos",
    );
  });

  it("orders Propuestas before Conflictos", () => {
    // The deterministic sync is reachable from every tab, so the reading order
    // is Grafo → Propuestas → Conflictos: generate with AI, then audit.
    renderPage();

    expect(
      screen.getAllByRole("tab").map((tab) => tab.textContent),
    ).toEqual(["Grafo", "Propuestas", "Conflictos"]);
  });

  it("renders the deterministic conflicts panel in the Conflictos tab", async () => {
    const user = userEvent.setup();
    fetchConflictsMock.mockResolvedValue({
      indexed: true,
      conflicts: [],
      summary: {
        total: 0,
        errors: 0,
        warnings: 0,
        known: 0,
        muted: 0,
        proposed: 0,
        by_code: {},
        review: { total: 0, reviewed: 0, pending: 0 },
      },
    });
    renderPage();

    await user.click(screen.getByRole("tab", { name: "Conflictos" }));

    expect(await screen.findByTestId("conflicts-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("graph-view")).not.toBeInTheDocument();
  });

  it("renders the sweep panel with the candidate count", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("tab", { name: "Propuestas" }));

    expect(screen.getByTestId("proposals-panel")).toBeInTheDocument();
    expect(await screen.findByTestId("candidate-count")).toHaveTextContent(
      "1 fichas con menciones para revisar",
    );
    expect(screen.queryByTestId("graph-view")).not.toBeInTheDocument();
  });

  it("sweeps one candidate on demand and reports the result", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("tab", { name: "Propuestas" }));

    await user.click(await screen.findByTestId("sweep-button"));

    expect(sweepRelations).toHaveBeenCalledWith("vibrantes");
    expect(await screen.findByTestId("sweep-notice")).toHaveTextContent(
      "Revisada lore/alpha.md: 1 propuestas nuevas.",
    );
  });

  it("lets the Author leave a candidate as is", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("tab", { name: "Propuestas" }));

    await user.click(await screen.findByRole("button", { name: "Dejar así" }));

    expect(muteRelationCandidate).toHaveBeenCalledWith(
      "vibrantes",
      "lore/alpha.md",
    );
  });

  it("shows the sync action in the header on every tab", async () => {
    const user = userEvent.setup();
    renderPage();

    const syncButton = await screen.findByTestId("sync-button");
    expect(syncButton).toHaveTextContent("Sincronizar");

    await user.click(screen.getByRole("tab", { name: "Propuestas" }));
    expect(screen.getByTestId("sync-button")).toBeInTheDocument();
  });

  it("does not compute the world plan until the sync dialog is opened", async () => {
    const user = userEvent.setup();
    renderPage();

    // Regression: the plan is a whole-world server scan and the page only uses
    // it to label the button. Paying it on every entry — for every tab — is
    // what made the section take seconds to appear.
    await screen.findByTestId("sync-button");
    expect(fetchRelationReconcilePreview).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("sync-button"));

    await screen.findByRole("dialog");
    expect(fetchRelationReconcilePreview).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("sync-button")).toHaveTextContent(
      "Sincronizar · 1 cambio",
    );
  });

  it("reports a preview failure instead of opening an empty dialog", async () => {
    vi.mocked(fetchRelationReconcilePreview).mockRejectedValue(
      new Error("boom"),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByTestId("sync-button"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No se pudo comprobar el estado de sincronización.",
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("applies the world sync after confirmation", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByTestId("sync-button"));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/Se modificarán 1 fichas/);
    expect(within(dialog).getByText("Cambios por aplicar")).toBeInTheDocument();
    // The per-ficha detail is expandable and lists the actual relations.
    expect(within(dialog).getByText("Se agregan")).toBeInTheDocument();
    expect(within(dialog).getByText("lore::beta")).toBeInTheDocument();
    expect(within(dialog).getByText("Se quitan")).toBeInTheDocument();
    expect(within(dialog).getByText(/lore::gamma/)).toBeInTheDocument();
    expect(
      within(dialog).getByText(/el texto no la respalda/),
    ).toBeInTheDocument();
    await user.click(
      within(dialog).getByRole("button", { name: "Sincronizar ahora" }),
    );

    expect(applyRelationReconcile).toHaveBeenCalledWith("vibrantes");
  });
});
