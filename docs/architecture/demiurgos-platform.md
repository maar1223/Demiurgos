# Demiurgos — Constitución de Arquitectura de la Plataforma

> **Fuente de verdad global de producto y arquitectura.** Este documento es el contrato canónico de la plataforma Demiurgos. Todo trabajo de implementación (SDD, herramientas, UI, servicios) se valida contra este documento y contra el contrato de la iniciativa que le aplique. **No es un artefacto SDD**: describe qué es y qué debe cumplir la plataforma, no prescribe implementación hasta que una decisión esté cerrada. Lo que no está etiquetado como `[ACTUAL]` no debe presentarse como existente.

| Campo | Valor |
|---|---|
| Estado | Constitución de arquitectura (fuente de verdad global) |
| Versión del documento | 1.7 |
| Fecha | 2026-08-17 |
| Autor | Demiurgos (orquestación) |
| Idioma | Español neutro (prosa técnica) |
| Alcance | Plataforma completa: frontend, backend, Hermes, almacenamiento, grafo, indexado, workflows, memoria y UI |
| Relación con SDD | Requisito previo global. Ningún SDD/tool debe comenzar sin leer este documento y el de la iniciativa afectada |
| Documentos relacionados | `docs/architecture/skill-library-and-guided-character-creation.md` (iniciativa de skills + creación guiada — subsistema), `docs/architecture/tool-workshop.md` (contrato de superficie del Taller de Herramientas), `docs/architecture/world-workshop.md` (contrato del Taller de Mundo), `docs/architecture/foundational-research-skill.md` (contrato de la Skill Fundacional de Investigación — skill transversal), `AGENTS.md` (orquestador narrativo), `README.md`, `Agente_Maestro.md` |

## Leyenda de etiquetas

| Etiqueta | Significado |
|---|---|
| `[ACTUAL]` | Comportamiento que existe hoy en el repositorio y está verificado |
| `[OBJETIVO]` | Comportamiento objetivo acordado, no necesariamente implementado aún |
| `[PROPUESTO]` | Diseño propuesto; requiere decisión antes de ser contrato |
| `[DECISIÓN ABIERTA]` | Punto sin resolver que requiere aprobación explícita del Autor |
| `[DECISIÓN CERRADA]` | Decisión ya aprobada; no debe revertirse sin nuevo acuerdo explícito |

---

## 0. Cómo usar estos documentos antes de tocar código

Antes de implementar CUALQUIER herramienta web de Demiurgos, en orden:

1. **Lee esta constitución** (`demiurgos-platform.md`): definición del producto, principios, mapa del sistema, conceptos canónicos, superficies con su etiqueta de estado, y reglas de arquitectura.
2. **Lee la iniciativa relevante** (p. ej. `skill-library-and-guided-character-creation.md` para el subsistema técnico y `tool-workshop.md` para la superficie del Taller de Herramientas) si el trabajo toca esa área. Si no existe iniciativa para tu área, este documento es tu contrato de partida y el trabajo debe pasar por un SDD/propuesta antes de implementar.
3. **Consulta el runtime real** (CodeGraph/`codegraph_explore` primero, luego lectura puntual): nunca asumas comportamiento; verifica `[ACTUAL]` contra el código y los tests.
4. **Si el cambio es de arquitectura sensible**, propón un SDD (propuesta → spec → diseño → tareas → implementación → verificación). **No empieces un SDD ahora mismo por este documento**; primero se resuelven las decisiones abiertas que toquen tu cambio.
5. **Regla de etiquetas**: toda afirmación nueva lleva `[ACTUAL]` (verificado), `[OBJETIVO]`, `[PROPUESTO]` o `[DECISIÓN ABIERTA]`. Nunca presentes comportamiento objetivo como implementado.

---

## 1. Definición del producto

### 1.1 Definición en una frase

**[DECISIÓN CERRADA]** Demiurgos es la **plataforma web integral, agnóstica de mundo, para gestionar lore y worldbuilding** — compuesta por frontend, backend, Hermes, almacenamiento, grafo, indexado, workflows y UI — que acepta cualquier mundo que el Autor cargue en **formato OKF** y **nunca se acopla a Vibrantes ni a un único universo ficticio**.

### 1.2 Qué es y qué no es

| Demiurgos ES | Demiurgos NO es |
|---|---|
| Plataforma web completa (frontend + backend + servicios de gestión) | Un único skill de narrativa o un "prompt de IA" |
| Freeware propietario con capacidades gratuitas y de pago | Un proyecto open source o una distribución pública del código |
| **Core gratuito + módulos de pago único** | Una suscripción obligatoria para usar el núcleo, una licencia recurrente por cada taller o el bloqueo de la versión instalada al caducar el acceso a actualizaciones |
| **Cobros agnósticos de proveedor** | Depender estructuralmente de un único proveedor de cobro (p. ej. solo Stripe o solo Binance); los descuentos se calculan en Demiurgos, no en el proveedor |
| Agnóstica de mundo: opera cualquier mundo en OKF | Una aplicación específica del universo Vibrantes |
| Canon-safety: el canon es sagrado, las contradicciones se señalan antes de llegar a la página | Un editor de wiki genérico sin gobierno de canon |
| Intención sobre comandos: el Autor habla naturalmente, la plataforma orquesta | Una máquina de formularios ni un asistente de campos |
| Proveedor de IA intercambiable (Hermes es uno de ellos) | Sinónimo de Hermes |
| Con memoria persistente obligatoria (Engram) | Un chat efímero sin memoria |
| Escritura siempre detrás de compuertas con aprobación explícita | Un sistema que persiste lo que la IA propone automáticamente |

### 1.3 Autor objetivo

El **Autor** es el usuario de la plataforma: escribe intenciones y respuestas en lenguaje natural, aprueba o rechaza cada propuesta, decide qué es canon y gestiona los mundos cargados. La plataforma existe para servir al Autor como **única fuente de hechos canónicos**; toda capacidad de IA está subordinada a su aprobación.

### 1.4 Principios de producto

| Principio | Regla | Estado |
|---|---|---|
| **Soberanía del Autor** | El Autor es la única fuente de hechos canónicos; ningún contenido se convierte en Canon, versión publicada o estado activo sin su aprobación explícita. Los borradores de trabajo pueden autoguardarse para evitar pérdidas | `[DECISIÓN CERRADA]` |
| **Canon y evidencia** | El canon vive en los archivos del mundo; la IA consulta la fuente y señala contradicciones; toda afirmación propuesta lleva provenance y certeza | `[DECISIÓN CERRADA]` |
| **Agnosticismo de mundo** | La plataforma opera mundos en OKF; está prohibido acoplar la arquitectura a un mundo concreto (Vibrantes es un mundo de ejemplo, no un requisito) | `[DECISIÓN CERRADA]` |
| **Intención, no comandos** | El Autor se expresa naturalmente; el orquestador interpreta, valida precondiciones y encadena fases | `[DECISIÓN CERRADA]` |
| **Agnosticismo de proveedor** | Configuración unificada de proveedores (texto/visión); Hermes es el proveedor conversacional actual y tratado como componente reemplazable | `[DECISIÓN CERRADA]` |
| **Fronteras seguras de propuesta/escritura** | Las propuestas no alteran Canon ni runtime; los borradores de trabajo pueden autoguardarse, pero toda promoción a Canon, publicación o activación ocurre solo tras aprobación con digest + token de un solo uso | `[DECISIÓN CERRADA]` |
| **Divulgación progresiva** | Primero lo esencial, después lo profundo; una pregunta a la vez; opciones solo cuando ayudan (máx. 5) | `[DECISIÓN CERRADA]` |
| **Memoria persistente** | Engram es memoria obligatoria; sin ella el flujo de co-creación se detiene y reporta el error | `[DECISIÓN CERRADA]` |
| **Metodología como contenido** | Las metodologías creativas (qué preguntar, cómo explorar) son contenido editable del Autor (skills), no lógica incrustada en el servidor | `[DECISIÓN CERRADA]` |
| **Co-creación asistida** | En la creación de skills, Hermes conversa y **redacta la propuesta**; el backend valida/compila y protege el kernel; el Autor aprueba la publicación. Hermes no escribe ni decide canon | `[DECISIÓN CERRADA]` |
| **Co-creación adaptativa** | El sistema **aprende el vocabulario y la estructura del mundo** y **pregunta ante la ambigüedad** en lugar de asumir; el LLM propone y el backend conserva **contexto, procedencia y seguridad**; el Autor confirma | `[DECISIÓN CERRADA]` |

### 1.5 Co-creación adaptativa y soberanía del Autor `[DECISIÓN CERRADA]`

La co-creación es **adaptativa**: la plataforma aprende el **vocabulario y la estructura del mundo** a lo largo de la interacción y **pregunta ante la ambigüedad** en lugar de asumir interpretaciones. Es un principio de diseño y no una afirmación de superioridad comercial.

- **El LLM propone; el backend conserva**: el proveedor redacta candidatos; el backend mantiene el **contexto, la procedencia y la seguridad** (compuertas, digest + token, autorización) sin delegar esa autoridad (sección 5).
- **El Autor confirma**: nada pasa a Canon, versión publicada o estado activo sin aprobación explícita (Soberanía del Autor, 1.4).
- **Etapas separadas**: **contexto → propuesta → escritura → Canon** son etapas distintas, con estado y compuertas propios; no se funden ni se saltan.
- **Conexiones sin mutación automática de destinos**: una conexión o relación propuesta **no modifica** las entidades implicadas ni se confirma sola; queda como candidato hasta la aprobación del Autor (coherente con W4 del Taller de Mundo).

---

## 2. Mapa del sistema y flujo de datos

### 2.1 Mapa de componentes `[ACTUAL]`

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DEMIURGOS (plataforma)                        │
│                                                                     │
│  ┌────────────┐   ┌──────────────────────────┐   ┌───────────────┐  │
│  │  FRONTEND  │──▶│       BACKEND API        │──▶│  ALMACENAM.   │  │
│  │  React/Vite│   │  FastAPI api_server.py   │   │ mundos/{mundo}│  │
│  │  (wiki,    │◀──│  (auth, wiki, assistant, │◀──│  + .papelera  │  │
│  │   editor,   │   │   guided, grafo, ideas) │   │  + historial   │  │
│  │   guided)   │   └──────────┬──────────────┘   └───────────────┘  │
│  └────────────┘              │                                      │
│        ▲                     ▼                                      │
│        │            ┌─────────────────────┐                        │
│        │            │      GRAFO / ÍNDICE  │                        │
│        │            │  graph_indexer.py    │                        │
│        │            │  search·read·links   │                        │
│        │            │  MCP server (10+     │                        │
│        │            │  tools)              │                        │
│        │            └──────────┬──────────┘                        │
│        │                       │                                    │
│        │                       ▼                                    │
│        │            ┌─────────────────────┐                        │
│        └────────────│   HERMES (prov.)     │◀── Engram (memoria)    │
│   UI ◀──── SSE ◀────│  runs adapter +      │                        │
│   (chat/assistant)  │  semantic gate       │                        │
│                     └─────────────────────┘                        │
│                                                                     │
│  Orquestador: AGENTS.md (14 skills narrativas) + .demiurgos-estado  │
│  Indexado: src/tools/sync_lore (pipelines) · Ideas: idea_capture    │
│  Config: onboarding + Centro (wiki) · Instalación: install.sh       │
└─────────────────────────────────────────────────────────────────────┘
```

**Componentes de distribución** *(2026-10-02, decisión G8)* — capa separada de
la aplicación, sobre el canal público:

| Componente | Rol |
|---|---|
| `install.sh` / `install.ps1` | bootstraps públicos: descargan, verifican y delegan al core de instalación |
| `scripts/install-demiurgos.sh` / `.ps1` | core de instalación: pisos de sistema, `uv` verificado, entorno con ruedas y *hash lock*, staging atómico, semilla del data root |
| `scripts/start-demiurgos.sh` / `.ps1` | launcher portable: deriva rutas de su propia ubicación, gestión idempotente, provider opcional |
| `.github/workflows/release.yml` | pipeline: un solo build del frontend, empaquetado por sistema, auditoría del payload, manifiesto firmado y smoke anónimo antes de mover `latest` |

### 2.2 Flujo de datos end-to-end

```
 1. OKF (mundos/{mundo}: lore/, personajes/, sagas/)
    └─▶ [Import/sync_lore] valida y normaliza el mundo OKF           [ACTUAL — pipeline de importación]
        └─▶ [graph_indexer] construye grafo e índice
             (search → read → links/backlinks, watch de cambios)      [ACTUAL]
                └─▶ [Backend API] sirve endpoints: wiki, editor,
                     asistente, creación guiada, media, trash          [ACTUAL]
                     └─▶ [Frontend/workspace] UI del Autor             [ACTUAL]
                          └─▶ [Hermes] conversación con contexto
                               acotado server-verificado
                               (SemanticContext: mundo/ficha/reference/graph) [ACTUAL]
                               └─▶ [Propuestas/revisión] diskless:
                                    diff + digest SHA-256 server-side
                                    + token de confirmación             [ACTUAL]
                                    └─▶ [Persistencia gated]
                                         /{section}/create|save
                                         (verifica digest/token)        [ACTUAL]
                                         └─▶ [ReindexCoordinator]
                                              reconcilia el grafo
                                              (indexed/pending/dirty/failed) [ACTUAL]
```

### 2.3 Límites de confianza (resumen de responsabilidades)

| Actor | Responsabilidad | Autoridad de escritura | Notas |
|---|---|---|---|
| **Autor** | Expresar intención, responder, aprobar/rechazar cada propuesta y el diff final | Única fuente de hechos canónicos; aprueba cada escritura | `[ACTUAL]` |
| **Frontend** | Renderizar chat/fases/propuestas/diff/biblioteca; enviar turnos; recuperar sesión | Ninguna: solo emite acciones mapeadas a API; `localStorage` es pista de recuperación, el backend es autoritativo | `[ACTUAL]` |
| **Backend (policy/sesión)** | Grafo (search/read/links), sesión/revisión, candidate state, propuesta/diff, autorización, persistencia gated, indexado, gate semántico, fail-closed | Único dueño de la escritura gated; ningún otro actor delega esta autoridad; **no redacta síntesis creativas ni decide relaciones** (las propone Hermes; las aprueba el Autor) | `[ACTUAL]` |
| **Hermes (proveedor)** | Voz conversacional, **determinación de la intención semántica**, propuestas/deltas y redacción de la propuesta de co-creación en envelope JSON estricto | **NUNCA** escribe, no otorga permisos, no toca grafo/filesystem como autoridad, no decide canon | `[ACTUAL]` |
| **Grafo/índice** | Resolver entidades, enlaces, evidencia; reindexación | Solo índice; nunca autor de canon | `[ACTUAL]` |
| **Almacenamiento** | Archivos del mundo + papelera + snapshots de historial | Solo vía rutas gated del backend | `[ACTUAL]` |
| **Skills** | Metodologías de creación (contenido editable del Autor) | Ninguna por sí mismas: ejecutan dentro de rieles del kernel | `[OBJETIVO]` |
| **Proveedores de IA** | Texto (extracción/escritura) y visión (imágenes) bajo configuración unificada | Ninguna: proveedores no confiables y acotados | `[ACTUAL]` |
| **Engram** | Memoria persistente de sesiones, decisiones y artefactos | Ninguna sobre el canon: registro, no fuente | `[ACTUAL]` |
| **Canales externos (p. ej. Skool/Telegram)** | Comunidad/entitlement para ideas, paquetes compartidos y acceso autorizado a actualizaciones | Ninguna hasta validación/revisión del Autor | `[OBJETIVO]` |

---

## 3. Conceptos de datos canónicos

| Concepto | Definición | Estado |
|---|---|---|
| **Mundo (world)** | Un universo cargado en OKF bajo `mundos/{mundo}/`; unidad de aislamiento de datos y sesiones | `[ACTUAL]` |
| **Entidad** | Unidad del grafo (personaje, lugar, facción, artefacto, saga) derivada de archivos OKF; leída vía grafo, nunca vía filesystem | `[ACTUAL]` |
| **Lore** | Hechos del mundo (reglas, lugares, historia) bajo `lore/`; fuente de canon | `[ACTUAL]` |
| **Personaje (ficha)** | Ficha de personaje bajo `personajes/`; objetivo de creación guiada | `[ACTUAL]` |
| **Relación** | Enlace entre entidades (forward/backlinks) derivado del grafo | `[ACTUAL]` |
| **Referencia (reference)** | Entidad nombrada citada por el Autor como contexto relacional; se resuelve por el grafo una vez (search→read→links) | `[ACTUAL]` |
| **Fuente/evidencia** | Origen trazable de un dato (archivo, ruta del grafo, `hermes:run:...`, `graph:read:...`); base de la provenance | `[ACTUAL]` |
| **Aceptado / propuesto / desconocido / conflictuado** | Estados de certeza de un dato de candidato: `accepted_canon` (solo transición del Autor), `proposals`, `unknowns/rumors`, `conflicts`, `unresolved_references` | `[ACTUAL]` |
| **Sesión** | Unidad de interacción guiada, ligada a `authorization_binding` y con revisión optimista (`revision`) | `[ACTUAL]` |
| **Skill** | Metodología de creación versionada que gobierna un flujo guiado; contenido editable del Autor | `[ACTUAL — artefacto estático] / [OBJETIVO — biblioteca]` |
| **Skill Madre** | Capacidad protegida **instalada obligatoriamente con Demiurgos**: no editable ni eliminable, **invisible en el árbol de skills**, **no desactivable**, se actualiza solo mediante **releases oficiales** y sirve para **co-crear nuevas skills** | `[DECISIÓN CERRADA — G13]` |
| **Versión** | Snapshot inmutable de una skill publicada | `[OBJETIVO]` |
| **Propuesta (proposal)** | Dato o ficha propuesta, diskless, hasta aprobación explícita | `[ACTUAL]` |
| **Diff** | Comparación entre contenido vigente y propuesto; ligado a digest SHA-256 y token de un solo uso | `[ACTUAL]` |
| **Revisión (revision)** | Contador optimista de concurrencia de la sesión; toda mutación exige revisión vigente | `[ACTUAL]` |
| **Autorización** | `principal.id` (cookie HttpOnly, mismo origen) ligado a sesión y a toda escritura confirmada | `[ACTUAL]` |

---

## 4. Superficies y capacidades del producto

Etiquetas de estado: `[ACTUAL]` = verificado hoy; `[OBJETIVO]` = acordado, pendiente; `[PROPUESTO]` = requiere decisión.

| Superficie / capacidad | Estado | Qué es hoy / qué se busca |
|---|---|---|
| Carga/importación de mundos OKF | `[ACTUAL]` pipeline de importación (sync_lore, graph) · `[OBJETIVO]` adaptadores formales de validación/normalización OKF | Importa archivos del mundo e indexa; el contrato OKF formal es decisión abierta (sección 10) |
| Wiki / editor | `[ACTUAL]` | CRUD gated (create/save/restore), diff, papelera (`.papelera`, TTL 30 días), snapshots de historial, estados OKF (`draft`/`stable`) |
| Grafo de entidades | `[ACTUAL]` | `graph_search/read/links/status`, MCP server (10+ tools), resolución de referencias nombradas |
| Asistente IA | `[ACTUAL]` | Chat + `ai/ask` + SSE (`ai/ask/activity`) con gate semántico Hermes-first; sugerencias de edición (`ai/edit-suggest`). El nombre visible del asistente es **Asistente de Demiurgos**; Hermes es solo el proveedor conversacional interno (decisión G15) |
| Contexto acotado | `[ACTUAL]` | `SemanticContext` limita claves a `mundo/ficha/reference/graph`; evidencia server-verificada; sin rutas internas ni provenance |
| Creación guiada de personajes | `[ACTUAL]` | Protocolo `guided-character-v1`, fases `confirmation→conversation→review→complete`, propuesta diskless, gate de mínimos, persistencia gated, reindex |
| Skills narrativas | `[ACTUAL]` 14 skills `narrative-*` como herramientas estáticas del orquestador · `[OBJETIVO]` biblioteca gestionada por el Autor (ver iniciativa) | Las skills guían fases; el runtime guiado NO las carga dinámicamente hoy |
| Plantillas/catálogos | `[ACTUAL]` | Catálogos narrativos en `plantillas/` con `_catalog.json` |
| Búsqueda/índice | `[ACTUAL]` | Search del grafo + `lore_search`; indexado vía sync_lore y `ReindexCoordinator` |
| Persistencia y revisión | `[ACTUAL]` | Pipeline de escritura gated (confirmación digest+token), papelera, historial |
| Memoria persistente | `[ACTUAL]` | Engram (MCP): `mem_save/search/context`; obligatoria para co-creación |
| Imágenes | `[ACTUAL]` subida de media + `image_indexer` + proveedor de visión + `nanobanana` · `[PROPUESTO]` flujos de imagen de personaje profundos | No es objetivo de la iniciativa de skills; profundidad es decisión abierta (sección 10) |
| Configuración/instalación | `[ACTUAL]` | onboarding + Centro de Configuración (en el Perfil de la wiki, `/perfil`; sin página/ruta independiente); wizard legacy `web-config-ui` retirado (histórico, solo referencia) |
| Workflows narrativos | `[ACTUAL]` | Orquestador AGENTS.md + máquina de fases + `.demiurgos-estado.json` |
| Captura de ideas | `[ACTUAL]` | Ingesta nativa (`idea_capture`), entrada Telegram; el legacy batch sync está archivado/retirado |
| Navegación por talleres | `[OBJETIVO]` | Navbar modular con **solo los talleres disponibles**; el MVP arranca con el Core (Taller de Herramientas + Taller de Mundo) y los módulos de pago futuros aparecen como teaser "Próximamente" en el centro (Visuales, Planificación, Rol, Escritor, GameDesigner); Taller de Publicación siempre como último elemento a la derecha cuando exista. Contrato del Taller de Herramientas: `docs/architecture/tool-workshop.md` · Contrato del Taller de Mundo: `docs/architecture/world-workshop.md` |
| Exportar ficha a PDF | `[OBJETIVO]` | Permanecerá en el **Core**: exporta la ficha como PDF (datos/backup). No es un módulo de pago |
| Taller de Publicación | `[OBJETIVO — módulo de pago]` | Publica **artefactos** (no datos/backup) con perfiles por módulo; es un módulo de pago único y se distingue de la exportación de ficha (ver decisión G12) |
| Onboarding | `[OBJETIVO]` | Primer arranque: idioma, modelos LLM e importar/crear mundo; la carpeta sincronizada de Google Drive es no bloqueante; el árbol espejo por taller se escribe en esa carpeta; sync 30 s tras editar; restauración Google→Demiurgos (ver decisión G11) |
| Licencias y activación | `[OBJETIVO]` | Compra única por módulo; activación 1 Windows + 1 macOS + 1 Linux + 1 servidor/VPS con transferencia; actualizaciones incluidas 1 año; renovación colaborativa opcional; la versión instalada nunca se bloquea (ver decisión G9) |

---

## 5. Fronteras de dominio y autoridad de escritura

`[DECISIÓN CERRADA]` — Reglas sagradas de escritura:

| Dominio | Incluye | Puede escribir |
|---|---|---|
| **Planner** | explore, propose, world-spec, character-spec, design, tasks | NADA a archivos; solo Engram |
| **Writer** | outline, draft, revise | SOLO `mundos/{mundo}/sagas/` |
| **Validator** | verify, archive | SOLO `mundos/{mundo}/Lore/CHANGELOG.md` |
| **Backend (escrituras wiki/guided)** | create/save/restore de fichas y lore | SOLO vía rutas gated con digest + token; nunca bypass |

**La frontera Hermes (regla sagrada, `[DECISIÓN CERRADA]`):**

- **NO tiene autoridad de escritura**: nada persiste hasta la aprobación explícita del Autor sobre una propuesta diskless.
- **NO otorga permisos**: cualquier clave de autoridad (`target`, `digest`, `revision`, `authority`, `reference`, `acceptance`, `accepted_canon`, `authorization`) dentro de un envelope invalida el envelope completo (fail-closed).
- **NO puede saltarse las compuertas del servidor**: la persistencia, el diff y la autorización se resuelven íntegramente en rutas backend que Hermes no selecciona ni controla.
- **Sí es el intérprete semántico y la voz**: la intención natural se convierte en estado solo a través del prompt del gate semántico; la clasificación léxica es secundaria y solo se consulta tras un envelope semántico válido.
- **`[DECISIÓN CERRADA]` Intención semántica**: el Autor se expresa libremente y **Hermes determina la intención semántica**. El backend valida el envelope, resuelve referencias y ensambla contexto verificable, pero **no redacta síntesis narrativas ni decide/inventa relaciones**.
- **`[DECISIÓN CERRADA]` Co-creación de skills**: Hermes conversa y redacta la propuesta; Demiurgos valida/compila y protege el kernel; el Autor aprueba la publicación. Hermes no escribe ni decide canon (ver G13).

---

## 6. Contrato de mundo/OKF

- Un **mundo** es un directorio `mundos/{mundo}/` con subdirectorios canónicos (`lore/`, `personajes/`, `sagas/`, y otros como `referencias/`, `ideas/`, `wiki/`). `[ACTUAL]`
- Los **archivos OKF** son Markdown con frontmatter YAML que declara identidad y estado (`type`, `id`, `title`, `status`, etc.); el indexador de grafo los parsea y excluye no-OKF, prefijos `_` y directorios excluidos. `[ACTUAL]`
- Los **estados de ficha OKF** observados son `draft`/`stable`. `[ACTUAL]`
- **[DECISIÓN CERRADA]** Demiurgos definirá un **contrato OKF mínimo v1**, versionado y extensible, suficiente para que importación, almacenamiento, grafo, editor, API y skills compartan una interpretación estable sin bloquear la evolución completa del estándar.
- **[DECISIÓN CERRADA]** El contrato mínimo v1 prioriza dos ejes: (1) la **identidad** de la entidad y (2) las **convenciones de relación** (wikilinks `[[Nombre]]` y/o campos de relación en frontmatter) para que el grafo interconecte entidades de forma estable. También define **mínimos por tipo de entidad** (`required_minimums`), con **personaje primero** (ver G1).
- **[OBJETIVO]** El contrato mínimo v1 cubrirá, como mínimo, mundo, entidades, lore, personajes, relaciones, metadatos, referencias y estado de validación. La especificación campo por campo y sus reglas de compatibilidad se definirán antes del SDD que implemente el validador OKF.
- Hasta que ese contrato mínimo esté implementado, los **adaptadores validan y normalizan** cualquier entrada contra las reglas que el pipeline actual conoce, sin inventar campos ni romper mundos existentes. Esta conducta es transitoria respecto del contrato OKF objetivo. `[ACTUAL]`
- **Regla anti-acoplamiento**: ningún mundo concreto (p. ej. Vibrantes) puede entrar en el código de plataforma como requisito; los mundos son datos, no arquitectura. `[DECISIÓN CERRADA]`

---

## 7. Reglas de arquitectura para implementación, testing y proveedores

### 7.1 Implementación

- Toda escritura a canon pasa por las **compuertas existentes** (`/api/{mundo}/{section}/create|save`, confirmación con digest + token de un solo uso). Prohibido crear rutas de escritura sin gating. `[DECISIÓN CERRADA]`
- El **grafo es la fuente de verdad para leer entidades**; el filesystem queda prohibido para consultas de entidades. `[DECISIÓN CERRADA]`
- Las **sesiones se ligan a `authorization_binding`** y toda mutación verifica revisión vigente (concurrencia optimista). `[DECISIÓN CERRADA]`
- Los **proveedores de IA son no confiables y acotados**: envelopes estrictamente validados, contexto server-verificado, fail-closed sin fallback léxico autónomo. `[DECISIÓN CERRADA]`
- La **metodología creativa es contenido**, no código: los rieles de seguridad (kernel) son del servidor; la guía creativa vive en skills editables. `[DECISIÓN CERRADA]`
- **Progressive disclosure** en toda superficie: esencial primero, detalle después. `[DECISIÓN CERRADA]`
- La **activación de skills no modifica `AGENTS.md`**; el orquestador narrativo permanece como artefacto estático, nunca como contrato reescrito dinámicamente. `[DECISIÓN CERRADA]`
- Copia visible **localizada** (`DEMIURGOS_LANGUAGE`) y que **nunca exponga términos internos** de proveedor. `[ACTUAL]`

### 7.2 Testing

- Invariantes de seguridad (`cero escrituras sin aprobación`, `apply_delta` no toca `accepted_canon`, revisión+autorización antes de mutación, gate fail-closed, targets allowlist, digest server-side, token de un solo uso) **siempre con pruebas**. `[ACTUAL — wiki/tests]`
- Ramas de fallo de cada flujo guiado cubiertas en tests unitarios y e2e. `[ACTUAL — tests wiki]`
- Cualquier cambio que toque invariantes debe mantener o extender esas pruebas; no se eliminan pruebas para "hacer pasar" un cambio.

### 7.3 Abstracción de proveedores

- Configuración **unificada** texto/visión (`DEMIURGOS_TEXT_*`, `DEMIURGOS_VISION_*`); añadir un proveedor = cambiar endpoint/modelo/clave, sin tocar componentes. `[ACTUAL]`
- Hermes se integra como **proveedor conversacional acotado** (runs adapter + gate semántico + adaptador guiado); su contrato es el envelope JSON estricto. `[ACTUAL]`
- Cambiar de proveedor **nunca** altera las invariantes de escritura ni las compuertas. `[DECISIÓN CERRADA]`

---

## 8. Mapa actual del repositorio y brechas conocidas

### 8.1 Mapa `[ACTUAL]`

| Ruta | Rol |
|---|---|
| `frontend/` | React + Vite + Vitest: wiki, editor, asistente, creación guiada, language UI, semantic intent client |
| `src/tools/demiurgos-suite/wiki/` | Backend API (FastAPI): `api_server.py`, `graph_indexer.py`, `graph_models.py`, `graph_mcp_server.py`, `guided_character_{protocol,domain,persistence,provider}.py`, `semantic_intent.py`, `assistant_activity.py`, `assistant_settings.py`, `demiurgos_language.py`, `idea_capture_ui.py`, `hermes_runtime.py`, `mcp_adapter.py` |
| `src/tools/sync_lore/` | Pipeline de indexado de lore (35 tests) |
| `src/tools/idea_capture/` | Captura nativa de ideas |
| `src/tools/engram_sync/` | Worker de sincronización de Engram |
| `src/tools/web-config-ui/` | Wizard legacy de configuración — retirado, solo referencia histórica |
| `skills/` | 14 skills narrativas `narrative-*` + skills legacy `.md` (`crear_personaje.md` como referencia histórica) |
| `plantillas/` | Catálogos narrativos universales (`_catalog.json`) |
| `AGENTS.md` / `Agente_Maestro.md` | Orquestador narrativo / reglas maestras de la IA |
| `mundos/{mundo}/` | Mundos cargados en OKF |
| `.demiurgos-estado.json` | Seguimiento de arcos (gitignored) |
| `config/`, `scripts/`, `install.sh` | Configuración, utilidades, instalador |

### 8.2 Brechas conocidas (separadas del objetivo)

| Brecha | Detalle | Estado |
|---|---|---|
| Runtime guiado con prompts hardcodeados | `guided_character_provider.py` y `semantic_intent.py` mantienen el contrato builtin como driver actual; el compilador/biblioteca/cuarentena existen, pero el cableado de la metodología compilada al provider/gate queda para Phase 3 | `[ACTUAL]` — contrato builtin activo; puente compilado→runtime `[OBJETIVO]` (ver iniciativa) |
| Biblioteca de metodologías | Versionado inmutable, activación por mundo, rollback y borrado recuperable (`methodology_library.py`); import/export `.zip` con checksum, cuarentena y firma oficial aditiva (`methodology_trust.py`) | `[ACTUAL]` (ver iniciativa) |
| Persistencia de sesiones durable | `GuidedSessionStore` es durable (SQLite); TTL 30 días, snapshot de metodología pinneado, tokens/autorizaciones efímeros y no heredables; propuestas pendientes se re-piden | `[ACTUAL]` — modelo híbrido G2 implementado |
| Contrato OKF mínimo v1 | Identidad, wikilinks/relaciones, estado y mínimos por tipo (personaje primero) validados por `okf_contract.py`; sin acoplamiento a mundo | `[ACTUAL]` (ver iniciativa) |
| Modelo de autorización de amplio alcance | Hoy `local-dev session` (cookie HttpOnly, mismo origen); la arquitectura queda preparada para multiusuario, pero la implementación inicial sigue siendo monousuario/local | `[OBJETIVO]` |
| Inicio de sesión visible al arrancar | La sesión local se consulta actualmente desde el perfil; falta el popup/modal automático al abrir la aplicación | `[OBJETIVO]` — contrato G3 |
| Indexado tras escrituras | `ReindexCoordinator` reconcilia por operación; no hay indexador de fondo global | `[ACTUAL]`; servicio de fondo es decisión abierta |

---

## 9. No-objetivos y reglas anti-acoplamiento

### 9.1 No-objetivos

- NO es una plataforma para un mundo concreto (Vibrantes es un mundo de ejemplo). `[DECISIÓN CERRADA]`
- NO es un sustituto de un proveedor de IA; la plataforma es agnóstica de proveedor. `[DECISIÓN CERRADA]`
- NO persiste sin aprobación explícita; no existe "escritura automática de IA". `[DECISIÓN CERRADA]`
- NO implementa todavía colaboración multiusuario completa ni RBAC/SSO; la arquitectura debe conservar ownership, workspace, world, principal y permisos como extensiones futuras. `[OBJETIVO]`
- NO promete superficies inexistentes como `[ACTUAL]`; todo lo no verificado se etiqueta objetivo/propuesto. `[regla del documento]`

### 9.2 Anti-coupling

| Regla | Detalle |
|---|---|
| **Mundos no son código** | Prohibido importar lore de un mundo en la plataforma como lógica |
| **Skills no son código del servidor** | La metodología editable nunca se compila a lógica de autorización |
| **Hermes no es la plataforma** | Es un proveedor; su fallo degrada la conversación, no la arquitectura |
| **El documento global no repite la iniciativa** | Decisiones de iniciativa viven en su contrato; el global las referencia |
| **Sin doble fuente de verdad** | Un hecho se declara en un solo documento; los demás referencian |

---

## 10. Decisiones globales de la plataforma

Estas decisiones pertenecen a la **plataforma completa** (no al Taller de Herramientas; las técnicas del subsistema están en `skill-library-and-guided-character-creation.md`, sección 16, y las de superficie del Taller en `tool-workshop.md`, sección 9). Las decisiones ya confirmadas se marcan como cerradas; las restantes requieren aprobación explícita del Autor:

| ID | Decisión | Opciones/Propuesta |
|---|---|---|
| **G1** | Estrategia del contrato OKF | **[DECISIÓN CERRADA]** Definir un contrato OKF mínimo v1, versionado y extensible, priorizando **identidad** de la entidad y **convenciones de relación** (wikilinks/campos de relación) para que el grafo interconecte, además de **mínimos por tipo de entidad** con **personaje primero**. El detalle campo por campo y las reglas de compatibilidad se especificarán antes del SDD del validador; mientras tanto, los adaptadores validan/normalizan de forma tolerante |
| **G2** | Durabilidad de sesiones y confirmaciones | **[DECISIÓN CERRADA]** Persistencia híbrida: se reanudan conversaciones tras reinicio y las propuestas pendientes se **re-piden** (revalidan o regeneran); los tokens y autorizaciones de escritura siguen siendo efímeros, revalidables y no heredables. Las sesiones abandonadas/reanudables se conservan durante **30 días**; después se descartan |
| **G3** | Modelo de autorización | **[DECISIÓN CERRADA]** Arquitectura preparada para multiusuario (ownership/workspace/world/roles/permisos), con implementación inicial monousuario/local. El Core es gratuito y los módulos usan entitlements de compra única; Skool queda separado como comunidad y canal de descuentos, no como autoridad de acceso o escritura |
| **G4** | Indexado de fondo | `ReindexCoordinator` por operación vs servicio/indexador de fondo global con watch |
| **G5** | Alcance de flujos de imagen | Subida/media + `image_indexer` + visión actuales vs generación/regeneración profunda de imágenes de personaje |
| **G6** | Rol de Engram como memoria de plataforma | Registro de co-creación vs fuente de contexto de búsqueda; sincronización con el worker `engram_sync` |
| **G7** | Idioma de UI en runtime | `DEMIURGOS_LANGUAGE` estático actual vs cambio dinámico con persistencia (el frontend ya tiene `useAppLanguage`) |
| **G8** | Instalación/despliegue | **[DECISIÓN CERRADA]** *(2026-10-02)* Instalación **local de un solo comando**: canal público de artefactos precompilados, `uv` + ruedas binarias (sin compilador), sin permisos de administrador, launcher portable y rollback acotado a la versión anterior. **Docker queda como canal paralelo futuro, no como canal principal** (rompería la promesa de un solo comando y exigiría privilegios). Esta decisión **supersede #2330** (ejecutables nativos, diferidos): la distribución *source-visible* con `uv` + wheels es el enfoque vigente. Detalle en `docs/install/` y `docs/architecture/INSTALL_LAYOUT.md` |
| **G9** | Modelo de licencias y activación | **[DECISIÓN CERRADA]** Módulos de **pago único**; la compra incluye **actualizaciones durante 1 año**; la **renovación colaborativa** es opcional y posterior; la **versión instalada nunca se bloquea**. La activación es **por plataforma**: 1 Windows + 1 macOS + 1 Linux + 1 servidor/VPS, con transferencia. Los cobros son agnósticos de proveedor (Stripe/Binance futuros) y los **descuentos se calculan en Demiurgos**, no en el proveedor |
| **G10** | Alcance del MVP | **[DECISIÓN CERRADA]** El MVP entrega solo el **Core**: Taller de Herramientas + Taller de Mundo. Los 6 módulos de pago (Visuales, Planificación, Rol, Escritor, GameDesigner, Publicación) van después |
| **G11** | Onboarding y respaldo | **[DECISIÓN CERRADA]** El onboarding configura idioma, modelos LLM e importar/crear mundo; la **carpeta sincronizada** de Google Drive es **no bloqueante**; el **árbol espejo por taller** se escribe en esa carpeta; hay **sync 30 s tras editar** y **restauración Google→Demiurgos**. El cliente de sincronización queda fuera de esta arquitectura y lo elige el operador |
| **G12** | Exportar vs publicar | **[DECISIÓN CERRADA]** "Exportar ficha a PDF" permanece en el **Core** (datos/backup). El **Taller de Publicación** completo es módulo de pago con **perfiles por módulo**. Se distingue **exportar** (datos/backup) de **publicar** (artefactos) |
| **G13** | Skill Madre (capacidad protegida) | **[DECISIÓN CERRADA]** Capacidad protegida **instalada obligatoriamente con Demiurgos**: no editable ni eliminable, **invisible en el árbol de skills**, **no desactivable**, se actualiza solo mediante **releases oficiales** y sirve para **co-crear nuevas skills**. Contrato en 10.5; el ciclo de vida de la biblioteca gestionada por el Autor vive en la iniciativa |
| **G14** | Clasificación y autoridad de Skills | **[DECISIÓN CERRADA]** La UI muestra tres categorías: **Oficiales** (solo creadas/aprobadas y firmadas por el Autor de Demiurgos), **Personalizadas** (creadas o derivadas por el Autor) y **Comunitarias** (creadas/compartidas por la comunidad). `fundacional`, `derived`, `co-created`, `verified` y `quarantined` son atributos secundarios; la Skill Madre queda fuera de estas categorías visibles. **Dos ejes:** el atributo `fundacional` solo puede acompañar a `Oficiales` (fundacional⇒Oficiales); la protección de no-eliminación se ancla en el atributo, no en la categoría — un `Oficiales` firmado sin `fundacional` seguiría siendo eliminable. El sembrado de skills fundacionales está implementado (mecanismo en el adendum 8.1 del contrato del Taller de Herramientas) |
| **G15** | Identidad y comportamiento del asistente | **[DECISIÓN CERRADA]** El nombre visible del asistente de la plataforma es **Asistente de Demiurgos**; "Hermes" queda como nombre interno del proveedor conversacional y no se expone en la copia visible. El asistente es **creativo, imaginativo y adaptable dentro de un marco**: plantea propuestas y el **Autor decide**; distingue explícitamente entre **regla, recomendación y posibilidad**; ante una recomendación importante ofrece **una única reconsideración** y luego respeta la decisión del Autor. Contrato en 10.6 |

### 10.1 Contrato de la decisión G2 `[DECISIÓN CERRADA]`

La sesión guiada podrá recuperarse después de un reinicio, pero recuperar la conversación **no** recupera automáticamente la autoridad de escritura:

- Se persisten mensajes, candidato, propuestas, fase, revisión, referencias autorizadas y snapshot de skill.
- Todo token de confirmación, digest operativo o autorización de escritura se considera efímero.
- Tras un reinicio, una propuesta pendiente debe revalidarse o regenerarse antes de crear o guardar.
- Nunca se reutiliza automáticamente un token emitido antes del reinicio, expiración o cambio de revisión.
- La recuperación respeta `authorization_binding`, revisión optimista y el TTL de **30 días** para sesiones abandonadas.
- Una sesión obsoleta, corrupta o no autorizada falla cerrado sin escribir.

### 10.2 Contrato de la decisión G3 `[DECISIÓN CERRADA]`

Demiurgos se implementa inicialmente para un **Autor local**, pero sus límites de autorización deben quedar preparados para evolucionar a colaboración multiusuario:

- La primera etapa mantiene una instalación/local session y un principal principal, sin exigir cuentas, equipos ni RBAC completo.
- El modelo de recursos debe poder incorporar `owner`, `workspace`, `world`, `created_by`, `updated_by`, `visibility` y roles sin romper `authorization_binding` ni las rutas gated.
- La colaboración futura se organiza alrededor de workspaces y mundos compartidos, no alrededor de una identidad global de Hermes.
- Skool no es el sistema de identidad de Demiurgos ni el servidor de distribución de software: es la comunidad que autoriza mediante API el entitlement de actualización. Pertenecer activamente a la comunidad puede habilitar que Demiurgos descargue actualizaciones desde GitHub u otro servicio de release, pero nunca concede permisos locales de lectura, activación o escritura.

### 10.3 UX de autenticación al iniciar `[OBJETIVO]`

La autenticación no debe depender de que el Autor recuerde abrir manualmente el menú de perfil:

- Al abrir Demiurgos, el frontend consulta el estado de sesión antes de habilitar acciones protegidas.
- Si la autenticación está habilitada y no existe una sesión válida, la UI abre automáticamente una ventana emergente/modal de inicio de sesión.
- La ventana debe explicar por qué se requiere autenticación y conservar la ruta, mundo o acción que el Autor intentaba usar.
- Tras autenticarse, la UI revalida la sesión y reanuda la superficie protegida sin obligar al Autor a navegar de nuevo.
- Si el Autor cierra la ventana, el workspace puede permanecer visible en modo limitado, pero el asistente, las escrituras, la configuración y las acciones protegidas deben mostrar un estado accionable de autenticación pendiente, nunca un bloqueo silencioso.
- La primera implementación puede usar el flujo local; el mismo contrato debe permitir una futura ventana OAuth/SSO sin acoplar Skool a la autorización local.

### 10.4 Contrato de la decisión G9 — licencias, activación y cobros `[DECISIÓN CERRADA]`

- **Pago único**: cada módulo se compra una sola vez; no hay suscripción recurrente por taller ni por uso.
- **Actualizaciones incluidas 1 año**: la compra de un módulo incluye las actualizaciones durante un año desde la adquisición.
- **Renovación colaborativa opcional**: después del año, el Autor puede renovar el acceso a actualizaciones como gesto colaborativo a la comunidad; es opcional y no condiciona el uso del software ya instalado.
- **La versión instalada nunca se bloquea**: la caducidad del acceso a actualizaciones no desactiva, degrada ni bloquea la versión instalada; el software sigue funcionando con la versión que el Autor tiene.
- **Activación por plataforma**: una misma licencia cubre 1 Windows + 1 macOS + 1 Linux + 1 servidor/VPS, con mecanismo de **transferencia** entre dispositivos.
- **Cobros agnósticos de proveedor**: los cobros pueden servirse desde cualquier proveedor (p. ej. Stripe o Binance, ambos futuros) sin acoplar la arquitectura a uno; los **descuentos se calculan en Demiurgos**, no en el proveedor.
- **Skool no es autoridad de acceso, identidad ni escritura**: solo canal de comunidad, descuentos por antigüedad y (en el futuro) entitlement de actualización; nunca concede permisos locales.

### 10.5 Contrato de la decisión G13 — Skill Madre `[DECISIÓN CERRADA]`

- **Instalación obligatoria**: la Skill Madre se instala junto con Demiurgos como parte del Core; no requiere activación del Autor.
- **Protección**: no es editable ni eliminable desde el Taller de Herramientas; **no es visible en el árbol de skills** y **no puede desactivarse**; no pertenece a la biblioteca gestionada por el Autor ni puede ser reemplazada por un borrador.
- **Actualización solo por releases**: sus cambios llegan exclusivamente mediante **releases oficiales** de la plataforma; no se actualiza vía importación de paquetes (ver G13 y contrato de la Skill Madre).
- **Propósito**: co-crear nuevas skills junto al Autor; el flujo de co-creación y su UX viven en el contrato de superficie del Taller de Herramientas (`docs/architecture/tool-workshop.md`, sección 6).
- **Co-creación**: Hermes conversa y redacta la propuesta; el backend valida/compila y protege el kernel; el Autor aprueba la publicación. Hermes no escribe ni decide canon (sección 5).
- **Ritmo conversacional**: toda skill conversacional hace **una sola pregunta por turno**; la Skill Madre crea una **primera versión en 15–20 preguntas máximo** (adaptativas) y el progreso se reporta **por hitos, no por porcentaje** (ver contrato de superficie del Taller de Herramientas, `docs/architecture/tool-workshop.md`).

### 10.6 Contrato de la decisión G15 — Asistente de Demiurgos `[DECISIÓN CERRADA]`

- **Nombramiento visible**: el asistente que el Autor ve en toda la plataforma se llama **Asistente de Demiurgos**. "Hermes" es el identificador interno del proveedor conversacional y **nunca aparece como nombre visible** en la UI ni en la copia localizada.
- **Personalidad de servicio**: creativo, imaginativo y adaptable **dentro de un marco** (el kernel y los rieles del sistema); no improvisa fuera de esos límites.
- **El Autor decide**: el asistente **plantea** propuestas, opciones y preguntas; la decisión final (aprobar, rechazar, ajustar) es siempre del Autor.
- **Regla / recomendación / posibilidad**: el asistente distingue explícitamente qué es **regla** (impuesta por el canon o el sistema), qué es **recomendación** (su juicio) y qué es **posibilidad** (una opción abierta).
- **Reconsideración acotada**: ante una **recomendación importante**, el asistente ofrece **una única reconsideración** (reformular o insistir una vez) y después respeta la decisión del Autor; no insiste en bucle ni repite preguntas sin nuevo material.
- **Aplicación**: esta identidad rige la copia visible de todas las superficies conversacionales; el comportamiento por-turno de las skills y el diseño UX de co-creación se detallan en el contrato de superficie del Taller de Herramientas (`docs/architecture/tool-workshop.md`, sección 6).

---

## 11. Definition of ready para SDD/tools futuros

Un SDD o herramienta de esta plataforma **solo** puede comenzar cuando se cumplan todos:

- [ ] Se leyeron esta constitución y el contrato de la iniciativa relevante (ver sección 0).
- [ ] Se verificó el runtime real (CodeGraph/tests) antes de asumir cualquier `[ACTUAL]`.
- [ ] Las decisiones abiertas que tocan el cambio (sección 10 y/o de la iniciativa) están resueltas y anotadas.
- [ ] El cambio respeta las invariantes `[ACTUAL]` (secciones 5, 7) y las fronteras de dominio.
- [ ] Todo comportamiento nuevo se etiqueta `[ACTUAL]`/`[OBJETIVO]`/`[PROPUESTO]` y no se presenta como implementado.
- [ ] El SDD declara explícitamente qué NO toca (AGENTS.md, skills, lore/personajes fuera de escritura gated) si aplica.
- [ ] Las pruebas cubren las invariantes afectadas y las ramas de fallo relevantes.

---

## 12. Iniciativas y documentos relacionados

| Documento | Rol | Relación |
|---|---|---|
| `docs/architecture/skill-library-and-guided-character-creation.md` | Contrato de la iniciativa **biblioteca de skills + creación guiada de personajes** (subsistema técnico) | Subordinado a este documento; define el alcance técnico, paquete/manifest, ciclo de vida, flujo guiado, decisiones 16.x y aplica la gobernanza de la Skill Madre (G13) sin duplicarla |
| `docs/architecture/tool-workshop.md` | Contrato de **superficie/producto del Taller de Herramientas** | Subordinado a este documento; define el selector/árbol, estados de Skills, categorías, biblioteca global, Skill Madre protegida y la co-creación (decisiones TW1–TW19), sin duplicar el subsistema técnico |
| `docs/architecture/world-workshop.md` | Contrato del **Taller de Mundo** (subsistema del Core) | Subordinado a este documento; define el ámbito, secciones, Borrador vs Canon, relaciones y su frontera con el futuro Taller de Narrativa |
| `docs/architecture/foundational-research-skill.md` | Contrato de la **Skill Fundacional de Investigación** (skill transversal del Core) | Subordinado a este documento; define el núcleo de investigación externa (ramas Descubrimiento/Verificación, flujo, procedencia, estados de worldbuilding y comparación con Canon) sin duplicar la constitución ni los contratos de Taller |
| `docs/architecture/skill-runtime-consumption-contract.md` | Contrato de **consumo de skills en runtime** (activación por flujo, enrutamiento/inyección, adjuntos `skill@version`, ejes de vocabulario) | Subordinado a este documento; norma cómo el runtime consume las Skills del subsistema técnico (SR1–SR6) sin duplicar la constitución, la biblioteca ni la superficie |
| `AGENTS.md` | Orquestador narrativo (rol dentro de la plataforma) | Define el subsistema de fases narrativas y sus límites de escritura |
| `README.md` | Visión y estructura del proyecto | Fuente de referencia, no reemplaza estos contratos |
| `Agente_Maestro.md` | Reglas maestras de la IA en co-creación | Complementa los principios del canon |

> **Regla final:** cuando este documento y la iniciativa entren en conflicto, prevalece este documento (constitución global); toda contradicción se reporta al Autor para resolución.
