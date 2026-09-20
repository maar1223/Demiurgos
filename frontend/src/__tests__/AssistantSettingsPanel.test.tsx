import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { Mock } from "vitest";
import {
  clearAssistantKey,
  discoverAssistantModels,
  getAssistantSettings,
  runAssistantTextProbe,
  runAssistantVisionProbe,
  saveAssistantConfiguration,
  validateAssistantConnection,
} from "@/api/assistantSettings";
import { AssistantSettingsPanel } from "@/components/organisms/AssistantSettingsPanel";
import type { AssistantModelOption, AssistantProbeResult, AssistantSettingsStatus } from "@/api/types";
import type { AuthSessionController } from "@/components/organisms/IdeaCapturePanel";

vi.mock("@/api/assistantSettings", () => ({
  clearAssistantKey: vi.fn(),
  discoverAssistantModels: vi.fn(),
  getAssistantSettings: vi.fn(),
  runAssistantTextProbe: vi.fn(),
  runAssistantVisionProbe: vi.fn(),
  saveAssistantConfiguration: vi.fn(),
  validateAssistantConnection: vi.fn(),
}));

const mocked = {
  clearAssistantKey: clearAssistantKey as Mock,
  discoverAssistantModels: discoverAssistantModels as Mock,
  getAssistantSettings: getAssistantSettings as Mock,
  runAssistantTextProbe: runAssistantTextProbe as Mock,
  runAssistantVisionProbe: runAssistantVisionProbe as Mock,
  saveAssistantConfiguration: saveAssistantConfiguration as Mock,
  validateAssistantConnection: validateAssistantConnection as Mock,
};

const models: AssistantModelOption[] = [
  { id: "gpt-5.6-luna", label: "GPT-5.6 Luna", capability: "text-only", pricing: { input: 1 } },
  { id: "vision-unknown", label: "Vision Unknown", capability: "unknown", pricing: null },
];

const status: AssistantSettingsStatus = {
  provider: "opencode-go",
  base_url: "https://opencode.ai/zen/go/v1",
  model: "gpt-5.6-luna",
  model_metadata: models[0],
  key_configured: true,
  models,
  active_profile: "default",
  revision: 1,
  runtime_state: "active",
};

const auth: AuthSessionController = {
  status: {
    mode: "local-dev",
    enabled: true,
    authenticated: true,
    label: "Local development user",
  },
  isLoading: false,
  error: null,
  start: vi.fn(),
  logout: vi.fn(),
};

/** Render the panel inside a Router (it uses useNavigate for the Center CTA). */
const renderPanel = () =>
  render(
    <MemoryRouter>
      <AssistantSettingsPanel auth={auth} />
    </MemoryRouter>,
  );

/** Walk the happy path to the Pruebas step with a discovered model. */
const walkToProbes = async (user: ReturnType<typeof userEvent.setup>) => {
  await screen.findByRole("heading", { name: "Conexión" });
  await user.click(screen.getByRole("button", { name: "Validar conexión" }));
  expect(await screen.findByText("Conexión validada.")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Siguiente" }));
  await screen.findByRole("heading", { name: "Modelo" });
  await user.click(screen.getByRole("button", { name: "Descubrir modelos" }));
  await screen.findByRole("combobox", { name: "Modelo descubierto" });
  await user.click(screen.getByRole("button", { name: "Siguiente" }));
  expect(screen.getByRole("heading", { name: "Pruebas" })).toBeInTheDocument();
};

/** Run both probes and press save. */
const saveFlow = async (user: ReturnType<typeof userEvent.setup>) => {
  await walkToProbes(user);
  await user.click(screen.getByRole("button", { name: "Probar texto + visión" }));
  await screen.findByText("Prueba de visión superada.");
  await user.click(screen.getByRole("button", { name: "Guardar configuración" }));
};

describe("AssistantSettingsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.getAssistantSettings.mockResolvedValue(status);
    mocked.validateAssistantConnection.mockResolvedValue({
      outcome: "validated",
      category: "ok",
      provider: "opencode-go",
    });
    mocked.discoverAssistantModels.mockResolvedValue({ outcome: "discovered", models });
    mocked.runAssistantTextProbe.mockResolvedValue({ outcome: "passed", oracle: "text-marker" });
    mocked.runAssistantVisionProbe.mockResolvedValue({ outcome: "passed", oracle: "causal-vision" });
    mocked.saveAssistantConfiguration.mockResolvedValue(status);
    mocked.clearAssistantKey.mockResolvedValue({ ...status, key_configured: false });
  });

  it("renders exactly three steps and revisits completed ones", async () => {
    const user = userEvent.setup();
    renderPanel();

    await screen.findByRole("heading", { name: "Conexión" });
    const progress = screen.getByRole("navigation", { name: "Pasos de configuración" });
    for (const label of ["Conexión", "Modelo", "Pruebas"]) {
      expect(within(progress).getByText(label)).toBeInTheDocument();
    }
    // Future steps stay static (not selectable) until their gate is met.
    expect(screen.queryByRole("button", { name: /Modelo/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pruebas/ })).not.toBeInTheDocument();

    // Once the connection validates, the completed step is revisitable.
    await user.click(screen.getByRole("button", { name: "Validar conexión" }));
    await screen.findByText("Conexión validada.");
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await screen.findByRole("heading", { name: "Modelo" });
    await user.click(screen.getByRole("button", { name: /Conexión/ }));
    expect(screen.getByRole("heading", { name: "Conexión" })).toBeInTheDocument();
  });

  it("does not mark Modelo done when the backend reports no model id yet", async () => {
    // The GET seeds `selectedModel` from `model_metadata`, which is an object
    // even when nothing is configured yet. An empty id must not read as "done",
    // or a fresh profile shows a completed step the user never completed.
    mocked.getAssistantSettings.mockResolvedValue({
      ...status,
      model: "",
      model_metadata: { id: "", label: "", capability: "unknown", pricing: null },
    });
    renderPanel();

    await screen.findByRole("heading", { name: "Conexión" });
    const progress = screen.getByRole("navigation", { name: "Pasos de configuración" });
    // Step 2 still renders its numeral: it is not complete.
    expect(within(progress).getByText("2")).toBeInTheDocument();
  });

  it("preserves the connection payload when navigating from Conexión to Modelo", async () => {
    const user = userEvent.setup();
    const expectedPayload = {
      provider: "opencode-go",
      base_url: "https://opaque.example/v1",
      api_key: "opaque-test-key",
    };
    renderPanel();
    await screen.findByRole("heading", { name: "Conexión" });
    // Discovery is not reachable before the connection validates.
    expect(screen.queryByRole("button", { name: "Descubrir modelos" })).not.toBeInTheDocument();

    await user.clear(screen.getByLabelText("Endpoint"));
    await user.type(screen.getByLabelText("Endpoint"), expectedPayload.base_url);
    await user.type(screen.getByLabelText("Clave API"), expectedPayload.api_key);
    await user.click(screen.getByRole("button", { name: "Validar conexión" }));
    expect(mocked.validateAssistantConnection).toHaveBeenLastCalledWith(expectedPayload);

    // The transient key survives the step change and feeds discovery.
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await screen.findByRole("heading", { name: "Modelo" });
    await user.click(screen.getByRole("button", { name: "Descubrir modelos" }));
    expect(mocked.discoverAssistantModels).toHaveBeenLastCalledWith(expectedPayload);
    expect(await screen.findByRole("combobox", { name: "Modelo descubierto" })).toHaveValue("gpt-5.6-luna");
    expect(localStorage.length).toBe(0);
    expect(window.location.search).not.toContain("api_key");
  });

  it("fills the OpenCode Go default endpoint when the provider is selected", async () => {
    const user = userEvent.setup();
    mocked.getAssistantSettings.mockResolvedValue({
      ...status,
      provider: "compatible",
      base_url: "https://custom.example/v1",
    });
    renderPanel();
    await screen.findByRole("heading", { name: "Conexión" });

    await user.selectOptions(screen.getByLabelText("Elegí un proveedor"), "opencode-go");

    expect(screen.getByLabelText("Endpoint")).toHaveValue("https://opencode.ai/zen/go/v1");
  });

  it("requires revalidation when the API key changes", async () => {
    const user = userEvent.setup();
    renderPanel();
    await screen.findByRole("heading", { name: "Conexión" });
    await user.click(screen.getByRole("button", { name: "Validar conexión" }));

    expect(await screen.findByText("Conexión validada.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeEnabled();

    await user.type(screen.getByLabelText("Clave API"), "opaque-key-placeholder");

    expect(screen.queryByText("Conexión validada.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();
  });

  it("offers the manual fallback and requires both probes before saving", async () => {
    const user = userEvent.setup();
    mocked.discoverAssistantModels.mockResolvedValue({
      outcome: "failed",
      category: "empty-discovery",
      provider: "opencode-go",
      message: "No usable models were returned",
      models: [],
    });
    renderPanel();
    await screen.findByRole("heading", { name: "Conexión" });
    await user.click(screen.getByRole("button", { name: "Validar conexión" }));
    expect(await screen.findByText("Conexión validada.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await screen.findByRole("heading", { name: "Modelo" });
    await user.click(screen.getByRole("button", { name: "Descubrir modelos" }));
    expect(screen.getByText(/No usable models/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("ID de modelo manual"), "manual-model");
    await user.click(screen.getByRole("button", { name: "Usar modelo manual" }));
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(screen.getByRole("heading", { name: "Pruebas" })).toBeInTheDocument();

    // Saving stays blocked until both probes pass.
    expect(screen.getByRole("button", { name: "Guardar configuración" })).toBeDisabled();
    expect(screen.getByText(/pruebas de texto y visión/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Probar texto + visión" }));
    expect(await screen.findByText("Prueba de texto superada.")).toBeInTheDocument();
    expect(await screen.findByText("Prueba de visión superada.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guardar configuración" })).toBeEnabled();
  });

  it("runs the text probe before the vision probe in the combined step", async () => {
    const user = userEvent.setup();
    renderPanel();
    await walkToProbes(user);

    await user.click(screen.getByRole("button", { name: "Probar texto + visión" }));
    expect(await screen.findByText("Prueba de visión superada.")).toBeInTheDocument();

    const textCall = mocked.runAssistantTextProbe.mock.invocationCallOrder[0];
    const visionCall = mocked.runAssistantVisionProbe.mock.invocationCallOrder[0];
    expect(textCall).toBeLessThan(visionCall);
    expect(mocked.runAssistantTextProbe).toHaveBeenCalledTimes(1);
    expect(mocked.runAssistantVisionProbe).toHaveBeenCalledTimes(1);
    // Both results stay visible together inside the single step.
    expect(screen.getByText("Prueba de texto superada.")).toBeInTheDocument();
    expect(screen.getByText("Prueba de visión superada.")).toBeInTheDocument();
  });

  it("skips vision and keeps saving blocked when the text probe fails", async () => {
    const user = userEvent.setup();
    mocked.runAssistantTextProbe.mockResolvedValue({
      outcome: "not_causal",
      oracle: "text-marker",
      message: "La prueba de texto no pasó.",
    });
    renderPanel();
    await walkToProbes(user);

    await user.click(screen.getByRole("button", { name: "Probar texto + visión" }));
    expect(await screen.findByText("La prueba de texto no pasó.")).toBeInTheDocument();
    expect(screen.getByText("La visión no se ejecutó porque la prueba de texto no pasó.")).toBeInTheDocument();
    expect(mocked.runAssistantVisionProbe).not.toHaveBeenCalled();

    // The footer explains the blocked save; the save button stays disabled.
    expect(screen.getByText(/pruebas de texto y visión/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guardar configuración" })).toBeDisabled();
  });

  it("keeps the text result and shows the vision error when vision fails", async () => {
    const user = userEvent.setup();
    mocked.runAssistantVisionProbe.mockResolvedValue({
      outcome: "not_causal",
      oracle: "causal-vision",
      message: "La prueba de visión no pasó.",
    });
    renderPanel();
    await walkToProbes(user);

    await user.click(screen.getByRole("button", { name: "Probar texto + visión" }));
    expect(await screen.findByText("La prueba de visión no pasó.")).toBeInTheDocument();
    // The separate text evidence stays visible even though vision failed.
    expect(screen.getByText("Prueba de texto superada.")).toBeInTheDocument();
    expect(screen.queryByText("La visión no se ejecutó porque la prueba de texto no pasó.")).not.toBeInTheDocument();

    expect(screen.getByText(/pruebas de texto y visión/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guardar configuración" })).toBeDisabled();
  });

  it("walks Conexión → Modelo → Pruebas and saves without unknown_ack", async () => {
    const user = userEvent.setup();
    renderPanel();
    await saveFlow(user);

    expect(mocked.saveAssistantConfiguration).toHaveBeenCalledTimes(1);
    expect(mocked.saveAssistantConfiguration.mock.calls[0][0]).toMatchObject({
      revision: status.revision,
    });
    expect(mocked.saveAssistantConfiguration.mock.calls[0][0]).not.toHaveProperty("unknown_ack");
  });

  it("shows a busy state and prevents double execution during the combined probe", async () => {
    const user = userEvent.setup();
    let resolveText!: (result: AssistantProbeResult) => void;
    mocked.runAssistantTextProbe.mockImplementation(
      () => new Promise<AssistantProbeResult>((resolve) => {
        resolveText = resolve;
      }),
    );
    renderPanel();
    await walkToProbes(user);

    await user.click(screen.getByRole("button", { name: "Probar texto + visión" }));
    const busyButton = await screen.findByRole("button", { name: "Probando texto…" });
    expect(busyButton).toBeDisabled();
    // A forced click on the disabled button must not start a second run.
    fireEvent.click(busyButton);
    await act(async () => {
      resolveText({ outcome: "passed", oracle: "text-marker" });
    });
    expect(await screen.findByText("Prueba de visión superada.")).toBeInTheDocument();
    expect(mocked.runAssistantTextProbe).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("button", { name: "Probar texto + visión" })).toBeEnabled();
  });

  it("announces probe results and the skipped-vision reason via aria-live", async () => {
    const user = userEvent.setup();
    renderPanel();
    await walkToProbes(user);

    await user.click(screen.getByRole("button", { name: "Probar texto + visión" }));
    expect(await screen.findByText("Prueba de visión superada.")).toBeInTheDocument();
    expect(screen.getByText("Prueba de texto superada.")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText("Prueba de visión superada.")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByLabelText("Pasos de configuración")).toBeInTheDocument();

    mocked.runAssistantTextProbe.mockResolvedValue({
      outcome: "not_causal",
      oracle: "text-marker",
      message: "La prueba de texto no pasó.",
    });
    await user.click(screen.getByRole("button", { name: "Probar texto + visión" }));
    expect(await screen.findByText("La visión no se ejecutó porque la prueba de texto no pasó.")).toHaveAttribute(
      "aria-live",
      "polite",
    );
  });

  it.each([
    ["active", "Activo"],
    ["pending-reload", "Guardado, pendiente de recarga"],
    ["saved-not-active", "Guardado, no activo"],
  ] as const)("shows runtime state %s", async (runtime_state, label) => {
    mocked.getAssistantSettings.mockResolvedValue({ ...status, runtime_state });
    renderPanel();
    expect(await screen.findByText(label)).toBeInTheDocument();
  });

  it("clears the configured key through the authenticated endpoint", async () => {
    const user = userEvent.setup();
    renderPanel();
    await screen.findByRole("heading", { name: "Conexión" });
    await user.click(screen.getByRole("button", { name: "Eliminar clave" }));

    expect(mocked.clearAssistantKey).toHaveBeenCalledTimes(1);
  });

  it("shows a persistent success panel with real runtime state after a successful save", async () => {
    const user = userEvent.setup();
    mocked.saveAssistantConfiguration.mockResolvedValue({ ...status, runtime_state: "active" });
    renderPanel();
    await saveFlow(user);

    const success = await screen.findByRole("status");
    expect(within(success).getByText("Configuración guardada")).toBeInTheDocument();
    expect(within(success).getByText("opencode-go")).toBeInTheDocument();
    expect(within(success).getByText("GPT-5.6 Luna")).toBeInTheDocument();
    expect(within(success).getByText("Texto: superada · Visión: superada")).toBeInTheDocument();
    // Real runtime state, not hardcoded success.
    expect(within(success).getByText("Activo")).toBeInTheDocument();
    expect(within(success).getByRole("button", { name: "Volver al Taller de Mundos" })).toBeInTheDocument();
    // The wizard and its progress indicator survive the success.
    expect(screen.getByRole("navigation", { name: "Pasos de configuración" })).toBeInTheDocument();
  });

  it("blocks a second save after the first succeeds (no duplicate requests)", async () => {
    const user = userEvent.setup();
    mocked.saveAssistantConfiguration.mockResolvedValue({ ...status, runtime_state: "active" });
    renderPanel();
    await saveFlow(user);

    expect(await screen.findByText("Configuración guardada")).toBeInTheDocument();
    // The success block replaces the probes body, so the save button is gone.
    expect(screen.queryByRole("button", { name: "Guardar configuración" })).not.toBeInTheDocument();
    expect(mocked.saveAssistantConfiguration).toHaveBeenCalledTimes(1);
  });

  it("shows pending-reload and saved-not-active runtime states with context after save", async () => {
    const user = userEvent.setup();
    mocked.saveAssistantConfiguration.mockResolvedValue({ ...status, runtime_state: "pending-reload" });
    renderPanel();
    await saveFlow(user);
    const success = await screen.findByRole("status");
    expect(within(success).getByText("Guardado, pendiente de recarga")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cambiar configuración" }));
    expect(screen.queryByText("Configuración guardada")).not.toBeInTheDocument();
  });

  it("shows an error and no success state when the save API fails", async () => {
    const user = userEvent.setup();
    mocked.saveAssistantConfiguration.mockRejectedValue(new Error("Servidor caído"));
    renderPanel();
    await saveFlow(user);

    expect(await screen.findByText("Servidor caído")).toBeInTheDocument();
    expect(screen.queryByText("Configuración guardada")).not.toBeInTheDocument();
    // The save button remains available so the user can retry.
    expect(screen.getByRole("button", { name: "Guardar configuración" })).toBeInTheDocument();
  });

  it("clears the confirmation and returns to the Conexión step via Cambiar configuración", async () => {
    const user = userEvent.setup();
    mocked.saveAssistantConfiguration.mockResolvedValue({ ...status, runtime_state: "active" });
    renderPanel();
    await saveFlow(user);
    expect(await screen.findByText("Configuración guardada")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cambiar configuración" }));
    expect(screen.queryByText("Configuración guardada")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Conexión" })).toBeInTheDocument();
    // Confirmation was cleared: the flow must be re-run to save again.
    expect(screen.queryByRole("button", { name: "Guardar configuración" })).not.toBeInTheDocument();
  });
});
