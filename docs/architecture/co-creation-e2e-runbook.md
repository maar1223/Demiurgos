# Runbook E2E manual — Co-creación de Skills (Skill Madre)

> **Qué es.** Procedimiento **manual** para validar de extremo a extremo la co-creación de Skills del Taller de Herramientas (MVP Alfa, ítem D) contra un proveedor Hermes **real**. No es un smoke test automático: cada paso lo ejecuta una persona y compara el resultado con el esperado.
> **Alcance.** Cubre arranque + semilla fundacional, biblioteca/activación/compañeros + router, sesión de co-creación real, materializar → publicar → derivar, e importar + consumo guiado.
> **Aviso de estado (leer antes de empezar).** El seam `_CO_CREATION_MATERIALIZER` (`src/tools/demiurgos-suite/wiki/api_server.py`) **está cableado**: se enlaza perezosamente junto a `_CO_CREATION_PROVIDER` y construye `CoCreationMaterializer(_methodology_library())` en el primer uso. Por eso los pasos de **materializar/derivar/canvas/validate** ya **no** responden 503 `capability_unavailable` por falta de materializador; ver §0 para el detalle y §4 para el punto exacto. Este runbook documenta el flujo completo para que el gate lo verifique.

---

## 0. Estado de partida (lo que hoy funciona y lo que no)

| Área | Estado verificado |
|---|---|
| Arranque, semilla fundacional, biblioteca, activación, compañeros, router | **Operativo** (con Hermes real donde se indica) |
| Sesión de co-creación: crear, `turn`, `progress`, `trigger/approve` | **Operativo** (requiere Hermes real) |
| `materialize`, `derive`, `canvas`, `validate` | **Operativo**: el seam `_CO_CREATION_MATERIALIZER` está cableado en producción (enlace perezoso, construido en el primer uso) |
| `publish` / `activate` de una co-creación | Disponibles; dependen de un borrador creado por `materialize` (ya operativo) |

**Evidencia del cableado** (`src/tools/demiurgos-suite/wiki/api_server.py`): declaración en `_CO_CREATION_MATERIALIZER: CoCreationMaterializer | None = None` (línea 3496) y lecturas que resuelven el seam en `materialize` (≈3851), `publish` (opcional, ≈3977), `derive` (≈4194), `canvas` (≈4311) y `validate` (≈4351). La asignación de producción vive junto a `_CO_CREATION_PROVIDER` y enlaza perezosamente el materializador: `_CO_CREATION_MATERIALIZER = _LazyBinding(lambda: CoCreationMaterializer(_methodology_library()))`. El enlace perezoso evita construir o sembrar la biblioteca al importar el módulo (ver `_DeferredMethodologyLibrary`); los tests siguen reemplazando el atributo después del import (`tests/test_co_creation_api.py`). La regresión está cubierta por `test_production_materializer_seam_is_wired` y `test_materialize_route_does_not_fail_closed_through_production_seam`. La ruta alterna (no co-creación) `/api/methodologies/drafts` + `/publish` sigue funcionando igual.

Con el seam cableado, la co-creación completa es validable de extremo a extremo en el gate. Los pasos 1–3 y la parte de biblioteca del paso 5 ya se podían validar sin el seam; ahora también los pasos 4–5 con `materialize`/`derive`.

---

## Prerrequisitos

| Requisito | Detalle |
|---|---|
| Backend | Python 3.11+; dependencias: `.venv/bin/pip install -r src/tools/demiurgos-suite/requirements.txt` |
| Frontend (opcional) | Node 18+; `cd frontend && npm install` |
| **Hermes real** | Hermes Agent CLI con gateway en `HERMES_GATEWAY_URL` (default `http://127.0.0.1:8642/v1/chat/completions`). Si exige auth, `HERMES_GATEWAY_KEY` (puede vivir en el `.env` de la raíz de datos; se lee en el arranque). **Sin gateway real, el paso 3 y todo el consumo guiado devuelven 503** |
| Auth | `DEMIURGOS_AUTH_MODE=local-dev` (sesión de un clic, **solo loopback**) o `credentials`. Sin principal confiable, toda ruta con escritura devuelve **401** |
| Mundo de prueba | Debe existir un mundo bajo la raíz de datos: `<data_root>/mundos/<mundo>/` (p. ej. `vibrantes`). Activación y guiado devuelven **404** si el mundo no existe |
| Raíz de datos | Se resuelve por `DEMIURGOS_DATA_ROOT` o el puntero `~/.config/demiurgos/data-root.json`. En este checkout el puntero apunta a la raíz del repo, así que los almacenes caen bajo `data/` |
| Terminología | «Skill Madre» = proveedor kernel de co-creación. El «qué skill usar y en qué orden» es **otro** sistema (`skill_router.py`), no la Skill Madre |

Variables útiles para los comandos siguientes:

```bash
API=http://127.0.0.1:8000
JAR=/tmp/demiurgos-cookies.txt
```

---

## Camino rápido

1. **Arrancar** el stack y confirmar salud.
2. **Semilla fundacional**: verificar `narrative-character-creation` en la biblioteca.
3. **Biblioteca/activación/compañeros** + router: activar una versión y listar compañeros.
4. **Sesión real de co-creación**: crear sesión, responder turnos, revisar hitos y techo de preguntas.
5. **Materializar → revisar → publicar → derivar**.
6. **Importar** un paquete y **consumir** la versión activada en el flujo guiado.

---

## Detalle por paso

### Paso 1 — Arranque y semilla fundacional

**Arrancar.** Desde la raíz del repo:

```bash
./scripts/start-demiurgos.sh start
```

Levanta el gateway Hermes (8642), la API Wiki (8000) y el frontend (5173). Alternativa solo-API (sin gateway):

```bash
.venv/bin/python -m uvicorn api_server:app \
  --app-dir src/tools/demiurgos-suite/wiki --host 127.0.0.1 --port 8000
```

Salud (debe responder `200`):

```bash
curl -fsS "$API/health"
```

**Semilla.** El sembrado corre en la **inicialización perezosa de la biblioteca**: la primera ruta que resuelve `_methodology_library()` construye `MethodologyLibrary(<data_root>/data/methodology/library.json`) y llama `_seed_foundational_skills` → `install_seeds(library, <data_root>/data/methodology/seeds)`. La instalación compila cada entrada, inyecta `clasificacion="Oficiales"` + `fundacional` desde `methodology_trust.py`, y es **insert-only** (nunca re-apunta activaciones ni compañeros).

**Verificar** (lectura pública, sin auth):

```bash
curl -fsS "$API/api/methodologies/inventory?fundacional=true"
```

Resultado esperado (`200`): `items[]` con `skill_id: "narrative-character-creation"`.
- En una raíz de datos **nueva**: solo `version: "1.2"` (el catálogo vigente tiene un único manifiesto).
- En una tienda **existente** (la de este repo): `1.0`, `1.1` **y** `1.2`.
- Todos con `clasificacion: "Oficiales"` y `trust_attributes: ["fundacional"]`.

Verificación equivalente en disco: `data/methodology/library.json` (almacén en runtime, **gitignored**) → claves de `published` `narrative-character-creation@1.0/1.1/1.2`.

### Paso 2 — Biblioteca, activación, compañeros y router

**Sesión de auth** (modo `local-dev`, loopback):

```bash
curl -fsS -c "$JAR" -X POST "$API/api/auth/local-dev/session"
```

A partir de aquí, añadir `-b "$JAR"` a las llamadas con escritura.

**Estado de la biblioteca:**

```bash
curl -fsS -b "$JAR" "$API/api/methodologies/status"
```

Esperado (`200`): `{ "published": [...], "activations": {...}, "drafts": [...], "companions": {...} }`.

**Activar una versión por mundo** (slot `guided-character` por defecto):

```bash
curl -fsS -b "$JAR" -X POST "$API/api/methodologies/activate" \
  -H 'Content-Type: application/json' \
  -d '{"world":"vibrantes","skill_id":"narrative-character-creation","version":"1.2","flow_type":"guided-character"}'
```

Esperado (`200`): `{ world, skill_id, version, digest, activated_at, flow_type }`. `flow_type` no soportado → `422 unsupported_flow_type`; versión no publicada → `422 not_published`; mundo inexistente → `404`.

**Leer / desactivar / rollback:**

```bash
curl -fsS -b "$JAR" "$API/api/methodologies/active/vibrantes?flow_type=guided-character"
curl -fsS -b "$JAR" -X POST "$API/api/methodologies/deactivate" \
  -H 'Content-Type: application/json' -d '{"world":"vibrantes","flow_type":"guided-character"}'
curl -fsS -b "$JAR" -X POST "$API/api/methodologies/rollback" \
  -H 'Content-Type: application/json' -d '{"world":"vibrantes","flow_type":"guided-character"}'
```

`deactivate` es idempotente (slot vacío → mismo eco). Esperado: eco con `skill_id`/`version` `null`.

**Compañeros** (independientes del slot de activación):

```bash
curl -fsS -b "$JAR" -X POST "$API/api/methodologies/companions/activate" \
  -H 'Content-Type: application/json' \
  -d '{"world":"vibrantes","skill_id":"narrative-character-creation","version":"1.2"}'
curl -fsS -b "$JAR" -X POST "$API/api/methodologies/companions/deactivate" \
  -H 'Content-Type: application/json' \
  -d '{"world":"vibrantes","skill_id":"narrative-character-creation"}'
```

Esperado: `{ world, companion: {...} }` y `{ world, removed: true|false }`. Límite de compañeros → `422 companion_limit_reached`.

**Router de skills** (`skill_router.route()`). Es el mecanismo de **selección** del asistente no guiado; lee la skill activada del mundo (slot `guided-character`) y sus compañeros, y clasifica con un run de Hermes (por eso requiere el gateway real). Se ejercita por el asistente:

```bash
curl -fsS -b "$JAR" -X POST "$API/api/vibrantes/ai/ask" \
  -H 'Content-Type: application/json' \
  -d '{"mundo":"vibrantes","prompt":"<texto que corresponda a la skill activada>","session_id":"e2e-1"}'
```

Observación esperada: el envío devuelve el sobre semántico; la **decisión de ruteo es un efecto lateral** registrado en el turno persistido (memoria de conversación, SQLite `<data_root>/data/conversation-memory.sqlite3`). Casos de borde del contrato: empate cercano o baja confianza **fallan abiertos** (`source="ambiguous"` / `"fallback"`, cero inyección); el ruteo se **suprime** si el canal activo del mundo no es `legacy`. El contrato del router vive en `docs/architecture/skill-runtime-consumption-contract.md` (SR1–SR6) y **no** es la Skill Madre.

### Paso 3 — Sesión de co-creación contra Hermes real

**Este es el paso que los tests existentes falsean** (inyectan un proveedor fake). Aquí se usa `HermesCoCreationProvider` contra el gateway real. Si el probe de capacidades no admite, la ruta responde `503 capability_unavailable`.

**Crear sesión** (transversal sin `world`, o con `world` existente):

```bash
curl -fsS -b "$JAR" -X POST "$API/api/co-creation/sessions" \
  -H 'Content-Type: application/json' \
  -d '{"author_input":"quiero crear una skill de duelos rituales","world":"vibrantes"}'
```

Esperado (`200`): `{ protocol_version: "co-creation-v1", session_id, principal_id, world, revision, milestone: "proposito", progress: [...], question_count, pending_question, pending_options, messages, phase, draft_id, draft_payload, warnings, history_count, derived_from, trigger_approval }`. La creación ejecuta el **primer turno** inmediatamente. Mundo inexistente → `422`; proveedor no admitido → `503`.

**Responder un turno** (una respuesta del Autor → una pregunta de la Skill Madre, REQ-CC-3):

```bash
curl -fsS -b "$JAR" -X POST "$API/api/co-creation/sessions/<SESSION_ID>/turn" \
  -H 'Content-Type: application/json' \
  -d '{"base_revision":<REVISION>,"author_input":"<respuesta>"}'
```

Esperado (`200`): el estado con `revision` incrementada y la nueva pregunta pendiente.

**Recuperar / progreso:**

```bash
curl -fsS -b "$JAR" "$API/api/co-creation/sessions/<SESSION_ID>"
curl -fsS -b "$JAR" "$API/api/co-creation/sessions/<SESSION_ID>/progress"
```

**Hitos.** Secuencia fija `proposito → alcance → flujo_principal → ramas_reglas → borrador_listo → revision_publicacion`; cada hito reporta estados `completado`/`actual`/`pendiente` (nunca un porcentaje).

**Techo de preguntas.** `QUESTION_CEILING = 20`, verificado **antes** de llamar a Hermes. Al superarlo: `422 ceiling_reached` con cero mutación de la sesión.

**Fail-closed del sobre de autoridad.** El proveedor no puede emitir claves de autoridad (`target`, `digest`, `revision`, `authority`, `reference`, `acceptance`, `accepted_canon`, `authorization`) en ningún nivel (hasta profundidad 4). Si aparecen: `422 invalid_envelope` (o `502 malformed_output`), con **cero mutación**. Como un Hermes conforme nunca las emite, esta prueba negativa requiere apuntar el gateway a un **stub/mock controlable** que devuelva un sobre con una clave de autoridad; es una comprobación manual y opcional.

**Guardas adicionales:** `base_revision` obsoleto → `409 revision_conflict`; sesión de otro principal → `403`; desconocida/expirada → `404`; sesión ya `complete` → `422`.

### Paso 4 — Materializar → revisar → publicar → derivar

> ✅ **Seam cableado.** `POST .../materialize`, `POST /api/co-creation/derive`, `PUT .../canvas` y `POST .../validate` resuelven el materializador a través del seam `_CO_CREATION_MATERIALIZER` (enlace perezoso; ver §0), por lo que este paso ya produce borrador. Si el materializador no se pudiera construir, la ruta sigue fallando cerrado con 503 `capability_unavailable` (guarda defensiva, no estado por defecto).

**Materializar** (Autor confirma `borrador_listo`; crea un **borrador**, nunca publica):

```bash
curl -fsS -b "$JAR" -X POST "$API/api/co-creation/sessions/<SESSION_ID>/materialize" \
  -H 'Content-Type: application/json' \
  -d '{"base_revision":<REVISION>,"name":"Duelos rituales","description":"<trigger>","taller":"Mundo","categoria_funcional":"Creación","etiquetas":["duelos"]}'
```

Esperado (`200`): `{ draft_id, ok: true, issues: [], compile_issues: [], phase: "review", milestone: "borrador_listo", revision }`. Si el compilador encuentra problemas: `ok: false` con `issues[]` y la sesión **permanece** en `borrador_listo`. Guardas: hito distinto de `borrador_listo` → `422`; `base_revision` obsoleto → `409`.

**Canvas / validación / historial** (editor visual TW12):

```bash
curl -fsS -b "$JAR" -X PUT "$API/api/co-creation/sessions/<SESSION_ID>/canvas" \
  -H 'Content-Type: application/json' -d '{"base_revision":<REV>,"payload":{"purpose":"..."}}'
curl -fsS -b "$JAR" -X POST "$API/api/co-creation/sessions/<SESSION_ID>/validate" \
  -H 'Content-Type: application/json' -d '{"payload":{"purpose":"..."}}'
curl -fsS -b "$JAR" "$API/api/co-creation/sessions/<SESSION_ID>/history"
```

`validate` es previsualización pura (render + compile, sin mutación). Claves de autoridad en el `payload` → `422 invalid_envelope`.

**Publicar** (el POST **es** la aprobación explícita; versión inmutable):

```bash
curl -fsS -b "$JAR" -X POST "$API/api/co-creation/sessions/<SESSION_ID>/publish" \
  -H 'Content-Type: application/json' -d '{"base_revision":<REV>}'
```

Esperado (`200`): `{ session_id, phase: "complete", revision, published: { skill_id, version, name, description, digest, published_at } }`. Re-publicar contenido cambiado → `409 already_published`; trigger no aprobado → `409 trigger_not_approved`; sin borrador materializado → `422`.

**Activar** la versión publicada a un mundo:

```bash
curl -fsS -b "$JAR" -X POST "$API/api/co-creation/sessions/<SESSION_ID>/activate" \
  -H 'Content-Type: application/json' -d '{"base_revision":<REV>,"world":"vibrantes"}'
```

Esperado (`200`): `{ session_id, phase, revision, activation: {...} }`. Requiere versión publicada (`422 not_published` si no).

**Derivar** (adaptación TW13 desde una publicada — obligatoria para `Oficiales`):

```bash
curl -fsS -b "$JAR" -X POST "$API/api/co-creation/derive" \
  -H 'Content-Type: application/json' \
  -d '{"skill_id":"narrative-character-creation","version":"1.2","world":"vibrantes"}'
```

Esperado (`200`): `{ session_id, draft_id, derived_from: { skill_id, version } }`. El servidor inyecta la procedencia (`parent_skill_id`/`parent_version`) y auto-versiona `parent_version+1`; la original permanece intacta.

### Paso 5 — Importar un paquete y consumo guiado

**Importar** (`.zip` a cuarentena obligatoria; nunca muta la biblioteca):

```bash
curl -fsS -b "$JAR" -X POST "$API/api/methodologies/import" \
  -F 'file=@/ruta/al/paquete.zip' -F 'origin=community'
```

Esperado (`200`): `{ package_id, verdict: { ok, checksum_valid, signature_present, signature_valid, issues }, trusted: false, draft_id: null, clasificacion, trust_attributes }`.

**Listar cuarentena** y **confiar** (promueve a borrador editable):

```bash
curl -fsS -b "$JAR" "$API/api/methodologies/quarantine"
curl -fsS -b "$JAR" -X POST "$API/api/methodologies/quarantine/<PACKAGE_ID>/trust"
```

Esperado: `{ package_id, trusted: true, draft_id, clasificacion, trust_attributes }`. El id fundacional reservado `narrative-character-creation` → `409 reserved_skill_id`; paquete que ya no revalida → `422 trust_rejected`.

**Publicar y activar** el borrador importado, y **consumir** en el guiado:

```bash
curl -fsS -b "$JAR" -X POST "$API/api/methodologies/drafts/<DRAFT_ID>/publish"
curl -fsS -b "$JAR" -X POST "$API/api/methodologies/activate" \
  -H 'Content-Type: application/json' \
  -d '{"world":"vibrantes","skill_id":"<SKILL>","version":"<VERSION>","flow_type":"guided-character"}'
curl -fsS -b "$JAR" -X POST "$API/api/vibrantes/guided-character/session" \
  -H 'Content-Type: application/json' -d '{"author_input":"crear un personaje nuevo"}'
```

Esperado: al iniciar el guiado, la sesión fija la **versión activada** (`_active_methodology_snapshot(mundo, "guided-character")`). Verificar con:

```bash
curl -fsS -b "$JAR" "$API/api/vibrantes/guided-character/session/<SESSION_ID>"
```

El guiado requiere **Hermes real** (gate semántico + proveedor guiado); si el gateway falta, falla cerrado con el sobre `blocked` localizado.

**Exportar** una versión publicada (opcional, cierra el ciclo):

```bash
curl -fsS -b "$JAR" -X POST "$API/api/methodologies/published/<SKILL>/<VERSION>/export" -o paquete.zip
```

---

## Checklist con resultados esperados

| # | Verificación | Resultado esperado | ¿Bloqueado hoy? |
|---|---|---|---|
| 1 | `GET /health` | `200` | No |
| 2 | `GET /api/methodologies/inventory?fundacional=true` | `narrative-character-creation` `Oficiales`+`fundacional`; `1.2` (nueva) o `1.0/1.1/1.2` (existente) | No |
| 3 | `POST /api/methodologies/activate` + `GET .../active/{world}` | Eco de activación; slot refleja la versión | No |
| 4 | `POST .../companions/activate` + `status` | `companion` presente; `422` sobre el límite | No |
| 5 | Router vía `POST /api/{mundo}/ai/ask` | Sobre semántico; decisión en memoria de conversación; fallos abiertos según SR3 | No (requiere gateway) |
| 6 | `POST /api/co-creation/sessions` | `200`, `milestone=proposito`, primera pregunta | No (requiere gateway) |
| 7 | `POST .../turn` con `base_revision` | `200`, revisión+1, una pregunta | No (requiere gateway) |
| 8 | Superar 20 preguntas | `422 ceiling_reached`, cero mutación | No |
| 9 | Sobre con clave de autoridad (stub) | `422 invalid_envelope`/`502 malformed_output`, cero mutación | Manual/opcional |
| 10 | `POST .../materialize` en `borrador_listo` | `{ draft_id, ok: true }`, `phase=review` | No |
| 11 | `PUT .../canvas` / `POST .../validate` | `ok` + `issues[]`; validación sin mutación | No |
| 12 | `POST .../publish` | `phase=complete` + `published{digest}` | Depende de #10 |
| 13 | `POST /api/co-creation/derive` | `{ draft_id, derived_from }`, versión parent+1 | No |
| 14 | `POST /api/methodologies/import` + `/trust` | Cuarentena con veredicto; borrador tras confiar; `409` para el id reservado | No |
| 15 | Publicar/activar el import + `guided-character/session` | Sesión guiada fija la versión activada | No (requiere gateway) |

---

## Qué capturar si algo falla

Adjunta al reporte del gate, como mínimo:

1. **Comando exacto + status HTTP + cuerpo JSON** de la llamada fallida (incluye `detail` y `code`; p. ej. `capability_unavailable`, `ceiling_reached`, `invalid_envelope`, `revision_conflict`).
2. **Estado de la sesión de co-creación**: `GET /api/co-creation/sessions/<id>` (marca `revision`, `milestone`, `phase`, `draft_id`).
3. **Snapshot del sobre crudo de Hermes** cuando el fallo sea `malformed_output`/`invalid_envelope` (si tienes acceso al log del gateway).
4. **Log de la API**: `<repo>/logs/demiurgos-api.log` (y `demiurgos-gateway.log`). `LOG_DIR` = `<install_root>/logs`; en modo dev `<install_root>` es la raíz del repo.
5. **Almacenes**: `data/methodology/library.json` (publicadas/activaciones/compañeros), `<data_root>/data/co-creation-sessions.sqlite3` (o `DEMIURGOS_CO_CREATION_SESSIONS_DB`), `data/methodology/materialization-sessions.json` (runtime, no versionado) y `<data_root>/data/conversation-memory.sqlite3` (ruteo).
6. **Commit y config**: `git rev-parse HEAD`, `DEMIURGOS_AUTH_MODE`, y si el gateway responde al probe de capacidades.

> Nota: **no** subas el `.env` ni claves del gateway; censura `HERMES_GATEWAY_KEY` en cualquier captura.

---

## Siguiente paso

- Co-creación completa: el seam `_CO_CREATION_MATERIALIZER` ya está cableado en `api_server.py` (enlace perezoso junto a `_CO_CREATION_PROVIDER`), así que los pasos 4–5 se pueden validar de extremo a extremo en el gate sin cambios de código.
- Contrato de superficie del Taller: `docs/architecture/tool-workshop.md` (§8).
- Contrato de selección/ruteo: `docs/architecture/skill-runtime-consumption-contract.md`.
- Subsistema técnico (biblioteca, compilador, ciclo de vida): `docs/architecture/skill-library-and-guided-character-creation.md`.
