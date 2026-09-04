import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  CoCreationContextPanel,
  CoCreationMilestoneSidebar,
  CoCreationPanel,
} from "@/components/organisms/CoCreationPanel";
import type { UseCoCreationReturn } from "@/hooks/useCoCreation";
import type { CoCreationSession } from "@/api/types";

const sessionFixture = (
  overrides: Partial<CoCreationSession> = {},
): CoCreationSession => ({
  protocol_version: "co-creation-v1",
  session_id: "co-creation-abc123",
  principal_id: "principal-1",
  world: null,
  revision: 3,
  milestone: "alcance",
  progress: [
    { name: "proposito", state: "completado" },
    { name: "alcance", state: "actual" },
    { name: "flujo_principal", state: "pendiente" },
    { name: "ramas_reglas", state: "pendiente" },
    { name: "borrador_listo", state: "pendiente" },
    { name: "revision_publicacion", state: "pendiente" },
  ],
  question_count: 2,
  pending_question: "¿La skill es para un mundo específico o transversal?",
  pending_options: ["Mundo específico", "Transversal"],
  messages: [
    { role: "author", content: "Quiero una skill de eneagrama" },
    { role: "assistant", content: "¿Cuál es el propósito?" },
  ],
  phase: "conversation",
  draft_id: null,
  compile_issues: null,
  draft_payload: null,
  warnings: [],
  history_count: 0,
  derived_from: null,
  ...overrides,
});

const baseState = (): UseCoCreationReturn => ({
  session: null,
  published: null,
  activation: null,
  isLoading: false,
  error: null,
  create: vi.fn(),
  send: vi.fn(),
  recover: vi.fn(),
  materialize: vi.fn(),
  publish: vi.fn(),
  activate: vi.fn(),
  reset: vi.fn(),
  // TW12 canvas
  draftPayload: null,
  canvasError: null,
  editCanvas: vi.fn(),
  undo: vi.fn(),
  redo: vi.fn(),
  canUndo: false,
  canRedo: false,
  isSavingCanvas: false,
  validateCanvas: vi.fn(),
  validation: null,
  isValidating: false,
  loadHistory: vi.fn(),
  historyEntries: [],
  isLoadingHistory: false,
  restoreSnapshot: vi.fn(),
  isRestoring: false,
  restoreError: null,
  setWarningStatus: vi.fn(),
  setPendingQuestionStatus: vi.fn(),
  // TW13/TW14
  derive: vi.fn(),
  getPublishedDetail: vi.fn(),
  derivedFrom: null,
});

describe("CoCreationMilestoneSidebar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the six milestones with completado/actual/pendiente styling", () => {
    const state = {
      ...baseState(),
      session: sessionFixture(),
    };
    render(<CoCreationMilestoneSidebar state={state} />);

    expect(screen.getByText("Propósito")).toBeInTheDocument();
    expect(screen.getByText("Alcance")).toBeInTheDocument();
    expect(screen.getByText("Flujo principal")).toBeInTheDocument();
    expect(screen.getByText("Ramas y reglas")).toBeInTheDocument();
    expect(screen.getByText("Borrador listo")).toBeInTheDocument();
    expect(screen.getByText("Revisión y publicación")).toBeInTheDocument();
    // Exactly the server-owned "actual" milestone is the current step.
    expect(screen.getByText("Alcance").closest("li")).toHaveAttribute(
      "aria-current",
      "step",
    );
    expect(screen.getByText("Propósito").closest("li")).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("resets the session from the sidebar", async () => {
    const user = userEvent.setup();
    const state = {
      ...baseState(),
      session: sessionFixture(),
    };
    render(<CoCreationMilestoneSidebar state={state} />);

    await user.click(screen.getByRole("button", { name: "Nueva sesión" }));

    expect(state.reset).toHaveBeenCalledTimes(1);
  });
});

describe("CoCreationPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("starts a session from the author's idea", async () => {
    const user = userEvent.setup();
    const state = baseState();
    render(<CoCreationPanel state={state} worlds={["Vibrantes"]} />);

    await user.type(
      screen.getByRole("textbox", { name: "Idea de skill" }),
      "Quiero una skill de eneagrama",
    );
    await user.click(screen.getByRole("button", { name: "Crear skill" }));

    expect(state.create).toHaveBeenCalledWith(
      "Quiero una skill de eneagrama",
      null,
    );
  });

  it("renders one pending question per turn and sends an option as the answer", async () => {
    const user = userEvent.setup();
    const state = {
      ...baseState(),
      session: sessionFixture(),
    };
    render(<CoCreationPanel state={state} worlds={["Vibrantes"]} />);

    expect(
      screen.getByText("¿La skill es para un mundo específico o transversal?"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Transversal" }));

    expect(state.send).toHaveBeenCalledWith("Transversal");
  });

  it("shows the materialization confirmation only at Borrador listo", async () => {
    const user = userEvent.setup();
    const state = {
      ...baseState(),
      session: sessionFixture({
        milestone: "borrador_listo",
        pending_question: null,
        pending_options: [],
        messages: [{ role: "assistant", content: "El borrador está listo." }],
      }),
    };
    render(<CoCreationPanel state={state} worlds={["Vibrantes"]} />);

    expect(screen.getByText(/Borrador listo — confirmá los datos/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Generar borrador" }));

    expect(state.materialize).toHaveBeenCalledTimes(1);
  });

  it("keeps the publish button disabled while compiler issues remain", () => {
    const state = {
      ...baseState(),
      session: sessionFixture({
        phase: "review",
        milestone: "revision_publicacion",
        draft_id: "draft-1",
        compile_issues: [
          { code: "AUTH_CLAIM", message: "Autoridad no permitida", field: "delta" },
        ],
        pending_question: null,
        pending_options: [],
      }),
    };
    render(<CoCreationPanel state={state} worlds={["Vibrantes"]} />);

    expect(screen.getByRole("button", { name: "Publicar" })).toBeDisabled();
  });

  it("enables publish only when the draft has zero issues", async () => {
    const user = userEvent.setup();
    const state = {
      ...baseState(),
      session: sessionFixture({
        phase: "review",
        milestone: "revision_publicacion",
        draft_id: "draft-1",
        compile_issues: [],
        pending_question: null,
        pending_options: [],
      }),
    };
    render(<CoCreationPanel state={state} worlds={["Vibrantes"]} />);

    const publish = screen.getByRole("button", { name: "Publicar" });
    expect(publish).toBeEnabled();
    await user.click(publish);

    expect(state.publish).toHaveBeenCalledTimes(1);
  });
});

describe("CoCreationContextPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows compiler issues with code, message and field", () => {
    const state = {
      ...baseState(),
      session: sessionFixture({
        milestone: "borrador_listo",
        compile_issues: [
          { code: "AUTH_CLAIM", message: "Autoridad no permitida", field: "delta" },
        ],
        pending_question: null,
        pending_options: [],
      }),
    };
    render(<CoCreationContextPanel state={state} />);

    expect(screen.getByText("AUTH_CLAIM")).toBeInTheDocument();
    expect(screen.getByText("Autoridad no permitida")).toBeInTheDocument();
    expect(screen.getByText("delta")).toBeInTheDocument();
    expect(screen.getByText(/errores de compilación/)).toBeInTheDocument();
  });

  it("reports a clean compile when there are no issues", () => {
    const state = {
      ...baseState(),
      session: sessionFixture({
        phase: "review",
        milestone: "revision_publicacion",
        draft_id: "draft-1",
        compile_issues: [],
        pending_question: null,
        pending_options: [],
      }),
    };
    render(<CoCreationContextPanel state={state} />);

    expect(screen.getByText(/compila correctamente/)).toBeInTheDocument();
  });

  it("shows the world binding for a world-scoped session", () => {
    const state = {
      ...baseState(),
      session: sessionFixture({ world: "Vibrantes" }),
    };
    render(<CoCreationContextPanel state={state} />);

    expect(screen.getByText(/ligada a «Vibrantes»/)).toBeInTheDocument();
  });
});