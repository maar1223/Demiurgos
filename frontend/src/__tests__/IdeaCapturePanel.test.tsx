import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Mock } from "vitest";
import {
  authorizeChat,
  clearIdeaCaptureToken,
  discoverChatCandidates,
  getIdeaCaptureStatus,
  saveIdeaCaptureConfig,
  setIdeaCaptureToken,
} from "@/api/ideaCapture";
import {
  IdeaCapturePanel,
  type LocalAuthController,
} from "@/components/organisms/IdeaCapturePanel";
import { ApiError, type IdeaCaptureStatus } from "@/api/types";

vi.mock("@/api/ideaCapture", () => ({
  getIdeaCaptureStatus: vi.fn(),
  saveIdeaCaptureConfig: vi.fn(),
  setIdeaCaptureToken: vi.fn(),
  clearIdeaCaptureToken: vi.fn(),
  discoverChatCandidates: vi.fn(),
  authorizeChat: vi.fn(),
}));

const mocked = {
  getIdeaCaptureStatus: getIdeaCaptureStatus as Mock,
  saveIdeaCaptureConfig: saveIdeaCaptureConfig as Mock,
  setIdeaCaptureToken: setIdeaCaptureToken as Mock,
  clearIdeaCaptureToken: clearIdeaCaptureToken as Mock,
  discoverChatCandidates: discoverChatCandidates as Mock,
  authorizeChat: authorizeChat as Mock,
};

function makeStatus(overrides: Partial<IdeaCaptureStatus> = {}): IdeaCaptureStatus {
  return {
    config: {
      private_chat_ids: [],
      approved_groups: {},
      limits: { image_mb: 20, audio_mb: 50, audio_minutes: 5, raw_retention_days: 30 },
    },
    has_token: false,
    validation: { ok: true, errors: [] },
    serve: {
      command: "PYTHONPATH=src/tools python -m idea_capture serve",
      runnable: false,
      blocked_reasons: ["No hay TELEGRAM_BOT_TOKEN configurado en .env"],
    },
    worlds: ["vibrantes"],
    limitations: ["Limitación de prueba"],
    ...overrides,
  };
}

function makeAuth(overrides: Partial<LocalAuthController> = {}): LocalAuthController {
  return {
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
    ...overrides,
  };
}

function renderPanel(auth: LocalAuthController) {
  return render(<IdeaCapturePanel auth={auth} />);
}

/** Walk the wizard forward `target` steps (clicking Continuar each time).
 *  Only valid when the Continue button is enabled (e.g. token already set). */
async function goToStep(user: ReturnType<typeof userEvent.setup>, target: number) {
  for (let i = 0; i < target; i++) {
    await user.click(await screen.findByRole("button", { name: "Continuar" }));
  }
}

describe("IdeaCapturePanel — wizard navigation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.getIdeaCaptureStatus.mockResolvedValue(makeStatus());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the local-auth gate when the session is not started", async () => {
    const start = vi.fn().mockResolvedValue({});
    const user = userEvent.setup();
    renderPanel(
      makeAuth({
        status: {
          mode: "local-dev",
          enabled: true,
          authenticated: false,
          label: null,
        },
        start,
      }),
    );

    expect(screen.getByText(/Sesión local no iniciada/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Iniciar sesión local" }));
    expect(start).toHaveBeenCalledOnce();
    expect(mocked.getIdeaCaptureStatus).not.toHaveBeenCalled();
  });

  it("explains how to enable local auth when disabled, without fetching", () => {
    renderPanel(
      makeAuth({
        status: {
          mode: "disabled",
          enabled: false,
          authenticated: false,
          label: null,
        },
      }),
    );

    expect(
      screen.getByText(/DEMIURGOS_AUTH_MODE=local-dev/i),
    ).toBeInTheDocument();
    expect(mocked.getIdeaCaptureStatus).not.toHaveBeenCalled();
  });

  it("shows a 4-step progress indicator and only the current step's content", async () => {
    renderPanel(makeAuth());
    // Wait until the status has loaded (step 0 content rendered).
    await screen.findByRole("heading", { name: "Conectá tu bot de Telegram" });

    for (const label of [
      "Conectar bot",
      "Detectar chat",
      "Revisar",
      "Finalizar",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    // Capture never asks for a world: no world step exists at all.
    expect(screen.queryByText("Elegir mundo")).not.toBeInTheDocument();
    // Step 0 content visible; the rest are hidden (only the progress label
    // for later steps exists, never their content).
    expect(
      screen.getByRole("heading", { name: "Conectá tu bot de Telegram" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Detectá el chat que recibirá tus ideas" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Elegí el mundo de captura" }),
    ).not.toBeInTheDocument();
  });

  it("keeps Continuar disabled on the token step until a token is saved", async () => {
    const user = userEvent.setup();
    renderPanel(makeAuth());

    const cont = await screen.findByRole("button", { name: "Continuar" });
    expect(cont).toBeDisabled();
    expect(screen.getByText(/Guardá el token para continuar/i)).toBeInTheDocument();

    await user.type(await screen.findByLabelText("Token del bot"), "123:AA");
    await user.click(screen.getByRole("button", { name: "Guardar token" }));

    expect(
      await screen.findByRole("button", { name: "Continuar" }),
    ).toBeEnabled();
  });

  it("walks forward one step at a time and back with Volver", async () => {
    mocked.getIdeaCaptureStatus.mockResolvedValue(
      makeStatus({ has_token: true }),
    );
    const user = userEvent.setup();
    renderPanel(makeAuth());

    await goToStep(user, 1);
    expect(
      screen.getByRole("heading", { name: "Detectá el chat que recibirá tus ideas" }),
    ).toBeInTheDocument();

    await goToStep(user, 1);
    expect(
      screen.getByRole("heading", { name: "Revisá tu configuración" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Volver" }));
    expect(
      screen.getByRole("heading", { name: "Detectá el chat que recibirá tus ideas" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Volver" }));
    expect(
      screen.getByRole("heading", { name: "Conectá tu bot de Telegram" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Volver" })).toBeDisabled();
  });
});

describe("IdeaCapturePanel — Conectar bot (token)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.getIdeaCaptureStatus.mockResolvedValue(makeStatus());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("masks the token input by default and only reveals while editing", async () => {
    const user = userEvent.setup();
    renderPanel(makeAuth());

    const tokenInput = await screen.findByLabelText("Token del bot");
    expect(tokenInput).toHaveAttribute("type", "password");

    const reveal = screen.getByRole("button", { name: "Mostrar token" });
    const copy = screen.getByRole("button", { name: "Copiar token" });
    // Nothing typed yet → not editing → reveal/copy disabled.
    expect(reveal).toBeDisabled();
    expect(copy).toBeDisabled();

    await user.type(tokenInput, "123:AA");
    expect(reveal).toBeEnabled();

    await user.click(reveal);
    expect(tokenInput).toHaveAttribute("type", "text");
    await user.click(screen.getByRole("button", { name: "Ocultar token" }));
    expect(tokenInput).toHaveAttribute("type", "password");
  });

  it("copies only the value being typed, never a stored value", async () => {
    const user = userEvent.setup();
    // user-event's setup() installs its own clipboard stub, so ours must be
    // defined AFTER setup; we assert on the local reference, not the global.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    renderPanel(makeAuth());

    const tokenInput = await screen.findByLabelText("Token del bot");
    await user.type(tokenInput, "987:BB");
    await user.click(screen.getByRole("button", { name: "Copiar token" }));

    expect(writeText).toHaveBeenCalledWith("987:BB");
    expect(await screen.findByText("Copiado")).toBeInTheDocument();
  });

  it("saves the token, wipes the input, and confirms without echoing the value", async () => {
    mocked.setIdeaCaptureToken.mockResolvedValue({ has_token: true });
    const user = userEvent.setup();
    renderPanel(makeAuth());

    const tokenInput = await screen.findByLabelText("Token del bot");
    await user.type(tokenInput, "123:AA-secret");
    await user.click(screen.getByRole("button", { name: "Guardar token" }));

    expect(mocked.setIdeaCaptureToken).toHaveBeenCalledWith("123:AA-secret");
    expect(await screen.findByText(/Token guardado en .env/i)).toBeInTheDocument();
    expect(tokenInput).toHaveValue("");
    // Regression: the secret never leaks into the rendered DOM.
    expect(screen.queryByText("123:AA-secret")).not.toBeInTheDocument();
  });

  it("replaces and clears an existing token with a two-step confirmation", async () => {
    mocked.clearIdeaCaptureToken.mockResolvedValue({ has_token: false });
    mocked.getIdeaCaptureStatus.mockResolvedValue(
      makeStatus({ has_token: true }),
    );
    const user = userEvent.setup();
    renderPanel(makeAuth());

    expect(
      await screen.findByText(/Configurado en .env/i, { selector: "p" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reemplazar token" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Eliminar token" }));
    await user.click(
      screen.getByRole("button", { name: "¿Confirmar eliminación?" }),
    );

    expect(mocked.clearIdeaCaptureToken).toHaveBeenCalledOnce();
    expect(await screen.findByText(/Token eliminado de .env/i)).toBeInTheDocument();
  });
});

describe("IdeaCapturePanel — Detectar chat", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.getIdeaCaptureStatus.mockResolvedValue(
      makeStatus({ has_token: true }),
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("only offers discovery once a token is configured", async () => {
    const { unmount } = renderPanel(makeAuth());
    // Step 0 with no token → the detect button (step 1) is unreachable.
    expect(
      screen.queryByRole("button", { name: "Ya lo envié — Detectar chat" }),
    ).not.toBeInTheDocument();
    unmount();

    mocked.getIdeaCaptureStatus.mockResolvedValue(makeStatus({ has_token: true }));
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 1);
    expect(
      screen.getByRole("button", { name: "Ya lo envié — Detectar chat" }),
    ).toBeInTheDocument();
  });

  it("gives a clear /start instruction and warns fail-closed without chats", async () => {
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 1);

    expect(screen.getByText(/\/start/)).toBeInTheDocument();
    expect(screen.getByText(/se rechaza TODO el ingreso/i)).toBeInTheDocument();
  });

  it("runs the discover flow and lists private and group candidates", async () => {
    mocked.discoverChatCandidates.mockResolvedValue({
      ok: true,
      message: "",
      candidates: [
        { id: 111, type: "private", kind: "private", title: "Ana Perez" },
        { id: -100, type: "group", kind: "group", title: "Equipo Narrativo" },
      ],
    });
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 1);

    await user.click(
      screen.getByRole("button", { name: "Ya lo envié — Detectar chat" }),
    );

    expect(mocked.discoverChatCandidates).toHaveBeenCalledOnce();
    expect(await screen.findByText("Ana Perez")).toBeInTheDocument();
    expect(screen.getByText("Equipo Narrativo")).toBeInTheDocument();
    // The numeric id stays an internal selection value: not rendered as text.
    expect(screen.queryByText("111")).not.toBeInTheDocument();
    expect(screen.queryByText("-100")).not.toBeInTheDocument();
  });

  it("selects and authorizes a private chat in one click, then confirms", async () => {
    mocked.discoverChatCandidates.mockResolvedValue({
      ok: true,
      message: "",
      candidates: [
        { id: 111, type: "private", kind: "private", title: "Ana Perez" },
      ],
    });
    mocked.authorizeChat.mockResolvedValue({
      ...makeStatus({ has_token: true, config: { ...makeStatus().config, private_chat_ids: [111] } }),
      message: "Chat privado autorizado.",
    });
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 1);

    await user.click(
      screen.getByRole("button", { name: "Ya lo envié — Detectar chat" }),
    );
    await user.click(await screen.findByRole("button", { name: "Autorizar" }));

    expect(mocked.authorizeChat).toHaveBeenCalledWith({
      chat_id: 111,
      chat_type: "private",
    });
    // Friendly confirmation comes straight from the backend response.
    expect(
      await screen.findByText("Chat privado autorizado."),
    ).toBeInTheDocument();
    // The fail-closed warning is replaced by the active authorization state.
    expect(
      screen.getByText(/Autorización activa: 1 chat/),
    ).toBeInTheDocument();
  });

  it("group authorization is explicit and fail-closed: confirm + senders required", async () => {
    mocked.discoverChatCandidates.mockResolvedValue({
      ok: true,
      message: "",
      candidates: [
        { id: -100, type: "group", kind: "group", title: "Equipo Narrativo" },
      ],
    });
    mocked.authorizeChat.mockResolvedValue({
      ...makeStatus({
        has_token: true,
        config: { ...makeStatus().config, approved_groups: { "-100": [5, 6] } },
      }),
      message: "Grupo autorizado con remitentes explícitos.",
    });
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 1);

    await user.click(
      screen.getByRole("button", { name: "Ya lo envié — Detectar chat" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Autorizar grupo" }),
    );

    // Nothing typed, nothing confirmed -> client-side fail-closed, no API call.
    expect(
      screen.getByText("Ingresá al menos un ID de remitente entero para el grupo."),
    ).toBeInTheDocument();
    expect(mocked.authorizeChat).not.toHaveBeenCalled();

    await user.type(
      screen.getByLabelText("Remitentes del grupo -100"),
      "5, 6",
    );
    await user.click(
      screen.getByRole("button", { name: "Autorizar grupo" }),
    );

    // Senders present but no explicit confirmation -> still refused.
    expect(
      screen.getByText(
        "Confirmá explícitamente que autorizás solo a los remitentes listados.",
      ),
    ).toBeInTheDocument();
    expect(mocked.authorizeChat).not.toHaveBeenCalled();

    await user.click(
      screen.getByLabelText("Confirmar autorización del grupo -100"),
    );
    await user.click(
      screen.getByRole("button", { name: "Autorizar grupo" }),
    );

    expect(mocked.authorizeChat).toHaveBeenCalledWith({
      chat_id: -100,
      chat_type: "group",
      sender_ids: [5, 6],
      confirm_group: true,
    });
    expect(
      await screen.findByText("Grupo autorizado con remitentes explícitos."),
    ).toBeInTheDocument();
  });

  it("shows the friendly empty state when there are no updates yet", async () => {
    mocked.discoverChatCandidates.mockResolvedValue({
      ok: true,
      candidates: [],
      message: "Todavía no hay mensajes de este bot. Enviá /start.",
    });
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 1);

    await user.click(
      screen.getByRole("button", { name: "Ya lo envié — Detectar chat" }),
    );

    expect(
      await screen.findByText(/Todavía no hay mensajes de este bot/),
    ).toBeInTheDocument();
  });

  it("shows a friendly error when discovery fails (e.g. serve owner active)", async () => {
    mocked.discoverChatCandidates.mockRejectedValue(
      new Error(
        "El serve de captura ya está activo y es el único consumidor del bot.",
      ),
    );
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 1);

    await user.click(
      screen.getByRole("button", { name: "Ya lo envié — Detectar chat" }),
    );

    expect(
      await screen.findByText(/El serve de captura ya está activo/),
    ).toBeInTheDocument();
  });

  it("renders webhook-conflict remediation without ever deleting the webhook", async () => {
    mocked.discoverChatCandidates.mockRejectedValue(
      new ApiError(
        409,
        "El bot tiene un webhook activo: Telegram no permite usar getUpdates mientras haya un webhook configurado.",
        undefined,
        "webhook_conflict",
      ),
    );
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 1);

    await user.click(
      screen.getByRole("button", { name: "Ya lo envié — Detectar chat" }),
    );

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByText(/Webhook activo: Telegram no permite usar getUpdates/i),
    ).toBeInTheDocument();
    // The remediation must instruct a MANUAL deleteWebhook — the panel never
    // deletes it automatically.
    expect(screen.getByText(/\/deletewebhook/)).toBeInTheDocument();
    expect(screen.getByText(/deleteWebhook/)).toBeInTheDocument();
    expect(
      screen.getByText(/nunca borra el webhook automáticamente/i),
    ).toBeInTheDocument();
  });

  it("renders safe remediation for an invalid token", async () => {
    mocked.discoverChatCandidates.mockRejectedValue(
      new ApiError(
        400,
        "El token guardado no es válido o fue revocado. Guardá un token nuevo desde este panel.",
        undefined,
        "invalid_token",
      ),
    );
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 1);

    await user.click(
      screen.getByRole("button", { name: "Ya lo envié — Detectar chat" }),
    );

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByText(/El token guardado no es válido o fue revocado/i),
    ).toBeInTheDocument();
  });

  it("renders safe remediation for a network failure without crashing", async () => {
    mocked.discoverChatCandidates.mockRejectedValue(
      new ApiError(
        502,
        "No se pudo contactar la API de Telegram. Verificá la conexión e intentá de nuevo.",
        undefined,
        "network",
      ),
    );
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 1);

    await user.click(
      screen.getByRole("button", { name: "Ya lo envié — Detectar chat" }),
    );

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByText(/No se pudo contactar la API de Telegram/i),
    ).toBeInTheDocument();
  });

  it("keeps the generic red error for ApiError without a remediation code", async () => {
    mocked.discoverChatCandidates.mockRejectedValue(
      new ApiError(500, "Internal Server Error", "Internal Server Error"),
    );
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 1);

    await user.click(
      screen.getByRole("button", { name: "Ya lo envié — Detectar chat" }),
    );

    expect(await screen.findByText(/Internal Server Error/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("IdeaCapturePanel — sin elegir mundo (Taller de Ideas)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("never shows a world selector anywhere in the wizard", async () => {
    mocked.getIdeaCaptureStatus.mockResolvedValue(makeStatus({ has_token: true }));
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 2);

    expect(
      screen.getByRole("heading", { name: "Revisá tu configuración" }),
    ).toBeInTheDocument();
    // No world select, no world label, no world step content.
    expect(screen.queryByLabelText("Mundo activo")).not.toBeInTheDocument();
    expect(screen.queryByText("— sin mundo —")).not.toBeInTheDocument();
    expect(screen.queryByText(/Sin mundo activo/i)).not.toBeInTheDocument();
  });

  it("reaches Finalizar without any world state — capture needs no world", async () => {
    mocked.getIdeaCaptureStatus.mockResolvedValue(makeStatus({ has_token: true }));
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 3);

    expect(
      screen.getByRole("heading", { name: "Finalizá y arrancá la captura" }),
    ).toBeInTheDocument();
    // The destination copy names the Taller de Ideas, not a world.
    expect(screen.getByText(/Taller de Ideas/)).toBeInTheDocument();
  });

  it("shows the Taller de Ideas as the capture destination in Revisar", async () => {
    mocked.getIdeaCaptureStatus.mockResolvedValue(makeStatus({ has_token: true }));
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 2);

    // Destination row + explanatory note both name the Taller de Ideas.
    expect(screen.getAllByText("Taller de Ideas").length).toBeGreaterThan(0);
    expect(
      screen.getByText(/no elegís mundo al capturar/i),
    ).toBeInTheDocument();
  });
});

describe("IdeaCapturePanel — Revisar y configuración avanzada", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("summarizes bot, chat and destination before finishing", async () => {
    const base = makeStatus({ has_token: true });
    base.config.private_chat_ids = [111];
    mocked.getIdeaCaptureStatus.mockResolvedValue(base);
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 2);

    expect(
      screen.getByRole("heading", { name: "Revisá tu configuración" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Token configurado")).toBeInTheDocument();
    expect(screen.getByText("1 chat(s)")).toBeInTheDocument();
    // Destination row + explanatory note both name the Taller de Ideas.
    expect(screen.getAllByText("Taller de Ideas").length).toBeGreaterThan(0);
  });

  it("flags fail-closed in review when no chat is authorized", async () => {
    mocked.getIdeaCaptureStatus.mockResolvedValue(makeStatus({ has_token: true }));
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 2);

    expect(screen.getByText("Ninguno (fail-closed)")).toBeInTheDocument();
    expect(screen.getAllByText(/se rechaza TODO el ingreso/i).length).toBeGreaterThan(0);
  });

  it("keeps the advanced settings collapsed by default and discloses them on demand", async () => {
    mocked.getIdeaCaptureStatus.mockResolvedValue(makeStatus({ has_token: true }));
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 2);

    const summary = screen.getByText("Configuración avanzada (opcional)");
    expect(summary).toBeInTheDocument();
    expect(screen.queryByLabelText("Chats privados autorizados")).not.toBeInTheDocument();

    await user.click(summary);
    expect(
      await screen.findByLabelText("Chats privados autorizados"),
    ).toBeInTheDocument();
  });

  it("edits manual IDs and media limits in the advanced disclosure", async () => {
    mocked.getIdeaCaptureStatus.mockResolvedValue(makeStatus({ has_token: true }));
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 2);

    await user.click(screen.getByText("Configuración avanzada (opcional)"));

    const privateInput = await screen.findByLabelText("Chats privados autorizados");
    await user.type(privateInput, "111, 222");
    expect(privateInput).toHaveValue("111, 222");

    await user.click(screen.getByRole("button", { name: /Agregar grupo/ }));
    await user.type(await screen.findByLabelText("ID del grupo 1"), "-100");
    await user.type(screen.getByLabelText("Remitentes del grupo 1"), "5");

    const imageLimit = screen.getByLabelText("Límite imagen (MB)");
    await user.clear(imageLimit);
    await user.type(imageLimit, "40");
    expect(imageLimit).toHaveValue(40);
  });

  it("shows server validation errors when present", async () => {
    mocked.getIdeaCaptureStatus.mockResolvedValue(
      makeStatus({
        has_token: true,
        validation: {
          ok: false,
          errors: ["limits.image_mb: debe ser un entero positivo"],
        },
      }),
    );
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 2);

    expect(
      screen.getByText(/limits\.image_mb: debe ser un entero positivo/),
    ).toBeInTheDocument();
  });
});

describe("IdeaCapturePanel — Finalizar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("saves the assembled config and shows the exact Hermes command", async () => {
    const base = makeStatus({ has_token: true });
    base.config.private_chat_ids = [111];
    base.serve = {
      command: "powershell -ExecutionPolicy Bypass -File start-gateway.ps1",
      runnable: true,
      blocked_reasons: [],
    };
    mocked.getIdeaCaptureStatus.mockResolvedValue(base);
    mocked.saveIdeaCaptureConfig.mockResolvedValue(base);
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 3);

    await user.click(screen.getByRole("button", { name: "Guardar configuración" }));

    // The saved config never carries a world: capture goes to the Taller de
    // Ideas automatically.
    expect(mocked.saveIdeaCaptureConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        private_chat_ids: [111],
        approved_groups: {},
      }),
    );
    expect(
      (mocked.saveIdeaCaptureConfig.mock.calls[0][0] as { active_world?: string })
        .active_world,
    ).toBeUndefined();
    expect(await screen.findByText("Configuración guardada.")).toBeInTheDocument();
    expect(screen.getByText(/start-gateway\.ps1/)).toBeInTheDocument();
    expect(screen.getByText(/Listo para ejecutar Hermes/)).toBeInTheDocument();
  });

  it("never auto-starts Telegram and shows the next manual action", async () => {
    mocked.getIdeaCaptureStatus.mockResolvedValue(makeStatus({ has_token: true }));
    mocked.saveIdeaCaptureConfig.mockResolvedValue(makeStatus({ has_token: true }));
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 3);

    await user.click(screen.getByRole("button", { name: "Guardar configuración" }));

    expect(
      await screen.findByText(/no inicia Telegram automáticamente/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/ejecutá el comando en tu terminal/i)).toBeInTheDocument();
  });

  it("shows the fail-closed blocked reasons after saving when serve cannot run", async () => {
    const base = makeStatus({ has_token: true });
    base.serve = {
      command: "PYTHONPATH=src/tools python -m idea_capture serve",
      runnable: false,
      blocked_reasons: [
        "Las listas de autorización están vacías (fail-closed): se rechaza todo ingreso",
      ],
    };
    mocked.getIdeaCaptureStatus.mockResolvedValue(base);
    mocked.saveIdeaCaptureConfig.mockResolvedValue(base);
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 3);

    await user.click(screen.getByRole("button", { name: "Guardar configuración" }));

    expect(
      await screen.findByText(/Las listas de autorización están vacías \(fail-closed\)/),
    ).toBeInTheDocument();
    // A missing world is no longer a blocking reason: capture goes to the
    // Taller de Ideas without a world.
    expect(
      screen.queryByText(/No hay un mundo activo configurado/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Listo para ejecutar el serve/),
    ).not.toBeInTheDocument();
  });

  it("shows the current limitations when finishing", async () => {
    mocked.getIdeaCaptureStatus.mockResolvedValue(makeStatus({ has_token: true }));
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 3);

    expect(screen.getByText("Limitaciones actuales")).toBeInTheDocument();
    expect(screen.getByText("Limitación de prueba")).toBeInTheDocument();
  });

  it("rejects invalid manual ids client-side without calling the API", async () => {
    const base = makeStatus({ has_token: true });
    base.config.private_chat_ids = [111];
    mocked.getIdeaCaptureStatus.mockResolvedValue(base);
    const user = userEvent.setup();
    renderPanel(makeAuth());
    await goToStep(user, 3);

    // Break the private ids through the advanced disclosure on the review step.
    await user.click(screen.getByRole("button", { name: "Volver" }));
    await user.click(screen.getByText("Configuración avanzada (opcional)"));
    const privateInput = await screen.findByLabelText("Chats privados autorizados");
    await user.clear(privateInput);
    await user.type(privateInput, "abc");
    await user.click(screen.getByRole("button", { name: "Continuar" }));
    await user.click(screen.getByRole("button", { name: "Guardar configuración" }));

    expect(
      screen.getByText("IDs privados: enteros separados por coma", {
        selector: "p",
      }),
    ).toBeInTheDocument();
    expect(mocked.saveIdeaCaptureConfig).not.toHaveBeenCalled();
  });
});
