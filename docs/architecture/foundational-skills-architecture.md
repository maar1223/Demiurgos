# Arquitectura de Skills Fundacionales — Diseño y estado

**Estado:** diseño en curso. Envelope **implementado** (4 commits locales, sin pushear). Método `Sistema` **reformulado** (§4, base #3626).
**Propósito de este documento:** dejar el contexto completo para retomar en una sesión limpia.

> Este documento es la fuente de verdad narrativa del diseño. Los artefactos detallados viven en Engram (ver §9). No reabrir las decisiones marcadas **[LOCK]** sin motivo.

---

## 0. Para retomar en 60 segundos

- **Qué buscamos:** que Demiurgos se diferencie de ChatGPT/Gemini por **MÉTODO** (estructura, rigor, repetibilidad), no por la IA. Las **Skills fundacionales** son ese método empaquetado; el **Taller de Herramientas** deja que el usuario empaquete el suyo.
- **Dónde estamos:** fundamentos lockeados + envelope implementado + método `Sistema` reformulado y validado (§4). Decidido: **el tiempo vive en `Cronología`** (visión A). **Siguiente paso: confirmar la taxonomía de clases y resolver los huecos #7/#8/#12** (§5).
- **No reiniciar:** leer §1–§5 antes de proponer nada nuevo.

---

## 1. Fundamentos lockeados **[LOCK]**

1. **Una skill es un MÉTODO**, no un tema. (Preguntas repetibles + un output.)
2. **Los métodos se definen por FORMA**; el dominio/tema es **parámetro**.
3. **Formas del MVP:** `entidad` · `sistema` · `cronologia`.
   - `relacion`/`tension` está **DIFERIDA** (post-MVP): ya existe gobierno de conflictos/propuestas en el código, pero necesita diseño propio + frontend.
4. **Envelope fijo** = contrato entre talleres. **El cuerpo emerge**; no hay ficha universal.
5. **Las skills se COMPONEN**: la **Skill Madre** *diseña* el encadenado y los gatillos; el **Asistente de Demiurgos** los *consume* (ver §5, #12).
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

## 4. Método de la forma `Sistema` (reformulado — base #3626)

**Principio:** el método es un **contrato de preguntas mínimas y semánticas** + **ramificación por clase de sistema**. **NO** impone un registro fijo: el cuerpo **emerge**; el envelope vive en OKF (fijo, §2).

> Este apartado corrige el borrador anterior (Engram #3634), que fijaba un registro "Poder/Regla" con `efecto/costo/límite`. Eso era **estructural y con forma de magia** — justo lo que la corrección lockeada (#3626) prohíbe.

### 4.1 Preguntas universales (lo agnóstico)
1. **Nombre y clase** de sistema.
2. **Origen/fuente:** ¿de dónde vienen las reglas? (dioses, biología, instituciones, tecnología, naturaleza…)
3. **Qué hace:** ¿qué permite o determina?
4. **Qué exige / qué restringe** *(antes "qué cuesta")*: ¿qué necesita para operar — un **recurso**, una **condición** (consecuencia), o **nada** porque es impersonal? Si no exige nada, ¿por qué, y qué restringe en su lugar?
5. **Límites:** ¿qué no puede / cuándo falla? → **siempre obligatorio**.
6. **Acceso** *(condicional)*: ¿quién puede usarlo/participar/ser afectado, y mediante qué? → **N/A si el sistema es impersonal** (sin agente/operador).
7. **Consecuencia:** ¿qué implica para el mundo? (enlaza otros pilares)
8. **Estado de verdad:** `canon_state` (§3).
9. **Estabilidad:** ¿reglas **fijas** o **mutables**? (intrínseco a los sistemas institucionales). **Los cambios concretos —de reglas o de estado— se narran en la forma `Cronología`, NO aquí** (§4.5).

> **Eje de agencia:** los sistemas con **operador** (magia, tecnología, ley) responden 4 y 6; los **impersonales** (leyes naturales, cosmología) declaran 4 como "sin costo, impersonal" y marcan 6 como **N/A**.

### 4.2 Ramificación por clase (parámetro declarativo, no código) **[LOCK]**
La respuesta a **(1)** elige un **paquete de vocabulario** que re-instancia **(2)–(7)** en los términos del dominio. Clases (por **ORIGEN**, **una sola** por sistema):
`material/construido` · `innato/biológico` · `otorgado/divino` · `natural/cósmico` · `social/convencional`.

Ejemplo de la pregunta 4 re-instanciada: magia → *energía/material*; economía → *escasez*; ley → *sanción*; La Fuerza → *nada material: la disciplina y el tirón al lado oscuro*.

> **Clase única, por ORIGEN.** Se **rechazan** las etiquetas combinadas: vuelven ambigua la rama (¿qué vocabulario aplica?), explotan en combinaciones (2ⁿ), diluyen la decisión de clasificar y multiplican los tests. Un sistema que "se comporta" distinto a su origen (ej. la Selva Oscura: origen `natural`, comportamiento social) describe eso en el **cuerpo**, no en la clase.
> `duro/blando` **no** es clase: es un **eje aparte** (rigor). Un sistema blando responde (4) **justificando**, no evitando.

### 4.3 Rieles 40% (siempre verificables, pero semánticos — no campos)
Un sistema está **incompleto** si no responde **origen (2) + exigencia-o-justificación (4) + límite (5)**. No son columnas de una ficha: son preguntas que **deben tener respuesta**. (En sistemas impersonales, la pregunta 4 se responde como "sin costo, impersonal".)

### 4.4 Validación anti-sobreajuste (corregida)
Hay que validar contra **al menos un sistema NO-mágico** (economía, ley o religión). La lista anterior (Vibrastal, La Fuerza, Dune, HP, Red Rising) era **toda mágica/blanda → sesgo de sobreajuste**.

**Resultado — estresado contra *Rebelión en la granja* y *El problema de los tres cuerpos*:**
El método **aguanta**: las 8 preguntas se responden en ambos. Pero aparecieron **4 estirones**:
- **P4 "qué cuesta"** debe leerse como **"qué exige/restringe"**: el costo puede ser *recurso* (magia), *consecuencia* (Selva Oscura: la exposición) o *inexistente-impersonal* (ley física). → reformular.
- **P6 "acceso" no siempre aplica** (leyes naturales, sistemas universales sin operador) → marcar **N/A** cuando no hay agencia.
- **HUECO NUEVO — sistemas que MUTAN**: Animal Farm reescribe sus reglas; el sistema tres-cuerpos pasa de era estable a caótica; la Selva Oscura cae ante quien trasciende la velocidad de la luz. El método asume el sistema **estático** → falta un eje de **dinámica/estabilidad**.
- **Hueco #8 confirmado**: Animal Farm tiene **canon + creencia + leyenda en el mismo sistema** → `canon_state` por ficha es **demasiado grueso**; el análisis debe bajar a **afirmación/regla**.

### 4.5 Decisión: el tiempo vive en `Cronología` (visión A) **[LOCK]**

El Owner eligió la **visión A**: la historia es una **forma** (`Cronología`), no un eje transversal.

- `Sistema` **solo declara** estabilidad (pregunta 9); los cambios —de reglas o de estado— se narran en `Cronología`.
- **Descartada la visión B** ("todo hecho lleva fecha de verdad"): implicaba volver el tiempo un campo del envelope y construir un motor temporal transversal (envelope + storage + grafo + UI). Costo desproporcionado para el MVP.
- **Mutación de REGLAS** (intrínseca a sistemas institucionales: economía, ley, religión, política, sociedad, tecnología) vs **evolución de ESTADO** (naturales/impersonales: física, cosmología, sistemas estelares). **Ambas son temporales → `Cronología`.**
- **Consecuencia:** el hueco #8 (`canon_state` por ficha) **sigue abierto** bajo A.
- **Tensión abierta de taxonomía:** la Selva Oscura es `social` **y** `natural` a la vez → resolver si la clase es **única o combinada**.

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

### Huecos resueltos por el reencuadre de §4
- **#1 "fuga de blanda"** y **#2 "registro de forma mágica"**: eran el **mismo error** — un registro estructural fijo. Al volver a **preguntas semánticas** (§4.1), "blando" pasa a ser una *respuesta justificada* a la pregunta 4, y el límite (5) nunca se evade.
- **#7 "cuerpo emergente vs consumo por máquina"**: **RESUELTO** — el cuerpo se queda **emergente**; el taller consumidor **extrae** lo que necesita en tiempo de lectura. Agregar estructura ahora = **sobre-ingeniería** (aún no se conoce el mecanismo de consumo).

- **Taxonomía resuelta (§4.2):** clase **única por origen**; se rechazan las combinadas.
- **#12 Composición / integración con Hermes**: **RESUELTO** a nivel de diseño → ver **§10**.

### Huecos que SIGUEN abiertos
1. **#8 `canon_state`**: **DIFERIDO** (YAGNI). Hoy es **plomería**: se deriva, se indexa y se expone por MCP, pero **ningún feature lo consume** (ni filtro ni display). Se decide su granularidad **cuando exista un consumidor real**. Nota: la verdad narrativa es **fluida** → **sin estado "principal"**; si se refina, será **acumulativo (tags)**, no exclusivo.

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

1. ~~Validar contra un sistema NO-mágico~~ → **HECHO** (§4.4).
2. ~~Hueco #12 (composición)~~ → **RESUELTO a nivel de diseño** (§10). Siguiente: **pre-mortem del diseño de integración**, y luego implementar por slices.
3. **Hueco #8** (`canon_state`): **DIFERIDO** hasta que exista un consumidor real.
4. **(Opcional) Cablear `register_minimums`** a config del mundo + versión de OKF.

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
- `sdd/sistema-method/validation` (#3638) — validación anti-sobreajuste.
- `sdd/sistema-method/time-ownership` (#3639) — el tiempo en `Cronología` (visión A).
- `architecture/co-creation-principle` (#3644) — co-creador, no escupe-info.
- `sdd/hermes-integration/decisions` (#3646) — decisiones de integración (0–4).
- `architecture/hermes-product-runtime` (#3647) — runtime real del producto.
- `sdd/hermes-integration/how` (#3648) — diseño del "cómo" (A/B1/C1/D/E1).
- `architecture/hermes-skills-indexing` (#3649) — caché/índice de skills de Hermes.
- `nec/checkpoint` (#2351) — checkpoint de sesión.

---

## 10. Integración con Hermes — resolución de #12 **[LOCK]**

Se **reutiliza el mecanismo nativo de skills de Hermes**; **no** se construye índice/router propio. Verificado en el código de Hermes (`~/.hermes/hermes-agent/`).

### 10.1 Estado real del producto (verificado)
- El asistente del producto corre como **`hermes gateway run`** (puerto 8642, lanzado por `scripts/start-demiurgos.sh`), usando el **perfil activo**.
- Habla por la **API de agent runs** (`/v1/runs`) para `/ai/ask`; OpenAI-compatible para tareas auxiliares.
- Hoy la metodología entra **solo** como **texto inyectado** (router + proyección server-side). **No usa skills nativas.**
- El perfil `demiurgos-mcp` es **solo de desarrollo/OpenCode**, no del producto.

### 10.2 Cómo funciona el mecanismo nativo de Hermes
- Skill = carpeta con `SKILL.md` (frontmatter + cuerpo), en `~/.hermes/skills/` o en `skills.external_dirs`.
- **Índice** = caché en proceso + snapshot en disco (`.skills_prompt_snapshot.json`), validado por mtime/size. El modelo ve el **índice chico** y **carga** el `SKILL.md` on demand.
- Hermes **cachea el índice en memoria**; cuando Hermes escribe una skill por su cuenta, limpia la caché. Si un proceso **externo** escribe archivos, hay que **avisarle** o el índice queda viejo.

### 10.3 Decisiones **[LOCK]**
- **A — Perfil propio y aislado.** Demiurgos corre su **propio perfil** de Hermes (no el personal del usuario); solo Demiurgos lo invoca; sin las skills globales.
- **B1 — Un solo canal.** Las metodologías pasan a ser **skills nativas**; se **retira** el router + la proyección server-side. Nada de doble guía.
- **C1 — Carpeta propia de Demiurgos.** Los `SKILL.md` viven en una carpeta de Demiurgos; el perfil apunta ahí (`skills.external_dirs`).
- **D — Render y gatillo.** Metodología → `SKILL.md`: `name`; `description` = **gatillo "cuándo usarme"** (lo **escribe** quien crea la skill; se **muestra al usuario para aprobar/aportar**); `metadata` (version/scope); cuerpo (`source` + **reglas de co-creación siempre**); adjuntos como archivos extra.
- **E1 — Dos carpetas.** **Transversal** (siempre) + **mundo activo** (específicas); el perfil apunta a ambas; al cambiar de mundo solo se reescribe la del mundo.
- **E-2 — Sincronización.** El materializador escribe los archivos **y dispara la invalidación de caché de Hermes** (requisito técnico; vía exacta a definir en implementación).

### 10.4 Invariantes a preservar (hacerlo bien)
Consentimiento antes de crear · una pregunta por turno · retirar el canal viejo de verdad · aislamiento · disponibilidad por mundo · versión publicada inmutable · degradación segura si falta el toolset o la carpeta.

### 10.5 Detalles técnicos pendientes (implementación)
- Vía exacta de recarga/invalidación de caché de Hermes.
- Asociación perfil ↔ `skills.external_dirs`.
- Render fino (`source` → cuerpo del `SKILL.md`).
- Superar el contrato **SR1–SR6** (`skill-runtime-consumption-contract.md`) y rehacer el **flujo guiado** como skill.

---

## 11. Pre-mortem del diseño de integración (§10) — 4 lentes

Ejercicio adversarial con 4 especialistas: **runtime Hermes** · **migración/contratos** · **datos/consistencia** · **producto/UX/aislamiento**.
**Veredicto:** el norte es correcto (skills nativas), pero hay **una suposición central sin verificar** y varias costuras no triviales. **No conviene el big-bang.**

### P0 — bloquean "hacerlo bien"
1. **El canal nativo no está probado.** El producto invoca a Hermes como *run* sin estado; el toolset `skills` está **apagado** para `api_server` (`~/.hermes/config.yaml:92-99`). Sin eso, el "único canal" queda **vacío**. → **RESUELTO:** habilitar `skills` en `platform_toolsets.api_server` del **perfil dedicado** + **vetar `skill_manage`** con un hook **`pre_tool_call`** (`{"action":"block"}`, `hermes_cli/plugins.py:1771-1786`), registrable en el plugin del gateway o como hook shell (`hermes hooks`). Hermes **no** permite deshabilitar tools individuales (los toolsets son atómicos, `toolsets.py:98-102`), pero `pre_tool_call` **veta** la tool y es **fail-closed**. → **B1 es viable.**
2. **Escrituras externas no invalidan la caché en proceso.** Borrar el snapshot no alcanza. → seam **en proceso**: el plugin del gateway ya registra `pre_llm_call` (`.hermes/plugins/demiurgos-idea-capture/__init__.py:439`) y puede llamar `clear_skills_system_prompt_cache()`.
3. **Una sesión viva no se actualiza** aunque se limpie la caché (restaura su system prompt). → **sesión nueva por mundo/revisión** (o época de capacidades).
4. **El consentimiento es del servidor.** Un gatillo en el `SKILL.md` **no tiene costura de token** → abriría la creación **sin** consentimiento (o nunca). → el gate **sigue siendo del servidor**.
5. **SR1 (slot por flujo) no tiene análogo nativo.** Dos carpetas no expresan `guided-character` vs `co-creation`.
6. **Se pierden garantías de SR1–SR6**: fail-open (SR3), proyección acotada + digest (SR4), specimen de convergencia (SR6), y el **fail-closed por drift de versión**.
7. **Segunda fuente de verdad sin reconciliación.** `library.json`/seeds vs `SKILL.md`: huérfanos tras borrar/desactivar; sin verificación.
8. **Aislamiento real no logrado.** El instalador escribe en el `~/.hermes` **personal** (`install.sh:52,230-251`) y el producto sigue el `active_profile`; `assistant_settings` leería/escribiría la config y las claves del usuario.
9. **Carpeta generada en ruta excluida de backup y trackeada por git** (`<repo>/skills`). → ponerla bajo `data/methodology/` (con backup) + gitignore.
10. **Versión inmutable vs archivo mutable.** Un archivo por `skill_id` no representa dos versiones.

### P1/P2 — destacados
- La `description` de la skill se **trunca a 57 chars** en el índice → el gatillo debe ser **≤57**.
- `external_dirs` **cachea la existencia**; swaps en la misma ruta no invalidan.
- **Colisiones de nombre**: una skill externa con nombre ya ocupado **se salta en silencio**.
- Retirar `contract_projection` **rompe imports** (`convergence_injection.py:16` importa `_estimate_tokens`).
- Fuga de identidad (`SOUL.md`) y de **lore cross-world** (graph search sin scope).
- **Degradación silenciosa**; falta la **superficie de aprobación del gatillo**; "una pregunta por turno" no queda forzada.
- Retiro masivo: tests/docs que asertan el canal viejo.

### Veredicto operativo
Migración **por etapas**, manteniendo el canal viejo hasta **probar** el nativo; y **el consentimiento se queda del lado del servidor**.

---

## 12. Plan por etapas (implementación)

Migración **por etapas**; el producto **sigue funcionando** hasta la Etapa 3. Regla: Etapas 0–2 **no cambian el comportamiento visible**; la Etapa 3 es el único corte.

### Etapa 0 — Cimientos (aditivo)
1. **Perfil Hermes propio y aislado** (`HERMES_HOME` dedicado; el instalador deja de escribir en el `~/.hermes` personal).
   - **Consecuencia aceptada (aislamiento):** el perfil dedicado **no hereda** el modelo/proveedor/clave del perfil personal. Quien actualice con `--with-cli-stack` reconfigura **una sola vez** por Assistant Settings contra el perfil dedicado ahora activo (los valores se persisten en `<dedicated root>/config.yaml` y su `.env`; el `~/.hermes` personal no se modifica). Es una consecuencia aceptada del aislamiento, **no una regresión**; un perfil dedicado sin credenciales es un estado conocido y no bloquea el arranque.
2. **Carpeta de skills de Demiurgos** (`data/methodology/skills/`) + `external_dirs` + gitignore + **fix** del instalador (merge, no append).
3. **Hooks del gateway**: `pre_tool_call` (veta `skill_manage`) + `pre_llm_call` (invalida la caché de skills).
   - **Fallback fail-open (registro ausente):** el veto solo puede actuar a través de un callback **registrado**. Si el plugin de proyecto no se carga (`plugins.enabled` sin el plugin o `HERMES_ENABLE_PROJECT_PLUGINS` sin definir), Hermes no puede vetar `skill_manage` por esta vía — el hueco es **fail-open por diseño** y está mitigado por el fallback documentado: escribir una entrada `hooks.pre_tool_call` en el `config.yaml` del perfil dedicado que ejecute un script pequeño llamando a `skill_manage_veto("$TOOL_NAME")` (los shell hooks son la única superficie de registro con matcher por herramienta).
   - **Observabilidad de arranque:** el estado de registro es observable en el gestor de plugins (eventos de hook registrados: `pre_gateway_dispatch`, `pre_llm_call`, `pre_tool_call`) y en los logs del gateway (la carga del plugin emite los nombres de hook registrados); un registro ausente es detectable, no silencioso. Nota de la sonda: `hermes hooks list` solo lista shell hooks de config, no callbacks de plugin. La sonda de integración de este cambio verifica que ambos hooks estén vivos antes de que la Etapa 3 (el corte) pueda encender el toolset.

### Etapa 1 — Materializador (aditivo; escribe a *staging*, sin conectar)
4. **Render** metodología → `SKILL.md` (gatillo ≤60; `version`/`scope`; cuerpo = método + reglas de co-creación; adjuntos; namespaces).
5. **Materializador + reconciliación** (transversal + mundo; atómico; GC de huérfanos contra la biblioteca).
6. **Sesión nueva por mundo/revisión**.

### Etapa 2 — Superficie de aprobación
7. **Gatillo visible y aprobable** en la revisión del Taller; no publicar sin gatillo.

### Etapa 3 — El corte (riesgoso; último)
8. **Encender el canal nativo + apagar la proyección** (flag por mundo; sin doble guía).
9. **Rehacer el flujo guiado como skill**; el **consentimiento queda server-side**.
10. **Retirar** `skill_router` + `contract_projection` (rewiring de imports como `convergence_injection.py:16`) + **portar tests**.

### Etapa 4 — Cierre
11. Backup/restore del perfil y la carpeta; docs; evidencia de migración.
