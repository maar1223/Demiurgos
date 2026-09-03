import { useEffect, useState } from "react";
import { useWorlds } from "@/hooks/useWorlds";
import { WorldSelector } from "@/components/molecules/WorldSelector";
import { TallerSelector } from "@/components/molecules/TallerSelector";
import { CreateWorldModal } from "@/components/organisms/CreateWorldModal";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import { MethodologyLibrary } from "@/components/organisms/MethodologyLibrary";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { Spinner } from "@/components/atoms/Spinner";
import {
  getCurrentTaller,
  setCurrentTaller,
  subscribeCurrentTaller,
} from "@/lib/currentTaller";

/** Active-Taller hook (spec REQ-TRE-2): subscribes to the custom event +
 *  cross-tab `storage` listener and re-renders on change. */
function useActiveTaller(): string {
  const [activeTaller, setActiveTaller] = useState<string>(() =>
    getCurrentTaller(),
  );

  useEffect(
    () => subscribeCurrentTaller(() => setActiveTaller(getCurrentTaller())),
    [],
  );

  return activeTaller;
}

/**
 * Taller de Herramientas shell (`/taller-herramientas`).
 *
 * The free Core's methodology-workshop landing. Renders the methodology
 * library (view published → publish a validated draft → activate an immutable
 * version by world) and lets the Author pick which world receives the
 * activation via the shared world selector.
 *
 * World creation: this page owns the page-body `WorldSelector` (the global
 * Navbar selector is hoisted to the AppLayout). It wires the `+ Nuevo mundo`
 * entry, the `CreateWorldModal`, and the post-creation switch confirmation.
 * Local `world` is only updated when the user confirms the switch — declined
 * creation does not change the activation target.
 *
 * States:
 * - 🟡 Loading: spinner centered on page
 * - 🔴 Error: ErrorBanner with retry
 * - 🟢 No world selected (or no worlds at all): the library still shows
 *   publications, but activation stays disabled ("Sin mundo")
 * - 🟢 Data: world selector + MethodologyLibrary
 */
export default function ToolWorkshop() {
  const { worlds, isLoading, error, mutate } = useWorlds();
  const [world, setWorld] = useState<string>();
  const activeTaller = useActiveTaller();
  const [creatingWorld, setCreatingWorld] = useState(false);
  const [pendingSwitch, setPendingSwitch] = useState<string | null>(null);

  const handleWorldCreated = (created: string) => {
    setCreatingWorld(false);
    // Local world stays the same until the user confirms the switch.
    void mutate();
    setPendingSwitch(created);
  };

  const confirmSwitch = () => {
    if (!pendingSwitch) return;
    setWorld(pendingSwitch);
    setPendingSwitch(null);
  };

  return (
    <div className="flex min-h-screen flex-col bg-surface">
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8">
        <header className="mb-8">
          <h1 className="font-heading text-h3 text-primary">
            Taller de Herramientas
          </h1>
          <p className="mt-2 text-body text-muted">
            Metodologías de construcción seguras: editar, compilar, publicar
            versiones inmutables y activarlas por mundo.
          </p>
        </header>

        {isLoading ? (
          <div className="flex justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : error ? (
          <ErrorBanner
            message="No se pudo cargar la lista de mundos. Verificá que el servidor esté corriendo."
            onRetry={() => mutate()}
          />
        ) : (
          <>
            <div className="mb-6 flex flex-wrap items-center gap-3">
              <TallerSelector
                activeTaller={activeTaller}
                onTallerChange={setCurrentTaller}
              />
              <WorldSelector
                worlds={worlds}
                currentWorld={world}
                onWorldChange={setWorld}
                onRequestCreate={() => setCreatingWorld(true)}
              />
              <p className="text-small text-muted">
                {world
                  ? `Las activaciones se aplican a «${world}».`
                  : worlds.length > 0
                    ? "Elegí un mundo para poder activar versiones."
                    : "No hay mundos disponibles; podés ver publicaciones pero no activar."}
              </p>
            </div>
            <MethodologyLibrary world={world} activeTaller={activeTaller} />
          </>
        )}
      </main>

      <CreateWorldModal
        isOpen={creatingWorld}
        onClose={() => setCreatingWorld(false)}
        onCreated={(created) => handleWorldCreated(created.name)}
      />

      {pendingSwitch && (
        <ConfirmDialog
          title="Cambiar mundo activo"
          message={`¿Querés cambiar el mundo activo a «${pendingSwitch}»?`}
          confirmLabel="Cambiar"
          onConfirm={confirmSwitch}
          onClose={() => setPendingSwitch(null)}
        />
      )}
    </div>
  );
}