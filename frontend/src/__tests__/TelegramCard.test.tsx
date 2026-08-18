import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Mock } from "vitest";
import {
  clearTelegramToken,
  getTelegramStatus,
  setTelegramToken,
  testTelegramConnection,
} from "@/api/telegram";
import { TelegramCard } from "@/components/organisms/TelegramCard";
import type { TelegramStatus } from "@/api/types";

vi.mock("@/api/telegram", () => ({
  clearTelegramToken: vi.fn(),
  getTelegramStatus: vi.fn(),
  setTelegramToken: vi.fn(),
  testTelegramConnection: vi.fn(),
}));

vi.mock("@/hooks/useLocalDevAuth", () => ({
  useLocalDevAuth: vi.fn(),
}));

import { useLocalDevAuth } from "@/hooks/useLocalDevAuth";

const mocked = {
  clearTelegramToken: clearTelegramToken as Mock,
  getTelegramStatus: getTelegramStatus as Mock,
  setTelegramToken: setTelegramToken as Mock,
  testTelegramConnection: testTelegramConnection as Mock,
};

const authenticatedAuth = () => ({
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
});

const pending: TelegramStatus = {
  state: "pending",
  has_token: false,
  tested_at: null,
  error_code: "",
};

const requiresConnection: TelegramStatus = {
  state: "requires_connection",
  has_token: true,
  tested_at: null,
  error_code: "",
};

const configured: TelegramStatus = {
  state: "configured",
  has_token: true,
  tested_at: "2026-08-18T00:00:00Z",
  error_code: "",
};

const errored: TelegramStatus = {
  state: "error",
  has_token: true,
  tested_at: "2026-08-18T00:00:00Z",
  error_code: "invalid_token",
};

describe("TelegramCard (ONB-3.3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (useLocalDevAuth as Mock).mockReturnValue(authenticatedAuth());
  });

  it("renders pending with a write-only token input and no stored token text", async () => {
    mocked.getTelegramStatus.mockResolvedValue(pending);
    render(<TelegramCard />);

    expect(
      await screen.findByRole("heading", { name: "Conexión del bot" }),
    ).toBeInTheDocument();
    const input = screen.getByLabelText("Token del bot (write-only)");
    expect(input).toHaveAttribute("type", "password");
    // The stored value is never displayed: only the input exists, empty.
    expect(document.body.textContent).not.toContain("123456789:AA");
    expect(screen.getByRole("button", { name: /Guardar token/ })).toBeInTheDocument();
  });

  it("saves the token write-only: sent to the backend, input cleared, never rendered", async () => {
    mocked.getTelegramStatus.mockResolvedValue(pending);
    mocked.setTelegramToken.mockResolvedValue(requiresConnection);
    const user = userEvent.setup();
    render(<TelegramCard />);

    const input = await screen.findByLabelText("Token del bot (write-only)");
    await user.type(input, "123456789:AA-secret-token");
    await user.click(screen.getByRole("button", { name: /Guardar token/ }));

    expect(mocked.setTelegramToken).toHaveBeenCalledWith("123456789:AA-secret-token");
    // Input cleared after save; the secret never appears anywhere in the DOM.
    expect(input).toHaveValue("");
    expect(document.body.textContent).not.toContain("123456789:AA-secret-token");
    expect(await screen.findByRole("button", { name: /Probar conexión/ })).toBeInTheDocument();
  });

  it("test connection success moves the card to configured with a live announcement", async () => {
    mocked.getTelegramStatus.mockResolvedValue(requiresConnection);
    mocked.testTelegramConnection.mockResolvedValue({
      ...configured,
      message: "Conexión verificada con Telegram.",
    });
    const user = userEvent.setup();
    render(<TelegramCard />);

    await user.click(await screen.findByRole("button", { name: /Probar conexión/ }));
    expect(await screen.findByText("Conexión verificada con Telegram.")).toBeInTheDocument();
    expect(screen.getByText("Configurado")).toBeInTheDocument();
  });

  it("offline/network failure honestly maps to requires_connection", async () => {
    mocked.getTelegramStatus.mockResolvedValue(requiresConnection);
    mocked.testTelegramConnection.mockResolvedValue({
      ...requiresConnection,
      message: "No se pudo contactar la API de Telegram. Verificá la conexión e intentá de nuevo.",
    });
    const user = userEvent.setup();
    render(<TelegramCard />);

    await user.click(await screen.findByRole("button", { name: /Probar conexión/ }));
    expect(await screen.findByText(/No se pudo contactar la API de Telegram/)).toBeInTheDocument();
    expect(screen.getByText("Requiere conexión")).toBeInTheDocument();
  });

  it("invalid token surfaces the error state with remediation guidance", async () => {
    mocked.getTelegramStatus.mockResolvedValue(errored);
    render(<TelegramCard />);

    expect(await screen.findByText("Error")).toBeInTheDocument();
    expect(screen.getByText(/El token guardado no es válido/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Probar conexión/ })).toBeInTheDocument();
  });

  it("clears the token only after explicit confirmation, then returns to pending", async () => {
    mocked.getTelegramStatus.mockResolvedValue(requiresConnection);
    mocked.clearTelegramToken.mockResolvedValue(pending);
    const user = userEvent.setup();
    render(<TelegramCard />);

    const clearButton = await screen.findByRole("button", { name: /Eliminar token/ });
    await user.click(clearButton);
    expect(mocked.clearTelegramToken).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /Confirmar eliminación/ }));
    expect(mocked.clearTelegramToken).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Pendiente")).toBeInTheDocument();
  });

  it("fails closed without the local session and offers to start it", async () => {
    (useLocalDevAuth as Mock).mockReturnValue({
      ...authenticatedAuth(),
      status: {
        mode: "local-dev",
        enabled: true,
        authenticated: false,
        label: null,
      },
    });
    render(<TelegramCard />);

    expect(
      await screen.findByText(/Iniciá la sesión local para configurar Telegram/),
    ).toBeInTheDocument();
    expect(mocked.getTelegramStatus).not.toHaveBeenCalled();
  });
});