import type { MethodologyInventoryItem, MethodologyStatus } from "@/api/types";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Switch } from "@/components/atoms/Switch";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ProvenanceBadge } from "@/components/organisms/CoCreation/ProvenanceBadge";
import { MethodologyComparePanel } from "@/components/molecules/MethodologyComparePanel";
import type { Lens } from "@/components/organisms/LensToggle";
import { GLOBAL_ASSISTANT_CONTEXT } from "@/hooks/useAIAssistantSessions";

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
  onActivate: (skillId: string, version: string) => void;
  onAdaptar: (item: MethodologyInventoryItem) => void;
  onComparar: (item: MethodologyInventoryItem) => void;
  onExportar: (item: MethodologyInventoryItem) => void;
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
 * mi-mundo → Activar + Adaptar (SC-SB-4.1); catalogo → Adaptar + Comparar +
 * Exportar with NO Activar (SC-SB-4.2). Null selection renders an empty state
 * (SC-SB-4.4).
 */
export function MethodologyStatePanel({
  selected,
  status,
  lens,
  world,
  onActivate,
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
  if (!selected) {
    return (
      <EmptyState
        icon="empty"
        message="Seleccioná una metodología para ver su estado y sus acciones."
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
                      <span className="text-action">
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
              <Button
                variant="primary"
                size="sm"
                disabled={!world || isIdeasGlobal}
                onClick={() => onActivate(selected.skill_id, selected.version)}
                title="Activa esta versión para nuevas sesiones en el mundo seleccionado."
              >
                Activar
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => onAdaptar(item)}
                title="Derivá una versión editable de esta publicación."
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
                title="Derivá una versión editable de esta publicación."
              >
                Adaptar
              </Button>
              <Button variant="secondary" size="sm" onClick={() => onComparar(item)}>
                Comparar
              </Button>
              <Button variant="secondary" size="sm" onClick={() => onExportar(item)}>
                Exportar
              </Button>
            </>
          )}
        </div>

        {/* Companion ON/OFF chips (R-UI): a world-scoped, multi-activation
         * control beside Activar — the single activation slot is never
         * labeled to the user. Only real workshop worlds get chips. */}
        {isMiMundo && !isIdeasGlobal && (
          <div className="mt-4 space-y-3 border-t border-edge pt-4">
            <div className="flex items-center justify-between gap-3">
              <span className="text-small font-medium text-primary">
                Compañera en {world}
              </span>
              <Switch
                checked={isCompanion}
                disabled={!world || busy}
                aria-label={`Compañera en ${world}`}
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
                mientras haya skills compañeras activas.
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