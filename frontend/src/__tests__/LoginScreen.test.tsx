import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import LoginScreen from "@/pages/LoginScreen";
import { reloadPage } from "@/lib/reloadPage";
import { tEs } from "@/__tests__/i18nTestUtils";

/**
 * jsdom's Location.reload is an own non-configurable property that cannot be
 * spied on or replaced. The app routes reloads through `reloadPage()` so this
 * suite stubs that seam instead.
 */
vi.mock("@/lib/reloadPage", () => ({
  reloadPage: vi.fn(),
}));

const unauthenticatedCredentials = {
  mode: "credentials",
  enabled: true,
  authenticated: false,
  label: "el-autor",
  provider: "credentials",
  // Default fixture: the account has a password (S-AC-02a).
  has_password: true,
};

function authenticatedCredentials(
  daysUntilReauth: number | null,
  lastAuthAt?: string,
) {
  return {
    mode: "credentials",
    enabled: true,
    authenticated: true,
    label: "el-autor",
    provider: "credentials",
    last_auth_at: lastAuthAt ?? new Date().toISOString(),
    days_until_reauth: daysUntilReauth,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
    headers: new Headers(),
  };
}

/** Route-based fetch mock for the credentials endpoints used by the flow. */
function mockCredentialsRoutes(overrides: Record<string, unknown> = {}) {
  const routes: Record<string, unknown> = {
    "/api/auth/session/status": unauthenticatedCredentials,
    "/api/auth/credentials/login": authenticatedCredentials(null),
    "/api/auth/credentials/recover": { recovery_token: "token-abc" },
    "/api/auth/credentials/recover/complete": { success: true },
    ...overrides,
  };
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : String(input);
    const body = routes[url];
    if (body === undefined) {
      return Promise.resolve(jsonResponse({ detail: "not found" }, 404));
    }
    if (typeof body === "object" && body !== null && "status" in body) {
      const { status, ...payload } = body as { status: number } & Record<string, unknown>;
      return Promise.resolve(jsonResponse(payload, status));
    }
    return Promise.resolve(jsonResponse(body));
  });
  globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
  return fetchMock;
}

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <LoginScreen />
    </MemoryRouter>,
  );
}

describe("LoginScreen (credentials vault mode)", () => {
  beforeEach(() => {
    (reloadPage as ReturnType<typeof vi.fn>).mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("prompts for the password without a username field and posts password + remember_me", async () => {
    const fetchMock = mockCredentialsRoutes();
    const user = userEvent.setup();

    renderLogin();

    expect(
      await screen.findByRole("button", { name: "Entrar" }),
    ).toBeInTheDocument();
    // R-AC-02: no username field — the vault holds a single account.
    expect(screen.queryByLabelText("Usuario")).not.toBeInTheDocument();

    await user.type(
      screen.getByLabelText("Contraseña"),
      "mi-contraseña-secreta",
    );
    await user.click(screen.getByLabelText(/recordarme/i));
    await user.click(screen.getByRole("button", { name: "Entrar" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url]) => url === "/api/auth/credentials/login",
      );
      expect(call).toBeDefined();
      const [, options] = call as unknown as [string, RequestInit];
      expect(options.method).toBe("POST");
      expect(options.credentials).toBe("same-origin");
      expect(JSON.parse(options.body as string)).toEqual({
        password: "mi-contraseña-secreta",
        remember_me: true,
      });
    });
    await waitFor(() => expect(reloadPage).toHaveBeenCalled());
  });

  it("logs in passwordless: hides the password field and omits it from the body", async () => {
    const fetchMock = mockCredentialsRoutes({
      "/api/auth/session/status": {
        ...unauthenticatedCredentials,
        has_password: false,
      },
    });
    const user = userEvent.setup();

    renderLogin();

    // S-AC-02b: a passwordless account shows no password field — only the
    // "Entrar" button (decided by the backend has_password flag).
    expect(
      await screen.findByRole("button", { name: "Entrar" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Contraseña")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Entrar" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url]) => url === "/api/auth/credentials/login",
      );
      expect(call).toBeDefined();
      const [, options] = call as unknown as [string, RequestInit];
      expect(JSON.parse(options.body as string)).toEqual({
        remember_me: false,
      });
    });
    await waitFor(() => expect(reloadPage).toHaveBeenCalled());
  });

  it("asks for the password when a password-protected account sends none (422)", async () => {
    mockCredentialsRoutes({
      "/api/auth/credentials/login": {
        status: 422,
        detail: "Password required",
      },
    });
    const user = userEvent.setup();

    renderLogin();

    await user.click(await screen.findByRole("button", { name: "Entrar" }));

    expect(
      await screen.findByText("Ingresá tu contraseña para continuar."),
    ).toBeInTheDocument();
  });

  it("surfaces the server error for a wrong password", async () => {
    mockCredentialsRoutes({
      "/api/auth/credentials/login": {
        status: 401,
        detail: "Invalid or rate-limited password",
      },
    });
    const user = userEvent.setup();

    renderLogin();

    await user.type(await screen.findByLabelText("Contraseña"), "incorrecta");
    await user.click(screen.getByRole("button", { name: "Entrar" }));

    expect(
      await screen.findByText("Invalid or rate-limited password"),
    ).toBeInTheDocument();
  });

  it("routes a fresh install (no account) to onboarding", async () => {
    mockCredentialsRoutes({
      "/api/auth/session/status": {
        ...unauthenticatedCredentials,
        has_password: false,
      },
      "/api/auth/credentials/login": {
        status: 401,
        detail: "No account configured",
      },
    });
    const user = userEvent.setup();

    renderLogin();

    await user.click(await screen.findByRole("button", { name: "Entrar" }));

    expect(
      await screen.findByRole("link", { name: tEs("login.configureAccount") }),
    ).toBeInTheDocument();
  });

  it("recovers the account: words → token → new username/password", async () => {
    const fetchMock = mockCredentialsRoutes();
    const user = userEvent.setup();

    renderLogin();

    await user.click(
      await screen.findByRole("button", { name: "¿Olvidaste tu contraseña?" }),
    );

    // Step 1: prove ownership with the recovery words.
    await user.type(
      screen.getByLabelText("Palabras claves"),
      "alpha beta gamma",
    );
    await user.click(screen.getByRole("button", { name: "Recuperar" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url]) => url === "/api/auth/credentials/recover",
      );
      expect(call).toBeDefined();
      const [, options] = call as unknown as [string, RequestInit];
      expect(JSON.parse(options.body as string)).toEqual({ words: "alpha beta gamma" });
    });

    // Step 2: change username + password with the recovery token.
    expect(
      await screen.findByRole("heading", { name: "Cambiar usuario o contraseña" }),
    ).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Usuario"));
    await user.type(screen.getByLabelText("Usuario"), "nuevo-autor");
    await user.type(screen.getByLabelText(/nueva contraseña/i), "nueva-clave");
    await user.click(screen.getByRole("button", { name: "Guardar cambios" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url]) => url === "/api/auth/credentials/recover/complete",
      );
      expect(call).toBeDefined();
      const [, options] = call as unknown as [string, RequestInit];
      expect(JSON.parse(options.body as string)).toEqual({
        recovery_token: "token-abc",
        new_username: "nuevo-autor",
        new_password: "nueva-clave",
      });
    });

    expect(
      await screen.findByText(/credenciales actualizadas/i),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Volver al inicio de sesión" }),
    );
    expect(
      screen.getByRole("button", { name: "Entrar" }),
    ).toBeInTheDocument();
  });

  it("shows the dismissible re-auth banner once the interval elapsed", async () => {
    mockCredentialsRoutes({
      "/api/auth/session/status": authenticatedCredentials(0),
    });
    const user = userEvent.setup();

    renderLogin();

    // The banner is an alert; the countdown card (role=status) is always
    // visible and carries the same warning copy (S-AC-04b/d).
    const banner = await screen.findByRole("alert");
    expect(
      within(banner).getByText(
        /si no reingresas tu contraseña, la sesión de demiurgos se cerrará/i,
      ),
    ).toBeInTheDocument();

    await user.click(
      within(banner).getByRole("button", { name: "Descartar aviso" }),
    );

    // Dismissed: the banner disappears, the countdown card stays.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("keeps the countdown and warning always visible on the welcome card", async () => {
    mockCredentialsRoutes({
      "/api/auth/session/status": authenticatedCredentials(4),
    });

    renderLogin();

    expect(
      await screen.findByText("Reingreso recomendado en 4 días"),
    ).toBeInTheDocument();
    const countdown = screen.getByRole("status");
    expect(
      within(countdown).getByText(
        /si no reingresas tu contraseña, la sesión de demiurgos se cerrará/i,
      ),
    ).toBeInTheDocument();
    // The banner only appears once the interval elapsed (reauthDue).
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});