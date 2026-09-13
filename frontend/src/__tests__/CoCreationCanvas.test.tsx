import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  CoCreationCanvas,
  normalizePendingQuestion,
} from "@/components/organisms/CoCreation/CoCreationCanvas";
import type { DraftPayload } from "@/api/types";

const payload: DraftPayload = {
  name: "Eneagrama",
  description: "Tipos de personalidad",
  purpose: "Modelar los nueve eneatipos",
  scope: "Personajes",
  main_flow: "Clasificar y derivar arcos",
  branches: ["Rama A", "Rama B"],
  rules: ["Regla 1"],
  pending_questions: [
    { text: "¿Aplica a mundos con magia?", state: "pendiente" },
    { text: "¿Incluye plantillas?", state: "aceptada_por_autor" },
  ],
  world: null,
};

function renderCanvas(overrides: Partial<Parameters<typeof CoCreationCanvas>[0]> = {}) {
  const props = {
    payload,
    onChange: vi.fn(),
    canUndo: false,
    canRedo: false,
    onUndo: vi.fn(),
    onRedo: vi.fn(),
    isSaving: false,
    saveError: null,
    onPendingQuestionStatus: vi.fn(),
    onUploadAdjunto: vi.fn(),
    onRemoveAdjunto: vi.fn(),
    isUploadingAdjunto: false,
    ...overrides,
  };
  render(<CoCreationCanvas {...props} />);
  return props;
}

describe("CoCreationCanvas", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders every per-section editor (REQ-CC-11)", () => {
    renderCanvas();

    expect(screen.getByDisplayValue("Eneagrama")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Modelar los nueve eneatipos")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Clasificar y derivar arcos")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Rama A")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Regla 1")).toBeInTheDocument();
    expect(screen.getByText("Preguntas pendientes")).toBeInTheDocument();
  });

  it("fires onChange with the section patch on edit (REQ-CC-11)", () => {
    const props = renderCanvas();

    // Controlled component: fire the change with the full new value (the
    // parent owns the payload, so the input snaps back between events).
    fireEvent.change(screen.getByDisplayValue("Modelar los nueve eneatipos"), {
      target: { value: "Nuevo propósito" },
    });

    expect(props.onChange).toHaveBeenCalledWith(
      expect.objectContaining({ purpose: "Nuevo propósito" }),
    );
  });

  it("adds and removes branch/rules list items through onChange", async () => {
    const user = userEvent.setup();
    const props = renderCanvas();

    await user.type(screen.getByLabelText("Nueva rama"), "Rama C");
    await user.click(screen.getByRole("button", { name: "Añadir rama" }));
    expect(props.onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ branches: ["Rama A", "Rama B", "Rama C"] }),
    );

    await user.click(screen.getByRole("button", { name: "Quitar rama 2" }));
    // The parent owns the payload (mock does not re-render), so the list is
    // still ["Rama A", "Rama B"]: removing index 1 sends ["Rama A"].
    expect(props.onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ branches: ["Rama A"] }),
    );
  });

  it("renders pending questions read-only with Author-only status buttons (REQ-CC-14)", async () => {
    const user = userEvent.setup();
    const props = renderCanvas();

    // Entries are displayed read-only (no editable text input for them).
    expect(
      screen.getByText("¿Aplica a mundos con magia?"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: /pregunta/i }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Aceptar" }));
    expect(props.onPendingQuestionStatus).toHaveBeenCalledWith(
      0,
      "aceptada_por_autor",
    );

    // The accepted entry renders its state badge and no buttons.
    expect(screen.getAllByText("Aceptada por el autor").length).toBeGreaterThan(0);
  });

  it("normalizes legacy plain-string pending questions", () => {
    expect(normalizePendingQuestion("texto viejo")).toEqual({
      text: "texto viejo",
      state: "pendiente",
    });
    expect(
      normalizePendingQuestion({ text: "t", state: "resuelta" }),
    ).toEqual({ text: "t", state: "resuelta" });
  });

  it("wires the undo/redo toolbar to the in-memory stack (REQ-CC-15)", async () => {
    const user = userEvent.setup();
    const props = renderCanvas({ canUndo: true, canRedo: true });

    await user.click(screen.getByRole("button", { name: "Deshacer edición" }));
    await user.click(screen.getByRole("button", { name: "Rehacer edición" }));
    expect(props.onUndo).toHaveBeenCalledTimes(1);
    expect(props.onRedo).toHaveBeenCalledTimes(1);
  });

  it("disables undo/redo when the stack is empty", () => {
    renderCanvas({ canUndo: false, canRedo: false });

    expect(
      screen.getByRole("button", { name: "Deshacer edición" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Rehacer edición" }),
    ).toBeDisabled();
  });

  it("surfaces the autosave status and errors in the toolbar", () => {
    renderCanvas({ isSaving: true });
    expect(screen.getByText("Guardando…")).toBeInTheDocument();

    renderCanvas({ isSaving: false, saveError: "revision_conflict" });
    expect(screen.getByRole("alert")).toHaveTextContent("revision_conflict");
  });

  it("freezes all editors in review/complete phases", () => {
    renderCanvas({ disabled: true });

    expect(screen.getByDisplayValue("Eneagrama")).toBeDisabled();
    expect(screen.getByDisplayValue("Rama A")).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Aceptar" }),
    ).not.toBeInTheDocument();
  });

  it("shows an empty-state message when there is no payload yet", () => {
    renderCanvas({ payload: null });

    expect(
      screen.getByText(/El lienzo todavía no tiene contenido/),
    ).toBeInTheDocument();
  });

  // -- "Ejemplares" section (REQ-CC-24) -------------------------------------

  const adjuntosPayload: DraftPayload = {
    ...payload,
    adjuntos: [
      { path: "mapa.md", sha256: "a".repeat(64), bytes: 1024, nivel: "mundo" },
      { path: "fauna.md", sha256: "b".repeat(64), bytes: 2048, nivel: "region" },
    ],
  };

  it("renders exemplars as metadata only without fetching carrier bytes (REQ-CC-24)", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    try {
      renderCanvas({ payload: adjuntosPayload });

      expect(screen.getByText("Ejemplares")).toBeInTheDocument();
      expect(screen.getByText("mapa.md")).toBeInTheDocument();
      expect(screen.getByText("fauna.md")).toBeInTheDocument();
      expect(screen.getByText("mundo")).toBeInTheDocument();
      expect(screen.getByText("region")).toBeInTheDocument();
      expect(screen.getByText("1024 bytes")).toBeInTheDocument();
      expect(screen.getByText("2048 bytes")).toBeInTheDocument();
      // `sha256` is metadata the UI must NOT surface, and the section never
      // fetches carrier bytes to render.
      expect(screen.queryByText("a".repeat(64))).not.toBeInTheDocument();
      expect(screen.queryByText("b".repeat(64))).not.toBeInTheDocument();
      expect(fetchMock).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("shows the empty state when the payload has no exemplars (legacy payload parses, REQ-CC-24)", () => {
    renderCanvas();

    expect(screen.getByText(/No hay ejemplares cargados/)).toBeInTheDocument();
  });

  it("uploads an exemplar with the selected file and nivel (REQ-CC-24)", async () => {
    const user = userEvent.setup();
    const props = renderCanvas();
    const file = new File(["# Mapa"], "mapa.md", { type: "text/markdown" });

    await user.upload(screen.getByLabelText("Ejemplar (.md)"), file);
    await user.type(screen.getByLabelText("Nivel del ejemplar"), "mundo");
    await user.click(screen.getByRole("button", { name: "Subir ejemplar" }));

    expect(props.onUploadAdjunto).toHaveBeenCalledWith(file, "mundo");
  });

  it("removes an exemplar by path (REQ-CC-24)", async () => {
    const user = userEvent.setup();
    const props = renderCanvas({ payload: adjuntosPayload });

    await user.click(
      screen.getByRole("button", { name: "Quitar ejemplar 1" }),
    );

    expect(props.onRemoveAdjunto).toHaveBeenCalledWith("mapa.md");
  });

  it("freezes the exemplar controls when the canvas is disabled (REQ-CC-24)", () => {
    renderCanvas({ payload: adjuntosPayload, disabled: true });

    expect(
      screen.queryByRole("button", { name: "Subir ejemplar" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Quitar ejemplar 1" }),
    ).not.toBeInTheDocument();
  });
});