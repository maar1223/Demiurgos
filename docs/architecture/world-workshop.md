# Taller de Mundo — Contrato de Taller

> **Contrato de taller.** Este documento es el contrato de producto y arquitectura del **Taller de Mundo** de Demiurgos, el subsistema del Core donde el Autor gestiona el lore de un mundo. **No es un artefacto SDD** ni sustituye a la constitución global. Toda afirmación lleva la etiqueta de estado correspondiente; lo no implementado no se presenta como existente.

| Campo | Valor |
|---|---|
| Estado | Contrato de taller (nuevo — consolidación de decisiones cerradas) |
| Versión del documento | 1.4 |
| Fecha | 2026-08-17 |
| Autor | Demiurgos (orquestación) |
| Idioma | Español neutro (prosa técnica) |
| Alcance | TALLER (subsistema): **Taller de Mundo** — secciones de contenido independientes (Lore, Personajes, Lugares, Facciones, Artefactos, Historia y cronología, Relaciones y Canon; agrupables por la UI con grupos plegables; Sagas hoy como pruebas prescindibles), Referencias, árbol físico propiedad del Autor con vistas semánticas, edición con diff, flujos CRUD/imágenes, sidebar asistente/contexto, creación guiada, propuestas/conflictos como Markdown y gobierno de canon (Borrador vs Canon, relaciones, conflictos, provenance, grafo) |
| Depende de | `docs/architecture/demiurgos-platform.md` (constitución global del producto) |
| Relación con SDD | Requisito previo. Ningún SDD de este dominio debe comenzar sin este contrato aprobado y sus decisiones abiertas resueltas |
| Documentos relacionados | `docs/architecture/demiurgos-platform.md`, `docs/architecture/tool-workshop.md` (contrato de superficie del Taller de Herramientas), `docs/architecture/skill-library-and-guided-character-creation.md` (subsistema de skills + creación guiada), `docs/architecture/foundational-research-skill.md` (Skill Fundacional de Investigación — vía de entrada de información externa), `docs/architecture/skill-runtime-consumption-contract.md` (consumo de skills en runtime — SR1–SR6), `AGENTS.md` (límites de dominio), runtime en `src/tools/demiurgos-suite/wiki/` y `frontend/` |

## Leyenda de etiquetas

| Etiqueta | Significado |
|---|---|
| `[ACTUAL]` | Comportamiento que existe hoy en el repositorio y está verificado |
| `[OBJETIVO]` | Comportamiento objetivo acordado, no necesariamente implementado aún |
| `[PROPUESTO]` | Diseño propuesto; requiere decisión antes de ser contrato |
| `[DECISIÓN ABIERTA]` | Punto sin resolver que requiere aprobación explícita del Autor |
| `[DECISIÓN CERRADA]` | Decisión ya aprobada; no debe revertirse sin nuevo acuerdo explícito |

---

## 0. Relación con la constitución de la plataforma

- La **definición global del producto** (qué es Demiurgos, principios, mapa del sistema, conceptos canónicos, superficies, límites de dominio y decisiones globales G1–G15) vive en `docs/architecture/demiurgos-platform.md`. **Este documento no la duplica.**
- El **Taller de Mundo forma parte del Core gratuito del MVP** junto al Taller de Herramientas (constitución, G10); en el Navbar solo se muestran los talleres disponibles. `[DECISIÓN CERRADA — W1]`
- La frontera entre **kernel/metodología** y el flujo guiado de personajes (protocolo `guided-character-v1`, 40/60, handoff semántico) viven en el **subsistema técnico** (`skill-library-and-guided-character-creation.md`) y la **superficie del Taller de Herramientas** (`tool-workshop.md`); este contrato las referencia sin repetirlas.
- La **Skill Fundacional de Investigación** (`docs/architecture/foundational-research-skill.md`) es la **vía de entrada de información externa** que puede alimentar propuestas, conflictos y estados del mundo **sin auto-canon**; este contrato mantiene el gobierno de canon (Borrador vs Canon, propuestas y conflictos, W3–W5/W11) que aquella referencia.
- El asistente visible en este Taller se llama **Asistente de Demiurgos**; "Hermes" es el nombre interno del proveedor y nunca aparece en la copia visible (constitución, G15/10.6). `[DECISIÓN CERRADA — W7]`
- En caso de conflicto, prevalece la constitución; la contradicción se reporta al Autor.

---

## 1. Definición del Taller de Mundo

**[DECISIÓN CERRADA]** El **Taller de Mundo** es la superficie del Core donde el Autor da forma a **un mundo a la vez** (aislamiento por mundo; el Mundo es concepto canónico de la constitución). Opera **mundo por mundo**: cada mundo tiene sus propias secciones, canon, sesiones y configuración de skills activas; el cambio de mundo no mezcla datos ni contextos.

| El Taller de Mundo ES | El Taller de Mundo NO es |
|---|---|
| La casa del lore y del canon de un mundo | Un editor genérico de wiki sin gobierno de canon |
| Co-creación asistida: el Asistente propone, el Autor decide | Un sistema que persiste lo que la IA propone automáticamente |
| Borrador vs Canon con aprobación explícita y gated | Un solo estado mutable sin trazabilidad |
| Relaciones y conflictos visibles (propuestas, panel y grafo) | Relaciones que se promueven a canon en silencio |
| El gestor de contenido factual del mundo (Lore, Personajes, Lugares, Facciones, Artefactos, Historia/Cronología, Relaciones/Canon) | El gestor de **historias/tramas/arcos/capítulos/escenas**, que pertenece al futuro **Taller de Narrativa** (sección 6) |

---

## 2. Ámbito: secciones del Taller de Mundo

### 2.1 Secciones objetivo `[OBJETIVO]`

**[DECISIÓN CERRADA — W2]** El Taller de Mundo abarca, como objetivo, las siguientes secciones de contenido:

| Sección | Estado | Notas |
|---|---|---|
| **Lore** | `[ACTUAL]` | Reglas, lugares, historia y hechos del mundo bajo `lore/`; fuente de canon |
| **Personajes** | `[ACTUAL]` | Fichas de personajes bajo `personajes/`; objetivo de la creación guiada |
| **Lugares** | `[OBJETIVO]` | Geografía, regiones, escenarios; su contenido vive hoy bajo Lore |
| **Facciones** | `[OBJETIVO]` | Organizaciones, grupos, órdenes; su contenido vive hoy bajo Lore |
| **Artefactos** | `[OBJETIVO]` | Objetos, reliquias, ítems; su contenido vive hoy bajo Lore |
| **Historia/Cronología** | `[OBJETIVO]` | Línea temporal y eventos del mundo; su contenido vive hoy bajo Lore |
| **Relaciones/Canon** | `[OBJETIVO]` | Vista de relaciones entre entidades, conflictos y estados de certeza; se apoya en el grafo (sección 4) |

> **`[DECISIÓN CERRADA — W9]`** Las secciones son **independientes**: Lore, Personajes, Lugares, Facciones, Artefactos, Historia y cronología, y Relaciones y Canon. La UI puede **agruparlas visualmente con grupos plegables** sin fusionar su identidad. Este contrato no afirma que Lugares/Facciones/Artefactos/Historia existan hoy como secciones propias: son `[OBJETIVO]`.

### 2.2 Sagas y la frontera con la Narrativa `[ACTUAL]`

**[DECISIÓN CERRADA — W8]** Las **Sagas actuales** (`sagas/`) son **pruebas prescindibles**: **no se diseña migración** hacia el futuro Taller de Narrativa; pueden **retirarse o eliminarse** sin afectar el Taller de Mundo. El futuro **Taller de Narrativa tendrá su propia estructura**, independiente de `sagas/`.

- **Hoy** el Taller de Mundo expone la sección **Sagas** (`sagas/`), junto a Lore y Personajes, como sección de contenido. `[ACTUAL — VALID_SECTIONS = lore, personajes, sagas]`
- **Objetivo** el contenido narrativo (historias, tramas, arcos, capítulos, escenas) pertenece a un **futuro Taller de Narrativa** con **estructura propia**; **no** a este contrato. `[OBJETIVO]`

### 2.3 Árbol físico del mundo y vistas semánticas `[DECISIÓN CERRADA — W10]`

- El **árbol físico del mundo** (carpetas y jerarquías bajo `mundos/{mundo}/`) **pertenece al Autor**: las vistas del Taller son **semánticas** y **no imponen carpetas** sobre su estructura.
- Se **conservan las jerarquías** que el Autor ya mantiene (p. ej. `lore/ayagars/Dvex_por_Stal`, `Dvins_por_Stal`, `Formas_por_Stal`); el Taller las expone tal cual, sin reestructurarlas. `[ACTUAL — evidencia en sección 5]`
- Se **distinguen las carpetas del sistema** (`_context`, `.history`, `.papelera`) del **contenido** del Autor; las del sistema no se presentan como secciones de contenido. `[ACTUAL — evidencia en sección 5]`

### 2.4 Referencias del mundo `[DECISIÓN CERRADA — W13]`

El Taller de Mundo ofrece una sección **Referencias** para conservar material de apoyo sin confundirlo con el Canon:

```text
Referencias/
├── Investigaciones/
└── Visuales/
```

- Las investigaciones aprobadas se guardan como archivos `.md` con frontmatter YAML en `mundos/{mundo}/referencias/investigaciones/`.
- Las referencias visuales se conservan en `mundos/{mundo}/referencias/visuales/`.
- El cuerpo Markdown es legible para el Autor; el YAML permite indexado, procedencia y consulta del Asistente.
- Una referencia externa nunca se convierte en Canon automáticamente. Si genera una propuesta o un conflicto, el registro correspondiente vive en `Relaciones_y_Canon/` y enlaza con la investigación original.
- La sección Referencias no impone una reorganización del árbol físico del Autor: es una vista semántica sobre el contenido existente.

---

## 3. Borrador vs Canon

**[DECISIÓN CERRADA — W3]** El Taller de Mundo distingue explícitamente entre **Borrador** (contenido en construcción, mutable, no canónico) y **Canon** (contenido aceptado por el Autor, fuente de hechos del mundo):

| Aspecto | Borrador | Canon |
|---|---|---|
| Estado OKF observado | `draft` | `stable` |
| Mutabilidad | Mutable, en construcción | Solo cambia por **transición explícita del Autor** |
| Efecto en el mundo | No gobierna lecturas canónicas | Es la única fuente de hechos canónicos |
| Persistencia | Guardado normal del editor | Vía compuertas gated (create/save con digest + token) |

- Los estados OKF observados son `draft`/`stable` (constitución, sección 6). `[ACTUAL]`
- La transición a canon es **decisión exclusiva del Autor**; la IA propone, nunca decide canon. `[DECISIÓN CERRADA — constitución, secciones 2.3 y 5]`
- Toda escritura pasa por las **compuertas existentes** con confirmación (diff + digest + token de un solo uso). `[ACTUAL — constitución, sección 7.1]`

---

## 4. Relaciones y canon

### 4.1 Relaciones propuestas

**[DECISIÓN CERRADA — W4]** Las **relaciones entre entidades** (p. ej. "hija de X", "aliada de la facción Y") son **propuestas por el Asistente**, presentadas **una por vez**, y requieren **aceptación explícita del Autor** antes de incorporarse al canon:

- El Asistente propone la relación como **interpretación propuesta**; Demiurgos **resuelve/verifica la referencia** por el grafo, pero **no decide ni confirma la relación** (coherente con la iniciativa, 10.6).
- La relación permanece en la partición **`proposals`** hasta la aprobación explícita; **nunca** se promueve a canon automáticamente.
- El backend registra **provenance** (origen trazable) de cada dato propuesto, sin exponerla al Autor ni al proveedor como clave de autoridad. `[ACTUAL]`

### 4.2 Conflictos

**[DECISIÓN CERRADA — W5]** Los **conflictos intencionales** (elementos del mundo que se contradicen a propósito) están **permitidos**, salvo que constituyan una **ruptura estructural** del canon (una contradicción que invalide reglas o hechos fundacionales del mundo):

| Tipo de conflicto | Tratamiento |
|---|---|
| **Conflicto intencional** (contradicción deliberada, sin ruptura estructural) | Permitido; se registra y se muestra como conflicto conocido, no como error |
| **Ruptura estructural** (contradice reglas/hechos fundacionales) | Se señala al Autor como **advertencia de ruptura**; la decisión de mantenerla es del Autor |
| **Conflicto accidental** (inconsistencia no intencional) | Se detecta y se propone al Autor para que lo resuelva; no se resuelve en silencio |

- Los conflictos se **retienen** en la partición `conflicts` y **no se resuelven en silencio** ni se crean archivos automáticamente. `[ACTUAL]`
- La superficie prevista es un **panel de conflicto** integrado con el **grafo** (vista de entidades, enlaces y estados de certeza) que permita al Autor ver y decidir sobre cada conflicto. `[OBJETIVO — la profundidad queda acotada por W11 (almacenamiento) y W12 (alcance del grafo), secciones 4.4 y 4.5]`

### 4.3 Gobierno de canon por el grafo

- El **grafo es la fuente de verdad para leer entidades**; el filesystem queda prohibido para consultas de entidades. `[ACTUAL — constitución, 7.1]`
- Las particiones de certeza del candidato guiado son `accepted_canon / proposals / unknowns / rumors / conflicts / unresolved_references / provenance`; la aceptación es transición exclusiva del Autor. `[ACTUAL]`
- El grafo provee `search/read/links/status` y resolución de referencias nombradas como contexto relacional. `[ACTUAL]`

### 4.4 Persistencia de propuestas y conflictos `[DECISIÓN CERRADA — W11]`

- **Propuestas y conflictos se guardan como archivos Markdown** en una **sección especial** del Taller de Mundo, con **frontmatter YAML estructurado** (metadatos: tipo, estado, entidades implicadas, origen) y **cuerpo legible** (la propuesta o el conflicto explicado en lenguaje natural).
- **No son entidades del mundo**: no forman parte del canon ni del grafo como entidades de contenido consultables; son registros de trabajo.
- Al **aceptar una propuesta**, se **actualiza la ficha relacionada** (transición gated a canon, sección 3) y el **registro permanece como historial** de la decisión.

### 4.5 Vista de grafo: alcance de la primera versión `[DECISIÓN CERRADA — W12; superficie OBJETIVO]`

La vista de Relaciones/Canon (sección 2.1) se apoya en el grafo (sección 4.3). **La primera versión incluye**:

- **Nodos y relaciones** (entidades y enlaces), con **etiquetas** legibles.
- **Estados comprensibles** (p. ej. certeza/borrador/canon) visibles sobre la vista.
- **Zoom/desplazamiento**, **filtros** y **foco** en una entidad.
- **Subgrafos acotados** (por sección, tipo o criterio del Autor).
- **Nodos aislados ocultos por defecto**, para no saturar la vista.
- **Clic en un nodo** para abrir la **ficha normal** de la entidad.

**No se incluye en la primera versión:** edición desde el grafo, creación/eliminación de relaciones, todos los mundos juntos, miles de nodos, tiempo real, requisito operativo ni fuente independiente del Canon.

### 4.6 Conexiones, contexto y ramas — contrato general `[DECISIÓN CERRADA]`

Contrato general del Taller de Mundo (no limitado a una cultura o tipo de personaje) para **conexiones, contexto y ramas de trabajo**:

- **Leer contexto no escribe**: consultar contexto (entidades, referencias, grafo) es de **solo lectura**; nunca produce escrituras ni promueve candidatos por el simple hecho de consultarlos. `[DECISIÓN CERRADA]`
- **Una conexión genera una sugerencia**: cualquier conexión/relación propuesta entre entidades genera una **sugerencia** (candidato) y **no muta los destinos** implicados; se confirma solo con aprobación explícita del Autor (W4). `[DECISIÓN CERRADA]`
- **Cambios cruzados son candidatos independientes**: cuando una acción toca varias entidades, cada cambio se trata como **candidato independiente**; aprobar uno no aprueba los demás. `[DECISIÓN CERRADA]`
- **Tarjeta inline clara**: la superficie presenta cada sugerencia/candidato en una **tarjeta inline** con acciones explícitas — **usar ahora / guardar después / pausar** — y, al trabajar sobre ella, **trabajar / crear propuesta / ignorar**. `[OBJETIVO — superficie]`
- **Backend con checkpoints y reanudación**: el backend conserva **checkpoints** de ramas de trabajo (contexto + candidatos) y permite **reanudar** sin pérdida; reanudar **no recupera autoridad de escritura** (constitución, G2/10.1). `[OBJETIVO]`
- **Vistas semánticas explicadas y mapeo confirmable**: las vistas del Taller son **semánticas** y se **explican** al Autor (qué agrupan y por qué); el **mapeo del contenido importado es confirmable** sin tocar el árbol físico (coherente con W10). `[DECISIÓN CERRADA]`

---

## 5. Evidencia de implementación actual `[ACTUAL]`

Estado verificado en el repositorio (no es objetivo; existe hoy):

| Capacidad | Evidencia |
|---|---|
| Secciones `lore`, `personajes`, `sagas` | `frontend/src/lib/constants.ts` — `VALID_SECTIONS` y etiquetas `Lore`/`Personajes`/`Sagas` |
| Edición Markdown directa con diff | Editor wiki: CRUD gated (create/save/restore), diff con digest + token, papelera (TTL 30 días), snapshots de historial, estados OKF `draft`/`stable` |
| Crear / duplicar / renombrar / mover / papelera | `POST /api/{mundo}/duplicate`, `POST /api/{mundo}/move`, `GET|POST|DELETE /api/{mundo}/papelera*` |
| Flujos de imagen | Subida de media + `image_indexer` + proveedor de visión; `ImportImageModal`/`ImagePicker` |
| Sidebar Asistente/Contexto | `EditorLayout` con panel derecho (Asistente IA / Contexto); `AIAssistantSidebar` (chat, historial, whisper) + `ai/ask` + SSE |
| Creación guiada de personaje | `GuidedCharacterPanel` con fases, propuestas Aceptar/Rechazar, serialización diskless, create gated, reindex |
| Canon / propuestas / conflictos / provenance | `CandidateState` con particiones `accepted_canon/proposals/unknowns/rumors/conflicts/unresolved_references/provenance`; modelo `LoreConflict` |
| Jerarquías del Autor conservadas | `mundos/vibrantes/lore/ayagars/Dvex_por_Stal`, `Dvins_por_Stal`, `Formas_por_Stal` (contenido del Autor) |
| Carpetas del sistema distinguidas | `_context`, `.history`, `.papelera` en la raíz del mundo (no son secciones de contenido) |

> Regla de etiquetas: todo lo listado arriba es `[ACTUAL]` verificado; las superficies objetivo de las secciones 2–4 llevan su etiqueta propia y **no se presentan como implementadas**.

---

## 6. Frontera con el futuro Taller de Narrativa

**[DECISIÓN CERRADA — W6]** El Taller de Mundo **no incluye** historias, tramas, arcos, capítulos ni escenas:

| Fuera del Taller de Mundo | Dónde vive |
|---|---|
| Historias / tramas / arcos | Futuro **Taller de Narrativa** |
| Capítulos / escenas / borradores narrativos | Futuro **Taller de Narrativa** |
| Workflows narrativos del orquestador (AGENTS.md) | Subsistema narrativo existente (no es este contrato) |

- La etiqueta actual **Sagas** (`sagas/`) es una sección de contenido del Taller de Mundo **hoy** y un conjunto de **pruebas prescindibles**: **no se diseña migración**; puede retirarse/eliminarse y el Taller de Narrativa tendrá **estructura propia**. `[ACTUAL] → [DECISIÓN CERRADA — W8]`
- Este contrato no define el Taller de Narrativa; solo **delimita la frontera** para que su futuro contrato no invente el vacío ni colisione con el contenido factual del mundo.

---

## 7. Decisiones cerradas y abiertas

### 7.1 Cerradas (no revertir sin nuevo acuerdo)

| ID | Decisión |
|---|---|
| **W1** | El Taller de Mundo es parte del **Core gratuito del MVP**, opera **mundo por mundo** y solo muestra los talleres disponibles (constitución, G10) |
| **W2** | Secciones objetivo del Taller de Mundo: **Lore, Personajes, Lugares, Facciones, Artefactos, Historia/Cronología, Relaciones/Canon** (sección 2.1) |
| **W3** | **Borrador vs Canon**: estados OKF `draft`/`stable`; la transición a canon es decisión exclusiva del Autor; escritura siempre gated (sección 3) |
| **W4** | **Relaciones propuestas por el Asistente**, una por vez, con **aceptación explícita**; nunca promoción automática a canon (sección 4.1) |
| **W5** | **Conflictos intencionales permitidos** salvo **ruptura estructural**; panel de conflicto + grafo como superficie objetivo (sección 4.2) |
| **W6** | El Taller de Mundo **no incluye** historias/tramas/arcos/capítulos/escenas; las Sagas actuales son **pruebas prescindibles** sin migración diseñada (secciones 2.2 y 6; ver W8) |
| **W7** | El asistente visible en este Taller es el **Asistente de Demiurgos**; Hermes es solo el nombre interno del proveedor (constitución, G15/10.6) |
| **W8** | Las **Sagas actuales** (`sagas/`) son **pruebas prescindibles**: **no se diseña migración**; pueden **retirarse o eliminarse**; el futuro Taller de Narrativa tendrá **estructura propia** (secciones 2.2 y 6; **resuelve A1**) |
| **W9** | Secciones del Taller de Mundo **independientes**: Lore, Personajes, Lugares, Facciones, Artefactos, Historia y cronología, Relaciones y Canon; la UI puede **agruparlas visualmente con grupos plegables** (sección 2.1; **resuelve A2**) |
| **W10** | El **árbol físico del mundo pertenece al Autor**: las vistas del Taller son **semánticas** y **no imponen carpetas**; se **conservan jerarquías** del Autor (p. ej. `lore/ayagars/Dvex_por_Stal`, `Dvins_por_Stal`, `Formas_por_Stal`) y se **distinguen carpetas del sistema** (`_context`, `.history`, `.papelera`) de contenido (sección 2.3) |
| **W11** | **Propuestas y conflictos se guardan como archivos Markdown** en una **sección especial** con **frontmatter YAML estructurado** y **cuerpo legible**; **no son entidades del mundo**; al aceptar una propuesta se **actualiza la ficha relacionada** y el **registro permanece como historial** (sección 4.4; contribuye a resolver A3) |
| **W12** | **Grafo — primera versión**: nodos/relaciones, etiquetas, estados comprensibles, zoom/desplazamiento, filtros, foco, subgrafos acotados, nodos aislados ocultos por defecto y clic en nodo para abrir la ficha normal; **no incluye** edición desde el grafo, creación/eliminación de relaciones, todos los mundos juntos, miles de nodos, tiempo real, requisito operativo ni fuente independiente del Canon (sección 4.5; contribuye a resolver A3) |
| **W13** | **Referencias**: las investigaciones aprobadas se guardan como `.md` con frontmatter YAML en `mundos/{mundo}/referencias/investigaciones/`, las referencias visuales en `mundos/{mundo}/referencias/visuales/`, y las propuestas/conflictos derivados enlazan con la investigación original (sección 2.4) |
| **W14** | **Conexiones, contexto y ramas (contrato general)**: leer contexto no escribe; una conexión genera una sugerencia sin mutar destinos; los cambios cruzados son candidatos independientes; tarjeta inline con acciones usar ahora/guardar después/pausar y trabajar/crear propuesta/ignorar; el backend conserva checkpoints y permite reanudar sin recuperar autoridad de escritura; las vistas semánticas se explican y el mapeo de importados es confirmable sin tocar el árbol físico (sección 4.6) |

### 7.2 Abiertas (acotadas; no se expande el alcance sin consolidar primero)

> Sin decisiones abiertas pendientes: A1–A3 quedaron **cerradas** (A1 → W8, A2 → W9, A3 → W11 y W12). Cualquier nuevo punto abierto se registrará aquí.

---

## 8. Definition of ready para SDD futuro

Un SDD de este dominio **solo** puede comenzar cuando se cumplan todos:

- [ ] Se leyeron esta constitución global y este contrato (sección 0).
- [ ] Se verificó el runtime real (CodeGraph/tests) antes de asumir cualquier `[ACTUAL]` (sección 5).
- [ ] Las decisiones abiertas que tocan el cambio están resueltas y anotadas (A1–A3 quedaron cerradas: A1 → W8, A2 → W9, A3 → W11 y W12).
- [ ] El cambio respeta las invariantes `[ACTUAL]` de la constitución (secciones 5, 7) y las fronteras de dominio.
- [ ] Todo comportamiento nuevo se etiqueta `[ACTUAL]`/`[OBJETIVO]`/`[PROPUESTO]` y no se presenta como implementado.
- [ ] El SDD declara explícitamente qué NO toca (Taller de Narrativa, skills, archivos fuera de la escritura gated).
- [ ] Las pruebas cubren las invariantes afectadas (escritura gated, Borrador vs Canon, relaciones/conflictos) y las ramas de fallo relevantes.
