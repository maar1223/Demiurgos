import { useEffect, useState } from "react";
import { useWorlds } from "@/hooks/useWorlds";
import { useCoCreation } from "@/hooks/useCoCreation";
import { WorldSelector } from "@/components/molecules/WorldSelector";
import { TallerSelector } from "@/components/molecules/TallerSelector";
import { CreateWorldModal } from "@/components/organisms/CreateWorldModal";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import { MethodologyLibrary } from "@/components/organisms/MethodologyLibrary";
import { GlobalMethodologyLibrary } from "@/components/organisms/GlobalMethodologyLibrary";
import { ToolWorkshopHeader } from "@/components/organisms/ToolWorkshopHeader";
import { LensToggle, type Lens } from "@/components/organisms/LensToggle";
import {
  CoCreationMilestoneSidebar,
  CoCreationPanel,
  CoCreationContextPanel,
} from "@/components/organisms/CoCreationPanel";
import { EditorLayout } from "@/components/templates/EditorLayout";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { Spinner } from "@/components/atoms/Spinner";
import { cn } from "@/lib/utils";
import type { MethodologyInventoryItem } from "@/api/types";
import {
  getCurrentTaller,
  setCurrentTaller,
  subscribeCurrentTaller,
} from "@/lib/currentTaller";

/** Page-level methodology selection (REQ-SB-5): the `{ skill_id, version }`
 *  pair picked in the "Taller" explorer. Lives at page level so it survives
 *  lens switches AND tab switches (SC-SB-5.1/5.2), mirroring the `lens`
 *  precedent (REQ-LEN-1.3/1.4). */
interface MethodologySelection {
  skill_id: string;
  version: string;
}

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
  /** Local view toggle (REQ-TAB-1): "taller" = operational tree + lens
   *  toggle (default), "co-crear" = Skill Madre co-creation. Switching tabs
   *  NEVER touches `activeTaller`, `world`, or persisted state. */
  const [view, setView] = useState<"taller" | "co-crear">("taller");
  /** Internal lens toggle inside the "Taller" tab (REQ-LEN-1): "mi-mundo" =
   *  operational MethodologyLibrary (default), "catalogo-total" = read-only
   *  global inventory. Page-level state so it survives tab switches
   *  (SC-LEN-1.3); never mutated by lens changes (SC-LEN-1.4). */
  const [lens, setLens] = useState<Lens>("mi-mundo");
  /** Methodology selected in the "Taller" explorer (REQ-SB-5). Both names are
   *  underscore-prefixed in this PR because no consumer exists yet — the
   *  EditorLayout wiring (TallerExplorerSidebar + detail/state panels) lands
   *  in the PR 2 integration slice, which renames them to `selected` /
   *  `setSelected` (keeps tsc noUnusedLocals green on the foundation slice). */
  const [_selected, _setSelected] = useState<MethodologySelection | null>(null);
  /** Single shared co-creation hook instance distributed across the three
   *  EditorLayout panes (backend authoritative; localStorage only a hint). */
  const coCreation = useCoCreation();

  const handleWorldCreated = (created: string) => {
    setCreatingWorld(false);
    // Local world stays the same until the user confirms the switch.
    void mutate();
    setPendingSwitch(created);
  };

  /** TW13 adaptation entry on published inventory rows: derive an editable
   *  draft from the published version (the ONLY path for `Oficiales`,
   *  REQ-CC-16) and switch to the "Crear skill" tab, where the chat + canvas
   *  work on the derived draft (REQ-CC-17). The world binding follows the
   *  page's selected world when present; otherwise the session is transversal. */
  const handleAdaptar = async (item: MethodologyInventoryItem) => {
    const result = await coCreation.derive(item.skill_id, item.version, world ?? null);
    if (result) setView("co-crear");
  };

  const confirmSwitch = () => {
    if (!pendingSwitch) return;
    setWorld(pendingSwitch);
    setPendingSwitch(null);
  };

  const tabs = [
    { key: "taller", label: "Taller" },
    { key: "co-crear", label: "Crear skill" },
  ] as const;

  const tablist = (
    <div
      role="tablist"
      aria-label="Vistas del taller de herramientas"
      className="inline-flex gap-1 rounded-lg border border-edge bg-surface-raised p-1"
    >
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={view === tab.key}
          onClick={() => setView(tab.key)}
          className={cn(
            "rounded-md px-4 py-1.5 text-small transition-colors",
            view === tab.key
              ? "bg-action text-action-text"
              : "text-muted hover:bg-surface-hover hover:text-primary",
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );

  return (
    <div className="flex min-h-screen flex-col bg-surface">
      <main
        className={cn(
          "mx-auto w-full flex-1",
          // The co-creation editor spans the full width and fixes its own
          // height; the other views keep the constrained flowing layout.
          view === "co-crear" ? "" : "max-w-7xl px-4 py-8",
        )}
      >
        {view === "co-crear" ? (
          <EditorLayout
            header={
              <ToolWorkshopHeader
                subtitle="Co-creá una skill conversando con la Skill Madre, una pregunta por vez."
                tablist={tablist}
              />
            }
            sidebar={<CoCreationMilestoneSidebar state={coCreation} />}
            rightPanel={<CoCreationContextPanel state={coCreation} />}
          >
            <CoCreationPanel
              state={coCreation}
              worlds={worlds.map((item) => item.name)}
            />
          </EditorLayout>
        ) : (
          <>
            <ToolWorkshopHeader
              subtitle="Metodologías de construcción seguras: editar, compilar, publicar versiones inmutables y activarlas por mundo."
              tablist={tablist}
            />

            <div className="flex items-center py-3">
              <LensToggle lens={lens} onChange={setLens} />
            </div>

            {lens === "mi-mundo" ? (
              isLoading ? (
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
                  <MethodologyLibrary
                    world={world}
                    activeTaller={activeTaller}
                  />
                </>
              )
            ) : (
              <GlobalMethodologyLibrary onAdaptar={(item) => void handleAdaptar(item)} />
            )}
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