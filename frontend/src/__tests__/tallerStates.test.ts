import { describe, expect, it } from "vitest";
import type {
  MethodologyActivation,
  PublishedMethodology,
} from "@/api/types";
import {
  computeSkillState,
  groupSkillsByState,
  publishedHasActiveInWorld,
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

function activation(
  skill_id: string,
  version = "1.0.0",
  world = WORLD,
): MethodologyActivation {
  return {
    world,
    skill_id,
    version,
    digest: `digest-${skill_id}`,
    activated_at: "2026-01-01T00:00:00Z",
  };
}

describe("computeSkillState", () => {
  it("returns 'activa' for an own-taller skill active in the world (REQ-TRE-5 S1)", () => {
    const s = skill({ skill_id: "s1", taller: MUNDO });
    expect(
      computeSkillState(
        s,
        MUNDO,
        WORLD,
        { [WORLD]: activation("s1") },
        [s],
      ),
    ).toBe("activa");
  });

  it("returns 'transversal-activa' for a compatible skill of another taller active in the world (S2)", () => {
    const s = skill({
      skill_id: "s2",
      taller: IDEAS,
      talleres_compatibles: [MUNDO],
    });
    expect(
      computeSkillState(
        s,
        MUNDO,
        WORLD,
        { [WORLD]: activation("s2") },
        [s],
      ),
    ).toBe("transversal-activa");
  });

  it("returns 'transversal-inactiva' when its primary taller has no active skill in the world (S3)", () => {
    const s = skill({
      skill_id: "s3",
      taller: IDEAS,
      talleres_compatibles: [MUNDO],
    });
    // The world's active skill belongs to the active taller — Ideas has
    // nothing active, so S is NOT blocked.
    const other = skill({ skill_id: "s3b", taller: MUNDO, name: "Otro" });
    expect(
      computeSkillState(
        s,
        MUNDO,
        WORLD,
        { [WORLD]: activation("s3b") },
        [s, other],
      ),
    ).toBe("transversal-inactiva");
  });

  it("returns 'bloqueada' when its primary taller already has an active skill in the world (S4)", () => {
    const s = skill({
      skill_id: "s4",
      taller: IDEAS,
      talleres_compatibles: [MUNDO],
    });
    const activeIdeas = skill({
      skill_id: "s4b",
      taller: IDEAS,
      name: "Activa Ideas",
    });
    expect(
      computeSkillState(
        s,
        MUNDO,
        WORLD,
        { [WORLD]: activation("s4b") },
        [s, activeIdeas],
      ),
    ).toBe("bloqueada");
  });

  it("returns 'transversal-activa' — an active skill is never blocked (S5)", () => {
    const s = skill({
      skill_id: "s5",
      taller: IDEAS,
      talleres_compatibles: [MUNDO],
    });
    const other = skill({ skill_id: "s5b", taller: IDEAS, name: "Otra Ideas" });
    expect(
      computeSkillState(
        s,
        MUNDO,
        WORLD,
        { [WORLD]: activation("s5") },
        [s, other],
      ),
    ).toBe("transversal-activa");
  });

  it("returns 'hidden' for a non-transversal skill of another taller (S6)", () => {
    const s = skill({ skill_id: "s6", taller: IDEAS, talleres_compatibles: [] });
    expect(computeSkillState(s, MUNDO, WORLD, {}, [s])).toBe("hidden");
  });

  it("returns 'inactiva' for an own-taller skill that is not active", () => {
    const s = skill({ skill_id: "s7", taller: MUNDO });
    expect(computeSkillState(s, MUNDO, WORLD, {}, [s])).toBe("inactiva");
  });

  describe("no world selected (S7)", () => {
    it("marks own-taller skills 'inactiva' and transversals 'transversal-inactiva'", () => {
      const propia = skill({ skill_id: "s8", taller: MUNDO });
      const transversal = skill({
        skill_id: "s9",
        taller: IDEAS,
        talleres_compatibles: [MUNDO],
      });
      expect(
        computeSkillState(propia, MUNDO, undefined, {}, [
          propia,
          transversal,
        ]),
      ).toBe("inactiva");
      expect(
        computeSkillState(transversal, MUNDO, undefined, {}, [
          propia,
          transversal,
        ]),
      ).toBe("transversal-inactiva");
    });

    it("never blocks without a world, even with an activation record present", () => {
      const s = skill({
        skill_id: "s10",
        taller: IDEAS,
        talleres_compatibles: [MUNDO],
      });
      const activeIdeas = skill({
        skill_id: "s10b",
        taller: IDEAS,
        name: "Activa Ideas",
      });
      expect(
        computeSkillState(
          s,
          MUNDO,
          undefined,
          { [WORLD]: activation("s10b") },
          [s, activeIdeas],
        ),
      ).toBe("transversal-inactiva");
    });
  });

  describe("sin taller bucket", () => {
    it("returns 'inactiva' for a null-taller skill that is not active", () => {
      const s = skill({ skill_id: "s11", taller: null });
      expect(computeSkillState(s, MUNDO, WORLD, {}, [s])).toBe(
        "inactiva",
      );
    });

    it("returns 'activa' for a null-taller skill active in the world", () => {
      const s = skill({ skill_id: "s12", taller: null });
      expect(
        computeSkillState(s, MUNDO, WORLD, { [WORLD]: activation("s12") }, [s]),
      ).toBe("activa");
    });

    it("returns 'inactiva' for a skill whose taller is not in OPERATIONAL_TALLERES", () => {
      const s = skill({ skill_id: "s13", taller: "No Core" });
      expect(computeSkillState(s, MUNDO, WORLD, {}, [s])).toBe(
        "inactiva",
      );
    });

    it("routes a 'Herramientas' primary to the bucket — never blocks (REQ-TRE-5 S8)", () => {
      const s = skill({
        skill_id: "s14",
        taller: "Herramientas",
        talleres_compatibles: [MUNDO],
      });
      const activeHerramientas = skill({
        skill_id: "s14b",
        taller: "Herramientas",
        name: "Activa Herramientas",
      });
      expect(
        computeSkillState(
          s,
          MUNDO,
          WORLD,
          { [WORLD]: activation("s14b") },
          [s, activeHerramientas],
        ),
      ).toBe("inactiva");
      const groups = groupSkillsByState(
        [s, activeHerramientas],
        MUNDO,
        WORLD,
        { [WORLD]: activation("s14b") },
      );
      expect(groups.sinTaller.map((skill) => skill.skill_id)).toEqual([
        "s14b",
        "s14",
      ]);
      expect(groups.bloqueadas).toEqual([]);
    });
  });
});

describe("seeded foundational skill narrative-character-creation@1.0 (Taller de Mundo tree)", () => {
  // The real seed manifest (data/methodology/seeds/narrative-character-creation/
  // manifest.yaml) declares `taller: Mundo` and NO talleres_compatibles, so
  // the server-installed record lands here with taller "Mundo": it derives
  // activa/inactiva in the contextual tree and groups under Inactivas, never
  // under "Sin taller" (foundational-skills-seeding FE add-on, seeding S2).
  const seeded = skill({
    skill_id: "narrative-character-creation",
    version: "1.0",
    name: "Creación de Personajes",
    taller: MUNDO,
    talleres_compatibles: [],
  });

  it("derives 'inactiva' in the Taller de Mundo while not active in the world", () => {
    expect(
      computeSkillState(seeded, MUNDO, WORLD, {}, [seeded]),
    ).toBe("inactiva");
  });

  it("derives 'activa' when the seeded skill is active in the world", () => {
    expect(
      computeSkillState(
        seeded,
        MUNDO,
        WORLD,
        { [WORLD]: activation("narrative-character-creation", "1.0") },
        [seeded],
      ),
    ).toBe("activa");
  });

  it("groups it under Inactivas — never Sin taller, never hidden (seeding S2)", () => {
    const groups = groupSkillsByState([seeded], MUNDO, WORLD, {});
    expect(groups.inactivas.map((s) => s.skill_id)).toEqual([
      "narrative-character-creation",
    ]);
    expect(groups.sinTaller).toEqual([]);
    expect([
      ...groups.activas,
      ...groups.transversalesActivas,
      ...groups.transversalesInactivas,
      ...groups.bloqueadas,
    ]).toHaveLength(0);
  });
});

describe("publishedHasActiveInWorld", () => {
  it("is true when a published skill of the taller is the world's active skill", () => {
    const s = skill({ skill_id: "p1", taller: MUNDO });
    expect(
      publishedHasActiveInWorld(MUNDO, WORLD, { [WORLD]: activation("p1") }, [s]),
    ).toBe(true);
  });

  it("is false when the world's active skill belongs to another taller", () => {
    const s = skill({ skill_id: "p2", taller: IDEAS });
    expect(
      publishedHasActiveInWorld(MUNDO, WORLD, { [WORLD]: activation("p2") }, [s]),
    ).toBe(false);
  });

  it("is false when the active skill_id is not present in the published list", () => {
    const s = skill({ skill_id: "p3", taller: MUNDO });
    expect(
      publishedHasActiveInWorld(MUNDO, WORLD, { [WORLD]: activation("ghost") }, [s]),
    ).toBe(false);
  });

  it("is false without a world", () => {
    expect(publishedHasActiveInWorld(MUNDO, undefined, {}, [])).toBe(false);
  });
});

describe("groupSkillsByState", () => {
  it("returns empty arrays (not undefined) when nothing is published", () => {
    expect(groupSkillsByState([], MUNDO, WORLD, {})).toEqual({
      activas: [],
      transversalesActivas: [],
      inactivas: [],
      transversalesInactivas: [],
      bloqueadas: [],
      sinTaller: [],
    });
  });

  it("routes each skill into its state bucket and drops hidden skills", () => {
    const activa = skill({ skill_id: "a1", taller: MUNDO, name: "Alfa Activa" });
    const inactiva = skill({ skill_id: "i1", taller: MUNDO, name: "Inactiva" });
    const transversalInactiva = skill({
      skill_id: "ti1",
      taller: IDEAS,
      talleres_compatibles: [MUNDO],
      name: "Transversal Inactiva",
    });
    const oculta = skill({ skill_id: "h1", taller: IDEAS, name: "Oculta" });

    const groups = groupSkillsByState(
      [activa, inactiva, transversalInactiva, oculta],
      MUNDO,
      WORLD,
      { [WORLD]: activation("a1") },
    );

    expect(groups.activas.map((s) => s.skill_id)).toEqual(["a1"]);
    expect(groups.inactivas.map((s) => s.skill_id)).toEqual(["i1"]);
    expect(groups.transversalesInactivas.map((s) => s.skill_id)).toEqual(["ti1"]);
    expect(groups.transversalesActivas).toEqual([]);
    expect(groups.bloqueadas).toEqual([]);
    expect(groups.sinTaller).toEqual([]);
  });

  it("routes an active transversal to transversalesActivas and a conflicting one to bloqueadas", () => {
    const transversalActiva = skill({
      skill_id: "ta1",
      taller: IDEAS,
      talleres_compatibles: [MUNDO],
      name: "Transversal Activa",
    });
    const bloqueada = skill({
      skill_id: "b1",
      taller: IDEAS,
      talleres_compatibles: [MUNDO],
      name: "Bloqueada",
    });
    const inactiva = skill({ skill_id: "i2", taller: MUNDO, name: "Inactiva" });

    const groups = groupSkillsByState(
      [transversalActiva, bloqueada, inactiva],
      MUNDO,
      WORLD,
      { [WORLD]: activation("ta1") },
    );

    expect(groups.transversalesActivas.map((s) => s.skill_id)).toEqual(["ta1"]);
    expect(groups.bloqueadas.map((s) => s.skill_id)).toEqual(["b1"]);
    expect(groups.inactivas.map((s) => s.skill_id)).toEqual(["i2"]);
    expect(groups.activas).toEqual([]);
  });

  it("routes null/off-list taller skills into the sinTaller bucket only", () => {
    const sinTallerNull = skill({ skill_id: "st1", taller: null, name: "Sin Taller Null" });
    const sinTallerNoCore = skill({ skill_id: "st2", taller: "No Core", name: "Sin Taller No Core" });
    const activa = skill({ skill_id: "a2", taller: MUNDO, name: "Activa" });

    const groups = groupSkillsByState(
      [sinTallerNull, sinTallerNoCore, activa],
      MUNDO,
      WORLD,
      { [WORLD]: activation("a2") },
    );

    // Sin-taller skills route to the bucket sorted alphabetically by name
    // ("No Core" < "Null"), and never leak into the operational state groups.
    expect(groups.sinTaller.map((s) => s.name)).toEqual([
      "Sin Taller No Core",
      "Sin Taller Null",
    ]);
    expect(groups.activas.map((s) => s.skill_id)).toEqual(["a2"]);
    // Sin-taller skills never leak into the operational state groups.
    expect([
      ...groups.activas,
      ...groups.inactivas,
      ...groups.transversalesActivas,
      ...groups.transversalesInactivas,
      ...groups.bloqueadas,
    ]).toHaveLength(1);
  });

  it("with no world, own-taller skills are inactivas and transversals are transversal-inactivas (S7)", () => {
    const propia = skill({ skill_id: "nw1", taller: MUNDO, name: "Propia" });
    const transversal = skill({
      skill_id: "nw2",
      taller: IDEAS,
      talleres_compatibles: [MUNDO],
      name: "Transversal",
    });
    const activaIdeas = skill({
      skill_id: "nw3",
      taller: IDEAS,
      name: "Activa Ideas",
    });

    const groups = groupSkillsByState(
      [propia, transversal, activaIdeas],
      MUNDO,
      undefined,
      { [WORLD]: activation("nw3") },
    );

    expect(groups.inactivas.map((s) => s.skill_id)).toEqual(["nw1"]);
    expect(groups.transversalesInactivas.map((s) => s.skill_id)).toEqual(["nw2"]);
    expect(groups.activas).toEqual([]);
    expect(groups.bloqueadas).toEqual([]);
  });

  it("sorts each group alphabetically by name", () => {
    const inactivas = [
      skill({ skill_id: "z", taller: MUNDO, name: "Zeta" }),
      skill({ skill_id: "a", taller: MUNDO, name: "Alfa" }),
      skill({ skill_id: "m", taller: MUNDO, name: "Media" }),
    ];
    const sinTaller = [
      skill({ skill_id: "stz", taller: null, name: "Zeta Sin" }),
      skill({ skill_id: "sta", taller: null, name: "Alfa Sin" }),
    ];

    const groups = groupSkillsByState(
      [...inactivas, ...sinTaller],
      MUNDO,
      WORLD,
      {},
    );

    expect(groups.inactivas.map((s) => s.name)).toEqual(["Alfa", "Media", "Zeta"]);
    expect(groups.sinTaller.map((s) => s.name)).toEqual(["Alfa Sin", "Zeta Sin"]);
  });
});