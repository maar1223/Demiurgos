import { useState } from "react";
import type {
  MethodologyCompanion,
  PublishedMethodology,
} from "@/api/types";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import type { GroupedSkills } from "@/lib/tallerStates";
import { isTransversalSkill } from "@/lib/tallerStates";
import {
  AXIS_TERM_KEYS,
  chatChip,
  scopeChip,
} from "@/lib/vocabularyAxes";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import type { MessageKey } from "@/i18n/messages";

interface TallerTreeProps {
  groups: GroupedSkills;
  /** Active Taller SHORT KEY (Herramientas | Mundo | Ideas) — drives the
   *  transversal chip (scope axis). */
  activeTaller: string;
  /** Companions of the current world (status-derived): a row whose skill is
   *  in this list renders the read-only "En el chat" chip (S1). */
  companions?: MethodologyCompanion[];
  /** Optional sidebar selection contract (SC-SB-2.1): when provided, rows
   *  become clickable and report the clicked `skill_id`/`version`. */
  onSelect?: (skillId: string, version: string) => void;
  /** One-click chat update (drift affordance): fired with the row's version
   *  when the chat still pins an older published version of that skill. */
  onUpdateCompanion?: (skillId: string, version: string) => void;
  /** Currently selected row — highlighted when it matches (SC-SB-2.1). */
  selected?: { skill_id: string; version: string } | null;
}

/** One collapsible group. */
interface GroupDef {
  key: keyof GroupedSkills;
  labelKey: MessageKey;
}

/** Group order (S1): the explorer answers "what can the chat use?" first.
 *  Group labels are byte-frozen (spec R7). */
const GROUP_ORDER: GroupDef[] = [
  { key: "enChat", labelKey: "tallerTree.group.enChat" },
  { key: "fueraDelChat", labelKey: "tallerTree.group.fueraDelChat" },
  { key: "sinTaller", labelKey: "tallerTree.group.sinTaller" },
];

/** One attributed row chip (spec R1): the registry term plus its axis
 *  attribution, surfaced as a `data-axis` marker for tests and assistive
 *  tooling. Chat availability + scope only. */
function AxisBadge({ chip }: { chip: ReturnType<typeof chatChip> }) {
  const { t } = useAppLanguage();
  return (
    <span data-axis={chip.axis} className="inline-flex">
      <Badge variant={chip.variant}>{t(AXIS_TERM_KEYS[chip.term])}</Badge>
    </span>
  );
}

interface SkillRowProps {
  skill: PublishedMethodology;
  activeTaller: string;
  /** Read-only chat marker (S1): true when this skill is a companion of the
   *  current world. */
  isCompanion: boolean;
  /** Version the world's chat currently pins, when the skill is a companion. */
  companionVersion?: string | null;
  onSelect?: (skillId: string, version: string) => void;
  onUpdateCompanion?: (skillId: string, version: string) => void;
  selected?: { skill_id: string; version: string } | null;
}

function SkillRow({
  skill,
  activeTaller,
  isCompanion,
  companionVersion,
  onSelect,
  onUpdateCompanion,
  selected,
}: SkillRowProps) {
  const { t } = useAppLanguage();
  const chatIsBehind =
    isCompanion && !!companionVersion && companionVersion !== skill.version;
  /** Selection highlight is skill-level (REQ-TRE-12): a version picked in the
   *  right-panel "Versiones" block highlights this skill's single explorer row
   *  even when it is not the rendered representative. */
  const isSelected = selected?.skill_id === skill.skill_id;
  const transversal = isTransversalSkill(skill, activeTaller);
  return (
    <li
      onClick={() => onSelect?.(skill.skill_id, skill.version)}
      className={[
        "flex flex-wrap items-start justify-between gap-x-4 gap-y-2 rounded-lg border p-3 transition-colors",
        onSelect ? "cursor-pointer" : "",
        isSelected
          ? "border-action bg-action/10 ring-1 ring-action/40"
          : "border-edge/20 bg-surface-raised/40 hover:border-edge/50 hover:bg-surface-raised/70",
      ].join(" ")}
    >
      <button
        type="button"
        aria-pressed={isSelected}
        onClick={(event) => {
          // The whole row card is clickable; stop the bubbling double-select.
          event.stopPropagation();
          onSelect?.(skill.skill_id, skill.version);
        }}
        className="min-w-[9rem] flex-1 rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50"
      >
        <p className="break-words font-medium text-primary">{skill.name}</p>
        <p className="break-words text-small text-muted">
          {skill.skill_id}@{skill.version}
        </p>
      </button>
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        {isCompanion && <AxisBadge chip={chatChip()} />}
        {transversal && <AxisBadge chip={scopeChip()} />}
        {chatIsBehind && (
          <Button
            variant="secondary"
            size="sm"
            title={t("tallerTree.chatUpdateTitle", {
              pinned: companionVersion ?? "",
              latest: skill.version,
            })}
            onClick={(event) => {
              // Rows are selection-only; this affordance must never also
              // select the skill.
              event.stopPropagation();
              onUpdateCompanion?.(skill.skill_id, skill.version);
            }}
          >
            {t("tallerTree.chatUpdate")}
          </Button>
        )}
      </div>
    </li>
  );
}

/**
 * Contextual tree of published methodologies for the active Taller (spec
 * REQ-TRE-3/4/6): groups by chat availability (S1/S2) and shows each row's
 * attributed chat/scope chips. Rows are selection + information only — the
 * chat toggle and every other action live in the right MethodologyStatePanel.
 */
export function TallerTree({
  groups,
  activeTaller,
  companions,
  onSelect,
  onUpdateCompanion,
  selected,
}: TallerTreeProps) {
  const { t } = useAppLanguage();
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(GROUP_ORDER.map((group) => [group.key, true])),
  );
  const chatSkillIds = new Set((companions ?? []).map((entry) => entry.skill_id));
  const companionVersionBySkill = new Map(
    (companions ?? []).map((entry) => [entry.skill_id, entry.version]),
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
                {t(group.labelKey)}
              </button>
            </h3>
            {isOpen && (
              <ul className="mt-3 space-y-3">
                {skills.map((skill) => (
                  <SkillRow
                    key={skill.skill_id}
                    skill={skill}
                    activeTaller={activeTaller}
                    isCompanion={chatSkillIds.has(skill.skill_id)}
                    companionVersion={
                      companionVersionBySkill.get(skill.skill_id) ?? null
                    }
                    onSelect={onSelect}
                    onUpdateCompanion={onUpdateCompanion}
                    selected={selected}
                  />
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}
