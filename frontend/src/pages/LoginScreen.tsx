import { useEffect, useState } from "react";
import { GoogleLogin } from "@react-oauth/google";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { getAuthStatus, startEmergencySession } from "@/api/wiki";
import type { AuthSessionStatus } from "@/api/types";
import { useGoogleAuth } from "@/hooks/useGoogleAuth";
import { useLocalDevAuth } from "@/hooks/useLocalDevAuth";
import { reloadPage } from "@/lib/reloadPage";

/**
 * Full-screen login page (mandatory when DEMIURGOS_AUTH_MODE=local-dev or
 * =google).
 *
 * This is the authentication gate: when auth is enabled, the user MUST
 * authenticate before accessing any application surface. Similar to
 * onboarding, this is a blocking screen that cannot be dismissed.
 *
 * Mode-aware:
 * - `google` — "Continuar con Google" (GIS id_token + server nonce), the
 *   "Recordarme" opt-in (14d TTL) and the offline emergency-key fallback,
 *   surfaced when the GSI script fails to load or the Google flow errors.
 * - `local-dev` — the legacy single-button loopback session (unchanged).
 * - `disabled` — never blocks; shows an explanatory card if reached.
 */
export default function LoginScreen() {
  const [status, setStatus] = useState<AuthSessionStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [statusError, setStatusError] = useState<Error | null>(null);

  const googleEnabled = status?.mode === "google";
  const google = useGoogleAuth(googleEnabled);
  const localDev = useLocalDevAuth(status?.mode === "local-dev");

  const [localActionLoading, setLocalActionLoading] = useState(false);
  const [localActionError, setLocalActionError] = useState<string | null>(null);

  const [emergencyKey, setEmergencyKey] = useState("");
  const [emergencyLoading, setEmergencyLoading] = useState(false);
  const [emergencyError, setEmergencyError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void getAuthStatus()
      .then((next) => {
        if (active) setStatus(next);
      })
      .catch((cause: unknown) => {
        if (active) {
          setStatusError(
            cause instanceof Error
              ? cause
              : new Error("No se pudo consultar la sesión"),
          );
        }
      })
      .finally(() => {
        if (active) setStatusLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const handleLocalLogin = async () => {
    setLocalActionLoading(true);
    setLocalActionError(null);
    try {
      await localDev.start();
      // After successful login, the page will reload and the AuthGate
      // will allow access to the application.
      reloadPage();
    } catch (cause) {
      setLocalActionError(
        cause instanceof Error
          ? cause.message
          : "No se pudo iniciar sesión",
      );
    } finally {
      setLocalActionLoading(false);
    }
  };

  const handleEmergency = async () => {
    setEmergencyLoading(true);
    setEmergencyError(null);
    try {
      await startEmergencySession(emergencyKey.trim());
      reloadPage();
    } catch (cause) {
      setEmergencyError(
        cause instanceof Error
          ? cause.message
          : "Clave de emergencia inválida",
      );
    } finally {
      setEmergencyLoading(false);
    }
  };

  if (statusLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-cripta">
        <div className="flex flex-col items-center gap-4">
          <Spinner size="lg" />
          <p className="text-body text-tinta-desvaida">Verificando sesión…</p>
        </div>
      </div>
    );
  }

  if (statusError && !status) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-cripta px-4">
        <div className="w-full max-w-md rounded-lg border border-sangre/30 bg-madero p-6">
          <h1 className="font-heading text-h3 text-sangre">Error de conexión</h1>
          <p className="mt-3 text-body text-pergamino">{statusError.message}</p>
          <p className="mt-3 text-small text-tinta-desvaida">
            Verificá que el servidor esté corriendo y recargá la página.
          </p>
        </div>
      </div>
    );
  }

  if (!status) return null;

  // Auth is disabled: this screen should never appear, but if it does,
  // show a clear message instead of blocking the user.
  if (!status.enabled) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-cripta px-4">
        <div className="w-full max-w-md rounded-lg border border-filio bg-madero p-6">
          <h1 className="font-heading text-h3 text-pergamino">Autenticación desactivada</h1>
          <p className="mt-3 text-body text-tinta-desvaida">
            La autenticación está desactivada. No es necesario iniciar sesión.
          </p>
          <p className="mt-3 text-small text-tinta-desvaida">
            Si querés habilitar la autenticación, configurá{" "}
            <code className="rounded bg-cripta px-1.5 py-0.5 text-plata">
              DEMIURGOS_AUTH_MODE
            </code>{" "}
            en <code className="rounded bg-cripta px-1.5 py-0.5 text-plata">.env</code>.
          </p>
        </div>
      </div>
    );
  }

  // Auth is enabled but the user is not authenticated: show login screen.
  return (
    <div className="flex min-h-screen items-center justify-center bg-cripta px-4">
      <div className="w-full max-w-md rounded-lg border border-filio bg-madero p-6">
        <h1 className="font-heading text-h3 text-pergamino">Bienvenido a Demiurgos</h1>
        <p className="mt-3 text-body text-tinta-desvaida">
          Iniciá sesión para acceder al Taller de Mundo y todas sus capacidades.
        </p>

        {status.authenticated ? (
          <div className="mt-6">
            <p className="text-small text-musgo">Sesión activa</p>
            <p className="mt-1 text-small text-tinta-desvaida">{status.label}</p>
            <p className="mt-3 text-small text-tinta-desvaida">
              Redirigiendo a la aplicación…
            </p>
          </div>
        ) : status.mode === "google" ? (
          <GoogleVaultLogin
            rememberMe={google.rememberMe}
            onRememberMeChange={google.setRememberMe}
            nonce={google.nonce}
            nonceFailed={google.nonceFailed}
            scriptError={google.scriptError}
            googleError={google.error}
            onGoogleSuccess={google.startGoogle}
            onGoogleError={google.handleGoogleError}
            emergencyKey={emergencyKey}
            onEmergencyKeyChange={setEmergencyKey}
            emergencyLoading={emergencyLoading}
            emergencyError={emergencyError}
            onEmergencySubmit={handleEmergency}
          />
        ) : (
          <LocalDevLogin
            authenticated={localDev.status?.authenticated ?? false}
            label={localDev.status?.label ?? null}
            isLoading={localDev.isLoading}
            error={localDev.error}
            actionLoading={localActionLoading}
            actionError={localActionError}
            onLogin={() => void handleLocalLogin()}
          />
        )}
      </div>
    </div>
  );
}

interface GoogleVaultLoginProps {
  rememberMe: boolean;
  onRememberMeChange: (remember: boolean) => void;
  nonce: string | null;
  nonceFailed: boolean;
  scriptError: boolean;
  googleError: string | null;
  onGoogleSuccess: (credential: string) => Promise<void>;
  onGoogleError: () => void;
  emergencyKey: string;
  onEmergencyKeyChange: (key: string) => void;
  emergencyLoading: boolean;
  emergencyError: string | null;
  onEmergencySubmit: () => Promise<void>;
}

/**
 * Google vault login block: the GIS button (only when the server nonce is
 * ready), the remember-me opt-in and the emergency-key fallback. The fallback
 * is exposed whenever the Google path cannot complete: script load error,
 * nonce fetch failure or a Google flow / session error.
 */
function GoogleVaultLogin({
  rememberMe,
  onRememberMeChange,
  nonce,
  nonceFailed,
  scriptError,
  googleError,
  onGoogleSuccess,
  onGoogleError,
  emergencyKey,
  onEmergencyKeyChange,
  emergencyLoading,
  emergencyError,
  onEmergencySubmit,
}: GoogleVaultLoginProps) {
  const showEmergency =
    scriptError || nonceFailed || googleError !== null || emergencyLoading;

  return (
    <div className="mt-6">
      <div className="flex flex-col gap-3">
        {nonce ? (
          <GoogleLogin
            nonce={nonce}
            onSuccess={(response) => void onGoogleSuccess(response.credential ?? "")}
            onError={onGoogleError}
            theme="outline"
            size="large"
            text="continue_with"
            shape="rectangular"
            width="100%"
          />
        ) : nonceFailed ? (
          <p className="text-small text-sangre">
            No se pudo obtener el nonce de inicio de sesión. Usá la clave de
            emergencia para acceder.
          </p>
        ) : (
          <div className="flex items-center justify-center py-2">
            <Spinner size="sm" />
          </div>
        )}

        <label className="flex items-center gap-2 text-small text-tinta-desvaida">
          <input
            type="checkbox"
            checked={rememberMe}
            onChange={(event) => onRememberMeChange(event.target.checked)}
            className="h-4 w-4 rounded border-filio bg-cripta accent-musgo"
          />
          Recordarme por 14 días
        </label>
      </div>

      {googleError && (
        <p className="mt-3 text-small text-sangre" role="alert">
          {googleError}
        </p>
      )}

      {showEmergency && (
        <div className="mt-6 rounded-lg border border-filio bg-cripta/50 p-4">
          <h2 className="font-heading text-body text-pergamino">
            Acceso de emergencia
          </h2>
          <p className="mt-1 text-small text-tinta-desvaida">
            Si Google no está disponible (sin conexión o error del proveedor),
            usá tu clave de recuperación.
          </p>
          <div className="mt-3 flex flex-col gap-2">
            <label htmlFor="emergency-key" className="sr-only">
              Clave de emergencia
            </label>
            <input
              id="emergency-key"
              type="text"
              autoComplete="off"
              placeholder="Clave de emergencia"
              value={emergencyKey}
              onChange={(event) => onEmergencyKeyChange(event.target.value)}
              className="w-full rounded-lg border border-filio bg-cripta px-3 py-2 text-body text-pergamino placeholder:text-tinta-desvaida focus:border-plata focus:outline-none"
            />
            <Button
              variant="secondary"
              onClick={() => void onEmergencySubmit()}
              disabled={emergencyLoading || emergencyKey.trim() === ""}
              className="w-full"
            >
              {emergencyLoading ? (
                <span className="flex items-center justify-center gap-2">
                  <Spinner size="sm" />
                  Verificando…
                </span>
              ) : (
                "Ingresar con clave de emergencia"
              )}
            </Button>
          </div>
          {emergencyError && (
            <p className="mt-3 text-small text-sangre" role="alert">
              {emergencyError}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

interface LocalDevLoginProps {
  authenticated: boolean;
  label: string | null;
  isLoading: boolean;
  error: Error | null;
  actionLoading: boolean;
  actionError: string | null;
  onLogin: () => void;
}

/** Legacy local-dev login block: a single loopback session button. */
function LocalDevLogin({
  authenticated,
  label,
  isLoading,
  error,
  actionLoading,
  actionError,
  onLogin,
}: LocalDevLoginProps) {
  if (isLoading) {
    return (
      <div className="mt-6 flex items-center gap-2 text-small text-tinta-desvaida">
        <Spinner size="sm" /> Verificando sesión local…
      </div>
    );
  }

  if (error) {
    return <p className="mt-4 text-small text-sangre">{error.message}</p>;
  }

  return (
    <div className="mt-6">
      {authenticated ? (
        <div>
          <p className="text-small text-musgo">Sesión local activa</p>
          <p className="mt-1 text-small text-tinta-desvaida">{label}</p>
          <p className="mt-3 text-small text-tinta-desvaida">
            Redirigiendo a la aplicación…
          </p>
        </div>
      ) : (
        <div>
          <Button
            variant="primary"
            onClick={onLogin}
            disabled={actionLoading}
            className="w-full"
          >
            {actionLoading ? (
              <span className="flex items-center justify-center gap-2">
                <Spinner size="sm" />
                Iniciando sesión…
              </span>
            ) : (
              "Iniciar sesión local"
            )}
          </Button>
          <p className="mt-3 text-center text-small text-tinta-desvaida">
            La sesión es local y segura. No requiere credenciales externas.
          </p>
        </div>
      )}

      {actionError && (
        <div className="mt-4 rounded-lg border border-sangre/30 bg-sangre/10 p-3">
          <p className="text-small text-sangre">{actionError}</p>
        </div>
      )}
    </div>
  );
}