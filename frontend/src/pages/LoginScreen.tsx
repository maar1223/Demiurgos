import { useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { useLocalDevAuth } from "@/hooks/useLocalDevAuth";

/**
 * Full-screen login page (mandatory when DEMIURGOS_AUTH_MODE=local-dev).
 *
 * This is the authentication gate: when local auth is enabled, the user
 * MUST authenticate before accessing any application surface. Similar to
 * onboarding, this is a blocking screen that cannot be dismissed.
 *
 * The login is simple: a single button that starts the local dev session.
 * No credentials needed (loopback-only, cookie-based). The goal is to
 * make authentication explicit and unavoidable, not to add friction.
 */
export default function LoginScreen() {
  const { status, isLoading, error, start } = useLocalDevAuth(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const handleLogin = async () => {
    setActionLoading(true);
    setActionError(null);
    try {
      await start();
      // After successful login, the page will reload and the AuthGate
      // will allow access to the application.
      window.location.reload();
    } catch (cause) {
      setActionError(
        cause instanceof Error ? cause.message : "No se pudo iniciar sesión",
      );
    } finally {
      setActionLoading(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-cripta">
        <div className="flex flex-col items-center gap-4">
          <Spinner size="lg" />
          <p className="text-body text-tinta-desvaida">Verificando sesión…</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-cripta px-4">
        <div className="w-full max-w-md rounded-lg border border-sangre/30 bg-madero p-6">
          <h1 className="font-heading text-h3 text-sangre">Error de conexión</h1>
          <p className="mt-3 text-body text-pergamino">{error.message}</p>
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
            La autenticación local está desactivada. No es necesario iniciar sesión.
          </p>
          <p className="mt-3 text-small text-tinta-desvaida">
            Si querés habilitar la autenticación, configurá{" "}
            <code className="rounded bg-cripta px-1.5 py-0.5 text-plata">
              DEMIURGOS_AUTH_MODE=local-dev
            </code>{" "}
            en <code className="rounded bg-cripta px-1.5 py-0.5 text-plata">.env</code>.
          </p>
        </div>
      </div>
    );
  }

  // Auth is enabled but user is not authenticated: show login screen.
  return (
    <div className="flex min-h-screen items-center justify-center bg-cripta px-4">
      <div className="w-full max-w-md rounded-lg border border-filio bg-madero p-6">
        <h1 className="font-heading text-h3 text-pergamino">Bienvenido a Demiurgos</h1>
        <p className="mt-3 text-body text-tinta-desvaida">
          Iniciá sesión para acceder al Taller de Mundo y todas sus capacidades.
        </p>

        {status.authenticated ? (
          <div className="mt-6">
            <p className="text-small text-musgo">Sesión local activa</p>
            <p className="mt-1 text-small text-tinta-desvaida">{status.label}</p>
            <p className="mt-3 text-small text-tinta-desvaida">
              Redirigiendo a la aplicación…
            </p>
          </div>
        ) : (
          <div className="mt-6">
            <Button
              variant="primary"
              onClick={() => void handleLogin()}
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
    </div>
  );
}
