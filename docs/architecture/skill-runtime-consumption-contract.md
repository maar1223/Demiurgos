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

## 2. Activación por tipo de flujo guiado `[OBJETIVO]` — SR1

**[DECISIÓN CERRADA — SR1, origen D1]** Cada mundo debe tener **un slot de activación por tipo de flujo guiado**, no uno solo global. El slot actual es único (`wiki/methodology_library.py:739` `active_for`); el objetivo extiende ese modelo a **un slot por tipo de flujo**. `[OBJETIVO]`

- **Estado por tipo de flujo**: cada slot se expresa **Activada/Desactivada por flujo** (la copia exacta de la etiqueta se decide en el pase de copy posterior; este contrato fija el modelo, no las palabras). `[OBJETIVO]`
- **Pinning de sesión**: al iniciar una sesión guiada, `skill@version` queda fijado para toda la sesión (`wiki/api_server.py:2183`, `:5904` — snapshot en la creación de la sesión); **todas las continuaciones** de la sesión inyectan el contrato compilado activo (`wiki/api_server.py:2081`). `[ACTUAL]`
- **Deriva de versión**: reanudar una sesión cuyo pin no coincide con la versión activa **se rechaza** y se fuerza una sesión nueva (`wiki/api_server.py:1995-2012`). `[ACTUAL]`
- **Sin activación**: si el mundo no tiene slot activo para el flujo, aplica la creación guiada integrada `guided-character-v1` (`wiki/api_server.py:1855-1860`, `:1780`). `[ACTUAL]`
- **El slot nunca inyecta en chat libre**: la inyección en chat no guiado ocurre **solo** cuando el ganador del enrutamiento es compañero del mundo (`wiki/api_server.py:5508-5533`; docstring `:5516-5517`: los ganadores no-compañero, incluidos los transversales, **nunca inyectan**). El slot **sí** permanece como candidato de enrutamiento (`wiki/skill_router.py:102-103`, `:236-245`), pero no inyecta. `[ACTUAL]`
- **Detección de intención de chat**: si el chat expresa intención de flujo guiado (p. ej. crear personaje), la detección de intención **abre el flujo guiado correspondiente con su Skill**; el turno de chat en sí no recibe inyección del slot. `[OBJETIVO]`
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
- **Digest-pinning**: los adjuntos quedan **fijados por SHA-256** en el registro publicado (mismo algoritmo que `checksums.json` de las semillas, `data/methodology/seeds/narrative-character-creation/`); la semilla verifica el pin (PR ③). `[ACTUAL]` El runtime **sirve solo los bytes del digest fijado** — servicio de bytes pendiente de PR ④ (retención post-publish). `[OBJETIVO]`
- **Fallo en build/publish**: un **desajuste de digest** (el adjunto cambió tras publicarse) **falla el build/publish**; no existe auto-curado — verificado en `wiki/methodology_seed.py:146-172` (`_verify_entry`, `SeedIntegrityError`); overflow de publish → 422 `attachment_limit_reached` (`wiki/api_server.py:7818-7822`). `[ACTUAL]`
- **Fuera de mundos/referencias**: los ejemplos **nunca** viven bajo `mundos/{world}/referencias/` — el indexador trata `referencias/` como entidades de grafo (`wiki/graph_indexer.py:46`, `:55`), y colocarlos allí **contaminaría el grafo**. La validación de publish **rechaza** rutas `mundos/**`/`referencias/**` — implementada en el compilador (PR ③, `invalid-value` en `wiki/methodology_compiler.py:467-546`). `[DECISIÓN CERRADA — origen D5/D6]`
- **Inyección en convergencia**: el ejemplo de espécimen terminado se inyecta en la fase de **propuesta/convergencia**, nunca en el primer turno; la estructura de salida ya llega al runtime vía la descripción de semilla en la **proyección ≤ 1000 tokens** (`wiki/contract_projection.py:99-136`, tope `:102`); el adjunto aporta los **ejemplares** dentro de su propio presupuesto (sección 6). `[OBJETIVO]`

**Escenarios cubiertos (spec, skill-example-attachments):** deriva de contenido (`Content drift`), sesión de creación guiada (`Guided creation session`), validación de publish (`Publish validation`).

---

## 5. Ejes de vocabulario `[OBJETIVO]` — SR5

**[DECISIÓN CERRADA — SR5, origen D4]** El vocabulario de estado define **exactamente cuatro ejes canónicos**; cada término se ata a **un solo eje**:

| Eje | Visibilidad en la fila del árbol |
|---|---|
| **Activación por flujo** | **Visible** — etiqueta `Activada/Desactivada` por flujo (`[OBJETIVO]`; hoy el slot no se etiqueta al usuario: `fe/components/organisms/MethodologyStatePanel.tsx:278-280`) |
| **Compañero en chat** | **Visible** — estado de compañero en la fila (`[ACTUAL]`: badge "Compañera", `fe/components/organisms/TallerTree.tsx:152`; switch `fe/components/organisms/MethodologyStatePanel.tsx:285,290`, "Apagar" `:318`) |
| **Alcance de taller** | Tooltip/panel — hoy mezclado en los grupos del árbol (`fe/components/organisms/TallerTree.tsx:49-64` `GROUP_ORDER`: "En uso · funciona solo en este taller", "funciona también en otros talleres", "Apagada", "En conflicto", "Sin taller") |
| **Conflicto** | Tooltip/panel — estado bloqueada (`fe/components/organisms/TallerTree.tsx:62`) |

- **La fila muestra solo los dos primeros ejes** (activación-por-flujo + compañero), con **atribución de eje**; alcance y conflicto van a tooltip/panel. `[OBJETIVO]`
- **Prohibido: contradicción entre ejes sin atribución.** Un compañero que no es el slot activo muestra hoy "Inactiva" (eje slot, `fe/components/organisms/TallerTree.tsx:72`) junto a "Compañera" (eje compañero, `:152`) — una contradicción entre ejes sin etiquetar. El modelo objetivo muestra "Desactivada por flujo" + estado de compañero, cada uno **atribuido a su eje**; nunca la combinación desnuda "Inactiva + Compañera". `[OBJETIVO]`
- El modelo de estados máquina subyacente (`fe/lib/tallerStates.ts:12-17` `SkillState`, derivación `:53-98`) **no cambia** en este contrato; solo se define a qué eje pertenece cada término. `[ACTUAL]`
- El **rename de "Compañera"** queda registrado como restricción para el pase de copy posterior (fuera de alcance de este contrato). `[DECISIÓN CERRADA — D4]`

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
| Inyección de convergencia | **1 adjunto/turno, ≤ 3072 tokens estimados** | = bytes/4, mismo heurístico `_CHARS_PER_TOKEN` que la proyección (`wiki/contract_projection.py:23`); **fuera** de la proyección ≤ 1000 tokens (`:102`) |
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
| Zip sigue fail-closed: `_ALLOWED_ENTRIES` sin extender; paquete con adjuntos rechazado | `wiki/methodology_trust.py:46`, `:212` |
| Proyección de contrato ≤ 1000 tokens con heurístico ~4 chars/token | `wiki/contract_projection.py:23`, `:99-136`, `:102` |
| `referencias/` indexado como entidades de grafo | `wiki/graph_indexer.py:46`, `:55` |
| Ejes de vocabulario en la UI (grupos mixtos, badges, slot sin etiquetar) | `fe/components/organisms/TallerTree.tsx:49-64`, `:70-74`, `:140-142`, `:152`, `:169`; `fe/components/organisms/MethodologyStatePanel.tsx:278-280`, `:285-290`, `:318`; `fe/lib/tallerStates.ts:12-17`, `:53-98` |
| Ejemplos canónicos de salida (5, solo en docs; runtime no los referencia) | `docs/architecture/character-creation/examples/` (`Axill_Garner.md`, `Kae_Turant.md`, `Secundario_Ejemplo.md`, `Relleno_Ejemplo.md`, `Villano_Korrane.md` = 9802 B), `docs/architecture/character-creation/README.md:13-17`, `:113-119` |
| Ejemplos de técnica en dominio de skill | `skills/narrative-character-creation/references/conversation-examples.md`, citado en `docs/architecture/character-creation/README.md:146-148` |

**No implementado (objetivo):** el slot por tipo de flujo guiado (§2), la inyección de convergencia (§4/SR6) y los ejes de vocabulario atribuidos (§5). Todo ello es `[OBJETIVO]`/`[DECISIÓN CERRADA]`, no `[ACTUAL]`.

> Regla de etiquetas: todo lo listado como `[ACTUAL]` está verificado contra el código; las superficies objetivo de las secciones 2–5 llevan su propia etiqueta y **no se presentan como implementadas**.

---

## 8. Decisiones cerradas y abiertas

### 8.1 Cerradas (no revertir sin nuevo acuerdo)

> Tabla SR1–SR6 completada en la segunda unidad de trabajo (WU2), tras cerrar el Apéndice A y el pool transversal (§3); cada fila se anota "(origen: D1–D6, ledger #3149)". Mientras tanto, los requisitos normativos están en sus secciones (§§2–6).

| ID | Decisión | Etiqueta |
|---|---|---|
| **SR1** | *(origen: D1, ledger #3149)* Un slot de activación **por tipo de flujo guiado** por mundo (extiende el `active_for` único); el slot **nunca inyecta** en chat libre; la intención de chat abre el flujo guiado con su Skill; los compañeros siguen moldeando el chat (§2) | `[OBJETIVO]` |
| **SR2** | *(origen: D2, ledger #3149)* La política del pool transversal **deriva de la auditoría** (Apéndice A): 1 recuperable + 19 legado → pool = compañeros ∪ slot activado (`GUIDED_CHARACTER_FLOW`) ∪ `narrative-character-creation`; los fantasma se retiraron en el PR ②; la unión de slots de todos los flujos queda diferida; el dominio del orquestador no se retira (§3) | `[ACTUAL]` |
| **SR3** | *(origen: D3, ledger #3149)* Enrutamiento de compañeros **fail-open**: ambigüedad ⇔ confianza `< 0.7` **o** top-2 de clase compañero `< NEAR_TIE_MARGIN = 0.15` → **cero inyecciones** (genérico o preguntar); reemplaza el "primer ganador silencioso"; el clasificador reporta top-2 (§3). Implementado en el PR ② | `[ACTUAL]` |
| **SR4** | *(origen: D6, ledger #3149)* Campo **adjuntos** por `skill@version` en manifest/compilador/registro publicado, **digest-pinned** por SHA-256; ≤ 8 adjuntos/skill, ≤ 12288 B; desajuste de digest falla build/publish; nunca bajo `mundos/**/referencias/**` (§4). Implementado en el PR ③ (`attachment-digests`); digest-canonical excluido (D1); la inyección en convergencia queda en SR6 | `[ACTUAL]` |
| **SR5** | *(origen: D4, ledger #3149)* **Cuatro ejes canónicos** de vocabulario (activación por flujo, compañero en chat, alcance de taller, conflicto); la fila muestra solo los dos primeros con **atribución de eje**; alcance/conflicto a tooltip/panel; prohibida la contradicción entre ejes sin atribución; rename "Compañera" registrado para el pase de copy (§5) | `[OBJETIVO]` |
| **SR6** | *(origen: D5, ledger #3149)* Ejemplo de espécimen terminado se inyecta en la **fase de propuesta/convergencia** (nunca turno uno), dentro de su presupuesto (1 adjunto/turno ≤ 3072 tokens estimados, fuera de la proyección ≤ 1000); estructura de salida llega vía la proyección (§4/§6) | `[OBJETIVO]` |

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

**Seguimiento (PRs encadenados, fuera de este cambio):** ① slot por tipo de flujo guiado (SR1); ~~② derivación del pool + retiro de fantasma + `NEAR_TIE_MARGIN` + top-2 (SR2/SR3)~~ — ✅ **completado en el PR ②** (`pool-router-derivation`; §3 y §7 pasan a `[ACTUAL]`); ~~③ adjuntos del manifest/compilador + digest (SR4)~~ — ✅ **completado en el PR ③** (`attachment-digests`; §4 y §7 pasan a `[ACTUAL]` para la maquinaria de adjuntos; la inyección de convergencia queda en ④); ④ inyección de convergencia (SR6); ⑤ binding de ejes en la UI (SR5); ⑥ pase de copy incl. rename "Compañera". Todos encadenados, stacked-to-main, presupuesto ~400 líneas cada uno.

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