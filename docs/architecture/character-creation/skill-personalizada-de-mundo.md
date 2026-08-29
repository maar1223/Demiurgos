# Skill Personalizada de Mundo

> **Referencia de diseño para el Taller de Herramientas.**
> Define cómo una **Skill Personalizada de Mundo** le da a Demiurgos "poderes" de conocimiento de un
> mundo específico, extendiendo el esquema de datos **sin romper** lo que el importador genera, y de forma
> que el **grafo entienda el mundo sin ambigüedad**.
> El backend actual ya soporta el ciclo de vida completo (draft → compile → publish → activate → rollback)
> y el compilador define la frontera de autoridad. Este doc la aterriza al caso de enriquecimiento por mundo.

## 1. Qué es una Skill Personalizada de Mundo

Una **metodología/methodology** que el autor crea desde el **Taller de Herramientas** y activa por mundo.
Su manifest está **acotado** por el compilador (`methodology_compiler.py`):

```
ALLOWED_MANIFEST_FIELDS = {"skill_id", "version", "name", "description", "phases", "language"}
MAX_SOURCE_CHARS = 200_000
MAX_PHASES = 12
```

O sea: un manifest de 6 campos + un cuerpo Markdown + una lista de `phases`. Nada más.

**Qué aporta al mundo:**
- **Conocimiento** (qué es un Stal, qué es un Áyagar, sus razas, sus lugares) → el cuerpo Markdown.
- **Metodología** (cómo crear una ficha de este mundo) → las `phases`.
- **Campos de mundo** (Stal, Subtipo, etc.) que se agregan al OKF → requiere el esquema de la sección 3.

## 2. La frontera de autoridad (NO negociable)

El compilador **rechaza** cualquier metodología que intente reclamar campos `kernel-owned`:

```
authorization, permissions, allowlisted_targets, minimums, phase_safety,
compatibility, persistence, approval, gates, kernel, exec, commands,
trust, activate, publish, signature, checksum, self_authorize, grant, override
```

**Lo que una skill personalizada PUEDE hacer:**
| Área | ¿Puede? |
|---|---|
| Metodología de trabajo (cómo crear X) | ✅ Sí (`phases` + Markdown) |
| Conocimiento/vocabulario de un mundo | ✅ Sí (cuerpo Markdown) |
| Nuevas fases de flujo | ✅ Sí (hasta 12) |
| **Agregar campos de mundo al OKF** | ✅ Sí (**con el esquema de la sección 3**) |

**Lo que NO puede hacer** (hard-boundary del kernel):
| Área | ¿Puede? |
|---|---|
| Permisos / autorización | ❌ No |
| Ejecutar comandos / código | ❌ No |
| Sobreescribir el núcleo | ❌ No |
| Activar/persistir sola | ❌ No |
| Modificar ciclo de aprobación | ❌ No |

*Racional:* Hermes corre por debajo, y está capado para que una skill no se edite a sí misma ni
rompa el sistema por tener demasiados permisos en manos de alguien inexperto. La skill extiende
**contenido y método**, nunca el **núcleo de seguridad**.

## 3. El caso clave: extender el esquema de datos sin romper el OKF

El objetivo real es que el grafo entienda el mundo sin ambigüedad. Eso requiere campos tipados de
mundo (p. ej. el **Stal**) que se agregan a la ficha. Verificación de lo que el backend permite hoy:

### 3.1 El OKF tolera campos extra (buena noticia)

`okf_contract.parse_document()` **NO rechaza campos desconocidos** en el frontmatter. Solo valida:
`type` (identidad), versión OKF, mínimos (identidad+deseo) y resolución de wikilinks.

→ El Stal puede agregarse como campo del frontmatter **sin romper el validador OKF.**

### 3.2 Quién es dueño de qué campo (la regla de no-pisar)

| Campo | Dueño | Cómo se modifica |
|---|---|---|
| `id`, `title`, `type`, `status` | Sistema / importador | Solo flujo de sistema (import, setStatus) |
| `description`, `relaciones` | Importador, pero editables | Flujo de edición normal (autor confirma) |
| **Campos de mundo** (Stal, etc.) | **Skill Personalizada de Mundo** | **Fase de enriquecimiento (esta arquitectura)** |

### 3.3 El flujo de enriquecimiento (post-generación, acotado)

El enriquecimiento NO es "editar el OKF a mano" — es una **fase distinta**, separada y acotada, que
respeta el mismo mecanismo de `base_revision` + digest que ya protege la edición.

```
[Importador]  genera OKF base (type, title, id, description, status, relaciones)  — determinista
      │
      ▼
[Skill Personalizada de Mundo]  →  paso de ENRIQUECIMIENTO
      │      • Lee el OKF ya validado.
      │      • Solo AGREGA campos de su mundo (Stal, etc.) — NUNCA toca id/title/type/status/relaciones.
      │      • El asistente propone los campos de mundo como propuesta diskless.
      │      • El autor aprueba → se escribe con base_revision + digest.
      ▼
[OKF enriquecido]  =  OKF base + campos de mundo (Stal)
      │
      ▼
[Grafo]  indexa los campos de mundo declarados, para entender el mundo sin ambigüedad
```

### 3.4 Las 3 invariantes del enriquecimiento

1. **Solo agrega campos declarados en su schema de mundo.** La skill declara un conjunto de campos
   permitidos (`allowed_world_fields`). El backend valida que la edición solo toque esos campos.
2. **Nunca toca los campos del kernel.** Si la propuesta intenta modificar `id`/`title`/`type`/`status`/
   `relaciones`, se rechaza (esos son del sistema, no del mundo).
3. **Respeta `base_revision` + digest.** Igual que el flujo de edición: la escritura solo procede si la
   revisión base no cambió. Protege contra pisar ediciones concurrentes.

## 4. El gap de indexación (lo que falta para "sin ambigüedad")

Verificado en `graph_indexer.py`: el grafo indexa hoy `id, name, type, status, forward_links,
backlinks, relaciones`. **NO indexa campos de mundo** (Stal, etc.).

Por eso, para que el grafo entienda el mundo sin ambigüedad, hace falta:

- **La skill personalizada declara qué campos de mundo se indexan** (parte de su schema).
- **El índice aprende esos campos extendidos** — o bien el indexador los lee de forma genérica
  (cualquier campo extra del frontmatter que la skill marque como indexable), o bien hay un esquema por
  mundo que el índice consulta.

**Decisión de diseño a resolver** (ver `README.md` → decisiones abiertas): ¿el índice lee campos de mundo
de forma genérica (todo campo extra que la skill declare indexable) o hay un **schema por mundo** que el
índice consulta para saber qué campos indexar? La segunda es más determinista y "sin ambigüedad".

## 5. El caso "importó algo y luego agrega metadatos" (tu escenario)

Este es el caso que motivó todo, y se resuelve con la fase de enriquecimiento:

1. **Importación:** el importador genera el OKF correctamente (esto ya funciona excelente; no se toca).
2. **Post-importación, el usuario quiere agregar metadatos de mundo:** el asistente, al editar la ficha,
   **detecta que este mundo tiene una skill de enriquecimiento activa**, la invoca, y propone agregar los
   campos de mundo (Stal, etc.) como **propuesta diskless que el autor aprueba.**
3. **Resultado:** el OKF queda enriquecido con los campos de mundo, sin que el importador necesite saber
   nada del Stal, y sin pisar los campos del sistema.

**La separación clave:** el importador y la skill de enriquecimiento **no compiten** — el importador
genera la base determinista, la skill de enriquecimiento agrega la capa de mundo. Son fases distintas que
operan sobre el mismo OKF sin pisarse, porque la skill solo toca sus campos declarados.

## 6. Skill Fundacional vs Skill Personalizada de Mundo (la frontera)

| | Skill Fundacional | Skill Personalizada de Mundo |
|---|---|---|
| Origen | Viene con Demiurgos | La crea el autor (Taller de Herramientas) |
| Escopo | Universal (cualquier mundo) | Específica de un mundo |
| Campos | Eneatipo, Subtipo, Arquetipo, Alineamiento, identidad, carácter, conflicto, arco | Stal, razas, lugares, poderes, campos del mundo |
| La invoca | Siempre (crea la base) | El asistente la llama al crear/editar una ficha de ESE mundo |

**Cadena:** Skill Fundacional crea la base universal → Skill Personalizada de Mundo enriquece con lo
específico. El Stal (sistema de PODER de Vibrantes) vive en la capa de mundo, no en la base.
