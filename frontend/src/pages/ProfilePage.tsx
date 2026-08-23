import { useCallback, useEffect, useState } from "react";
import { Navbar } from "@/components/organisms/Navbar";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { IdeaCapturePanel } from "@/components/organisms/IdeaCapturePanel";
import { AssistantSettingsPanel } from "@/components/organisms/AssistantSettingsPanel";
import { DeleteWorldModal } from "@/components/organisms/DeleteWorldModal";
import { WorldTrashPanel } from "@/components/organisms/WorldTrashPanel";
import { getIdeaCaptureStatus } from "@/api/ideaCapture";
import { useWorlds } from "@/hooks/useWorlds";
import { useLocalDevAuth } from "@/hooks/useLocalDevAuth";
import type { WorldInfo } from "@/api/types";
import { cn } from "@/lib/utils";

type ProfileSection = "sesion" | "integraciones" | "asistente" | "mundos";

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
 * Perfil → Mundos — world management: the "Zona peligrosa" delete flow and
 * the world-level recycle bin ("Papelera de mundos").
 *
 * The delete button mirrors the backend guards: it is disabled for the active
 * world (idea-capture config) and when the world is the only one left. A
 * successful delete refreshes the worlds list and bumps the trash panel's
 * refresh token so the new entry appears immediately.
 */
function WorldsSection() {
  const { worlds, isLoading, error, mutate } = useWorlds();
  const [deleteTarget, setDeleteTarget] = useState<WorldInfo | null>(null);
  const [trashRefresh, setTrashRefresh] = useState(0);
  const [activeWorld, setActiveWorld] = useState("");

  // The backend refuses to delete the active world; mirror that rule in the
  // UI with a disabled button + tooltip. Fail-open: if the idea-capture
  // status cannot be read, no world is treated as active.
  useEffect(() => {
    let active = true;
    void getIdeaCaptureStatus()
      .then((status) => {
        if (active) setActiveWorld(status.config.active_world);
      })
      .catch(() => {
        if (active) setActiveWorld("");
      });
    return () => {
      active = false;
    };
  }, []);

  const onlyWorld = worlds.length <= 1;

  const handleDeleted = useCallback(() => {
    void mutate();
    setTrashRefresh((n) => n + 1);
    setDeleteTarget(null);
  }, [mutate]);

  const handleTrashChanged = useCallback(() => {
    // A restore makes a world reappear; a purge only empties the trash.
    void mutate();
  }, [mutate]);

  return (
    <div>
      <h3 className="font-heading text-body text-pergamino">Mundos</h3>
      <p className="mt-1 text-small text-tinta-desvaida">
        Gestioná los mundos del taller: eliminá uno (queda recuperable 30 días en la papelera) o
        restaurá mundos eliminados.
      </p>

      {/* Zona peligrosa — 3-step confirmation before any delete. */}
      <div className="mt-4 rounded-lg border border-sangre/30 bg-sangre/10 p-4">
        <h4 className="flex items-center gap-2 font-heading text-body text-sangre">
          <Icon name="trash" size={18} />
          Zona peligrosa
        </h4>
        <p className="mt-1 text-small text-tinta-desvaida">
          Eliminar un mundo lo mueve a la papelera durante 30 días; no se destruye de inmediato.
        </p>

        {error && (
          <div
            role="alert"
            className="mt-3 rounded-lg border border-sangre/30 bg-sangre/10 px-3 py-2 text-small text-sangre"
          >
            {error.message}
          </div>
        )}

        {isLoading ? (
          <div className="flex items-center justify-center py-6">
            <Spinner size="md" />
          </div>
        ) : worlds.length === 0 ? (
          <p className="mt-3 text-small text-tinta-desvaida">No hay mundos creados todavía.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2">
            {worlds.map((world) => {
              const isActive = activeWorld.toLowerCase() === world.name.toLowerCase();
              const disabledReason = isActive
                ? "No se puede eliminar el mundo activo"
                : onlyWorld
                  ? "Debe existir al menos un mundo"
                  : null;
              return (
                <li
                  key={world.name}
                  className="flex items-center gap-3 rounded-lg border border-filio bg-cripta/50 px-3 py-2"
                >
                  <Icon name="world" size={18} className="shrink-0 text-plata" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-mono text-small text-pergamino">{world.name}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      <Badge>Lore {world.lore_count}</Badge>
                      <Badge>Personajes {world.character_count}</Badge>
                      <Badge>Sagas {world.saga_count}</Badge>
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={disabledReason !== null}
                    title={disabledReason ?? undefined}
                    onClick={() => setDeleteTarget(world)}
                  >
                    Borrar
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Papelera de mundos — restore / permanent delete. */}
      <div className="mt-6">
        <WorldTrashPanel refreshToken={trashRefresh} onChanged={handleTrashChanged} />
      </div>

      {deleteTarget && (
        <DeleteWorldModal
          world={deleteTarget}
          onDeleted={handleDeleted}
          onClose={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}

/**
 * Profile page (`/perfil`).
 *
 * Sections: Sesión de edición (local-dev auth, same controls as the Navbar
 * dropdown), Integraciones (idea capture configuration panel), Asistente IA
 * (assistant settings) and Mundos (world delete + recycle bin). The whole
 * page sits behind the same local-dev auth boundary as wiki editing.
 */
export default function ProfilePage() {
  const { worlds } = useWorlds();
  const [section, setSection] = useState<ProfileSection>("sesion");

  const tabs: { id: ProfileSection; label: string }[] = [
    { id: "sesion", label: "Sesión de edición" },
    { id: "integraciones", label: "Integraciones" },
    { id: "asistente", label: "Asistente IA" },
    { id: "mundos", label: "Mundos" },
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
            ) : section === "mundos" ? (
              <WorldsSection />
            ) : (
              <AssistantSection />
            )}
          </section>
        </div>
      </main>
    </div>
  );
}
