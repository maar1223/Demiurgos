# Skill Fundacional de Investigación — Contrato de Skill Transversal

> **Contrato de skill transversal.** Este documento define la **Skill Fundacional de Investigación** de Demiurgos: una capacidad metodológica transversal que **encuentra, evalúa y convierte información externa en conocimiento útil para el Autor**, reutilizable por los Talleres actuales y futuros. **Es diseño objetivo, no implementación actual**: describe qué debe cumplir la Skill, no presupone que exista hoy en el repositorio. Toda afirmación lleva la etiqueta de estado correspondiente; las capacidades se etiquetan `[OBJETIVO]`/`[DECISIÓN CERRADA]` y no se presentan como implementadas. No es un artefacto SDD ni sustituye a la constitución global; referencia los contratos de Taller sin duplicarlos.

| Campo | Valor |
|---|---|
| Estado | Contrato de skill transversal (diseño objetivo; no implementación actual) |
| Versión del documento | 1.1 |
| Fecha | 2026-08-16 |
| Autor | Demiurgos (orquestación) |
| Idioma | Español neutro (prosa técnica) |
| Alcance | Skill transversal de investigación externa: propósito, transversalidad, agnosticismo de proveedor/CLI/plataforma, ramas Descubrimiento y Verificación, flujo de investigación, procedencia y límites, ejes fiabilidad/utilidad/estado, estados de worldbuilding, comparación con Canon autorizado, integraciones propuestas, funcionamiento conversacional sin documento automático, guardado `.md` con frontmatter YAML con aprobación, referencias multimodales, privacidad/permisos/degradación, núcleo común + perfiles por Taller, fuera de alcance |
| Depende de | `docs/architecture/demiurgos-platform.md` (constitución global del producto) |
| Relación con SDD | Requisito previo. Ningún SDD de implementación de esta Skill debe comenzar sin este contrato aprobado y sus decisiones abiertas resueltas |
| Documentos relacionados | `docs/architecture/demiurgos-platform.md`, `docs/architecture/tool-workshop.md` (Taller de Herramientas — estados transversales de Skills y derivación), `docs/architecture/world-workshop.md` (Taller de Mundo — canon, propuestas y conflictos), `docs/architecture/skill-library-and-guided-character-creation.md` (subsistema de skills), `AGENTS.md` (orquestador) |

## Leyenda de etiquetas

| Etiqueta | Significado |
|---|---|
| `[ACTUAL]` | Comportamiento que existe hoy en el repositorio y está verificado |
| `[OBJETIVO]` | Comportamiento objetivo acordado, no necesariamente implementado aún |
| `[PROPUESTO]` | Diseño propuesto; requiere decisión antes de ser contrato |
| `[DECISIÓN ABIERTA]` | Punto sin resolver que requiere aprobación explícita del Autor |
| `[DECISIÓN CERRADA]` | Decisión ya aprobada; no debe revertirse sin nuevo acuerdo explícito |

---

## 0. Relación con la constitución y los contratos de Taller

- La **definición global del producto** (principios, conceptos canónicos, fronteras de dominio y decisiones G1–G15) vive en `docs/architecture/demiurgos-platform.md`. **Este documento no la duplica.**
- La Skill Fundacional de Investigación es una **skill transversal** en el sentido del Taller de Herramientas: declarada compatible con el Taller activo y disponible en la conversación sin cambiar de Taller (`tool-workshop.md`, secciones 2–3; TW2–TW3). `[OBJETIVO — referencia]`
- Los **estados de worldbuilding** que esta Skill produce (Canon del mundo, Propuesta, etc.) se apoyan en el **gobierno de canon** del Taller de Mundo (Borrador vs Canon, propuestas y conflictos; `world-workshop.md`, secciones 3–4; W3–W5, W11). **Este documento define el tránsito de la información externa hacia esos estados; no redefine el canon.**
- El asistente visible es el **Asistente de Demiurgos**; "Hermes" es el nombre interno del proveedor y nunca aparece en copia visible (constitución, G15/10.6). `[DECISIÓN CERRADA]`
- En caso de conflicto, prevalece la constitución; la contradicción se reporta al Autor.

---

## 1. Definición de la Skill

**[DECISIÓN CERRADA — RI1]** La **Skill Fundacional de Investigación** es la capacidad metodológica de la plataforma para **encontrar, evaluar y convertir información externa en conocimiento útil para el Autor**, operando dentro de cualquier conversación y sin depender de un proveedor, CLI o plataforma concreta. No es un Taller ni una superficie: es un **núcleo de investigación** reutilizable que cualquier Taller actual o futuro puede invocar, y cuyas **ramas internas** (Descubrimiento y Verificación) permiten trabajar desde la exploración abierta hasta el contraste riguroso.

| La Skill ES | La Skill NO es |
|---|---|
| Una capacidad transversal y conversacional para investigar información externa | Un taller, un módulo o una superficie de navegación propia |
| Agnóstica de proveedor, CLI y plataforma: usa las capacidades disponibles y degrada con claridad | Un cliente de un proveedor concreto ni una herramienta instalada |
| Una guía que propone hallazgos y el Autor decide | Una puerta de entrada automática a Canon |
| Concienzuda sobre procedencia, límites y fiabilidad | Un agregador silencioso de enlaces sin evaluación |
| Reutilizable por Talleres actuales y futuros | Una capacidad acoplada a un Taller concreto |
| Funciona en la conversación sin crear documentos automáticamente | Un generador automático de documentos o registros |

**Declaración de estado:** todo el comportamiento de la Skill descrito en este documento es **diseño objetivo** (`[OBJETIVO]`/`[DECISIÓN CERRADA]`), no implementación actual. Solo las capacidades de la plataforma que la sustentan (grafo, escritura gated, estados de canon) se citan como `[ACTUAL]` en su propio contrato.

---

## 2. Carácter transversal y reutilizable

**[DECISIÓN CERRADA — RI2]** La Skill es **transversal por diseño**:

- Funciona **dentro de cualquier conversación**, independientemente del Taller activo, y no exige cambiar de contexto para investigar.
- Es **reutilizable por Talleres actuales y futuros**: el **núcleo común** (propósito, flujo, procedencia, estados, comparación con canon, multimodales) es único; los **perfiles/ramas específicos** por Taller se contratan aparte (sección 15).
- En el árbol del Taller de Herramientas se declara como **transversal activa** según los estados de Skill existentes (`tool-workshop.md`, sección 3; TW3), sin duplicar ese contrato.
- Un Taller futuro puede **derivar un perfil** de investigación (ramas, fuentes y criterios específicos) **sin redefinir el núcleo** (sección 15).

---

## 3. Agnosticismo de proveedor, CLI y plataforma

**[DECISIÓN CERRADA — RI3]** La Skill **no depende de un proveedor, CLI o plataforma concreta**:

- Las **capacidades** se modelan de forma abstracta (búsqueda web, consulta de documentación, lectura de archivos, imágenes, vídeo, audio, etc.) y se **mapean a las capacidades disponibles** en cada instalación.
- La **disponibilidad se comprueba** antes de cada flujo (sección 5, paso 3); si una capacidad falta, se elige una **ruta primaria** y una **ruta alternativa (fallback)** o se degrada con claridad (sección 14).
- La integración con un proveedor, CLI o plataforma externa (p. ej. Agent Reach) es **inspiración conceptual externa, no dependencia ni adopción técnica** (sección 16).
- Coherente con el **agnosticismo de proveedor** de la plataforma (constitución, 7.3): añadir o quitar una fuente no altera el contrato de la Skill ni las invariantes de escritura.

---

## 4. Ramas internas: Descubrimiento y Verificación

**[DECISIÓN CERRADA — RI4]** La Skill opera con **dos ramas internas**, con **transición posible de una a otra**:

| Rama | Propósito | Actividad característica |
|---|---|---|
| **Descubrimiento** | Explorar y localizar información externa candidata | Generar rutas de búsqueda, seleccionar fuentes, recopilar hallazgos, ampliar el espacio de opciones |
| **Verificación** | Contrastar y evaluar los hallazgos | Confrontar fuentes entre sí, valorar fiabilidad, comparar con el Canon autorizado (sección 9), registrar procedencia y límites (sección 6) |

- La transición **Descubrimiento → Verificación** es la vía principal: un hallazgo se contrasta antes de presentarse como útil.
- La transición **Verificación → Descubrimiento** también existe: una verificación insuficiente o un vacío detectado **reabre la búsqueda** (nuevas fuentes, otros ángulos, otras modalidades).
- El paso de una rama a otra **se anuncia al Autor** y queda registrado en la procedencia; ninguna rama promueve contenido a Canon (sección 10).

---

## 5. Flujo de investigación

**[DECISIÓN CERRADA — RI5]** El flujo de la Skill es **secuencial y consciente**, y puede acortarse solo cuando el Autor lo pide:

| Paso | Acción | Notas |
|---|---|---|
| 1. **Entender la necesidad** | Aclarar qué necesita el Autor (dato factual, inspiración, marco, validación de canon) | Una pregunta a la vez (constitución, G15); si la necesidad es ambigua, se acota antes de buscar |
| 2. **Seleccionar capacidades y fuentes** | Elegir las capacidades y tipos de fuente adecuados (sección 13) | Según la necesidad, no una lista fija |
| 3. **Comprobar disponibilidad** | Verificar qué capacidades/fuentes están disponibles en la instalación | Si falta una, elegir ruta alternativa |
| 4. **Ruta primaria / fallback** | Ejecutar la ruta primaria; si falla, la alternativa | La degradación se reporta con claridad (sección 14) |
| 5. **Recopilar** | Reunir los hallazgos candidatos (rama Descubrimiento) | Se registra de dónde vino cada uno |
| 6. **Contrastar** | Confrontar fuentes, evaluar fiabilidad y comparar con canon (rama Verificación) | Sección 9 |
| 7. **Sintetizar** | Convertir los hallazgos en conocimiento útil para el Autor | Distinguiendo fiabilidad factual, utilidad creativa y estado en el mundo (sección 7) |
| 8. **Registrar procedencia y límites** | Documentar fuente, enlace, fecha, contexto, tipo, relevancia y confianza, más las limitaciones | Sección 6; nunca se omite el origen |

---

## 6. Procedencia y límites

**[DECISIÓN CERRADA — RI6]** Toda investigación registra **procedencia y límites**; un hallazgo sin procedencia no se presenta como verificado:

| Campo de procedencia | Contenido |
|---|---|
| **Fuente** | Origen trazable de la información (sitio, obra, autor, documento, persona) |
| **Enlace** | Referencia localizable cuando existe |
| **Fecha** | Fecha de consulta/obtención y, si se conoce, fecha de la fuente |
| **Contexto** | Circunstancias en que se obtuvo (pregunta, rama, necesidad) |
| **Tipo** | Modalidad de referencia (sección 13): web, libro, PDF, imagen, vídeo, audio, mapa, dato, repositorio, comunidad |
| **Relevancia** | Grado de pertinencia para la necesidad del Autor |
| **Confianza** | Nivel de confianza en la fuente (fiabilidad factual; sección 7) |

- Los **límites** se registran siempre: fuente no accesible, parcial, traducida, desactualizada o no contrastable; se informa explícitamente qué **no** se pudo verificar.
- La procedencia se presenta de forma **legible para el Autor**, sin exponer mecanismos técnicos internos (constitución, 7.1/10.6).

---

## 7. Fiabilidad factual, utilidad creativa y estado dentro del mundo

**[DECISIÓN CERRADA — RI7]** La Skill distingue explícitamente **tres ejes** para cada hallazgo, sin mezclarlos:

| Eje | Pregunta que responde | Resultado |
|---|---|---|
| **Fiabilidad factual** | ¿La información es verificable y confiable? | Nivel de confianza (alta/media/baja; sección 6) |
| **Utilidad creativa** | ¿Resulta útil como material para el mundo, aunque no sea un hecho? | Valor creativo (p. ej. inspiración, matiz, alternativa) |
| **Estado dentro del mundo** | ¿Qué rol tiene respecto al mundo del Autor? | Uno de los estados de worldbuilding (sección 8) |

- Un hallazgo puede ser **factualmente débil pero creativamente rico**, o **factualmente sólido e irrelevante para el mundo**; la Skill lo comunica así, sin forzar una conclusión única.

---

## 8. Estados de worldbuilding

**[DECISIÓN CERRADA — RI8]** Los hallazgos externos se clasifican en **cinco estados de worldbuilding**:

| Estado | Significado | Relación con el canon |
|---|---|---|
| **Canon del mundo** | Hecho aceptado por el Autor como parte del mundo | No lo asigna la Skill: es transición exclusiva del Autor (constitución y `world-workshop.md`, W3) |
| **Referencia externa** | Información del mundo real/externo que no pretende ser parte del mundo | Se conserva como contexto; no entra al canon |
| **Inspiración** | Material creativo que despierta ideas; no aspira a ser hecho | Se usa como materia creativa; no se contrasta como dato |
| **Hipótesis** | Afirmación provisional, no verificada, en estudio | Requiere verificación antes de proponerse como candidata |
| **Propuesta** | Candidato a integrarse al mundo, pendiente de aprobación del Autor | Mapea a las propuestas del Taller de Mundo (W4/W11): nunca promoción automática |

- El **estado lo propone la Skill y lo confirma el Autor**; cambiar de estado (p. ej. Hipótesis → Propuesta → Canon) exige la aprobación correspondiente.

---

## 9. Comparación con el Canon autorizado

**[DECISIÓN CERRADA — RI9]** Antes de proponer cualquier integración, la Skill **compara el hallazgo con el Canon autorizado** del mundo (leído vía grafo; constitución, 7.1 y `world-workshop.md`, 4.3):

| Resultado | Significado | Acción |
|---|---|---|
| **Compatible** | No contradice el canon; encaja o es independiente | Puede proponerse sin conflicto |
| **Enriquecedor** | Complementa o amplía el canon sin contradecirlo | Se propone como ampliación |
| **Potencialmente conflictivo** | Contradice o tensa el canon existente | Se señala según el tratamiento de conflictos del Taller de Mundo (W5); no se resuelve en silencio |
| **No relacionado** | No toca el canon | Se descarta o se guarda como referencia externa |

- La comparación **nunca convierte el hallazgo en canon**; solo clasifica la relación y fundamenta la propuesta (sección 10).

---

## 10. Integraciones propuestas

**[DECISIÓN CERRADA — RI10]** La Skill **propone integraciones, no las aplica**:

- Presenta al Autor una propuesta de integración (qué se añadiría, dónde, en qué estado) con su procedencia y su clasificación frente al canon (sección 9).
- La **decisión final es siempre del Autor**; ninguna integración se persiste, se promueve a canon ni se escribe en archivos del mundo automáticamente.
- Las propuestas que el Autor acepta siguen el modelo de propuestas del Taller de Mundo (`world-workshop.md`, W4/W11) y la escritura gated de la plataforma (constitución, 7.1).

---

## 11. Funcionamiento conversacional sin documento automático

**[DECISIÓN CERRADA — RI11]** La Skill opera **dentro de la conversación** y **no crea ningún documento automáticamente**:

- La investigación, sus hallazgos y su síntesis viven **en el hilo conversacional**; nada se persiste sin que el Autor lo pida.
- La Skill **ofrece** guardar el resultado cuando la investigación es útil (sección 12), pero la escritura es **siempre con aprobación explícita**.
- Coherente con el principio de la plataforma: **nada se persiste sin aprobación** (constitución, 1.4 y 9.1).

---

## 12. Guardado de la investigación como `.md` con frontmatter YAML

**[DECISIÓN CERRADA — RI12]** Cuando una investigación es útil y el Autor lo desea, la Skill **ofrece guardarla** como un archivo Markdown con **frontmatter YAML estructurado**:

- El guardado ocurre **solo con aprobación explícita** del Autor; nunca se autoguarda una investigación.
- El frontmatter declara metadatos de la investigación (título, fecha, rama, procedencia resumida, estados de worldbuilding, resultados frente al canon).
- El **cuerpo** es el resumen legible de la investigación: necesidad, hallazgos, contraste, síntesis, límites y propuestas.
- La **ubicación depende del alcance**: una investigación vinculada a un mundo se guarda en `mundos/{mundo}/referencias/investigaciones/`; una investigación transversal o personal se guarda en la biblioteca global `referencias/investigaciones/`. Si la propuesta resultante se integra al mundo, se remite al modelo de propuestas del Taller de Mundo (`world-workshop.md`, W11), que gobierna la persistencia de propuestas y conflictos.

---

## 13. Referencias multimodales en el chat

**[DECISIÓN CERRADA — RI13]** La Skill reconoce y maneja **referencias multimodales** dentro de la conversación:

| Tipo de referencia | Manejo |
|---|---|
| **Web** | Páginas y recursos en línea; se evalúa procedencia y fiabilidad |
| **Libros / artículos** | Obras y publicaciones; se registra título, autor y edición |
| **PDFs** | Documentos adjuntos o enlazados; extracción de contenido relevante |
| **Imágenes** | Visuales (mapas, ilustraciones, fichas); lectura mediante capacidades de visión disponibles |
| **Vídeos** | Contenido audiovisual; se resume según capacidades disponibles |
| **Audio / podcasts** | Contenido sonoro; transcripción/resumen según capacidades disponibles |
| **Mapas** | Cartografía; contexto geográfico del mundo o referencia externa |
| **Tablas / datos** | Conjuntos estructurados; contraste y síntesis |
| **Repositorios / documentación** | Código, estándares y referencias técnicas; consulta según disponibilidad |
| **Publicaciones comunitarias** | Contenido de la comunidad; evaluado con menor confianza y su correspondiente límite |

- Si una modalidad no está disponible, se **degrada con claridad** (sección 14): se informa qué no se pudo procesar y se propone alternativa.

---

## 14. Privacidad, permisos, fuentes no disponibles y degradación

**[DECISIÓN CERRADA — RI14]** La Skill respeta privacidad y permisos y **degrada con claridad**:

- **Privacidad**: no expone ni persiste información de fuentes que requieran credenciales o acceso autorizado sin consentimiento; los enlaces con acceso restringido se informan como no verificables.
- **Permisos**: la Skill no ejecuta acciones de escritura ni descargas fuera de la aprobación del Autor; no omite las compuertas de la plataforma.
- **Fuentes no disponibles**: si una fuente no es accesible (caduca, requiere pago, no existe), se reporta y se registra como límite (sección 6).
- **Degradación clara**: ante una capacidad o fuente ausente, la Skill declara qué pudo y qué no pudo hacer, qué alternativa tomó y qué queda pendiente. Coherente con el agnosticismo de proveedor de la plataforma (constitución, 7.3 y 9.2).

---

## 15. Núcleo común y perfiles/ramas por Taller

**[DECISIÓN CERRADA — RI15]** La Skill separa **núcleo común** de **perfiles específicos**:

- **Núcleo común** (este contrato): propósito, agnosticismo, ramas, flujo, procedencia, ejes, estados de worldbuilding, comparación con canon, integraciones, modo conversacional, multimodales, privacidad/degradación. Único, transversal y compartido por todos los Talleres.
- **Perfil/rama por Taller**: cada Taller (actual o futuro) puede definir **fuentes, capacidades y criterios específicos** sin modificar el núcleo. P. ej. el perfil del Taller de Mundo enfatiza la comparación con el canon autorizado y la clasificación en estados de worldbuilding; un Taller futuro define el suyo.
- Los perfiles se declaran como **ramas derivadas** del núcleo (análogo a la derivación de Skills del Taller de Herramientas, `tool-workshop.md`, 6.5), con procedencia visible del núcleo del que derivan.

---

## 16. Fuera de alcance

**[DECISIÓN CERRADA — RI16]** Quedan **fuera de alcance** de este contrato:

- **Copiar Agent Reach** o asumir su diseño como propio: Agent Reach se referencia únicamente como **inspiración conceptual externa** (la idea de investigación con múltiples fuentes, ramas y verificación), nunca como dependencia, adopción técnica o modelo contractual.
- **Su CLI, instalación automática, monetización, proveedores concretos y la asunción de todos sus canales**: no se integran, no se clonan y no se contratan aquí.
- **Bugs menores**: los defectos de detalle (errores de redacción, casos de borde menores) quedan fuera de este contrato y se tratan como incidencias, no como cambios de contrato.
- **Implementación**: este documento es diseño objetivo; la construcción es materia de un futuro SDD (sección 19).

---

## 17. Relación con los contratos existentes (sin duplicar)

| Documento | Relación con esta Skill |
|---|---|
| `docs/architecture/demiurgos-platform.md` | Constitución global: principios, canon/evidencia, agnosticismo de proveedor, escritura gated y fronteras. Esta Skill opera **dentro** de esas reglas y no las redefine |
| `docs/architecture/tool-workshop.md` | Gobierna cómo se declara la Skill como **transversal** en el árbol de Skills y cómo se **derivan** perfiles/ramas; no duplica el núcleo de investigación |
| `docs/architecture/world-workshop.md` | Gobierna **canon, propuestas y conflictos**; esta Skill es la **vía de entrada de información externa** que alimenta esos estados sin auto-canon; el guardado de propuestas/conflictos vive allí (W11) |
| `docs/architecture/skill-library-and-guided-character-creation.md` | Subsistema técnico de skills; el contrato de investigación es contenido metodológico editable (constitución, principio de metodología como contenido), no lógica de servidor |
| `AGENTS.md` | Orquestador narrativo; puede invocar investigación como apoyo de contexto sin invadir las fronteras de dominio |

---

## 18. Decisiones cerradas y abiertas

### 18.1 Cerradas (no revertir sin nuevo acuerdo)

| ID | Decisión |
|---|---|
| **RI1** | Definición: encontrar, evaluar y convertir información externa en conocimiento útil para el Autor; conversacional y no documental por defecto (sección 1) |
| **RI2** | **Carácter transversal y reutilizable** por Talleres actuales y futuros; núcleo común único (secciones 2 y 15) |
| **RI3** | **Agnosticismo de proveedor, CLI y plataforma**: capacidades abstractas, disponibilidad comprobada, rutas primaria/fallback (sección 3) |
| **RI4** | **Ramas Descubrimiento y Verificación** con transición posible en ambos sentidos, anunciada y registrada (sección 4) |
| **RI5** | **Flujo de investigación en 8 pasos** (entender necesidad → capacidades/fuentes → disponibilidad → ruta primaria/fallback → recopilar → contrastar → sintetizar → procedencia/límites) (sección 5) |
| **RI6** | **Procedencia obligatoria**: fuente, enlace, fecha, contexto, tipo, relevancia y confianza, más límites (sección 6) |
| **RI7** | Distinción de **tres ejes**: fiabilidad factual, utilidad creativa y estado dentro del mundo (sección 7) |
| **RI8** | **Cinco estados de worldbuilding**: Canon del mundo, Referencia externa, Inspiración, Hipótesis y Propuesta; el estado lo propone la Skill y lo confirma el Autor (sección 8) |
| **RI9** | **Comparación con el Canon autorizado**: compatible, enriquecedor, potencialmente conflictivo o no relacionado; sin auto-canon (sección 9) |
| **RI10** | **Integraciones propuestas, nunca aplicadas**; la decisión es del Autor y sigue el modelo de propuestas del Taller de Mundo (sección 10) |
| **RI11** | Funcionamiento **en la conversación sin crear documentos automáticamente**; nada se persiste sin aprobación (sección 11) |
| **RI12** | **Guardado como `.md` con frontmatter YAML solo con aprobación explícita**; investigaciones de mundo van a `mundos/{mundo}/referencias/investigaciones/` y las transversales/personales a `referencias/investigaciones/` (sección 12) |
| **RI13** | **Referencias multimodales** en el chat (web, libros/artículos, PDFs, imágenes, vídeos, audio/podcasts, mapas, tablas/datos, repositorios/documentación, publicaciones comunitarias) (sección 13) |
| **RI14** | **Privacidad, permisos, fuentes no disponibles y degradación clara**; sin escrituras ni descargas fuera de aprobación (sección 14) |
| **RI15** | **Separación núcleo común / perfiles-ramas por Taller**; los perfiles derivan del núcleo sin redefinirlo (sección 15) |
| **RI16** | **Fuera de alcance**: Agent Reach solo como inspiración conceptual externa (sin CLI, instalación automática, monetización, proveedores ni canales asumidos) y bugs menores fuera de contrato (sección 16) |

### 18.2 Abiertas (acotadas; solo las necesarias para un futuro SDD)

> No quedan decisiones abiertas de producto en este contrato. Cualquier decisión técnica de persistencia, indexado o sincronización que surja durante un futuro SDD deberá documentarse allí sin alterar esta regla de ubicación por alcance.

---

## 19. Definition of ready para SDD futuro

Un SDD de implementación de esta Skill **solo** puede comenzar cuando se cumplan todos:

- [ ] Se leyeron esta constitución global, este contrato y los contratos de Taller referenciados (secciones 0 y 17).
- [ ] Se verificó el runtime real (CodeGraph/tests) antes de asumir cualquier `[ACTUAL]` citado de la plataforma.
- [ ] Las decisiones abiertas que tocan el cambio están resueltas y anotadas; este contrato no tiene decisiones abiertas de producto.
- [ ] El cambio respeta las invariantes de la constitución (secciones 5, 7), la escritura gated y las fronteras de dominio.
- [ ] Todo comportamiento nuevo se etiqueta `[ACTUAL]`/`[OBJETIVO]`/`[PROPUESTO]` y no se presenta como implementado.
- [ ] El SDD declara explícitamente qué NO toca (Agent Reach, CLI/proveedores, canon, escrituras fuera de gating).
- [ ] Las pruebas cubren las invariantes afectadas (cero escrituras sin aprobación, procedencia obligatoria, degradación, no auto-canon) y las ramas de fallo relevantes.
