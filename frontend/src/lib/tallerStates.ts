import type { MethodologyCompanion, PublishedMethodology } from "@/api/types";
import { isOperationalTaller } from "@/lib/constants";

/** Skills of the active Taller (plus its transversals) bucketed by chat
 *  availability. Activation is not a library state anymore (S1/S2): the only
 *  per-skill state the explorer shows is whether the skill is in the chat. */
export interface GroupedSkills {
  enChat: PublishedMethodology[];
  fueraDelChat: PublishedMethodology[];
  sinTaller: PublishedMethodology[];
}

/** Numeric, specificity-aware version ordering (REQ-TRE-11): dot-separated
 *  segments compared segment-wise up to the longer length, missing segments
 *  treated as 0. Ordering is numeric, never lexicographic (`"1.10" > "1.9"`),
 *  and a numeric tie is broken by segment count so `"1.2.0" > "1.2"`. */
export function compareVersions(a: string, b: string): number {
  const aSegments = a.split(".");
  const bSegments = b.split(".");
  const length = Math.max(aSegments.length, bSegments.length);
  for (let i = 0; i < length; i += 1) {
    const aValue = parseInt(aSegments[i] ?? "0", 10) || 0;
    const bValue = parseInt(bSegments[i] ?? "0", 10) || 0;
    if (aValue !== bValue) return aValue - bValue;
  }
  return aSegments.length - bSegments.length;
}

/** Collapses `published` (one record per skill@version) to ONE representative
 *  record per `skill_id` (REQ-TRE-9/10): the latest version per REQ-TRE-11.
 *  The representative's own `taller`/`talleres_compatibles` drive the
 *  routing below. */
function dedupeBySkill(
  published: PublishedMethodology[],
): PublishedMethodology[] {
  const bySkill = new Map<string, PublishedMethodology>();
  for (const skill of published) {
    const current = bySkill.get(skill.skill_id);
    if (!current || compareVersions(skill.version, current.version) > 0) {
      bySkill.set(skill.skill_id, skill);
    }
  }
  return [...bySkill.values()];
}

/** A skill that belongs to another operational Taller but is declared
 *  compatible with the active one (scope axis, rendered as a chip). */
export function isTransversalSkill(
  skill: PublishedMethodology,
  activeTaller: string,
): boolean {
  if (skill.taller === activeTaller) return false;
  if (!isOperationalTaller(skill.taller)) return false;
  return (skill.talleres_compatibles ?? []).includes(activeTaller);
}

/** True when the skill is part of the active Taller's context: its own
 *  Taller or a declared transversal. Everything else stays hidden (TW2). */
function isInActiveContext(
  skill: PublishedMethodology,
  activeTaller: string,
): boolean {
  return skill.taller === activeTaller || isTransversalSkill(skill, activeTaller);
}

const byName = (a: PublishedMethodology, b: PublishedMethodology): number =>
  a.name.localeCompare(b.name);

/** Routes every visible published skill into the chat-availability buckets
 *  (S1) and sorts each group alphabetically by name. `companions` is the
 *  selected world's chat list; chat membership is skill-level (a skill is in
 *  the chat when any of its versions is a companion). */
export function groupSkillsByChat(
  published: PublishedMethodology[],
  activeTaller: string,
  companions: MethodologyCompanion[],
): GroupedSkills {
  const chatSkillIds = new Set(companions.map((entry) => entry.skill_id));
  const groups: GroupedSkills = {
    enChat: [],
    fueraDelChat: [],
    sinTaller: [],
  };

  for (const skill of dedupeBySkill(published)) {
    if (!isOperationalTaller(skill.taller)) {
      groups.sinTaller.push(skill);
      continue;
    }
    if (!isInActiveContext(skill, activeTaller)) continue;
    if (chatSkillIds.has(skill.skill_id)) {
      groups.enChat.push(skill);
    } else {
      groups.fueraDelChat.push(skill);
    }
  }

  return {
    enChat: groups.enChat.sort(byName),
    fueraDelChat: groups.fueraDelChat.sort(byName),
    sinTaller: groups.sinTaller.sort(byName),
  };
}
