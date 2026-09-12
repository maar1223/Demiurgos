import { useState } from "react";
import type {
  MethodologyActivation,
  MethodologyCompanion,
  PublishedMethodology,
} from "@/api/types";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Tooltip } from "@/components/atoms/Tooltip";
import type { GroupedSkills, SkillState } from "@/lib/tallerStates";
import {
  activationChip,
  companionChip,
  conflictExplanation,
} from "@/lib/vocabularyAxes";

interface TallerTreeProps {
  groups: GroupedSkills;
  world: string | undefined;
  /** Active Taller SHORT KEY (Herramientas | Mundo | Ideas) — used for the
   *  blocked-skill conflict copy (spec REQ-TRE-6 S1). */
  activeTaller: string;
  /** Current activation for the selected world — drives the version-aware
   *  "Activada"/"Activa en {world}" state (REQ-TRE-7: one active version per
   *  world) and the sin-taller bucket badges. */
  active?: MethodologyActivation;
  /** Companions of the current world (status-derived, R-UI): rows whose
   *  skill@version is ON render a read-only "Método en chat" badge. */
  companions?: MethodologyCompanion[];
  onActivate: (skillId: string, version: string) => void;
  busy: boolean;
  /** Optional sidebar selection contract (SC-SB-2.1): when provided, rows
   *  become clickable and report the clicked `skill_id`/`version`. */
  onSelect?: (skillId: string, version: string) => void;
  /** Currently selected row — highlighted when it matches (SC-SB-2.1). */
  selected?: { skill_id: string; version: string } | null;
}

/** One collapsible group. `state` is the row badge state for every skill in
 *  the group; `"sin-taller"` rows resolve per-row (activa/inactiva by the
 *  world activation, spec REQ-TRE-5). */
interface GroupDef {
  key: keyof GroupedSkills;
  label: string;
  state: SkillState | "sin-taller";
}

/** TW3 group order (spec REQ-TRE-3) + the separate "Sin taller" bucket
 *  (REQ-TRE-1 S3). The 5th "Bloqueadas" group is Author-approved Option B.
 *  Group labels are byte-frozen (spec R7) — they carry the scope/conflict
 *  vocabulary at group level. */
const GROUP_ORDER: GroupDef[] = [
  { key: "activas", label: "En uso · funciona solo en este taller", state: "activa" },
  {
    key: "transversalesActivas",
    label: "En uso · funciona también en otros talleres",
    state: "transversal-activa",
  },
  { key: "inactivas", label: "Apagada · funciona solo en este taller", state: "inactiva" },
  {
    key: "transversalesInactivas",
    label: "Apagada · funciona también en otros talleres",
    state: "transversal-inactiva",
  },
  { key: "bloqueadas", label: "En conflicto · su taller de origen ya tiene una activa", state: "bloqueada" },
  { key: "sinTaller", label: "Sin taller", state: "sin-taller" },
];

/** One attributed row chip (spec R1): the registry term plus its axis
 *  attribution, surfaced as a `data-axis` marker for tests and assistive
 *  tooling. Axes 1+2 only — scope/conflict live in tooltips/panel (R3). */
function AxisBadge({ chip }: { chip: ReturnType<typeof activationChip> }) {
  return (
    <span data-axis={chip.axis} className="inline-flex">
      <Badge variant={chip.variant}>{chip.term}</Badge>
    </span>
  );
}

interface SkillRowProps {
  skill: PublishedMethodology;
  state: SkillState;
  world: string | undefined;
  activeTaller: string;
  isActive: boolean;
  /** True when the world has an activation for the displayed flow — the
   *  no-activation slot renders a neutral placeholder, never "Inactiva"
   *  (spec R4). */
  hasActivation: boolean;
  /** Read-only companion marker (R-UI): true when this row's skill@version
   *  is an active companion in the current world. */
  isCompanion: boolean;
  busy: boolean;
  onActivate: (skillId: string, version: string) => void;
  onSelect?: (skillId: string, version: string) => void;
  selected?: { skill_id: string; version: string } | null;
}

function SkillRow({
  skill,
  state,
  world,
  activeTaller,
  isActive,
  hasActivation,
  isCompanion,
  busy,
  onActivate,
  onSelect,
  selected,
}: SkillRowProps) {
  const isSelected =
    selected?.skill_id === skill.skill_id && selected?.version === skill.version;
  const slotChip = activationChip({ state, hasActivation });
  const companion = isCompanion ? companionChip() : null;
  return (
    <li
      className={[
        "flex items-center justify-between gap-4 rounded-lg border border-edge/20 bg-surface-raised/40 p-4 transition-colors",
        isSelected ? "border-action/50 bg-action/5" : "",
      ].join(" ")}
    >
      <button
        type="button"
        aria-pressed={isSelected}
        onClick={() => onSelect?.(skill.skill_id, skill.version)}
        className="min-w-0 flex-1 rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50"
      >
        <p className="font-medium text-primary">{skill.name}</p>
        <p className="text-small text-muted">
          {skill.skill_id}@{skill.version}
          {isActive && world && (
            <span className="ml-2 text-action">• Activa en {world}</span>
          )}
        </p>
      </button>
      <div className="flex shrink-0 items-center gap-2">
        <AxisBadge chip={slotChip} />
        {companion && <AxisBadge chip={companion} />}
        {state === "bloqueada" && (
          <Tooltip
            id={`conflict-${skill.skill_id}@${skill.version}`}
            content={conflictExplanation(activeTaller, skill.taller)}
          >
            <Icon
              name="error"
              size={16}
              className="cursor-help text-status-error"
            />
          </Tooltip>
        )}
        {state === "bloqueada" ? (
          <Button
            variant="secondary"
            size="sm"
            disabled
            title="Adaptación disponible en fase futura"
          >
            Adaptar
          </Button>
        ) : (
          <Button
            variant={isActive ? "secondary" : "primary"}
            size="sm"
            disabled={!world || isActive || busy}
            onClick={() => onActivate(skill.skill_id, skill.version)}
          >
            {isActive ? "Activada" : world ? "Activar" : "Sin mundo"}
          </Button>
        )}
      </div>
    </li>
  );
}

/**
 * Contextual tree of published methodologies for the active Taller (spec
 * REQ-TRE-3/4/6): five collapsible groups in TW3 order plus the "Sin taller"
 * bucket (REQ-TRE-1 S3). Empty groups are hidden (REQ-TRE-3 S3). Each row
 * shows the name, `skill_id@version`, attributed axis-1/2 chips (REQ-TRE-4,
 * axis-binding-ui R1) and the world-gated Activar/Activada/Sin mundo button;
 * blocked rows show the conflict copy in a row tooltip (R3) and a disabled
 * Adaptar action (REQ-TRE-6 S2).
 */
export function TallerTree({
  groups,
  world,
  activeTaller,
  active,
  companions,
  onActivate,
  busy,
  onSelect,
  selected,
}: TallerTreeProps) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(GROUP_ORDER.map((group) => [group.key, true])),
  );

  const toggle = (key: keyof GroupedSkills) => {
    setExpanded((prev) => ({ ...prev, [key]: !(prev[key] ?? true) }));
  };

  return (
    <div className="space-y-5">
      {GROUP_ORDER.map((group) => {
        const skills = groups[group.key];
        if (skills.length === 0) return null;
        const isOpen = expanded[group.key] ?? true;
        return (
          <section key={group.key}>
            <h3 className="font-heading text-small font-semibold text-primary">
              <button
                type="button"
                onClick={() => toggle(group.key)}
                aria-expanded={isOpen}
                className="flex items-center gap-1.5 rounded px-1 py-0.5 transition-colors hover:bg-surface-hover"
              >
                <Icon
                  name={isOpen ? "chevron-down" : "chevron-right"}
                  size={14}
                  className="shrink-0 text-muted"
                />
                {group.label}
              </button>
            </h3>
            {isOpen && (
              <ul className="mt-3 space-y-3">
                {skills.map((skill) => {
                  const isActive =
                    active?.skill_id === skill.skill_id &&
                    active?.version === skill.version;
                  const isCompanion =
                    companions?.some(
                      (companion) =>
                        companion.skill_id === skill.skill_id &&
                        companion.version === skill.version,
                    ) ?? false;
                  const rowState =
                    group.state === "sin-taller"
                      ? isActive
                        ? "activa"
                        : "inactiva"
                      : group.state;
                  return (
                    <SkillRow
                      key={`${skill.skill_id}@${skill.version}`}
                      skill={skill}
                      state={rowState}
                      world={world}
                      activeTaller={activeTaller}
                      isActive={isActive}
                      hasActivation={active != null}
                      isCompanion={isCompanion}
                      busy={busy}
                      onActivate={onActivate}
                      onSelect={onSelect}
                      selected={selected}
                    />
                  );
                })}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}