# Arquitectura de Skills Fundacionales — Diseño y estado

**Estado:** diseño en curso. Envelope **implementado** (3 commits locales, sin pushear).
**Propósito de este documento:** dejar el contexto completo para retomar en una sesión limpia.

> Este documento es la fuente de verdad narrativa del diseño. Los artefactos detallados viven en Engram (ver §9). No reabrir las decisiones marcadas **[LOCK]** sin motivo.

---

## 0. Para retomar en 60 segundos

- **Qué buscamos:** que Demiurgos se diferencie de ChatGPT/Gemini por **MÉTODO** (estructura, rigor, repetibilidad), no por la IA. Las **Skills fundacionales** son ese método empaquetado; el **Taller de Herramientas** deja que el usuario empaquete el suyo.
- **Dónde estamos:** fundamentos lockeados + envelope formalizado e implementado. **Siguiente paso: diseñar el método `Sistema`** (y resolver los 3 huecos del pre-mortem, §5).
- **No reiniciar:** leer §1–§5 antes de proponer nada nuevo.

---

## 1. Fundamentos lockeados **[LOCK]**

1. **Una skill es un MÉTODO**, no un tema. (Preguntas repetibles + un output.)
2. **Los métodos se definen por FORMA**; el dominio/tema es **parámetro**.
3. **Formas del MVP:** `entidad` · `sistema` · `cronologia`.
   - `relacion`/`tension` está **DIFERIDA** (post-MVP): ya existe gobierno de conflictos/propuestas en el código, pero necesita diseño propio + frontend.
4. **Envelope fijo** = contrato entre talleres. **El cuerpo emerge**; no hay ficha universal.
5. **Las skills se COMPONEN** vía Skill Madre (kernel provider).
6. **Las formas son DECLARATIVAS**: agregar un dominio = parámetro/config, no código.
7. **Anti-rewrite:** agregar dominio → parámetro nuevo, no reescritura.

**Corolario arquitectónico:** el **KERNEL** es dueño de la **forma** (pocas, fijas, agnósticas). El **MUNDO** es dueño del **tipo** (etiqueta) + su mapeo a forma + sus mínimos.

---

## 2. El Envelope — formalizado SOBRE OKF v1 **[LOCK]**

**No se reinventó:** el envelope ya existía como contrato **OKF v1** y como frontmatter YAML de las fichas (`mundos/**/*.md`).

### Qué ya definía OKF (`src/tools/demiurgos-suite/wiki/okf_contract.py`)
- Identidad: frontmatter con `type` no vacío.
- Relaciones: campo `relaciones` (lista de `[[wikilinks]]`) + wikilinks en el cuerpo.
- `id` canónico: `Padre::Título` (separador `::`, NFC, `#N` para duplicados).
- `okf_version`.
- **Mínimos por tipo extensibles** vía `register_minimums(entity_type, *groups)` — la costura declarativa.

### Qué se agregó (implementado)
| Campo | Estado | Nota |
|---|---|---|
| `shape` | **NUEVO**, derivado de `type` si falta | `entidad` \| `sistema` \| `cronologia` (`relacion` reservada) |
| `canon_state` | **NUEVO**, derivado de `status` | 7 estados propios del mundo (ver §3) |
| `type` | normalizado | lowercase + mapa de alias (`Criatura`→`criatura`) |
| mínimos | por **forma** + extras por tipo | `entidad`=identidad; `sistema`=origen/fuente; `cronologia`=evento/fecha; `personaje` además=deseo |
| `taller` | **NO va en la ficha** | registro aparte de qué formas/tipos muestra cada taller |

**Lectura tolerante:** datos viejos siguen válidos (normalización + defaults, sin migración masiva).
**`status`** (editorial: `draft`|`stable`) queda **SEPARADO** de **`canon_state`** (verdad en la ficción).

---

## 3. `canon_state` — 7 estados propios del mundo **[LOCK]**

> NO se reusan los 5 del contrato de investigación: esos describen **procedencia/autoridad** de un material; `canon_state` describe **qué es verdad dentro de la ficción**.

`canon` · `creencia` · `leyenda` · `hipotesis` · `perdido` · `prohibido` · `propuesta`

- Default: `status = stable` → `canon`; `status = draft` → `propuesta`.
- Eje **separado y NO construido aún:** **visibilidad** (público/secreto) — algo puede ser verdad **Y** secreto (la Mascarada).

---

## 4. Método candidato: forma `Sistema` (borrador a validar)

Cubre **cualquier** sistema de reglas: magia, tecnología, economía, ley, religión, divino, natural.

### Qué produce (el cuerpo, que emerge)
- **Sistema (meta):** nombre · clase · naturaleza (dura/blanda) · fuente/origen · principio rector · acceso global · `canon_state`.
- **Poder/Regla (N registros):** nombre · efecto · costo (o "blando") · límite · acceso · consecuencias · `canon_state`.

### Preguntas 40/60
1. ¿Nombre y **clase**?
2. ¿**De dónde viene** el poder?
3. ¿**Duro o blando**? (cambia las siguientes)
4. *(por poder)* ¿Qué **hace**?
5. ¿Qué **cuesta**? (o ¿por qué no cuesta?)
6. ¿Qué **no puede** / cuándo **falla**?
7. ¿**Quién accede** y cómo?
8. ¿Qué **consecuencia** tiene para el mundo?
9. ¿Verdad/creencia/leyenda? (`canon_state`)

### Rieles 40% (verificable)
Cada sistema declara **fuente + naturaleza**; cada poder declara **efecto + (costo O blandura) + límite**.

### Validación anti-sobreajuste (contra ≥2 sistemas)
- **Vibrastal** (del Autor): material, **duro** → ✅
- **La Fuerza (Star Wars)**: espiritual, **blando** → ✅
- **La Especia (Dune)**: económico/biológico, no-mágico → ✅
- **HP / Red Rising**: ✅ sin polaridad.

### Hallazgo de los contraejemplos
La **polaridad NO es universal** (HP: neutral; sus "Artes Oscuras" son clasificación **social/legal**, no polaridad intrínseca). Se **retiró** como campo; se reemplazó por una **pregunta opcional de clasificación propia** (polaridad/escuelas/elementos) que captura la taxonomía **cuando existe**.

---

## 5. Pre-mortem — cómo se rompe y dónde hay huecos

### A) El método `Sistema` se rompe
1. **Fuga de "blanda"** 🔴: declarar "blando" evita pensar costo/límite → **mata el rigor**. (El hueco #1.)
2. **Registro "poder" de forma MÁGICA** 🔴: economía/ley/sociedad no se descomponen en "habilidades".
3. Frontera `sistema` vs `entidad` difusa (criatura con poderes innatos; religión).
4. `acceso` mezcla **capacidad** vs **permiso** (dos ejes).
5. Sistemas **anidados/multicapa** sin jerarquía (Vibrastal: estados+arquetipos+vínculos).
6. Falta **relación explícita** (refs) con otros sistemas/pilares.

### B) El envelope / arquitectura se rompe
7. **Cuerpo EMERGENTE vs consumo por MÁQUINA** 🔴: Mesa de rol necesita `costo`/`límite` estructurados; si el cuerpo es libre, la interop queda solo en metadata.
8. `canon_state` **por ficha** es muy grueso (una ficha mezcla canon+leyenda) → quizá a nivel de **afirmación**.
9. Normalización de `type`: mantenimiento de alias + pérdida del tipo original + vocabulario compartido entre mundos.
10. **Sin versión** de OKF ni de método → cambios silenciosos.
11. **La costura extensible NO está cableada** (`register_minimums` solo lo usan los tests).
12. **COMPOSICIÓN / Skill Madre sin diseñar** 🔴: quién elige y encadena los métodos ante un objetivo.

### C) Proceso
13. **YAGNI**: arquitectura para talleres futuros sobre un pre-alpha con una sola seed.
14. Sesgo residual a Vibrantal.

### Top 3 a resolver ANTES de seguir
1. **"Blanda" con justificación obligatoria** (hueco #1).
2. **Qué campos son contractuales (consumibles) vs emergentes** (hueco #7).
3. **Composición / Skill Madre** (hueco #12).

---

## 6. Implementado (commits locales, NO pusheados)

| Commit | Qué |
|---|---|
| `840c3e3` | `feat(okf): formalize the content envelope (shape, canon_state, type normalization)` — `okf_contract.py` + tests. Backend **3488 passed / 0 failed**. |
| `df01e68` | `feat(graph): expose envelope shape and canon_state in the entity index` — `graph_indexer`/`graph_models`/`mcp_adapter` + tests. Backend **3493 passed / 0 failed**. |
| `3917eb6` | `feat(frontend): carry envelope shape and canon_state on graph entity types` — `types.ts` + 2 fixes de display. Frontend **1440 passed**, typecheck/build OK. |

**Nota:** el `type` ahora viaja en **minúsculas** (cambio de wire); el display se capitaliza en el frontend.

---

## 7. Próximos pasos (orden sugerido)

1. **Resolver los 3 huecos del pre-mortem** (§5), empezando por la fuga de "blanda".
2. **Cerrar el método `Sistema`** (preguntas + rieles), con la clasificación propia opcional.
3. **(Opcional) Cablear `register_minimums`** a config del mundo + versión de OKF.
4. Diseñar **la composición / Skill Madre**.

### Frentes MVP pendientes (más amplios, en pausa)
- `tool-workshop-completion`: doc-sync (`docs/architecture/tool-workshop.md:236` stale) + runbook e2e con Hermes real.
- Cadena release: versionado/canal → updater Estable/Beta → bug-reporting.
- `usage-docs-and-alpha-onboarding` + verificación manual de la instalación (paso F) antes del tag Alfa.

---

## 8. Notas de entorno

- Backend tests: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q`.
- Frontend: `cd frontend && npm test` / `npm run typecheck` / `npm run build`.
- `strict_tdd: NO`.
- **RDD está apagado** y la revisión nativa está **bloqueada por el filesystem** (ntfs-3g/FUSE proyecta dueño fijo; el validador RAR no puede leer la propiedad de `.git`).
- `mem_save` MCP a veces falla por **ambigüedad de sesión** → usar el CLI `engram save ... --topic ...`.

---

## 9. Referencias en Engram

- `architecture/foundational-skills-foundations` (#3627) — fundamentos.
- `architecture/okf-content-envelope` (#3628) — el envelope ya existía (OKF).
- `sdd/okf-envelope-formalization/spec` (#3629) — envelope formalizado.
- `sdd/okf-envelope-formalization/canon-state` (#3630) — vocabulario de canon_state.
- `sdd/okf-envelope-formalization/relations-deferred` (#3631) — `relacion` diferida + formas del MVP.
- `sdd/okf-envelope-formalization/tasks` (#3632) — plan de tareas.
- `sdd/sistema-method/draft` (#3634) — método candidato `Sistema`.
- `sdd/sistema-method/premortem` (#3635) — pre-mortem (huecos + top 3).
- `architecture/methodology-activation-model` (#3622) — cómo funciona activar/desactivar skills.
- `nec/checkpoint` (#2351) — checkpoint de sesión.
