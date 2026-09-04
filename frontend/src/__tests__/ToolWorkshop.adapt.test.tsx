import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ToolWorkshop from "@/pages/ToolWorkshop";
import type { Mock } from "vitest";

vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: vi.fn(),
}));

vi.mock("@/api/methodologies", () => ({
  getMethodologyStatus: vi.fn(),
  createMethodologyDraft: vi.fn(),
  publishMethodologyDraft: vi.fn(),
  activateMethodology: vi.fn(),
  getMethodologyInventory: vi.fn(),
}));

vi.mock("@/api/coCreation", () => ({
  createCoCreationSession: vi.fn(),
  turnCoCreationSession: vi.fn(),
  recoverCoCreationSession: vi.fn(),
  coCreationProgress: vi.fn(),
  materializeCoCreationSession: vi.fn(),
  publishCoCreationSession: vi.fn(),
  activateCoCreationSession: vi.fn(),
  updateCanvas: vi.fn(),
  validatePayload: vi.fn(),
  listHistory: vi.fn(),
  restoreHistory: vi.fn(),
  setWarningStatus: vi.fn(),
  setPendingQuestionStatus: vi.fn(),
  getPublishedDetail: vi.fn(),
  deriveDraft: vi.fn(),
}));

import { useWorlds } from "@/hooks/useWorlds";
import {
  getMethodologyInventory,
  getMethodologyStatus,
} from "@/api/methodologies";
import {
  deriveDraft,
  recoverCoCreationSession,
} from "@/api/coCreation";
import type { WorldInfo } from "@/api/types";

const worlds: WorldInfo[] = [
  {
    name: "Vibrantes",
    path: "/vibrantes",
    lore_count: 77,
    character_count: 10,
    reference_count: 0,
  },
];

const status = { published: [], activations: {}, drafts: [] };

const inventory = {
  items: [
    {
      skill_id: "eneagrama",
      version: "1.2.0",
      name: "Eneagrama oficial",
      description: "Clasificación de personalidades",
      digest: "abc",
      published_at: "2026-01-01",
      clasificacion: "Oficiales",
      trust_attributes: ["fundamental"],
    },
  ],
};

/** The adaptation session the derive route opens (seeded canvas + TW14
 *  provenance, server-injected). */
const derivedSession = {
  protocol_version: "co-creation-v1",
  session_id: "adaptation-session",
  principal_id: "principal-1",
  world: "Vibrantes",
  revision: 1,
  milestone: "proposito",
  progress: [
    { name: "proposito", state: "actual" },
    { name: "alcance", state: "pendiente" },
    { name: "flujo_principal", state: "pendiente" },
    { name: "ramas_reglas", state: "pendiente" },
    { name: "borrador_listo", state: "pendiente" },
    { name: "revision_publicacion", state: "pendiente" },
  ],
  question_count: 0,
  pending_question: null,
  pending_options: [],
  messages: [],
  phase: "conversation",
  draft_id: "draft-derivado",
  compile_issues: null,
  draft_payload: {
    name: "Eneagrama oficial",
    description: "",
    purpose: "Modelar los nueve eneatipos",
    scope: "",
    main_flow: "",
    branches: [],
    rules: [],
    pending_questions: [],
    world: "Vibrantes",
  },
  warnings: [],
  history_count: 0,
  derived_from: { skill_id: "eneagrama", version: "1.2.0" },
};

function renderToolWorkshop() {
  return render(
    <MemoryRouter initialEntries={["/taller-herramientas"]}>
      <Routes>
        <Route path="/taller-herramientas" element={<ToolWorkshop />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ToolWorkshop — TW13 adaptation entry on published rows", () => {
  beforeEach(() => {
    window.localStorage.clear();
    (useWorlds as Mock).mockReturnValue({
      worlds,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
    (getMethodologyStatus as Mock).mockResolvedValue(status);
    (getMethodologyInventory as Mock).mockResolvedValue(inventory);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("derives an Oficiales skill through the gate and opens the co-creation tab", async () => {
    const user = userEvent.setup();
    (deriveDraft as Mock).mockResolvedValue({
      session_id: "adaptation-session",
      draft_id: "draft-derivado",
      derived_from: { skill_id: "eneagrama", version: "1.2.0" },
    });
    (recoverCoCreationSession as Mock).mockResolvedValue(derivedSession);

    renderToolWorkshop();

    // Switch the internal lens of the "Taller" tab to the read-only global
    // inventory where the published rows live (REQ-LEN-1 — lens toggle, not
    // a top-level tab).
    await user.click(screen.getByRole("tab", { name: "Catálogo total" }));
    await waitFor(() => {
      expect(screen.getByText("Eneagrama oficial")).toBeInTheDocument();
    });

    // TW13 gate: Oficiales rows offer "Adaptar" (derivation, not in-place).
    await user.click(screen.getByRole("button", { name: "Adaptar" }));

    await waitFor(() => {
      expect(deriveDraft).toHaveBeenCalledWith("eneagrama", "1.2.0", null);
    });

    // The page switches to the "Crear skill" tab bound to the derived session
    // (REQ-CC-17: adaptation = unified chat + canvas on the derived draft).
    // The shared ToolWorkshopHeader now carries the tabs — assert the active
    // top-level tab plus its subtitle (the h2 was removed in task 2.2/PR 2).
    await waitFor(() => {
      expect(
        screen.getByRole("tab", { name: "Crear skill" }),
      ).toHaveAttribute("aria-selected", "true");
    });
    expect(
      screen.getByText(
        "Co-creá una skill conversando con la Skill Madre, una pregunta por vez.",
      ),
    ).toBeInTheDocument();
    expect(recoverCoCreationSession).toHaveBeenCalledWith("adaptation-session");
  });

  it("does not switch tabs when the derive fails", async () => {
    const user = userEvent.setup();
    (deriveDraft as Mock).mockRejectedValue(new Error("not published"));

    renderToolWorkshop();

    await user.click(screen.getByRole("tab", { name: "Catálogo total" }));
    await waitFor(() => {
      expect(screen.getByText("Eneagrama oficial")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Adaptar" }));

    await waitFor(() => {
      expect(deriveDraft).toHaveBeenCalled();
    });
    // Still on the "Taller" tab — the failed derive must not switch views.
    expect(screen.getByRole("tab", { name: "Taller" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});