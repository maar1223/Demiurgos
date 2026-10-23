# Entity foundational skill (`entidad` as the fourth guided flow)

Branch: `integration/guided-flows` (base HEAD `6bd8939d`). Delivery: work-unit commits, **no push, no PR, no merge**. Runner: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q`; `cd frontend && npx vitest run`; `npm run typecheck`; `npm run build`.

## Specs

- **S1 Tipo persistido (decisión Owner: 1a).** The engine writes exactly one `type` per flow. The kernel currently rejects the generic type `entidad` (`entity_type_is_persistible` only lets `personaje` use the `entidad` shape). Permit the explicit type `entidad` as persistible into `lore/` and write `type: Entidad`; the class (`lugar`/`facción`/`criatura`/`artefacto`/`cultura`/`especie`) lives as a body/frontmatter field. The `type` is **not** a per-session parameter (option 1b rejected). "el dominio es parámetro, no código".
- **S2 Nombres e identificadores (fijados).** Skill `narrative-entity-creation`; flow `guided-entity`; `ui_copy_key` = `"entity"`; `ENTITY_TYPE_BY_FLOW["guided-entity"] == "entidad"`.
- **S3 Mínimos de la forma (decisión Owner: obligatoria, kernel-owned).** The skill does **not** declare minimums. `okf_contract` owns them: identity **plus** the entity class. Minimum stays declarative (`OKF_MINIMUM_GROUPS_BY_TYPE`), never a skill field.
- **S4 Apertura desde chat (criterio de aceptación).** `"quiero crear un lugar / una facción / una criatura"` abre la tarjeta guiada con el método de entidad; `guided-methods?flow=guided-entity` lista `narrative-entity-creation` como default y ningún método de otro flujo.
- **S5 Persistencia (criterio de aceptación).** Aceptar persiste en `lore/` con el `type` decidido, valida los mínimos OKF y indexa; un borrador sin clase no puede aceptarse como completo.
- **S6 Sin regresiones.** Personajes, Sistemas y Cronología quedan intactos (sus suites verdes; serializer de personaje byte-idéntico).
- **S7 Seed (criterio de aceptación).** `data/methodology/seeds/narrative-entity-creation/{manifest.yaml,source.md,checksums.json}`. `trigger` ≤57 caracteres, separado de `description`; la `description` es el método que se inyecta y conserva las preguntas y la ramificación por clase sin registro fijo; `guided_flow` con intent terms (`entidad`, `lugar`, `facción`, `criatura`, `artefacto`, `cultura`, `especie`) y verbs. `test_real_seed_injects_full_system_method_contract` sigue verde.
- **S8 Cableado de superficie.** Frontend: unión `ui_copy_key` en `types.ts`, admisión en `semanticIntent.ts`, copy del consentimiento es/en en `messages.ts` y la selección en `AIAssistantSidebar.tsx`. Server: texto de consentimiento por copy key.
- **S9 Proceso ODD.** Este documento se crea antes del primer write, con espejo en Engram (`odd/entity-foundational-skill/tasks`), commits por unidad de trabajo, y no se tocan los pendientes conocidos listados fuera de alcance.
- **S10 Límites.** No push, no PR, no merge. No RDD nuevo. No tocar: export de paquetes (pierde `trigger`/`guided_flow`), `create_derived_draft` (no hereda `trigger`), canvas de la Skill Madre (`guided_flow` diferido a fase dos).

Exact quotes to honor (owner request): `"quiero crear un lugar / una facción / una criatura"`, `type: Entidad`, `"entity"`, `"trigger ≤57 separado de description (la description es el método que se inyecta)"`.

Out of scope: option 1b (per-session `type`), `relacion`/`tension` forms, publishing, PRs, the three known pendings above.

## Tasks

- [x] T1 kernel: `guided_flow.py` (`GUIDED_ENTITY_FLOW`, `ENTITY_TYPE_BY_FLOW`, `FOUNDATIONAL_METHOD_BY_FLOW`, `GUIDED_FLOW_IDS`, `UI_COPY_KEYS`, `TARGET_SECTION`, `TYPE_LABEL`, `QUESTION_KEYS`, `FRONTMATTER_FIELDS`, `PROVENANCE_DEFAULT`, `DEFAULT_TITLE`, `entity_type_is_persistible` relaxed only for the explicit `entidad`) + `okf_contract.py` (`entidad` shape entry, `MINIMUM_CLASS_FIELDS`, registered group). Inline. Tests RED first in `test_guided_flow.py` + `test_okf_contract.py`. Evidence: RED 4 failed → GREEN 79 passed. Commit `d0684023`.
- [x] T2 domain: identity + class question copy in `guided_character_domain.py`. Inline. Tests in `test_guided_character_domain.py`. Evidence: RED 2 failed (identity copy) → GREEN 57 passed. Commit `d0684023`.
- [x] T3 seed: `data/methodology/seeds/narrative-entity-creation/` + `checksums.json` + `payload_manifest.json` regeneration. Inline. Tests in `test_methodology_seed.py`. Evidence: RED 13 failed → GREEN 48 passed; `payload_manifest.json` 162 files (+3 seed files, `source_commit` `6bd8939d`). Commit `cd32e628`.
- [x] T4 server: consent copy by copy key in `api_server.py`. Inline. Tests in `test_guided_flow_api.py`. Evidence: RED 1 failed (copy key) → GREEN 20 passed, including the end-to-end write+index acceptance test. Copy in `d0684023`; tests in `cd32e628`.
- [x] T5 frontend: `types.ts`, `semanticIntent.ts`, `messages.ts` (es/en), `AIAssistantSidebar.tsx`. Inline. Tests in `semanticIntent.test.ts` + `AIAssistantSidebar.test.tsx`. Evidence: RED 2 failed → GREEN 61 passed (both files); full FE 1489 passed; typecheck and build clean. Commit `cab7da5e`.
- [x] T6 docs: `skill-runtime-consumption-contract.md` §2.1 and `tool-workshop.md` §6.8 reflect the fourth flow. Inline. Evidence: contract §2.1 (kernel-owned section + supported flows), subsystem §10.7 (entity bullet), foundational §2 (minimums row). `tool-workshop.md` §6.8 is generic and needed no edit. Commit `docs(skills)`.
- [x] T7 verification: backend suite, frontend suite, typecheck, build; the 2 known order-dependent `test_gateway_hooks` failures verified in isolation. Evidence: BE 4101 passed / 18 skipped / 2 failed (`test_cache_safe_returns_false_when_modules_absent`, `test_cache_safe_version_fallback_to_plain_prompt_builder`) → `test_gateway_hooks.py` alone 39 passed; FE 1489 passed (123 files); typecheck clean; build OK. Differential probe against `6bd8939d` over 25 type labels: the only changed behavior is the normalized type `entidad` (minimums + persistibility); every other type is byte-identical.

## Log

- **L1 (Owner request, verbatim):**

  > Contexto: repo Demiurgos (cwd del workspace). Rama integration/guided-flows, HEAD 6bd8939d.
  > Arrancá cargando el checkpoint: mem_search("nec/checkpoint", project:"demiurgos") + mem_get_observation.
  > No hagas push, PR ni merge.
  >
  > OBJETIVO
  > Crear la Skill fundacional de la forma `entidad` (la única del MVP que falta) y cablearla
  > como flujo guiado, siguiendo el patrón ya probado de Sistemas y Cronología.
  >
  > BASE DOCUMENTAL (leer antes de proponer)
  > - docs/architecture/foundational-skills-architecture.md §1 (formas MVP: entidad · sistema ·
  >   cronologia; relacion diferida; "el dominio es parámetro, no código"), §2 (envelope OKF),
  >   §4 (método) y §5 (huecos).
  > - docs/architecture/skill-runtime-consumption-contract.md §2.1 y §3.
  > - docs/architecture/tool-workshop.md §6.8.
  > - Referencia de implementación: commits 9dfc8acc (Cronología) y 6bd8939d; seed
  >   data/methodology/seeds/narrative-chronology-creation/.
  >
  > DECISIONES QUE DEBE CERRAR EL OWNER ANTES DE ESCRIBIR CÓDIGO
  > 1. Tipo persistido. El motor escribe UN `type` por flujo. Además, el kernel HOY RECHAZA el
  >    tipo genérico `entidad` en guided_flow.entity_type_is_persistible (solo `personaje` puede
  >    usar la forma entidad). Opciones:
  >    a) Permitir `entidad` como tipo persistible y escribir `type: Entidad`, con la clase
  >       (lugar/facción/criatura/artefacto/cultura/especie) como campo del cuerpo. (Recomendada
  >       para MVP: aditiva, respeta "dominio = parámetro".)
  >    b) Extender el perfil para que el `type` sea parámetro por sesión. (Cambio de esquema,
  >       más grande; no hacer sin decisión explícita.)
  > 2. Nombre e identificadores: narrative-entity-creation / guided-entity / ui_copy_key "entity".
  > 3. Mínimos de la forma entidad: hoy solo identidad (okf_contract). ¿La skill exige además la
  >    clase de entidad? Si sí, el mínimo es kernel-owned: se declara en okf_contract, no en la skill.
  >
  > ALCANCE TÉCNICO (si las decisiones cierran)
  > - Kernel: guided_flow.py (GUIDED_ENTITY_FLOW, ENTITY_TYPE_BY_FLOW, FOUNDATIONAL_METHOD_BY_FLOW,
  >   GUIDED_FLOW_IDS, UI_COPY_KEYS; TARGET_SECTION/TYPE_LABEL/QUESTION_KEYS/FRONTMATTER_FIELDS/
  >   PROVENANCE_DEFAULT/DEFAULT_TITLE) y okf_contract.py si hay mínimos nuevos. Si se elige 1a,
  >   relajar el guard de entity_type_is_persistible SOLO para el tipo explícito `entidad`.
  > - Dominio: copy de identidad y preguntas en guided_character_domain.py.
  > - Servidor: texto de consentimiento por copy key en api_server.py.
  > - Frontend: unión de ui_copy_key, semanticIntent, copy del consentimiento es/en.
  > - Seed: data/methodology/seeds/narrative-entity-creation/{manifest.yaml, source.md,
  >   checksums.json}. `trigger` ≤57 separado de `description` (la description es el método que se
  >   inyecta); `guided_flow` con intent terms (entidad, lugar, facción, criatura, artefacto,
  >   cultura, especie) y verbs. Descripción del método con las preguntas y la ramificación por
  >   clase, en el cuerpo; sin registro fijo.
  > - Tests: kernel (perfil, rechazo de tipos desconocidos), dominio (preguntas, serializer,
  >   validación OKF), API (guided-methods, session start, serialize, consent copy), seed
  >   (catálogo, trigger ≤57 sin issues, description conserva el método), frontend (flow echo,
  >   consent body).
  > - ODD: crear odd/tasks/entity-foundational-skill.md ANTES del primer write, con Specs/Tasks/Log
  >   y espejo en Engram (odd/entity-foundational-skill/tasks). Commits por unidad de trabajo.
  >
  > CRITERIOS DE ACEPTACIÓN
  > - "quiero crear un lugar / una facción / una criatura" abre la tarjeta guiada con el método de
  >   entidad; aceptar persiste en lore/ con el type decidido, valida los mínimos y indexa.
  > - Personajes, Sistemas y Cronología quedan intactos (sus suites verdes).
  > - El trigger renderiza ≤57 sin issues; la description sigue alimentando el contrato inyectado
  >   (test_real_seed_injects_full_system_method_contract sigue verde).
  >
  > RUNNERS
  > - .venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q
  > - cd frontend && npx vitest run && npm run typecheck && npm run build
  > - Los 2 fallos de test_gateway_hooks son order-dependent conocidos: verificalos en aislamiento.
  >
  > PENDIENTES CONOCIDOS QUE NO SON DE ESTA TAREA (no tocar sin pedirlo)
  > - El export de paquetes NO incluye `trigger` ni `guided_flow` (round-trip los pierde).
  > - `create_derived_draft` (Adaptar) no hereda `trigger`.
  > - El canvas de la Skill Madre no puede declarar `guided_flow` (fase dos documentada).

- **L2 (decisiones Owner, 2026-10-22):** (1) **1a** — `type: Entidad` y clase como campo, sin tocar el esquema de sesión. (2) **Clase obligatoria, kernel-owned** — el mínimo se declara en `okf_contract`, no en la skill. Dato de apoyo: `grep -rli "^type:[[:space:]]*entidad" mundos/` = 0 fichas, así que el mínimo nuevo no invalida datos legacy.
- **L3 (exploración, 2026-10-22):** el guard tiene dos cerrojos (`TARGET_SECTION_BY_ENTITY_TYPE` y la línea 129 `shape == entidad` salvo `personaje`); `GUIDED_FLOW_IDS` gobierna las rutas del server (7 sitios) y `SUPPORTED_FLOW_TYPES` deriva de él; el frontend tiene 4 puntos duros. `payload_manifest.json` se regenera con `scripts/derive_payload_manifest.py` (glob de seeds). El fixture `_isolated_flow_env` instala el seed real, así que los tests de API de entidad dependen del seed (orden T1→T3→T4).

- **L4 (implementation discovery, 2026-10-22):** con el kernel table-driven y el seed real, las rutas de API de entidad (guided-methods, session start, serialize, consent) funcionaron sin tocar `api_server.py` salvo el copy de consentimiento; el único RED de T4 fue la copy key. El guard de persistencia necesitó **dos** cambios, no uno: la sección kernel (`TARGET_SECTION_BY_ENTITY_TYPE`) y el rechazo por forma, que excluía todo tipo con `shape == "entidad"` salvo `personaje`.
- **L5 (locks de conteo, 2026-10-22):** agregar un cuarto seed toca locks explícitos en `test_methodology_seed`, `test_methodology_library`, `test_guided_character_api`, `test_api_server`, `test_payload_boot` y `test_per_flow_activation`. Cada uno se actualizó con el valor esperado nuevo (nunca se relajó). `test_seeds_are_sixteen_files` se renombró a `test_seeds_are_nineteen_files` para que el nombre diga la verdad.
- **L6 (diferencial, 2026-10-22):** probe contra `6bd8939d` (copia base en `mktemp` fuera del worktree) sobre 25 etiquetas (`personaje`, `sistema`, `cronologia`, `evento`, `era`, `historia`, `lugar`, `criatura`, `faccion`, `artefacto`, `cultura`, `objeto`, `especie`, `concepto`, `ficha`, `referencia_visual`, `magia`, `tecnologia`, `economia`, `ley`, `religion`, `desconocido`, `Entidad`, `ENTIDAD`, vacío): `CHANGED TYPES = ['ENTIDAD', 'Entidad']`, es decir sólo el tipo normalizado `entidad`. Cero regresiones en el resto del vocabulario.

- **L7 (commits, 2026-10-22):** `d0684023` kernel + dominio + consent copy; `cd32e628` seed + payload manifest + locks de conteo y tests de API; `cab7da5e` frontend; el commit de docs cierra T6 y este documento. Sin push, sin PR, sin merge.
