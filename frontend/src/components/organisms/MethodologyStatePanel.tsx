import { useState } from "react";
import type { MethodologyInventoryItem, MethodologyStatus } from "@/api/types";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Switch } from "@/components/atoms/Switch";
import { Tooltip } from "@/components/atoms/Tooltip";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ProvenanceBadge } from "@/components/organisms/CoCreation/ProvenanceBadge";
import { MethodologyComparePanel } from "@/components/molecules/MethodologyComparePanel";
import type { Lens } from "@/components/organisms/LensToggle";
import { GLOBAL_ASSISTANT_CONTEXT } from "@/hooks/useAIAssistantSessions";
import { computeSkillState } from "@/lib/tallerStates";
import {
  AXIS_SCOPE,
  AXIS_TERMS,
  conflictExplanation,
} from "@/lib/vocabularyAxes";

/** Registry scope term (axis-3) — reverse lookup so the panel never hardcodes
 *  axis vocabulary (spec R3: scope/conflict terms render only from the
 *  registry). */
const SCOPE_TERM =
  Object.entries(AXIS_TERMS).find(([, axis]) => axis === AXIS_SCOPE)?.[0] ?? "";

interface MethodologySelection {
  skill_id: string;
  version: string;
}

interface MethodologyStatePanelProps {
  /** Page-level selection (REQ-SB-5). Null renders the empty state. */
  selected: MethodologySelection | null;
  /** Library status from `getMethodologyStatus()` — versions/activations are
   *  derived client-side by filtering on `skill_id` (no per-skill endpoint). */
  status: MethodologyStatus | null;
  /** Lens-scoped action set (SC-SB-4.1/4.2). */
  lens: Lens;
  /** World for activation gating (mi-mundo): Activar is disabled when null. */
  world?: string;
  /** Active Taller SHORT KEY (Herramientas | Mundo | Ideas) — the browsing
   *  context shared with the sidebar tree. Drives the "Alcance de taller" /
   *  "Conflicto" panel blocks (axis-binding-ui R3, REQ-TRE-6). */
  activeTaller?: string;
  onActivate: (skillId: string, version: string) => void;
  /** World-scoped deactivation (mi-mundo): clears the world's activation slot
   *  for the selected version (the active state is shown by the Versiones
   *  block and the sidebar chip, so the action slot carries this instead of
   *  a disabled "Activada" button). */
  onDeactivate: (skillId: string, version: string) => void;
  onAdaptar: (item: MethodologyInventoryItem) => void;
  onComparar: (item: MethodologyInventoryItem) => void;
  /** Catalogo "Exportar" — resolves the `.zip` download; when it rejects the
   *  panel surfaces the inline export error (REQ-IMP-1: feedback moved from
   *  the catalog rows to this panel). */
  onExportar: (item: MethodologyInventoryItem) => Promise<void> | void;
  /** Companion toggle, page-owned (mirrors onActivate; refetches status).
   *  `on` true activates the selected version, false deactivates the skill. */
  onToggleCompanion?: (skillId: string, version: string, on: boolean) => void;
  /** World whose first-activation latency notice is active (R-UI notice). */
  latencyNoticeWorld?: string | null;
  /** Request in flight — disables the chip and the OFF buttons. */
  busy?: boolean;
  /** Clickable Versiones (UL-3): fired when a version row is clicked. */
  onSelect?: (selection: MethodologySelection) => void;
  /** Controlled compare selection (UL-4): when exactly two items are
   *  compared, the compare panel renders below the actions block. */
  compareSelection?: MethodologyInventoryItem[];
  onCompareClear?: () => void;
}

/**
 * Right state/actions panel for the "Taller" EditorLayout (REQ-SB-4).
 *
 * Renders versions/activations derived from `getMethodologyStatus()` filtered
 * by `skill_id`, provenance via `ProvenanceBadge(parentSkillId/parentVersion)`
 * (SC-SB-4.3), talleres compatibles, etiquetas, and lens-appropriate actions:
 * mi-mundo → Activar/Desactivar + Adaptar (SC-SB-4.1); catalogo → Adaptar +
 * Comparar + Exportar with NO Activar (SC-SB-4.2). Null selection renders an
 * empty state (SC-SB-4.4).
 */
export function MethodologyStatePanel({
  selected,
  status,
  lens,
  world,
  activeTaller,
  onActivate,
  onDeactivate,
  onAdaptar,
  onComparar,
  onExportar,
  onSelect,
  onToggleCompanion,
  latencyNoticeWorld,
  busy = false,
  compareSelection,
  onCompareClear,
}: MethodologyStatePanelProps) {
  /** Export failure feedback (REQ-IMP-1): the right panel owns the inline
   *  alert the catalog rows used to render. */
  const [exportError, setExportError] = useState<string | null>(null);

  if (!selected) {
    return (
      <EmptyState
        icon="empty"
        message="Selecciona una metodología para ver su estado y sus acciones."
      />
    );
  }

  const published = status?.published ?? [];
  const activations = status?.activations ?? {};
  const entry = published.find(
    (item) =>
      item.skill_id === selected.skill_id && item.version === selected.version,
  );
  /** Every published version of this skill (SC-SB-4: "versions/activations
   *  filtered by skill_id"). */
  const versions = published.filter((item) => item.skill_id === selected.skill_id);
  /** Worlds where one of this skill's versions is active. */
  const activationsForSkill = Object.values(activations).filter(
    (activation) => activation.skill_id === selected.skill_id,
  );

  /** Action payload: the selected published entry as an inventory item.
   *  `clasificacion`/`trust_attributes` default when the published record
   *  omits them. */
  const item: MethodologyInventoryItem = entry
    ? {
        ...entry,
        clasificacion: entry.clasificacion ?? null,
        trust_attributes: entry.trust_attributes ?? [],
      }
    : {
        skill_id: selected.skill_id,
        version: selected.version,
        name: selected.skill_id,
        description: "",
        digest: "",
        published_at: "",
      };

  const talleresCompatibles = entry?.talleres_compatibles ?? [];
  const etiquetas = entry?.etiquetas ?? [];
  const isMiMundo = lens === "mi-mundo";
  /** Companions of the current world (status-derived; absent key → none).
   *  The selected version is ON when it appears in this list. */
  const companions = world ? status?.companions?.[world] ?? [] : [];
  const isCompanion = companions.some(
    (companion) =>
      companion.skill_id === selected.skill_id &&
      companion.version === selected.version,
  );
  /** ideas-global is the assistant's null-mundo context, NOT a workshop
   *  world: it never gets companion chips and its slot Activar stays disabled
   *  (the companion routes 404 it). */
  const isIdeasGlobal = world === GLOBAL_ASSISTANT_CONTEXT;

  /** The selected version is already the current world activation — the
   *  mi-mundo action slot swaps Activar for the deactivate affordance (the
   *  Versiones block and the sidebar chip already show the active state;
   *  REQ-TRE-7: one active version per world). */
  const isWorldActive =
    world != null &&
    activations[world]?.skill_id === selected.skill_id &&
    activations[world]?.version === selected.version;

  /** Wraps the download so a rejection surfaces the inline alert instead of
   *  failing silently (REQ-IMP-1). */
  const handleExport = async (item: MethodologyInventoryItem) => {
    setExportError(null);
    try {
      await onExportar(item);
    } catch {
      setExportError("No se pudo exportar la metodología.");
    }
  };

  /** Axis-surface derivations (axis-binding-ui R3, REQ-TRE-6): the selected
   *  skill's scope and conflict state, driven by the same activeTaller/world
   *  context the sidebar tree uses. The blocked rule reuses
   *  `computeSkillState` (tallerStates — the single state-derivation source). */
  const skillState =
    entry != null && activeTaller != null
      ? computeSkillState(entry, activeTaller, world, activations, published)
      : null;
  const isBlocked = skillState === "bloqueada";
  const isTransversal =
    entry != null &&
    activeTaller != null &&
    entry.taller !== activeTaller &&
    (entry.talleres_compatibles ?? []).includes(activeTaller);

  return (
    <section
      aria-label="Estado y acciones de la metodología"
      className="space-y-6"
    >
      {/* Versions + world activations (SC-SB-4) */}
      <div className="rounded-lg border border-edge bg-surface-raised p-4">
        <h3 className="font-heading text-small font-semibold text-primary">
          Versiones
        </h3>
        {versions.length === 0 ? (
          <p className="mt-2 text-small text-muted">
            No hay versiones publicadas de {selected.skill_id}.
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {versions.map((version) => {
              const isCurrent = version.version === selected.version;
              const activeWorlds = activationsForSkill
                .filter(
                  (activation) => activation.version === version.version,
                )
                .map((activation) => activation.world);
              /** Model-level flow attribution for the current world's slot
               *  (axis-binding-ui R6): `flow_type` labels the slot display —
               *  never per-flow display copy. */
              const worldFlowType =
                world != null && activations[world]?.version === version.version
                  ? activations[world]?.flow_type
                  : undefined;
              return (
                <li key={version.version}>
                  <button
                    type="button"
                    onClick={() =>
                      onSelect?.({
                        skill_id: selected.skill_id,
                        version: version.version,
                      })
                    }
                    className="flex w-full cursor-pointer flex-wrap items-center gap-2 rounded-md px-1 py-0.5 text-left text-small transition-colors hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50"
                  >
                    <span className="font-medium text-primary">
                      v{version.version}
                    </span>
                    {isCurrent && (
                      <Badge variant="info">Seleccionada</Badge>
                    )}
                    {activeWorlds.length > 0 && (
                      <span className="text-action" data-flow-type={worldFlowType}>
                        Activa en {activeWorlds.join(", ")}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Provenance (SC-SB-4.3) */}
      <div className="rounded-lg border border-edge bg-surface-raised p-4">
        <h3 className="font-heading text-small font-semibold text-primary">
          Origen
        </h3>
        <div className="mt-2">
          <ProvenanceBadge
            parentSkillId={entry?.parent_skill_id}
            parentVersion={entry?.parent_version}
          />
        </div>
        {!entry?.parent_skill_id && (
          <p className="mt-2 text-small text-muted">
            Skill raíz (no derivada de otra metodología).
          </p>
        )}
      </div>

      {/* Talleres compatibles */}
      {talleresCompatibles.length > 0 && (
        <div className="rounded-lg border border-edge bg-surface-raised p-4">
          <h3 className="font-heading text-small font-semibold text-primary">
            Talleres compatibles
          </h3>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {talleresCompatibles.map((taller) => (
              <Badge key={taller} variant="default">
                {taller}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Alcance de taller (axis-binding-ui R3): the registry scope term
       * renders ONLY in this panel block — never a primary badge. Shown when
       * the selected skill is a transversal of the active taller. */}
      {isTransversal && (
        <div className="rounded-lg border border-edge bg-surface-raised p-4">
          <h3 className="font-heading text-small font-semibold text-primary">
            Alcance de taller
          </h3>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <span data-axis={AXIS_SCOPE} className="inline-flex">
              <Badge variant="default">{SCOPE_TERM}</Badge>
            </span>
          </div>
        </div>
      )}

      {/* Conflicto (REQ-TRE-6 S1 + axis-binding-ui R3): the blocked skill's
       * conflict copy renders ONLY in this panel block and the row tooltip —
       * registry-sourced, verbatim, taller names interpolated. The Tooltip
       * mirrors the row (R5): aria-describedby + sr-only copy, so
       * keyboard-only Authors reach the same copy. */}
      {isBlocked && entry && activeTaller != null && (
        <div className="rounded-lg border border-edge bg-surface-raised p-4">
          <h3 className="font-heading text-small font-semibold text-primary">
            Conflicto
          </h3>
          <div className="mt-2 flex items-start gap-2">
            <Tooltip
              id={`conflicto-panel-${entry.skill_id}@${entry.version}`}
              content={conflictExplanation(activeTaller, entry.taller)}
            >
              <Icon
                name="error"
                size={16}
                className="cursor-help text-status-error"
              />
            </Tooltip>
            <p className="text-small text-muted">
              {conflictExplanation(activeTaller, entry.taller)}
            </p>
          </div>
        </div>
      )}

      {/* Etiquetas */}
      {etiquetas.length > 0 && (
        <div className="rounded-lg border border-edge bg-surface-raised p-4">
          <h3 className="font-heading text-small font-semibold text-primary">
            Etiquetas
          </h3>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {etiquetas.map((tag) => (
              <Badge key={tag} variant="info">
                {tag}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Lens-specific actions (SC-SB-4.1/4.2) */}
      <div className="rounded-lg border border-edge bg-surface-raised p-4">
        <h3 className="font-heading text-small font-semibold text-primary">
          Acciones
        </h3>
        <div className="mt-3 flex flex-wrap gap-2">
          {isMiMundo ? (
            <>
              {isWorldActive ? (
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!world || isIdeasGlobal || busy}
                  onClick={() => onDeactivate(selected.skill_id, selected.version)}
                  title="Quita esta versión de las nuevas sesiones del mundo seleccionado."
                >
                  Desactivar
                </Button>
              ) : (
                <Button
                  variant="primary"
                  size="sm"
                  disabled={!world || isIdeasGlobal || busy}
                  onClick={() => onActivate(selected.skill_id, selected.version)}
                  title="Activa esta versión para nuevas sesiones en el mundo seleccionado."
                >
                  Activar
                </Button>
              )}
              <Button
                variant="secondary"
                size="sm"
                onClick={() => onAdaptar(item)}
                title="Deriva una versión editable de esta publicación."
              >
                Adaptar
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => onAdaptar(item)}
                title="Deriva una versión editable de esta publicación."
              >
                Adaptar
              </Button>
              <Button variant="secondary" size="sm" onClick={() => onComparar(item)}>
                Comparar
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => void handleExport(item)}
              >
                Exportar
              </Button>
            </>
          )}
        </div>

        {exportError && (
          <p
            role="alert"
            className="mt-3 rounded-md border border-status-error/30 bg-status-error/10 px-3 py-2 text-xs text-status-error"
          >
            {exportError}
          </p>
        )}

        {/* Companion ON/OFF chips (R-UI): a world-scoped, multi-activation
         * control beside Activar — the single activation slot is never
         * labeled to the user. Only real workshop worlds get chips. */}
        {isMiMundo && !isIdeasGlobal && (
          <div className="mt-4 space-y-3 border-t border-edge pt-4">
            <div className="flex items-center justify-between gap-3">
              <span className="text-small font-medium text-primary">
                Metodología de chat en {world}
              </span>
              <Switch
                checked={isCompanion}
                disabled={!world || busy}
                aria-label={`Metodología de chat en ${world}`}
                onChange={(on) =>
                  onToggleCompanion?.(selected.skill_id, selected.version, on)
                }
              />
            </div>
            {companions.length > 0 && (
              <ul className="space-y-1.5">
                {companions.map((companion) => (
                  <li
                    key={`${companion.skill_id}@${companion.version}`}
                    className="flex items-center justify-between gap-2 text-small"
                  >
                    <span className="text-primary">
                      {companion.skill_id}@{companion.version}
                    </span>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={busy}
                      onClick={() =>
                        onToggleCompanion?.(
                          companion.skill_id,
                          companion.version,
                          false,
                        )
                      }
                    >
                      Apagar
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            {latencyNoticeWorld === world && (
              <p className="text-small text-muted">
                Las charlas de IA en este mundo pueden tardar un poco más
                mientras haya skills de metodología de chat activas.
              </p>
            )}
          </div>
        )}
      </div>

      {/* Compare panel (UL-4): rendered in the right panel area, below the
       *  actions block, when exactly two items are compared. The clear
       *  control moved here with the panel (REQ-LIB-7). */}
      {compareSelection && compareSelection.length === 2 && (
        <div className="space-y-2">
          <div className="flex justify-end">
            <Button variant="ghost" size="sm" onClick={onCompareClear}>
              Limpiar
            </Button>
          </div>
          <MethodologyComparePanel
            a={compareSelection[0]}
            b={compareSelection[1]}
          />
        </div>
      )}
    </section>
  );
}

export default MethodologyStatePanel;