import { describe, expect, it } from "vitest";
import type {
  MethodologyCompanion,
  PublishedMethodology,
} from "@/api/types";
import {
  compareVersions,
  groupSkillsByChat,
  isTransversalSkill,
} from "@/lib/tallerStates";

const MUNDO = "Mundo";
const IDEAS = "Ideas";
const WORLD = "Vibrantes";

function skill(
  overrides: Partial<PublishedMethodology> = {},
): PublishedMethodology {
  return {
    skill_id: "skill-1",
    version: "1.0.0",
    name: "Skill Uno",
    description: "desc",
    digest: "digest-1",
    published_at: "2026-01-01T00:00:00Z",
    taller: MUNDO,
    talleres_compatibles: [],
    ...overrides,
  };
}

function companion(
  skill_id: string,
  version = "1.0.0",
  world = WORLD,
): MethodologyCompanion {
  return {
    world,
    skill_id,
    version,
    description: "desc",
    activated_at: "2026-01-01T00:00:00Z",
  };
}

describe("isTransversalSkill", () => {
  it("is true for another operational taller declared compatible", () => {
    const s = skill({ taller: IDEAS, talleres_compatibles: [MUNDO] });
    expect(isTransversalSkill(s, MUNDO)).toBe(true);
  });

  it("is false for an own-taller skill", () => {
    expect(isTransversalSkill(skill({ taller: MUNDO }), MUNDO)).toBe(false);
  });

  it("is false for another taller without a compatibility declaration", () => {
    expect(isTransversalSkill(skill({ taller: IDEAS }), MUNDO)).toBe(false);
  });
});

describe("groupSkillsByChat", () => {
  it("returns empty arrays (not undefined) when nothing is published", () => {
    const groups = groupSkillsByChat([], MUNDO, []);
    expect(groups).toEqual({ enChat: [], fueraDelChat: [], sinTaller: [] });
  });

  it("splits own-taller skills by chat membership (S1)", () => {
    const inChat = skill({ skill_id: "s1", name: "Alfa" });
    const out = skill({ skill_id: "s2", name: "Beta" });
    const groups = groupSkillsByChat(
      [inChat, out],
      MUNDO,
      [companion("s1")],
    );
    expect(groups.enChat.map((s) => s.skill_id)).toEqual(["s1"]);
    expect(groups.fueraDelChat.map((s) => s.skill_id)).toEqual(["s2"]);
    expect(groups.sinTaller).toEqual([]);
  });

  it("keeps transversals in the chat buckets (scope chip stays visible)", () => {
    const transversal = skill({
      skill_id: "s3",
      name: "Transversal",
      taller: IDEAS,
      talleres_compatibles: [MUNDO],
    });
    const groups = groupSkillsByChat([transversal], MUNDO, [companion("s3")]);
    expect(groups.enChat.map((s) => s.skill_id)).toEqual(["s3"]);
    expect(isTransversalSkill(groups.enChat[0], MUNDO)).toBe(true);
  });

  it("hides a skill of another taller that is not compatible (TW2)", () => {
    const foreign = skill({ skill_id: "s4", taller: IDEAS });
    const groups = groupSkillsByChat([foreign], MUNDO, []);
    expect(groups.enChat).toEqual([]);
    expect(groups.fueraDelChat).toEqual([]);
    expect(groups.sinTaller).toEqual([]);
  });

  it("routes null/off-list taller skills into sinTaller only", () => {
    const groups = groupSkillsByChat(
      [
        skill({ skill_id: "null", taller: null }),
        skill({ skill_id: "off", taller: "Herramientas" }),
        skill({ skill_id: "own", taller: MUNDO }),
      ],
      MUNDO,
      [],
    );
    expect(groups.sinTaller.map((s) => s.skill_id)).toEqual(["null", "off"]);
    expect(groups.fueraDelChat.map((s) => s.skill_id)).toEqual(["own"]);
  });

  it("chat membership is skill-level: any companion version marks the row", () => {
    const current = skill({ skill_id: "s5", version: "2.0.0" });
    const groups = groupSkillsByChat(
      [current],
      MUNDO,
      [companion("s5", "1.0.0")],
    );
    expect(groups.enChat.map((s) => s.skill_id)).toEqual(["s5"]);
  });

  it("sorts each group alphabetically by name", () => {
    const groups = groupSkillsByChat(
      [
        skill({ skill_id: "b", name: "Zeta" }),
        skill({ skill_id: "a", name: "Alfa" }),
        skill({ skill_id: "c", name: "Beta" }),
      ],
      MUNDO,
      [companion("c")],
    );
    expect(groups.enChat.map((s) => s.name)).toEqual(["Beta"]);
    expect(groups.fueraDelChat.map((s) => s.name)).toEqual(["Alfa", "Zeta"]);
  });
});

describe("groupSkillsByChat — one row per skill (REQ-TRE-9/10)", () => {
  it("renders the latest published version as the single row", () => {
    const groups = groupSkillsByChat(
      [
        skill({ skill_id: "s1", version: "1.2.0", name: "Skill Uno" }),
        skill({ skill_id: "s1", version: "1.10.0", name: "Skill Uno" }),
        skill({ skill_id: "s1", version: "1.9.0", name: "Skill Uno" }),
      ],
      MUNDO,
      [],
    );
    expect(groups.fueraDelChat).toHaveLength(1);
    expect(groups.fueraDelChat[0].version).toBe("1.10.0");
  });
});

describe("compareVersions (REQ-TRE-11 S7)", () => {
  it("orders numeric segments, never lexicographically", () => {
    expect(compareVersions("1.10", "1.9")).toBeGreaterThan(0);
    expect(compareVersions("1.9", "1.10")).toBeLessThan(0);
  });

  it("breaks a numeric tie by segment specificity", () => {
    expect(compareVersions("1.2.0", "1.2")).toBeGreaterThan(0);
  });

  it("returns 0 for equal versions", () => {
    expect(compareVersions("1.2", "1.2")).toBe(0);
  });
});

describe("seeded foundational skill narrative-character-creation@1.0 (Taller de Mundo tree)", () => {
  it("is visible in the Mundo context as a chat candidate", () => {
    const seeded = skill({
      skill_id: "narrative-character-creation",
      name: "Creación de Personajes",
      taller: MUNDO,
    });
    const groups = groupSkillsByChat([seeded], MUNDO, []);
    expect(groups.fueraDelChat.map((s) => s.skill_id)).toEqual([
      "narrative-character-creation",
    ]);
  });

  it("moves to En el chat when the world adds it", () => {
    const seeded = skill({
      skill_id: "narrative-character-creation",
      name: "Creación de Personajes",
      taller: MUNDO,
    });
    const groups = groupSkillsByChat(
      [seeded],
      MUNDO,
      [companion("narrative-character-creation")],
    );
    expect(groups.enChat.map((s) => s.skill_id)).toEqual([
      "narrative-character-creation",
    ]);
  });
});
