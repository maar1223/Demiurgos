import { useState } from "react";
import { Navbar } from "@/components/organisms/Navbar";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { IdeaCapturePanel } from "@/components/organisms/IdeaCapturePanel";
import { AssistantSettingsPanel } from "@/components/organisms/AssistantSettingsPanel";
import { useWorlds } from "@/hooks/useWorlds";
import { useLocalDevAuth } from "@/hooks/useLocalDevAuth";
import { cn } from "@/lib/utils";

type ProfileSection = "sesion" | "integraciones" | "asistente";

/** Sesión de edición — the same local-dev session controls as the Navbar
 *  dropdown, kept accessible from the full Profile page. */
function SessionSection() {
  const { status, isLoading, error, start, logout } = useLocalDevAuth(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const handleAction = async () => {
    setActionLoading(true);
    setActionError(null);
    try {
      if (status?.authenticated) {
        await logout();
      } else {
        await start();
      }
    } catch (cause) {
      setActionError(
        cause instanceof Error ? cause.message : "No se pudo actualizar la sesión local",
      );
    } finally {
      setActionLoading(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-6 text-small text-tinta-desvaida">
        <Spinner size="sm" /> Comprobando sesión local…
      </div>
    );
  }

  if (error) {
    return <p className="text-small text-sangre">{error.message}</p>;
  }

  if (!status) return null;

  return (
    <div className="rounded-lg border border-filio bg-madero p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-heading text-body text-pergamino">Sesión de edición</h3>
        <span className="text-small text-tinta-desvaida">Local</span>
      </div>

      {status.authenticated && (
        <>
          <p className="mt-3 text-small text-musgo">Sesión local activa</p>
          <p className="mt-1 text-small text-tinta-desvaida">{status.label}</p>
          <Button
            variant="secondary"
            onClick={() => void handleAction()}
            disabled={actionLoading}
            className="mt-3"
          >
            {actionLoading ? "Cerrando…" : "Cerrar sesión local"}
          </Button>
        </>
      )}

      {!status.authenticated && status.enabled && (
        <>
          <p className="mt-3 text-small text-tinta-desvaida">
            Sesión local no iniciada. Iniciala para editar y configurar el perfil.
          </p>
          <Button
            variant="primary"
            onClick={() => void handleAction()}
            disabled={actionLoading}
            className="mt-3"
          >
            {actionLoading ? "Iniciando…" : "Iniciar sesión local"}
          </Button>
        </>
      )}

      {!status.enabled && (
        <p className="mt-3 text-small text-tinta-desvaida">
          Autenticación local desactivada. Activá{" "}
          <code className="text-plata">DEMIURGOS_AUTH_MODE=local-dev</code> en{" "}
          <code className="text-plata">.env</code> para probar la edición.
        </p>
      )}

      {actionError && <p className="mt-3 text-small text-sangre">{actionError}</p>}
    </div>
  );
}

/** Perfil → Integraciones → Captura de ideas (temporary MVP panel). */
function IntegrationsSection() {
  const auth = useLocalDevAuth(true);
  return (
    <div>
      <h3 className="font-heading text-body text-pergamino">Captura de ideas</h3>
      <p className="mt-1 text-small text-tinta-desvaida">
        Hermes / Telegram — ingreso de ideas nativo desde el bot.
      </p>
      <div className="mt-4">
        <IdeaCapturePanel auth={auth} />
      </div>
    </div>
  );
}

function AssistantSection() {
  const auth = useLocalDevAuth(true);
  return <AssistantSettingsPanel auth={auth} />;
}

/**
 * Profile page (`/perfil`).
 *
 * Sections: Sesión de edición (local-dev auth, same controls as the Navbar
 * dropdown) and Integraciones (idea capture configuration panel). The whole
 * page sits behind the same local-dev auth boundary as wiki editing.
 */
export default function ProfilePage() {
  const { worlds } = useWorlds();
  const [section, setSection] = useState<ProfileSection>("sesion");

  const tabs: { id: ProfileSection; label: string }[] = [
    { id: "sesion", label: "Sesión de edición" },
    { id: "integraciones", label: "Integraciones" },
    { id: "asistente", label: "Asistente IA" },
  ];

  return (
    <div className="flex min-h-screen flex-col bg-cripta">
      <Navbar worlds={worlds} />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
        <h1 className="font-heading text-h3 text-pergamino">Perfil</h1>
        <div className="mt-6 flex flex-col gap-6 md:flex-row">
          <nav
            aria-label="Secciones del perfil"
            className="flex gap-1 md:w-56 md:flex-col md:gap-1"
          >
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setSection(tab.id)}
                aria-current={section === tab.id ? "page" : undefined}
                className={cn(
                  "rounded-lg px-3 py-2 text-left text-body transition-colors",
                  section === tab.id
                    ? "bg-piedra text-pergamino"
                    : "text-tinta-desvaida hover:bg-madero hover:text-pergamino",
                )}
              >
                {tab.label}
              </button>
            ))}
          </nav>
          <section className="min-w-0 flex-1">
            {section === "sesion" ? (
              <SessionSection />
            ) : section === "integraciones" ? (
              <IntegrationsSection />
            ) : (
              <AssistantSection />
            )}
          </section>
        </div>
      </main>
    </div>
  );
}
