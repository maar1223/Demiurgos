import { useCallback, useEffect, useState } from "react";
import { useWorlds } from "@/hooks/useWorlds";
import { useCoCreation } from "@/hooks/useCoCreation";
import { CreateWorldModal } from "@/components/organisms/CreateWorldModal";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import { ToolWorkshopHeader } from "@/components/organisms/ToolWorkshopHeader";
import { TallerExplorerSidebar } from "@/components/organisms/TallerExplorerSidebar";
import { MethodologyDetailView } from "@/components/organisms/MethodologyDetailView";
import { MethodologyStatePanel } from "@/components/organisms/MethodologyStatePanel";
import { toggleCompareSelection } from "@/components/organisms/GlobalMethodologyLibrary";
import {
  CoCreationMilestoneSidebar,
  CoCreationPanel,
  CoCreationContextPanel,
} from "@/components/organisms/CoCreationPanel";
import { EditorLayout } from "@/components/templates/EditorLayout";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { Spinner } from "@/components/atoms/Spinner";
import {
  activateCompanion,
  activateMethodology,
  deactivateCompanion,
  exportPublished,
  getMethodologyStatus,
} from "@/api/methodologies";
import type { Lens } from "@/components/organisms/LensToggle";
import type { MethodologyInventoryItem, MethodologyStatus } from "@/api/types";
import { markCompanionLatencyNotified } from "@/lib/companionLatency";
import { getCurrentWorld, subscribeCurrentWorld } from "@/lib/currentWorld";
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
 * BOTH tabs render inside the shared `EditorLayout` 3-pane shell (SC-SB-1):
 * the "Taller" tab gets the methodology explorer sidebar, the read-only
 * `MethodologyDetailView` body and the `MethodologyStatePanel` right pane; the
 * "Crear skill" tab keeps the co-creation panes. The previous flowing
 * `max-w-7xl` wrapper is gone.
 *
 * World creation: this page owns the `WorldSelector` inside the sidebar
 * header (the global Navbar selector is hoisted to the AppLayout). It wires
 * the `+ Nuevo mundo` entry, the `CreateWorldModal`, and the post-creation
 * switch confirmation. Local `world` is only updated when the user confirms
 * the switch — declined creation does not change the activation target.
 *
 * States:
 * - 🟡 Loading (worlds): spinner centered in the EditorLayout body
 * - 🔴 Error (worlds): ErrorBanner with retry in the body
 * - 🟢 No world selected (or no worlds at all): the tree still shows
 *   publications, but activation stays disabled ("Sin mundo")
 * - 🟢 Data: sidebar explorer + detail body + state/actions panel
 */
export default function ToolWorkshop() {
  const { worlds, isLoading, error, mutate } = useWorlds();
  /** Activation target world. Initialized from the Navbar-persisted global
   *  world and kept in sync with it (same subscribe pattern as
   *  `useActiveTaller`): without this, the sidebar `WorldSelector` falls back
   *  to the Navbar world for DISPLAY while this state stayed `undefined`, so
   *  the tree rendered a world-labeled selector next to a permanently
   *  disabled "Sin mundo" activation button until a manual switch-confirm. */
  const [world, setWorld] = useState<string | undefined>(
    () => getCurrentWorld() ?? undefined,
  );
  useEffect(
    () => subscribeCurrentWorld(() => setWorld(getCurrentWorld() ?? undefined)),
    [],
  );
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
  /** Methodology selected in the "Taller" explorer (REQ-SB-5). Page-level so
   *  it survives lens + tab switches (SC-SB-5.1/5.2). */
  const [selected, setSelected] = useState<MethodologySelection | null>(null);
  /** Page-lifted library status (task 2.3): fetched on mount and refetched
   *  after activations; shared by the sidebar tree and the right state panel
   *  (no per-skill endpoint exists — filtering is client-side). */
  const [status, setStatus] = useState<MethodologyStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  /** World whose first-activation latency notice is active (R-UI notice): set
   *  only on the FIRST-ever successful companion activation in that world. */
  const [latencyNoticeWorld, setLatencyNoticeWorld] = useState<string | null>(
    null,
  );
  /** Compare selection shared by the catalog explorer rows and the right
   *  panel's "Comparar" action (SC-SB-4.2). */
  const [compareSelection, setCompareSelection] = useState<
    MethodologyInventoryItem[]
  >([]);
  /** Single shared co-creation hook instance distributed across the three
   *  EditorLayout panes (backend authoritative; localStorage only a hint). */
  const coCreation = useCoCreation();

  const loadStatus = useCallback(async () => {
    setStatusError(null);
    try {
      setStatus(await getMethodologyStatus());
    } catch {
      setStatusError("No se pudo cargar la biblioteca de metodologías.");
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  /** World-scoped activation (moved up from MethodologyLibrary, task 2.3):
   *  the page owns it so a successful activation can refetch the shared
   *  status for both the tree and the right panel. */
  const handleActivate = useCallback(
    async (skillId: string, version: string) => {
      if (!world) {
        return;
      }
      setBusy(true);
      setStatusError(null);
      try {
        await activateMethodology(world, skillId, version);
        await loadStatus();
      } catch {
        setStatusError("No se pudo activar la versión para este mundo.");
      } finally {
        setBusy(false);
      }
    },
    [world, loadStatus],
  );

  /** World-scoped companion toggle (R-UI chips): mirrors handleActivate — the
   *  client call is followed by the shared status refetch. The first-ever
   *  successful activation in a world surfaces the one-time latency notice
   *  (persisted per world so it never repeats, R-UI notice). */
  const handleToggleCompanion = useCallback(
    async (skillId: string, version: string, on: boolean) => {
      if (!world) {
        return;
      }
      const previousCompanions = status?.companions?.[world] ?? [];
      setBusy(true);
      setStatusError(null);
      try {
        if (on) {
          await activateCompanion(world, skillId, version);
        } else {
          await deactivateCompanion(world, skillId);
        }
        await loadStatus();
        if (
          on &&
          previousCompanions.length === 0 &&
          markCompanionLatencyNotified(world)
        ) {
          setLatencyNoticeWorld(world);
        }
      } catch {
        setStatusError("No se pudo actualizar la skill compañera para este mundo.");
      } finally {
        setBusy(false);
      }
    },
    [world, status, loadStatus],
  );

  /** Catalogo "Comparar" (SC-SB-4.2): toggles the selected item in the
   *  compare selection shared with the catalog sidebar (REQ-LIB-7 caps at
   *  two, replacing the oldest on a third selection). */
  const handleComparar = useCallback((item: MethodologyInventoryItem) => {
    setCompareSelection((prev) => toggleCompareSelection(prev, item));
  }, []);

  /** Catalogo "Exportar" (SC-SB-4.2): downloads the published version as a
   *  `.zip` package. Failures stay silent here — the catalog rows already
   *  surface inline export errors (REQ-IMP-1). */
  const handleExportar = useCallback(async (item: MethodologyInventoryItem) => {
    try {
      const blob = await exportPublished(item.skill_id, item.version);
      const objectUrl = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = `${item.skill_id}-${item.version}.zip`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(objectUrl);
    } catch {
      // Silent: the catalog row export already reports failures inline.
    }
  }, []);

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

  /** UL-5: empty-state CTA of the mi-mundo library — jumps straight to the
   *  "Crear skill" tab to author the first skill. */
  const handleGoToCoCrear = useCallback(() => setView("co-crear"), []);

  const confirmSwitch = () => {
    if (!pendingSwitch) return;
    setWorld(pendingSwitch);
    setPendingSwitch(null);
  };

  const tabs = [
    { key: "taller", label: "Biblioteca" },
    { key: "co-crear", label: "Crear skill" },
  ] as const;

  const tablist = (
    <div
      role="tablist"
      aria-label="Vistas de la biblioteca de herramientas"
      className="inline-flex gap-1 rounded-lg border border-edge bg-surface-raised p-1"
    >
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={view === tab.key}
          onClick={() => setView(tab.key)}
          className={
            view === tab.key
              ? "rounded-md bg-action px-4 py-1.5 text-small text-action-text transition-colors"
              : "rounded-md px-4 py-1.5 text-small text-muted transition-colors hover:bg-surface-hover hover:text-primary"
          }
        >
          {tab.label}
        </button>
      ))}
    </div>
  );

  return (
    <div className="flex min-h-screen flex-col bg-surface">
      {view === "co-crear" ? (
        <EditorLayout
          header={
            <ToolWorkshopHeader
              subtitle="Co-creá una skill conversando con el Co-creador de skills, una pregunta por vez."
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
        <EditorLayout
          header={
            <ToolWorkshopHeader
              subtitle="Explorá y activá skills publicadas por mundo."
              tablist={tablist}
            />
          }
          sidebar={
            <TallerExplorerSidebar
              lens={lens}
              onLensChange={setLens}
              world={world}
              worlds={worlds}
              activeTaller={activeTaller}
              onWorldChange={setWorld}
              onTallerChange={setCurrentTaller}
              onRequestCreateWorld={() => setCreatingWorld(true)}
              status={status}
              statusError={statusError}
              onStatusRetry={() => void loadStatus()}
              selected={selected}
              onSelect={setSelected}
              onActivate={(skillId, version) =>
                void handleActivate(skillId, version)
              }
              onAdaptar={(item) => void handleAdaptar(item)}
              busy={busy}
              compareSelection={compareSelection}
              onCompareToggle={handleComparar}
              onGoToCoCrear={handleGoToCoCrear}
            />
          }
          rightPanel={
            <MethodologyStatePanel
              selected={selected}
              status={status}
              lens={lens}
              world={world}
              activeTaller={activeTaller}
              busy={busy}
              onSelect={setSelected}
              onActivate={(skillId, version) =>
                void handleActivate(skillId, version)
              }
              onToggleCompanion={(skillId, version, on) =>
                void handleToggleCompanion(skillId, version, on)
              }
              latencyNoticeWorld={latencyNoticeWorld}
              onAdaptar={(item) => void handleAdaptar(item)}
              onComparar={handleComparar}
              onExportar={(item) => void handleExportar(item)}
              compareSelection={compareSelection}
              onCompareClear={() => setCompareSelection([])}
            />
          }
        >
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
            <MethodologyDetailView selected={selected} />
          )}
        </EditorLayout>
      )}

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