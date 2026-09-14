import type {
  MethodologyInventoryItem,
  MethodologyStatus,
  WorldInfo,
} from "@/api/types";
import { TallerSelector } from "@/components/molecules/TallerSelector";
import { WorldSelector } from "@/components/molecules/WorldSelector";
import { GlobalMethodologyLibrary } from "@/components/organisms/GlobalMethodologyLibrary";
import { LensToggle, type Lens } from "@/components/organisms/LensToggle";
import { MethodologyLibrary } from "@/components/organisms/MethodologyLibrary";

/** Page-level methodology selection (REQ-SB-5): the `{ skill_id, version }`
 *  pair picked in the "Taller" explorer. Structural type — compatible with
 *  the same-named interfaces in ToolWorkshop / MethodologyDetailView /
 *  MethodologyStatePanel. */
export interface MethodologySelection {
  skill_id: string;
  version: string;
}

interface TallerExplorerSidebarProps {
  /** Active lens of the "Taller" tab (REQ-LEN-1). */
  lens: Lens;
  onLensChange: (lens: Lens) => void;
  // ── mi-mundo context (header block + tree) ──────────────────────────
  world?: string;
  worlds: WorldInfo[];
  activeTaller: string;
  onWorldChange: (world: string) => void;
  onTallerChange: (taller: string) => void;
  onRequestCreateWorld: () => void;
  /** Page-lifted library status (task 2.3); null while the first fetch is in
   *  flight. Shared with the right `MethodologyStatePanel`. */
  status: MethodologyStatus | null;
  statusError: string | null;
  onStatusRetry: () => void;
  // ── shared selection ────────────────────────────────────────────────
  /** Page-level selection; `null` clears it (filter contract SC-SB-2.3). */
  selected: MethodologySelection | null;
  onSelect: (sel: MethodologySelection | null) => void;
  // ── controlled compare selection (shared with the right panel) ──────
  compareSelection: MethodologyInventoryItem[];
  /** UL-5: empty-state CTA of the mi-mundo library — switches the page to
   *  the "Crear skill" tab. Forwarded to MethodologyLibrary. */
  onGoToCoCrear?: () => void;
}

/**
 * Left explorer sidebar of the "Taller" EditorLayout (SC-SB-1.1/1.2,
 * SC-LEN-1.7).
 *
 * Header block: TallerSelector + WorldSelector + LensToggle stacked — the
 * context controls sit adjacent to the explorer they scope, matching the
 * "Crear skill" sidebar pattern. Explorer: the mi-mundo `MethodologyLibrary`
 * (tree + client-side filter) or the read-only `GlobalMethodologyLibrary`
 * (inventory + InventoryFilterBar) depending on the lens.
 */
export function TallerExplorerSidebar({
  lens,
  onLensChange,
  world,
  worlds,
  activeTaller,
  onWorldChange,
  onTallerChange,
  onRequestCreateWorld,
  status,
  statusError,
  onStatusRetry,
  selected,
  onSelect,
  compareSelection,
  onGoToCoCrear,
}: TallerExplorerSidebarProps) {
  return (
    <div className="flex h-full flex-col">
      {/* Header block (SC-LEN-1.7): the lens toggle lives here, NOT as a
       *  standalone flowing row. Lens first — it decides which context
       *  controls apply — then the world it scopes and the taller below it.
       *  The toggle is self-labeling (its segments state the lens), so it
       *  carries no visible heading; `role="tablist"` + "Lente de la
       *  biblioteca" keep its accessible name (SB-1). The World/Taller
       *  selectors keep visible labels and are suppressed in the
       *  "catalogo-total" lens (UL-2) — only the lens toggle stays. */}
      <div className="space-y-3 border-b border-edge px-4 py-3">
        <LensToggle lens={lens} onChange={onLensChange} />
        {lens === "mi-mundo" && (
          <>
            <div className="space-y-1">
              <span className="text-xs font-medium text-muted">Mundo</span>
              <WorldSelector
                worlds={worlds}
                currentWorld={world}
                onWorldChange={onWorldChange}
                onRequestCreate={onRequestCreateWorld}
              />
            </div>
            <div className="space-y-1">
              <span className="text-xs font-medium text-muted">Taller</span>
              <TallerSelector activeTaller={activeTaller} onTallerChange={onTallerChange} />
            </div>
          </>
        )}
      </div>

      {/* Explorer per lens */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {lens === "mi-mundo" ? (
          <div className="space-y-4">
            {/* No-world prompt (SC-SB-5.3): informational only — it never
             * touches the page-level `selected` state. */}
            {!world && (
              <p className="text-small text-muted">
                {worlds.length > 0
                  ? "Elegí un mundo para poder activar versiones."
                  : "No hay mundos disponibles; podés ver publicaciones pero no activar."}
              </p>
            )}
            <MethodologyLibrary
              status={status}
              error={statusError}
              onRetry={onStatusRetry}
              world={world}
              activeTaller={activeTaller}
              selected={selected}
              onSelect={onSelect}
              onGoToCoCrear={onGoToCoCrear}
            />
          </div>
        ) : (
          <GlobalMethodologyLibrary
            onSelect={onSelect}
            compareSelection={compareSelection}
          />
        )}
      </div>
    </div>
  );
}