# Importador → Taller de Mundo → Skill Madre — Roadmap de bloques para salir del agujero del conejo

> Documento vivo de referencia para retomar trabajo **bloque a bloque** en sesiones nuevas.
> No depende de Engram: es la fuente de contexto completa y específica de lo que falta implementar.
> Complementa (no reemplaza) `world-importer.md`, `world-importer-ui.md` y `world-workshop.md`.

---

## 0. Propósito y cómo usar este documento

Este documento registra el **mapa de dependencias** entre los bloques que hay que construir para salir del
descenso: `Skill Madre → Taller de Mundo → Importador`. Se sale **en orden inverso**: primero el importador
(la base), luego el Taller de Mundo, y al final la Skill Madre.

Cada **bloque** tiene:
- **Problema** — qué está roto o falta.
- **Qué construir** — la pieza concreta.
- **Qué desbloquea** — qué bloque superior queda habilitado.
- **Estado** — `[PENDIENTE]`, `[EN CURSO]`, `[HECHO]`.

Regla: **un bloque se cierra en una sesión**; al terminar se actualiza el estado aquí y se guarda en Engram.

---

## 1. El descenso (por qué estamos acá)

```
Taller de Herramientas + Skill Madre
        │  (depende de: qué herramientas/skills ofrecer y cómo crearlas)
        ▼
Taller de Mundo        ← secciones, vistas, árbol flexible, Relaciones y Canon
        │  (depende de: tener contenido del mundo materializado y clasificado)
        ▼
Importador de Lore     ← materializar el árbol + las relaciones ANTES que los Talleres
```

- **Skill Madre** → se definió en `tool-workshop.md` (no es el foco ahora).
- **Taller de Mundo** → se definió en `world-workshop.md` (secciones, vistas, Relaciones y Canon).
- **Importador** → es la **BASE**. Sin él, el Taller de Mundo no tiene contenido que mostrar.

> Decisión clave (memoria #2081/#2082): el Importador de Mundo/Lore es el **primer SDD de implementación**
> de Demiurgos, porque materializa árboles personalizados, fichas, catálogos, referencias, relaciones y
> estados ANTES de que los Talleres los interpreten.

---

## 2. Decisiones de diseño tomadas en esta iteración (NO están en ningún otro .md)

Estas son las decisiones que surgieron en la sesión de diagnóstico y **aún no se registran** en los
contratos existentes. Son vinculantes para el diseño del importador.

### D1 — El importador crea la jerarquía desde el documento, NO por taxonomía de tipos [CERRADA]
- La jerarquía de archivos nace de la **estructura del documento** (los segmentos del `canonical_id`),
  respetando la organización que el Autor ya le dio a su lore.
- El **tipo** (`lugar`, `personaje`, `criatura`…) es un **dato adicional** del frontmatter (`type:`),
  NO la fuente de la carpeta. El tipo enriquece pero no esclaviza la estructura.
- Motivo: los Stals y Áyagars NO son "personajes" (son poderes y criaturas que se unen a humanos).
  Una taxonomía automática tipo→carpeta los clasificaría mal y corrompería el lore.
- Ruta objetivo: ESTABLE (mismo `canonical_id` → misma ruta), INYECTIVA (dos identidades nunca chocan),
  LEGIBLE (el Autor razona `Política::Dottua` → `lore/politica.../dottua.md`, no un hash críptico).

### D2 — La clasificación de cada documento la decide el AUTOR, no la máquina [CERRADA]
- Al cargar un documento, el sistema **pregunta al Autor** a qué categoría/sección pertenece.
- Dos rutas: (a) el Autor elige manualmente, o (b) el sistema **sugiere** automáticamente según el
  contenido y el Autor **confirma**.
- Motivo: un caso de uso real — un Autor sin acceso a Demiurgos investiga/enriquece su mundo en un `.docx`
  suelto durante un viaje, y luego lo importa. El sistema debe recibir ese documento y preguntar dónde va.
- Principio "no grilletes": la máquina sugiere, el Autor decide; la clasificación automática es un helper
  opcional, nunca un destino obligatorio.

### D3 — Se clasifica POR DOCUMENTO, no por ficha [CERRADA]
- El importador mira **cada archivo fuente** y decide la sección del documento completo (una vez por archivo).
- Dentro de esa sección, genera la jerarquía interna de headings del documento.
- Motivo: un Autor estructural importa `Personajes.docx`, `Razas.docx`, `Territorios.docx`. La sección
  (`personajes/` vs `lore/`) se decide por documento; la jerarquía interna, por headings.
- Caso del Autor con un documento único mezclado (la Enciclopedia): si el Autor elige "Lore", TODO va a
  `lore/` con la jerarquía interna intacta. NO se separan personajes de lore por tipo.

### D4 — El estado Borrador/Canon ya existe (backend), falta el panel/grafo que lo consuma [HALLAZGO]
- El estado está persistido y conectado: `status: draft` / `stable` en frontmatter; `setStatus()` API;
  `FileNode.status` en el árbol; badge en la ficha.
- **NO existe**: el panel "Relaciones y Canon" que filtre por canon, ni el grafo que distinga entidades
  canon/borrador, ni la detección de conflictos borrador-vs-canon. Es diseño pendiente.

### D5 — Sagas se elimina como sección del Taller de Mundo [HALLAZGO + DESFASE]
- Decisión conceptual: Saga es **narrativa** (historias/tramas/arcos) → pertenece al futuro Taller de
  Narrativa, NO al Taller de Mundo (memoria #2039, #2058). No se sustituye por Referencias (son cosas
  distintas: Sagas = narrativa, Referencias = material de apoyo/investigación).
- **DESFASE con el código**: `VALID_SECTIONS`, `_SCAN_SECTIONS` (grafo) y `IMPORTER_SCOPE_SECTIONS`
  siguen incluyendo `sagas`. Hay que retirarla y verificar que ningún mundo real la use con contenido valioso.

---

## 3. Mapa de bloques a construir (en orden de dependencia)

### BLOQUE 1 — El importador materializa el árbol  `[PENDIENTE]` ★ ARRANCAR ACÁ

**Problema:** hoy "Contenido de fichas: 0" y todo cae en "Requiere tu decisión (52)". La causa raíz es el
**gap identidad-vs-ruta**: `resolve_target` deriva la ruta solo del `source_path`
(= `Enciclopedia de los Vibrantes.md`), ignorando el `canonical_id` jerárquico → `unknown section` → `review`.

**Qué construir:**
1. **Clasificador por documento** (D2/D3): al cargar, el Autor elige la categoría (Lore/Personajes/
   Referencias), con sugerencia automática confirmable. UI: dropdown por archivo en la selección.
2. **Mapeo identidad→ruta**: usar la jerarquía del `canonical_id` con `safe_slug_from_id` (ya existe en
   `okf_contract.py:103` pero tiene 0 callers). `Política | Distribución Y Territorios::Dottua` →
   `lore/politica-distribucion-y-territorios/dottua.md`.
3. **Rama `canonical_id` en `resolve_target`** ANTES de la rama source (mantener la rama source legacy
   intacta para fichas implícitas / `canonical_id=""`).

**Qué desbloquea:** que las fichas se materialicen realmente en `lore/…`, `personajes/…`. Fin del "Contenido: 0".

**Decisión abierta:** dónde vive el dropdown del clasificador — propuesta: en la selección de archivos,
**antes** del análisis. Validar con el Autor.

---

### BLOQUE 2 — Estado inicial de las fichas importadas  `[PENDIENTE]`

**Qué construir:** que las fichas importadas entren como **borrador** (`status: draft`) por defecto.
**Qué desbloquea:** que el panel Relaciones y Canon tenga fichas con estado para filtrar (D4).

---

### BLOQUE 3 — Detección de colisiones al importar  `[PENDIENTE]`

**Qué construir:** al importar, contrastar las fichas nuevas contra el índice del grafo existente (por
identidad + referencias, no contra todo el mundo a ciegas) → marcar `review`/`conflicto` antes de materializar.
**Qué desbloquea:** que importar no corrompa lore preexistente. Se apoya en `plan_merge` (ya existe) y
`okf_contract.validate` con `resolve` (ya existe).

---

### BLOQUE 4 — Panel "Relaciones y Canon"  `[PENDIENTE]` (subimos al Taller de Mundo)

**Qué construir:** grafo visual + panel de conflictos + vista de propuestas; filtrar por borrador/canon (D4).
**Qué desbloquea:** la vista semántica que decidimos (memoria #2061). Es "objetivo de producto, no
capacidad actual completa".

---

### BLOQUE 5 — Skill Madre / Taller de Herramientas  `[PENDIENTE]` (superficie)

Lo que consume el Taller de Mundo ya funcionando. Menos urgente; su contrato vive en `tool-workshop.md`.

---

## 4. Estado de implementación actual (qué existe vs qué falta)

### Ya implementado y funcionando
| Pieza | Evidencia |
|---|---|
| Splitter H1-H5 → `canonical_id` jerárquico | `import_analysis.split_heading_tree` — produce jerarquía correcta (52 fichas, 0 duplicados `#N`) |
| Enriquecimiento Hermes (summary/type/relaciones) | `analyze_ficha_funnel` — trocea por bytes (20k), fill-in de resúmenes, catálogo global para relaciones cross-lote (commit `3291280` + tests) |
| Validación OKF por ficha | `okf_contract.validate` — detecta `missing type`, `unresolved-reference`, `ambiguous-reference` |
| Índice del mundo (grafo) | `graph_indexer` — resuelve `[[wikilink]]` contra el mundo, recalcula backlinks |
| Relaciones se anclan por `id` canónico, NO por ruta | `graph_indexer._resolve_link` — prioridad 1 = `id` del frontmatter → el Autor puede mover archivos sin romper relaciones |
| Resolución de target | `resolve_target` / `_resolve_candidate_target` (marca `review`/`rejected`) |
| Merge vs colisión | `plan_merge` en `import_service` — `keep`/`merge`/`review`/`replace` |
| Detección de contradicciones semánticas | `_TEXT_SYSTEM_PROMPT` extrae `contradictions` al analizar |
| Estado Borrador/Canon (dato) | `status: draft/stable` en frontmatter + `setStatus()` + `FileNode.status` |

### Falta implementar
| Pieza | Estado |
|---|---|
| Clasificador por documento (decisión del Autor) | ❌ No existe — es BLOQUE 1 |
| Mapeo identidad→ruta (`resolve_target` rama canonical_id) | ❌ No existe (causa del "Contenido: 0") — BLOQUE 1 |
| Panel "Relaciones y Canon" (grafo/conflictos/propuestas) | ❌ No existe — BLOQUE 4 |
| Vista de grafo visual en frontend | ❌ No hay componente de grafo (solo `api/graph.ts`) |
| Panel de conflictos (350 vs 500 → decidir canon) | ❌ No existe — BLOQUE 4 |
| Vista de propuestas (aceptar/rechazar) | ❌ No existe — BLOQUE 4 |
| Estado inicial de fichas importadas (borrador por defecto) | ❌ No existe — BLOQUE 2 |
| Retirar `sagas` de secciones canónicas | ⚠️ Desfase código vs decisión (D5) |

### OJO — confusión de términos
- `conflict` en backend (`import_models`, `import_service`) = **estado del importador** (ficha que no se
  materializa limpio). ✅ Existe.
- Panel "Conflictos" del Taller de Mundo = ver contradicciones entre fichas y decidir canon. ❌ No existe.

---

## 5. Hallazgos técnicos clave (para retomar sin re-investigar)

### Gap identidad-vs-ruta (causa raíz del "Contenido: 0")
- `resolve_target` (import_analysis.py:492) lee **solo** `candidate.provenance.source_path`.
- El `canonical_id` jerárquico (identidad de dedup y `id` del grafo) **nunca** se consulta para la ruta.
- Con DOCX suelto: `source_path = Enciclopedia de los Vibrantes.md` → primer segmento no es sección
  canónica → `unknown section` → `review` → "Contenido: 0".
- Verificado en job `d762cf1a`: 52/52 candidatos `status=review`, todos con el mismo diagnóstico.

### El splitter NO es el problema (documento corregido funciona)
- Después de corregir la jerarquía (sub-sección `### La Orden...` al 5to Stal): 52 fichas, **0 duplicados** `#N`.
- `Sistema Stal` → 9 hijos (1er→9no Stal, todos FICHA). Regla del splitter: `is_ficha = nivel 1 o tiene hijos`.
  Un Stal sin heading hijo se plegaba al padre (por eso faltaba el 5to antes).

### `safe_slug_from_id` ya existe pero no se usa
- `okf_contract.py:103`: transforma `Ayagares::Descripción Física#2` → `ayagares-descripcion-fisica-2`.
- **0 callers en producción** — solo tests. Es la pieza lista para el mapeo identidad→ruta.

### Deduplicación YA es por ficha, no por archivo
- CONSTRAINT `UNIQUE (world, source_hash, normalized_identity)` en `import_store.py:59`.
- `normalized_identity = canonical_id` → N fichas del mismo archivo = N filas, sin chocar.
- La ruta NO es parte de la clave → cambiarla no rompe la dedup. PERO la ruta debe ser **inyectiva**
  sobre el `canonical_id` completo (carpetas por segmento + ordinal `#N`), o dos identidades distintas
  podrían colisionar en disco sin que la dedup lo detecte.

### Relaciones ancladas por `id`, no por ruta (principio "no grilletes")
- `graph_indexer._resolve_link` (line 319): prioridad 1 = `id` canónico, luego display-name, luego stem.
- Resultado: el Autor puede **mover/renombrar archivos** después sin romper el grafo (las relaciones
  sobreviven por `id`). Solo hay que reindexar (el `watcher` ya lo hace).

### Cómo se detectan conflictos/propuestas (NO por barrido completo)
- **Validación por ficha** contra el contrato OKF + `resolve` de referencias contra el índice del grafo.
  Solo las referencias que la ficha declara se contrastan, no todo el mundo.
- **Conflictos** ← señales: `unresolved-reference`, `ambiguous-reference`, `okf_issues` (identity/missing-type),
  `contradictions` (semántico de Hermes).
- **Propuestas** ← `enrichment_json` (relaciones del funnel), sugerencias de clasificación, `EditProposal`.
- Nada se convierte en **canon automáticamente**: el Autor decide (memoria #2040, #2061).

### Estructura del documento actual (para el clasificador)
- `Enciclopedia de los Vibrantes.docx` → 11 raíces top-level: El Origen, Vibrastal, Sistema Stal, Áyagars,
  Planeta Vibral, Tecnología, Cultura, Política, Religión, Índice De Términos, Ideas que me dió Cloude 2.
- Secciones con hijos: Sistema Stal (8→9), Áyagars (3 → Impacto Social y Dvex con 9 c/u), Planeta Vibral (1),
  Cultura (1), Política (9).

---

## 6. Decisiones que siguen ABIERTAS (necesitan acuerdo del Autor)

1. **¿Clasificador antes del análisis o en el paso de revisión?** → Recomendado: antes, dropdown por archivo.
2. **¿Se permiten secciones de primer nivel nuevas, o solo subcarpetas dentro de lore/personajes?**
   → Recomendado: solo subcarpetas (las secciones de primer nivel son fijas del Taller). Validar.
3. **¿Cómo resolver "este documento va a lore pero la ficha ya existe"?** → Recomendado: marcar colisión →
   el Autor decide (mantener/fusionar/reemplazar). Nunca merge automático silencioso.
4. **¿Cómo se ve el estado borrador/canon dentro del árbol?** → badge por ficha, filtro "ver solo canon",
   marcación visual distinta. No definido aún.
5. **Retirada de `sagas`**: verificar impacto antes (¿algún mundo real la usa con contenido valioso?).

---

## 7. Próximo paso recomendado

**Empezar por BLOQUE 1** (el importador materializa el árbol), y dentro de él, la primera pieza es el
**clasificador por documento** (decisión del Autor al cargar), porque la raíz de la ruta depende de la
categoría elegida. Sin esa decisión, no se puede mapear `canonical_id → ruta` correctamente.

Antes de tocar código del Bloque 1, cerrar las decisiones abiertas §6.1 y §6.2 (clasificador antes/análisis
y secciones de primer nivel) — son de producto, no técnicas.
