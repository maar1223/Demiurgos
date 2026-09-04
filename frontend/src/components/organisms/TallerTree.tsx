import { useState } from "react";
import type {
  MethodologyActivation,
  PublishedMethodology,
} from "@/api/types";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { CORE_TALLER_LABELS, type CoreTaller } from "@/lib/constants";
import type { GroupedSkills, SkillState } from "@/lib/tallerStates";

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
 *  (REQ-TRE-1 S3). The 5th "Bloqueadas" group is Author-approved Option B. */
const GROUP_ORDER: GroupDef[] = [
  { key: "activas", label: "Activas del Taller", state: "activa" },
  {
    key: "transversalesActivas",
    label: "Transversales activas",
    state: "transversal-activa",
  },
  { key: "inactivas", label: "Inactivas del Taller", state: "inactiva" },
  {
    key: "transversalesInactivas",
    label: "Transversales inactivas",
    state: "transversal-inactiva",
  },
  { key: "bloqueadas", label: "Bloqueadas", state: "bloqueada" },
  { key: "sinTaller", label: "Sin taller", state: "sin-taller" },
];

const BADGE_META: Record<
  SkillState,
  { label: string; variant: "default" | "success" | "error" | "info" }
> = {
  activa: { label: "Activa", variant: "success" },
  "transversal-activa": { label: "Transversal", variant: "info" },
  inactiva: { label: "Inactiva", variant: "default" },
  "transversal-inactiva": { label: "Transversal", variant: "info" },
  bloqueada: { label: "Bloqueada", variant: "error" },
};

/** Display label for a Taller key (short key → CORE_TALLER_LABELS label,
 *  raw value fallback for unknown keys). */
function tallerLabel(taller: string | null | undefined): string {
  if (taller == null) return "";
  return CORE_TALLER_LABELS[taller as CoreTaller] ?? taller;
}

/** Exact conflict copy from spec REQ-TRE-6 S1, taller names interpolated via
 *  CORE_TALLER_LABELS. */
function blockedExplanation(
  activeTaller: string,
  skillTaller: string | null | undefined,
): string {
  return `This skill is a transversal of ${tallerLabel(activeTaller)} but its primary taller (${tallerLabel(skillTaller)}) already has an active skill in this world. Adapt the skill to resolve the conflict or activate it in a different world.`;
}

interface SkillRowProps {
  skill: PublishedMethodology;
  state: SkillState;
  world: string | undefined;
  activeTaller: string;
  isActive: boolean;
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
  busy,
  onActivate,
  onSelect,
  selected,
}: SkillRowProps) {
  const badge = BADGE_META[state];
  const isSelected =
    selected?.skill_id === skill.skill_id && selected?.version === skill.version;
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
        {state === "bloqueada" && (
          <p className="mt-2 max-w-prose text-small text-status-error">
            {blockedExplanation(activeTaller, skill.taller)}
          </p>
        )}
      </button>
      <div className="flex shrink-0 items-center gap-2">
        <Badge variant={badge.variant}>{badge.label}</Badge>
        {state === "bloqueada" ? (
          <Button
            variant="secondary"
            size="sm"
            disabled
            title="Adaptation available in future phase"
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
 * shows the name, `skill_id@version`, a state Badge (REQ-TRE-4) and the
 * world-gated Activar/Activada/Sin mundo button; blocked rows show the
 * conflict copy and a disabled Adaptar action (REQ-TRE-6).
 */
export function TallerTree({
  groups,
  world,
  activeTaller,
  active,
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