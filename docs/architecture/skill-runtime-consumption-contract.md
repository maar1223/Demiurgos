# Contrato de Consumo de Skills en Runtime

> **Contrato de consumo.** Este documento es el contrato **normativo de consumo** de las **Skills** de Demiurgos en el **runtime**: activación por tipo de flujo guiado, enrutamiento e inyección en chat, adjuntos `skill@version` y ejes de vocabulario. **No es un artefacto SDD** ni sustituye a la constitución global. El contrato del **subsistema técnico** (biblioteca gestionada, paquete/manifest, compilador, runtime, ciclo de vida, import/export/cuarentena y creación guiada de personajes) vive en `docs/architecture/skill-library-and-guided-character-creation.md` y la **superficie** en `docs/architecture/tool-workshop.md`; este documento los referencia sin repetirlos. Toda afirmación lleva la etiqueta de estado correspondiente; lo no implementado no se presenta como existente.

| Campo | Valor |
|---|---|
| Estado | Contrato de consumo de skills en runtime (nuevo) |
| Versión del documento | 1.0 |
| Fecha | 2026-09-11 |
| Autor | Demiurgos (orquestación) |
| Idioma | Español neutro (prosa técnica) |
| Alcance | Consumo en runtime de las Skills: activación por tipo de flujo guiado (§2), política de enrutamiento e inyección (§3), adjuntos `skill@version` con digest (§4), ejes de vocabulario (§5), constantes (§6), evidencia actual (§7), decisiones cerradas SR1–SR6 (§8) y auditoría del corpus de skills (Apéndice A) |
| Depende de | `docs/architecture/demiurgos-platform.md` (constitución global del producto), `docs/architecture/skill-library-and-guided-character-creation.md` (subsistema técnico), `docs/architecture/tool-workshop.md` (superficie del Taller de Herramientas), `docs/architecture/world-workshop.md` (Taller de Mundo) |
| Relación con SDD | Requisito previo. Ningún SDD de enrutamiento, activación, adjuntos o vocabulario debe comenzar sin este contrato aprobado; los cambios de código que este contrato prescribe se ejecutan como PRs encadenados posteriores (sección 9, seguimiento) |
| Documentos relacionados | `docs/architecture/demiurgos-platform.md`, `docs/architecture/skill-library-and-guided-character-creation.md`, `docs/architecture/tool-workshop.md`, `docs/architecture/world-workshop.md`, runtime en `src/tools/demiurgos-suite/wiki/` y `frontend/src/` |

## Leyenda de etiquetas

| Etiqueta | Significado |
|---|---|
| `[ACTUAL]` | Comportamiento que existe hoy en el repositorio y está verificado |
| `[OBJETIVO]` | Comportamiento objetivo acordado, no necesariamente implementado aún |
| `[PROPUESTO]` | Diseño propuesto; requiere decisión antes de ser contrato |
| `[DECISIÓN ABIERTA]` | Punto sin resolver que requiere aprobación explícita del Autor |
| `[DECISIÓN CERRADA]` | Decisión ya aprobada; no debe revertirse sin nuevo acuerdo explícito |

**Prefijos de anclas.** Todas las citas `archivo:línea` de este documento usan dos prefijos declarados una sola vez: `wiki/` = `src/tools/demiurgos-suite/wiki/` y `fe/` = `frontend/src/`. Cada ancla se re-verificó contra HEAD en el momento de redactar (sección 7).

---

## 0. Relación con la constitución y con los contratos hermanos

- La **definición global del producto** (qué es Demiurgos, principios, mapa del sistema, conceptos canónicos, superficies, límites de dominio y decisiones globales G1–G15) vive en `docs/architecture/demiurgos-platform.md`. **Este documento no la duplica.**
- El **subsistema técnico** de las Skills (biblioteca gestionada por el Autor, paquete `.zip`/manifest, compilador/validador, runtime, ciclo de vida de versiones, import/export/cuarentena y creación guiada de personajes) está contratado en `docs/architecture/skill-library-and-guided-character-creation.md`. Este documento contrata **cómo el runtime consume** esas Skills: qué se activa, qué se enruta, qué se inyecta y con qué vocabulario. **Sin duplicar el subsistema.**
- La **superficie** del Taller de Herramientas (selector de Taller, árbol contextual, estados visibles, categorías funcionales, Skill Madre, co-creación) está contratada en `docs/architecture/tool-workshop.md`. La detección de solapamientos de ese contrato (TW4/TW7) es de **tiempo de catálogo/creación** — recomienda, no bloquea — y **no** es una política de colisiones de runtime. Este documento contrata las colisiones de runtime (§3). `[DECISIÓN CERRADA]`
- La **frontera con el orquestador**: los **workflows narrativos del orquestador** (`Agente_Maestro.md`, `src/commands/narrative-*`, `src/prompts/narrative/`) son un **subsistema narrativo existente que no es dominio de este contrato** (world-workshop §6). Las Skills que viven allí comparten **nombres** con slugs del router; esa colisión de nombres **no** convierte a los activos del orquestador en activos muertos del runtime (Apéndice A). `[DECISIÓN CERRADA]`
- En caso de conflicto, prevalece la constitución; la contradicción se reporta al Autor.

---

## 1. Definición del dominio: consumo de skills en runtime

**[DECISIÓN CERRADA]** El **consumo en runtime** es el conjunto de decisiones que el servidor toma sobre las Skills **mientras conversa con el Autor**: qué Skill gobierna un flujo guiado, qué Skill (si alguna) moldea un turno de chat libre, qué ejemplos adjunta y con qué vocabulario se presentan sus estados.

| El consumo en runtime ES | El consumo en runtime NO es |
|---|---|
| La activación por tipo de flujo guiado y su pinning de sesión (§2) | El catálogo o la conciencia del inventario (TW7, tiempo de catálogo) |
| El enrutamiento de intención a una Skill y la inyección acotada en el turno (§3) | La co-creación o la adaptación de Skills (superficie, tool-workshop §§5–6) |
| Los adjuntos `skill@version` digest-pinned que alimentan la convergencia (§4) | El contenido de canon ni las Referencias del mundo (world-workshop) |
| Los ejes canónicos de vocabulario de estado (§5) | La copia visible final (pase de copy posterior, fuera de alcance) |

- **El pool de candidatos del router** es la unión de **compañeros del mundo ∪ slot de activación ∪ transversales** (`wiki/skill_router.py:94-104`, `:208-250`). Solo el **ganador** de la clasificación puede inyectar, y solo si es compañero del mundo (`wiki/api_server.py:5508-5533`). `[ACTUAL]`
- Las **constantes** que acotan estas decisiones (umbral de confianza, margen de empate, capas de adjuntos, presupuesto de tokens) son **normativas** y viven en la sección 6. `[DECISIÓN CERRADA]`
- Los **requisitos SR1–SR6** de este contrato se cierran en la sección 8, cada uno anotado con su origen (D1–D6, ledger #3149). `[DECISIÓN CERRADA]`

---

## 2. Activación por tipo de flujo guiado `[ACTUAL]` — SR1

**[DECISIÓN CERRADA — SR1, origen D1]** Cada mundo tiene **un slot de activación por tipo de flujo guiado**, no uno solo global. Implementado en el PR ① (`per-flow-activation-schema`): los slots viven en `self._activations = {world: {flow_type: record}}` (`wiki/methodology_library.py:248-249`), con `activate(..., flow_type)` (`:795-830`) y `active_for(world, flow_type)` (`:832-839`). `[ACTUAL]`

- **Estado por tipo de flujo**: cada slot se expresa **Activada/Desactivada por flujo** (la copia exacta de la etiqueta se resolvió en el pase de copy del PR ⑥). El estado es por `flow_type` en el runtime (`wiki/methodology_library.py:832-839` `active_for(world, flow_type)`) y se presenta como chip de eje activación-por-flujo en la UI (`fe/lib/vocabularyAxes.ts:57-72` `activationChip`; `fe/components/organisms/MethodologyStatePanel.tsx:211` `data-flow-type`). `[ACTUAL]`
- **Pinning de sesión**: al iniciar una sesión guiada, `skill@version` queda fijado para toda la sesión (`wiki/api_server.py:2183`, `:5904` — snapshot en la creación de la sesión); **todas las continuaciones** de la sesión inyectan el contrato compilado activo (`wiki/api_server.py:2081`). `[ACTUAL]`
- **Deriva de versión**: reanudar una sesión cuyo pin no coincide con la versión activa **se rechaza** y se fuerza una sesión nueva (`wiki/api_server.py:1995-2012`). `[ACTUAL]`
- **Sin activación**: si el mundo no tiene slot activo para el flujo, aplica la creación guiada integrada `guided-character-v1` (`wiki/api_server.py:1855-1860`, `:1780`). `[ACTUAL]`
- **El slot nunca inyecta en chat libre**: la inyección en chat no guiado ocurre **solo** cuando el ganador del enrutamiento es compañero del mundo (`wiki/api_server.py:5508-5533`; docstring `:5516-5517`: los ganadores no-compañero, incluidos los transversales, **nunca inyectan**). El slot **sí** permanece como candidato de enrutamiento (`wiki/skill_router.py:102-103`, `:236-245`), pero no inyecta. `[ACTUAL]`
- **Detección de intención de chat** `[OBJETIVO — DIFERIDO]`: si el chat expresa intención de flujo guiado (p. ej. crear personaje), la detección de intención **abre el flujo guiado correspondiente con su Skill**; el turno de chat en sí no recibe inyección del slot. **Estado verificado (2026-09-13):** hoy **no** se auto-abre. El comportamiento implementado es un **redirect acotado a nivel chat** (`wiki/api_server.py:5695` `_skill_creation_redirect`, REQ-CC-2/TW9): el asistente recomienda ir al Taller y **el Autor decide** ("no auto-detected co-creation session, no auto-navigation"). El detector de intención `route_new_character_intent` (`wiki/guided_character_domain.py:208`) solo corre en el arranque del flujo guiado, iniciado por el cliente, y la capa de keywords del router se retiró en el PR ②. Auto-abrir es una **decisión de producto pendiente**: implementarlo (gira a `[ACTUAL]`) o reescribir el bullet al comportamiento de redirect realmente implementado (también `[ACTUAL]`).
- **Los compañeros siguen moldeando el chat libre**: el compañero ganador del enrutamiento sigue siendo la **única** inyección de chat, independiente de cualquier slot (`wiki/api_server.py:5508-5533`; `wiki/methodology_library.py:768-772` — las operaciones de compañero son "fully independent of the activation slot"). `[ACTUAL]`

**Escenarios cubiertos (spec, skill-activation-model):** sesión con pin (`Pins session`), deriva de versión (`Version drift`), sin activación (`No activation`), intención de flujo desde chat (`Flow intent`), compañero gana el turno (`Companion wins`).

---

## 3. Política de enrutamiento e inyección `[OBJETIVO]` — SR2, SR3

**[DECISIÓN CERRADA — SR2, origen D2]** La política del **pool transversal** debe derivar de la **auditoría del corpus** (Apéndice A): cada entrada se clasifica como **recuperable / a rehacer / legado** y la composición del pool se fija **después** de la auditoría, no antes. `[DECISIÓN CERRADA]`

- **Pool actual (tras PR ②)**: `TRANSVERSAL_SKILLS = {narrative-character-creation}` (`wiki/skill_router.py:30-32`) con comentario de trazabilidad de auditoría (1 recuperable / 19 legado, `:25-29`); los 6 slugs fantasma y la capa de keywords se retiraron en el PR ② (sección 9). `[ACTUAL]`
- **Pool derivado (consecuencia de la auditoría del Apéndice A)**: la auditoría clasifica 1 recuperable y 19 legado; el pool transversal derivado se reduce a **compañeros del mundo ∪ slot activado (`GUIDED_CHARACTER_FLOW`) ∪ el transversal fundacional `narrative-character-creation`** (`wiki/skill_router.py:85-95`, `:189`). Los 19 legado **no** son miembros del pool. La unión de slots de **todos** los flujos (incluido `CO_CREATION_FLOW`) queda **diferida**. `[ACTUAL]`
- **Trazabilidad**: toda afirmación de membresía transversal se **traza a una clase de auditoría** (Apéndice A); ningún slug fantasma queda en el pool (`wiki/skill_router.py:25-32`, comentario de auditoría). `[ACTUAL]`
- **El dominio del orquestador no se retira**: los activos de flujo de trabajo (`src/prompts/narrative/`, `src/commands/narrative-*`, `Agente_Maestro.md`) **no se retiran ni se declaran muertos** por este contrato; siguen vivos como subsistema narrativo del orquestador (sección 0). Lo que este contrato declara es **solo** su **ausencia del pool del router** (Apéndice A). `[DECISIÓN CERRADA — D2]`

**[DECISIÓN CERRADA — SR3, origen D3]** El enrutamiento de compañeros es **fail-open** ante ambigüedad. Ambigüedad ⇔ (confianza del ganador `< 0.7`) **O** (diferencia top-2 entre candidatos clase compañero `< NEAR_TIE_MARGIN = 0.15`). Implementado en el PR ② (`wiki/skill_router.py:327-338`). `[ACTUAL]`

- **Ante ambigüedad**: **cero inyecciones** (`skill_id=None`; `source="ambiguous"` para empate cercano de compañeros, `source="fallback"` para modo degradado; `wiki/skill_router.py:305-307`, `:338`). Reemplaza el antiguo "primer ganador silencioso" (umbral único). `[ACTUAL]`
- **El clasificador reporta top-2**: el prompt con descripciones (mundos con compañeros) pide `runner_up_skill_id`/`runner_up_confidence` (`wiki/skill_router.py:257-260`); el parse tolera ausencia/malformación → `None` (`:143-156`). El prompt bare-id (sin compañeros) queda byte-idéntico (`:159`). `[ACTUAL]`
- **La regla del margen aplica solo cuando ambos top-2 son de clase compañero**; con menos de 2 compañeros la regla es vacua (no hay empate posible) (`wiki/skill_router.py:332-338`). `[ACTUAL]`
- **Ruta de keywords retirada (PR ②)**: la capa de keywords (incluida la rama `route_new_character_intent`) se eliminó; el modo degradado es fail-open puro, `source="fallback"` (`wiki/skill_router.py:305-307`). `[ACTUAL]`
- **Ganador claro (status quo)**: un compañero por encima del umbral y con margen sobre el segundo sigue inyectando. `[ACTUAL]`

**Escenarios cubiertos (spec, skill-routing-policy):** inventario completo (`Inventory complete`), trazabilidad del pool (`Pool traceability`), ganador claro (`Clear winner`), empate cercano (`Near-tie`).

---

## 4. Adjuntos `skill@version` `[OBJETIVO]` — SR4

**[DECISIÓN CERRADA — SR4, origen D6]** Manifest, compilador y registro publicado incluyen un campo **adjuntos** por `skill@version`, **implementado en el PR ③** (`attachment-digests`): `adjuntos` en `ALLOWED_MANIFEST_FIELDS` (`wiki/methodology_compiler.py:67-71`). `[ACTUAL]`

- **Registro de adjunto (esquema normativo)**: `{path: .md relativo al paquete, sha256: hex sobre los bytes del paquete, bytes: ≤ 12288, nivel: "1º" | "2º" | "3º" | etiqueta-de-rama}`; entrada exacta de 4 claves exigida por el compilador (`wiki/methodology_compiler.py:458`, `AttachmentEntry` `:125-146`). `[ACTUAL]`
- **Límites**: **≤ 8 adjuntos por skill** (tope de casa, cf. `MAX_COMPANIONS_PER_WORLD` en `wiki/methodology_library.py:187-189`) y **≤ 12288 B por adjunto** (el ejemplar existente más grande, `Villano_Korrane.md` = 9802 B, con ~25% de holgura) — `MAX_ADJUNTOS`/`MAX_ADJUNTO_BYTES` en `wiki/methodology_compiler.py:55-56`. `[ACTUAL]`
- **Digest-pinning**: los adjuntos quedan **fijados por SHA-256** en el registro publicado (mismo algoritmo que `checksums.json` de las semillas, `data/methodology/seeds/narrative-character-creation/`); la semilla verifica el pin (PR ③). `[ACTUAL]` El runtime **sirve solo los bytes del digest fijado**, re-verificando el sha256 contra el pin en cada servicio: seam `serve_adjunto` (`wiki/convergence_injection.py:23`); la retención post-publish la hace el upsert del pin en el registro publicado al instalar la semilla (`wiki/methodology_library.py:696-705`). Implementado en el PR ④ (`convergence-injection`). `[ACTUAL]`
- **Fallo en build/publish**: un **desajuste de digest** (el adjunto cambió tras publicarse) **falla el build/publish**; no existe auto-curado — verificado en `wiki/methodology_seed.py:146-172` (`_verify_entry`, `SeedIntegrityError`); overflow de publish → 422 `attachment_limit_reached` (`wiki/api_server.py:7818-7822`). `[ACTUAL]`
- **Fuera de mundos/referencias**: los ejemplos **nunca** viven bajo `mundos/{world}/referencias/` — el indexador trata `referencias/` como entidades de grafo (`wiki/graph_indexer.py:46`, `:55`), y colocarlos allí **contaminaría el grafo**. La validación de publish **rechaza** rutas `mundos/**`/`referencias/**` — implementada en el compilador (PR ③, `invalid-value` en `wiki/methodology_compiler.py:467-546`). `[DECISIÓN CERRADA — origen D5/D6]`
- **Inyección en convergencia**: el runtime inyecta el espécimen terminado en la fase de **propuesta/convergencia**, nunca en el primer turno; el disparo exige **ambas** compuertas sobre el estado recuperado (delta=None): `candidate_minimum_complete` **y** ≥ 1 intercambio terminado (`has_finished_exchange`, `wiki/guided_character_domain.py:115`) — `_convergence_specimen_markdown` (`wiki/api_server.py:1923-1957`, cableado `:2171-2176`); la selección es por nivel narrativo del candidato (`resolve_candidate_nivel`, `:136`): 1º/2º/3º, nivel desconocido → 1º; el bloque `[Convergence specimen — nivel N]` se arma en `build_specimen_block` (`wiki/convergence_injection.py:53`) desde los carriers `adjunto-nivel-{1-principal,2-secundario,3-relleno}.md` de la semilla, **1 adjunto/turno ≤ 3072 tokens estimados**; sobre presupuesto → **skip, nunca truncar** (`serve_adjunto`, `:23`); la estructura de salida sigue llegando vía la descripción de semilla en la **proyección ≤ 1000 tokens** (`wiki/contract_projection.py:99-136`, tope `:102`); el adjunto aporta los **ejemplares** dentro de su propio presupuesto (sección 6). Implementado en el PR ④ (`convergence-injection`). `[ACTUAL]`

**Escenarios cubiertos (spec, skill-example-attachments):** deriva de contenido (`Content drift`), sesión de creación guiada (`Guided creation session`), validación de publish (`Publish validation`).

---

## 5. Ejes de vocabulario `[ACTUAL]` — SR5

**[DECISIÓN CERRADA — SR5, origen D4]** El vocabulario de estado define **exactamente cuatro ejes canónicos**; cada término se ata a **un solo eje**:

| Eje | Visibilidad en la fila del árbol |
|---|---|
| **Activación por flujo** | **Visible** — chip de eje activación-por-flujo con término de registro (`[ACTUAL]`, implementado en el PR ⑤): `activationChip` (`fe/lib/vocabularyAxes.ts:57-72`) → badge atribuido en la fila (`fe/components/organisms/TallerTree.tsx:115,139`); etiqueta de slot por flujo (`data-flow-type`, modelo, cero copy por flujo) en `fe/components/organisms/MethodologyStatePanel.tsx:211` |
| **Metodología en chat** | **Visible** — estado de metodología en chat en la fila como chip atribuido (`[ACTUAL]`): `companionChip` "Método en chat" (`fe/lib/vocabularyAxes.ts:86-88`) → badge `data-axis="companion"` (`fe/components/organisms/TallerTree.tsx:116,140`); switch "Metodología de chat en {world}" y "Apagar" en `fe/components/organisms/MethodologyStatePanel.tsx:370,:375,:403` |
| **Alcance de taller** | Tooltip/panel — `[ACTUAL]`: término de alcance del registro (`SCOPE_TERM` reverse-lookup, `fe/lib/vocabularyAxes.ts:27-32,84-89`; bloque "Alcance de taller" con `data-axis="scope"` en `fe/components/organisms/MethodologyStatePanel.tsx:257-267`); los grupos del árbol conservan los labels `GROUP_ORDER` (`fe/components/organisms/TallerTree.tsx:53`) |
| **Conflicto** | Tooltip/panel — `[ACTUAL]`: `conflictExplanation` del registro (`fe/lib/vocabularyAxes.ts:96`) en tooltip de fila (`fe/components/organisms/TallerTree.tsx:142-151`) y bloque "Conflicto" del panel (`fe/components/organisms/MethodologyStatePanel.tsx:278-295`) |

- **La fila muestra solo los dos primeros ejes** (activación-por-flujo + compañero), con **atribución de eje**; alcance y conflicto van a tooltip/panel. `[ACTUAL]` (implementado en el PR ⑤: `AxisBadge` con chip de registro y `data-axis`, `fe/components/organisms/TallerTree.tsx:71-75,115-116,139-140`; tooltip accesible `fe/components/atoms/Tooltip.tsx:29-36`)
- **Prohibido: contradicción entre ejes sin atribución.** Una metodología en chat que no es el slot activo muestra hoy "Inactiva" (eje slot) junto a "Método en chat" (eje compañero) — una contradicción entre ejes sin etiquetar. El modelo muestra el estado del slot (eje 1) + el estado de metodología en chat (eje 2), cada uno **atribuido a su eje**; nunca la combinación desnuda "Inactiva + Método en chat". `[ACTUAL]` (PR ⑤: cada término se renderiza como chip separado atribuido a su eje, `fe/components/organisms/TallerTree.tsx:115-116,139-140`; el escenario "Companion not active" verifica que la combinación desnuda es imposible, `fe/__tests__/TallerTree.test.tsx:142`)
- El modelo de estados máquina subyacente (`fe/lib/tallerStates.ts:12-17` `SkillState`, derivación `:53-98`) **no cambia** en este contrato; solo se define a qué eje pertenece cada término. `[ACTUAL]` (verificado: diff cero sobre `tallerStates.ts` en el PR ⑤)
- El **rename del eje-2** (registrado para el pase de copy en este contrato) se ejecutó en el PR ⑥ (`copy-polish-pass`): **"Metodología en chat"** (nombre del eje) / **"Método en chat"** (chip de fila); el switch del panel pasa a "Metodología de chat en {world}". `[DECISIÓN CERRADA — D4]`
- **Método, no voz/persona** (base del rename, `[DECISIÓN CERRADA — D4]`): el mecanismo inyecta **solo la proyección de contrato ≤ 1000 tokens** (el método), nunca el contenido de voz/persona de la skill — por eso "Metodología en chat" es un descriptor metodológico y no una figura compañera re-romantizada. `[ACTUAL]`

**Escenarios cubiertos (spec, skill-vocabulary-axes):** inspección de fila (`Row inspection`), compañero no activo (`Companion not active`).

---

## 6. Constantes normativas

| Constante | Valor | Fundamento (ancla) |
|---|---|---|
| Umbral de confianza del ganador | **0.7** | `wiki/skill_router.py:36`, `:332` (hoy); normativa §3 |
| Margen de empate cercano `NEAR_TIE_MARGIN` | **0.15** | Decisión D3 (design #3152); normativa §3 |
| Algoritmo de digest de adjuntos | **SHA-256** | Coherente con `checksums.json` de semillas |
| Adjuntos máximos por skill | **≤ 8** | Tope de casa; cf. `MAX_COMPANIONS_PER_WORLD` `wiki/methodology_library.py:187-189` |
| Tamaño máximo por adjunto | **≤ 12288 B** | Ejemplar mayor existente `Villano_Korrane.md` = 9802 B + ~25% |
| Inyección de convergencia | **1 adjunto/turno, ≤ 3072 tokens estimados** | Implementado en el PR ④ — `MAX_SPECIMEN_TOKENS = 3072` (`wiki/convergence_injection.py:19`); = bytes/4, mismo heurístico `_CHARS_PER_TOKEN` que la proyección (`wiki/contract_projection.py:23`); **fuera** de la proyección ≤ 1000 tokens (`:102`) |
| Peor caso de contenido de metodología por turno | **≈ 4072 tokens** | 1000 (proyección) + 3072 (convergencia) |

---

## 7. Evidencia de implementación actual `[ACTUAL]`

Estado verificado en el repositorio contra HEAD en el momento de redactar (todas las anclas re-verificadas; las correcciones frente a la exploración #3148 se anotan en el progreso de apply):

| Capacidad | Evidencia |
|---|---|
| Pool transversal audit-derivado (1 transversal fundacional) | `wiki/skill_router.py:25-32` — `TRANSVERSAL_SKILLS = {narrative-character-creation}` con comentario de trazabilidad de auditoría (1 recuperable / 19 legado); los 6 slugs fantasma se retiraron en el PR ② |
| Umbral de confianza 0.7 y margen de empate `NEAR_TIE_MARGIN = 0.15`; capa de keywords retirada (PR ②), modo degradado = fail-open puro | `wiki/skill_router.py:34` (umbral), `:41` (margen), `:305-307` (fail-open `source="fallback"`) |
| Candidatos del pool: transversal fundacional ∪ slot activado (`GUIDED_CHARACTER_FLOW`) ∪ compañeros | `wiki/skill_router.py:85-95`, `:189` (`_companion_candidates` devuelve `(orden, companion_ids)`) |
| Clasificador LLM reporta top-2 en prompts con descripciones; prompt bare-id (sin compañeros) byte-idéntico | `wiki/skill_router.py:241`, `:257-260` (`runner_up_*`), `:143-156` (parse tolerante → None), `:159` (bare-id sin top-2) |
| `CO_CREATION_FLOW` documentado como reservado (no enlazado; PR ② WARNING-1) | `wiki/methodology_library.py:55-64` |
| Slot único de activación por mundo | `wiki/methodology_library.py:739` `active_for` |
| Compañeros independientes del slot; tope 8; un slot por skill_id | `wiki/methodology_library.py:187-189`, `:768-772` |
| Pinning `skill@version` en creación de sesión guiada y en continuaciones | `wiki/api_server.py:2183`, `:5904` (snapshot), `:2081` (inyección) |
| Rechazo de reanudación con versión distinta | `wiki/api_server.py:1995-2012` |
| Sin activación → `guided-character-v1` integrado | `wiki/api_server.py:1855-1860`, `:1780` |
| Inyección de chat solo para compañero ganador; transversales/slot nunca inyectan | `wiki/api_server.py:5508-5533`, docstring `:5516-5517` |
| Compuerta de compañero esperada antes del prompt (bridge) | `wiki/api_server.py:6478-6495` |
| Compilador acepta `adjuntos` {path, sha256, bytes, nivel} (11 campos en `ALLOWED_MANIFEST_FIELDS`) | `wiki/methodology_compiler.py:67-71`, `AttachmentEntry` `:125-146`, `_collect_adjuntos_issues` `:467-546` |
| Límites ≤ 8 adjuntos/skill, ≤ 12288 B/adjunto, `nivel` ≤ 64 chars | `wiki/methodology_compiler.py:55-57` (`MAX_ADJUNTOS`, `MAX_ADJUNTO_BYTES`, `MAX_NIVEL_LEN`) |
| Digest-canonical EXCLUYE `adjuntos` (per-attachment sha256 es el pin); digest `narrative-character-creation@1.0` = `2ae521a0…` estable | `wiki/methodology_compiler.py:274-288` (canonical fijo) |
| Publish overflow → 422 `attachment_limit_reached` (analog `companion_limit_reached`), cero mutación | `wiki/methodology_library.py:102-110` (`AttachmentLimitError`), `:531-545` (pre-check en `publish()`), `wiki/api_server.py:7818-7822` |
| Registro publicado lleva `adjuntos`; decode aditivo `.get()` → registros pre-PR③ válidos | `wiki/methodology_library.py:174` (`PublishedVersion.adjuntos`), `:656-659` (`_published_record`), `:1083-1085` (`_published_from`) |
| Semilla: `_verify_entry` verifica carrier + checksums + sha256 por adjunto cuando presente; cero adjuntos hoy → sin cambio de comportamiento | `wiki/methodology_seed.py:76`, `:146-172` |
| Portabilidad de adjuntos (export/import): el export **embebe cada carrier** en su `path` de paquete y los ata en `checksums.json`; el import **deriva la allowlist del manifest** y verifica sha256+bytes por carrier, fail-closed; las entradas no declaradas siguen rechazadas (`"unexpected entries"`) y `_ALLOWED_ENTRIES` permanece como conjunto base | `wiki/methodology_trust.py:167` (`build_package`, kwarg `attachments`), `:250` (`inspect_package`), `:46` (`_ALLOWED_ENTRIES` base) |
| Export falla-cerrado con **422 `attachment_unavailable`** cuando un carrier pinneado falta, deriva o no coincide en bytes (sin zip parcial); resuelve carriers bajo `data/methodology/seeds/{skill_id}` | `wiki/api_server.py:8096`, `:8121`, `:8128` |
| Exposición **metadata-only** de `adjuntos` en el detalle publicado y en el status (nunca bytes por API) | `wiki/api_server.py:7668` (detail), `:7698` (status) |
| Seam de bytes crudos `read_adjunto_bytes` (containment + is_file + sha256, sin presupuesto de tokens ni decode); `serve_adjunto` lo reutiliza con comportamiento idéntico | `wiki/convergence_injection.py:23` (`read_adjunto_bytes`), `:48` (`serve_adjunto`) |
| `trust()` enhebra `adjuntos=tuple(compiled.adjuntos)` al draft creado (import→trust→publish preserva los pins) | `wiki/methodology_trust.py:523`, `:560` |
| FE: tipo aditivo `MethodologyAdjunto` + `adjuntos?` en `PublishedMethodology` y bloque metadata-only (path + nivel + bytes) en el detalle, oculto cuando está vacío | `fe/api/types.ts:1519`, `:1549`; `fe/components/organisms/MethodologyDetailView.tsx:138`, `:165` |
| Proyección de contrato ≤ 1000 tokens con heurístico ~4 chars/token | `wiki/contract_projection.py:23`, `:99-136`, `:102` |
| `referencias/` indexado como entidades de grafo | `wiki/graph_indexer.py:46`, `:55` |
| Ejes de vocabulario atribuidos en la UI (PR ⑤, SR5): fila con chips de los dos primeros ejes, alcance/conflicto a tooltip/panel, cero diff en `tallerStates.ts` | `fe/lib/vocabularyAxes.ts:20-37` (enum de ejes), `:57-72` (`activationChip`), `:80-81` (`companionChip`), `:96` (`conflictExplanation`); `fe/components/atoms/Tooltip.tsx:29-36` (a11y: `aria-describedby`, `tabIndex=0`, sr-only, `aria-hidden`); `fe/components/organisms/TallerTree.tsx:71-75` (`AxisBadge`), `:115-116,:139-140` (chips atribuidos), `:142-151` (tooltip de conflicto), `:157-160` (`Adaptar` deshabilitado); `fe/components/organisms/MethodologyStatePanel.tsx:211` (`data-flow-type`), `:257-267` (bloque "Alcance de taller"), `:278-295` (bloque "Conflicto"); `fe/api/types.ts:1553` (`flow_type?` aditivo) |
| Ejemplos canónicos de salida (5, solo en docs; runtime no los referencia) | `docs/architecture/character-creation/examples/` (`Axill_Garner.md`, `Kae_Turant.md`, `Secundario_Ejemplo.md`, `Relleno_Ejemplo.md`, `Villano_Korrane.md` = 9802 B), `docs/architecture/character-creation/README.md:13-17`, `:113-119` |
| Ejemplos de técnica en dominio de skill | `skills/narrative-character-creation/references/conversation-examples.md`, citado en `docs/architecture/character-creation/README.md:146-148` |
| Servicio de bytes del adjunto (PR ④): seam sirve solo los bytes del digest fijado, sha256 re-verificado por servicio, skip silencioso ante deriva/falta/sobre-presupuesto/traversal, nunca truncar | `wiki/convergence_injection.py:19` (`MAX_SPECIMEN_TOKENS = 3072`), `:23` (`serve_adjunto`), `:53` (`build_specimen_block`); upsert del pin en instalación `wiki/methodology_library.py:696-705` |
| Inyección de convergencia (SR6, PR ④): trigger `candidate_minimum_complete` ∧ `has_finished_exchange` (nunca turno uno); bloque `[Convergence specimen — nivel N]`; nivel 1º/2º/3º, desconocido → 1º; 1 adjunto/turno | `wiki/api_server.py:1923-1957` (`_convergence_specimen_markdown`), cableado `:2171-2176`; `wiki/guided_character_domain.py:115` (`has_finished_exchange`), `:136` (`resolve_candidate_nivel`); `wiki/guided_character_provider.py:108-112` (append tras el bloque de contrato) |
| Carriers de convergencia sembrados (3): `adjunto-nivel-{1-principal,2-secundario,3-relleno}.md` (sha256 == manifest == checksums.json; bytes 9852/3638/1938; reescritos agnósticos al mundo en el PR ⑥) | `data/methodology/seeds/narrative-character-creation/` |
| Almacenamiento de carriers de autor: `data/methodology/attachments/{skill_id}/`, resuelto por `carrier_root_for(skill_id)` (usa `seeds/{skill_id}` si existe, si no `attachments/{skill_id}`); **la ubicación ES la marca de autoría** (sin campo `origin`) | `wiki/convergence_injection.py` (`carrier_root_for`); call sites `wiki/api_server.py:1951`, `:8122` |
| Autoría de ejemplares en co-creación: subida multipart a staging por sesión con guards 3–8 y cero mutación al rechazar; movimiento atómico a `attachments/{skill_id}/` al materializar; `adjuntos` enhebrado en canvas/materializer/route; UI "Ejemplares" metadata-only | `wiki/co_creation_attachments.py`; `wiki/co_creation_protocol.py` (`CANVAS_PAYLOAD_KEYS`); `wiki/co_creation_materializer.py`; `fe/components/organisms/CoCreation/CoCreationCanvas.tsx`; `fe/hooks/useCoCreation.ts` |
| Extracción en trust: un paquete importado+confiado materializa sus bytes verificados en `attachments/{skill_id}/`, cerrando el round-trip de export (antes fallaba 422) | `wiki/methodology_trust.py` (`trust(..., attachments_root=...)`) |

**No implementado (objetivo):** el slot por tipo de flujo guiado (§2, SR1) ya no es objetivo: pasó a `[ACTUAL]` en el PR ① (`per-flow-activation-schema`); los ejes de vocabulario atribuidos (§5) ya lo eran (PR ⑤).

> Regla de etiquetas: todo lo listado como `[ACTUAL]` está verificado contra el código; las superficies objetivo de las secciones 2–5 llevan su propia etiqueta y **no se presentan como implementadas**.

---

## 8. Decisiones cerradas y abiertas

### 8.1 Cerradas (no revertir sin nuevo acuerdo)

> Tabla SR1–SR6 completada en la segunda unidad de trabajo (WU2), tras cerrar el Apéndice A y el pool transversal (§3); cada fila se anota "(origen: D1–D6, ledger #3149)". Mientras tanto, los requisitos normativos están en sus secciones (§§2–6).

| ID | Decisión | Etiqueta |
|---|---|---|
| **SR1** | *(origen: D1, ledger #3149)* Un slot de activación **por tipo de flujo guiado** por mundo (extiende el `active_for` único); el slot **nunca inyecta** en chat libre; la intención de chat abre el flujo guiado con su Skill; los compañeros siguen moldeando el chat (§2). Implementado en el PR ① (`per-flow-activation-schema`) | `[ACTUAL]` |
| **SR2** | *(origen: D2, ledger #3149)* La política del pool transversal **deriva de la auditoría** (Apéndice A): 1 recuperable + 19 legado → pool = compañeros ∪ slot activado (`GUIDED_CHARACTER_FLOW`) ∪ `narrative-character-creation`; los fantasma se retiraron en el PR ②; la unión de slots de todos los flujos queda diferida; el dominio del orquestador no se retira (§3) | `[ACTUAL]` |
| **SR3** | *(origen: D3, ledger #3149)* Enrutamiento de compañeros **fail-open**: ambigüedad ⇔ confianza `< 0.7` **o** top-2 de clase compañero `< NEAR_TIE_MARGIN = 0.15` → **cero inyecciones** (genérico o preguntar); reemplaza el "primer ganador silencioso"; el clasificador reporta top-2 (§3). Implementado en el PR ② | `[ACTUAL]` |
| **SR4** | *(origen: D6, ledger #3149)* Campo **adjuntos** por `skill@version` en manifest/compilador/registro publicado, **digest-pinned** por SHA-256; ≤ 8 adjuntos/skill, ≤ 12288 B; desajuste de digest falla build/publish; nunca bajo `mundos/**/referencias/**` (§4). Implementado en el PR ③ (`attachment-digests`); digest-canonical excluido (D1); la inyección en convergencia queda en SR6 | `[ACTUAL]` |
| **SR5** | *(origen: D4, ledger #3149)* **Cuatro ejes canónicos** de vocabulario (activación por flujo, metodología en chat, alcance de taller, conflicto); la fila muestra solo los dos primeros con **atribución de eje**; alcance/conflicto a tooltip/panel; prohibida la contradicción entre ejes sin atribución; el rename del eje-2 se ejecutó en el PR ⑥ (`copy-polish-pass`) → "Metodología en chat"/"Método en chat" (§5). Implementado en el PR ⑤ (`axis-binding-ui`) | `[ACTUAL]` |
| **SR6** | *(origen: D5, ledger #3149)* Ejemplo de espécimen terminado se inyecta en la **fase de propuesta/convergencia** (nunca turno uno), dentro de su presupuesto (1 adjunto/turno ≤ 3072 tokens estimados, fuera de la proyección ≤ 1000); estructura de salida llega vía la proyección (§4/§6). Implementado en el PR ④ (`convergence-injection`): trigger `candidate_minimum_complete` ∧ `has_finished_exchange` (nunca turno uno), selección por nivel 1º/2º/3º con desconocido → 1º, sobre presupuesto → skip nunca truncar (§4/§6) | `[ACTUAL]` |

### 8.2 Abiertas (acotadas; no se expande el alcance sin consolidar primero)

> Sin decisiones abiertas pendientes en este contrato: D1–D6 quedaron cerradas (ledger #3149). Cualquier nuevo punto abierto se registrará aquí.

---

## 9. Definition of ready para SDD futuro

Un SDD de este dominio **solo** puede comenzar cuando se cumplan todos:

- [ ] Se leyeron esta constitución global, el contrato del subsistema técnico (`skill-library-and-guided-character-creation.md`), la superficie (`tool-workshop.md`) y este contrato de consumo (sección 0).
- [ ] Se verificó el runtime real (CodeGraph/tests) antes de asumir cualquier `[ACTUAL]` (sección 7); las anclas se re-verifican contra HEAD en el momento del apply.
- [ ] Las decisiones cerradas SR1–SR6 que tocan el cambio están anotadas con su origen (D1–D6, ledger #3149) y no se reabren (sección 8).
- [ ] El cambio respeta las invariantes `[ACTUAL]` (secciones 7, 8) y las fronteras de dominio: el orquestador (`Agente_Maestro.md`, `src/commands/narrative-*`, `src/prompts/narrative/`) **no** es dominio de este contrato (sección 0).
- [ ] Todo comportamiento nuevo se etiqueta `[ACTUAL]`/`[OBJETIVO]`/`[PROPUESTO]` y no se presenta como implementado.
- [ ] El SDD declara explícitamente qué NO toca (copy visible, ejemplos en `mundos/{world}/referencias/`, corpus del orquestador).
- [ ] Las pruebas cubren las invariantes afectadas (fail-open §3, digest-pinning §4, ejes §5) y las ramas de fallo relevantes.

**Seguimiento (PRs encadenados, fuera de este cambio):** ~~① slot por tipo de flujo guiado (SR1)~~ — ✅ **completado en el PR ①** (`per-flow-activation-schema`; §2 y §8.1 SR1 pasan a `[ACTUAL]`); ~~② derivación del pool + retiro de fantasma + `NEAR_TIE_MARGIN` + top-2 (SR2/SR3)~~ — ✅ **completado en el PR ②** (`pool-router-derivation`; §3 y §7 pasan a `[ACTUAL]`); ~~③ adjuntos del manifest/compilador + digest (SR4)~~ — ✅ **completado en el PR ③** (`attachment-digests`; §4 y §7 pasan a `[ACTUAL]` para la maquinaria de adjuntos; la inyección de convergencia queda en ④); ~~④ inyección de convergencia (SR6)~~ — ✅ **completado en el PR ④** (`convergence-injection`; §4 servicio de bytes + inyección, §6, §7 y §8.1 SR6 pasan a `[ACTUAL]`); ~~⑤ binding de ejes en la UI (SR5)~~ — ✅ **completado en el PR ⑤** (`axis-binding-ui`; §5 y §8.1 SR5 pasan a `[ACTUAL]`); ~~⑥ pase de copy incl. rename "Compañera"~~ — ✅ **completado en el PR ⑥** (`copy-polish-pass`; §5/§8.1 filas post-rename, SR1 drift flip aplicado, carriers agnósticos re-pinned; **la serie SR1–SR6 queda completamente entregada**). Todos encadenados, stacked-to-main, presupuesto ~400 líneas cada uno.

**Seguimiento post-serie — `adjuntos-portabilidad` (⑤a server + ⑤b FE, 2026-09-13):** cierra el hueco de portabilidad de adjuntos de §4/§7. La maquinaria de portabilidad queda `[ACTUAL]`: export embebe los carriers con sus bytes pinneados y los ata en `checksums.json`, import deriva la allowlist del manifest y valida sha256/bytes fail-closed, `adjuntos` se exponen metadata-only en detalle/status y el FE los renderiza. Invariantes preservadas: digest `2ae521a0…` inmóvil (el canonical excluye adjuntos), `methodology_seed.py` intacto y `.gitattributes` de semillas sin cambios. Verificado localmente (backend 2392/0, FE 1133/0 + tsc limpio); entrega en PRs encadenados (feature-branch-chain). **Follow-ups abiertos (fuera de este cambio):** los `[OBJETIVO]` de §2 (**:67 detección de intención de chat** — diferido: hoy el chat ofrece un redirect acotado y el Autor decide, no auto-abre; **:62 estado por flujo pasó a `[ACTUAL]`** el 2026-09-13).

**Seguimiento post-serie — `co-creation-attachment-authoring` (S1–S5, 2026-09-13):** agrega la capability `author-example-attachments` (entrega el follow-up de autoría de co-creación antes diferido). El Autor anexa ejemplares en el lienzo de co-creación: subida multipart a staging por sesión con validación (path/.md, ≤12288 B, ≤8, `nivel`), movimiento atómico a `attachments/{skill_id}/` al materializar, y `adjuntos` enhebrado por canvas/materializer/route con el mismo contrato de pins. La **ubicación es la marca de autoría** (sin campo `origin`). El resolver `carrier_root_for` sirve tanto semillas como ejemplares de autor, y el trust de un import extrae los carriers verificados para que el export haga round-trip. Invariantes: digest `2ae521a0…` inmóvil, `methodology_seed.py` y semillas intactos. Verificado localmente (backend 2465/0, FE 1143/0 + tsc limpio). **Follow-ups abiertos:** `sweep_staging` sin caller de producción (limpieza de staging pendiente de wire); test de no-herencia de adjuntos en adaptaciones derivadas; wiring de `sweep_staging` a un endpoint/hook.

---

## Apéndice A — Auditoría del corpus de skills

> La auditoría precede a la política (§3): cada entrada se clasifica como **recuperable / a rehacer / legado**, y el pool transversal se fija **después** de esta tabla, no antes. Criterio de clase (design #3152): **recuperable** = metodología coherente hoy, trasladable al manifest de 10 campos sin reescribir flujo/reglas y con rol viable de runtime; **a rehacer** = contenido sustancial pero necesita revisión previa (deriva manifest/schema, colisión de vocabulario D4, duplicación frente a `narrative-character-creation@1.0` publicado); **legado** = superado o con hogar en el dominio del flujo de trabajo del orquestador → fuera del pool del router (su retiro lo ejecuta un PR posterior, no este contrato). "Runtime" = `wiki/` + `tests/` + `fe/`; "workflow" = corpus del orquestador (`Agente_Maestro.md`, `src/commands/narrative-*`, `src/prompts/narrative/`).

| entry | origin | runtime visibility | consumers | class | rationale |
|---|---|---|---|---|---|
| narrative-archive SKILL.md | `skills/narrative-archive/SKILL.md` | none | workflow-only (`narrative-archive`/`help`/`onboard` cmds, prompts, `Agente_Maestro`) | legado | Hogar = flujo de trabajo del orquestador (arc close/CHANGELOG); sin referencias de runtime |
| narrative-character-creation SKILL.md | `skills/narrative-character-creation/SKILL.md` | published+routable+injectable | runtime (methodology_library, skill_router, tests, fe tests) | recuperable | Publica `narrative-character-creation@1.0`, sembrada y limpia para el compilador; la única skill viable de runtime |
| narrative-character-spec SKILL.md | `skills/narrative-character-spec/SKILL.md` | none | workflow-only (`narrative-ff`, prompts, `Agente_Maestro`) | legado | Hogar = flujo de trabajo del orquestador; sin referencias de runtime |
| narrative-design SKILL.md | `skills/narrative-design/SKILL.md` | none | workflow-only (`narrative-ff`, prompts, `Agente_Maestro`) | legado | Hogar = flujo de trabajo del orquestador; sin referencias de runtime |
| narrative-draft SKILL.md | `skills/narrative-draft/SKILL.md` | routable (slug fantasma) | runtime (router+keyword, tests) + workflow-only (`narrative-write`, prompts) | legado | Slug fantasma (sin entrada de biblioteca); contenido con hogar = flujo de trabajo del orquestador |
| narrative-explore SKILL.md | `skills/narrative-explore/SKILL.md` | routable (slug fantasma) | runtime (router+keyword) + workflow-only (`narrative-explore`/`new`/`help`) | legado | Slug fantasma; contenido con hogar = flujo de trabajo del orquestador |
| narrative-idea SKILL.md | `skills/narrative-idea/SKILL.md` | routable (slug fantasma) | runtime (router+keyword, fixture en `wiki/tests/test_conversation_memory_store.py:57,:68`) + workflow-only (`narrative-idea`) | legado | Slug fantasma; contenido con hogar = flujo de trabajo del orquestador (la capacidad Banco de Ideas vive en el runtime dedicado `ideas_bank.py`, no en este slug) |
| narrative-init SKILL.md | `skills/narrative-init/SKILL.md` | none | workflow-only (`narrative-init`/`help`/`onboard`, prompts, `Agente_Maestro`) | legado | Hogar = flujo de trabajo del orquestador (bootstrap de proyecto); sin referencias de runtime |
| narrative-outline SKILL.md | `skills/narrative-outline/SKILL.md` | routable (slug fantasma) | runtime (router+keyword, tests) + workflow-only (`narrative-write`) | legado | Slug fantasma; contenido con hogar = flujo de trabajo del orquestador |
| narrative-propose SKILL.md | `skills/narrative-propose/SKILL.md` | none | workflow-only (`narrative-ff`/`idea`/`new`, prompts, `Agente_Maestro`) | legado | Hogar = flujo de trabajo del orquestador; la referencia del test fe es un slug distinto (`narrative-proposer`) |
| narrative-revise SKILL.md | `skills/narrative-revise/SKILL.md` | routable (slug fantasma) | runtime (router+keyword) + workflow-only (`narrative-write`) | legado | Slug fantasma; contenido con hogar = flujo de trabajo del orquestador |
| narrative-tasks SKILL.md | `skills/narrative-tasks/SKILL.md` | none | workflow-only (`narrative-ff`, prompts, `Agente_Maestro`) | legado | Hogar = flujo de trabajo del orquestador; sin referencias de runtime |
| narrative-verify SKILL.md | `skills/narrative-verify/SKILL.md` | none | workflow-only (`narrative-verify`/`help`/`onboard`, prompts, `Agente_Maestro`) | legado | Hogar = flujo de trabajo del orquestador; sin referencias de runtime |
| narrative-world-spec SKILL.md | `skills/narrative-world-spec/SKILL.md` | routable (slug fantasma) | runtime (router+keyword, tests) + workflow-only (`narrative-ff`) | legado | Slug fantasma; contenido con hogar = flujo de trabajo del orquestador |
| slug `narrative-world-spec` | `wiki/skill_router.py:26-34` (`TRANSVERSAL_SKILLS`) | routable (candidato, nunca inyecta) | runtime (router, tests) | legado | Fantasma (la biblioteca publica solo `narrative-character-creation@1.0`); retirar del pool en el PR ② |
| slug `narrative-idea` | `wiki/skill_router.py:26-34` | routable (candidato, nunca inyecta) | runtime (router, tests) | legado | Fantasma; retirar del pool en el PR ② |
| slug `narrative-outline` | `wiki/skill_router.py:26-34` | routable (candidato, nunca inyecta) | runtime (router, tests) | legado | Fantasma; retirar del pool en el PR ② |
| slug `narrative-draft` | `wiki/skill_router.py:26-34` | routable (candidato, nunca inyecta) | runtime (router, tests) | legado | Fantasma; retirar del pool en el PR ② |
| slug `narrative-revise` | `wiki/skill_router.py:26-34` | routable (candidato, nunca inyecta) | runtime (router, tests) | legado | Fantasma; retirar del pool en el PR ② |
| slug `narrative-explore` | `wiki/skill_router.py:26-34` | routable (candidato, nunca inyecta) | runtime (router, tests) | legado | Fantasma; retirar del pool en el PR ② |

**Resultado:** 1 recuperable (`narrative-character-creation`), 0 a rehacer, 19 legado. Ningún slug fantasma sin clasificar queda en el pool. Los 6 slugs fantasma y la ruta de keywords fundamentales (`route_new_character_intent`, `wiki/skill_router.py:117-124`) se retiran como PR ② (sección 9, seguimiento); ese retiro se ejecuta allí, **no** en este contrato.