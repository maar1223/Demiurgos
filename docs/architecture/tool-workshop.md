# Taller de Herramientas — Contrato de Taller

> **Contrato de taller.** Este documento es el contrato de **superficie y producto** del **Taller de Herramientas** de Demiurgos: lo que el Autor ve, elige y co-crea dentro de este Taller del Core. **No es un artefacto SDD** ni sustituye a la constitución global. El contrato del **subsistema técnico** (biblioteca gestionada, paquete/manifest, compilador, runtime, ciclo de vida, import/export/cuarentena y creación guiada de personajes) vive en `docs/architecture/skill-library-and-guided-character-creation.md` y este documento lo referencia sin repetirlo. Toda afirmación lleva la etiqueta de estado correspondiente; lo no implementado no se presenta como existente.

| Campo | Valor |
|---|---|
| Estado | Contrato de taller (nuevo — superficie separada del subsistema técnico) |
| Versión del documento | 1.4 |
| Fecha | 2026-08-17 |
| Autor | Demiurgos (orquestación) |
| Idioma | Español neutro (prosa técnica) |
| Alcance | TALLER (superficie): **Taller de Herramientas** — selector de Taller y árbol contextual de Skills, disponibilidad en el chat (en el chat / fuera del chat / transversal / sin taller), categorías funcionales y etiquetas, biblioteca global de consulta, Skill Madre protegida, co-creación de Skills con la Skill Madre (detección/handoff, ritmo conversacional, editor visual + chat, adaptación, revisión/publicación), transparencia y frontera con otros Talleres |
| Depende de | `docs/architecture/demiurgos-platform.md` (constitución global del producto) |
| Relación con SDD | Requisito previo. Ningún SDD de este dominio debe comenzar sin este contrato aprobado y sus decisiones abiertas resueltas |
| Documentos relacionados | `docs/architecture/demiurgos-platform.md`, `docs/architecture/skill-library-and-guided-character-creation.md` (subsistema técnico), `docs/architecture/world-workshop.md` (Taller de Mundo), `docs/architecture/foundational-research-skill.md` (Skill Fundacional de Investigación — skill transversal del Core), `docs/architecture/skill-runtime-consumption-contract.md` (consumo de skills en runtime — SR1–SR6), `AGENTS.md` (límites de dominio), runtime en `frontend/src/` y `src/tools/demiurgos-suite/wiki/` |

## Leyenda de etiquetas

| Etiqueta | Significado |
|---|---|
| `[ACTUAL]` | Comportamiento que existe hoy en el repositorio y está verificado |
| `[OBJETIVO]` | Comportamiento objetivo acordado, no necesariamente implementado aún |
| `[PROPUESTO]` | Diseño propuesto; requiere decisión antes de ser contrato |
| `[DECISIÓN ABIERTA]` | Punto sin resolver que requiere aprobación explícita del Autor |
| `[DECISIÓN CERRADA]` | Decisión ya aprobada; no debe revertirse sin nuevo acuerdo explícito |

---

## 0. Relación con la constitución y con el subsistema técnico

- La **definición global del producto** (qué es Demiurgos, principios, mapa del sistema, conceptos canónicos, superficies, límites de dominio y decisiones globales G1–G15) vive en `docs/architecture/demiurgos-platform.md`. **Este documento no la duplica.**
- El **Taller de Herramientas forma parte del Core gratuito del MVP** junto al Taller de Mundo (constitución, G10); en el Navbar solo se muestran los talleres disponibles. `[DECISIÓN CERRADA — TW1]`
- El **subsistema técnico** que este Taller expone (biblioteca gestionada por el Autor, paquete `.zip`/manifest, compilador/validador, runtime, ciclo de vida de versiones, import/export/cuarentena y creación guiada de personajes) está contratado en `docs/architecture/skill-library-and-guided-character-creation.md`. Este documento contrata la **superficie**: cómo se presenta, cómo se navega, cómo se co-crea. **Sin duplicar el subsistema.**
- La **Skill Madre** es una capacidad protegida global (constitución, G13/10.5); su **presentación en este Taller** y la **UX de co-creación** se contratan aquí (sección 5), mientras el kernel y la gobernanza global viven en la constitución.
- La **Skill Fundacional de Investigación** es una **skill transversal** del Core cuyo contrato vive en `docs/architecture/foundational-research-skill.md`; este documento gobierna cómo se declara **transversal** en el árbol (sección 3) y cómo se **deriva un perfil** desde ella, sin duplicar su núcleo de investigación.
- El asistente visible en este Taller se llama **Asistente de Demiurgos**; "Hermes" es el nombre interno del proveedor y nunca aparece en la copia visible (constitución, G15/10.6). `[DECISIÓN CERRADA — TW16]`
- En caso de conflicto, prevalece la constitución; la contradicción se reporta al Autor.

---

## 1. Definición del Taller de Herramientas

**[DECISIÓN CERRADA]** El **Taller de Herramientas** es la superficie del Core donde el Autor **gestiona y co-crea las metodologías de trabajo** (Skills) que luego gobiernan los flujos guiados de la plataforma. Se presenta como la primera sección del Navbar y la **base instrumental de los talleres creativos** (constitución, G10). Dentro contiene las **Metodologías**: métodos para **crear, editar, publicar (versiones inmutables), añadir al chat, importar/exportar, compartir y eliminar** formas de trabajo; **"Skill" permanece como nombre técnico del paquete**. `[DECISIÓN CERRADA]`

| El Taller de Herramientas ES | El Taller de Herramientas NO es |
|---|---|
| El lugar donde el Autor gestiona sus metodologías (Skills) y **co-crea nuevas** con la Skill Madre | Un formulario técnico de Skill ID/Markdown como flujo principal |
| Una superficie conversacional asistida: el Asistente propone, el Autor decide | Un editor que persiste o publica sin aprobación explícita |
| La puerta de entrada a la **biblioteca global** y a la disponibilidad de Skills en el chat del mundo | Un runtime de ejecución: los flujos guiados se ejecutan en el Taller de Mundo (sección 7) |
| Transparente sobre qué publica, qué añade al chat y qué método usa el asistente | Un panel que oculta sus consecuencias o sus permisos |

**Frontera:** este Taller **gestiona** metodologías; **no ejecuta** los flujos guiados que producen (esa ejecución ocurre en el Taller de Mundo, sección 7). El detalle técnico del paquete, el compilador y el runtime está en el subsistema (iniciativa técnica).

### 1.1 Vocabulario de la superficie: Metodologías, Plantillas, Catálogos y Referencias `[DECISIÓN CERRADA]`

Cuatro conceptos con significado fijo en esta superficie (y en todo el Taller de Herramientas):

| Concepto | Definición | Ejemplo de rol |
|---|---|---|
| **Metodologías / Skills** | **Cómo trabaja el asistente**: proceso, flujo, ramas, reglas y preguntas de la interacción guiada | `narrative-propose` gobierna cómo se explora una idea |
| **Plantillas** | **Estructura del resultado**: la forma/esqueleto del artefacto que produce una metodología, independiente del proceso | Esquema de ficha, documento o vista |
| **Catálogos** | **Índice y relaciones**: inventario y relaciones entre plantillas, recursos y metodologías; fuente de conciencia del inventario (TW7) | `_catalog.json` en `plantillas/` |
| **Referencias** | **Material del mundo**: contenido de apoyo del Autor (investigaciones, visuales) conservado sin confundirse con Canon | Referencias del Taller de Mundo (W13) |

- El **Taller de Herramientas gestiona y crea Skills y plantillas** como **capacidades objetivo** del Core. `[OBJETIVO]`
- **Plantilla sin metodología compatible**: es **válida** y **usable manualmente**; la superficie ofrece **crear o adaptar una metodología** que la aproveche. `[DECISIÓN CERRADA]`
- **Bindings explícitos**: la asociación **skill + plantilla + versiones** es un **binding explícito y versionado**, declarado en metadatos; nunca se infiere por coincidencia de nombres. `[DECISIÓN CERRADA]`
- **No confiar en la memoria del LLM**: la conciencia del inventario proviene del **catálogo/metadatos**, no de inyectar contenido completo ni de la memoria conversacional del proveedor (coherente con TW7). `[DECISIÓN CERRADA]`

---

## 2. Selector de Taller y árbol contextual de Skills

**[DECISIÓN CERRADA]** Las Skills se organizan por **Taller/capacidad** (árbol contextual), no como una lista plana global. El **Taller define el contexto operativo**; la **categoría funcional define el tipo de tarea** (sección 4). `[DECISIÓN CERRADA — TW2, TW3]`

- **Taller = contexto de trabajo.** El selector de Taller muestra exclusivamente los **talleres operativos** (`Mundo`, `Ideas`; futuros talleres creativos se añaden a esa lista). El Taller de Herramientas **no** aparece en el selector: es la superficie de gestión y co-creación, nunca un contexto operativo (sección 7; TW5/TW8/G13). La disponibilidad de navegación (Navbar) es un concepto distinto. El contexto operativo activo es **un solo Taller a la vez**: por defecto se muestran **solo las Skills del Taller actual**. `[DECISIÓN CERRADA — TW2]`
- **No existe "Todos los Talleres" como contexto operativo activo.** Skills de Talleres distintos pueden entrar en conflicto; como máximo existe una **vista de exploración de la biblioteca global** separada, de consulta, que no activa ni instrumenta Skills de otros Talleres. `[DECISIÓN CERRADA — TW2]`
- **Cada sesión recibe solo el alcance de su Taller**: la Skill activa, su versión, el mundo y el contexto autorizado. **Nunca recibe el árbol completo** a la vez (regla de scoping del subsistema). `[DECISIÓN CERRADA — subsistema, sección 3.3]`
- **Orden del árbol del Taller activo** (grupos plegables, orden alfabético dentro de cada grupo): `[DECISIÓN CERRADA — TW3]`

```
en el chat ──> fuera del chat ──> sin taller
```

- Los cruces entre Talleres requieren un **handoff explícito**; no se asume contexto de otro Taller. `[DECISIÓN CERRADA — TW2]`

---

## 3. Estados visibles de las Skills (disponibilidad en el chat)

**[DECISIÓN CERRADA — revisada por S2/S6]** La superficie **no expone ningún estado de activación**: no existe un botón que parezca encender/apagar una Skill. Cada Skill se presenta según su disponibilidad en el chat del mundo y su alcance de Taller:

| Estado visible | Significado | Regla |
|---|---|---|
| **En el chat** | La Skill está añadida al chat del mundo seleccionado | El chat elige solo entre las Skills añadidas según la conversación; añadir/quitar nombra ese efecto real |
| **Fuera del chat** | Skill publicada del Taller activo que no está añadida al chat | Sigue disponible en el catálogo; se puede añadir con una acción explícita |
| **Transversal** | Skill declarada compatible con otro Taller además del principal | Se muestra con chip propio dentro de su grupo, sin implicar activación |
| **Sin taller** | Skill sin Taller operativo (p. ej. legado `Herramientas`) | Bucket separado; nunca se oculta |

**Reglas de estado:**
- Una Skill **fuera del chat no entra sola**: el Autor decide si la añade o la adapta (sección 6.5). La detección de solapamientos **recomienda, no bloquea por defecto**. `[DECISIÓN CERRADA — TW4, TW7, revisada por S1/S5]`
- Los **solapamientos de tiempo de catálogo** (TW4/TW7) **no son colisiones de runtime**: detectar que dos skills se solapan en creación **no** prescribe qué inyecta el router en un turno. Las colisiones de runtime (ambigüedad, empate cercano, fail-open) son política del contrato de consumo de skills (`docs/architecture/skill-runtime-consumption-contract.md`, §3, SR3). `[DECISIÓN CERRADA]`
- **Quitar del chat** conserva la versión y el historial y solo la excluye del enrutamiento de chat; las sesiones existentes conservan su snapshot y pueden terminar. `[S5/S7]`
- La **cuarentena** (paquetes importados) es un estado del subsistema técnico, gestionado en la biblioteca (subsistema, sección 7.3); en superficie se muestra como importable solo tras revisión/validación.

---

## 4. Categorías funcionales, etiquetas y biblioteca global de consulta

**[DECISIÓN CERRADA]** Para evitar una taxonomía caótica se separa **Taller** (contexto operativo, sección 2) de **categoría funcional** (tipo de tarea). `[DECISIÓN CERRADA — TW6]`

- **Categorías funcionales base**: el conjunto acotado y curado de categorías es **Creación, Investigación, Diseño, Análisis, Organización y Visualización**. Cada Skill declara **una sola categoría funcional principal** de ese conjunto; evita duplicar la misma Skill en varias secciones. `[DECISIÓN CERRADA — TW6; resuelve A1]`
- **Etiquetas (tags) secundarias opcionales**: describen usos secundarios sin alterar la ubicación principal. `[DECISIÓN CERRADA — TW6]`
- **Clasificación visible** (constitución, G14): la biblioteca presenta tres categorías — **Oficiales** (creadas/aprobadas y firmadas por el Autor de Demiurgos), **Personalizadas** (creadas o derivadas por el Autor) y **Comunitarias** (compartidas por la comunidad). `fundacional`, `derived`, `co-created`, `verified` y `quarantined` son **atributos secundarios** de procedencia/confianza, no categorías excluyentes. La Skill Madre queda fuera de estas categorías (sección 5). `[DECISIÓN CERRADA — TW5]`
- **Estructura independiente del idioma**: la estructura de la Skill (propósito, flujo, ramas, permisos, validaciones) no depende del idioma; la **presentación** (nombres, descripciones, preguntas) se muestra según el idioma configurado. `[DECISIÓN CERRADA — TW6]`

**Biblioteca global de consulta** `[DECISIÓN CERRADA — TW7]`:

- Existe un **inventario completo** de Skills cargadas, estén o no **en el chat**, accesible como **vista de consulta/exploración separada** del contexto operativo activo (TW2).
- La **conciencia del inventario proviene del catálogo/metadatos**, no de inyectar todas las Skills completas en cada conversación.
- Sirve para **detectar solapamientos y similitudes** con nuevas candidatas (sección 6.1): reutilizar, extender o derivar en lugar de duplicar.
- Una Skill fuera del chat puede **advertirse como existente**, pero **no debe añadirse automáticamente**; la detección recomienda, no bloquea por defecto.
- **Acciones permitidas en consulta**: la vista de exploración permite **consultar, buscar, ver detalles, comparar y adaptar**; **nunca añade al chat ni cambia el contexto operativo activo** (no es un contexto operativo; ver TW2). `[DECISIÓN CERRADA — resuelve A2]`

> Las decisiones abiertas A1 (conjunto de categorías funcionales) y A2 (profundidad de la biblioteca global) quedan **cerradas** por las decisiones de esta sección; ver sección 9.1 (TW17, TW18).

---

## 5. Skill Madre: invisible y protegida

**[DECISIÓN CERRADA — TW8]** La **Skill Madre** (constitución, G13/10.5) es una capacidad protegida que sirve para **co-crear nuevas Skills**:

- **Instalación obligatoria** con Demiurgos como parte del Core; no requiere activación del Autor.
- **Invisible en el árbol de skills**: no aparece entre las Skills del Taller; se referencia solo para delimitar alcance.
- **No editable, no eliminable y no añadible al chat** desde el Taller de Herramientas.
- **No pertenece a la biblioteca gestionada por el Autor** ni puede ser reemplazada por un borrador.
- **Se actualiza solo mediante releases oficiales** de la plataforma; nunca vía importación de paquetes.
- **Co-creación**: Hermes conversa y redacta la propuesta; el backend valida/compila y protege el kernel; el Autor aprueba la publicación (constitución, G13). Hermes no escribe ni decide canon (constitución, sección 5).

La **mecánica de co-creación** que la Skill Madre guía se contrata en la sección 6.

---

## 6. Co-creación de Skills con la Skill Madre

Este contrato consolida la UX de co-creación acordada. Aplica la identidad del **Asistente de Demiurgos** (constitución, G15/10.6): propone, el Autor decide, y distingue **regla / recomendación / posibilidad**.

### 6.1 Detección, handoff, candidatas y autoguardado `[DECISIÓN CERRADA — TW9]`

- La **detección de intención de crear una skill** puede ocurrir **desde cualquier Taller** (el Autor lo menciona donde está), pero la **creación formal solo ocurre en el Taller de Herramientas** mediante un **handoff explícito**: el sistema reconoce la intención y ofrece pasar al Taller de Herramientas; el cruce respeta la regla de handoff explícito (sección 2).
- Una **skill candidata** (propuesta de borrador) **solo se guarda con confirmación del Autor**; nunca se persiste automáticamente una candidata.
- Una vez aceptada la creación y abierto el borrador, ese borrador **puede autoguardarse** para evitar pérdidas. El **autoguardado conserva el borrador y su historial**, pero **nunca publica ni activa automáticamente**; al regresar, el Autor ve **claramente dónde quedó** y qué estaba pendiente. `[DECISIÓN CERRADA — TW9]`
- El asistente **compara la intención emergente contra el inventario completo** (sección 4) mediante **consultas ligeras** y muestra coincidencias **solo cuando hay suficiente señal** y en **hitos conversacionales**; si existe una Skill cercana, **propone copiar/adaptar** con aprobación del Autor. La **original permanece intacta** y la derivada muestra su **procedencia** de forma visible (sección 6.5). `[DECISIÓN CERRADA — TW7, TW13]`

### 6.2 Ritmo conversacional y progreso `[DECISIÓN CERRADA — TW10]`

- **Toda skill conversacional hace una sola pregunta por turno**; el asistente no acumula preguntas ni las agrupa en bloques. Este requisito es **inmutable y universal**: aplica a todas las Skills de Demiurgos, no solo a la Skill Madre. La secuencia es **dinámica y adaptativa**: puede omitir preguntas irrelevantes, profundizar ante ambigüedad y resumir hipótesis para confirmación. `[DECISIÓN CERRADA — TW10]`
- La **Skill Madre crea una primera versión en 15–20 preguntas máximo**, **adaptativas** (el número y la profundidad dependen de las respuestas; nunca un cuestionario fijo). El límite es **techo, no objetivo**: puede converger antes. `[DECISIÓN CERRADA — constitución G13/10.5; TW10]`
- El **progreso se reporta por hitos, no por porcentaje** (p. ej. "propósito definido", "alcance definido", "borrador listo"), con estados **completado / actual / pendiente** que reflejan retrocesos o revisiones sin romper la conversación. `[DECISIÓN CERRADA — TW10]`
- **Hitos definitivos de la Skill Madre** (para el reporte de progreso y la comparación con el catálogo): **Propósito → Alcance → Flujo principal → Ramas y reglas → Borrador listo → Revisión y publicación**. `[DECISIÓN CERRADA — resuelve A3]`

### 6.3 Método de co-creación `[DECISIÓN CERRADA — TW11]`

- **Descubrir el propósito antes de exigir nombre**: el asistente explora qué debe lograr la skill antes de preguntar cómo llamarla; el nombre se propone cuando el propósito está claro.
- **Definir Taller y alcance temprano**: antes de profundizar, se acuerda a qué Taller pertenece la skill y cuál es su alcance.
- El desplegable 'Taller' de la co-creación manual ofrece solo talleres operativos (por defecto Mundo); 'Sin taller' deja de ser opción de autoría — toda Skill creada manualmente declara su taller de origen. El cubo 'Sin taller' del árbol sigue existiendo como visibilidad de registros importados o heredados sin taller operativo.
- **Alcance de mundo**: la Skill Madre pregunta si la Skill será **específica de un mundo** o **transversal** (para todos los mundos del Autor). Para una Skill específica, el Autor **aprueba explícitamente el acceso al contexto estructural** del mundo; para una transversal, la Skill Madre **no incorpora contenido específico de ningún mundo**. `[DECISIÓN CERRADA — TW11]`
- **Flujo principal antes de ramas**: se construye el flujo principal de la skill primero; las variantes (derivaciones, casos de borde) se exploran después.
- **Rama vs Skill distinta**: si la nueva capacidad tiene **la misma finalidad y metodología**, se modela como **rama/contexto** de la skill existente; si hay una **diferencia fundamental** (finalidad, metodología o entidad objetivo), se crea una **Skill distinta**. `[DECISIÓN CERRADA — TW11]`

### 6.4 Editor visual + chat sincronizado, validación e historial `[DECISIÓN CERRADA — TW12]`

- La co-creación muestra un **borrador visual editable** (propósito, alcance, flujo principal, ramas, reglas y preguntas pendientes) **sincronizado con el chat**: el Autor puede **editar directamente** el borrador o seguir conversando; ambos lados se mantienen coherentes. La sincronización es **bidireccional**: los cambios directos del Autor actualizan la conversación/validación y las solicitudes aceptadas en chat actualizan el lienzo. `[DECISIÓN CERRADA — TW12]`
- **Chat para intención y razonamiento; lienzo para manipular estructura** y comprobar el resultado. Ningún cambio salta la validación del borrador.
- La **validación se centraliza en un panel** visible (manifest, contrato compilado, errores) y se actualiza con el borrador.
- Las advertencias del borrador tienen tres estados explícitos: **Pendiente**, **Resuelta** y **Aceptada por Autor**. Una advertencia pendiente **no se corrige automáticamente** (no hay "deshacer automático" de decisiones del Autor).
- El editor de borrador ofrece **undo/redo, restauración e historial**, y **autoguardado** (6.1); el historial permite recuperar versiones del borrador sin pérdida silenciosa.

### 6.5 Adaptación por comparación visual y procedencia `[DECISIÓN CERRADA — TW13, TW14]`

- La **adaptación** de una Skill (incluida una **bloqueada**, sección 3) se presenta mediante una **comparación visual lado a lado** entre la original y la propuesta adaptada, no como un diff técnico.
- Los cambios se clasifican como **conservados, modificados, añadidos o eliminados**; la **original es solo lectura** y la adaptación es un **nuevo borrador derivado editable**.
- La **procedencia** es visible durante **todo el ciclo de vida**: cada borrador o Skill adaptada indica la **Skill original y la versión** de la que deriva, incluso si la derivada cambia mucho respecto a la original. `[DECISIÓN CERRADA — TW14]`
- **Editar una Skill publicada/en producción crea un borrador derivado** de la versión publicada vigente; la original permanece **intacta y operativa** hasta que la nueva versión se valide, apruebe y publique. Las Skills **protegidas/oficiales requieren derivación**, nunca edición directa. `[DECISIÓN CERRADA — TW13]`

### 6.6 Revisión, compilación, publicación y método por sesión `[DECISIÓN CERRADA — TW15, revisada por S2/S6]`

- La **revisión final es guiada**: el asistente presenta un **resumen humano** de lo acordado y pone a disposición los **detalles completos útiles** (diferencias, decisiones clave) para que el Autor verifique.
- **Aprobación, validación/compilación y publicación son pasos separados**; publicar **nunca** elige el método del asistente ni lo fija para un mundo. `[DECISIÓN CERRADA — TW15]`
- **El método del asistente de personajes se elige al iniciar la sesión** (selector con `De fábrica` por defecto) y queda fijado a esa sesión. No hay un estado permanente escondido en la biblioteca. `[S2/S6]`
- **Solo la familia de creación de personajes puede ser método**: la fundacional `narrative-character-creation`, el contrato integrado `guided-character-v1` y sus derivadas (`parent_skill_id`). Cronología y Sistemas quedan fuera; el servidor rechaza la selección aunque se llame por API. `[S4]`
- **Compatibilidad**: una activación heredada se usa solo como valor inicial del selector cuando es elegible; una activación no elegible se ignora para sesiones nuevas y **nunca se borra**. Las sesiones ya abiertas conservan su snapshot. `[S7]`
- La versión publicada **no se elimina** al cambiar de método: el historial de versiones sigue visible y restaurable (rollback a publicada, nunca a borrador).
- Solo los **borradores son editables directamente**; una Skill publicada/en producción no se modifica en sitio (sección 6.5). El borrador tiene estados explícitos: **pendiente** y **lista para publicar**; publicar produce la versión inmutable.
- La UX de versiones mantiene **visible el estado actual** (insignia persistente de versión publicada vigente vs borrador) y presenta el flujo en **lenguaje simple**, con detalles técnicos **colapsados**.

### 6.7 Transparencia útil y límites frente a detalles técnicos `[DECISIÓN CERRADA — TW16]`

- El asistente **muestra su comportamiento, permisos, dependencias y consecuencias** de forma comprensible (qué hará la skill, qué puede y qué no, de qué depende, qué implicaciones tiene añadirla al chat).
- La **vista final de aprobación es una proyección comprensible** de la Skill candidata, no el contrato técnico completo sin filtrar: resumen en lenguaje humano (propósito, alcance, flujo, ramas, reglas, dependencias y permisos), con opción de **expandir detalles avanzados**. `[DECISIÓN CERRADA — TW16]`
- La vista distingue **visualmente y con etiquetas** lo **decidido por el Autor**, lo **propuesto por el Asistente** y lo **exigido por Demiurgos**; el **artefacto aprobado subyacente es exactamente el candidato revisado**. `[DECISIÓN CERRADA — TW16]`
- Se **ocultan los mecanismos técnicos internos** (rutas, provenance interna, identificadores de autoridad, proveedor subyacente) en toda la copia visible (constitución, 7.1 y 10.6).
- **Una Skill creada fuera del Taller de Herramientas no se ejecuta como Skill válida**: carece de validación/compilación; esto es por **integridad del sistema**, no como castigo. `[DECISIÓN CERRADA — TW16]`

---

## 7. Frontera con el Taller de Mundo y futuros Talleres

**[DECISIÓN CERRADA]** El Taller de Herramientas **gestiona y co-crea metodologías**; el Taller de Mundo **ejecuta** los flujos guiados que esas metodologías gobiernan:

| Capacidad | Vive en |
|---|---|
| Crear/editar/publicar/añadir al chat/importar/exportar Skills y co-crear con la Skill Madre | **Taller de Herramientas** (este contrato) |
| Ejecutar flujos guiados (p. ej. creación guiada de personajes) con el método elegido al iniciar la sesión | **Taller de Mundo** (`docs/architecture/world-workshop.md`) |
| Contenido factual del mundo (lore, personajes, canon) | **Taller de Mundo** |

- **Método por sesión**: el asistente de personajes elige su método al iniciar la sesión (fábrica por defecto) y lo fija para esa conversación; cambiar de método exige una sesión nueva. El chat libre no cambia: sigue eligiendo solo entre las Skills añadidas al mundo. `[S2/S3/S6]`
- **Cruces entre Talleres** requieren **handoff explícito** (sección 2); no se asume contexto de otro Taller.
- **Futuros Talleres** (módulos de pago, constitución G10) aparecen en el Navbar como teaser "Próximamente" hasta su disponibilidad; el árbol de Skills crecerá por **dominios coherentes**, no por cada Skill individual. `[DECISIÓN CERRADA — TW2]`
- Este contrato **no define** el Taller de Narrativa ni otros talleres futuros; solo **delimita la frontera** para que sus futuros contratos no colisionen con la gestión de metodologías.

---

## 8. Evidencia de implementación actual `[ACTUAL]`

Estado verificado en el repositorio (existe hoy; no es objetivo):

| Capacidad | Evidencia |
|---|---|
| Ruta del Taller de Herramientas | `frontend/src/App.tsx` — `/taller-herramientas` → `ToolWorkshop` |
| Shell del Taller (Navbar + selector de mundo + biblioteca) | `frontend/src/pages/ToolWorkshop.tsx` |
| Biblioteca de metodologías (listado, publicar borrador validado, añadir/quitar del chat) | `frontend/src/components/organisms/MethodologyLibrary.tsx`, `MethodologyStatePanel.tsx` |
| API de metodologías | `frontend/src/api/methodologies.ts` — `status`, `guided-methods`, `drafts`, `drafts/{id}/publish`, `companions`, `activate`/`rollback` (legado) |
| Subsistema backend | `src/tools/demiurgos-suite/wiki/methodology_library.py`, `methodology_compiler.py`, `methodology_trust.py` |
| Sembrado de skills fundacionales (mecanismo completo, sección 8.1) | `data/methodology/seeds/narrative-character-creation/` (`manifest.yaml` + `source.md` + `checksums.json`), `src/tools/demiurgos-suite/wiki/methodology_seed.py` (carga + verificación + instalación), `methodology_trust.py` (inyección server-side de Oficiales + `fundacional`), hook de arranque `_seed_foundational_skills` en `api_server.py` |
| Navbar por talleres disponibles | `frontend/src/components/organisms/Navbar.tsx` — contrato `available`/`teaser`, teaser "Próximamente" |
| Selector de Taller y árbol contextual (sección 2) | `frontend/src/components/organisms/TallerExplorerSidebar.tsx`, `TallerTree.tsx`; estados y agrupación TW3 en `frontend/src/lib/tallerStates.ts` |
| Disponibilidad en el chat, categorías funcionales y etiquetas en la UI (secciones 3–4) | `frontend/src/components/organisms/TallerTree.tsx` (grupos `enChat`/`fueraDelChat` + cubo "Sin taller"), `InventoryFilterBar.tsx`, `MethodologyDetailView.tsx`, `MethodologyStatePanel.tsx`; copia en `frontend/src/i18n/messages.ts` (`tallerTree.group.*`) |
| Biblioteca global de consulta (sección 4) | `frontend/src/components/organisms/GlobalMethodologyLibrary.tsx` y `MethodologyComparePanel.tsx`; API de catálogo `GET /api/methodologies/inventory` en `frontend/src/api/methodologies.ts` |
| Skill Madre y co-creación conversacional (secciones 5–6) | `frontend/src/components/organisms/CoCreationPanel.tsx`, `ManualSkillCreator.tsx`, `frontend/src/hooks/useCoCreation.ts`, `frontend/src/api/coCreation.ts`; kernel en `src/tools/demiurgos-suite/wiki/hermes_co_creation_provider.py` (prompt de la Skill Madre), `co_creation_protocol.py`, `co_creation_session_store.py` |
| Editor visual + chat sincronizado, validación e historial (sección 6.4) | `frontend/src/components/organisms/CoCreation/CoCreationCanvas.tsx`, `DraftHistoryPanel.tsx`; rutas `PUT /api/co-creation/sessions/{id}/canvas`, `POST /api/co-creation/sessions/{id}/validate`, `GET /api/co-creation/sessions/{id}/history` |
| Comparación visual de adaptación y procedencia (sección 6.5) | `frontend/src/components/organisms/CoCreation/AdaptationComparePanel.tsx`, `ProvenanceBadge.tsx`; ruta `POST /api/co-creation/derive` |
| Vista de aprobación comprensible (sección 6.7) | `CoCreationPanel.tsx` — proyección de revisión con atribución "decidido por el Autor / propuesto por el Asistente / exigido por Demiurgos" (`frontend/src/i18n/messages.ts`, `cocreation.attribution.*`) |
| API de co-creación (familia de rutas) | `src/tools/demiurgos-suite/wiki/api_server.py` — **16** rutas `/api/co-creation/*`: `POST /sessions`, `POST /sessions/{id}/turn`, `GET /sessions/{id}`, `GET /sessions/{id}/progress`, `POST /sessions/{id}/materialize`, `POST /sessions/{id}/publish`, `POST /sessions/{id}/trigger/approve`, `POST /sessions/{id}/activate`, `POST /derive`, `PUT /sessions/{id}/canvas`, `POST /sessions/{id}/validate`, `GET /sessions/{id}/history`, `POST /sessions/{id}/history/restore`, `POST /sessions/{id}/warnings/{idx}/status`, `POST /sessions/{id}/pending-questions/{idx}/status`, `POST /sessions/{id}/adjuntos` |
| Materialización determinista de borrador de co-creación | `src/tools/demiurgos-suite/wiki/co_creation_materializer.py` (`create_draft` + `compile_methodology`; nunca `publish`), `co_creation_attachments.py` (adjuntos) |

**Corrección (2026-10-12, verificado en `01fc2f2d`).** La versión anterior de este apartado enumeraba como "no implementado (superficie objetivo)" el selector de Taller y el árbol contextual, los estados bloqueada/transversal, las categorías funcionales y etiquetas en la UI, la Skill Madre y la co-creación conversacional, el editor visual + chat, la comparación visual de adaptación y la vista de aprobación comprensible. La verificación en el árbol muestra que **esas superficies existen hoy** y por eso pasan a la tabla de evidencia `[ACTUAL]`; la lista "no implementado" queda retirada. No se reintroduce como implementado nada sin evidencia: lo que todavía no existe en el repositorio conserva su etiqueta `[OBJETIVO]`/`[DECISIÓN CERRADA]` en su sección (p. ej. la gestión de **plantillas**, sección 1.1).

> **Nota de verificación del seam de co-creación (2026-10-12).** Las superficies existen y el seam `_CO_CREATION_MATERIALIZER` de `src/tools/demiurgos-suite/wiki/api_server.py` **está cableado en el arranque de producción**: se enlaza perezosamente (`_LazyBinding`) junto a `_CO_CREATION_PROVIDER`, de modo que construye `CoCreationMaterializer(_methodology_library())` en el primer uso —sin construir ni sembrar la biblioteca al importar el módulo— y los tests siguen reemplazando el atributo después del import. En consecuencia, `POST /api/co-creation/sessions/{id}/materialize`, `POST /api/co-creation/derive`, `PUT /api/co-creation/sessions/{id}/canvas` y `POST /api/co-creation/sessions/{id}/validate` ya **no** responden 503 `capability_unavailable` por falta de materializador. El resto del flujo de co-creación (crear sesión, `turn`, `progress`, `trigger/approve`, `publish`, `activate`) no depende de ese seam y sigue igual. Regresión cubierta en `src/tools/demiurgos-suite/wiki/tests/test_co_creation_api.py` (`test_production_materializer_seam_is_wired`, `test_materialize_route_does_not_fail_closed_through_production_seam`). Procedimiento manual de extremo a extremo en `docs/architecture/co-creation-e2e-runbook.md`.

> Regla de etiquetas: todo lo listado como `[ACTUAL]` está verificado; las superficies objetivo de las secciones 1–7 llevan su propia etiqueta y **no se presentan como implementadas**.

### 8.1 Skills fundacionales: mecanismo de sembrado `[DECISIÓN CERRADA — TW5, G14]` `[ACTUAL]`

Las skills fundacionales son metodologías oficiales que Demiurgos instala y mantiene desde el propio repositorio, sin pasar por la biblioteca gestionada por el Autor:

- **Catálogo sembrado en el repo**: cada skill fundacional vive en `data/methodology/seeds/<skill-id>/` con `manifest.yaml` (compilable por el compilador del subsistema), `source.md` y `checksums.json` (SHA-256 de los bytes empaquetados). El catálogo es extensible por directorio; la semilla vigente del repositorio publica exactamente `narrative-character-creation@1.2` (verificado en `data/methodology/seeds/narrative-character-creation/manifest.yaml`, `01fc2f2d`). Por reconciliación **insert-only**, una instalación existente conserva además las versiones sembradas con anterioridad (`1.0`, `1.1`) sin re-apuntar activaciones ni compañeros (TW15).
- **Instalación en primer arranque, validada por compilación**: en la inicialización perezosa de la biblioteca, el servidor compila cada entrada con `compile_methodology` (los reclamos de autoridad se rechazan) e inserta la versión publicada con `clasificacion="Oficiales"` y el atributo `fundacional` **inyectados por el servidor** — única fuente: `methodology_trust.py`; la UI nunca los envía (sección 4). Un fallo de integridad (checksum o compilación) aborta el sembrado completo: cero registros parciales y el servidor sigue sirviendo sin semillas.
- **Reconciliación insert-only**: en cada arranque se inserta la versión sembrada solo si es más nueva que todas las versiones almacenadas del skill; las versiones antiguas se conservan y **nunca se re-apuntan activaciones ni compañeros** (TW15). Los reintentos son idempotentes: mismo digest ⇒ `existing` (skip); misma versión con digest distinto ⇒ conflicto permanente — la inmutabilidad gana sobre el auto-curado.
- **Derivación demuestra a Personalizadas**: adaptar una skill fundacional crea una derivada `Personalizadas` sin `fundacional`, con procedencia intacta (TW13, TW14).
- **No-eliminación por atributo**: `soft_delete` rechaza cualquier registro con `fundacional` en `trust_attributes`; la protección se ancla en el atributo, no en la categoría — un `Oficiales` firmado sin `fundacional` seguiría siendo eliminable (G14).
- **Skill Madre intacta**: el sembrado no toca la Skill Madre (G13, sección 5); sigue fuera de la biblioteca gestionada.

---

## 9. Decisiones cerradas y abiertas

### 9.1 Cerradas (no revertir sin nuevo acuerdo)

| ID | Decisión |
|---|---|
| **TW1** | El Taller de Herramientas es la **primera sección del Navbar**, la **base instrumental** de los talleres creativos y parte del **Core gratuito del MVP** (constitución, G10); presenta "Metodologías" y usa "Skill" como término técnico (sección 1) |
| **TW2** | **Taller = contexto de trabajo (talleres operativos); categoría funcional = tipo de tarea**. Por defecto solo se muestran las Skills del Taller activo; **no existe "Todos los Talleres" como contexto operativo activo**, solo una vista de **exploración de biblioteca global** separada; los cruces requieren **handoff explícito** (secciones 2 y 4) |
| **TW3** | **Orden del árbol** del Taller activo: activas del Taller → transversales activas → inactivas del Taller → transversales inactivas; grupos plegables, orden alfabético (sección 2) |
| **TW4** | **Estados visibles revisados (S1/S2)**: la superficie muestra disponibilidad en el chat (En el chat / Fuera del chat), alcance transversal y bucket Sin taller; **no existe ningún estado ni botón de activación**; el método del asistente se elige al iniciar la sesión (sección 3) |
| **TW5** | **Clasificación visible** Oficiales/Personalizadas/Comunitarias con atributos secundarios (`fundacional`, `derived`, `co-created`, `verified`, `quarantined`); la Skill Madre queda fuera (sección 4; constitución, G14) |
| **TW6** | **Categoría funcional principal única + etiquetas secundarias**; la **estructura de la Skill es independiente del idioma** y la presentación sigue el idioma configurado (sección 4) |
| **TW7** | **Biblioteca global de consulta** con **inventario completo** (activadas o no); conciencia desde catálogo/metadatos; detección de solapamientos que **recomienda, no bloquea por defecto** (secciones 4 y 6.1) |
| **TW8** | **Skill Madre invisible y protegida**: no editable, no eliminable, no desactivable, solo releases oficiales, fuera de la biblioteca gestionada (sección 5; constitución, G13/10.5) |
| **TW9** | **Detección desde cualquier Taller, creación formal solo en el Taller de Herramientas con handoff explícito**; candidatas solo con confirmación; **autoguardado** de borradores y progreso que nunca publica ni activa (sección 6.1) |
| **TW10** | **Una pregunta por turno** (inmutable y universal para todas las Skills); **primera versión en 15–20 preguntas máximo** adaptativas; **progreso por hitos, no por porcentaje** (sección 6.2; constitución, G13/10.5) |
| **TW11** | **Método de co-creación**: propósito antes que nombre; Taller/alcance temprano; alcance mundo vs transversal; flujo principal antes de ramas; **rama vs Skill distinta** (sección 6.3) |
| **TW12** | **Borrador visual editable + chat sincronizado bidireccional**; validación centralizada en panel; advertencias Pendiente/Resuelta/Aceptada por Autor; **sin deshacer automático**; undo/redo/restauración/historial (sección 6.4) |
| **TW13** | **Adaptación por comparación visual lado a lado** (conservado/modificado/añadido/eliminado); original solo lectura; adaptación = nuevo borrador derivado; editar una publicada crea borrador derivado (secciones 6.5 y 3) |
| **TW14** | **Procedencia visible durante todo el ciclo de vida** (Skill original + versión) de cada borrador o Skill derivada (sección 6.5) |
| **TW15** | **Revisión, compilación y publicación separadas**; publicar nunca elige método; **método por sesión** al iniciar el asistente, con `De fábrica` por defecto; solo la familia de personajes es elegible; activaciones heredadas solo como default elegible y nunca borradas (sección 6.6) |
| **TW16** | **Transparencia útil**: comportamiento/permisos/dependencias/consecuencias comprensibles; vista final como **proyección comprensible** que distingue decidido por el Autor / propuesto por el Asistente / exigido por Demiurgos; se ocultan mecanismos técnicos internos; una Skill creada fuera del Taller no se ejecuta como válida (sección 6.7; constitución, G15/10.6) |
| **TW17** | **Categorías funcionales base**: Creación, Investigación, Diseño, Análisis, Organización y Visualización; una sola categoría principal + etiquetas secundarias (sección 4; **resuelve A1**) |
| **TW18** | **Profundidad de la biblioteca global**: consultar, buscar, ver detalles, comparar y adaptar; **nunca activación directa ni cambio de contexto operativo** (sección 4; **resuelve A2**) |
| **TW19** | **Hitos definitivos de la Skill Madre**: Propósito → Alcance → Flujo principal → Ramas y reglas → Borrador listo → Revisión y publicación (sección 6.2; **resuelve A3**) |
| **TW20** | **Vocabulario de superficie**: Metodologías/Skills = cómo trabaja el asistente; Plantillas = estructura del resultado; Catálogos = índice/relaciones; Referencias = material del mundo. El Taller gestiona/crea Skills y plantillas como capacidades objetivo; una plantilla sin metodología compatible es válida y usable manualmente, con opción de crear/adaptar metodología; bindings explícitos skill+plantilla+versiones; la conciencia del inventario proviene del catálogo, no de la memoria del LLM (sección 1.1) |

### 9.2 Abiertas (acotadas; no se expande el alcance sin consolidar primero)

> Sin decisiones abiertas pendientes: A1–A3 quedaron **cerradas** (TW17–TW19). Cualquier nuevo punto abierto se registrará aquí.

---

## 10. Definition of ready para SDD futuro

Un SDD de este dominio **solo** puede comenzar cuando se cumplan todos:

- [ ] Se leyeron esta constitución global, este contrato de superficie y el contrato del subsistema técnico (`skill-library-and-guided-character-creation.md`).
- [ ] Se verificó el runtime real (CodeGraph/tests) antes de asumir cualquier `[ACTUAL]` (sección 8).
- [ ] Las decisiones abiertas que tocan el cambio están resueltas y anotadas (A1–A3 quedaron cerradas como TW17–TW19).
- [ ] El cambio respeta las invariantes `[ACTUAL]` de la constitución (secciones 5, 7) y las fronteras de dominio.
- [ ] Todo comportamiento nuevo se etiqueta `[ACTUAL]`/`[OBJETIVO]`/`[PROPUESTO]` y no se presenta como implementado.
- [ ] El SDD declara explícitamente qué NO toca (kernel, compilador/runtime del subsistema, escrituras gated, AGENTS.md) y referencia el contrato del subsistema técnico cuando toca la biblioteca.
- [ ] El SDD referencia el Taller de Mundo (`docs/architecture/world-workshop.md`) cuando el cambio cruce la frontera de activación/ejecución.
- [ ] Las pruebas cubren las invariantes afectadas (handoff explícito, estados de Skill, una sola versión activa, cero escrituras sin aprobación) y las ramas de fallo relevantes.
