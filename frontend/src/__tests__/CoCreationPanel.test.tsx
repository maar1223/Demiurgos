import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  CoCreationContextPanel,
  CoCreationMilestoneSidebar,
  CoCreationPanel,
} from "@/components/organisms/CoCreationPanel";
import type { UseCoCreationReturn } from "@/hooks/useCoCreation";
import type { CoCreationSession } from "@/api/types";
import { tEs } from "@/__tests__/i18nTestUtils";

const mockCreateDraft = vi.hoisted(() => vi.fn());
const mockPublish = vi.hoisted(() => vi.fn());
const mockImportPackage = vi.hoisted(() => vi.fn());
const mockListQuarantine = vi.hoisted(() => vi.fn());
const mockTrustQuarantine = vi.hoisted(() => vi.fn());

// CoCreationPanel mounts ManualSkillCreator / SkillImportPanel in the
// "manual"/"import" sub-modes (REQ-CC-1), which call the methodologies API on
// mount/submit — mock the module so those sub-modes never hit the network.
vi.mock("@/api/methodologies", () => ({
  createMethodologyDraft: mockCreateDraft,
  publishMethodologyDraft: mockPublish,
  importPackage: mockImportPackage,
  listQuarantine: mockListQuarantine,
  trustQuarantine: mockTrustQuarantine,
}));

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
  touchedSections: new Set<string>(),
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
  // TW16 exemplar authoring
  uploadAdjunto: vi.fn(),
  removeAdjunto: vi.fn(),
  isUploadingAdjunto: false,
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

    expect(screen.getByText(tEs("cocreation.milestone.proposito"))).toBeInTheDocument();
    expect(screen.getByText(tEs("cocreation.milestone.alcance"))).toBeInTheDocument();
    expect(
      screen.getByText(tEs("cocreation.milestone.flujo_principal")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(tEs("cocreation.milestone.ramas_reglas")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(tEs("cocreation.milestone.borrador_listo")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(tEs("cocreation.milestone.revision_publicacion")),
    ).toBeInTheDocument();
    // Exactly the server-owned "actual" milestone is the current step.
    expect(
      screen.getByText(tEs("cocreation.milestone.alcance")).closest("li"),
    ).toHaveAttribute("aria-current", "step");
    expect(
      screen.getByText(tEs("cocreation.milestone.proposito")).closest("li"),
    ).not.toHaveAttribute("aria-current");
  });

  it("resets the session from the sidebar", async () => {
    const user = userEvent.setup();
    const state = {
      ...baseState(),
      session: sessionFixture(),
    };
    render(<CoCreationMilestoneSidebar state={state} />);

    await user.click(
      screen.getByRole("button", { name: tEs("cocreation.newSession") }),
    );

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
      screen.getByRole("textbox", { name: tEs("cocreation.chat.inputAria") }),
      "Quiero una skill de eneagrama",
    );
    await user.click(
      screen.getByRole("button", { name: tEs("cocreation.chat.create") }),
    );

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

    expect(
      screen.getByText(tEs("cocreation.materialize.heading")),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: tEs("cocreation.materialize.generate") }),
    );

    expect(state.materialize).toHaveBeenCalledTimes(1);
  });

  it("offers exactly the operational taller options in the materialize dropdown (OC-4 S1)", () => {
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

    const tallerSelect = screen.getByLabelText(
      tEs("cocreation.materialize.taller"),
    );
    expect(
      within(tallerSelect)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Mundo", "Ideas"]);
    // No empty-value "Sin taller" option: every manually created skill
    // declares its operational home taller (OC-4).
    expect(
      within(tallerSelect).queryByRole("option", { name: "Sin taller" }),
    ).not.toBeInTheDocument();
    // The dropdown initializes to the operational default (OC-3).
    expect(tallerSelect).toHaveValue("Mundo");
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

    expect(screen.getByRole("button", { name: tEs("cocreation.review.publish") })).toBeDisabled();
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

    const publish = screen.getByRole("button", { name: tEs("cocreation.review.publish") });
    expect(publish).toBeEnabled();
    await user.click(publish);

    expect(state.publish).toHaveBeenCalledTimes(1);
  });
});

describe("CoCreationPanel — TW16 review projection (REQ-TW16-1..6)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const reviewPayload = {
    name: "Skill de eneagrama",
    description: "Perfil de los nueve eneatipos.",
    purpose: "Modelar personalidades en el mundo.",
    scope: "Mundo específico",
    main_flow: "Elegir tipo → responder → obtener perfil",
    branches: ["ramificacion-1", "ramificacion-2"],
    rules: ["regla-1"],
    pending_questions: [],
    world: "Vibrantes",
    // Manifest metadata the server folds into the payload at materialization.
    taller: "Mundo",
    etiquetas: ["eneagrama", "personajes"],
    skill_id: "co-created-eneagrama",
    version: "0.1.0",
  };

  const reviewState = (
    overrides: Partial<UseCoCreationReturn> = {},
  ): UseCoCreationReturn => ({
    ...baseState(),
    session: sessionFixture({
      phase: "review",
      milestone: "revision_publicacion",
      draft_id: "draft-review-abc123",
      world: "Vibrantes",
      compile_issues: [],
      pending_question: null,
      pending_options: [],
      draft_payload: reviewPayload,
    }),
    ...overrides,
  });

  it("renders the summary from session.draft_payload (not local state)", () => {
    render(<CoCreationPanel state={reviewState()} worlds={["Vibrantes"]} />);

    expect(screen.getByText("Skill de eneagrama")).toBeInTheDocument();
    expect(
      screen.getByText("Perfil de los nueve eneatipos."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Modelar personalidades en el mundo."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Elegir tipo → responder → obtener perfil"),
    ).toBeInTheDocument();
    expect(screen.getByText("ramificacion-1, ramificacion-2")).toBeInTheDocument();
    expect(screen.getByText("regla-1")).toBeInTheDocument();
    expect(screen.getByText("Mundo")).toBeInTheDocument();
    expect(screen.getByText("eneagrama, personajes")).toBeInTheDocument();
  });

  it("shows the attribution legend and per-section badges from touchedSections", () => {
    render(
      <CoCreationPanel
        state={reviewState({ touchedSections: new Set(["purpose"]) })}
        worlds={["Vibrantes"]}
      />,
    );

    // Canonical legend phrases (REQ-TW16-3).
    expect(
      screen.getByText(tEs("cocreation.attribution.decidido")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(tEs("cocreation.attribution.propuesto")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(tEs("cocreation.attribution.exigido")),
    ).toBeInTheDocument();

    // Purpose was touched in the canvas → Decidido; name untouched → Propuesto.
    const purposeRow = screen
      .getByText(tEs("cocreation.section.purpose"))
      .closest("div") as HTMLElement;
    expect(
      within(purposeRow).getByText(
        tEs("cocreation.attribution.decididoShort"),
      ),
    ).toBeInTheDocument();
    const nameRow = screen
      .getByText(tEs("cocreation.section.name"))
      .closest("div") as HTMLElement;
    expect(
      within(nameRow).getByText(tEs("cocreation.attribution.propuestoShort")),
    ).toBeInTheDocument();
  });

  it("renders permissions as an exigido invariant and dependencies from the world", () => {
    render(<CoCreationPanel state={reviewState()} worlds={["Vibrantes"]} />);

    expect(
      screen.getByText(tEs("cocreation.review.permissionsValue")),
    ).toBeInTheDocument();
    const permissionsRow = screen
      .getByText(tEs("cocreation.review.permissions"))
      .closest("div") as HTMLElement;
    expect(
      within(permissionsRow).getByText(
        tEs("cocreation.attribution.exigidoShort"),
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        tEs("cocreation.review.dependenciesWorld", { world: "Vibrantes" }),
      ),
    ).toBeInTheDocument();
  });

  it("renders dependencies as 'ninguna' without compatibles or a world", () => {
    const state = {
      ...baseState(),
      session: sessionFixture({
        phase: "review",
        milestone: "revision_publicacion",
        draft_id: "draft-review-abc123",
        compile_issues: [],
        pending_question: null,
        pending_options: [],
        world: null,
        draft_payload: { ...reviewPayload, world: null },
      }),
    };
    render(<CoCreationPanel state={state} worlds={[]} />);

    expect(
      screen.getByText(tEs("cocreation.review.dependenciesNone")),
    ).toBeInTheDocument();
  });

  it("hides internals by default and reveals them on expand (REQ-TW16-6)", async () => {
    const user = userEvent.setup();
    render(<CoCreationPanel state={reviewState()} worlds={["Vibrantes"]} />);

    // The internals (draft/manifest identity) live inside the COLLAPSED
    // "Detalles avanzados" <details> — closed by default, so they are not
    // part of the visible review.
    const details = screen
      .getByText(tEs("cocreation.review.advanced"))
      .closest("details") as HTMLElement;
    expect(details).not.toHaveAttribute("open");
    const internalPanel = within(details);
    expect(internalPanel.getByText(/draft-review/)).toBeInTheDocument();
    expect(internalPanel.getByText("co-created-eneagrama")).toBeInTheDocument();
    expect(internalPanel.getByText("0.1.0")).toBeInTheDocument();

    await user.click(screen.getByText(tEs("cocreation.review.advanced")));
    expect(details).toHaveAttribute("open");
  });

  it("keeps the publish button approving the reviewed candidate (REQ-TW16-7)", async () => {
    const user = userEvent.setup();
    const state = reviewState();
    render(<CoCreationPanel state={state} worlds={["Vibrantes"]} />);

    expect(screen.getByRole("button", { name: tEs("cocreation.review.publish") })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: tEs("cocreation.review.publish") }));

    expect(state.publish).toHaveBeenCalledTimes(1);
  });
});

describe("CoCreationPanel — authoring sub-modes (REQ-CC-1)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListQuarantine.mockResolvedValue({ entries: [] });
  });

  it("defaults to guided mode with the chat surface visible (SC-CC-1.1)", () => {
    render(<CoCreationPanel state={baseState()} worlds={["Vibrantes"]} />);

    expect(
      screen.getByRole("textbox", { name: tEs("cocreation.chat.inputAria") }),
    ).toBeInTheDocument();

    const toggle = screen.getByRole("tablist", {
      name: tEs("cocreation.tabs.modeAria"),
    });
    expect(
      within(toggle).getByRole("tab", { name: tEs("cocreation.tabs.guided") }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      within(toggle).getByRole("tab", { name: tEs("cocreation.tabs.manual") }),
    ).toHaveAttribute("aria-selected", "false");
    expect(
      within(toggle).getByRole("tab", { name: tEs("cocreation.tabs.import") }),
    ).toHaveAttribute("aria-selected", "false");
  });

  it("renders the manual markdown draft form in manual mode (SC-CC-1.2)", async () => {
    const user = userEvent.setup();
    render(<CoCreationPanel state={baseState()} worlds={["Vibrantes"]} />);

    await user.click(
      screen.getByRole("tab", { name: tEs("cocreation.tabs.manual") }),
    );

    expect(screen.getByText("Publicar un borrador")).toBeInTheDocument();
    expect(screen.getByLabelText("Skill ID")).toBeInTheDocument();
    expect(screen.getByLabelText("Versión")).toBeInTheDocument();
    expect(screen.getByLabelText("Nombre")).toBeInTheDocument();
    expect(screen.getByLabelText(/Fuente/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Publicar borrador" }),
    ).toBeInTheDocument();
    // The guided chat surface is not mounted in manual mode.
    expect(
      screen.queryByRole("textbox", {
        name: tEs("cocreation.chat.inputAria"),
      }),
    ).not.toBeInTheDocument();
  });

  it("renders the .zip import/quarantine block in import mode (SC-CC-1.3)", async () => {
    const user = userEvent.setup();
    render(<CoCreationPanel state={baseState()} worlds={["Vibrantes"]} />);

    await user.click(
      screen.getByRole("tab", { name: tEs("cocreation.tabs.import") }),
    );

    expect(await screen.findByText("Importar una skill")).toBeInTheDocument();
    expect(screen.getByLabelText(/Paquete/)).toBeInTheDocument();
  });

  it("preserves the guided chat input across guided→manual→guided (SC-CC-1.4)", async () => {
    const user = userEvent.setup();
    render(<CoCreationPanel state={baseState()} worlds={["Vibrantes"]} />);

    await user.type(
      screen.getByRole("textbox", { name: tEs("cocreation.chat.inputAria") }),
      "Quiero una skill de eneagrama",
    );

    await user.click(
      screen.getByRole("tab", { name: tEs("cocreation.tabs.manual") }),
    );
    expect(screen.getByText("Publicar un borrador")).toBeInTheDocument();

    await user.click(
      screen.getByRole("tab", { name: tEs("cocreation.tabs.guided") }),
    );

    expect(
      screen.getByRole("textbox", { name: tEs("cocreation.chat.inputAria") }),
    ).toHaveValue("Quiero una skill de eneagrama");
  });

  it("preserves the guided canvas view across guided→manual→guided (SC-CC-1.4)", async () => {
    const user = userEvent.setup();
    const state = { ...baseState(), session: sessionFixture() };
    render(<CoCreationPanel state={state} worlds={["Vibrantes"]} />);

    // Switch the guided surface to the canvas (TW12).
    await user.click(
      screen.getByRole("tab", { name: tEs("cocreation.tabs.canvas") }),
    );
    expect(
      screen.getByRole("tab", { name: tEs("cocreation.tabs.canvas") }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByRole("button", { name: tEs("cocreation.canvas.history") }),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("tab", { name: tEs("cocreation.tabs.manual") }),
    );
    expect(screen.getByText("Publicar un borrador")).toBeInTheDocument();
    // The chat/canvas toggle is a guided-only surface.
    expect(
      screen.queryByRole("tablist", {
        name: tEs("cocreation.tabs.surfaceAria"),
      }),
    ).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("tab", { name: tEs("cocreation.tabs.guided") }),
    );
    expect(
      screen.getByRole("tab", { name: tEs("cocreation.tabs.canvas") }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByRole("button", { name: tEs("cocreation.canvas.history") }),
    ).toBeInTheDocument();
  });

  it("shows the guided intro line (UC-3 S1)", () => {
    render(<CoCreationPanel state={baseState()} worlds={["Vibrantes"]} />);

    // Guided mode is the default: the intro must read exactly per spec UC-3 S1.
    expect(
      screen.getByText(tEs("cocreation.intro.guided")),
    ).toBeInTheDocument();
  });

  it("swaps the intro line per authoring sub-mode (UL-6 S1)", async () => {
    const user = userEvent.setup();
    render(<CoCreationPanel state={baseState()} worlds={["Vibrantes"]} />);

    // guided (default)
    expect(
      screen.getByText(tEs("cocreation.intro.guided")),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("tab", { name: tEs("cocreation.tabs.manual") }),
    );
    expect(
      screen.getByText(tEs("cocreation.intro.manual")),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("tab", { name: tEs("cocreation.tabs.import") }),
    );
    expect(
      screen.getByText(tEs("cocreation.intro.import")),
    ).toBeInTheDocument();
  });
});

describe("CoCreationContextPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("hides compiler issues by default and shows them on expand (REQ-TW16-6)", async () => {
    const user = userEvent.setup();
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

    // Compiler codes + fields collapse under the closed "Detalles avanzados".
    const details = screen
      .getByText(tEs("cocreation.context.advanced"))
      .closest("details") as HTMLElement;
    expect(details).not.toHaveAttribute("open");
    const internalPanel = within(details);
    expect(internalPanel.getByText("AUTH_CLAIM")).toBeInTheDocument();

    await user.click(screen.getByText(tEs("cocreation.context.advanced")));
    expect(details).toHaveAttribute("open");
    expect(internalPanel.getByText("Autoridad no permitida")).toBeInTheDocument();
    expect(internalPanel.getByText("delta")).toBeInTheDocument();
    expect(
      internalPanel.getByText(tEs("cocreation.context.issues")),
    ).toBeInTheDocument();
  });

  it("reports a clean compile when there are no issues (under Detalles avanzados)", async () => {
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
    render(<CoCreationContextPanel state={state} />);

    await user.click(screen.getByText(tEs("cocreation.context.advanced")));

    expect(
      screen.getByText(tEs("cocreation.context.clean")),
    ).toBeInTheDocument();
  });

  it("shows the world binding for a world-scoped session", () => {
    const state = {
      ...baseState(),
      session: sessionFixture({ world: "Vibrantes" }),
    };
    render(<CoCreationContextPanel state={state} />);

    expect(
      screen.getByText(
        tEs("cocreation.context.worldBound", { world: "Vibrantes" }),
      ),
    ).toBeInTheDocument();
  });
});