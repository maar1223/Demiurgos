# Taller de Herramientas y Creación Guiada de Personajes — Contrato de Iniciativa

> **Contrato de iniciativa.** Este documento es el contrato de producto y arquitectura de la iniciativa **biblioteca de skills gestionada por el Autor + runtime de creación guiada de personajes nuevos**, como subsistema de la plataforma Demiurgos. **No es un artefacto SDD** ni sustituye a la constitución global. Toda afirmación lleva la etiqueta de estado correspondiente; lo no implementado no se presenta como existente.

| Campo | Valor |
|---|---|
| Estado | Contrato de iniciativa (revisado — decisiones sincronizadas) |
| Versión del documento | 2.2 |
| Fecha | 2026-08-16 |
| Autor | Demiurgos (orquestación) |
| Idioma | Español neutro (prosa técnica) |
| Alcance | INICIATIVA (subsistema): **Taller de Herramientas** (metodologías/skills, plantillas y catálogos), compilador/validador, ciclo de vida, import/export/cuarentena/Skool y flujo guiado de personaje nuevo. El resto de la plataforma está cubierto por la constitución global |
| Depende de | `docs/architecture/demiurgos-platform.md` (constitución global del producto) |
| Relación con SDD | Requisito previo. Ningún SDD de este dominio debe comenzar sin este contrato aprobado y sus decisiones abiertas resueltas |
| Documentos relacionados | `docs/architecture/demiurgos-platform.md`, `skills/narrative-character-creation/SKILL.md`, `skills/narrative-character-creation/references/conversation-examples.md`, `skills/crear_personaje.md` (legacy), `AGENTS.md` (límites de dominio), runtime en `src/tools/demiurgos-suite/wiki/` |

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

- La **definición global del producto** (qué es Demiurgos, principios, mapa del sistema, conceptos canónicos, superficies, límites de dominio y decisiones globales G1–G12) vive en `docs/architecture/demiurgos-platform.md`. **Este documento no la duplica.**
- Este documento asume y referencia esa constitución. Los principios de producto y las reglas de arquitectura de la sección 7 de la constitución aplican aquí íntegramente.
- En caso de conflicto, prevalece la constitución; la contradicción se reporta al Autor.
- Esta iniciativa cubre **solo**: la biblioteca de skills gestionada por el Autor, el compilador/validador, el ciclo de vida, la importación/exportación/cuarentena/compartición por Skool, las superficies de frontend de la biblioteca, y el flujo guiado de creación de personajes nuevos.

---

## 1. Decisión ejecutiva

**[DECISIÓN CERRADA]** Demiurgos es una **plataforma web integral, agnóstica de mundo, de gestión de lore y worldbuilding** (definición completa en la constitución global, sección 1). Dentro de esa plataforma, esta iniciativa establece que:

1. Las **metodologías de creación** (qué preguntar, cómo explorar, qué anclar, cómo converger) son **contenido editable del Autor** — paquetes de skill versionados — y no lógica incrustada en el código del servidor. `[DECISIÓN CERRADA]`
2. El **runtime** (protocolo guiado, máquina de estados, candidate state, gates de seguridad, persistencia, indexado) es propiedad del backend de Demiurgos y es **inmutable para el Autor** en su núcleo de seguridad (system kernel). `[DECISIÓN CERRADA]`
3. Hermes es el **proveedor conversacional**: voz, interpretación semántica y propuestas creativas. Hermes **nunca** escribe, no otorga permisos y no puede saltarse las compuertas del servidor. `[DECISIÓN CERRADA]`
4. La creación guiada usa el principio **40/60** (sección 11): 40% rieles del sistema, 60% construcción de mundo adaptativa. `[DECISIÓN CERRADA]`

**Referencias a decisiones globales (sin duplicarlas):** la **co-creación** (Hermes conversa/redacta, el backend valida/compila/protege, el Autor aprueba) y la **intención semántica** (Hermes la determina; el backend valida el envelope, resuelve referencias y ensambla contexto, pero no redacta síntesis narrativas ni decide relaciones) son decisiones globales de la constitución (secciones 2.3 y 5). La **Skill Madre** es una capacidad protegida global (constitución, G13 y 10.5) que se usa para co-crear nuevas skills; este documento regula solo la **biblioteca gestionada por el Autor** y la referencia.

**[ACTUAL]** Hoy el repositorio tiene un protocolo guiado funcional (`guided-character-v1`) que usa prompts de proveedor **hardcodeados** en `guided_character_provider.py` y `semantic_intent.py`, y skills como archivos Markdown estáticos consumidos por Hermes como herramientas. **El runtime actual NO carga dinámicamente las skills**; el puente skill→runtime (compilador/adaptador) es exactamente lo que falta y es el objeto de la sección 8.

**[OBJETIVO]** El estado objetivo es: el Autor publica/activa/edita skills; el compilador valida y compila cada skill a un **contrato de runtime**; el runtime ejecuta la skill activa dentro de las invariantes del system kernel. Un SDD futuro debe construir la biblioteca y el compilador **sin tocar** las invariantes de seguridad ya implementadas.

---

## 2. Terminología

| Término | Definición |
|---|---|
| **Skill** | Metodología de creación coherente (capacidad + rieles + guía) que, activada, gobierna un flujo guiado. Unidad de producto que el Autor gestiona. |
| **Paquete (package)** | Unidad versionable de una skill: manifest + Markdown fuente + metadatos + (opcional) referencias/ejemplos. Es lo que se importa, exporta, comparte y versiona. |
| **Manifest** | Metadatos estructurados del paquete: identidad, versión, autor/fuente, idioma, tipo de entidad, triggers, capacidades, fases/anclas, mínimos, estrategia de preguntas, política de completitud, compatibilidad y dependencias. Distingue campos editables de campos protegidos (sección 6.3). |
| **Markdown fuente** | El cuerpo de la skill editable por el Autor: instrucciones, rieles, ejemplos, tono. Es entrada del compilador, no del runtime directo. |
| **Contrato compilado/runtime** | Representación validada y chequeada por máquina que deriva del Markdown fuente + manifest, y que el runtime sí consume (envelope de protocolo, fases, gates, mínimos). `[PROPUESTO]` en su forma general; `[ACTUAL]` el protocolo `guided-character-v1` es un contrato de runtime limitado y hardcodeado. |
| **Borrador (draft)** | Versión no publicada y mutable de una skill. Solo los borradores se editan. |
| **Versión publicada inmutable** | Snapshot versionado que ya no puede editarse, identificado por `V1`, `V2`… y metadatos de edición/publicación (`published_at`, `published_by`, historial de cambios). Las sesiones y activaciones referencian versiones publicadas, nunca borradores. |
| **Versión activa** | La versión publicada específica que gobierna actualmente la creación guiada en un mundo concreto (decisión 16.a). |
| **Snapshot de sesión** | Captura inmutable de la versión de skill + rieles del kernel vinculada a una sesión guiada al iniciarla, para que una republicación no altere una sesión en vuelo. |
| **Núcleo del sistema (system kernel)** | Rieles de propiedad del servidor no editables por el usuario: autenticación/autorización, revisión/sesiones, candidate state, provenance/certeza, gates de aceptación, digest/token de confirmación, persistencia e indexado. |
| **Metodología de usuario (user methodology)** | Porción editable que vive en el paquete de skill: guía creativa, estrategia de preguntas, exploración, tono. Se ejecuta solo dentro de los rieles del kernel. |
| **Skill importada** | Paquete traído de una fuente externa (p. ej. el canal Skool) y aún no revisado; toda importación entra en cuarentena obligatoria. |
| **Skill en cuarentena** | Paquete importado mantenido en estado aislado (no activable) hasta que el Autor lo valide. Solo tras la validación puede publicarse/activarse. |

---

## 3. La biblioteca de skills como subsistema gestionado

### 3.1 Objetivo del subsistema

**[DECISIÓN CERRADA]** La interfaz presenta este subsistema como **Taller de Herramientas**, la primera sección del Navbar y la base instrumental de los talleres creativos. El **Taller de Herramientas forma parte del Core gratuito del MVP** junto al Taller de Mundo (constitución, G10); en el Navbar solo se muestran los talleres disponibles y los módulos de pago futuros aparecen como teaser "Próximamente". Dentro contiene las **Metodologías**: métodos que permiten al Autor **crear, editar, publicar (versiones inmutables), activar, importar/exportar, compartir y eliminar** formas de trabajo para dar forma a mundos existentes; “Skill” permanece como nombre técnico del paquete.

**`[DECISIÓN CERRADA]`** La **Skill Madre** (capacidad protegida instalada con Demiurgos, constitución G13) **no pertenece a la biblioteca gestionada por el Autor**: no es editable ni eliminable desde este Taller y se actualiza solo mediante **releases oficiales**; se referencia aquí únicamente para delimitar el alcance (ver 9, co-creación).

### 3.2 Kernel del sistema vs metodología de usuario — frontera exacta

| Capa | Propiedad | Qué contiene | Quién lo edita | Efecto en runtime |
|---|---|---|---|---|
| **System kernel** | Servidor (backend) | Autorización, sesiones/revisión, candidate state, provenance/certeza, gates de aceptación, digest/token, persistencia gated, indexado, gate semántico, fail-closed | Nadie (solo el sistema) | Determina las **invariantes de seguridad**: nada de esto es negociable ni alcanzable por una skill |
| **Campos protegidos del manifest** | Contrato | `schema_version`, `id`, `version`, `compatibility`, política de `required_minimums` (por decisión abierta 16.f) | Nadie (solo el sistema) | Determina compatibilidad y seguridad del contrato |
| **Metodología de usuario** | Autor | Guía creativa, estrategia de preguntas, exploración, tono, anclas, política de completitud | El Autor | Determina la guía creativa **dentro** de los rieles del kernel |

**[DECISIÓN CERRADA]** La frontera exacta es: **el usuario edita la metodología; el kernel decide la seguridad.** Una skill jamás puede alterar autorización, persistencia, gates, digests, tokens, indexado, ni la resolución de grafo. Cualquier declaración de la skill que pretenda conceder permisos es ignorada (las capacidades son descriptivas, nunca autorizantes).

### 3.3 Árbol de skills y scoping por sesión

- **`[DECISIÓN CERRADA]`** Las skills se organizan por **Taller/capacidad** (árbol), no como una lista plana global.
- **`[OBJETIVO]`** Hermes puede estar presente en cada Taller como asistente de esa capacidad (posibilidad/objetivo; no hay cierre explícito).
- **`[DECISIÓN CERRADA]`** Cada sesión recibe **solo el alcance** de su Taller: la Skill activa, su versión, el mundo y el contexto autorizado. **Nunca recibe el árbol completo** a la vez.
- **`[DECISIÓN CERRADA]`** Los cruces entre Talleres requieren un **handoff explícito**; no se asume contexto de otro Taller.

---

## 4. Objetivos y no-objetivos de la iniciativa

### 4.1 Objetivos

- **O1. Creación guiada de personajes nuevos** de extremo a extremo (intención → exploración → propuesta diskless → aprobación → persistencia → indexado) sin escribir nada sin aprobación explícita. `[DECISIÓN CERRADA]`
- **O2. El Autor gestiona sus metodologías de creación** como skills versionadas, editables y publicables por mundo; las capacidades de taller que las ejecutan pueden pertenecer a módulos de pago único. `[OBJETIVO]`
- **O3. Separación kernel/metodología**: lo que el usuario edita nunca puede violar las invariantes de seguridad del sistema. `[DECISIÓN CERRADA]`
- **O4. Imagen mental de un chat normal**: la creación guiada es un handoff interno; el Autor habla en un solo chat. `[DECISIÓN CERRADA — ver #1739]`
- **O5. Importación/exportación y compartición** de skills por el canal Skool, con cuarentena y revisión previa a la activación. `[OBJETIVO]`
- **O6. Principio 40/60** como método de diseño de toda skill de personaje. `[DECISIÓN CERRADA — ver #1565]`

### 4.2 No-objetivos

- **N1. NO es una máquina de formularios ni un cuestionario fijo** (el legacy 7/12/18 de `crear_personaje.md` queda fuera de uso para este flujo). `[DECISIÓN CERRADA]`
- **N2. NO sustituye a `narrative-character-spec`**: rosters/arcos de personajes de un arco son otro flujo. `[DECISIÓN CERRADA]`
- **N3. NO permite a Hermes ni a las skills editar fichas existentes, el lore ni otorgar permisos.** `[DECISIÓN CERRADA]`
- **N4. NO incluye edición de fichas existentes** en la primera rebanada vertical. `[DECISIÓN CERRADA — primera rebanada]`
- **N5. NO genera imágenes ni regenera catálogos** en esta área. `[DECISIÓN CERRADA]`
- **N6. NO es un sistema de autorización de la plataforma**: solo define el modelo de skills y el flujo guiado de personaje.
- **N7. NO redefine la plataforma global**: este documento no duplica la constitución (sección 0).

---

## 5. Actores y límites estrictos de responsabilidad

### 5.1 Tabla de actores

| Actor | Puede | NO puede | Notas |
|---|---|---|---|
| **Autor/Usuario** | Escribir intención en lenguaje natural; responder preguntas; aceptar/rechazar cada propuesta; aprobar el diff final; gestionar skills (crear/editar/publicar/activar/importar/exportar/eliminar) | Aprobar por otro medio que no sea la UI; saltarse confirmaciones | El Autor es la única fuente de hechos canónicos (certeza/provenance) |
| **Frontend UI** | Mostrar chat, fases, preguntas, propuestas, diff, acciones de revisión; enviar turnos; recuperar sesión; gestión de biblioteca/editor/versiones/papelera | Renderizar provenance interna ni rutas del grafo; inventar acciones no mapeadas a API | `[ACTUAL]` el panel muestra fases `confirmation/conversation/review/complete`; `localStorage` es solo pista de recuperación, el backend es autoritativo |
| **Backend Demiurgos (frontera de policy/sesión)** | Resolución de grafo (search→read→links), sesión/revisión, candidate state, propuesta/diff, autorización, persistencia, indexado, gate semántico, envelope de decisión, fail-closed | Delegar autoridad de escritura a Hermes o a la skill | Es el **único** dueño de estas capacidades (sección 5.2) |
| **Hermes (proveedor conversacional)** | Voz conversacional; determinación de la intención semántica (`allow/clarify/require_confirmation/proposal_ready/blocked`); proponer deltas, preguntas y redactar la propuesta de co-creación en envelope JSON estricto | Escribir archivos; tocar el grafo como autoridad; otorgar permisos; reclamar aceptación del Autor; exponer provenance interna/rutas; inventar hechos canónicos; consultar grafo, serializar ficha, calcular digest, emitir tokens, persistir Engram o indexar | Tratado como proveedor no confiable y acotado; no escribe ni decide canon |
| **Importador/compilador/validador de skills** | Validar manifest; compilar Markdown fuente → contrato runtime; chequear compatibilidad/dependencias; aislar importaciones en cuarentena | Ejecutar efectos colaterales; activar sin validación; aceptar paquetes malformados | `[ACTUAL]` — `methodology_compiler.py`/`methodology_library.py`/`methodology_trust.py` implementados (sección 8) |
| **Comunidad/API Skool** | Compartir paquetes `.zip` entre usuarios y, en el futuro, autorizar el entitlement para descargar releases de software | Distribuir software directamente; ejercer autoridad de activación; inyectar contenido no validado | `[OBJETIVO]` — entitlement de actualizaciones según 16.g |

### 5.2 Backend: capacidades que NINGÚN otro actor posee

El backend es dueño exclusivo de:

1. **Resolución de grafo**: búsqueda→lectura→enlaces, detección de referencias no resueltas/ambiguas y evidencia (`guided_character_domain.resolve_named_reference`, `collect_graph_evidence`). `[ACTUAL]`
2. **Sesión y revisión**: `GuidedSessionStore` con `authorization_binding` y chequeo de revisión **antes de cada mutación**; fases `confirmation → conversation → review → complete`; gate de completitud mínima server-side. `[ACTUAL]`
3. **Candidate state**: particiones `accepted_canon / proposals / unresolved_references / conflicts`; `apply_delta` jamás escribe en `accepted_canon` (la aceptación es transición exclusiva del Autor). `[ACTUAL]`
4. **Propuesta/diff**: serialización diskless de `personajes/{slug}.md` con validación de slug, colisión y target; digest SHA-256 server-computed; diff ligado a token de confirmación de un solo uso. `[ACTUAL]`
5. **Autorización**: `_resolve_principal`/`_guided_principal` (cookie HttpOnly, mismo origen); el `principal.id` se vincula a toda sesión y flujo de edición confirmada. `[ACTUAL]`
6. **Persistencia**: escritura SOLO por las rutas de confirmación existentes (`/{section}/save|create`); `SecureCreateRequest` verifica digest antes de construir el payload. `[ACTUAL]`
7. **Indexado**: `ReindexCoordinator` reconcilia el grafo de forma idempotente tras la creación (`indexed/pending/dirty/failed`). `[ACTUAL]`
8. **Gate semántico**: `SemanticIntentProvider` valida el envelope de decisión con hasta 3 intentos y **sin fallback léxico**; cualquier Hermes no disponible/no válido cierra en `blocked` con copia segura localizada. `[ACTUAL]`

### 5.3 La frontera Hermes (regla sagrada)

**[DECISIÓN CERRADA]** Hermes:

- **NO tiene autoridad de escritura**: nada persiste hasta la aprobación explícita del Autor sobre la propuesta diskless.
- **NO otorga permisos**: `SemanticDecision.reference` es emitida solo por el servidor; cualquier clave de autoridad (`target`, `digest`, `revision`, `authority`, `reference`, `acceptance`, `accepted_canon`, `authorization`) dentro de un continuation invalida el envelope completo (fail-closed). `[ACTUAL — semantic_intent.py]`
- **NO puede saltarse las compuertas del servidor**: la persistencia, el diff y la autorización se resuelven por completo en rutas backend que Hermes no selecciona ni controla.
- **NO consulta el grafo por sí mismo**: recibe contexto ya resuelto y acotado por el servidor (`SemanticContext` limitado a `mundo/ficha/reference/graph`). `[ACTUAL]`
- **NO serializa ficha, NO calcula digest, NO emite tokens, NO persiste Engram, NO indexa**: todas esas operaciones pertenecen al servidor (sección 13). `[ACTUAL]`
- **Sí es el intérprete semántico y la voz**: el prompt del gate semántico es el único lugar donde la intención natural se convierte en estado (`[ACTUAL]`); la clasificación léxica (`route_new_character_intent`) es **secundaria y solo se consulta tras un envelope semántico válido** `[ACTUAL]`.

---

## 6. Paquete de skill, manifest y contrato de runtime

### 6.1 Estructura del paquete `[OBJETIVO]`

```
skill-package/
├── manifest.json          # identidad, versión, capacidades, fases, mínimos, política
├── SKILL.md               # Markdown fuente editable (rieles + guía + tono)
├── references/            # (opcional) ejemplos de conversación, plantillas
└── assets/                # (opcional) recursos del paquete  [PROPUESTO]
    └── signatures/        # (opcional) firma/cadena de autoridad para imports  [PROPUESTO]
```

### 6.2 Schema conceptual del manifest `[OBJETIVO]`

| Campo | Tipo | Protegido (kernel) o editable (metodología) | Obligatorio | Descripción |
|---|---|---|---|---|
| `schema_version` | int | protegido | sí | Versión del schema del manifest; controla compatibilidad del compilador |
| `id` | string (slug) | protegido | sí | Identidad estable del skill; única por biblioteca |
| `name` | string | editable | sí | Nombre humano |
| `description` | string | editable | sí | Para descubrimiento y contracto de activación |
| `version` | semver | protegido | sí | Versión del paquete; solo crece al publicar |
| `author` / `source` | string | editable | sí | Autor o fuente (para importaciones, cadena de origen) |
| `language` | `es`/`en`/… | editable | sí | Idioma de la prosa y de las preguntas |
| `entity_type` | `personaje` (inicialmente) | editable | sí | Qué entidad crea este skill |
| `triggers` | string[] | editable | sí | Frases/patrones de activación (verbos, términos, referencias de relación) |
| `capabilities` | map[string, bool] | **solo descriptivo** | sí | Declara qué sabe hacer el skill; **nunca** concede permisos (las capacidades de escritura las decide el kernel) |
| `phases` | string[] | editable | sí | Fases del flujo (p. ej. `seed`, `anchors`, `explore`, `converge`) |
| `anchors` | map[string, spec] | editable | sí | Anclas de canon: identidad, deseo definidor, conflicto significativo, relación/rol clave |
| `required_minimums` | map[string, spec] | **protegido por política** (ver decisión abierta 16.f) | sí | Mínimos server-side antes de proponer (hoy: identidad + deseo) |
| `optional_exploration` | spec | editable | sí | Exploración adaptativa opcional (fricción, deseos, mentiras, rupturas) |
| `question_strategy` | spec | editable | sí | Una pregunta a la vez, opciones máx. 5, profundización de mundo |
| `completion_policy` | spec | editable | sí | Condiciones de readiness explícitas para converger y proponer |
| `compatibility` | string[] | protegido | sí | Versiones de protocolo runtime compatibles |
| `dependencies` | map[string, version] | editable | no | Skills/recursos de los que depende (p. ej. un skill de canon base) |

### 6.3 Campos editables vs protegidos (regla de oro)

| Tipo de campo | Quién lo edita | Efecto en runtime | Ejemplos |
|---|---|---|---|
| **Protegido (kernel)** | Nadie (solo el sistema) | Determina invariantes de seguridad y compatibilidad | `schema_version`, `id`, `version`, `compatibility`, `required_minimums` (por política), identidad de sesión |
| **Editable (metodología)** | El Autor | Determina la guía creativa dentro de los rieles | `description`, `language`, `entity_type`, `triggers`, `phases`, `anchors`, `optional_exploration`, `question_strategy`, `completion_policy`, `dependencies` |

**[DECISIÓN ABIERTA — 16.d]** El conjunto exacto de campos protegidos del kernel debe confirmarse (mínimo propuesto: `schema_version`, `id`, `version`, `compatibility`, y la política de `required_minimums`).

### 6.4 De manifest a contrato de runtime `[OBJETIVO]`

El compilador produce un **contrato runtime** que el backend ejecuta:

- Normaliza los campos editables a una especificación validada (sin Markdown libre no chequeado).
- Expone al proveedor conversacional solo el contexto autorizado y acotado de la metodología activa.
- **Nunca** traduce declaraciones de `capabilities` a permisos reales: las capacidades son descriptivas y toda autoridad es del kernel.

---

## 7. Ciclo de vida de la skill

### 7.1 Diagrama

```
crear ──> borrador ──> validar ──> publicar (versión inmutable) ──> activar/desactivar
   ▲                                                                  │
   │                                                                  ▼
borrador <── editar <── desactivar ◄── pin de sesión (snapshot)   sesión guiada
   │                                                                  │
   └──────────── eliminar permanente (papelera/trash)                 │
       (soft delete) ─────────────────────────────────────────────────┘
   importar ──> cuarentena ──> revisar ──> validar ──> publicar (misma ruta)
   exportar / compartir (Skool) ◄── desde cualquier versión publicada
```

### 7.2 Transiciones

| Transición | Regla |
|---|---|
| `create` | Solo borradores nuevos. `id` único (colisión de slug falla). |
| `draft → validate` | El compilador valida manifest + Markdown fuente; si falla, vuelve a borrador con motivos. |
| `validate → publish` | Produce la **versión publicada inmutable**; nunca más editable. Incrementa la versión y registra fecha/hora, usuario y cambios aprobados. |
| `publish → activate` | La versión publicada se activa para un mundo concreto y gobierna sus nuevos flujos guiados. El backend selecciona la **Skill activa por mundo** tras el handoff semántico y **antes de la primera llamada guiada** `[DECISIÓN CERRADA]`. |
| `activate → session pin` | Al iniciar una sesión guiada se captura el **snapshot de sesión** de la versión activa + rieles del kernel: `workshop + world + skill_id + skill_version + contrato compilado` `[DECISIÓN CERRADA]`. La sesión **fija metodología+versión**: aplicar un cambio en la metodología o la versión exige iniciar una nueva sesión; las sesiones en vuelo siguen con su snapshot original. |
| `deactivate` | La versión deja de gobernar **nuevas** sesiones; conserva la **versión e historial**, pero impide nuevas sesiones. Las sesiones en vuelo conservan su snapshot y pueden terminar `[DECISIÓN CERRADA]`. |
| `rollback` | Revertir la versión activa a una versión publicada anterior (nunca a un borrador). |
| `soft delete / trash` | Mover a papelera; reversible; TTL 30 días `[PROPUESTO — siguiendo el precedente de papelera del wiki]`. |
| `permanent delete` | Irreversible; bloqueada mientras existan sesiones/snapshots activos que la referencien. |
| `import` | Entra en **cuarentena**; no activable hasta revisión del Autor. |
| `quarantine → validate` | Revisión del Autor + validación del compilador; solo entonces publicable. |
| `export / share (Skool)` | Exporta una versión publicada como paquete `.zip` con manifest, contenido y versión; la distribución comunitaria y las actualizaciones autenticadas futuras siguen la política de Skool. |

**[DECISIÓN CERRADA — 16.c]** El formato de intercambio de skills es un paquete `.zip` que contiene como mínimo el manifest, `SKILL.md`, referencias/assets declarados y **checksum de integridad**. La capa de confianza es la **firma digital oficial** (16.b) sumada a la **cuarentena y la confianza manual** para la comunidad.

### 7.3 Import/export, cuarentena y compartición Skool `[OBJETIVO]`

| Operación | Regla | Estado |
|---|---|---|
| **Import** | El paquete entra en **cuarentena** aislada; no activable ni visible como versión activa | `[OBJETIVO]` |
| **Revisión en cuarentena** | El Autor revisa el paquete; el compilador valida; solo entonces se puede publicar/activar | `[OBJETIVO]` |
| **Export** | Exporta una versión publicada como `.zip` con identidad, semver, manifest, contenido y checksum | `[OBJETIVO]` |
| **Compartir (Skool)** | Los usuarios comparten paquetes `.zip` en la comunidad de Demiurgos; Skool es canal de comunidad/distribución y **no** ejerce autoridad de activación | `[OBJETIVO]` |
| **Actualizaciones vía API Skool** | En una versión futura, Demiurgos consultará una API/integración oficial o autorizada de Skool para verificar el entitlement de membresía y, si está activo, descargará el release desde GitHub u otro servicio de software; la descarga no instala ni activa automáticamente. Inicialmente la verificación de membresía/antigüedad es **manual por chat privado** y el Autor recibe un **enlace de pago con el monto descontado** (16.g) | `[OBJETIVO]` |
| **Confianza** | Toda importación entra en cuarentena obligatoria y muestra un informe comprensible antes de permitir publicar/activar | `[DECISIÓN CERRADA]` |
| **Integridad y firma** | Cada paquete `.zip` lleva **checksum de integridad** y, cuando proviene de una fuente oficial, **firma digital** como capa de confianza adicional; la comunidad conserva la **confianza manual** (importar y revisar en cuarentena) incluso sin firma | `[DECISIÓN CERRADA]` |

---

## 8. Compilador/validador y estado actual del runtime

### 8.1 Estado verificado `[ACTUAL]`

El runtime actual **NO carga dinámicamente `narrative-character-creation`**:

- `guided_character_provider.py` construye el envelope del proveedor con un **prompt hardcodeado** que referencia `guided-character-v1`.
- `semantic_intent.py` usa otro **prompt hardcodeado** para el gate semántico.
- La skill `skills/narrative-character-creation/SKILL.md` vive como **artefacto de metodología estático** consumible por Hermes como tool del orquestador, pero **no existe un compilador ni un adaptador** que traduzca su Markdown fuente + manifest al contrato runtime.
- Por tanto: la skill es **fuente de contrato de metodología** para el orquestador narrativo, **no** entrada del runtime guiado.

### 8.2 Desajustes concretos

| Desajuste | Detalle |
|---|---|
| Prompt hardcodeado | Las reglas del 40/60 y los rieles de la skill no entran desde el paquete; el texto fijo gobierna el envelope |
| Sin compilador | No hay validación de manifest ni conversión fuente→contrato |
| Sin biblioteca | No hay versionado, activación, import/export ni cuarentena |
| Semántica léxica secundaria | `route_new_character_intent` existe como derivación post-envelope; el gate semántico es la frontera real |

### 8.3 Puente requerido `[OBJETIVO]`

Un componente **importador/compilador/validador** que: (1) valide manifest, (2) compile el Markdown fuente a un contrato runtime, (3) alimente al provider/gate con la metodología activa **en lugar del prompt hardcodeado**, y (4) provea biblioteca/versiones/cuarentena. **No se afirma que el runtime actual ya haga esto**; es exactamente el gap que el futuro SDD debe cerrar, y las secciones 6–7 son su contrato. Este componente **no** puede alterar las invariantes del kernel (autorización, gates, digest/token, persistencia, indexado).

---

## 9. Frontend: biblioteca/editor/versiones/activación/papelera

### 9.1 Capacidades `[OBJETIVO]`

| Capacidad | Estado | Descripción |
|---|---|---|
| Biblioteca | `[OBJETIVO]` | Lista de skills (nombre, versión, estado, fuente), filtros, activación visible |
| Editor de skill | `[OBJETIVO]` | Edición de borradores (manifest + Markdown fuente) con vista previa del contrato compilado |
| Creación asistida (co-creación) | `[DECISIÓN CERRADA]` | La creación de una skill es un flujo **asistido por Hermes** (chat de co-creación), **no** un formulario técnico de Skill ID/Markdown como flujo principal; con revisión del borrador, validación visible y aprobación explícita del Autor |
| Importar/Exportar | `[OBJETIVO]` | Import → cuarentena → revisión; export de versiones publicadas |
| Activar/Desactivar | `[OBJETIVO]` | Selección de versión activa (ámbito según 16.b) |
| Versiones/Diff/Rollback | `[OBJETIVO]` | Ver historial de versiones publicadas, diff entre ellas, rollback |
| Papelera/Restaurar | `[OBJETIVO]` | Soft delete + restaurar + borrado permanente |
| Compartir Skool | `[OBJETIVO]` | Enviar/recibir paquetes; semántica de identidad/versión según 16.g |
| Creación guiada | `[ACTUAL]` | Panel único de chat con fases, propuestas aceptar/rechazar, diff final, retry de index |

### 9.2 Flujos clave de UI

**Creación guiada** `[ACTUAL]`:
1. El Autor escribe la intención en el chat normal; el backend decide el handoff guiado (gate semántico → `require_confirmation`/`proposal_ready`).
2. `GuidedCharacterPanel` muestra una pregunta por vez; propuestas con Aceptar/Rechazar.
3. `serialize` produce el diff diskless; la revisión final ocurre en el editor existente (`WikiEditor`).
4. Tras aprobar el create, se muestra el estado de indexado con reintento.

**Biblioteca/editor/versiones** `[OBJETIVO]`:
- Biblioteca: lista + detalle de versión activa.
- Editor: borrador editable; guardar como borrador; "Publicar versión" (inmutable).
- Versiones: tabla de versiones publicadas; diff seleccionable; botón rollback.
- Papelera: lista de skills eliminadas; restaurar o borrado permanente.

**Creación asistida por Hermes (co-creación)** `[DECISIÓN CERRADA]`:
1. El Autor describe la skill en lenguaje natural; Hermes conversa y **redacta la propuesta** de borrador (manifest + contenido).
2. El backend valida/compila el borrador y presenta la **validación visible** (manifest, contrato compilado, errores).
3. El Autor **revisa el borrador** y ajusta o aprueba; solo la **aprobación explícita** publica la versión. El formulario técnico de Skill ID/Markdown queda como herramienta secundaria, nunca como flujo principal.

**Import/export/Skool** `[OBJETIVO]`:
- Import: subir paquete → aparece en cuarentena con aviso → revisar/validar → publicar.
- Export: elegir versión → generar paquete.
- Skool: compartir/recibir a través del canal, respetando la semántica 16.g.

---

## 10. Flujo guiado de creación de personaje nuevo

El flujo completo implementa el principio **40/60** (sección 11). Los números entre paréntesis referencian los pasos de `narrative-character-creation/SKILL.md`.

### 10.1 Secuencia de fases

| # | Paso | Dueño | 40/60 | Comportamiento |
|---|---|---|---|---|
| 0 | **Intento/objetivo** | Backend (gate semántico) | kernel | El Autor expresa la intención. `SemanticIntentProvider` decide `allow/clarify/require_confirmation/proposal_ready/blocked`. Solo tras un envelope válido el routing léxico deriva la política. `[ACTUAL]` |
| 1 | **Ambigüedad de ficha activa** | Backend | kernel | Si hay una ficha activa como contexto, el sistema confirma si el destino es el personaje NUEVO o una edición. La ficha activa es **contexto, no objetivo** (sección 10.3). `[ACTUAL — contrato del skill]` |
| 2 | **Confirmación de referencia nombrada** | Backend | kernel | Para referencias de relación (p. ej. "la esposa de Rhyz"), se resuelve la referencia UNA vez por el grafo (search→read→links); `requires_confirmation` inicia fase `confirmation` con pregunta explícita de confirmación antes de preguntas guiadas. La semántica de la relación (semilla del Autor vs interpretación de Hermes) queda definida en 10.6 `[DECISIÓN CERRADA]`. `[ACTUAL — resolve_named_reference; defecto conocido: "esposa" en la primera sesión]` |
| 3 | **Confirmación de personaje relacionado** | Backend | kernel | El Autor confirma (sí/no/clarifica) el inicio de la propuesta de un personaje nuevo relacionado. Negar → fase `complete` sin escrituras (abandono/cambio de opinión). `[ACTUAL]` |
| 4 | **Semilla** | Backend + Hermes | 60% | Se conserva la semilla (deseo/tensión/mundo expresados) como `proposals`, nunca como canon. |
| 5 | **Rol y profundidad** | Hermes (guiado por kernel) | 60% | Rol narrativo y profundidad deseados, conversacional, **sin rangos fijos** (el legacy 7/12/18 queda fuera). `[ACTUAL — contrato del skill]` |
| 6 | **Anclas mínimas** | Backend (gate) | 40% | Gate server-side de completitud mínima: identidad (nombre) + deseo definidor (`MINIMUM_IDENTITY_FIELDS`, `MINIMUM_DESIRE_FIELDS`). El provider nunca es fuente de completitud; el servidor decide. Luego, si aplica: conflicto significativo y relación/rol clave. `[ACTUAL — candidate_minimum_complete/next_required_question]` |
| 7 | **Exploración creativa adaptativa** | Hermes | 60% | Refleja lo dicho → identifica una tensión → UNA pregunta enfocada → opciones solo si ayudan (máx. 5) → profundiza el mundo. **No** recoge campos. Ejemplos concretos en `references/conversation-examples.md` (sección 10.2). |
| 8 | **Certeza y provenance** | Backend | 40% | Etiquetado `hechos/propuestas/hipótesis/desconocidos/conflictos` con origen; el provider no expone provenance interna; confirmar certeza cuando un dato contradice o amplía el mundo. `[ACTUAL — candidate partitions + semántica de semantic_intent]` |
| 9 | **Manejo de conflictos** | Backend | 40% | Referencias no resueltas y conflictos se retienen (`unresolved_references`, `conflicts`), nunca se resuelven en silencio ni se crean archivos automáticamente. `[ACTUAL — retain_graph_evidence]` |
| 10 | **Convergencia y readiness explícita** | Backend | 40% | Con anclas mínimas presentes y el Autor satisfecho, se resume y se ofrece la propuesta. La readiness es explícita (política de completitud del skill / kernel). **Anclas mínimas ≠ readiness narrativa** (sección 10.4). `[ACTUAL — gate de completitud + fases]` |
| 11 | **Propuesta diskless** | Backend | 40% | `serialize_ficha` genera `personajes/{slug}.md` con `status: "proposed"` (slug validado, colisión chequeada). Nada se escribe. `[ACTUAL]` |
| 12 | **Aceptar/rechazar por propuesta** | Autor | kernel | El Autor aprueba o descarta cada propuesta individual (`accept_proposal`/`reject_proposal`); solo la aceptación la vuelve canon. `[ACTUAL]` |
| 13 | **Aprobación final del diff** | Autor + Backend | 40% | Diff con digest SHA-256 ligado al token de confirmación de un solo uso; la persistencia ocurre SOLO tras la aprobación explícita (`SecureCreateRequest` → `/{section}/create`). `[ACTUAL]` |
| 14 | **Persistir/indexar/recuperar** | Backend | 40% | Tras el create, `ReindexCoordinator` reconcilia el grafo (idempotente: `indexed/pending/dirty/failed`); el frontend ofrece reintento. `[ACTUAL]` |

### 10.2 Ejemplo concreto de la fase creativa (60%)

Tomado de `references/conversation-examples.md` (los diálogos allí son ilustrativos de la técnica, no canon del mundo):

> **Autor:** "Quiero crear un personaje: la hermana menor de Rhyz, pero que no quiera ser como él."
>
> **Hermes:** "Entiendo: una hermana menor que se define en contra del camino de Rhyz. La fricción ya está ahí — es fácil romper con alguien a quien no admiras. ¿Su rechazo nace de la admiración herida, ese 'nunca seré suficiente', o de la convicción de que el camino de él es un callejón sin salida?"

**Por qué funciona (contrato):** refleja el material, nombra una tensión interna (no el drama externo) y hace UNA pregunta que abre dos personajes distintos. No recoge edad, aspecto ni nación. La referencia "Rhyz" se resuelve por el grafo en el paso 2 y se trata solo como contexto de relación (paso 3 del contrato del skill), nunca como ficha a editar.

Los demás ejemplos (detalle que profundiza el mundo, hecho vs hipótesis, referencia como contexto) están en el archivo de referencia y deben leerse junto a este contrato para entrenar/validar la exploración. **Este documento no los duplica a propósito para mantenerse enfocado.**

### 10.3 Ficha activa vs referencia (distinción)

| Elemento | Rol | Regla |
|---|---|---|
| **Ficha activa** (personaje abierto en el editor/asistente) | **Contexto** leído, nunca objetivo | Si existe una ficha activa, el sistema confirma si el destino es el personaje NUEVO o una edición; la edición de fichas existentes queda fuera de esta iniciativa (N4) |
| **Referencia nombrada** (p. ej. "Rhyz", "la esposa de X") | **Contexto relacional** resuelto por el grafo una vez | Solo se usa como contexto del personaje NUEVO; nunca se edita ni expande a la referencia misma |

### 10.4 Anclas mínimas vs readiness narrativa

| Concepto | Qué lo decide | Regla |
|---|---|---|
| **Anclas mínimas** | Gate del servidor (`candidate_minimum_complete`) | Identidad (nombre) + deseo definidor presentes; el provider nunca es fuente de completitud; en modo rápido se salta el gate con supuestos marcados |
| **Readiness narrativa** | Política de completitud del skill / kernel + satisfacción del Autor | Anclas presentes Y el Autor manifiesta estar satisfecho; es una condición **explícita**, no inferida |

### 10.5 Certeza y provenance

- Todo dato del candidato se etiqueta: `accepted` (solo transición del Autor), `proposed`, `unknown`, `conflicted`. `[ACTUAL]`
- La provenance registra el origen (`graph:search:...`, `graph:read:...`, `hermes:run:...`, `rejected:{key}`) y **nunca se expone al Autor ni a Hermes como clave de autoridad**. `[ACTUAL]`
- Las referencias no resueltas/ambiguas y los conflictos se **retienen**; no se resuelven en silencio ni se crean archivos. `[ACTUAL]`

### 10.6 Relaciones propuestas vs semilla del Autor `[DECISIÓN CERRADA]`

- Una relación (p. ej. `esposa de Toryn`) o un atributo relacional (p. ej. `fallecida`) es **semilla del Autor** o **interpretación propuesta por Hermes** durante la exploración.
- Demiurgos solo **resuelve/verifica la referencia** (p. ej. Toryn) por el grafo; **no decide ni confirma la relación**.
- La relación permanece en la partición **`proposals`** (o como aclaración pendiente) hasta la **aprobación explícita del Autor**; nunca se promueve a canon automáticamente.
- Crear un personaje **relacionado** es una **rama/contexto de la Skill general de creación de personajes**, no una Skill separada (ver árbol/scoping, 3.3).

---

## 11. Principio 40/60

**[DECISIÓN CERRADA]** El 40/60 es **un principio de diseño**, no una proporción literal ni un conteo de preguntas.

| Porción | Qué controla | Ejemplos |
|---|---|---|
| **40% — rieles (rails)** | Canon, mínimos, seguridad, estado. Propiedad del sistema (kernel + campos protegidos). | Anclas de canon obligatorias (identidad + deseo definidor), gate de completitud server-side, certeza/provenance, candidato no-canónico separado, gates de aceptación y persistencia con digest/token, invariantes de revisión/seguridad. |
| **60% — construcción de mundo adaptativa** | Orden, redacción, profundidad, seguimientos, exploración opcional. Propiedad de la metodología de usuario. | Qué pregunta sigue a cuál, cómo se redacta, cuánta profundidad se explora, qué fricción opcional se ofrece, cuándo converger (dentro de la política de completitud). |

**Regla práctica:** los rieles del 40% definen **qué debe ser cierto** antes de avanzar (identidad presente, deseo definido, dato etiquetado, propuesta aprobada). El 60% define **cómo se llega** a que eso sea cierto, con libertad creativa y sin formularios. Las skills editables del usuario codifican rieles y prioridades del 40% y libertad del 60%; **nunca** fuerzan preguntas numeradas. `[ACTUAL — la primera rebanada implementa el gate de mínimos y la exploración adaptativa; el 60% se comporta por contrato de skill, no por código hardcodeado]`.

---

## 12. Máquina de estados y ramas de fallo

### 12.1 Fases de sesión guiada `[ACTUAL]`

```
                   ┌─────────────────────────────────────────────────────────┐
                   │                SESIÓN GUIADA (server-owned)              │
                   └─────────────────────────────────────────────────────────┘
 start (handoff) ──> confirmation ──> conversation ──> review ──> complete
                        │ (si requiere)        │            │
                        └──declinado──> complete│            └──aprobado──> create gated ──> reindex ──> complete
                                                │
                                                └── factual question ──> responde y vuelve a conversation
```

- Fases admitidas por el frontend: `confirmation`, `conversation`, `review`, `complete`. `[ACTUAL]`
- Fase no admitida → UI muestra "No se puede actuar sobre esta solicitud. No se guardó nada." `[ACTUAL — GuidedCharacterPanel]`

### 12.2 Estados de decisión semántica `[ACTUAL]`

| Estado | Acción determinista | Notas |
|---|---|---|
| `allow` | `answer` (chat normal) | No crea sesión guiada |
| `clarify` | `ask_question` | Una pregunta, sin mutar estado |
| `require_confirmation` | `request_confirmation` | Lleva `continuation.question`; inicia/continúa fase `confirmation` |
| `proposal_ready` | `show_proposal` | Lleva `continuation.delta` acotado (≤50 claves); nunca contiene claves de autoridad |
| `blocked` | `blocked_explanation` | Fail-closed; copia segura localizada; cero escrituras |

Los estados `require_confirmation`/`proposal_ready` son reales **solo** cuando la maquinaria guiada/sesión diskless los respalda; si falta el `continuation` o es inválido, fallan a `blocked` con cero escrituras. `[ACTUAL]`

### 12.3 Ramas de fallo y salida `[ACTUAL]`

| Rama | Comportamiento | Código |
|---|---|---|
| **Referencia ambigua/no resuelta** | `resolve_named_reference` marca `unresolved/ambiguous`; se retiene como `unresolved_references`, no se crea archivo; la copia visible pide clarificar la referencia | — |
| **Grafo no disponible** | `_named_reference_context` → `graph_unavailable`; la ruta cierra con `CAPABILITY_UNAVAILABLE` retryable | 503 |
| **Mundo no disponible** | `_resolve_mundo_dir` falla → `INVALID_INPUT`; sin sesión | 422 |
| **Colisión de slug** | `serialize_ficha` lanza `FichaValidationError("character slug collision")`; sin persistencia | 422 |
| **Proveedor no disponible** | `invoke_bounded` → `Outcome.UNAVAILABLE` retryable; gate semántico → `blocked` fail-closed sin fallback léxico | 503 |
| **Timeout/cancelación** | `invoke_bounded` → `TIMEOUT`/`CANCELLED` retryable; token de cancelación activa | 504/499 |
| **Salida malformada/sobre-limitada** | Envelope inválido → `MALFORMED_OUTPUT`/`INVALID_ENVELOPE_REASON`; intentos limitados a 3 | 502/422 |
| **Conflicto de revisión** | Revisión obsoleta (otra pestaña/mensaje) → `REVISION_CONFLICT` retryable | 409 |
| **Abandono/cambio de opinión del Autor** | Rechazo de confirmación → fase `complete`; rechazo de propuesta → propuesta descartada; nunca promueve a canon | — |
| **Confirmación ambigua** | `confirmation_decision` no clasifica (sí/no/neutral) → pregunta de clarificación, sin mutar canon | — |
| **Fallo de validación** | Envelope malformado/con autoridad → `MALFORMED_OUTPUT` o `INVALID_ENVELOPE_REASON`; intentos ≤3 | 422/502 |
| **Propuesta rechazada** | `reject_proposal` conserva registro `rejected:{key}` en provenance, fuera de canon | — |
| **Fallo de indexado** | `ReindexCoordinator` → `failed/dirty/pending` con reintento idempotente | — |
| **Contenido alterado tras create** | La verificación de digest falla → `INTERNAL`; nunca se reporta éxito falso | 500 |
| **Rollback** | Solo de versión publicada activa a versión publicada anterior; nunca a borrador `[OBJETIVO]` | — |

**Manejo de idioma (`[ACTUAL]`)**: el idioma de la UI/prosa viene de `DEMIURGOS_LANGUAGE` (`demiurgos_language.resolve_ui_language`); el provider responde en el idioma de la entrada del Autor; las preguntas por defecto y la copia fail-closed están localizadas (es/en); el manifest declara su `language`. El cambio dinámico de idioma es decisión global (constitución, G7).

**Semántica del modo rápido (`[ACTUAL]`)**: marcadores explícitos ("sin preguntas", "créalo ya", "skip the questionnaire", etc.) y marcadores rápidos combinados con verbos directos derivan `mode="fast"` y `depth="fundamental"`; en modo rápido el provider marca supuestos, arma un candidato preliminar y **el gate de completitud mínima se salta** (`candidate_minimum_complete` devuelve `True` para `mode=="fast"`). El modo completo (`full`/`standard`) aplica el gate en cada turno.

---

## 13. Envelope de sesión y responsabilidades del runtime

### 13.1 Quién hace qué (frontera exacta de ejecución)

| Operación | Propietario | Hermes (provider) |
|---|---|---|
| Consultar el grafo (search→read→links) y resolver referencias | **Backend** (`resolve_named_reference`, `collect_graph_evidence`) | **No**: recibe contexto ya resuelto y acotado |
| Construir el contexto autorizado del proveedor | **Backend** (`SemanticContext` limitado a `mundo/ficha/reference/graph`) | **No**: no puede ampliar ni alterar el contexto |
| Serializar la ficha propuesta (diskless, slug/target validados) | **Backend** (`serialize_ficha`) | **No** |
| Calcular el digest SHA-256 y ligarlo a la propuesta | **Backend** | **No** |
| Emitir y consumir el token de confirmación de un solo uso | **Backend** (`_issue_confirmation`/`_redeem_confirmation`) | **No** |
| Persistir el archivo | **Backend** (rutas `/{section}/create|save` gated) | **No** |
| Indexar/reindexar el grafo | **Backend** (`ReindexCoordinator`) | **No** |
| Persistir en Engram | **Capa de orquestación narrativa** (AGENTS.md / flujos de fase) | **No como parte del envelope guiado** |
| Emitir la decisión semántica y las propuestas de creación | — | **Sí**, exclusivamente como envelope JSON estricto (estado/continuación) |

**[DECISIÓN CERRADA]** El envelope del proveedor guiado solo contiene `outcome` (`question`/`delta`), `question`, `delta` acotado, `provenance` y metadatos de run. **Nunca** claves de autoridad ni resultados de operaciones del servidor. El runtime guiado **no persiste Engram ni indexa por sí mismo**: esas responsabilidades pertenecen al servidor y a la capa de orquestación, nunca al proveedor.

---

## 14. Invariantes de versión/sesión y de seguridad

### 14.1 Versión y sesión

- Toda versión publicada es **inmutable**; las sesiones referencian versiones publicadas, nunca borradores. `[OBJETIVO]`
- Cada sesión guiada captura un **snapshot de sesión** (versión de skill + rieles del kernel) al iniciar; republicaciones posteriores no alteran sesiones en vuelo. La sesión **fija metodología+versión** y **aplicar un cambio exige iniciar una nueva sesión**. `[DECISIÓN CERRADA]`
- **`[DECISIÓN CERRADA]`** Activar una **versión nueva** de la Skill requiere una **nueva conversación** en el Asistente IA del Taller de Mundo; las sesiones anteriores **no** la utilizan.
- **`[DECISIÓN CERRADA]`** Desactivar una Skill conserva la **versión e historial**, pero impide **nuevas sesiones**; las sesiones existentes conservan su snapshot y pueden terminar.
- **`[DECISIÓN CERRADA]`** La activación **no modifica `AGENTS.md`**; el backend nunca lo reescribe dinámicamente (ver constitución, 7.1).
- **`[DECISIÓN CERRADA]`** El contrato compilado deriva de **fuente + manifest** y se **proyecta de forma compacta por turno** a Hermes; no se reenvía Markdown crudo ni se confía en la memoria implícita del proveedor.
- Toda mutación de sesión exige `authorization_binding` correcto **y** revisión vigente. `[ACTUAL — GuidedSessionStore]`
- El estado de sesión autoritativo vive en el backend; `localStorage` del frontend es solo una pista de recuperación. `[ACTUAL]`
- Un mismo `world` no comparte sesiones entre principales distintos. `[ACTUAL — principal.id binding]`

### 14.2 Seguridad

- **Cero escrituras sin aprobación explícita**: nada persiste hasta el diff aprobado con digest + token de un solo uso. `[ACTUAL]`
- **Provider no confiable**: Hermes jamás es fuente de digest, revision, target, acceptance o autoridad. Cualquier clave de autoridad invalida el envelope. `[ACTUAL]`
- **Targets autorizados**: solo `personajes/{slug}.md` para creación guiada; secciones allowlist; rutas internas/provenance nunca expuestas al Autor. `[ACTUAL]`
- **Fail-closed**: proveedor no disponible/indefinido/no válido → `blocked`/`unavailable` con copia segura localizada, cero mutaciones. `[ACTUAL]`
- **Contexto acotado**: el contexto autorizado que llega a Hermes se limita a `mundo/ficha/reference/graph`; cualquier otra clave se descarta estructuralmente. `[ACTUAL — normalize_context]`
- **Rollback de versión activa** no puede violar invariantes de sesión (nunca afecta snapshots en vuelo). `[OBJETIVO]`
- **Compilador acotado**: el futuro compilador/validador no puede alterar las invariantes anteriores (sección 8.3). `[DECISIÓN CERRADA]`

---

## 15. Migración desde el estado actual

### 15.1 Inventario

| Recurso | Rol | Estado |
|---|---|---|
| `skills/crear_personaje.md` | Legacy (cuestionario 7/12/18, eneatipo/stal/arquetipos) | **Referencia histórica**. Fuera de uso para el flujo guiado; no se elimina, no se reutiliza como base de la skill activa |
| `skills/narrative-character-spec/SKILL.md` | Skill de rosters/arcos | Activo, otro dominio (no confundir con creación guiada) |
| `skills/narrative-character-creation/SKILL.md` + `references/conversation-examples.md` | **Skill de creación guiada** (contrato 40/60, reglas duras, gates, pasos) | `[ACTUAL]` como artefacto de metodología estático del orquestador; **NO lo carga el runtime guiado** |
| `guided_character_provider.py` | Adaptador Hermes con prompt **hardcodeado** del envelope | `[ACTUAL]` |
| `semantic_intent.py` | Gate semántico (5 estados, fail-closed, 3 intentos) | `[ACTUAL]` |
| `guided_character_protocol.py` / `domain.py` / `persistence.py` | Protocolo, dominio, persistencia segura | `[ACTUAL]` |
| `api_server.py` | Endpoints guiados + gate semántico + create gated | `[ACTUAL]` |
| Frontend guiado | `useGuidedCharacter`, `GuidedCharacterPanel`, `guidedCharacter.ts`, `semanticIntent.ts` | `[ACTUAL]` |

### 15.2 Desajuste actual y puente requerido

**[ACTUAL — hecho verificado]** El runtime actual **NO carga `narrative-character-creation`**: el provider usa un prompt hardcodeado que referencia `guided-character-v1` y el gate semántico usa otro prompt hardcodeado. La skill vive como archivo estático consumible por Hermes como tool, pero **no existe** un compilador ni un adaptador que traduzca el Markdown fuente + manifest al contrato runtime.

**Puente requerido `[OBJETIVO]`:** un componente **importador/compilador/validador** que (1) valide manifest, (2) compile el Markdown fuente a un contrato runtime, (3) alimente al provider/gate con la metodología activa en lugar del prompt hardcodeado, y (4) provea biblioteca/versiones/cuarentena. Las secciones 6–7 y 8.3 son el contrato de ese trabajo.

---

## 16. Decisiones cerradas y abiertas

### 16.1 Cerradas (no revertir sin nuevo acuerdo)

- **C1.** La metodología de creación es contenido editable del Autor (paquetes de skill versionados), no lógica del servidor; sin prompts hardcodeados como producto final (secciones 1, 8).
- **C2.** Hermes no escribe, no otorga permisos, no salta compuertas, no consulta el grafo por sí mismo, no serializa/digest/tokens/Engram/indexa; el backend es dueño de grafo/sesión/revisión/candidate/propuesta/diff/autorización/persistencia/indexado (secciones 5, 13).
- **C3.** Nada persiste sin aprobación explícita; candidato no-canónico separado; aceptación es transición exclusiva del Autor (secciones 10, 14).
- **C4.** 40/60 es principio de diseño, no proporción ni conteo (sección 11).
- **C5.** El legacy 7/12/18 queda fuera de uso; una pregunta a la vez; opciones ≤5.
- **C6.** Primera rebanada: solo creación de personajes nuevos (sin editar fichas, sin catálogos, sin imágenes).
- **C7.** La UX es un chat normal con handoff interno; no un wizard de campos.
- **C8.** El gate semántico (Hermes) es la frontera de intención; sin fallback léxico autónomo como autoridad.
- **C9.** La constitución global prevalece sobre este documento; este documento no duplica la definición global (sección 0).
- **C10.** La co-creación, la intención semántica y la **Skill Madre** son decisiones globales de la constitución (secciones 2.3, 5, G13/10.5); esta iniciativa las referencia sin duplicarlas y regula solo la **biblioteca gestionada por el Autor**.

### 16.2 Decisiones 16.a–16.l (todas cerradas; solo quedan residuos propuestos o fuera de iniciativa)

| ID | Decisión | Opciones/Propuesta | Depende de |
|---|---|---|---|
| **16.a** | Ámbito de activación de la skill | **[DECISIÓN CERRADA]** La skill se activa por mundo; cada mundo puede tener su propia versión activa | Modelo de biblioteca |
| **16.b** | Permisos/confianza en compartición | **[DECISIÓN CERRADA]** Toda importación entra en cuarentena y requiere revisión/validación antes de publicar o activar. El paquete `.zip` lleva **checksum de integridad**; la **firma digital oficial** es una capa de confianza adicional; la comunidad conserva la **confianza manual** (importar y revisar en cuarentena) incluso sin firma. La cadena de confianza para terceros no oficiales queda `[PROPUESTO]` | Canal Skool |
| **16.c** | Transporte de paquete | **[DECISIÓN CERRADA]** Paquete `.zip` con manifest, contenido declarado y checksum; la **firma digital oficial** como capa de confianza según 16.b | Import/export |
| **16.d** | Campos protegidos exactos del kernel | **[DECISIÓN CERRADA]** Son ineditables: autorización, persistencia, tokens/digests, targets allowlist, compatibilidad de runtime, mínimos kernel y máquina de fases. Triggers, preguntas, fases metodológicas y exploración son editables solo dentro de esa validación | Manifest/kernel |
| **16.e** | Ediciones y versionado | **[DECISIÓN CERRADA]** Toda edición publicada crea una nueva versión inmutable (V1, V2…), con fecha/hora y usuario que la editó; las sesiones fijan su snapshot | Ciclo de vida |
| **16.f** | Política de anclas mínimas | **[DECISIÓN CERRADA]** La completitud se define por tipo de entidad/entrada; cada tipo tendrá un contrato de mínimos extensible, no una lista universal. En OKF v1 se implementa **personaje primero** (constitución, G1) | Manifest/seguridad |
| **16.g** | Skool como canal de comunidad y descuentos | **[DECISIÓN CERRADA en producto]** Los usuarios comparten skills `.zip` en la comunidad; Skool no distribuye software ni concede entitlements de módulos. Los módulos se compran una sola vez; inicialmente el Autor verifica manualmente por chat privado la membresía/antigüedad y envía el enlace Stripe con el descuento correspondiente. La comunidad recibe descuentos escalonados por antigüedad (más de 3, 6 y 9 meses) y el descuento máximo por membresía anual; una futura automatización puede reemplazar el paso manual. Quedan fuera de esta iniciativa los porcentajes exactos, la política de antigüedad acumulada/continua y las actualizaciones posteriores | Plataforma/Skool |
| **16.h** | Relaciones propuestas en creación guiada | **[DECISIÓN CERRADA]** `esposa de Toryn` / `fallecida` son **semilla del Autor** o **interpretación propuesta por Hermes**; Demiurgos solo resuelve/verifica la referencia y mantiene la relación como **propuesta** hasta aprobación; crear personajes relacionados es rama/contexto de la skill general, no una skill separada (sección 10.6) | Flujo guiado |
| **16.i** | Árbol y scoping por Taller | **[DECISIÓN CERRADA]** Skills organizadas por Taller/capacidad; cada sesión recibe solo su alcance (Taller, skill activa, versión, mundo, contexto autorizado), nunca el árbol completo; cruces entre Talleres requieren **handoff explícito**. Hermes presente en cada Taller queda `[OBJETIVO]` (sección 3.3) | Biblioteca |
| **16.j** | Activación de la skill activa | **[DECISIÓN CERRADA]** El backend selecciona la skill activa por mundo tras el handoff semántico y **antes de la primera llamada guiada**; snapshot `workshop + world + skill_id + skill_version + contrato compilado`; **no modifica `AGENTS.md`**; el contrato compilado se proyecta **compacto por turno** (secciones 7.2, 14.1, 16.3) | Ciclo de vida/runtime |
| **16.k** | Versiones y desactivación | **[DECISIÓN CERRADA]** Publicada inmutable; cambios crean nueva versión. Activar una versión nueva exige **nueva conversación** en el Asistente IA del Taller de Mundo. Desactivar conserva versión/historial pero impide **nuevas sesiones**; las sesiones existentes conservan su snapshot y pueden terminar (sección 14.1) | Ciclo de vida |
| **16.l** | UX del Taller de Herramientas | **[DECISIÓN CERRADA]** La creación de skills es **asistida por Hermes** (co-creación), no un formulario técnico de Skill ID/Markdown como flujo principal; con revisión del borrador, validación visible y aprobación explícita del Autor (sección 9) | Frontend |

### 16.3 Decisión de diseño sobre el snapshot de sesión

**[DECISIÓN CERRADA]** La sesión guiada **fija metodología+versión** al iniciarse y **aplicar un cambio exige iniciar una nueva sesión**; republicaciones posteriores no alteran sesiones en vuelo (secciones 7.2 y 14.1). El snapshot de activación incluye **Taller (`workshop`) + mundo (`world`) + `skill_id` + `skill_version` + contrato compilado**, y el backend lo crea tras el handoff semántico y **antes de la primera llamada guiada** (decisión 16.j).

`[PROPUESTO]` Los campos internos del snapshot se registran como propuesta técnica para que un SDD futuro no los invente distinto: `{workshop, world, skill_id, skill_version, contract_compiled_digest, kernel_policy_digest}`. El detalle de esos campos **no es contrato** hasta la aprobación del SDD.

---

## 17. Criterios de aceptación / definition of ready para SDD futuro

Un SDD de esta área **solo** puede comenzar cuando se cumplan todos:

- [ ] Las partes todavía abiertas quedan resueltas y anotadas en este documento: detalle técnico de los digests del snapshot (16.3 `[PROPUESTO]`), cadena de confianza para terceros no oficiales (16.b `[PROPUESTO]`), y lo declarado fuera de esta iniciativa (porcentajes exactos y política de antigüedad de descuentos en 16.g).
- [ ] Se mantienen intactas las invariantes `[ACTUAL]`: cero escrituras sin aprobación, `apply_delta` no toca `accepted_canon`, revisión+autorización antes de cada mutación, gate semántico fail-closed, targets `personajes/` allowlist, digests server-computed, token de un solo uso, contexto acotado `mundo/ficha/reference/graph`.
- [ ] El SDD incluye un contrato para el **compilador/validador** (manifest→contrato runtime) sin reescribir el protocolo `guided-character-v1`.
- [ ] El SDD incluye la biblioteca (versiones publicadas inmutables, activación, rollback, papelera) y la cuarentena de importación.
- [ ] El SDD verifica que ninguna sesión en vuelo se ve alterada por republicaciones (snapshot de sesión).
- [ ] Las pruebas cubren: ramas de fallo de la sección 12.3, invariantes de la sección 14, manejo de idioma y modo rápido, y los ejemplos de `conversation-examples.md` como casos de entrenamiento/validación de la fase creativa.
- [ ] `narrative-character-creation` es el único skill de creación guiada; `crear_personaje.md` permanece como referencia histórica sin uso en runtime.
- [ ] El SDD declara explícitamente que NO toca AGENTS.md, el registro de skills, ni los archivos de lore/personajes fuera de la escritura gated.
- [ ] El SDD referencia la constitución global (`demiurgos-platform.md`) y no contradice sus secciones 5, 7 y 9.
