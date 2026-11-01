import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import RelacionesCanon from "@/pages/RelacionesCanon";
import type { Mock } from "vitest";

vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: vi.fn(),
}));

vi.mock("@/components/GraphView", () => ({
  default: () => <div data-testid="graph-view">GraphView</div>,
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

import { useWorlds } from "@/hooks/useWorlds";
import {
  applyRelationReconcile,
  fetchRelationCandidates,
  fetchRelationProposals,
  fetchRelationReconcilePreview,
  muteRelationCandidate,
  sweepRelations,
} from "@/api/graph";

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/taller-mundo/vibrantes/relaciones-canon"]}>
      <Routes>
        <Route
          path="/taller-mundo/:mundo/relaciones-canon"
          element={<RelacionesCanon />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RelacionesCanon", () => {
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

  it("shows a Próximamente placeholder in the Conflictos tab", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("tab", { name: "Conflictos" }));

    // Navbar also renders a "Próximamente" teaser — scope to the panel.
    expect(
      within(screen.getByTestId("placeholder-panel")).getByText(
        "Próximamente",
      ),
    ).toBeInTheDocument();
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
    await waitFor(() =>
      expect(syncButton).toHaveTextContent("Sincronizar · 1 cambio"),
    );

    await user.click(screen.getByRole("tab", { name: "Propuestas" }));
    expect(screen.getByTestId("sync-button")).toBeInTheDocument();
  });

  it("applies the world sync after confirmation", async () => {
    const user = userEvent.setup();
    renderPage();

    const syncButton = await screen.findByTestId("sync-button");
    await waitFor(() =>
      expect(syncButton).toHaveTextContent("Sincronizar · 1 cambio"),
    );
    await user.click(syncButton);

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
