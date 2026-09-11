import type {
  MethodologyActivation,
  PublishedMethodology,
} from "@/api/types";
import { isOperationalTaller } from "@/lib/constants";

/** Derived state of a published methodology for a (activeTaller, world) pair
 *  (taller-selector-tree-states spec REQ-TRE-5). `"hidden"` means the skill
 *  is not part of the active Taller's context (TW2) and must not render.
 *  Sin-taller skills report `"activa"`/`"inactiva"` here and are routed to
 *  the separate "Sin taller" bucket by the caller based on their taller. */
export type SkillState =
  | "activa"
  | "transversal-activa"
  | "inactiva"
  | "transversal-inactiva"
  | "bloqueada";

/** Skills bucketed by derived state, each sorted alphabetically by name.
 *  `sinTaller` is a separate section (REQ-TRE-1 S3), never one of the
 *  operational groups. */
export interface GroupedSkills {
  activas: PublishedMethodology[];
  transversalesActivas: PublishedMethodology[];
  inactivas: PublishedMethodology[];
  transversalesInactivas: PublishedMethodology[];
  bloqueadas: PublishedMethodology[];
  sinTaller: PublishedMethodology[];
}

type Activations = Record<string, MethodologyActivation>;

/** True when the world's active skill belongs to a published methodology of
 *  the given primary taller — the blocked-rule lookup (REQ-TRE-5). */
export function publishedHasActiveInWorld(
  taller: string,
  world: string | undefined,
  activations: Activations,
  published: PublishedMethodology[],
): boolean {
  if (world == null) return false;
  const active = activations[world];
  if (!active) return false;
  return published.some(
    (s) => s.skill_id === active.skill_id && s.taller === taller,
  );
}

/** First-match-wins state derivation — exact design algorithm (design
 *  §State Derivation Algorithm, spec REQ-TRE-5 table):
 *  Activa → Transversal activa → Bloqueada → Inactiva → Transversal
 *  inactiva → hidden. */
export function computeSkillState(
  skill: PublishedMethodology,
  activeTaller: string,
  world: string | undefined,
  activations: Activations,
  published: PublishedMethodology[],
): SkillState | "hidden" {
  const compatibles = skill.talleres_compatibles ?? [];
  const isTransversal =
    skill.taller !== activeTaller && compatibles.includes(activeTaller);
  const activeInWorld =
    world != null && activations[world]?.skill_id === skill.skill_id;

  // Sin taller bucket — separate section, not part of the 4+1 groups
  // (caller routes to the sinTaller bucket based on the taller value).
  if (!isOperationalTaller(skill.taller)) {
    return activeInWorld ? "activa" : "inactiva";
  }

  // 1. Activa — own taller + active in world
  if (skill.taller === activeTaller && activeInWorld) return "activa";

  // 2. Transversal activa — other taller + compatible + active in world
  if (isTransversal && activeInWorld) return "transversal-activa";

  // 3. Bloqueada — transversal + NOT active + primary taller is another
  //    operational taller that already has an active skill in this world
  if (
    isTransversal &&
    !activeInWorld &&
    isOperationalTaller(skill.taller) &&
    skill.taller !== activeTaller &&
    publishedHasActiveInWorld(skill.taller, world, activations, published)
  ) {
    return "bloqueada";
  }

  // 4. Inactiva — own taller + not active
  if (skill.taller === activeTaller && !activeInWorld) return "inactiva";

  // 5. Transversal inactiva — transversal + not active + not blocked
  if (isTransversal && !activeInWorld) return "transversal-inactiva";

  // Hidden — not a transversal, not own taller (TW2: not this Taller's context)
  return "hidden";
}

const byName = (a: PublishedMethodology, b: PublishedMethodology): number =>
  a.name.localeCompare(b.name);

/** Routes every published skill into its state bucket (hidden skills are
 *  dropped) and sorts each group alphabetically by name (REQ-TRE-3 S2). */
export function groupSkillsByState(
  published: PublishedMethodology[],
  activeTaller: string,
  world: string | undefined,
  activations: Activations,
): GroupedSkills {
  const groups: GroupedSkills = {
    activas: [],
    transversalesActivas: [],
    inactivas: [],
    transversalesInactivas: [],
    bloqueadas: [],
    sinTaller: [],
  };

  for (const skill of published) {
    if (!isOperationalTaller(skill.taller)) {
      groups.sinTaller.push(skill);
      continue;
    }
    switch (
      computeSkillState(skill, activeTaller, world, activations, published)
    ) {
      case "activa":
        groups.activas.push(skill);
        break;
      case "transversal-activa":
        groups.transversalesActivas.push(skill);
        break;
      case "inactiva":
        groups.inactivas.push(skill);
        break;
      case "transversal-inactiva":
        groups.transversalesInactivas.push(skill);
        break;
      case "bloqueada":
        groups.bloqueadas.push(skill);
        break;
      case "hidden":
        break;
    }
  }

  return {
    activas: groups.activas.sort(byName),
    transversalesActivas: groups.transversalesActivas.sort(byName),
    inactivas: groups.inactivas.sort(byName),
    transversalesInactivas: groups.transversalesInactivas.sort(byName),
    bloqueadas: groups.bloqueadas.sort(byName),
    sinTaller: groups.sinTaller.sort(byName),
  };
}