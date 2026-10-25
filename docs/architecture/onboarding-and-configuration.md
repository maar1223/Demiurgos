# Onboarding y Centro de Configuración — Contrato de Producto y Arquitectura

> **Contrato de producto/arquitectura.** Este documento es el contrato de **superficie y producto** del **onboarding inicial** de Demiurgos y de su **Centro de Configuración permanente**: el orden del primer arranque, qué es bloqueante y qué opcional, y cómo el Autor retoma capacidades pendientes sin repetir el onboarding. **No es un artefacto SDD** ni sustituye a la constitución global; el SDD de implementación futuro tendrá su propia Definition of Ready (sección 15). Toda afirmación lleva la etiqueta de estado correspondiente; lo que no está etiquetado `[ACTUAL]` no debe presentarse como existente. Los contratos técnicos vecinos (importador, Taller de Mundo, Taller de Herramientas) se referencian sin duplicarse.

| Campo | Valor |
|---|---|
| Estado | Contrato de producto/arquitectura (consolidación de decisiones de onboarding y configuración; diseño objetivo) |
| Versión del documento | 1.1 |
| Fecha | 2026-08-17 |
| Autor | Demiurgos (orquestación) |
| Idioma | Español neutro (prosa técnica) |
| Alcance | Onboarding inicial (orden MVP, bloqueantes/opcionales), Centro de Configuración permanente, idioma/región/zona horaria, identidad Google, comportamiento offline, modelos/proveedores de IA locales y remotos (configuración del modelo principal del Asistente, multimodalidad obligatoria, prueba causal de visión y descubrimiento por runtime), mundo como último paso operativo, estructura Lore recomendada para mundos nuevos, respaldo, estado "Listo para Trabajar", retiro del wizard legacy `web-config-ui` y decisiones abiertas |
| Depende de | `docs/architecture/demiurgos-platform.md` (constitución global del producto) |
| Relación con SDD | Requisito previo. Ningún SDD de onboarding o Centro de Configuración debe comenzar sin este contrato aprobado y sus decisiones abiertas (sección 14) resueltas |
| Documentos relacionados | `docs/architecture/demiurgos-platform.md`, `docs/architecture/world-importer.md` y `docs/architecture/world-importer-ui.md` (importador de mundo y restauración), `docs/architecture/world-workshop.md` (Taller de Mundo — árbol físico, vistas semánticas, Borrador vs Canon), `docs/architecture/tool-workshop.md` (Taller de Herramientas — vocabulario Metodologías/Plantillas/Catálogos/Referencias), `AGENTS.md` (orquestador), configurador actual del Asistente (`frontend/src/components/organisms/AssistantSettingsPanel.tsx`, backend en `src/tools/demiurgos-suite/wiki/assistant_settings.py` y `assistant_provider_adapters.py`), fixture de prueba de visión (`src/tools/capability_probes/fixtures/logo-demiurgos.jpg`), legacy runtime en `src/tools/web-config-ui/`, `install.sh`, `sdd/web-config-ui/spec.md` (especificación histórica del wizard legacy) |

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
- La **decisión global G11** (`[DECISIÓN CERRADA]`) ya acordó que el onboarding configura **idioma, modelos LLM e importar/crear mundo**, que la **carpeta sincronizada de Google Drive es no bloqueante**, que el **árbol espejo por taller** se escribe en esa carpeta, que hay **sync 30 s tras editar** y **restauración Google→Demiurgos**. Este contrato **consolida y ordena** esa decisión en el orden MVP de la sección 2 sin reabrirla. El cliente de sincronización queda fuera de la arquitectura y lo elige el operador.
- El **importador de mundo** (producto y arquitectura en `docs/architecture/world-importer.md`; superficie en `docs/architecture/world-importer-ui.md`) es el contrato del flujo "importar mundo existente"; la **restauración desde respaldo** es un flujo distinto (IM9) y este contrato no la convierte en una modalidad de importación.
- El **Taller de Mundo** gobierna el **árbol físico del mundo propiedad del Autor**, las **vistas semánticas** (W9, W10) y el **gobierno de canon** Borrador vs Canon (W3–W5, W11). La estructura Lore recomendada de la sección 8 opera **dentro** de esas reglas y no las redefine.
- El **Taller de Herramientas** fija el vocabulario **Metodologías / Plantillas / Catálogos / Referencias** (`docs/architecture/tool-workshop.md`, sección 1.1); este contrato lo referencia sin duplicarlo (sección 9).
- El asistente visible se llama **Asistente de Demiurgos**; "Hermes" es el nombre interno del proveedor y no aparece en la copia visible (constitución, G15/10.6). En este contrato técnico se menciona "Hermes" solo para denotar capacidades internas (secciones 2 y 12), nunca como nombre de superficie.
- En caso de conflicto, prevalece la constitución; la contradicción se reporta al Autor.

---

## 1. Propósito y no repetición del onboarding

**[DECISIÓN CERRADA — OC1]** Demiurgos tiene **dos superficies de configuración** con responsabilidades distintas:

| Superficie | Rol | Duración |
|---|---|---|
| **Onboarding inicial** | Primer arranque: secuencia mínima para dejar la instalación operativa (sección 2) | **Una sola vez**; no se repite |
| **Centro de Configuración** | Superficie permanente para revisar y completar capacidades | Indefinida; accesible siempre (sección 12) |

- El onboarding **no se repite para completar capacidades pendientes**: si una capacidad no bloqueante se omite (p. ej. Telegram o respaldo), **no se vuelve a ofrecer el onboarding completo**; la capacidad queda **pendiente** y se retoma **desde el Centro de Configuración**, sección por sección. `[DECISIÓN CERRADA — OC1]`
- El estado de cada capacidad se persiste y se consulta desde el Centro; el onboarding solo declara qué se dejó pendiente, sin insistir. `[DECISIÓN CERRADA — OC1]`
- El paso 5 "Listo para Trabajar" es el **único punto de salida** del onboarding; una vez salido, el Autor solo vuelve a las superficies de configuración a través del Centro. `[DECISIÓN CERRADA — OC1]`

---

## 2. Orden del MVP

**[DECISIÓN CERRADA — OC2]** El orden de pasos del onboarding MVP es el siguiente. Consolida la decisión G11 (idioma, modelos LLM e importar/crear mundo; Google no bloqueante) y la ordena:

| Paso | Capacidad | Bloqueante | Notas |
|---|---|---|---|
| **0** | Bienvenida, idioma, región, zona horaria | **Bloqueante** | Requisito para proseguir; detalle en sección 3 |
| **1** | IA texto y visión | **Bloqueante para las capacidades de IA**, no para el núcleo local | Con soporte de **configuración local/offline** desde el MVP (secciones 5–6); puede omitirse temporalmente sin bloquear pasos posteriores no-IA |
| **2** | Telegram | **Opcional** | **Único servicio de mensajería inicial**, usando las capacidades internas de Hermes (proveedor conversacional); la captura de ideas por Telegram ya existe como ingesta (`[ACTUAL]` — constitución, sección 4, captura de ideas) |
| **3** | Mundo: crear desde cero o importar | **Bloqueante para entrar al Taller de Mundo** | **Último paso operativo** del onboarding; detalle en secciones 7–8 |
| **4** | Respaldo (carpeta sincronizada) | **Opcional, posterior al mundo** | Detalle en sección 10 |
| **5** | Listo para Trabajar / resumen | — | Punto de salida; detalle en sección 11 |

- La **generación/regeneración profunda de imágenes queda fuera del MVP**: el paso 1 incluye **visión como análisis** (texto y visión), no la generación de imágenes de personaje, cuyo alcance sigue siendo decisión global abierta (constitución, G5). `[DECISIÓN CERRADA — OC2]`
- Los pasos **opcionales no bloquean el avance**: se marcan pendientes y se retoman desde el Centro de Configuración (sección 12). `[DECISIÓN CERRADA — OC2]`
- El orden es **estricto**: el paso 3 (mundo) es el último operativo y el paso 4 (respaldo) va **después** de que exista un mundo; no hay respaldo configurable antes del mundo. `[DECISIÓN CERRADA — OC2]`

---

## 3. Idioma, región y zona horaria

**[DECISIÓN CERRADA — OC3]** El paso 0 define la localización con estas reglas:

| Regla | Contenido |
|---|---|
| **Idioma y variante sugeridos por región** | La región (geografía detectada o elegida) **sugiere** idioma y variante, con **override explícito** del Autor; la sugerencia nunca se aplica en silencio |
| **Zona horaria IANA** | Se usa un identificador de zona IANA (p. ej. `America/Argentina/Buenos_Aires`), **no** un offset numérico fijo |
| **Timestamps internos UTC** | El almacenamiento interno y las comunicaciones usan **UTC**; la zona IANA solo gobierna la **presentación** |
| **Título humano local** | Fechas y horas se muestran en el idioma y la zona elegidos, con formato comprensible para el Autor |
| **Sin dialecto forzado por región** | La región **no impone** un dialecto ni una variante lingüística; solo sugiere. La variante final la decide el Autor |
| **Lenguajes separados** | Se distinguen **tres dominios**: **lenguaje de UI**, **lenguaje de conversación** (asistente) y **lenguaje de contenido** (prosa del mundo). Cada uno puede configurarse de forma independiente |

- El runtime de idioma sigue la decisión global **G7** (abierta en la constitución): hoy `DEMIURGOS_LANGUAGE` es estático y el frontend ya dispone de `useAppLanguage` (`[ACTUAL]` — `frontend/src/hooks/useAppLanguage.ts`, `demiurgos_language.py`). Este contrato **no reabre G7**; la separación UI/conversación/contenido de OC3 es compatible con cualquiera de sus opciones. `[DECISIÓN CERRADA — OC3]`
- La separación de lenguajes **no afecta** la regla de la constitución de que la estructura de las Skills es independiente del idioma y la presentación sigue el idioma configurado (`tool-workshop.md`, TW6). `[DECISIÓN CERRADA — referencia]`

---

## 4. Identidad

**[DECISIÓN CERRADA — OC4]** La identidad del Autor se contrata así:

| Regla | Contenido |
|---|---|
| **Google OAuth/OIDC como objetivo del MVP** | El inicio de sesión con cuenta Google (OAuth/OIDC) forma parte del **objetivo del MVP** (`[OBJETIVO]`), **no es comportamiento actual**; se prepara sin acoplar la arquitectura (coherente con la constitución, G3 y 10.3) |
| **Cuenta Google ≠ acceso a Google Drive** | Son **consentimientos separados**: autenticarse con Google no autoriza el acceso a Drive; el acceso a Drive (sección 10) requiere un consentimiento propio y explícito |
| **Identificador estable, no email** | La identidad usa un **identificador estable** de la identidad Google (`sub`/identificador de cuenta), **nunca el email como ID**; el email es dato de contacto, no clave de identidad |
| **Primer vínculo online** | El vínculo inicial de la identidad Google requiere **conexión online**; no hay vínculo de cuenta sin conexión |
| **Credencial local protegida** | La instalación conserva una **credencial local protegida** (no la contraseña de Google) que permite **continuar offline** tras el vínculo inicial |
| **Instalación nueva/formateada/VPS** | Una instalación nueva, una máquina formateada o un VPS **requiere revalidación online o una recuperación autorizada** para volver a vincular la identidad; no se reutiliza la credencial de otra instalación sin autorización |
| **Sin contraseñas de Google** | **No se almacenan contraseñas de Google**; solo los tokens de acceso/refresco necesarios, en un almacén protegido |

- El modelo de autorización base sigue siendo **monousuario/local** (constitución, G3) y la UX de autenticación al arrancar es la de la constitución 10.3 (modal automático, modo limitado accionable). `[DECISIÓN CERRADA — referencia]`
- La **revalidación online** es obligatoria en instalaciones nuevas, máquinas formateadas o VPS. La recuperación offline solo opera como **excepción autorizada**, con evidencia verificable y sin reutilizar silenciosamente la credencial de otra instalación. `[DECISIÓN CERRADA — OC23]`

---

## 5. Comportamiento offline

**[DECISIÓN CERRADA — OC5]** Demiurgos distingue capacidades **locales** y **remotas**:

| Capacidad | Disponibilidad offline | Notas |
|---|---|---|
| Mundos locales (los ya creados/cargados) | **Sí** | El mundo es un árbol local `mundos/{mundo}/` |
| Editor local (wiki, fichas, CRUD gated local) | **Sí** | Compuertas y escrituras funcionan en la instalación local |
| Ideas y plantillas | **Sí** | Captura nativa (`idea_capture`) y catálogos locales (`plantillas/`) |
| Grafo local | **Sí** | `EntityGraphIndex` deriva del contenido local |
| Remoto (Telegram) | **No** | Requiere conexión |
| Google Drive (respaldo/restauración) | **No** | Requiere conexión y consentimiento (sección 10) |
| Proveedores de IA en la nube | **No** | Requieren conexión; ver sección 6 |
| **Modelos locales de IA** | **Sí** | Configurables desde el MVP (sección 6) |

- **Sin LLM disponible** (ni local ni remoto), un **mundo nuevo puede crearse igualmente** (identidad + árbol mínimo, sección 7); solo la **importación semántica** de contenido queda **pendiente** hasta disponer de un modelo. `[DECISIÓN CERRADA — OC5]`
- Un **primer arranque sin internet** permite **crear un perfil local provisional** y **vincular la cuenta Google después**, cuando haya conexión; la identidad remota no se exige para arrancar el núcleo local. `[DECISIÓN CERRADA — OC22]`
- El estado offline es **visible** en el Centro de Configuración (tarjeta offline/dispositivo, sección 12), nunca un bloqueo silencioso. `[DECISIÓN CERRADA — OC5]`

---

## 6. IA: modelos y proveedores locales vs remotos

**[DECISIÓN CERRADA — OC6]** La configuración de IA (paso 1) separa explícitamente dos familias:

| Familia | Características | Estado |
|---|---|---|
| **Modelos/proveedores locales** | Se ejecutan en la instalación del Autor (Ollama y LM Studio en el MVP); **configuración persistente local**; disponibles offline | **Configurables desde el MVP** `[DECISIÓN CERRADA]`; los runtimes homologados del MVP quedan definidos en OC20 (sección 6.1) |
| **Modelos/proveedores remotos** | Requieren conexión y credenciales externas | La configuración y validación de conectividad forman parte del flujo objetivo; las credenciales se gestionan como secretos protegidos (OC18) `[OBJETIVO]` |

- La configuración unificada texto/visión existente (`DEMIURGOS_TEXT_*`, `DEMIURGOS_VISION_*`; constitución, 7.3) se **mantiene y extiende** para acomodar la familia local/remota, sin cambiar el contrato de proveedores (`[ACTUAL]` — referencia). `[DECISIÓN CERRADA — OC6]`
- **El núcleo local nunca se bloquea por falta de credenciales remotas**: un proveedor remoto sin credenciales o sin conectividad se marca pendiente y la instalación sigue operativa localmente (secciones 5 y 11). `[DECISIÓN CERRADA — OC6]`
- El paso 1 es **bloqueante solo para las capacidades de IA**: si el Autor no configura ningún modelo, el resto del onboarding avanza y la tarjeta IA queda **pendiente** en el Centro. `[DECISIÓN CERRADA — OC6]`

### 6.1 Configuración del modelo principal del Asistente

**[DECISIÓN CERRADA — OC14]** El configurador actual de LLM en **Perfil** (`AssistantSettingsPanel`) es la **base futura** del Centro de Configuración. Este contrato documenta la superficie y el contrato de configuración del **modelo principal del Asistente**; el panel actual es la base y el objetivo lo extiende sin reescribir la superficie desde cero:

- **Flujo gradual `[OBJETIVO — OC14]`**: la configuración del modelo principal sigue este orden: **proveedor → conexión → descubrir modelos → seleccionar modelo → probar texto → probar visión → confirmar**. `[OBJETIVO]`
- El paso de **confirmación** solo persiste como configurado un modelo que haya superado las pruebas de texto y visión del flujo. `[OBJETIVO — OC14]`

**Multimodalidad obligatoria del modelo principal `[OBJETIVO — OC15]`:**

- El **modelo principal de Demiurgos debe ser obligatoriamente multimodal (texto + visión)**: no se puede guardar como **configurado** un modelo `text-only` ni `unknown`. `[OBJETIVO — OC15]`
- El estado **configurado** del Asistente se reserva para modelos que pasan las pruebas; la etiqueta que declara el proveedor **no basta** por sí sola (ver prueba causal más abajo). `[OBJETIVO — OC15]`
- **Cambio respecto al `[ACTUAL]`**: el panel actual permite guardar un modelo de capacidad `unknown` con acuse explícito del Autor (`unknown_ack`); el objetivo **elimina** esa vía para el modelo principal del Asistente. `[ACTUAL → OBJETIVO — OC15]`

**Prueba causal de visión `[OBJETIVO — OC16]`:**

- La prueba visual usa el **fixture versionado** `src/tools/capability_probes/fixtures/logo-demiurgos.jpg` (`[ACTUAL]` — el fixture existe en el repositorio; la prueba como capacidad es `[OBJETIVO]`).
- La prueba se complementa con una **variante temporal con alteración visual controlada** (misma escena con modificación controlada) para comprobar que el modelo realmente ve, no que memorizó la imagen.
- **La etiqueta declarada por el proveedor nunca sustituye al probe**: aunque el proveedor declare multimodalidad, el modelo se considera apto solo si supera la prueba causal. `[OBJETIVO — OC16]`

**Descubrimiento y estado por runtime `[OBJETIVO — OC17]`:**

- **Ollama**: `/api/tags` lista los modelos **instalados/disponibles**; `/api/ps` lista los **cargados en memoria**. `[OBJETIVO — OC17]`
- **LM Studio**: `/api/v0/models` lista los modelos **descargados** y expone su `state`; `/v1/models` depende del JIT. `[OBJETIVO — OC17]`
- Se distingue **instalado/descargado** (disponible) de **cargado/no cargado** (en memoria); un modelo no cargado **puede cargarse bajo demanda** si el runtime lo permite. `[OBJETIVO — OC17]`
- La **UI es común** para todos los runtimes; los **adaptadores específicos por runtime** implementan el descubrimiento y el estado. `[OBJETIVO — OC17]`

**Persistencia en el runtime `[ACTUAL]`:**

- El panel no escribe el id de proveedor de producto en el bloque `model` del perfil activo de Hermes: lo traduce a la identidad que el runtime resuelve. `opencode-go`, `openrouter`, `ollama` y `lm-studio` se persisten como `opencode-go`, `openrouter`, `ollama` y `lmstudio`; `openai` y `compatible` se persisten como `custom`, el endpoint OpenAI-compatible; para `api.openai.com` el runtime decide su transporte (Responses) por contrato propio.
- Para un endpoint `compatible`, el bloque `model` referencia el secreto ya almacenado en el `.env` del perfil (`api_key: ${ASSISTANT_PROVIDER_API_KEY}`); el secreto nunca se escribe en `config.yaml`. Al cambiar de proveedor o borrar la clave, la referencia se retira; un `api_key` ajeno al producto se conserva intacto, salvo que el guardado aporte un secreto nuevo (la entrada explícita gana).
- El bloque normalizado `assistant_settings` conserva el id de producto y sigue siendo la fuente del panel y del gate de visión.
- La **aceptación del runtime es una corrida real pequeña** en cada guardado (subida de un run por la API documentada y espera de su estado terminal): la mera liveness del gateway no acredita el Asistente, porque un gateway vivo acepta el run con `202` y puede fallar de forma asíncrona cuando el proveedor no se resuelve. Una corrida fallida, cancelada, vacía, inalcanzable o agotada deja el estado en `saved-not-active`.

  Una aceptación `saved-not-active` para la revisión vigente **se re-evalúa una vez al arrancar**: si el gateway está vivo y una corrida real completada lo demuestra, la evidencia pasa a `accepted` y el panel deja de mostrar como inactivo un Asistente que funciona. La convergencia es **solo ascendente**: nunca degrada una revisión aceptada ni vuelve a probar una sana, para que un fallo transitorio del proveedor no marque como inactivo un Asistente operativo.

**Credenciales `[OBJETIVO — OC18]`:**

- La configuración **local no requiere API key**; la configuración **remota usa un secreto protegido** (el panel actual ya solo envía la clave al backend autenticado, `[ACTUAL]`). `[OBJETIVO — OC18]`

**Asistente sin modelo multimodal `[OBJETIVO — OC19]`:**

- La **ausencia de un modelo multimodal** deja el **Asistente pendiente/no apto**, y **no** debe afirmarse que el Asistente está configurado. `[OBJETIVO — OC19]`
- Se conserva la **distinción con el núcleo local**: el núcleo local funciona sin modelo de IA (secciones 5, 11 y 12); el Asistente es la capacidad que queda pendiente. `[OBJETIVO — OC19]`

---

## 7. Mundo: último paso operativo

**[DECISIÓN CERRADA — OC7]** El paso 3 (mundo) es el **último paso operativo** del onboarding: sin un mundo el Autor no entra al **Taller de Mundo**. Ofrece dos caminos mutuamente excluyentes y un flujo separado:

| Camino | Qué hace | Resultado |
|---|---|---|
| **Crear desde cero** | Crea **identidad del mundo** + **árbol mínimo** + **estructura Lore recomendada** (opcional, sección 8) | Mundo nuevo listo para editar |
| **Importar existente** | **Delega en el contrato del importador de mundo** (`world-importer.md`/`world-importer-ui.md`): análisis semántico con LLM, aclaraciones interactivas al Autor y escritura gated tras aprobación | Mundo importado con candidatos revisables |
| **Restaurar desde respaldo** | Flujo **separado** de la importación: recupera estado y configuración no secreta de otra instalación (sección 10) | No es un camino del paso 3; se ofrece desde el Centro |

- **Importar ≠ restaurar**: la importación incorpora contenido analizando fuentes; la restauración recupera un estado de instalación (IM9 del importador). `[DECISIÓN CERRADA — OC7]`
- El **Árbol mínimo** de un mundo nuevo comprende los subdirectorios canónicos del contrato OKF (`lore/`, `personajes/`, y el resto según el contrato de mundo de la constitución, sección 6); la **estructura Lore recomendada** es opcional y se detalla en la sección 8. `[DECISIÓN CERRADA — OC7]`
- **Incompatibilidad actual verificada**: el wizard legacy crea `Lore/` y `Personajes/` con mayúsculas, mientras el runtime moderno espera `lore/` y `personajes/` en minúsculas. En sistemas sensibles a mayúsculas como Linux, un mundo creado por el wizard puede quedar invisible o aparecer vacío para el grafo y las superficies modernas. Esta estructura legacy no es el objetivo de implementación; el SDD debe definir la creación canónica y la compatibilidad/migración. `[ACTUAL — riesgo de migración]`

---

## 8. Estructura Lore recomendada (solo mundos nuevos)

**[DECISIÓN CERRADA — OC8]** Para **mundos creados desde cero** se ofrece una estructura Lore recomendada bajo `lore/`, opcional y **explicada en términos humanos**:

| Carpeta recomendada | Qué contiene, en términos humanos |
|---|---|
| `lore/reglas` | Las reglas y leyes del mundo (cómo funciona la realidad del mundo) |
| `lore/lugares` | Geografía, regiones, escenarios y ubicaciones |
| `lore/culturas` | Pueblos, costumbres, lenguas y modos de vida |
| `lore/criaturas` | Seres, fauna, bestias y entidades vivas |
| `lore/facciones` | Organizaciones, órdenes, grupos y alianzas |
| `lore/artefactos` | Objetos, reliquias y elementos notables |
| `lore/historia` | Eventos, cronología e historia del mundo |

Reglas de la estructura recomendada:

- **No se crea contenido inventado**: solo se crean las carpetas (esqueleto); **no** se generan fichas, ejemplos ni textos de relleno. `[DECISIÓN CERRADA — OC8]`
- **No se crean carpetas físicas** `relaciones`, `canon`, `conflictos` ni `propuestas`: son **vistas transversales** (semánticas) del Taller de Mundo (W9); sus registros siguen los contratos existentes (registros de propuesta/conflicto W11), no el esqueleto de Lore. `[DECISIÓN CERRADA — OC8]`
- La estructura es **solo para mundos nuevos**. Los **mundos importados conservan su árbol físico** (W10: el árbol pertenece al Autor) y reciben un **mapeo semántico confirmable con su nivel de confianza**, sin reorganización forzada de carpetas. `[DECISIÓN CERRADA — OC8]`
- Las carpetas recomendadas son **secciones de contenido del Autor**; las carpetas del sistema (`_context`, `.history`, `.papelera`) nunca se presentan como contenido (W10). `[DECISIÓN CERRADA — referencia]`

---

## 9. Plantillas, metodologías y referencias

**[DECISIÓN CERRADA — OC9]** El vocabulario y la mecánica de **Metodologías (Skills), Plantillas, Catálogos y Referencias** viven en el contrato del Taller de Herramientas (`docs/architecture/tool-workshop.md`, sección 1.1, decisión TW20). **Este contrato no lo duplica.**

- El onboarding explica del vocabulario **solo lo necesario para sus decisiones** (p. ej. qué plantillas/catálogos se ofrecen al crear un mundo o qué se referencia desde el Centro); no re-explica el ciclo de vida de Skills ni la co-creación. `[DECISIÓN CERRADA — OC9]`
- Toda referencia a "plantillas", "metodologías" o "referencias" en este documento usa el significado fijo de `tool-workshop.md` 1.1. `[DECISIÓN CERRADA — OC9]`

---

## 10. Respaldo

**[DECISIÓN CERRADA — OC10]** El respaldo (paso 4) se configura **después de que exista un mundo**, es **opcional** y **puede omitirse**:

| Regla | Contenido |
|---|---|
| **Momento** | Posterior al paso 3; nunca antes de existir un mundo |
| **Opcionalidad** | Omitir deja la tarjeta respaldo en **pendiente**; se retoma desde el Centro |
| **Medio inicial** | **Carpeta sincronizada** (coherente con G11: árbol espejo por taller, sync tras editar, restauración Google→Demiurgos). El cliente de sincronización es externo y lo elige el operador |
| **Backup ≠ Restore** | Son **flujos distintos**: **backup** guarda estado en la carpeta sincronizada; **restore** recupera estado y configuración no secreta hacia la instalación (IM9) |
| **Restore** | Recupera **estado no secreto**, **reconstruye el grafo** y **revalida servicios** |
| **Reconfiguración tras restore** | **Secretos, proveedores, Telegram, dominio y TLS pueden requerir reconfiguración** en la máquina destino; el restore no los transporta en claro |

- La cuenta Google y el acceso a Google Drive son **consentimientos separados** (sección 4); el backup usa solo el consentimiento de Drive, nunca el de identidad general. `[DECISIÓN CERRADA — OC10]`
- El paquete de respaldo incluye el **mundo y la configuración no secreta**, con restauración granular por mundo/carpeta cuando corresponda. **API keys, tokens, contraseñas y demás secretos quedan excluidos**; tras restaurar se revalidan los servicios y las credenciales en la instalación destino. `[DECISIÓN CERRADA — OC24]`

**Retención del destino `[ACTUAL]`:**

- El destino conserva un historial GFS: la última snapshot de cada uno de los **7 días**, **4 semanas ISO** y **6 meses** más recientes, más como máximo las **4 snapshots más recientes del día UTC en curso**. Las anteriores del mismo día se podan; el borrado es definitivo (una carpeta simple no tiene papelera).
- Los logs de ejecución (`logs/`) **no** forman parte del respaldo: son runtime regenerable y, al vivir dentro de la raíz de datos, incluirlos realimentaba el motor (cada request programaba una snapshot).

---

## 11. Listo para Trabajar

**[DECISIÓN CERRADA — OC11]** El paso final del onboarding es el estado **Listo para Trabajar**:

- Es un **estado del mundo/workspace**, **no** un estado OKF `stable`: no declara que el contenido del mundo sea canon; declara que la instalación tiene un mundo operativo. `[DECISIÓN CERRADA — OC11]`
- La instalación puede estar **lista para trabajar con insignias de capacidad**, una por área (p. ej. **editor local listo**, **asistente pendiente**, **respaldo pendiente**). `[DECISIÓN CERRADA — OC11]`
- **No debe afirmar capacidades cloud listas**: si Telegram, Drive o un proveedor remoto están pendientes, la insignia correspondiente lo refleja como pendiente o requiere conexión; nunca como configurado. `[DECISIÓN CERRADA — OC11]`
- La insignia del **Asistente** se marca **pendiente/no apto** si no hay un **modelo principal multimodal** superando la prueba de visión (sección 6.1); nunca se muestra como "configurado" en ese caso, y el núcleo local permanece operativo. `[OBJETIVO — OC19]`
- El resumen final muestra qué quedó pendiente y cómo retomarlo desde el Centro de Configuración (sección 12). `[DECISIÓN CERRADA — OC11]`
- **Mundo**: existe un mundo válido y se puede abrir y editar.
- **Editor local**: el almacenamiento local permite leer y guardar correctamente.
- **Asistente**: existe un modelo principal multimodal que supera las pruebas de texto y visión.
- **Telegram**: la conexión fue validada con éxito.
- **Respaldo**: la carpeta sincronizada tiene consentimiento y una prueba de acceso funciona.
- **Identidad**: la identidad local o Google está validada según el modo disponible.
- **Offline/dispositivo**: el núcleo local funciona sin conexión.
- Solo **Mundo** y **Editor local** son esenciales para `Listo para Trabajar`; Telegram, Respaldo, Identidad y Asistente pueden quedar pendientes sin afirmar que están configurados. `[DECISIÓN CERRADA — OC21]`

---

## 12. Centro de Configuración permanente

**[DECISIÓN CERRADA — OC12]** El **Centro de Configuración** es la superficie permanente que sustituye la repetición del onboarding:

- **Ajustes globales + entrada contextual**: el Centro agrupa los ajustes globales de la instalación y es alcanzable contextualmente desde las superficies donde corresponda (p. ej. desde el perfil/autenticación según la constitución 10.3, o desde el estado del asistente). `[DECISIÓN CERRADA — OC12]`
- **Ubicación actual**: la superficie vive **dentro del Perfil** (`/perfil`, pestaña "Centro de Configuración"), con la configuración de Telegram bajo la pestaña "Integraciones" y la migración de carpetas legacy bajo "Mundos"; **no existe una página/ruta independiente** `/centro-configuracion` (decisión nav-restructure, aplicada en el frontend). `[ACTUAL]`
- **Tarjetas por sección**, cada una con su estado:

| Tarjeta | Capacidad |
|---|---|
| Identidad | Cuenta Google, revalidación, recuperación autorizada (sección 4) |
| IA texto/visión | Modelos/proveedores locales y remotos, credenciales, modelo principal del Asistente (sección 6 y 6.1) |
| Telegram | Canal de mensajería (paso 2) |
| Respaldo/Restauración | Backup y restore hacia la carpeta sincronizada (sección 10) |
| Idioma, región y zona horaria | Localización del paso 0 (sección 3) |
| Mundos | Crear, importar o restaurar (secciones 7–8) |
| Offline/dispositivo | Estado de conexión y capacidades locales (sección 5) |

- **Estados de tarjeta**: `pendiente` / `configurado` / `requiere conexión` / `error`. Cada tarjeta muestra el estado actual, no promesas. `[DECISIÓN CERRADA — OC12]`
- **Reanudación por sección independiente**: cada tarjeta permite retomar o reconfigurar **su** capacidad de forma aislada, sin volver a recorrer el onboarding ni otras secciones. `[DECISIÓN CERRADA — OC12]`
- El Centro **no duplica** las superficies de Taller: referencias a mundos, Skills y plantillas enlazan a sus contratos/talleres (secciones 0 y 9) en lugar de reimplementarlas. `[DECISIÓN CERRADA — OC12]`

---

## 13. Retiro del wizard legacy `web-config-ui`

Esta sección registra el retiro del wizard legacy: **13.1** conserva la auditoría del estado previo al retiro y **13.2** documenta el retiro ejecutado y el estado final verificado.

### 13.1 Estado previo al retiro — auditoría `[ACTUAL — histórico]`

Estado verificado ANTES del retiro (WU-5a/WU-5b, 2026-08-18). Se conserva como evidencia de auditoría; **ya no describe el estado actual** del repositorio:

| Evidencia | Detalle |
|---|---|
| `src/tools/web-config-ui/` | Wizard de configuración web legacy: servidor FastAPI de un solo archivo (`main.py`) con **asistente de 7 pantallas** (idioma/bienvenida, mundo, IA, imágenes, chat, respaldo y resumen) vía htmx, sin CDN externo, con `i18n.py`, `config.py`, `backup.py` y `templates/` — **retirado del camino soportado en WU-5b; conservado solo como referencia histórica** |
| `install.sh` | Contenía la referencia activa al wizard: Stage 6/`launch_web_ui` instalaba `requirements.txt` y usaba el directorio `src/tools/web-config-ui/` (líneas 257 y 265) — **eliminado en WU-5b** |
| Puerto 8000 | **Auditoría ONB-4.6:** dos servidores podían enlazar el puerto 8000 — la **Wiki API** (`src/tools/demiurgos-suite/wiki/api_server.py`, puerto por defecto en su entrada) y el wizard legacy (`install.sh` línea 267: `uvicorn main:app --port 8000`). **Resolución: la Wiki API es el dueño canónico del puerto 8000**; el binder legacy fue **eliminado en WU-5b** con el Stage 6 — sin propiedad residual en conflicto |
| `sdd/web-config-ui/spec.md` | Especificación SDD del wizard legacy (proveedores, claves de API) — **histórica** |
| Constitución (`demiurgos-platform.md`) | Mapa de componentes (sección 2.1), superficie "Configuración/instalación" (sección 4), mapa del repositorio (sección 8.1) y decisión G8 citaban `web-config-ui` como wizard actual — **actualizados a estado histórico en WU-5b** |

### 13.2 Retiro ejecutado `[ACTUAL — WU-5b]`

**[DECISIÓN CERRADA — OC13, ejecutada]** Tras validar el nuevo onboarding y el Centro de Configuración (gate WU-5a, 10/10), el wizard legacy pasó a ser **histórico / solo referencia**:

- **Retirado del camino soportado**: ya no es la superficie de configuración oficial; el onboarding + Centro de Configuración (wiki) la reemplazan.
- **Marcado no usable**: `src/tools/web-config-ui/` se conserva **solo como referencia histórica**; no se invoca ni se mantiene como funcional.
- **Referencias activas eliminadas** (ONB-5.3): `install.sh` perdió el Stage 6 (`launch_web_ui`) y su llamada, incluyendo el binder legacy del puerto 8000; el mapa, la superficie y la decisión G8 de la constitución se actualizaron a estado histórico (ONB-5.4).
- **Conservadas solo las ideas aprovechables**: los flujos de respaldo/restauración (`backup.py`) y la configuración de proveedores informan el nuevo Centro; `backup.py` y `tests/test_restore.py` permanecen **intactos como referencia de patrón**, sin reutilizarse como runtime.
- **Gate de retiro finalizado** (ONB-5.4): `retirement_gate.py` valida ahora el estado post-retirement (`legacy_wiring_removed`, `legacy_preserved_historical`, `new_runtime_present` + 8 gates funcionales); el runbook `retirement-overlap-runbook.md` documenta la comprobación final.

> **Regla de etiquetas:** la sección 13.1 es `[ACTUAL — histórico]` (auditoría previa al retiro, conservada como evidencia); la sección 13.2 es `[ACTUAL]` porque el retiro **ya está ejecutado** (WU-5b). El solapamiento controlado (OC25) se completó con el gate WU-5a y el retiro se aplicó después, con rollback posible hasta que las compuertas pasaron.

---

## 14. Decisiones cerradas y abiertas

### 14.1 Cerradas (no revertir sin nuevo acuerdo)

| ID | Decisión |
|---|---|
| **OC1** | Onboarding **una sola vez** + **Centro de Configuración permanente**; las capacidades pendientes se retoman por sección desde el Centro, **sin repetir el onboarding** (sección 1) |
| **OC2** | **Orden MVP** 0→5: bienvenida/idioma/región/zona (bloqueante) → IA texto y visión (bloqueante solo para IA, con soporte local/offline) → Telegram (opcional, único servicio de mensajería inicial) → mundo crear/importar (bloqueante para el Taller de Mundo, último paso operativo) → respaldo (opcional, posterior al mundo) → Listo para Trabajar; **imágenes fuera del MVP** (sección 2) |
| **OC3** | Idioma y variante **sugeridos por región con override explícito**; zona **IANA**; timestamps internos **UTC**; **título humano local**; **sin dialecto forzado por región**; **lenguajes de UI, conversación y contenido separados** (sección 3) |
| **OC4** | Identidad: **Google OAuth/OIDC como objetivo del MVP**; cuenta Google y acceso Drive con **consentimientos separados**; **identificador estable, no email**; primer vínculo **online**; credencial local protegida para **offline**; instalación nueva/formateada/VPS requiere **revalidación online o recuperación autorizada**; **sin contraseñas de Google** (sección 4) |
| **OC5** | **Offline**: mundos/editor/ideas/plantillas/grafo local disponibles; remoto/Telegram/Drive/proveedores cloud requieren conexión; modelos locales configurable desde MVP; **sin LLM, mundo nuevo creable** e importación semántica pendiente (sección 5) |
| **OC6** | **IA**: separación modelos/proveedores **locales y remotos**; configuración local **persistente**; credenciales remotas y conectividad **pendientes**; **el núcleo local no se bloquea** (sección 6) |
| **OC7** | **Mundo como último paso**: crear desde cero (identidad + árbol mínimo + estructura Lore recomendada opcional) o **importar delegando en el contrato del importador** (análisis semántico LLM + aclaraciones interactivas); **restaurar respaldo es flujo separado** (sección 7) |
| **OC8** | **Estructura Lore recomendada solo para mundos nuevos**: `lore/reglas, lugares, culturas, criaturas, facciones, artefactos, historia`; explicada en términos humanos; **sin contenido inventado**; sin carpetas físicas relaciones/canon/conflictos/propuestas (vistas transversales); mundos importados **conservan su árbol físico** con **mapeo semántico confirmable y con confianza**, sin reorganización forzada (sección 8) |
| **OC9** | Vocabulario **Metodologías/Plantillas/Catálogos/Referencias** referenciado a `tool-workshop.md` 1.1 **sin duplicarlo**; el onboarding solo explica lo necesario (sección 9) |
| **OC10** | **Respaldo** después del mundo, **opcional y omitible**; carpeta sincronizada; **backup y restore son flujos distintos**; restore recupera estado no secreto, **reconstruye el grafo** y **revalida servicios**; secretos/proveedores/Telegram/dominio/TLS pueden requerir reconfiguración (sección 10) |
| **OC11** | **Listo para Trabajar** = estado de mundo/workspace, **no** OKF `stable`; posible con **insignias de capacidad** (editor local listo, asistente pendiente, respaldo pendiente); **no afirma capacidades cloud listas** (sección 11) |
| **OC12** | **Centro de Configuración permanente**: ajustes globales + entrada contextual; tarjetas identidad, IA texto/visión, Telegram, respaldo/restauración, idioma/región/zona, mundos, offline/dispositivo; estados **pendiente/configurado/requiere conexión/error**; reanudación **por sección independiente** (sección 12) |
| **OC13** | **Retiro del wizard legacy `web-config-ui`** tras validar el nuevo onboarding: histórico/solo referencia; fuera del camino soportado; marcado no usable; sin referencias activas en docs/arranque; solo se conservan las ideas aprovechables (sección 13) |
| **OC14** | **Configuración del modelo principal del Asistente**: el `AssistantSettingsPanel` de Perfil es la **base futura**; **flujo gradual** proveedor → conexión → descubrir modelos → seleccionar modelo → probar texto → probar visión → confirmar; solo se persiste como configurado un modelo que superó las pruebas (sección 6.1) |
| **OC15** | **Multimodalidad obligatoria del modelo principal**: texto + visión; **no se guarda como configurado** un modelo `text-only` ni `unknown`; se elimina la vía `unknown_ack` para el modelo principal (sección 6.1) |
| **OC16** | **Prueba causal de visión**: fixture versionado `src/tools/capability_probes/fixtures/logo-demiurgos.jpg` + variante temporal con alteración visual controlada; **la etiqueta del proveedor nunca sustituye al probe** (sección 6.1) |
| **OC17** | **Descubrimiento y estado por runtime**: Ollama `/api/tags` (instalados/disponibles) y `/api/ps` (cargados); LM Studio `/api/v0/models` (descargados, expone `state`) y `/v1/models` (JIT); se distingue **instalado/descargado vs cargado/no cargado**; carga bajo demanda si el runtime lo permite; **UI común con adaptadores por runtime** (sección 6.1) |
| **OC18** | **Credenciales**: configuración **local sin API key**; configuración **remota con secreto protegido** (solo al backend autenticado) (sección 6.1) |
| **OC19** | **Asistente sin modelo multimodal**: queda **pendiente/no apto** y **no se afirma configurado**; se conserva la distinción con el núcleo local, que opera sin modelo (secciones 5, 11 y 12) |
| **OC20** | **Runtimes locales del MVP**: se homologan **Ollama y LM Studio**; ambos tienen descubrimiento específico de modelos y estado instalado/descargado frente a cargado/no cargado (sección 6.1) |
| **OC21** | **Criterios de insignias**: Mundo y Editor local son esenciales para `Listo para Trabajar`; Asistente requiere modelo multimodal probado; Telegram, Respaldo, Identidad y Offline/dispositivo se marcan según sus validaciones, sin bloquear el núcleo local (sección 11) |
| **OC22** | **Bootstrap offline**: el primer arranque puede crear un perfil local provisional y vincular Google posteriormente; el núcleo local funciona mientras la identidad remota queda pendiente (sección 5) |
| **OC23** | **Autenticación y recuperación de Google**: instalaciones nuevas, máquinas formateadas y VPS requieren revalidación online; la recuperación offline es una excepción autorizada con evidencia verificable y no reutiliza silenciosamente credenciales de otra instalación (sección 4) |
| **OC24** | **Respaldo y restauración**: el paquete incluye mundo y configuración no secreta, permite granularidad por mundo/carpeta, excluye API keys/tokens/contraseñas/secretos y exige revalidar servicios y credenciales en destino (sección 10) |
| **OC25** | **Retiro del wizard legacy**: habrá solapamiento controlado durante la validación del nuevo onboarding; después se retirará del camino soportado y se eliminarán sus referencias activas en `install.sh` y documentación (sección 13) |

### 14.2 Estado de decisiones abiertas

No quedan decisiones abiertas OD1–OD6 de este contrato. Cualquier decisión nueva que surja durante el SDD debe registrarse explícitamente sin presentar el comportamiento objetivo como `[ACTUAL]`.

> **Sin endpoints inventados:** este contrato no declara rutas de API para onboarding ni Centro de Configuración; la definición de endpoints es materia del SDD futuro, sujeta a las invariantes de la constitución (escritura gated, sin exponer secretos, rutas acotadas al mundo).

---

## 15. Definition of ready para SDD futuro

El SDD de implementación de onboarding/Centro de Configuración **solo** puede comenzar cuando se cumplan todos:

- [ ] Se leyeron esta constitución global, este contrato y los contratos referenciados (secciones 0, 7, 8, 9).
- [ ] Se verificó el runtime real (CodeGraph/tests) antes de asumir cualquier `[ACTUAL]` (secciones 3, 6, 13).
- [ ] Las decisiones OD1–OD6 de este contrato están cerradas y anotadas como OC20 (OD3), OC21 (OD5), OC22 (OD2), OC23 (OD1), OC24 (OD4) y OC25 (OD6) (sección 14).
- [ ] El cambio respeta las invariantes `[ACTUAL]` de la constitución (secciones 5, 7) y las fronteras de dominio (Planner/Writer/Validator/Backend).
- [ ] La configuración del modelo principal del Asistente implementa el **flujo gradual completo** (proveedor → conexión → descubrir → seleccionar → probar texto → probar visión → confirmar) y solo persiste como **configurado** un modelo **multimodal** que superó las pruebas (OC14–OC15).
- [ ] La prueba de visión usa el **fixture versionado** y su variante alterada; la **etiqueta del proveedor no sustituye al probe**; no hay vía para guardar `text-only`/`unknown` como configurado (OC15–OC16).
- [ ] El descubrimiento y el estado por runtime siguen los contratos de Ollama/LM Studio (instalado/descargado vs cargado, carga bajo demanda) y las credenciales local/remota cumplen OC17–OC18.
- [ ] Sin modelo multimodal, el Asistente se muestra **pendiente/no apto**, nunca configurado, sin afectar el núcleo local (OC19).
- [ ] Todo comportamiento nuevo se etiqueta `[ACTUAL]`/`[OBJETIVO]`/`[PROPUESTO]` y no se presenta como implementado.
- [ ] El SDD declara explícitamente qué NO toca (AGENTS.md, escrituras gated, carpetas del sistema, contratos de Taller referenciados) y no inventa endpoints fuera de las invariantes.
- [ ] Las pruebas cubren las invariantes afectadas (no repetición del onboarding, separación de consentimientos, no bloqueo del núcleo local, insignias sin afirmaciones falsas, multimodalidad obligatoria y prueba causal de visión) y las ramas de fallo relevantes (offline, error de proveedor, modelo sin visión, modelo no cargado, restore parcial).
