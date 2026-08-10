import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Mock } from "vitest";
import {
  clearAssistantKey,
  discoverAssistantModels,
  getAssistantSettings,
  saveAssistantConfiguration,
  validateAssistantConnection,
} from "@/api/assistantSettings";
import { AssistantSettingsPanel } from "@/components/organisms/AssistantSettingsPanel";
import type { AssistantModelOption, AssistantSettingsStatus } from "@/api/types";
import type { LocalAuthController } from "@/components/organisms/IdeaCapturePanel";

vi.mock("@/api/assistantSettings", () => ({
  clearAssistantKey: vi.fn(),
  discoverAssistantModels: vi.fn(),
  getAssistantSettings: vi.fn(),
  saveAssistantConfiguration: vi.fn(),
  validateAssistantConnection: vi.fn(),
}));

const mocked = {
  clearAssistantKey: clearAssistantKey as Mock,
  discoverAssistantModels: discoverAssistantModels as Mock,
  getAssistantSettings: getAssistantSettings as Mock,
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
    mocked.saveAssistantConfiguration.mockResolvedValue(status);
    mocked.clearAssistantKey.mockResolvedValue({ ...status, key_configured: false });
  });

  it("renders exactly four revisitable steps", async () => {
    render(<AssistantSettingsPanel auth={auth} />);

    expect(await screen.findByRole("heading", { name: "Proveedor" })).toBeInTheDocument();
    for (const label of ["Proveedor", "Conexión", "Modelos", "Confirmación"]) {
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

  it("offers manual fallback, unavailable pricing, and requires unknown capability acknowledgement", async () => {
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
    await user.click(screen.getByRole("button", { name: "Modelos" }));
    await user.click(screen.getByRole("button", { name: "Descubrir modelos" }));
    expect(screen.getByText(/No usable models/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("ID de modelo manual"), "manual-model");
    await user.click(screen.getByRole("button", { name: "Usar modelo manual" }));
    expect(screen.getByText(/Precio no disponible/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirmación" }));
    expect(screen.getByRole("checkbox", { name: /acepto/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guardar configuración" })).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /acepto/i }));
    expect(screen.getByRole("button", { name: "Guardar configuración" })).toBeEnabled();
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
