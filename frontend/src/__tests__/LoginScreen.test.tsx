import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "@/App";
import { reloadPage } from "@/lib/reloadPage";

/**
 * jsdom's Location.reload is an own non-configurable property that cannot be
 * spied on or replaced. The app routes reloads through `reloadPage()` so this
 * suite stubs that seam instead.
 */
vi.mock("@/lib/reloadPage", () => ({
  reloadPage: vi.fn(),
}));

/**
 * GIS mock — the real GoogleOAuthProvider would inject the GSI script, which
 * jsdom never loads. The mock renders children and can fire the
 * `onScriptLoadError` provider callback (the emergency-fallback trigger).
 * `GoogleLogin` is replaced by a plain button that resolves with an id_token.
 */
const gsi = vi.hoisted(() => ({ fireScriptError: false }));

vi.mock("@react-oauth/google", async () => {
  const React = await import("react");
  return {
    GoogleOAuthProvider: ({
      children,
      onScriptLoadError,
    }: {
      children: React.ReactNode;
      onScriptLoadError?: () => void;
    }) => {
      React.useEffect(() => {
        if (gsi.fireScriptError) onScriptLoadError?.();
      }, [onScriptLoadError]);
      return <>{children}</>;
    },
    GoogleLogin: ({
      onSuccess,
    }: {
      onSuccess: (response: { credential?: string }) => void;
    }) => (
      <button
        type="button"
        onClick={() => onSuccess({ credential: "test-id-token" })}
      >
        Continuar con Google
      </button>
    ),
  };
});

const unauthenticatedGoogle = {
  mode: "google",
  enabled: true,
  authenticated: false,
  label: null,
};

function jsonResponse(body: unknown) {
  return {
    ok: true,
    status: 200,
    json: vi.fn().mockResolvedValue(body),
    headers: new Headers(),
  };
}

/** Route-based fetch mock for the vault endpoints used by the login flow. */
function mockVaultRoutes(overrides: Record<string, unknown> = {}) {
  const routes: Record<string, unknown> = {
    "/api/auth/session/status": unauthenticatedGoogle,
    "/api/auth/google/nonce": { nonce: "test-nonce" },
    "/api/auth/google/session": {
      mode: "google",
      enabled: true,
      authenticated: true,
      label: "author@example.com",
      provider: "google",
    },
    "/api/auth/emergency/session": {
      mode: "google",
      enabled: true,
      authenticated: true,
      label: "Emergency recovery",
      provider: "emergency",
    },
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
      return Promise.resolve({
        ok: false,
        status: 404,
        json: vi.fn().mockResolvedValue({ detail: "not found" }),
      } as unknown as Response);
    }
    return Promise.resolve(jsonResponse(body) as unknown as Response);
  });
  globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
  return fetchMock;
}

describe("LoginScreen (google vault mode)", () => {
  beforeEach(() => {
    gsi.fireScriptError = false;
    (reloadPage as ReturnType<typeof vi.fn>).mockClear();
  });

  afterEach(() => {
    gsi.fireScriptError = false;
    vi.restoreAllMocks();
  });

  it("posts the Google id_token to /api/auth/google/session and reloads", async () => {
    const fetchMock = mockVaultRoutes();
    const user = userEvent.setup();

    render(<App />);

    await user.click(
      await screen.findByRole("button", { name: "Continuar con Google" }),
    );

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url]) => url === "/api/auth/google/session",
      );
      expect(call).toBeDefined();
      const [, options] = call as unknown as [string, RequestInit];
      expect(options.method).toBe("POST");
      expect(options.credentials).toBe("same-origin");
      expect(JSON.parse(options.body as string)).toEqual({
        id_token: "test-id-token",
        remember_me: false,
      });
    });
    await waitFor(() => expect(reloadPage).toHaveBeenCalled());
  });

  it("sends remember_me=true when the checkbox is selected", async () => {
    const fetchMock = mockVaultRoutes();
    const user = userEvent.setup();

    render(<App />);

    await user.click(
      await screen.findByRole("checkbox", { name: /recordarme/i }),
    );
    await user.click(
      screen.getByRole("button", { name: "Continuar con Google" }),
    );

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url]) => url === "/api/auth/google/session",
      );
      expect(call).toBeDefined();
      const [, options] = call as unknown as [string, RequestInit];
      expect(JSON.parse(options.body as string)).toEqual({
        id_token: "test-id-token",
        remember_me: true,
      });
    });
  });

  it("shows the emergency fallback when the GSI script fails to load", async () => {
    gsi.fireScriptError = true;
    mockVaultRoutes();

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Acceso de emergencia" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Clave de emergencia")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Ingresar con clave de emergencia" }),
    ).toBeInTheDocument();
  });

  it("posts the emergency key to /api/auth/emergency/session and reloads", async () => {
    gsi.fireScriptError = true;
    const fetchMock = mockVaultRoutes();
    const user = userEvent.setup();

    render(<App />);

    await user.type(
      await screen.findByLabelText("Clave de emergencia"),
      "clave secreta",
    );
    await user.click(
      screen.getByRole("button", { name: "Ingresar con clave de emergencia" }),
    );

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url]) => url === "/api/auth/emergency/session",
      );
      expect(call).toBeDefined();
      const [, options] = call as unknown as [string, RequestInit];
      expect(JSON.parse(options.body as string)).toEqual({
        key: "clave secreta",
      });
    });
    await waitFor(() => expect(reloadPage).toHaveBeenCalled());
  });
});