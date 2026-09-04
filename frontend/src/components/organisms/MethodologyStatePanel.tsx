import type { MethodologyInventoryItem, MethodologyStatus } from "@/api/types";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ProvenanceBadge } from "@/components/organisms/CoCreation/ProvenanceBadge";
import type { Lens } from "@/components/organisms/LensToggle";

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
                <li
                  key={version.version}
                  className="flex flex-wrap items-center gap-2 text-small"
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
                disabled={!world}
                onClick={() => onActivate(selected.skill_id, selected.version)}
              >
                Activar
              </Button>
              <Button variant="secondary" size="sm" onClick={() => onAdaptar(item)}>
                Adaptar
              </Button>
            </>
          ) : (
            <>
              <Button variant="secondary" size="sm" onClick={() => onAdaptar(item)}>
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
      </div>
    </section>
  );
}

export default MethodologyStatePanel;