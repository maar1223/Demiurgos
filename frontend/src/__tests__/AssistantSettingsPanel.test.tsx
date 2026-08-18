import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
import type { LocalAuthController } from "@/components/organisms/IdeaCapturePanel";

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

const auth: LocalAuthController = {
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

/** Walk the happy path up to the single capability step with a discovered model. */
const walkToCapability = async (user: ReturnType<typeof userEvent.setup>) => {
  await screen.findByRole("heading", { name: "Proveedor" });
  await user.click(screen.getByRole("button", { name: "Conexión" }));
  await user.click(screen.getByRole("button", { name: "Validar conexión" }));
  expect(await screen.findByText("Conexión validada.")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Modelos" }));
  await user.click(screen.getByRole("button", { name: "Descubrir modelos" }));
  await screen.findByRole("combobox", { name: "Modelo descubierto" });
  await user.click(screen.getByRole("button", { name: "Capacidad" }));
  expect(screen.getByRole("heading", { name: "Capacidad" })).toBeInTheDocument();
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

  it("renders exactly five revisitable steps", async () => {
    render(<AssistantSettingsPanel auth={auth} />);

    expect(await screen.findByRole("heading", { name: "Proveedor" })).toBeInTheDocument();
    for (const label of ["Proveedor", "Conexión", "Modelos", "Capacidad", "Confirmación"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    await userEvent.click(screen.getByRole("button", { name: "Conexión" }));
    expect(screen.getByRole("heading", { name: "Conexión" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Proveedor" }));
    expect(screen.getByRole("heading", { name: "Proveedor" })).toBeInTheDocument();
  });

  it("preserves the connection payload when navigating from Connection to Models", async () => {
    const user = userEvent.setup();
    const expectedPayload = {
      provider: "opencode-go",
      base_url: "https://opaque.example/v1",
      api_key: "opaque-test-key",
    };
    render(<AssistantSettingsPanel auth={auth} />);
    await screen.findByRole("heading", { name: "Proveedor" });
    await user.click(screen.getByRole("button", { name: "Conexión" }));
    await user.click(screen.getByRole("button", { name: "Modelos" }));
    expect(screen.queryByRole("button", { name: "Descubrir modelos" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Conexión" }));
    await user.clear(screen.getByLabelText("Endpoint"));
    await user.type(screen.getByLabelText("Endpoint"), expectedPayload.base_url);
    await user.type(screen.getByLabelText("Clave API"), expectedPayload.api_key);
    await user.click(screen.getByRole("button", { name: "Validar conexión" }));
    expect(mocked.validateAssistantConnection).toHaveBeenLastCalledWith(expectedPayload);
    await user.click(screen.getByRole("button", { name: "Modelos" }));
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
    render(<AssistantSettingsPanel auth={auth} />);
    await screen.findByRole("heading", { name: "Proveedor" });

    await user.selectOptions(screen.getByLabelText("Elegí un proveedor"), "opencode-go");
    await user.click(screen.getByRole("button", { name: "Conexión" }));

    expect(screen.getByLabelText("Endpoint")).toHaveValue("https://opencode.ai/zen/go/v1");
  });

  it("requires revalidation when the API key changes", async () => {
    const user = userEvent.setup();
    render(<AssistantSettingsPanel auth={auth} />);
    await screen.findByRole("heading", { name: "Proveedor" });
    await user.click(screen.getByRole("button", { name: "Conexión" }));
    await user.click(screen.getByRole("button", { name: "Validar conexión" }));

    expect(await screen.findByText("Conexión validada.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeEnabled();

    await user.type(screen.getByLabelText("Clave API"), "opaque-key-placeholder");

    expect(screen.queryByText("Conexión validada.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();
  });

  it("offers manual fallback and requires both probes before confirmation", async () => {
    const user = userEvent.setup();
    mocked.discoverAssistantModels.mockResolvedValue({
      outcome: "failed",
      category: "empty-discovery",
      provider: "opencode-go",
      message: "No usable models were returned",
      models: [],
    });
    render(<AssistantSettingsPanel auth={auth} />);
    await screen.findByRole("heading", { name: "Proveedor" });
    await user.click(screen.getByRole("button", { name: "Conexión" }));
    await user.click(screen.getByRole("button", { name: "Validar conexión" }));
    expect(await screen.findByText("Conexión validada.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Modelos" }));
    await user.click(screen.getByRole("button", { name: "Descubrir modelos" }));
    expect(screen.getByText(/No usable models/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("ID de modelo manual"), "manual-model");
    await user.click(screen.getByRole("button", { name: "Usar modelo manual" }));
    await user.click(screen.getByRole("button", { name: "Capacidad" }));
    expect(screen.getByRole("heading", { name: "Capacidad" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirmación" }));
    expect(screen.getByText(/pruebas de texto y visión/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Probar texto + visión" }));
    expect(await screen.findByText("Prueba de texto superada.")).toBeInTheDocument();
    expect(await screen.findByText("Prueba de visión superada.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirmación" }));
    expect(screen.getByRole("heading", { name: "Confirmación" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guardar configuración" })).toBeEnabled();
  });

  it("runs the text probe before the vision probe in the combined step", async () => {
    const user = userEvent.setup();
    render(<AssistantSettingsPanel auth={auth} />);
    await walkToCapability(user);

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

  it("skips vision and blocks confirmation when the text probe fails", async () => {
    const user = userEvent.setup();
    mocked.runAssistantTextProbe.mockResolvedValue({
      outcome: "not_causal",
      oracle: "text-marker",
      message: "La prueba de texto no pasó.",
    });
    render(<AssistantSettingsPanel auth={auth} />);
    await walkToCapability(user);

    await user.click(screen.getByRole("button", { name: "Probar texto + visión" }));
    expect(await screen.findByText("La prueba de texto no pasó.")).toBeInTheDocument();
    expect(screen.getByText("La visión no se ejecutó porque la prueba de texto no pasó.")).toBeInTheDocument();
    expect(mocked.runAssistantVisionProbe).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Confirmación" }));
    expect(screen.getByText(/pruebas de texto y visión/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Guardar configuración" })).not.toBeInTheDocument();
  });

  it("keeps the text result and shows the vision error when vision fails", async () => {
    const user = userEvent.setup();
    mocked.runAssistantVisionProbe.mockResolvedValue({
      outcome: "not_causal",
      oracle: "causal-vision",
      message: "La prueba de visión no pasó.",
    });
    render(<AssistantSettingsPanel auth={auth} />);
    await walkToCapability(user);

    await user.click(screen.getByRole("button", { name: "Probar texto + visión" }));
    expect(await screen.findByText("La prueba de visión no pasó.")).toBeInTheDocument();
    // The separate text evidence stays visible even though vision failed.
    expect(screen.getByText("Prueba de texto superada.")).toBeInTheDocument();
    expect(screen.queryByText("La visión no se ejecutó porque la prueba de texto no pasó.")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Confirmación" }));
    expect(screen.getByText(/pruebas de texto y visión/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Guardar configuración" })).not.toBeInTheDocument();
  });

  it("walks provider → connection → models → capability → confirmation and saves without unknown_ack", async () => {
    const user = userEvent.setup();
    render(<AssistantSettingsPanel auth={auth} />);
    await walkToCapability(user);

    await user.click(screen.getByRole("button", { name: "Probar texto + visión" }));
    expect(await screen.findByText("Prueba de visión superada.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirmación" }));
    expect(screen.getByRole("heading", { name: "Confirmación" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Guardar configuración" }));
    expect(mocked.saveAssistantConfiguration).toHaveBeenCalledTimes(1);
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
    render(<AssistantSettingsPanel auth={auth} />);
    await walkToCapability(user);

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
    render(<AssistantSettingsPanel auth={auth} />);
    await walkToCapability(user);

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
    ["pending-reload", "Pendiente de reinicio\/recarga"],
    ["saved-not-active", "Guardado, no activo"],
  ] as const)("shows runtime state %s", async (runtime_state, label) => {
    mocked.getAssistantSettings.mockResolvedValue({ ...status, runtime_state });
    render(<AssistantSettingsPanel auth={auth} />);
    expect(await screen.findByText(label)).toBeInTheDocument();
  });

  it("clears the configured key through the authenticated endpoint", async () => {
    const user = userEvent.setup();
    render(<AssistantSettingsPanel auth={auth} />);
    await screen.findByRole("heading", { name: "Proveedor" });
    await user.click(screen.getByRole("button", { name: "Conexión" }));
    await user.click(screen.getByRole("button", { name: "Eliminar clave" }));

    expect(mocked.clearAssistantKey).toHaveBeenCalledTimes(1);
  });
});