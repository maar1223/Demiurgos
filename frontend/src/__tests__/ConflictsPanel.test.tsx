import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import ConflictsPanel from "@/components/organisms/ConflictsPanel";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { translate } from "@/i18n/messages";
import {
  fetchConflicts,
  rejectConflictProposal,
  setConflictDecision,
  sweepConflicts,
} from "@/api/conflicts";
import type {
  ConflictsResponse,
  ReviewProgress,
  WorldConflict,
} from "@/api/conflicts";
import { ApiError } from "@/api/types";

vi.mock("@/hooks/useAppLanguage", () => ({ useAppLanguage: vi.fn() }));
vi.mock("@/api/conflicts", () => ({
  fetchConflicts: vi.fn(),
  setConflictDecision: vi.fn(),
  sweepConflicts: vi.fn(),
  rejectConflictProposal: vi.fn(),
}));

const useAppLanguageMock = vi.mocked(useAppLanguage);
const fetchConflictsMock = vi.mocked(fetchConflicts);
const setConflictDecisionMock = vi.mocked(setConflictDecision);
const sweepConflictsMock = vi.mocked(sweepConflicts);
const rejectConflictProposalMock = vi.mocked(rejectConflictProposal);

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
    decision: null,
    state: "computed",
    origin: "deterministic",
    evidence_a: null,
    evidence_b: null,
    source_a: null,
    source_b: null,
    path_b: null,
    name_b: null,
    ...overrides,
  };
}

function response(
  conflicts: WorldConflict[],
  review: ReviewProgress = { total: 0, reviewed: 0, pending: 0 },
): ConflictsResponse {
  const counted = (decision: WorldConflict["decision"], severity?: string) =>
    conflicts.filter(
      (item) =>
        item.decision === decision &&
        (severity === undefined || item.severity === severity),
    ).length;
  return {
    indexed: true,
    conflicts,
    summary: {
      total: conflicts.length,
      errors:
        counted(null, "error") + counted("structural", "error"),
      warnings: counted(null, "warning") + counted("structural", "warning"),
      known: counted("intentional"),
      muted: counted("muted"),
      proposed: conflicts.filter((item) => item.state === "proposed").length,
      by_code: {},
      review,
    },
  };
}

function FichaProbe() {
  const location = useLocation();
  return (
    <div data-testid="ficha-page">
      {location.pathname}
      {location.search}
    </div>
  );
}

function renderPanel() {
  return render(
    <MemoryRouter initialEntries={["/taller-mundo/vibrantes/relaciones-canon"]}>
      <Routes>
        <Route
          path="/taller-mundo/:mundo/relaciones-canon"
          element={<ConflictsPanel mundo="vibrantes" />}
        />
        <Route path="/wiki/:mundo/:section/*" element={<FichaProbe />} />
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
      "Por revisar: 0 de 0 · Errores: 1 · Advertencias: 1 · Propuestos: 0 · Conocidos: 0 · Silenciados: 0",
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

  it("opens the single ficha of a deterministic conflict", async () => {
    fetchConflictsMock.mockResolvedValue(response([conflict()]));

    renderPanel();

    await screen.findByTestId("conflict-item");
    await userEvent.click(screen.getByTestId("open-ficha"));

    expect(await screen.findByTestId("ficha-page")).toBeInTheDocument();
  });

  it("records an intentional decision and moves the conflict to known", async () => {
    fetchConflictsMock.mockResolvedValue(response([conflict()]));
    setConflictDecisionMock.mockResolvedValue(
      response([conflict({ decision: "intentional" })]),
    );

    renderPanel();

    await screen.findByTestId("conflict-item");
    await userEvent.click(screen.getByRole("button", { name: "Intencional" }));

    expect(setConflictDecisionMock).toHaveBeenCalledWith("vibrantes", {
      conflict_id: "unresolved-reference:lore/alfa.md:Fantasma",
      decision: "intentional",
    });
    expect(await screen.findByTestId("conflicts-known")).toBeInTheDocument();
    expect(screen.queryByTestId("conflicts-errors")).not.toBeInTheDocument();
  });

  it("keeps muted conflicts recoverable", async () => {
    fetchConflictsMock.mockResolvedValue(
      response([conflict({ decision: "muted" })]),
    );
    setConflictDecisionMock.mockResolvedValue(response([conflict()]));

    renderPanel();

    const muted = await screen.findByTestId("conflicts-muted");
    expect(within(muted).getByTestId("conflict-item")).toBeInTheDocument();
    await userEvent.click(
      within(muted).getByRole("button", { name: "Quitar decisión" }),
    );

    expect(setConflictDecisionMock).toHaveBeenCalledWith("vibrantes", {
      conflict_id: "unresolved-reference:lore/alfa.md:Fantasma",
      decision: "clear",
    });
    expect(await screen.findByTestId("conflicts-errors")).toBeInTheDocument();
  });

  it("shows a structural decision as an error with its badge", async () => {
    fetchConflictsMock.mockResolvedValue(
      response([conflict({ decision: "structural" })]),
    );

    renderPanel();

    expect(await screen.findByTestId("structural-badge")).toHaveTextContent(
      "Ruptura estructural",
    );
    expect(screen.getByTestId("conflicts-errors")).toBeInTheDocument();
  });

  it("explains on hover what each decision action does", async () => {
    fetchConflictsMock.mockResolvedValue(
      response([
        conflict(),
        conflict({
          id: "semantic:A:B:date",
          code: "semantic-contradiction",
          state: "proposed",
          origin: "semantic",
          reference: "date",
          evidence_a: "nació en el año 120",
          evidence_b: "nació en el año 145",
          source_a: "Alar",
          source_b: "Vesta",
          path_b: "lore/vesta.md",
          name_b: "Vesta",
        }),
        conflict({ id: "known:lore/beta.md", path: "lore/beta.md", decision: "intentional" }),
      ]),
    );

    renderPanel();
    await screen.findAllByTestId("conflict-item");

    // The labels alone never say what the author is committing to.
    const hints: Record<string, string> = {
      Intencional:
        "Es así a propósito: pasa a Conocidos y deja de contar como error o advertencia.",
      Silenciar:
        "No es un problema: se aparta en Silenciados y deja de contar. Se puede deshacer con Quitar decisión.",
      Ruptura:
        "Ruptura deliberada de la estructura del mundo: queda marcada como ruptura y sigue contando como error.",
      "Falso positivo":
        "El modelo se equivocó: la pareja queda rechazada y no se vuelve a proponer.",
      "Quitar decisión":
        "Quita la decisión guardada y el conflicto vuelve a contar como pendiente.",
    };
    for (const [name, hint] of Object.entries(hints)) {
      const buttons = screen.getAllByRole("button", { name });
      expect(buttons.length).toBeGreaterThan(0);
      expect(buttons.every((button) => button.getAttribute("title") === hint)).toBe(
        true,
      );
    }
  });

  it("keeps the panel and reports an action failure", async () => {
    fetchConflictsMock.mockResolvedValue(response([conflict()]));
    setConflictDecisionMock.mockRejectedValue(new Error("boom"));

    renderPanel();

    await screen.findByTestId("conflict-item");
    await userEvent.click(screen.getByRole("button", { name: "Silenciar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No se pudo guardar la decisión.",
    );
    expect(screen.getByTestId("conflict-item")).toBeInTheDocument();
  });
});

function proposal(overrides: Partial<WorldConflict> = {}): WorldConflict {
  return conflict({
    id: "semantic:A:B:date",
    code: "semantic-contradiction",
    severity: "error",
    path: "lore/alar.md",
    name: "Alar",
    message: "",
    reference: "date",
    state: "proposed",
    origin: "semantic",
    evidence_a: "nació en el año 120",
    evidence_b: "nació en el año 145",
    source_a: "A",
    source_b: "B",
    path_b: "lore/vesta.md",
    name_b: "Vesta",
    ...overrides,
  });
}

describe("ConflictsPanel — semantic proposals (S3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAppLanguageMock.mockReturnValue(lang("es"));
  });

  it("offers both fichas of a proposal, each with its quote", async () => {
    fetchConflictsMock.mockResolvedValue(response([proposal()]));

    renderPanel();

    const pair = await screen.findByTestId("conflict-pair");
    expect(pair).toHaveTextContent("A · Alar");
    expect(pair).toHaveTextContent("lore/alar.md");
    expect(pair).toHaveTextContent("B · Vesta");
    expect(pair).toHaveTextContent("lore/vesta.md");
  });

  it("opens the chosen half with its quote as a highlight", async () => {
    fetchConflictsMock.mockResolvedValue(response([proposal()]));

    renderPanel();

    await screen.findByTestId("conflict-pair");
    await userEvent.click(screen.getByTestId("conflict-ficha-b"));

    const page = await screen.findByTestId("ficha-page");
    expect(page).toHaveTextContent("/wiki/vibrantes/lore/vesta.md");
    expect(page).toHaveTextContent(
      "?highlight=naci%C3%B3%20en%20el%20a%C3%B1o%20145",
    );
  });

  it("still names the other ficha when its path cannot be resolved", async () => {
    fetchConflictsMock.mockResolvedValue(
      response([
        proposal({
          path_b: null,
          name_b: null,
          source_b: "Política | Distribución Y Territorios::Atherr",
        }),
      ]),
    );

    renderPanel();

    const half = await screen.findByTestId("conflict-ficha-b");
    expect(half).toHaveTextContent(
      "Política | Distribución Y Territorios::Atherr",
    );
    expect(half).toHaveTextContent("No se pudo resolver la ruta");
  });

  it("shows both quotes of a proposal", async () => {
    fetchConflictsMock.mockResolvedValue(response([proposal()]));

    renderPanel();

    expect(await screen.findByTestId("conflicts-proposed")).toBeInTheDocument();
    expect(screen.getByTestId("conflict-quote-a")).toHaveTextContent(
      "nació en el año 120",
    );
    expect(screen.getByTestId("conflict-quote-b")).toHaveTextContent(
      "nació en el año 145",
    );
    expect(screen.getByTestId("conflict-summary")).toHaveTextContent(
      "Propuestos: 1",
    );
  });

  it("rejects a false positive", async () => {
    fetchConflictsMock.mockResolvedValue(response([proposal()]));
    rejectConflictProposalMock.mockResolvedValue(response([]));

    renderPanel();

    await screen.findByTestId("conflicts-proposed");
    await userEvent.click(screen.getByTestId("reject-proposal"));

    expect(rejectConflictProposalMock).toHaveBeenCalledWith(
      "vibrantes",
      "semantic:A:B:date",
    );
    expect(await screen.findByTestId("conflicts-empty")).toBeInTheDocument();
  });

  it("sweeps a bounded batch and reports the cost on the button", async () => {
    fetchConflictsMock.mockResolvedValue(
      response([], { total: 5, reviewed: 2, pending: 3 }),
    );
    sweepConflictsMock.mockResolvedValue({
      status: "swept",
      swept: 3,
      created: 2,
      proposals: 2,
      paths: [],
      message: "",
    });

    renderPanel();

    const button = await screen.findByTestId("conflict-sweep");
    expect(button).toHaveTextContent("Revisar 3 fichas · quedan 3");
    await userEvent.click(button);

    expect(sweepConflictsMock).toHaveBeenCalledWith("vibrantes", { size: 3 });
    expect(await screen.findByTestId("sweep-notice")).toHaveTextContent(
      "Revisadas 3 fichas · 2 propuestas nuevas",
    );
  });

  it("says how many claims were discarded for a quote that is not in the ficha", async () => {
    fetchConflictsMock.mockResolvedValue(
      response([], { total: 5, reviewed: 2, pending: 3 }),
    );
    sweepConflictsMock.mockResolvedValue({
      status: "swept",
      swept: 3,
      created: 1,
      discarded: 1,
      proposals: 0,
      paths: [],
      message: "",
    });

    renderPanel();

    await userEvent.click(await screen.findByTestId("conflict-sweep"));

    // Without this the notice promised a proposal the panel never showed.
    expect(await screen.findByTestId("sweep-notice")).toHaveTextContent(
      "1 descartada(s): la cita del modelo no aparece en la ficha.",
    );
  });

  it("says when the provider did not answer", async () => {
    fetchConflictsMock.mockResolvedValue(
      response([], { total: 5, reviewed: 2, pending: 3 }),
    );
    sweepConflictsMock.mockResolvedValue({
      status: "unavailable",
      swept: 0,
      created: 0,
      proposals: 0,
      paths: [],
      message: "",
    });

    renderPanel();

    await userEvent.click(await screen.findByTestId("conflict-sweep"));

    expect(await screen.findByTestId("sweep-notice")).toHaveTextContent(
      "El proveedor semántico no respondió; probá de nuevo.",
    );
  });
});

describe("ConflictsPanel — review progress", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAppLanguageMock.mockReturnValue(lang("es"));
  });

  it("shows how much of the world is still to review", async () => {
    fetchConflictsMock.mockResolvedValue(
      response([conflict()], { total: 68, reviewed: 3, pending: 65 }),
    );

    renderPanel();

    expect(await screen.findByTestId("conflict-summary")).toHaveTextContent(
      "Por revisar: 65 de 68",
    );
    expect(screen.getByTestId("conflict-sweep")).toHaveTextContent(
      "Revisar 3 fichas · quedan 65",
    );
  });

  it("disables the sweep and says so when everything was reviewed", async () => {
    fetchConflictsMock.mockResolvedValue(
      response([], { total: 68, reviewed: 68, pending: 0 }),
    );

    renderPanel();

    const button = await screen.findByTestId("conflict-sweep");
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent("Todo revisado");
  });

  it("says the provider is still working when the sweep times out", async () => {
    fetchConflictsMock.mockResolvedValue(
      response([], { total: 5, reviewed: 2, pending: 3 }),
    );
    sweepConflictsMock.mockRejectedValue(
      new ApiError(0, "timeout", undefined, "network.timeout"),
    );

    renderPanel();

    await userEvent.click(await screen.findByTestId("conflict-sweep"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "El proveedor sigue trabajando; las propuestas pueden aparecer en un momento. Recargá en unos segundos.",
    );
  });

  it("never claims everything is reviewed when the backend has no review block", async () => {
    const legacy = response([conflict()]);
    delete (legacy.summary as { review?: unknown }).review;
    fetchConflictsMock.mockResolvedValue(legacy);

    renderPanel();

    const button = await screen.findByTestId("conflict-sweep");
    expect(button).not.toBeDisabled();
    expect(button).toHaveTextContent("Revisar 3 fichas");
    expect(button).not.toHaveTextContent("Todo revisado");
    expect(screen.getByTestId("conflict-summary")).not.toHaveTextContent(
      "Por revisar",
    );
  });
});
