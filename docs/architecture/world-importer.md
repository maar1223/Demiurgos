# Importador de Mundo — Contrato de Producto y Arquitectura

> **Contrato de producto/arquitectura.** Este documento es el resultado de una **auditoría documental** del estado real del repositorio en torno a la "importación" de contenido a un mundo, y el contrato de partida para definir qué debe ser el **importador de mundo** de Demiurgos. **No es un artefacto SDD**: describe qué existe hoy y qué debería cumplir el importador, sin prescribir implementación hasta que las decisiones abiertas estén resueltas. Toda afirmación lleva la etiqueta de estado correspondiente; lo que no está etiquetado `[ACTUAL]` no debe presentarse como existente. El **contrato de superficie y UX** del importador vive en `docs/architecture/world-importer-ui.md`; este documento lo referencia sin duplicarlo.

| Campo | Valor |
|---|---|
| Estado | Contrato de producto/arquitectura (auditoría documental; diseño objetivo para el importador) |
| Versión del documento | 1.1 |
| Fecha | 2026-08-17 |
| Autor | Demiurgos (orquestación) |
| Idioma | Español neutro (prosa técnica) |
| Alcance | Importador de mundo: vocabulario y ciclo (análisis/indexación/importación), fuentes de verdad efectivas, rol de `lore-index.json` vs grafo OKF, contratos de datos/estados, invariantes, seguridad, idempotencia, rollback, no-objetivos, pruebas/documentación y decisiones abiertas |
| Depende de | `docs/architecture/demiurgos-platform.md` (constitución global del producto) |
| Relación con SDD | Requisito previo. Ningún SDD de implementación del importador debe comenzar sin este contrato aprobado, el de superficie (`world-importer-ui.md`) y sus decisiones abiertas resueltas |
| Documentos relacionados | `docs/architecture/demiurgos-platform.md`, `docs/architecture/world-importer-ui.md` (contrato de superficie y UX), `docs/architecture/world-workshop.md` (Taller de Mundo — canon, propuestas y conflictos), `docs/architecture/skill-library-and-guided-character-creation.md` (subsistema técnico — `okf_contract.py`), `docs/architecture/foundational-research-skill.md` (investigación — vía de entrada de información externa), `AGENTS.md` (orquestador narrativo), runtime en `src/tools/sync_lore/` y `src/tools/demiurgos-suite/wiki/` |

## Leyenda de etiquetas

| Etiqueta | Significado |
|---|---|
| `[ACTUAL]` | Comportamiento que existe hoy en el repositorio y está verificado |
| `[OBJETIVO]` | Comportamiento objetivo acordado, no necesariamente implementado aún |
| `[PROPUESTO]` | Diseño propuesto; requiere decisión antes de ser contrato |
| `[DECISIÓN ABIERTA]` | Punto sin resolver que requiere aprobación explícita del Autor |
| `[DECISIÓN CERRADA]` | Decisión ya aprobada; no debe revertirse sin nuevo acuerdo explícito |

---

## 0. Relación con la constitución y los contratos existentes

- La **definición global del producto** (principios, conceptos canónicos, fronteras de dominio y decisiones G1–G15) vive en `docs/architecture/demiurgos-platform.md`. **Este documento no la duplica.**
- El **gobierno de canon** (Borrador vs Canon, propuestas y conflictos; W3–W5, W11), el **árbol físico del mundo propiedad del Autor** y la distinción de **carpetas del sistema** (`_context`, `.history`, `.papelera`) viven en `docs/architecture/world-workshop.md`. El importador opera **dentro** de esas reglas y no las redefine.
- El **contrato OKF mínimo v1** (identidad, relaciones, mínimos por tipo) es decisión global cerrada (constitución, G1) y su capa de validación servidor-vive en `src/tools/demiurgos-suite/wiki/okf_contract.py`. El importador debe validar y normalizar contra ese contrato, no contra un duplicado.
- La **restauración desde respaldo** (Google Drive/rclone → Demiurgos) es un flujo distinto: recupera el estado del mundo y la configuración no secreta de una instalación, no analiza documentos ni genera candidatos de contenido. G11 la define como objetivo global; este contrato no la convierte en una modalidad de importación.
- El **asistente visible** se llama **Asistente de Demiurgos**; "Hermes" es el nombre interno del proveedor y nunca aparece en copia visible (constitución, G15/10.6). `[DECISIÓN CERRADA — referencia]`
- En caso de conflicto, prevalece la constitución; la contradicción se reporta al Autor.

---

## 1. Qué existe hoy y qué no existe (separación de responsabilidades)

**Regla de etiquetas:** todo lo listado aquí como `[ACTUAL]` está verificado contra el repositorio en esta auditoría (rutas citadas). Nada de lo `[OBJETIVO]`/`[PROPUESTO]` se presenta como implementado.

### 1.1 Mapa de componentes `[ACTUAL]`

| Componente | Rol hoy | Evidencia |
|---|---|---|
| **Pipeline `sync_lore` (CLI)** | Descubre mundo (variable de entorno `DEMIURGOS_WORLD` o primer subdirectorio de `mundos/`; **no carga `.env`**), escanea `.md`/`.docx`/`.pdf`, convierte, chunkea, extrae entidades/términos/contradicciones con LLM, extrae imágenes con visión, deduplica y detecta contradicciones heurísticas, y escribe `lore-index.json` | `src/tools/sync_lore/cli.py`, `lore_indexer.py`, `index_builder.py`, `image_indexer.py`, `schemas.py`, `utils/world.py`, `utils/chunker.py`, `utils/converter.py`, `providers/` |
| **`publisher.py` (STUB)** | `preview()` y `publish_entities()` **no publican archivos**: devuelven resultados vacíos (todo `skipped`); no tienen consumidores en API ni frontend | `src/tools/sync_lore/publisher.py` (solo exportado en `src/tools/sync-lore/__init__.py`) |
| **`try_engram_save`** | Persistencia best-effort a Engram vía **CLI obsoleta** `engram mem save` por `subprocess`; **falla silenciosamente** (devuelve `False`) cuando el CLI no existe o expira | `src/tools/sync_lore/persistence.py:91` |
| **`lore-index.json`** | Artefacto de salida **huérfano**: **nadie lo consume** en API ni frontend; no alimenta el grafo | `src/tools/sync_lore/persistence.py` `write_lore_index`; ausencia de referencias en `src/tools/demiurgos-suite/wiki/` y `frontend/src/` |
| **`LoreIndexAdapter`** | Adaptador del worker `engram_sync`: lee `lore-index.json` y **sincroniza solo conteos** (`entities`/`terms`/`contradictions`) al topic de Engram `lore/{project}/index`; no puede reconstruir el índice | `src/tools/engram_sync/adapters/lore_index.py` |
| **`EntityGraphIndex`** | **Fuente efectiva de lectura de entidades**: indexa archivos Markdown **OKF directamente** desde `mundos/{mundo}/{lore,personajes,sagas}`, resuelve wikilinks/relaciones (forward/backlinks), cachea en memoria con watcher (`watchdog`) o invalidación por API; expone `search/read/links/status`. **No consume `lore-index.json`** | `src/tools/demiurgos-suite/wiki/graph_indexer.py` (build/update/search/read/links/start_watch), `graph_mcp_server.py`, `api_server.py` |
| **`okf_contract.py`** | Capa servidor-propiedad de validación OKF v1 (identidad, wikilinks/relaciones, mínimos por tipo, personaje primero); consumida por el grafo y **duplicada en parte** por `sync_lore/schemas.py` | `src/tools/demiurgos-suite/wiki/okf_contract.py`; `graph_indexer.py:28`; `sync_lore/schemas.py:312` `normalize_okf_content` |
| **API (FastAPI)** | 4 endpoints REST de grafo (`/api/{mundo}/graph/{search,entity,links,status}`); CRUD de archivos gated; **no existen endpoints de importación** | `src/tools/demiurgos-suite/wiki/api_server.py:2255,2286,2315,2342` |
| **Superficie actual** | `WorldWorkshop` selecciona mundo y redirige a `/wiki/:mundo`; `WikiWorld` muestra tarjetas de secciones (Lore/Personajes/Sagas); `WikiEditor` edita archivos con frontmatter preservado, diff y persistencia gated | `frontend/src/pages/WorldWorkshop.tsx`, `WikiWorld.tsx`, `WikiEditor.tsx` |

### 1.2 Fuentes de verdad efectivas (jerarquía verificada)

```
1. Archivos del mundo (mundos/{mundo}/…)          ← canon y fuente de lectura del grafo
2. Contrato OKF / API (okf_contract.py, endpoints) ← interpretación estable compartida
3. Grafo derivado en memoria (EntityGraphIndex)    ← fuente de lectura de entidades (constitución 7.1)
4. lore-index.json                                 ← huérfano; nadie lo consume
```

### 1.3 Separación impresora: lo que es análisis/indexación vs lo que sería importación `[OBJETIVO]`

| Responsabilidad | Rol deseado | Efecto en archivos del mundo |
|---|---|---|
| **Análisis** (escaneo, conversión, chunking, extracción LLM, imágenes, dedup, contradicciones) | Producir un diagnóstico del contenido de la fuente | **Ninguno** |
| **Indexación** (construir el grafo o un índice consultable) | Hacer consultable lo que ya existe en el mundo | **Ninguno** (deriva de los archivos) |
| **Importación** (persistir contenido de la fuente en el mundo) | Mover contenido a un mundo de forma **aprobada, trazable y reversible** | **Sí**, solo tras aprobación explícita del Autor (ver sección 3) |

### 1.4 Contradicciones documentadas vs runtime `[ACTUAL]`

| Contradicción | Evidencia |
|---|---|
| `AGENTS.md` instruye `python3 src/tools/sync_lore --world . --output .demiurgos-index`, pero **el CLI no define `--world`** (falla con `argparse`) y `--output` apunta a un directorio, no a un archivo | `src/tools/sync_lore/cli.py:183` (`_build_parser`) |
| Documentación anterior describe **5 endpoints** de grafo; en el runtime hay **4** REST (`search`, `entity`, `links`, `status`) | `frontend/src/api/graph.ts`; `api_server.py:2255,2286,2315,2342` |
| Documentos previos presentan el pipeline como **importación implementada** (publisher, API y frontend incluidos), pero `publisher.py` es un stub sin consumidores y no hay API/frontend de importación | `src/tools/sync_lore/publisher.py` |
| `discover_world` lee **solo el entorno**; no carga `.env` (quien lo invoca debe haber cargado el entorno previamente) | `src/tools/sync_lore/utils/world.py:13` |
| Duplicación del contrato OKF: `okf_contract.py` (servidor) vs `normalize_okf_content` en `sync_lore/schemas.py` | `sync_lore/schemas.py:312` |

> Las contradicciones de **documentación** (AGENTS.md y contratos que presenten el importador como implementado) no se corrigen en esta tarea; se registran aquí como evidencia para el SDD/actualización documental futura.

---

## 2. Vocabulario y ciclo (sin confundir análisis/indexación con importación)

**[DECISIÓN CERRADA — IM2]** Para este contrato, los siguientes términos tienen significado fijo:

| Término | Definición | Efecto en el mundo |
|---|---|---|
| **Fuente** | Material de entrada del importador: archivo/carpeta `.md`, `.docx`, `.pdf` o imágenes, dentro o fuera del árbol del mundo | — |
| **Análisis** | Escaneo, conversión, chunking, extracción estructurada (LLM) y detección de imágenes/contradicciones/dedup sobre la fuente | Ninguno (solo produce diagnóstico) |
| **Indexación** | Construir un índice/grado consultable sobre contenido **ya existente** en el mundo (el `EntityGraphIndex` es el caso actual) | Ninguno (derivado) |
| **Normalización** | Convertir contenido de la fuente a la forma **OKF v1** (frontmatter de identidad, wikilinks/relaciones, mínimos por tipo) según `okf_contract.py` | Ninguno hasta que se persista |
| **Ficha** | Archivo OKF de entidad en el mundo (`personajes/`, `lore/`, …) que el grafo puede indexar | Solo vía escritura aprobada |
| **Propuesta** | Candidato diskless (o registro Markdown, W11) de una ficha, relación o dato, pendiente de aprobación del Autor | Ninguno (registro de trabajo, no canon) |
| **Aprobación** | Decisión explícita del Autor que autoriza la persistencia de un candidato | Habilita la escritura |
| **Importación** | **La acción persistente** que introduce contenido de la fuente en el mundo (véase sección 3: qué significa exactamente) | Sí — la única fase con efectos permanentes |

### 2.1 Importación de contenido frente a restauración de instalación `[DECISIÓN CERRADA — IM9]`

| Flujo | Propósito | Resultado |
|---|---|---|
| **Importador de Mundo** | Incorporar contenido nuevo o cambiado desde fuentes seleccionadas | Candidatos revisables, propuestas, borradores o actualizaciones gated |
| **Restaurar desde respaldo** | Recuperar un mundo y su configuración no secreta en otra máquina o después de un formateo | Estado restaurado, grafo reconstruido y servicios pendientes de revalidación |

Google Drive/rclone puede ser una fuente de ambos flujos, pero no comparten semántica: importar analiza contenido; restaurar recupera estado. La restauración nunca debe pasar por el diagnóstico de entidades del importador.

**Ciclo objetivo** (sección 4): `seleccionar fuente → analizar → diagnosticar → revisar → aprobar → importar → resultado/errores`. Análisis e indexación son **de solo lectura**; la importación es la única fase con escritura, y queda **detrás de la aprobación explícita del Autor** (constitución, 1.4 y 9.1).

**[PROPUESTO — IM8]** El importador es **incremental y recurrente**: puede ejecutarse durante todo el ciclo de vida del mundo, no solo durante el onboarding. Cada ejecución compara las fuentes seleccionadas con el contenido ya existente y propone únicamente altas, cambios, duplicados y conflictos detectados; nunca obliga a rehacer la importación completa.

---

## 3. [DECISIÓN CERRADA — IM1/O6] ¿Qué significa "importar"?

Esta fue la decisión central del contrato. El Autor aprobó **O6 — Importar tras aprobación** como significado canónico. Las demás opciones describen capacidades o resultados intermedios, no el significado principal de "importar".

| Opción | Qué hace | Consecuencias | Autoridad | Reversibilidad | Procedencia |
|---|---|---|---|---|---|
| **O1 — Analizar/indexar** | "Importar" = correr análisis + indexación sin escribir nada en el mundo | No hay cambios; el resultado es un diagnóstico/índice consultable | Ninguna escritura | N/A (sin efectos) | Se registra el origen de cada hallazgo |
| **O2 — Copiar archivos** | Copiar la fuente **tal cual** a una carpeta designada del mundo (sin convertir) | Duplica material no OKF dentro del mundo; el grafo lo ignora si no es OKF | Copia física, exige aprobación | Alta (borrado simple, papelera) | Carpeta de origen → destino |
| **O3 — Normalizar a OKF** | Convertir la fuente a archivos **OKF v1** (identidad, mínimos, wikilinks) | Nuevos archivos OKF visibles e indexables; requiere mapeo de tipos y manejo de mínimos faltantes | Escritura gated con aprobación | Media-alta (papelera) | Origen + reglas de normalización |
| **O4 — Crear fichas** | Generar **fichas de entidad** completas en las secciones correctas (`personajes/`, `lore/`, …) | Es la forma más útil y la más invasiva: introduce entidades nuevas en el canon del mundo | Escritura gated con aprobación por ficha | Media (papelera; decisiones ya tomadas al aceptar) | Origen + LLM + aprobación |
| **O5 — Generar propuestas** | El análisis produce **propuestas** (diskless o registros Markdown, W11) en lugar de escrituras directas | Nada entra al canon hasta aprobación; el Autor revisa candidatos uno a uno | Ninguna escritura al canon | N/A | Origen + estado de propuesta |
| **O6 — Importar tras aprobación (flujo por fases)** | Flujo en etapas: fuente → análisis/diagnóstico → revisión → **aprobación** → importación persistente → resultado | Sigue el patrón gated de la plataforma; el Autor decide el destino final de cada candidato | Escritura SOLO tras aprobación explícita (create/save gated o W11) | Media (papelera + registro de job) | Completa: fuente → análisis → aprobación |

### 3.1 Recomendación explícita

**[DECISIÓN CERRADA — IM1/O6]** "Importar" significa **importar tras aprobación** mediante un flujo por fases:

- **Análisis e indexación** (O1) quedan siempre disponibles como acciones de **solo lectura** (diagnóstico), separadas de la importación.
- La **importación persistente** es una **fase explícita, revisada y aprobada** que escribe **fichas OKF (O4) o propuestas (O5)**, nunca escritura directa automática.
- La **copia literal (O2)** y la **normalización (O3)** se presentan como **vistas intermedias opcionales** del diagnóstico, no como el significado de "importar".
- Toda escritura usa las **compuertas existentes** (`create`/`save` gated con digest + token, o registros de propuesta/conflicto W11); el importador **nunca** escribe al filesystem por fuera de ellas.
- Consecuencias, autoridad, reversibilidad y procedencia quedan como en la fila O6 de la tabla.

> Decisión del Autor: `importar` = O6 (flujo por fases con aprobación), con O1 siempre disponible como lectura y O4/O5 como destinos aprobados de la escritura.

---

## 4. Diseño objetivo del importador (no presentado como actual)

Todo lo de esta sección es `[OBJETIVO]`: es diseño acordado, **no** implementación existente.

### 4.1 Flujo por fases

```
seleccionar fuente ──> analizar ──> diagnosticar ──> revisar ──> aprobar ──> importar ──> resultado/errores
      [OBJETIVO]       [OBJETIVO]    [OBJETIVO]      [OBJETIVO]  [OBJETIVO]   [OBJETIVO]    [OBJETIVO]
```

| Fase | Qué produce | Efectos | Compuerta |
|---|---|---|---|
| **1. Seleccionar fuente** | Identifica el material de entrada (carpeta, archivo o paquete) y el mundo de destino | Ninguno | Ninguna (lectura) |
| **2. Analizar** | Escanea, convierte, chunkea y extrae entidades/términos/contradicciones (reutilizando la lógica de `sync_lore`) | Ninguno | Ninguna (lectura) |
| **3. Diagnosticar (dry-run)** | Reporte de qué se **crearía/actualizaría/saltaría**, validación OKF, mínimos faltantes, conflictos con canon, duplicados, estimación de tokens | Ninguno | Ninguna (lectura) |
| **4. Revisar** | El Autor ve los candidatos agrupados (nuevo/actualizado/saltado/conflicto/error) y decide destino (ficha vs propuesta) | Ninguno | Aprobación del Autor (una decisión por paso) |
| **5. Aprobar** | Confirmación explícita con digest + token de un solo uso (patrón gated) | Habilita la escritura | Gated: `create`/`save` existentes o registro W11 |
| **6. Importar** | Escribe fichas OKF o propuestas con procedencia; idempotente (ver sección 8) | **Sí** | Solo las rutas gated existentes |
| **7. Resultado/errores** | Reporte final con éxito/fallo por ítem, reintento y opciones de reversión | Ninguno (post) | — |

### 4.2 Principios de diseño `[OBJETIVO]`

- **Lectura siempre, escritura solo tras aprobación**: análisis e indexación nunca tocan archivos del mundo (constitución, 1.4/9.1).
- **Reutilizar, no duplicar**: la extracción y la validación OKF reutilizan `sync_lore` y `okf_contract.py`; el importador no lleva una tercera copia del contrato.
- **Un solo destino de escritura**: las compuertas gated del backend (`/api/{mundo}/{section}/create|save`) o los registros de propuesta/conflicto (W11); prohibido el bypass por filesystem.
- **Grafo como lectura**: tras importar, el `EntityGraphIndex` se reconcilia (reindex por archivo o watcher); la lectura de entidades sigue viviendo en el grafo.
- **Idempotencia y reversibilidad**: reimportar la misma fuente no duplica fichas; lo importado es deshacible vía papelera (TTL 30 días) o registro del job.
- **Importación incremental**: una importación posterior al arranque compara la fuente con el estado actual del mundo y conserva el historial de ejecuciones, decisiones y resultados por fuente.

### 4.3 Análisis semántico LLM obligatorio (interpretación) `[OBJETIVO]`

El análisis del contenido de la fuente se basa en **interpretación semántica con LLM obligatoria**: el resultado es una interpretación razonada del material, no una transcripción ni una clasificación mecánica.

- **Señales de rutas solo auxiliares**: los nombres de carpetas/archivos de la fuente son **pistas auxiliares**; nunca determinan por sí solos la clasificación de una entidad ni sustituyen el análisis semántico. `[DECISIÓN CERRADA]`
- **Aclaraciones del Autor antes y durante el análisis**: ante ambigüedad o insuficiencia de información, el importador **pide aclaraciones al Autor** (antes y durante el análisis) en lugar de asumir, respetando la regla de progresión (una pregunta por turno, constitución 1.4). `[DECISIÓN CERRADA]`
- **Propuestas con evidencia, confianza y alternativas**: cada clasificación o entidad propuesta se presenta con su **evidencia** (origen trazable), **confianza** y **alternativas** para que el Autor decida con contexto (sección 7.3). `[DECISIÓN CERRADA]`
- **`sin clasificar` cuando se omite**: si una entidad no puede clasificarse, se marca **`sin clasificar`** y se muestra al Autor; **no** se asigna una carpeta o tipo por defecto en silencio. `[DECISIÓN CERRADA]`
- **Tipos semánticos ≠ carpetas**: la clasificación semántica (personaje, lugar, facción…) es **independiente del árbol físico** del mundo; el mapeo de tipos a secciones/destino es configurable y **confirmable por el Autor** sin tocar su estructura (coherente con W10 del Taller de Mundo y la regla de una sola fuente de lectura, IM3). `[DECISIÓN CERRADA]`

---

## 5. Soberanía del Autor, Borrador/Canon, propuestas, conflictos, referencias y procedencia

Estas reglas son **`[DECISIÓN CERRADA]`** porque derivan de la constitución y del Taller de Mundo; el importador opera dentro de ellas sin redefinirlas:

| Regla | Contenido |
|---|---|
| **Soberanía del Autor** | Ningún contenido se convierte en Canon, versión publicada o estado activo sin aprobación explícita (constitución, 1.4). El importador nunca escribe "en frío" |
| **Borrador vs Canon** | El contenido importado **nunca llega como `stable`**: entra como **borrador** (`draft`) o como **propuesta**, y la transición a canon es decisión exclusiva del Autor (W3) |
| **Propuestas** | Los candidatos de importación pueden materializarse como **propuestas** (diskless o registro Markdown W11 con frontmatter YAML); al aceptar una propuesta se actualiza la ficha relacionada y el registro permanece como historial |
| **Conflictos** | El análisis detecta contradicciones (heurística de `sync_lore` y comparación con canon). Los conflictos **no se resuelven en silencio**: se retienen (`conflicts`) y se muestran al Autor para su decisión (W5) |
| **Referencias** | Las referencias nombradas se resuelven por el grafo (search→read→links) como contexto; nunca se inventan entidades al importar (constitución, 7.1) |
| **Procedencia** | Todo ítem importado registra origen trazable (archivo fuente, chunk, ejecución, modelo) y estado de certeza, sin exponer claves de autoridad al Autor ni al proveedor |
| **Contenido del Autor vs carpetas del sistema** | El importador escribe **solo** en secciones de contenido del Autor; **`_context`, `.history` y `.papelera` nunca son destinos de importación** (W10) |

---

## 6. `lore-index.json` vs grafo OKF: relación y decisión abierta

### 6.1 Situación actual `[ACTUAL]`

- El **grafo (`EntityGraphIndex`) es la fuente de lectura de entidades** (constitución, 7.1) y se deriva de los archivos OKF.
- `lore-index.json` es un artefacto de salida de `sync_lore` que **nadie consume**; `LoreIndexAdapter` solo sincroniza conteos.

### 6.2 Regla de no doble fuente de verdad `[DECISIÓN CERRADA — IM3]`

- **El grafo OKF es la fuente de lectura canónica de entidades.** `lore-index.json` **no** se convierte en una autoridad paralela de lectura.
- Cualquier decisión que haga leer entidades desde `lore-index.json` al frontend/API queda **descartada salvo nuevo acuerdo explícito** del Autor.
- `lore-index.json` puede existir solo como **artefacto derivado** (diagnóstico/análisis), nunca como fuente de verdad.

### 6.3 Roles derivados posibles `[PROPUESTO]`

| Rol posible | Descripción | Autoridad |
|---|---|---|
| **Reporte de análisis (dry-run)** | Salida de un diagnóstico de una fuente, previa a importar | Ninguna (lectura) |
| **Caché de análisis por lotes** | Resultado intermedio de un lote de análisis, regenerable desde los archivos | Ninguna (derivada) |
| **Índice de corpus aparte del grafo** | Índice de búsqueda sobre el corpus de texto (no entidades), sin competir con el grafo | Ninguna (búsqueda derivada) |

### 6.4 Reconciliación `[OBJETIVO]`

- El importador (si escribe fichas) **reconcilia el grafo** tras la importación (reindex por archivo o watcher), de forma idempotente.
- Si `lore-index.json` persiste como artefacto derivado, se **regenera desde los archivos del mundo**, nunca se usa para corregirlos ni como origen de lectura.
- **Sin doble fuente de verdad**: un hecho se declara en un solo lugar (constitución, 9.2); los demás lo referencian.

### 6.5 Decisión cerrada `[DECISIÓN CERRADA — IM6]`

El Autor decidió **retirarlo**: eliminar la escritura del CLI y del worker, sin mantener un artefacto huérfano.

El análisis y el dry-run no crearán `lore-index.json`; sus resultados deberán exponerse mediante el contrato del job de importación definido por el SDD.

---

## 7. Contratos de datos y estados

### 7.1 Estado del job de importación `[PROPUESTO]`

```
selección → análisis → diagnóstico → revisión → aprobación → importación → completado
                │            │            │             │           │
                └── fallido ─┴── fallido ──┴── cancelado ─┴── fallido ─┴── con errores
```

| Estado | Significado | Efectos |
|---|---|---|
| `idle` / `source_selected` | Job creado; fuente y mundo elegidos | Ninguno |
| `analyzing` | Pipeline de análisis en curso | Ninguno |
| `diagnosed` | Dry-run disponible (candidatos + validación + conflictos) | Ninguno |
| `reviewing` | El Autor revisa candidatos | Ninguno |
| `approved` | Aprobación explícita con digest + token | Habilita escritura |
| `importing` | Escritura gated en curso | Escritura aprobada |
| `done` | Importación completa (con o sin errores parciales) | Permanente |
| `failed` / `cancelled` | Abortado o cancelado por el Autor | Ninguno/parcial reversible |

### 7.2 Candidatos `[PROPUESTO]`

| Estado del candidato | Significado |
|---|---|
| `new` | Entidad/archivo que se crearía |
| `updated` | Entidad/archivo existente que se actualizaría |
| `skipped` | Duplicado o no aplicable (no se toca) |
| `conflict` | Contradice canon existente (se muestra, no se resuelve solo) |
| `error` | No pudo analizarse/validarse (se reporta con motivo) |

### 7.3 Registro de procedencia `[PROPUESTO]`

| Campo | Contenido |
|---|---|
| `source` | Ruta/origen del material (archivo, carpeta, paquete) |
| `format` | `.md` / `.docx` / `.pdf` / imagen |
| `chunk_ref` | Referencia del chunk (heading_path) cuando aplica |
| `tool_run` | Ejecución/versión del pipeline de análisis |
| `extracted_by` | Modelo/proveedor (si aplica) |
| `approved_at` / `approved_by` | Evidencia de aprobación |
| `certainty` | Estado de certeza (`accepted`/`proposed`/`unknown`/`conflicted`) |

---

## 8. Invariantes, seguridad, idempotencia y rollback

### 8.1 Invariantes `[DECISIÓN CERRADA — IM4]`

1. **Cero escrituras sin aprobación**: el importador no persiste nada en el mundo sin aprobación explícita del Autor (constitución, 5 y 7.1).
2. **Escritura solo por compuertas gated**: ninguna ruta de importación escribe al filesystem por fuera de `create`/`save` gated (digest + token) o del registro de propuestas/conflictos (W11).
3. **Borrador o propuesta, nunca canon directo**: el contenido importado llega como `draft` o propuesta; la transición a `stable` es del Autor (W3).
4. **Carpetas del sistema intocables**: `_context`, `.history`, `.papelera` nunca son destinos ni se presentan como contenido (W10).
5. **Procedencia obligatoria**: todo ítem importado registra origen y certeza; un ítem sin procedencia no se presenta como verificado.
6. **Una sola fuente de lectura**: el grafo OKF es la lectura de entidades; `lore-index.json` nunca compite (IM3).
7. **Sin promoción automática de relaciones**: las relaciones propuestas se resuelven/verifican por el grafo, pero **no se confirman ni deciden** sin aprobación del Autor (W4).

### 8.2 Seguridad `[DECISIÓN CERRADA — IM4]`

- **Rutas acotadas al mundo**: toda operación resuelve rutas relativas a `mundos/{mundo}/` y rechaza escapes (`..`, absolutos, symlinks fuera de alcance).
- **Sin fuga de secretos**: el análisis no persiste claves ni credenciales; los logs no exponen tokens.
- **Proveedor no confiable y acotado**: la extracción LLM produce datos candidatos, nunca autoridad; los envelopes/continuations que contengan claves de autoridad se invalidan (fail-closed), igual que en el flujo guiado.
- **Aprobación verificable**: el digest SHA-256 y el token de un solo uso se computan en el servidor; el Autor aprueba contra el diff, nunca contra un resumen no verificable.

### 8.3 Idempotencia `[OBJETIVO]`

- Reimportar la **misma fuente** (mismo origen + hash) con el mismo mundo produce **el mismo resultado**: los ítems ya presentes se marcan `skipped`/`updated`, no se duplican.
- La identidad del ítem se deriva de su **origen + contenido normalizado** (no del orden de ejecución).
- Un job reanudado tras una falla continúa desde el último paso completado sin efectos duplicados.

### 8.4 Rollback `[OBJETIVO]`

- Los archivos importados pasan por la **papelera** existente (`.papelera`, TTL 30 días) si el Autor decide revertir.
- El **registro del job** permite identificar qué se importó (lista de ítems con procedencia) para revertir selectivamente.
- La reversión de una importación **no elimina** las decisiones ya tomadas ni los registros W11: queda historial de la decisión.

---

## 9. No-objetivos

- **NO es un sistema de importación multiusuario** ni una herramienta de sincronización externa general (constitución, G3: implementación inicial monousuario/local).
- **NO es un gestor de archivos**: no reestructura el árbol físico del Autor (W10); sus vistas son semánticas.
- **NO es un editor de fichas existentes**: el importador no sustituye al editor manual; puede detectar cambios sobre fichas existentes y proponer actualizaciones, siempre mediante revisión y escritura gated.
- **NO es una puerta automática a Canon**: nada importado entra como canon sin aprobación.
- **NO reemplaza al grafo**: la lectura de entidades sigue en `EntityGraphIndex`; `lore-index.json` no es alternativa (IM3).
- **NO es un restaurador de instalaciones**: la migración local→VPS o la recuperación tras un formateo pertenece a un flujo separado de backup/restore, con revalidación de secretos, servicios y capacidades.
- **NO implementa el publisher como servicio**: `publisher.py` es un stub; su construcción (si aplica) es un SDD futuro con su propio contrato.
- **NO duplica la constitución ni los contratos de Taller**: referencia, no repite (constitución, 9.2).

---

## 10. Pruebas y documentación

### 10.1 Estado actual `[ACTUAL]`

| Área | Cobertura |
|---|---|
| `sync_lore` | 124 funciones de test recopiladas en 9 archivos (chunker, schemas, config, pipeline/e2e dry-run, imagen, proveedor mock, persistencia, mundo) — **sin** tests para `cli.main`, `publisher` ni `try_engram_save` |
| Grafo OKF | Tests para `EntityGraphIndex`, MCP server y `okf_contract` |
| Worker `engram_sync` | Tests de adapters y remediación (incluye `LoreIndexAdapter`) |

### 10.2 Requisitos para el SDD futuro `[OBJETIVO]`

- Invariantes de seguridad **siempre con pruebas**: cero escrituras sin aprobación, rutas acotadas al mundo, digest/token, fail-closed del proveedor, no tocar carpetas del sistema.
- Ramas de fallo del job: cancelación, reintento, fuente ilegible, proveedor no disponible, conflicto de revisión.
- Idempotencia: reimportar la misma fuente no duplica.
- Rollback: papelera y registro de job.
- Actualización documental pendiente (fuera de esta tarea): corregir el comando de `AGENTS.md` (`--world` no existe) y el conteo de endpoints de grafo cuando se toque esa documentación.

---

## 11. Decisiones cerradas y abiertas

### 11.1 Cerradas (no revertir sin nuevo acuerdo)

| ID | Decisión |
|---|---|
| **IM2** | Vocabulario fijo: análisis/indexación son de solo lectura; importación es la única fase persistente y queda detrás de la aprobación (sección 2) |
| **IM3** | El **grafo OKF es la única fuente de lectura de entidades**; `lore-index.json` no es autoridad paralela (sección 6.2) |
| **IM4** | Invariantes y seguridad del importador: cero escrituras sin aprobación, escritura solo por compuertas gated, borrador/propuesta nunca canon directo, carpetas del sistema intocables, procedencia obligatoria, una sola fuente de lectura, sin promoción automática de relaciones (sección 8) |

### 11.2 Abiertas (requieren aprobación explícita del Autor)

| ID | Decisión | Opciones | Recomendación propuesta |
|---|---|---|---|
| **IM1/O6** | Significado de "importar" | O1 analizar/indexar · O2 copiar · O3 normalizar a OKF · O4 crear fichas · O5 generar propuestas · **O6 importar tras aprobación** | **Cerrado:** O6 como significado canónico; O1 siempre disponible como lectura; O4/O5 como destinos aprobados de la escritura (sección 3.1) |
| **IM5** | Tipos de fuente admitidos por el importador | Carpeta local · archivo único · paquete `.zip` · subida desde la UI | **Cerrado:** subida desde la UI en la primera versión |
| **IM6** | Destino de `lore-index.json` | Retirarlo · conservarlo como reporte de diagnóstico · evolucionarlo como índice derivado de corpus | **Cerrado:** retirarlo; no será requisito de análisis/indexación ni fuente de lectura |
| **IM7** | Granularidad de la aprobación | Por ítem · por grupo · por lote completo | **Cerrado:** aprobación por grupo, con excepción por ítem antes de confirmar el grupo |
| **IM8** | Importación posterior al onboarding | Solo importación inicial · importación incremental/recurrente | **Importación incremental/recurrente** desde el Taller de Mundo, comparando fuentes con el estado actual y sin duplicar contenido |
| **IM9** | Relación entre importación y restauración | Google como fuente única · flujos separados con una fuente compartida | **Flujos separados**: importar incorpora contenido; restaurar recupera estado/configuración no secreta y revalida la máquina destino |

---

## 12. Definition of ready para SDD futuro

Un SDD de implementación del importador **solo** puede comenzar cuando se cumplan todos:

- [ ] Se leyeron esta constitución global, este contrato, el contrato de superficie (`world-importer-ui.md`) y los contratos de Taller referenciados (secciones 0).
- [ ] Se verificó el runtime real (CodeGraph/tests) antes de asumir cualquier `[ACTUAL]` citado (sección 1).
- [ ] Las decisiones abiertas que tocan el cambio están resueltas y anotadas (IM1, IM5, IM6, IM7).
- [ ] El cambio respeta las invariantes `[ACTUAL]` de la constitución (secciones 5, 7) y las fronteras de dominio.
- [ ] Todo comportamiento nuevo se etiqueta `[ACTUAL]`/`[OBJETIVO]`/`[PROPUESTO]` y no se presenta como implementado.
- [ ] El SDD declara explícitamente qué NO toca (AGENTS.md, `okf_contract.py` como única capa de validación OKF, carpetas del sistema, escrituras fuera de gating).
- [ ] Las pruebas cubren las invariantes afectadas (sección 10.2) y las ramas de fallo relevantes.
