# Auditoría de preparación para el MVP — sistemas y portabilidad

> **Documento clave de trabajo.** Registra el inventario de sistemas montados, sus
> interconexiones y los huecos verificados que deben resolverse antes de lanzar el
> MVP. Cada hallazgo tiene ID estable, evidencia y criterio de aceptación.
>
> - Fecha de la auditoría: 2026-11-02
> - Base: `master` en `ef2171e`
> - Alcance: plataforma completa (frontend, backend, Hermes, almacenamiento,
>   grafo, workflows, instalación y entrega)
> - Carácter: auditoría de solo lectura; este documento es el plan de resolución
>
> **Cómo usarlo:** tomar un `AUD-xx`, leer su evidencia, implementar el fix y
> cumplir su criterio de aceptación. No borrar hallazgos: marcarlos `resuelto`
> con el commit que los cierra. Un hallazgo sin evidencia no entra; uno resuelto
> sin criterio de aceptación cumplido no se cierra.

---

## 1. Método de la auditoría

Se cruzaron cuatro oráculos independientes para no depender de una sola fuente:

1. **Docs de contrato**: `docs/architecture/demiurgos-platform.md`,
   `INSTALL_LAYOUT.md`, `CONTENT_AND_STATE.md`, `onboarding-and-configuration.md`,
   `docs/install/SUPPORT_MATRIX.md`, `docs/RELEASING.md`.
2. **Código real**: entrypoints, routers (202 endpoints: 137 en `api_server.py`
   + 65 en routers), launchers, instaladores, stores, transportes.
3. **Tests**: 217 archivos backend (wiki, sync_lore, idea_capture) y 138 archivos
   / 1734 casos frontend.
4. **Artefactos de entrega**: `payload_manifest.json`,
   `.github/workflows/release.yml`, `.github/workflows/ci.yml`, canal firmado y
   historial de CI en GitHub.

Verificaciones específicas de portabilidad:

- Auditoría de imports contra `requirements.lock` y `requirements-optional.txt`.
- Completitud del payload contra el árbol real (archivo por archivo).
- Rutas absolutas, puertos y supuestos de OS en código y scripts.
- Secretos en el inventario de backup.
- Reproducción local del boot desde el payload (`test_payload_boot.py`).
- Estado real de CI en `master` y de los jobs que se ejecutan o se saltean.

---

## 2. Matriz soportada (fuente: `SUPPORT_MATRIX.md`)

| Plataforma | Arquitectura | Requisito |
|---|---|---|
| Windows 10 / 11 | x86_64 | rutas largas habilitadas |
| macOS | arm64 (Apple Silicon) | macOS ≥ 13 |
| Linux | x86_64 / aarch64 | glibc ≥ 2.28 |

No soportados (el instalador falla rápido con mensaje claro): macOS Intel,
musl/Alpine y glibc < 2.28. Node y Python no son requisitos del usuario final:
el instalador provee Python 3.12 vía `uv` y el SPA viaja precompilado.

---

## 3. Inventario de sistemas montados

| Capa | Sistemas | Estado |
|---|---|---|
| **Arranque** | Instaladores POSIX/Windows, launchers POSIX/Windows, updater, system control, atajos Linux/Windows | Montados; ver AUD-03 |
| **API** | Auth/vault, wiki/editor, grafo, asistente, creación guiada, co-creación, relaciones, conflictos, importador, ideas, backup, data-root, onboarding, i18n, bug report, migración, readiness | 202 endpoints; 106 módulos wiki + 17 de backup |
| **Frontend** | 14 páginas, 100 componentes, 22 clientes API; SPA servida desde `frontend/dist` | Montado |
| **Persistencia** | Content root (mundos, ideas, plantillas, config, metodologías) y state root (6 SQLite, sesiones, locks, trash, spool, evidencia) | Separación correcta |
| **IA** | Gateway Hermes, proveedores texto/visión, gate semántico, enriquecimiento, visión de importación | Dependencia crítica de Hermes; ver AUD-04 |
| **Metodologías** | Seeds, biblioteca, compilador, trust, activación, co-creación, skills narrativas | Biblioteca y bridge al runtime montados |
| **Integraciones** | Telegram (vía Hermes), carpeta sincronizada (backup), canal de releases firmado, relay de bug reports | Telegram y asistente dependen de Hermes |
| **Entrega** | Matriz de 4 celdas, wheels-only, minisign, smoke post-publicación | Diseño sólido; ver AUD-01 y AUD-02 |

### 3.1 Fortalezas verificadas (no tocar sin motivo)

- Separación content root / state root con adopción idempotente y evidencia de
  migración (`CONTENT_AND_STATE.md`, `state_root_migration.py`).
- Backup con GFS, exclusión explícita de secretos (`.env`, `*.key`, `*.pem`,
  `credentials*`), snapshots SQLite por `Connection.backup()` y gate de restore.
- Instalador sin admin, sin compilador y con cierre de dependencias wheels-only;
  pruebas de cierre por celda (`scripts/closure_proof.sh`).
- Release firmado (minisign), canal separado del repo privado, smoke anónimo que
  instala y bootea el artefacto publicado.
- Suite amplia: 1734 casos frontend; 217 archivos backend; tests de invariantes
  de seguridad (gating, revisión, digests, tokens de un solo uso).

---

## 4. Interconexiones principales

- Onboarding → cuenta/vault → content folder → mundo → editor gated → grafo.
- Editor/creación guiada → propuestas diskless → diff+digest+token → escritura
  gated → `ReindexCoordinator` → grafo.
- Importador → análisis → apply gated → grafo y relaciones; visión por proveedor;
  enriquecimiento LLM vía Hermes.
- Ideas → materialización → mundo → grafo; ingesta Telegram vía Hermes.
- Relaciones/conflictos → barrido semántico (Hermes) → propuestas → decisión del
  Autor → reconciliación.
- Metodologías → seeds al boot → biblioteca → co-creación → activación por mundo
  → snapshot pinneado en la sesión guiada.
- Backup → content root + state root → carpeta sincronizada externa → restore en
  otra máquina (secretos excluidos y servicios revalidados).
- Update → canal firmado → instalador → `current` atómico → rollback acotado.

---

## 5. Hallazgos

### P0 — bloquean instalación, release o asistente

#### AUD-01 — El manifiesto del payload está desactualizado

- **Estado (2026-11-02)**: implementado en `097201c` — manifiesto regenerado
  (187 archivos, con los cuatro `conflict_*.py`) y gate de frescura
  `scripts/derive_payload_manifest.py --check` como job de CI. Verificado en
  local: `test_payload_boot.py` 4 passed, derivador verde, installer contract
  POSIX 119 passed / 5 skipped. CI verde en PR #74 (run `41536146433`): las
  cuatro celdas de backend, `Installer smoke` y `PowerShell 5.1` pasan.
  Pendiente: verde en `master` y boot del paquete de release publicado (AUD-16).
- **Impacto**: el paquete publicado no contiene cuatro módulos que `api_server`
  importa al arrancar; la app instalada no bootea. El smoke de release lo
  detectaría recién al publicar.
- **Evidencia**:
  - `payload_manifest.json` no lista `conflict_decisions.py`,
    `conflict_detector.py`, `conflict_proposing.py` ni `conflict_sweep.py`.
  - `api_server.py:69-82` los importa en top-level.
  - `pytest src/tools/demiurgos-suite/wiki/tests/test_payload_boot.py` falla con
    `ModuleNotFoundError: No module named 'conflict_decisions'` (reproducido).
  - `scripts/derive_payload_manifest.py` regenerado agrega exactamente esos
    cuatro y actualiza `source_commit`.
  - El empaquetado (`release.yml`) lee el manifiesto tal cual; no lo regenera.
- **Fix**: regenerar el manifiesto y agregar un gate de frescura en CI que falle
  cuando el manifiesto difiera de la salida del derivador.
- **Aceptación**: `test_payload_boot.py` verde; gate de frescura verde en PR;
  paquete de release bootea `/health` y `/` en las cuatro celdas.

#### AUD-02 — CI en rojo y el backend queda salteado

- **Estado (2026-11-02)**: implementado en `097201c` — el aislamiento del test
  de `ProposalsPanel` ya estaba verde en CI (run `41494138986`,
  `Frontend (windows-latest)` success); `backend`, `launcher`,
  `static-serving` y `ps51` ahora consumen un job `frontend-build` que solo
  compila y publica el artefacto, nunca el resultado de los tests de frontend.
  CI verde en PR #74 (run `41536146433`). Pendiente: verde en `master` tras el
  merge.
- **Impacto**: `master` no está verde y el job de backend no corre, por lo que
  AUD-01 no se detecta en PRs. El riesgo llega al tag de release.
- **Evidencia**:
  - Run `41385285824` (2026-11-02 03:51): fallan `Installer smoke` y
    `Frontend (windows-latest)`; backend, launcher, static-serving y PowerShell
    quedan `skipped`.
  - `frontend/src/__tests__/ProposalsPanel.test.tsx:121`: espera
    “Revisar 1 ficha” y recibe “Revisar 5 fichas” (aislamiento de mocks).
  - `backend` declara `needs: frontend` solo para obtener `frontend/dist`.
- **Fix**: corregir el aislamiento del test de Windows y desacoplar el job de
  backend del resultado de frontend (descargar el artefacto sin heredar el
  fallo), manteniendo el orden de publicación.
- **Aceptación**: CI verde en `master` y en PR; un fallo de frontend no saltea el
  backend; `test_payload_boot` corre siempre.

#### AUD-03 — El layout del launcher Windows no coincide con el paquete

- **Estado (2026-11-02)**: implementado en `30ca73d` — las dos celdas de
  empaquetado copian `start-demiurgos.ps1` a `<current>\scripts\`, el instalador
  imprime esa ruta, el helper de accesos la prefiere y un test de deriva falla
  si vuelve a aparecer una mención en la raíz fuera de una copia. Verificado en
  local con el guard test y el installer contract POSIX, y en Windows por
  `PowerShell 5.1 contract`, `Launcher (windows-latest)` e `Installer smoke` en
  PR #74 (run `41536146433`). Pendiente: instalación Windows real y AUD-16.
- **Impacto**: en una instalación Windows, reiniciar/apagar desde la UI falla
  cerrado, el rollback no encuentra versión previa y el comando de arranque que
  imprime el instalador apunta a un archivo inexistente.
- **Evidencia**:
  - El release copia `start-demiurgos.ps1` a `<current>/` (extras de
    `release.yml`).
  - Esperan `<current>/scripts/start-demiurgos.ps1`: `api_server.py:11020`,
    `start-demiurgos.ps1:268,310`, `INSTALL_LAYOUT.md:23`, `install.ps1:179`,
    `ONE_SCREEN_GUIDE.md:53`.
  - El fixture de `test_installer_contract.py` fabrica `scripts\...`, por eso el
    test no detecta el mismatch.
- **Fix**: elegir un único layout y alinear paquete, launcher, backend, docs y
  tests; agregar un test que bootee el payload Windows real (no un fixture que
  fabrique el layout).
- **Aceptación**: instalación Windows real arranca con el comando impreso;
  `/api/system` reinicia; el rollback encuentra la versión previa.

#### AUD-04 — El install de un comando no provisiona el runtime del asistente

- **Impacto**: el asistente, la creación guiada, la co-creación y los barridos
  semánticos quedan inoperables en una instalación limpia. Onboarding los reporta
  `pending` (honesto), pero el MVP promete el asistente.
- **Evidencia**:
  - `install.sh` sin flags instala solo la web app; Hermes/Engram entran con
    `--with-cli-stack`.
  - `ai/ask`, edit-suggest, creación guiada y co-creación usan el gateway
    (`_SEMANTIC_PROVIDER`, `_GATEWAY_URL`, `_sync_hermes_enricher`).
  - `readiness.py` exige `runtime=accepted` para marcar el asistente configurado.
  - El README dice que Hermes “no es necesario para usar la web app”, pero el
    asistente es una capacidad central.
- **Decisión pendiente (producto)**: (A) provisionar Hermes en el install
  default; (B) implementar un camino provider-direct sin gateway; (C) mantenerlo
  opt-in y declarar honestamente que el asistente requiere el CLI stack.
- **Aceptación**: una instalación limpia alcanza un asistente funcional por el
  camino elegido, o la UI declara la limitación sin ambigüedad; onboarding y
  README coinciden con el camino elegido.

### P1 — degradación o promesa incumplida

#### AUD-05 — `collect-diagnostics.sh` no está en el payload

- **Evidencia**: `ONE_SCREEN_GUIDE.md:65` manda ejecutar
  `<current>/scripts/collect-diagnostics.sh`; el archivo no está en
  `payload_manifest.json` ni en los extras de `release.yml`.
- **Fix**: incluirlo en el payload (y en el audit allow-list) o cambiar la guía.
- **Aceptación**: el comando del paso “Si algo falla” funciona en una instalación
  limpia.

#### AUD-06 — PDF incompleto: PyMuPDF no está declarado

- **Evidencia**: `sync_lore/image_indexer.py:169` importa `fitz` (PyMuPDF) con
  degradación silenciosa; no figura en `requirements.lock` ni en
  `requirements-optional.txt`. El texto PDF depende de `markitdown[pdf]`
  (opcional). `SUPPORT_MATRIX.md` promete `.docx/.pdf` completo.
- **Fix**: declarar PyMuPDF como dependencia (mandatoria u opcional explícita) y
  ajustar la matriz o la degradación visible.
- **Aceptación**: un `.pdf` con imágenes se importa completo en cada target
  soportado, o la UI/doctor informa la limitación.

#### AUD-07 — VPS: bind local y auth loopback

- **Evidencia**: `README.md:61` afirma soporte VPS; `api_server.py:12298` y el
  launcher bindean `127.0.0.1`; `local-dev` exige loopback
  (`api_server.py:1945`). No hay guía de reverse proxy ni variable de bind.
- **Fix**: documentar el despliegue con proxy y `credentials`, o agregar bind
  configurable con valores por defecto seguros.
- **Aceptación**: una guía reproducible de VPS con TLS/proxy y modo de auth
  correcto, verificada de punta a punta.

#### AUD-08 — Auth `disabled` por defecto al correr desde fuente

- **Evidencia**: `_auth_mode()` cae a `"disabled"` sin `DEMIURGOS_AUTH_MODE`; el
  instalador siembra `local-dev`, pero la vía manual no.
- **Fix**: fallar cerrado o sembrar `local-dev` también en la vía manual;
  documentar el modo.
- **Aceptación**: ninguna instalación queda sin auth por omisión; los tests
  cubren el default.

#### AUD-09 — `es-ar` vive solo en el wizard retirado; la UI soporta `es`/`en`

- **Evidencia**: `SUPPORTED_UI_LANGUAGES = frozenset({"es", "en"})`
  (`demiurgos_language.py:35`); el locale `es-ar` existe en
  `src/tools/web-config-ui/i18n.py`, retirado según
  `onboarding-and-configuration.md §13`.
- **Impacto**: la decisión de conservar `es-ar` como opción no tiene superficie
  viva.
- **Fix**: decidir si se implementa la variante en onboarding/Centro o se retira
  el locale legacy; actualizar `REGLAS_LENGUAJE.md` en consecuencia.
- **Aceptación**: la decisión queda reflejada en una superficie viva o el código
  legacy se retira.

#### AUD-10 — Drift entre docs y código

- **Evidencia**:
  - La constitución marca como `[OBJETIVO]` el bridge metodología→runtime, pero
    `guided_character_provider.py` ya recibe el snapshot pinneado.
  - Engram figura como “obligatorio para co-creación” y el runtime web usa SQLite.
  - `requirements.txt` menciona macOS x86_64 como target aunque la matriz lo
    excluye.
  - README dice que Hermes no es necesario, pero el asistente lo requiere.
- **Fix**: una pasada de reconciliación docs↔código; etiquetar cada afirmación.
- **Aceptación**: la constitución y los contratos no contradicen el runtime; un
  lector puede decidir sin releer todo el código.

### P2 — higiene y cobertura

| ID | Hallazgo | Evidencia | Fix mínimo |
|---|---|---|---|
| AUD-11 | `relay/` sin job de CI | `.github/workflows/ci.yml` no lo ejecuta | agregar job `relay` (test + typecheck) |
| AUD-12 | `engram_sync` documentado pero no arrancado | README lo cita; ningún launcher lo inicia; el importer ya retiró su adaptador | retirar la promesa o cablearlo |
| AUD-13 | Dev tools con deps no declaradas | `sync-ideas.py`/`dev_diary.py` → `googleapiclient`; `opencode-bridge.py` → `faster_whisper` | declararlas en un requirements de dev o retirar los scripts |
| AUD-14 | Sin integración de escritorio en macOS | solo Linux `.desktop` y Windows shortcuts | decidir si se agrega `.app`/alias |
| AUD-15 | Puertos fijos sin fallback | 8000/8642; el launcher rechaza si los ocupa un proceso ajeno | documentar overrides o elegir puerto libre |
| AUD-16 | Sin test de payload Windows real | el fixture fabrica `scripts\start-demiurgos.ps1` | bootear el paquete Windows empaquetado |
| AUD-17 | `web-config-ui` retirado pero aún editable | se editó su i18n en `ef2171e` | congelar o retirar el árbol |

---

## 6. Orden de resolución recomendado

| Ola | Objetivo | Hallazgos | Nota |
|---|---|---|---|
| **0** | Desbloquear release y CI | AUD-02, AUD-01, AUD-03 | Sin esto no hay paquete confiable |
| **1** | Asistente y promesas del MVP | AUD-04 (decisión primero), AUD-05, AUD-06 | AUD-04 requiere decisión del Owner |
| **2** | Despliegue y consistencia | AUD-07, AUD-08, AUD-09, AUD-10 | VPS, auth, idioma y docs |
| **3** | Higiene y cobertura | AUD-11 … AUD-17 | Puede ir en paralelo con la ola 2 |

Regla de cierre: cada `AUD-xx` se marca `resuelto` solo con su criterio de
aceptación verificado y el commit que lo cierra registrado en este documento.

---

## 7. Plan de validación en máquina limpia

Ejecutar la matriz completa en Linux x86_64, macOS arm64 y Windows 10/11.

- [ ] **Instalación**: canal firmado; `current` correcto; `/health` y `/`
      responden; data root y state root en sus rutas; logs persistentes.
- [ ] **Ciclo de vida**: start / restart / stop / rollback; sin procesos
      huérfanos; segunda instancia no duplica.
- [ ] **Onboarding**: idioma/región/tz; cuenta y vault; content folder; crear e
      importar mundo; readiness honesta; modo offline.
- [ ] **Núcleo local**: CRUD gated; papelera e historial; búsqueda, grafo y
      backlinks; export PDF/DOCX.
- [ ] **Importador**: `.md`, `.docx` y `.pdf` con imágenes; visión; enriquecimiento
      con y sin Hermes.
- [ ] **IA**: asistente, SSE, edit-suggest, creación guiada y co-creación con
      Hermes presente y ausente; confirmar la degradación declarada.
- [ ] **Canon**: barridos de relaciones y conflictos; aceptar/rechazar;
      reconciliación; reindex.
- [ ] **Ideas**: captura manual y Telegram; materialización a mundo.
- [ ] **Metodologías**: instalar, activar, rollback; pin en sesión guiada.
- [ ] **Backup/restore** en una segunda máquina: secretos excluidos; servicios
      revalidados; grafo reconstruido.
- [ ] **Update/rollback**; bug report con relay on/off; diagnóstico.
- [ ] **Casos límite**: rutas con espacios y unicode; Documents localizado; sin
      Node/Python previos; sin admin; puertos ocupados; dos instancias.

---

## 8. Anexo: comandos de verificación

```bash
# Backend (grupos separados para evitar contaminación de orden entre conftests)
.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q
.venv/bin/python -m pytest src/tools/sync_lore/tests/ -q
.venv/bin/python -m pytest src/tools/idea_capture/tests/ -q

# Boot desde el payload (detecta AUD-01)
.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/test_payload_boot.py -q

# Frescura del manifiesto (propuesto; hoy no existe)
.venv/bin/python scripts/derive_payload_manifest.py
git diff --exit-code payload_manifest.json

# Frontend
cd frontend && npm test -- --run && npm run typecheck && npm run build

# CI
gh run list --limit 5
```

---

## 9. Límites de esta auditoría

- No se ejecutó una instalación real en una VM limpia ni la suite backend
  completa de una sola corrida (hay contaminación de orden conocida entre
  conftests).
- El inventario se deriva de routers, docs, tests y artefactos, no de probar uno
  por uno los 202 endpoints.
- AUD-01 está reproducido localmente; AUD-02 y AUD-03 se sostienen en el
  empaquetado, el historial de CI y la lectura del código.
- Este documento no autoriza cambios: cada `AUD-xx` se implementa con su propio
  alcance y verificación.

---

## 10. Registro de cambios

| Fecha | Cambio |
|---|---|
| 2026-11-02 | Creación del documento con la auditoría completa y el backlog AUD-01…AUD-17 |
| 2026-11-02 | Ola 0: AUD-01 y AUD-02 implementados en `097201c`; AUD-03 implementado en `30ca73d`; gate de frescura cross-platform en `77d6a89`. CI verde en PR #74 (run `41536146433`, 18/18 checks). Falta el verde en `master` y la instalación Windows real |
