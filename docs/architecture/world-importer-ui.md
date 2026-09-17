# Importador de Mundo — Contrato de Superficie y UX

> **Contrato de superficie y UX.** Este documento es el contrato de **superficie/producto** del **Importador de Mundo** de Demiurgos: cómo el Autor elige fuentes, revisa diagnósticos, aprueba y ve el resultado de una importación. **Es diseño objetivo, no implementación actual**: no existen hoy endpoints ni UI de importación, y este contrato no lo afirma. **No es un artefacto SDD** ni sustituye a la constitución global ni al contrato de producto/arquitectura del importador (`docs/architecture/world-importer.md`); los referencia sin duplicarlos. Toda afirmación lleva la etiqueta de estado correspondiente; lo no implementado no se presenta como existente.

| Campo | Valor |
|---|---|
| Estado | Contrato de taller/superficie (diseño objetivo; no implementación actual) |
| Versión del documento | 1.0 |
| Fecha | 2026-08-17 |
| Autor | Demiurgos (orquestación) |
| Idioma | Español neutro (prosa técnica) |
| Alcance | Importador de Mundo — superficie y UX: selección de mundo/fuentes, dry-run, diagnóstico, revisión, aprobación, importación, resultado/errores, progressive disclosure, accesibilidad, estados/loading/error/cancelación/reanudación, árbol físico vs vistas semánticas, distinción de acciones con y sin efectos, integración Borrador/Canon, propuestas, conflictos, referencias y procedencia, mapa de pantallas, contrato de estados y decisiones abiertas |
| Depende de | `docs/architecture/demiurgos-platform.md` (constitución), `docs/architecture/world-importer.md` (producto/arquitectura del importador) |
| Relación con SDD | Requisito previo. Ningún SDD de implementación de la superficie del importador debe comenzar sin este contrato aprobado y sus decisiones abiertas resueltas |
| Documentos relacionados | `docs/architecture/demiurgos-platform.md`, `docs/architecture/world-importer.md` (producto/arquitectura), `docs/architecture/world-workshop.md` (Taller de Mundo — canon, propuestas, conflictos, árbol físico), `docs/architecture/tool-workshop.md` (superficie del Taller de Herramientas), `frontend/src/pages/{WorldWorkshop,WikiWorld,WikiEditor}.tsx` (superficie actual) |

## Leyenda de etiquetas

| Etiqueta | Significado |
|---|---|
| `[ACTUAL]` | Comportamiento que existe hoy en el repositorio y está verificado |
| `[OBJETIVO]` | Comportamiento objetivo acordado, no necesariamente implementado aún |
| `[PROPUESTO]` | Diseño propuesto; requiere decisión antes de ser contrato |
| `[DECISIÓN ABIERTA]` | Punto sin resolver que requiere aprobación explícita del Autor |
| `[DECISIÓN CERRADA]` | Decisión ya aprobada; no debe revertirse sin nuevo acuerdo explícito |

---

## 0. Relación con la constitución y los contratos del importador

- La **definición global del producto** y las reglas de arquitectura (progressive disclosure, escritura gated, soberanía del Autor) viven en `docs/architecture/demiurgos-platform.md`. **Este documento no la duplica.**
- El **significado de "importar"** (decisión abierta **IM1**), el ciclo objetivo y las invariantes de seguridad están en `docs/architecture/world-importer.md`. Este contrato de superficie presupone la **recomendación IM1-O6** (importación tras aprobación, análisis de solo lectura), pero **no la cierra**: si el Autor aprueba otro significado, esta superficie se ajusta a ese contrato.
- **Restaurar desde respaldo** no es una pantalla del Importador: debe existir como flujo separado de recuperación/migración, aunque comparta la carpeta sincronizada como posible fuente. El Importador incorpora contenido; Restaurar recupera estado y configuración no secreta, reconstruye el grafo y revalida los servicios de la máquina destino.
- El **Taller de Mundo** gobierna el árbol físico del Autor, Borrador vs Canon, propuestas, conflictos y carpetas del sistema (`docs/architecture/world-workshop.md`, W3–W5, W10–W13). Esta superficie los presenta sin redefinirlos.
- **No existe hoy ninguna UI ni endpoint de importación.** Lo `[ACTUAL]` en este documento es únicamente la superficie que hoy permite navegar mundos (WorldWorkshop/WikiWorld/WikiEditor); todo lo demás es `[OBJETIVO]`/`[PROPUESTO]`.
- El asistente visible se llama **Asistente de Demiurgos**; "Hermes" es nombre interno y nunca aparece en copia visible (constitución, G15/10.6). `[DECISIÓN CERRADA — referencia]`

---

## 1. Qué es actual y qué es objetivo/propuesto

**Regla de etiquetas:** solo lo `[ACTUAL]` existe hoy; no se afirma que la UI del importador exista.

| Superficie | Estado | Qué es hoy / qué se busca |
|---|---|---|
| `WorldWorkshop` (`/taller-mundo`) | `[ACTUAL]` | Selecciona mundo (tarjetas) y **redirige** a `/wiki/:mundo`; no gestiona importación |
| `WikiWorld` (`/wiki/:mundo`) | `[ACTUAL]` | Tarjetas de secciones (Lore/Personajes/Sagas) con conteos; entrada al editor |
| `WikiEditor` (`/wiki/:mundo/:section`) | `[ACTUAL]` | Edición de archivos con frontmatter preservado, diff y persistencia gated; **no** es el importador |
| `WikiHome` (`/wiki`) | `[ACTUAL]` | Listado de mundos |
| **Selector de mundo del importador** | `[OBJETIVO]` | Reutiliza el patrón existente (`useWorlds`/`WorldSelector`), no un flujo nuevo |
| **Selección de fuentes** | `[OBJETIVO]` | Elegir carpeta/archivo (o paquete, según IM5) para analizar |
| **Dry-run / diagnóstico** | `[OBJETIVO]` | Vista de solo lectura del análisis: candidatos, validación OKF, conflictos, dedup, estimación |
| **Revisión** | `[OBJETIVO]` | El Autor decide destino de cada candidato (ficha/propuesta/descartar) |
| **Aprobación** | `[OBJETIVO]` | Confirmación explícita gated (digest + token) |
| **Importación** | `[OBJETIVO]` | Escritura gated con resultado/errores y opciones de reversión |
| **Resultado y errores** | `[OBJETIVO]` | Reporte final, reintentos y acceso a la papelera |

---

## 2. Flujo UX objetivo (una decisión clara por paso)

El flujo sigue el ciclo del contrato de producto (`world-importer.md`, sección 4) con **progressive disclosure**: el Autor ve lo esencial primero y profundiza solo cuando lo pide. **Cada paso resuelve una sola decisión**; no hay cuestionario interminable.

```
selección de mundo → selección de fuentes → dry-run/diagnóstico → revisión → aprobación → importación → resultado/errores
      [OBJETIVO]           [OBJETIVO]            [OBJETIVO]         [OBJETIVO]  [OBJETIVO]      [OBJETIVO]       [OBJETIVO]
```

| Paso | Decisión única del paso | Efectos | Compuerta |
|---|---|---|---|
| **1. Selección de mundo** | ¿En qué mundo se analiza/importa? | Ninguno | Ninguna |
| **2. Selección de fuentes** | ¿Qué material se analiza? | Ninguno | Ninguna |
| **3. Dry-run / diagnóstico** | (información) ¿Qué se crearía/actualizaría/saltaría y qué conflictos hay? | Ninguno | Ninguna (solo lectura) |
| **4. Revisión** | ¿Qué candidatos se aprueban y en qué forma (ficha o propuesta)? | Ninguno | Ninguna (decisiones de destino) |
| **5. Aprobación** | ¿Confirmo la importación de los ítems aprobados? | Habilita la escritura | Gated (digest + token) |
| **6. Importación** | (progreso) — | **Sí** | Solo rutas gated |
| **7. Resultado / errores** | ¿Reintento o revierto? | Post | — |

**Reglas transversales del flujo `[OBJETIVO]`:**

- **Una decisión por paso, siempre con botón de "volver"**: el Autor puede retroceder sin perder lo aprobado en pasos previos.
- **El dry-run es el corazón**: todo lo que el Autor decide en la revisión se basa en un diagnóstico explícito y verificable, no en promesas.
- **Cancelación en cualquier paso**: se conserva el progreso del job (si existe) y el Autor puede reanudarlo (ver sección 6).
- **Sin efectos antes de la aprobación**: los pasos 1–4 son de solo lectura; el Autor lo percibe (los botones de "efecto" aparecen solo tras la aprobación).
- **Importación recurrente**: después de que el mundo esté listo para trabajar, el Autor puede iniciar nuevas importaciones desde `Importaciones → Nueva importación`; el diagnóstico compara la fuente con el mundo actual y muestra solo novedades, cambios, duplicados y conflictos.

---

## 3. Progressive disclosure, decisión única por paso y accesibilidad

### 3.1 Progressive disclosure `[OBJETIVO]`

- **Resumen primero**: cada paso muestra un resumen legible en lenguaje simple, con detalles técnicos **colapsados** (p. ej. "se crearán 12 fichas, 3 se actualizarán, 2 en conflicto"; el detalle por ítem se expande a petición).
- **Una pregunta a la vez**: cuando se necesita decisión del Autor, se plantea **una sola pregunta** con opciones solo si ayudan (máx. 5) — coherente con la identidad del Asistente (constitución, G15/10.6) y con el ritmo de las skills (TW10).
- **Los mecanismos técnicos internos se ocultan**: rutas internas, provenance interna, IDs de autoridad y el proveedor subyacente nunca aparecen en la copia visible (constitución, 7.1).
- **El dry-run revela todo lo que el Autor necesita decidir**: no hay sorpresas en el paso de aprobación.

### 3.2 Accesibilidad y estados `[OBJETIVO]`

| Aspecto | Regla |
|---|---|
| **Contraste y foco** | Estados distinguibles sin depender solo del color (icono + texto + borde); foco visible en toda acción interactiva |
| **Teclado** | Todo el flujo es navegable por teclado; diálogos con cierre por `Escape` y foco inicial correcto |
| **Semántica** | Botones con `aria` descriptivo; regiones vivas (`aria-live`) para progreso y errores; diálogos con rol `dialog` |
| **Loading** | Spinner + mensaje descriptivo por fase (p. ej. "Analizando 42 archivos…"); nunca un estado vacío silencioso |
| **Error** | Mensaje accionable (qué falló, qué se puede hacer); errores de API se mapean a copia legible (patrón `getErrorMessage` existente) |
| **Cancelación** | Cancelar es explícito y reversible cuando el paso no ha escrito; tras escritura, cancelar ofrece "revierte lo importado" vía papelera |
| **Reanudación** | Un job de importación interrumpido (cierre, red, fallo) se puede **reanudar desde el último paso completado**, sin efectos duplicados (idempotencia del contrato de producto, IM4) |

---

## 4. Árbol físico del Autor y vistas semánticas

**[DECISIÓN CERRADA — UI2]** (deriva de W10) La superficie **no impone carpetas**:

- La **selección de fuentes** muestra el **árbol físico** del mundo y del sistema de archivos, respetando las jerarquías del Autor; la importación **no reestructura** esas carpetas.
- Las **carpetas del sistema** (`_context`, `.history`, `.papelera`) **se identifican visualmente y se excluyen** de la selección de fuentes como destinos; no aparecen como secciones de contenido.
- Se ofrecen **vistas semánticas** (Lore, Personajes, Lugares, Facciones, Artefactos, Historia/Cronología, Relaciones/Canon) sobre el árbol físico, sin renombrar ni mover archivos del Autor.
- En la **revisión**, cada candidato muestra su **destino semántico** (sección/tipo de entidad) y su **ubicación física prevista** (ruta dentro del mundo), para que el Autor sepa exactamente dónde quedaría.

---

## 5. Mostrar la diferencia entre acciones con y sin efectos

**[DECISIÓN CERRADA — UI3]** La UI distingue explícitamente entre acciones de **solo lectura** y acciones **con efectos permanentes**. Esto es central para la confianza del Autor.

| Acción | Tiene efectos | Cómo se presenta |
|---|---|---|
| **Analizar** | No | Botón "Analizar" (solo lectura); resultados marcados como diagnóstico |
| **Indexar** | No | Se presenta como "hacer consultable lo ya existente"; derivado, sin escritura |
| **Copiar archivos** (O2, si se aprueba) | Sí (solo si se elige explícitamente) | Acción separada y explícita, fuera del flujo canónico de aprobación |
| **Normalizar a OKF** (O3, si se aprueba) | Sí (solo tras aprobación) | Vista previa de los archivos OKF que se crearían; confirmación requerida |
| **Crear fichas** (O4) | Sí (tras aprobación) | Vista previa por ficha; aprobación gated |
| **Generar propuestas** (O5) | No escribe canon | Se presenta como "guardar propuesta" (registro W11), nunca como canon |
| **Aprobar** | Habilita la escritura | Confirmación con digest + token; aviso de "esto escribirá en tu mundo" |
| **Importar** | **Sí** | Única acción marcada como permanente; antes de ejecutarse se muestra resumen final |

**Regla visual `[OBJETIVO]`:** los botones que **solo leen** usan estilo "secundario/neutro"; los que **escriben** (tras aprobación) usan estilo "confirmación/principal" y van acompañados de un aviso explícito de efecto. Nunca se activa una escritura desde un botón ambiguo.

---

## 6. Borrador/Canon, propuestas, conflictos, referencias y procedencia en la UX

| Concepto | Presentación en la UI `[OBJETIVO]` |
|---|---|
| **Borrador vs Canon** | Cada candidato importado se muestra con su estado de llegada (`borrador`/`propuesta`); la transición a canon (`stable`) es un paso posterior del Autor en el editor (W3), no parte del importador |
| **Propuestas** | Si un candidato se importa como propuesta, se guarda como registro Markdown (W11) y la UI lo muestra en la sección correspondiente, con enlace a la ficha relacionada cuando exista |
| **Conflictos** | Los candidatos que contradicen canon se agrupan en una pestaña "Conflictos" con explicación en lenguaje simple; **se muestran, no se resuelven solos** (W5). El Autor decide: mantener, descartar o revisar |
| **Referencias** | Las entidades nombradas en la fuente se resuelven contra el grafo; si una referencia es ambigua o no existe, se marca como **pendiente de clarificar** y se pregunta al Autor (una pregunta a la vez) |
| **Procedencia** | Cada ítem muestra su **origen trazable** en forma legible (archivo fuente, sección/fragmento, fecha) **sin exponer** claves de autoridad ni rutas internas (constitución, 7.1) |
| **Certeza** | Los datos extraídos se etiquetan con su estado (`hecho`, `propuesta`, `desconocido`, `conflicto`) para que el Autor sepa qué es verificable y qué no |

---

## 7. Mapa de pantallas y componentes conceptuales

Estos componentes son **`[OBJETIVO]`/`[PROPUESTO]`** (conceptuales, no implementados). Se describen por su rol, **sin inventar endpoints**.

| Componente conceptual | Rol | Pertenece al paso |
|---|---|---|
| **ImportWorkshop (shell)** | Superficie contenedora del importador, accesible desde el Taller de Mundo (patrón `WorldWorkshop`/`CategoryCard` existente) | todos |
| **SourcePicker** | Selección de mundo (reutiliza `useWorlds`/`WorldSelector`) + selector de fuentes (árbol físico con carpetas del sistema excluidas) | 1–2 |
| **DiagnosticsPanel** | Dry-run: resumen + pestañas Candidatos / Conflictos / Validación OKF / Estimación; solo lectura | 3 |
| **CandidateList** | Lista de ítems con estado (nuevo/actualizado/saltado/conflicto/error), destino semántico y ubicación física; acciones por ítem (aprobar/descartar/propuesta) | 3–4 |
| **ReviewSummary** | Resumen humano de lo que se va a importar; distingue decidido por el Autor / propuesto por el Asistente / exigido por Demiurgos (patrón TW16) | 4 |
| **ApprovalGate** | Confirmación gated con diff legible, digest + token de un solo uso | 5 |
| **ImportProgress** | Progreso por fases, cancelación y reanudación del job | 6 |
| **ImportResult** | Resultado final: éxito/fallo por ítem, reintentos, acceso a papelera y al editor de lo importado | 7 |
| **Restore entry point** | Entrada separada para restaurar una instalación o mundo desde un respaldo; no reutiliza el diagnóstico de candidatos del Importador | Fuera del flujo de importación |
| **ErrorBanner / EmptyState / Spinner** | Reutiliza los componentes existentes de `frontend/src/components/organisms/` y `frontend/src/components/atoms/` | todos |

### 7.1 Ubicación de la acción de importación `[DECISIÓN CERRADA — UI1]`

- La acción visible se ubicará en el **sidebar izquierdo**, junto al árbol de archivos del mundo.
- Será una acción de nivel del mundo, situada en la cabecera o zona superior del árbol; no será un nodo de carpeta ni una acción exclusiva de un archivo.
- La copia visible recomendada es **"Importar contenido"**, para distinguirla de la restauración de un mundo completo desde un backup.
- La misma capacidad será accesible desde el Taller de Mundo y desde el onboarding mediante un enlace al flujo dedicado.
- El historial de importaciones podrá vivir bajo esta acción o como sección relacionada del mismo contexto del mundo.

> **Sin endpoints inventados:** este contrato no declara rutas de API para estos componentes; la definición de endpoints es materia del SDD futuro, sujeta a las invariantes del contrato de producto (escritura gated, rutas acotadas al mundo).

---

## 8. Contrato de estados de la superficie

### 8.1 Estados del flujo visible `[OBJETIVO]`

```
inicio → seleccionando → analizando → diagnosticado → revisando → aprobado → importando → resultado
   │         │               │             │             │            │           │
   └── cancelado ─┴── cancelado ─┴── fallido ─┴── cancelado ─┴── rechazado ─┴── fallido ─┴── con errores
```

| Estado | Qué ve el Autor | Acciones |
|---|---|---|
| `inicio` | Explicación de qué hace el importador y sus límites (solo lectura hasta aprobación) | Empezar |
| `seleccionando` | Selector de mundo y de fuentes | Elegir, volver |
| `analizando` | Progreso del análisis (solo lectura) | Cancelar (sin efectos) |
| `diagnosticado` | Dry-run: candidatos, conflictos, validación OKF | Revisar, ajustar fuentes, volver |
| `revisando` | Decisiones por ítem (aprobar/descartar/propuesta) | Decidir, volver al diagnóstico |
| `aprobado` | Resumen final + confirmación gated | Confirmar, cancelar (vuelve a revisar) |
| `importando` | Progreso por fases | Cancelar (se reanuda), pausar |
| `resultado` | Reporte final, reintentos, papelera | Reanudar, revierte, ir al editor |
| `con errores` | Ítems fallidos con motivo accionable | Reintentar los fallidos, descartar |

### 8.2 Contrato de botones `[OBJETIVO]`

- El botón que avanza al paso **con efectos** (importar) está **deshabilitado hasta la aprobación gated**.
- Cancelar en pasos de solo lectura **no pierde decisiones** (el Autor puede volver a `revisando`).
- Reanudar un job interrumpido **no re-ejecuta** pasos ya completados (idempotencia del contrato de producto, IM4).

---

## 9. Decisiones cerradas y abiertas

### 9.1 Cerradas (no revertir sin nuevo acuerdo)

| ID | Decisión |
|---|---|
| **UI2** | La superficie **no impone carpetas**: muestra el árbol físico del Autor y vistas semánticas; las carpetas del sistema (`_context`, `.history`, `.papelera`) se excluyen e identifican como no-contenido (sección 4; deriva de W10) |
| **UI3** | La UI **distingue explícitamente acciones con y sin efectos**: análisis/indexación de solo lectura; escritura solo tras aprobación y marcada visualmente (sección 5; deriva de la constitución 1.4/9.1) |
| **UI4** | **Progressive disclosure** y **una decisión clara por paso**: resumen legible primero, detalles colapsados, una pregunta a la vez, máx. 5 opciones (sección 3; deriva de la constitución y TW10) |

### 9.2 Abiertas (requieren aprobación explícita del Autor)

| ID | Decisión | Opciones | Recomendación propuesta |
|---|---|---|---|
| **UI1** | Ubicación de la superficie del importador | Dentro del Taller de Mundo (nueva sección/capacidad) · entrada en `WorldWorkshop` que abre un asistente dedicado · standalone en el Navbar | **Cerrado:** dentro del Taller de Mundo; el onboarding puede enlazar a esta capacidad y el flujo puede abrirse como asistente dedicado |
| **UI5** | Alcance de la vista de fuentes | Solo árbol físico · árbol + drag&drop de archivos · selector de paquetes `.zip` (según IM5) | **Cerrado:** árbol físico + drag&drop de archivos, con selector tradicional accesible; `.zip` queda para una extensión posterior |
| **UI6** | Presentación de la aprobación | Diff legible por ítem · resumen humano + detalles colapsados por grupo · ambos | **Cerrado:** resumen humano por defecto con detalles técnicos expandibles por grupo |

**[PROPUESTO — UI7]** La superficie conserva un historial de importaciones y permite iniciar nuevas importaciones incrementales desde el Taller de Mundo. Cada ejecución muestra la fuente, su última huella procesada, novedades, cambios, duplicados, conflictos y decisiones anteriores, sin presentar una reimportación completa como requisito.

> Estas decisiones de superficie dependen de las de producto (`world-importer.md`). **IM1/O6 ya está cerrado**: define que UI5/UI6 deben presentar un flujo de análisis, revisión, aprobación e importación persistente.

---

## 10. Definition of ready para SDD futuro

Un SDD de implementación de la superficie del importador **solo** puede comenzar cuando se cumplan todos:

- [ ] Se leyeron esta constitución global, este contrato de superficie, el contrato de producto (`world-importer.md`) y los contratos de Taller referenciados (sección 0).
- [ ] Las decisiones abiertas que tocan el cambio están resueltas y anotadas (IM1, IM5, IM6, IM7 en el contrato de producto; UI1, UI5, UI6 en este).
- [ ] Se verificó el runtime real (CodeGraph/tests) antes de asumir cualquier `[ACTUAL]` citado (sección 1).
- [ ] El cambio respeta las invariantes de la constitución (secciones 5, 7) y las fronteras de dominio; la UI no inventa endpoints ni presenta como implementado lo objetivo.
- [ ] Todo comportamiento nuevo se etiqueta `[ACTUAL]`/`[OBJETIVO]`/`[PROPUESTO]` y no se presenta como implementado.
- [ ] Las pruebas cubren: cero escrituras sin aprobación, estados/cancelación/reanudación, distinción visual de acciones con efecto, exclusión de carpetas del sistema, accesibilidad (teclado, `aria-live`, contraste) y ramas de fallo.

---

## 11. Slice 2 — Enriquecimiento asesor en la UI `[ACTUAL]`

> **Estado:** implementado en el SDD `world-importer-enrichment` (PR 2).
> Esta sección describe la superficie UI específica del enriquecimiento,
> sin duplicar el contrato de producto (`world-importer.md` §13).

### 11.1 Opt-in consciente, no sorpresa

El toggle "Pedirle al asistente sugerencias de clasificación y relaciones"
vive en el paso de selección, **antes** del botón "Analizar". Su copy
explica tres hechos clave que el Autor debe entender antes de activarlo:

1. Las sugerencias son **orientativas** y requieren aprobación individual.
2. La ausencia del asistente no bloquea el análisis (fail-open).
3. Activar el toggle es una decisión explícita por job, no un default.

El default es **off**: ningún job llama al gateway de Hermes sin el opt-in
explícito del Autor. El botón "Analizar" no cambia su label ni su icono
según el toggle, para que el opt-in no parezca una acción diferente.

### 11.2 Banner de estado (4 variantes)

Después del análisis, el paso de revisión muestra **uno** de cuatro
banners según `enrichment_status`:

| Estado              | Color    | Mensaje clave                                                          |
|---------------------|----------|------------------------------------------------------------------------|
| `disabled`          | (oculto) | La UI ignora el flujo; sin banner para no contaminar el camino legacy  |
| `ok`                | musgo    | "Asistente: sugerencias listas para revisar" + recordatorio de aprobar |
| `no_suggestions`    | neutro   | "El asistente respondió pero no produjo sugerencias aplicables"        |
| `error`             | llamita  | "El asistente no respondió. El análisis sigue siendo válido"           |

Los banners usan `role="status"` + `aria-live="polite"` para que lectores
de pantalla anuncien el resultado del análisis sin interrumpir.

### 11.3 Tarjetas de sugerencia (advisory cards)

Cada sugerencia del `enrichment_json` se renderiza como una tarjeta
independiente dentro del detalle del candidato. Distinción visual
obligatoria entre sugerido y determinado:

- **Clasificación** → borde y fondo `musgo` (verde-oliva; "es crecimiento,
  no es identidad").
- **Relación** → borde y fondo `filio` (neutro; sigue el patrón de las
  image placements existentes).

Cada tarjeta muestra:

- **Tipo** de sugerencia (badge): `clasificación` o `relación`.
- **Valor** sugerido: para clasificaciones, `tipo: <valor>` + badges de
  `tags`; para relaciones, `<relationship_type> → <target>`.
- **Confianza** como porcentaje (`Math.round(confidence * 100)`).
- **Evidencia** textual que el LLM adjuntó como justificación.
- **Provenance**: `provider` + `model`, derivado del
  `provenance.provenance` del payload.
- **Botones independientes**: `Aprobar` y `Rechazar` por sugerencia.

El estado aprobado/rechazado se refleja visualmente (anillo `musgo/40`
para aprobado, opacidad reducida para rechazado) y via
`data-suggestion-state` para tests automatizados y herramientas de
accesibilidad.

### 11.4 Decisiones independientes, sin acoplamiento

Cada botón opera sobre una sola sugerencia. La UI:

1. Hace optimistic update del estado local antes de la llamada al
   endpoint, para que el botón se sienta instantáneo.
2. Si el endpoint rechaza (409 stale digest, 401, etc.), revierte el
   estado optimista y muestra el error en el `ErrorBanner` global.
3. Re-lee el review después de un éxito para reflejar el estado del
   servidor (un par de decisiones simultáneas contra la misma lista
   nunca desincronizan la UI del servidor).

No hay "aprobar todas" ni "rechazar todas" — la decisión granular es la
única primitiva. Si el Autor quiere aplicar todas, aprueba una por una;
la fricción es intencional para que cada sugerencia se evalúe.

### 11.5 Compromiso visible antes del execute

Antes del botón "Aprobar grupos seleccionados", la UI muestra un resumen
"Sugerencias aprobadas: N se aplicarán al importar" con icono `lightbulb`.
El compromiso nunca es implícito: si el revisor aprobó sugerencias, las
ve escritas en el panel antes de confirmar el grupo.

El execute envía `suggestion_ids` con esos IDs. Si el servidor los
rechaza (por ejemplo, porque otra pestaña cambió el `review_state`), el
ErrorBanner explica el motivo y el flujo vuelve a revisión con el estado
actualizado.

### 11.6 Accesibilidad

- Cada botón `Aprobar` / `Rechazar` tiene `aria-label="Aprobar
  sugerencia <id>"` / `aria-label="Rechazar sugerencia <id>"` para que
  lectores de pantalla anuncien la acción concreta.
- Los banners usan `aria-live="polite"` (no `assertive`) para no
  interrumpir la navegación.
- El opt-in toggle tiene `aria-describedby` apuntando al texto
  explicativo, así el lector anuncia la descripción al recibir foco.
- Las tarjetas sugieren colores con contraste WCAG AA sobre fondo
  `cripta` (probado en `frontend/src/components/atoms/Badge.tsx`).
