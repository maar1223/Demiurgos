# Taller de Herramientas — Contrato de Taller

> **Contrato de taller.** Este documento es el contrato de **superficie y producto** del **Taller de Herramientas** de Demiurgos: lo que el Autor ve, elige y co-crea dentro de este Taller del Core. **No es un artefacto SDD** ni sustituye a la constitución global. El contrato del **subsistema técnico** (biblioteca gestionada, paquete/manifest, compilador, runtime, ciclo de vida, import/export/cuarentena y creación guiada de personajes) vive en `docs/architecture/skill-library-and-guided-character-creation.md` y este documento lo referencia sin repetirlo. Toda afirmación lleva la etiqueta de estado correspondiente; lo no implementado no se presenta como existente.

| Campo | Valor |
|---|---|
| Estado | Contrato de taller (nuevo — superficie separada del subsistema técnico) |
| Versión del documento | 1.3 |
| Fecha | 2026-08-17 |
| Autor | Demiurgos (orquestación) |
| Idioma | Español neutro (prosa técnica) |
| Alcance | TALLER (superficie): **Taller de Herramientas** — selector de Taller y árbol contextual de Skills, estados visibles (activa/transversal/inactiva/bloqueada), categorías funcionales y etiquetas, biblioteca global de consulta, Skill Madre protegida, co-creación de Skills con la Skill Madre (detección/handoff, ritmo conversacional, editor visual + chat, adaptación, revisión/publicación/activación), transparencia y frontera con otros Talleres |
| Depende de | `docs/architecture/demiurgos-platform.md` (constitución global del producto) |
| Relación con SDD | Requisito previo. Ningún SDD de este dominio debe comenzar sin este contrato aprobado y sus decisiones abiertas resueltas |
| Documentos relacionados | `docs/architecture/demiurgos-platform.md`, `docs/architecture/skill-library-and-guided-character-creation.md` (subsistema técnico), `docs/architecture/world-workshop.md` (Taller de Mundo), `docs/architecture/foundational-research-skill.md` (Skill Fundacional de Investigación — skill transversal del Core), `AGENTS.md` (límites de dominio), runtime en `frontend/src/` y `src/tools/demiurgos-suite/wiki/` |

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

**[DECISIÓN CERRADA]** El **Taller de Herramientas** es la superficie del Core donde el Autor **gestiona y co-crea las metodologías de trabajo** (Skills) que luego gobiernan los flujos guiados de la plataforma. Se presenta como la primera sección del Navbar y la **base instrumental de los talleres creativos** (constitución, G10). Dentro contiene las **Metodologías**: métodos para **crear, editar, publicar (versiones inmutables), activar, importar/exportar, compartir y eliminar** formas de trabajo; **"Skill" permanece como nombre técnico del paquete**. `[DECISIÓN CERRADA]`

| El Taller de Herramientas ES | El Taller de Herramientas NO es |
|---|---|
| El lugar donde el Autor gestiona sus metodologías (Skills) y **co-crea nuevas** con la Skill Madre | Un formulario técnico de Skill ID/Markdown como flujo principal |
| Una superficie conversacional asistida: el Asistente propone, el Autor decide | Un editor que persiste o publica sin aprobación explícita |
| La puerta de entrada a la **biblioteca global** y a la activación por mundo | Un runtime de ejecución: los flujos guiados se ejecutan en el Taller de Mundo (sección 7) |
| Transparente sobre qué publica y qué implica activar | Un panel que oculta sus consecuencias o sus permisos |

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

- **Taller = contexto de trabajo.** El selector de Taller muestra los talleres disponibles (Core hoy; futuros módulos como teaser). El contexto operativo activo es **un solo Taller a la vez**: por defecto se muestran **solo las Skills del Taller actual**. `[DECISIÓN CERRADA — TW2]`
- **No existe "Todos los Talleres" como contexto operativo activo.** Skills de Talleres distintos pueden entrar en conflicto; como máximo existe una **vista de exploración de la biblioteca global** separada, de consulta, que no activa ni instrumenta Skills de otros Talleres. `[DECISIÓN CERRADA — TW2]`
- **Cada sesión recibe solo el alcance de su Taller**: la Skill activa, su versión, el mundo y el contexto autorizado. **Nunca recibe el árbol completo** a la vez (regla de scoping del subsistema). `[DECISIÓN CERRADA — subsistema, sección 3.3]`
- **Orden del árbol del Taller activo** (grupos plegables, orden alfabético dentro de cada grupo): `[DECISIÓN CERRADA — TW3]`

```
activas del Taller ──> transversales activas ──> inactivas del Taller ──> transversales inactivas
```

- Los cruces entre Talleres requieren un **handoff explícito**; no se asume contexto de otro Taller. `[DECISIÓN CERRADA — TW2]`

---

## 3. Estados visibles de las Skills

**[DECISIÓN CERRADA — TW4]** La superficie presenta cada Skill en uno de estos estados:

| Estado | Significado | Regla |
|---|---|---|
| **Activa** | Skill del Taller activo con **una versión activa** que gobierna los nuevos flujos guiados | La activación es por mundo (subsistema, 16.a); una sola versión activa por alcance (sección 6.6) |
| **Transversal** | Skill declarada compatible con otro Taller además del principal | Aparece en el árbol del Taller activo **después de las activas propias**; solo si está activa como transversal **activa** (TW3) |
| **Inactiva** | Skill publicada pero **no activa** en el mundo/alcance actual | Conserva versión e historial; no gobierna sesiones nuevas; puede reactivarse (subsistema, 16.k) |
| **Bloqueada** | Skill transversal **incompatible con el Taller activo** (conflicto de compatibilidad o validación) | Se muestra bloqueada con **explicación clara del conflicto** y **opción de adaptarla**; no participa en el runtime hasta que el Autor la adapte, valide y active explícitamente; la original permanece intacta `[DECISIÓN CERRADA — TW4]` |

**Reglas de estado:**
- Una Skill **bloqueada no se desbloquea sola**: el Autor decide entre adaptarla (sección 6.5) o dejarla sin activar. La detección de solapamientos **recomienda, no bloquea por defecto**. `[DECISIÓN CERRADA — TW4, TW7]`
- **Desactivar** conserva la versión y el historial pero impide **nuevas sesiones**; las sesiones existentes conservan su snapshot y pueden terminar. `[DECISIÓN CERRADA — subsistema, 16.k]`
- La **cuarentena** (paquetes importados) es un estado del subsistema técnico, gestionado en la biblioteca (subsistema, sección 7.3); en superficie se muestra como importable solo tras revisión/validación.

---

## 4. Categorías funcionales, etiquetas y biblioteca global de consulta

**[DECISIÓN CERRADA]** Para evitar una taxonomía caótica se separa **Taller** (contexto operativo, sección 2) de **categoría funcional** (tipo de tarea). `[DECISIÓN CERRADA — TW6]`

- **Categorías funcionales base**: el conjunto acotado y curado de categorías es **Creación, Investigación, Diseño, Análisis, Organización y Visualización**. Cada Skill declara **una sola categoría funcional principal** de ese conjunto; evita duplicar la misma Skill en varias secciones. `[DECISIÓN CERRADA — TW6; resuelve A1]`
- **Etiquetas (tags) secundarias opcionales**: describen usos secundarios sin alterar la ubicación principal. `[DECISIÓN CERRADA — TW6]`
- **Clasificación visible** (constitución, G14): la biblioteca presenta tres categorías — **Oficiales** (creadas/aprobadas y firmadas por el Autor de Demiurgos), **Personalizadas** (creadas o derivadas por el Autor) y **Comunitarias** (compartidas por la comunidad). `fundacional`, `derived`, `co-created`, `verified` y `quarantined` son **atributos secundarios** de procedencia/confianza, no categorías excluyentes. La Skill Madre queda fuera de estas categorías (sección 5). `[DECISIÓN CERRADA — TW5]`
- **Estructura independiente del idioma**: la estructura de la Skill (propósito, flujo, ramas, permisos, validaciones) no depende del idioma; la **presentación** (nombres, descripciones, preguntas) se muestra según el idioma configurado. `[DECISIÓN CERRADA — TW6]`

**Biblioteca global de consulta** `[DECISIÓN CERRADA — TW7]`:

- Existe un **inventario completo** de Skills cargadas, estén **activadas o desactivadas**, accesible como **vista de consulta/exploración separada** del contexto operativo activo (TW2).
- La **conciencia del inventario proviene del catálogo/metadatos**, no de inyectar todas las Skills completas en cada conversación.
- Sirve para **detectar solapamientos y similitudes** con nuevas candidatas (sección 6.1): reutilizar, extender o derivar en lugar de duplicar.
- Una Skill desactivada puede **advertirse como existente**, pero **no debe activarse automáticamente**; la detección recomienda, no bloquea por defecto.
- **Acciones permitidas en consulta**: la vista de exploración permite **consultar, buscar, ver detalles, comparar y adaptar**; **nunca activa directamente** ni cambia el contexto operativo activo (no es un contexto operativo; ver TW2). `[DECISIÓN CERRADA — resuelve A2]`

> Las decisiones abiertas A1 (conjunto de categorías funcionales) y A2 (profundidad de la biblioteca global) quedan **cerradas** por las decisiones de esta sección; ver sección 9.1 (TW17, TW18).

---

## 5. Skill Madre: invisible y protegida

**[DECISIÓN CERRADA — TW8]** La **Skill Madre** (constitución, G13/10.5) es una capacidad protegida que sirve para **co-crear nuevas Skills**:

- **Instalación obligatoria** con Demiurgos como parte del Core; no requiere activación del Autor.
- **Invisible en el árbol de skills**: no aparece entre las Skills del Taller; se referencia solo para delimitar alcance.
- **No editable, no eliminable y no desactivable** desde el Taller de Herramientas.
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
- **Editar una Skill publicada/en producción crea un borrador derivado** de la versión activa; la original permanece **intacta y operativa** hasta que la nueva versión se valide, apruebe y publique. Las Skills **protegidas/oficiales requieren derivación**, nunca edición directa. `[DECISIÓN CERRADA — TW13]`

### 6.6 Revisión, compilación, publicación, activación y una sola versión activa `[DECISIÓN CERRADA — TW15]`

- La **revisión final es guiada**: el asistente presenta un **resumen humano** de lo acordado y pone a disposición los **detalles completos útiles** (diferencias, decisiones clave) para que el Autor verifique.
- **Aprobación, validación/compilación, publicación y activación son pasos separados**; el Autor los recorre de forma explícita y en orden (coherente con el ciclo de vida del subsistema). La **aprobación de una versión no reemplaza ni desactiva automáticamente** la versión activa; la **activación/reemplazo requiere confirmación explícita** del Autor. `[DECISIÓN CERRADA — TW15]`
- **Antes de activar se muestra el impacto**: versión activa reemplazada, qué cambia, qué permanece igual, permisos, alcance, advertencias aceptadas, conversaciones afectadas y opción de restauración. `[DECISIÓN CERRADA — TW15]`
- Existe **una sola versión activa** por alcance; **activar una nueva desactiva explícitamente la anterior tras confirmación**. La versión anterior **no se elimina**: queda **archivada o desactivada** y puede **restaurarse** (rollback a publicada, nunca a borrador). `[DECISIÓN CERRADA — TW15]`
- Solo los **borradores son editables directamente**; una Skill publicada/en producción no se modifica en sitio (sección 6.5). El borrador tiene estados explícitos: **pendiente** y **lista para publicar**; publicar produce la versión inmutable.
- La UX de versiones mantiene **visible el estado actual** (insignia persistente de versión activa vs borrador) y presenta el flujo en **lenguaje simple**, con detalles técnicos **colapsados**.

### 6.7 Transparencia útil y límites frente a detalles técnicos `[DECISIÓN CERRADA — TW16]`

- El asistente **muestra su comportamiento, permisos, dependencias y consecuencias** de forma comprensible (qué hará la skill, qué puede y qué no, de qué depende, qué implicaciones tiene activarla).
- La **vista final de aprobación es una proyección comprensible** de la Skill candidata, no el contrato técnico completo sin filtrar: resumen en lenguaje humano (propósito, alcance, flujo, ramas, reglas, dependencias y permisos), con opción de **expandir detalles avanzados**. `[DECISIÓN CERRADA — TW16]`
- La vista distingue **visualmente y con etiquetas** lo **decidido por el Autor**, lo **propuesto por el Asistente** y lo **exigido por Demiurgos**; el **artefacto aprobado subyacente es exactamente el candidato revisado**. `[DECISIÓN CERRADA — TW16]`
- Se **ocultan los mecanismos técnicos internos** (rutas, provenance interna, identificadores de autoridad, proveedor subyacente) en toda la copia visible (constitución, 7.1 y 10.6).
- **Una Skill creada fuera del Taller de Herramientas no se ejecuta como Skill válida**: carece de validación/compilación; esto es por **integridad del sistema**, no como castigo. `[DECISIÓN CERRADA — TW16]`

---

## 7. Frontera con el Taller de Mundo y futuros Talleres

**[DECISIÓN CERRADA]** El Taller de Herramientas **gestiona y co-crea metodologías**; el Taller de Mundo **ejecuta** los flujos guiados que esas metodologías gobiernan:

| Capacidad | Vive en |
|---|---|
| Crear/editar/publicar/activar/importar/exportar Skills y co-crear con la Skill Madre | **Taller de Herramientas** (este contrato) |
| Ejecutar flujos guiados (p. ej. creación guiada de personajes) con la Skill activa por mundo | **Taller de Mundo** (`docs/architecture/world-workshop.md`) |
| Contenido factual del mundo (lore, personajes, canon) | **Taller de Mundo** |

- **Activación por mundo**: la versión activa se selecciona por mundo (subsistema, 16.a); **activar una versión nueva exige una nueva conversación** en el Asistente IA del Taller de Mundo; las sesiones anteriores no la utilizan (subsistema, 16.k). `[DECISIÓN CERRADA]`
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
| Biblioteca de metodologías (listado, publicar borrador validado, activar versión inmutable por mundo) | `frontend/src/components/organisms/MethodologyLibrary.tsx` |
| API de metodologías | `frontend/src/api/methodologies.ts` — `status`, `drafts`, `drafts/{id}/publish`, `activate`, `rollback` |
| Subsistema backend | `src/tools/demiurgos-suite/wiki/methodology_library.py`, `methodology_compiler.py`, `methodology_trust.py` |
| Sembrado de skills fundacionales (mecanismo completo, sección 8.1) | `data/methodology/seeds/narrative-character-creation/` (`manifest.yaml` + `source.md` + `checksums.json`), `src/tools/demiurgos-suite/wiki/methodology_seed.py` (carga + verificación + instalación), `methodology_trust.py` (inyección server-side de Oficiales + `fundacional`), hook de arranque `_seed_foundational_skills` en `api_server.py` |
| Navbar por talleres disponibles | `frontend/src/components/organisms/Navbar.tsx` — contrato `available`/`teaser`, teaser "Próximamente" |

**No implementado (superficie objetivo):** el selector de Taller y el árbol contextual (sección 2), los estados visibles bloqueada/transversal en la UI (sección 3), categorías funcionales y etiquetas en la UI (sección 4), la Skill Madre y la co-creación conversacional (secciones 5–6), el editor visual + chat, la comparación visual de adaptación y la vista de aprobación comprensible. Todo ello es `[OBJETIVO]`/`[DECISIÓN CERRADA]`, no `[ACTUAL]`.

> Regla de etiquetas: todo lo listado como `[ACTUAL]` está verificado; las superficies objetivo de las secciones 1–7 llevan su propia etiqueta y **no se presentan como implementadas**.

### 8.1 Skills fundacionales: mecanismo de sembrado `[DECISIÓN CERRADA — TW5, G14]` `[ACTUAL]`

Las skills fundacionales son metodologías oficiales que Demiurgos instala y mantiene desde el propio repositorio, sin pasar por la biblioteca gestionada por el Autor:

- **Catálogo sembrado en el repo**: cada skill fundacional vive en `data/methodology/seeds/<skill-id>/` con `manifest.yaml` (compilable por el compilador del subsistema), `source.md` y `checksums.json` (SHA-256 de los bytes empaquetados). El catálogo es extensible por directorio; el MVP siembra exactamente `narrative-character-creation@1.0`.
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
| **TW2** | **Taller = contexto de trabajo; categoría funcional = tipo de tarea**. Por defecto solo se muestran las Skills del Taller activo; **no existe "Todos los Talleres" como contexto operativo activo**, solo una vista de **exploración de biblioteca global** separada; los cruces requieren **handoff explícito** (secciones 2 y 4) |
| **TW3** | **Orden del árbol** del Taller activo: activas del Taller → transversales activas → inactivas del Taller → transversales inactivas; grupos plegables, orden alfabético (sección 2) |
| **TW4** | **Estados visibles** activa/transversal/inactiva/bloqueada; una transversal **incompatible se bloquea** con explicación y **opción de adaptarla**; la bloqueada no participa en runtime hasta adaptar/validar/activar; la original permanece intacta (sección 3) |
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
| **TW15** | **Revisión, compilación, publicación y activación separadas**; impacto antes de activar; **una sola versión activa** por alcance; activar desactiva la anterior tras confirmación; versiones anteriores archivables/restaurables; UX de versiones con estado visible y lenguaje simple (sección 6.6) |
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
