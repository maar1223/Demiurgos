# Creación de Personajes — Documentación de diseño de la Skill

> **Índice y mapa de decisiones.**
> Documentación consultable para diseñar/mejorar la **Skill fundacional de creación de personajes**.
> Todo el contenido de diseño vive ACÁ (en archivos re-leíbles) y NO solo en la memoria del contexto
> o en Engram, para no perder decisiones entre sesiones.
> Idioma: español (igual que el resto de `docs/architecture/`).

## Mapa de documentos

| Documento | Contenido |
|---|---|
| [`examples/Axill_Garner.md`](examples/Axill_Garner.md) | Ejemplo canónico de ficha **1º nivel** (protagonista, formato ACOTADO) — **fuente de verdad del formato de salida** |
| [`examples/Kae_Turant.md`](examples/Kae_Turant.md) | Ejemplo canónico de ficha **1º nivel** (coprotagonista, formato estable) — confirma que el formato es estable por perfil |
| [`examples/Secundario_Ejemplo.md`](examples/Secundario_Ejemplo.md) | Ejemplo de ficha **2º nivel** (secundario, 2 arquetipos) — con la regla de qué se mantiene/omite |
| [`examples/Relleno_Ejemplo.md`](examples/Relleno_Ejemplo.md) | Ejemplo de ficha **3er nivel** (relleno, 1 arquetipo) — tarjeta mínima, sin peso narrativo |
| [`examples/Villano_Korrane.md`](examples/Villano_Korrane.md) | Ejemplo **histórico pre-cambio** de ficha **1º nivel** (rol `VILLANO`, 3 arquetipos) — **agnóstica al mundo** (sin Stal/lugares/razas). El stack del sistema integrado (Eneatipo+Subtipo+Arquetipo+Alineamiento) + Eneatipo derivado al final. Ver nota de legacy más abajo |
| [`systems/eneagrama-arquetipos-alineamientos.md`](systems/eneagrama-arquetipos-alineamientos.md) | **FUENTE CANÓNICA** (autor): Eneagrama completo + los 49 arquetipos numerados + alineamientos por nivel (Relleno/Principal-Secundario/Inmortales). Manda sobre las guías |
| [`systems/alignment-system.md`](systems/alignment-system.md) | Guía de uso de alineamientos: 2 ejes (orden × moral) + alcance por nivel + guardrails (no es D&D). **No redefine valores — cita la fuente** |
| [`systems/archetypes-7x7.md`](systems/archetypes-7x7.md) | Guía de uso de arquetipos: ejes (Qué busca × Lo consigue con) + lectura de la grieta + profundidad por rol (3/2/1). **No redefine descripciones — cita la fuente** |
| [`skill-taxonomia.md`](skill-taxonomia.md) | **Taxonomía final de skills**: Fundacional (sistema) / Personalizada de Mundo / Personalizada Transversal — qué aporta cada una, su activación y su frontera funcional |
| [`skill-personalizada-de-mundo.md`](skill-personalizada-de-mundo.md) | **Arquitectura de la Skill Personalizada de Mundo**: frontera de autoridad, cómo extender el esquema de datos sin romper el OKF, flujo de enriquecimiento post-generación, gap de indexación |

## Decisiones cerradas (no revertir sin nuevo acuerdo)

1. **Formato canónico de salida = Axill (acotado).** Bira es **contra-patrón** (sobre-generación; ver
   `examples/`). La skill debe escupir el formato Axill para personajes de primer nivel
   (protagonista/antagonista/coprotagonista).
2. **El arco de personaje es caracterización (60% flexible) y ENTRA al MVP.** No se separa de la
   "entidad". El único mecanismo que queda FUERA del MVP es el motor de sagas/tramas del universo
   (timeline de eventos, generación de historia → Taller de Narrativa), conforme a D5.
3. **Principio 40/60 = comportamiento del asistente, no regla matemática ni cuestionario.** El 40%
   determinista son anclas de canon (identidad/datos); el 60% flexible es el diálogo que hace volar
   al autor. No es "40% del texto".
4. **Los subsistemas se dividen en dos roles distintos** (corrección de un borrador anterior que los
   metió a todos en el mismo saco):
   - **Campos de la ficha VISIBLE, UNIVERSALES** (van en la skill fundacional): **Eneatipo + Subtipo +
     Arquetipo 7×7 + Alineamiento**. Son psicología/moral de personaje, aplican a cualquier mundo.
   - **Herramientas de DIAGNÓSTICO / validación** (lente interno del asistente, NO van en la ficha):
     **11 creencias irracionales (Ellis)** y **15 puntos del villano arquetípico**. Sirven para
     construir/validar la psique, no como campos que el autor rellena.
   - **Campos específicos del MUNDO** (p. ej. el **Stal**, lugares, razas, poderes del mundo Vibrantes):
     **NO van en la skill fundacional.** Los aporta la **Skill Personalizada de Mundo**
     (creada desde el Taller de Herramientas), que el asistente invoca al crear una ficha en ese mundo.
     Ver decisión #10.
5. **Se separan dos temas que NO son lo mismo** (los tenía mezclados en un borrador):
   - **11 creencias irracionales (Ellis)** → **psicología interna** / motor de conflicto interno.
     Universal (cualquier personaje). Alimenta **Conflicto interno**.
   - **15 puntos del villano arquetípico** → **craft narrativo** / cómo se lee ante el lector.
     No es un rol de la taxonomía: es una **lente** aplicable a antagonistas y a cualquier personaje
     cuya conducta se revele como tal. Alimenta **Rol en la historia** + validación.
6. **Subsistema de alineamientos**: custom, organizado **por nivel del personaje**
   (Relleno / Principal-Secundario / Inmortales), NO es D&D, y no confundir ejes ("Legal" es
   orden/autoridad, "Moral" es calidad). La lista de cada nivel está en la **fuente canónica**.
7. **Subsistema de arquetipos 7×7**: motor del 60%; la grieta entre "qué busca" y "cómo lo consigue"
   es la fuente del conflicto interno. La profundidad escala con el rol (3/2/1). Los 49 arquetipos
   están en la **fuente canónica**. Mecánica de generación (moldes simultáneos e independientes, por par
   `Fila × Columna`, rellenar huecos para que calce) en `systems/archetypes-7x7.md`.
8. **Fuente canónica del sistema psíquico** = `systems/eneagrama-arquetipos-alineamientos.md`
   (autor). El **Eneatipo + Subtipo + Arquetipo + Alineamiento** son universales de personaje (van en la
   skill fundacional). El **Stal** es un sistema de PODER del mundo Vibrantes — NO es universal, y se
   vincula al eneagrama en `mundos/vibrantes/lore/eneagrama_stal/` y `lore/sistema_stal/`. La guía apunta
   a la fuente, nunca la redefine ni la contradice.
9. **Densidad de la ficha por nivel** (la profundidad NO es "más texto", es estructura que escala con
   el peso del rol — el error Bira es poner más texto). Cada nivel tiene su propio recorte:

   | Nivel | Rol | Arquetipos | Qué se mantiene | Qué se omite |
   |---|---|---|---|---|
   | **1º** | Principal / Antagonista / Coprotagonista | 3 | Todo el formato fundacional completo | — |
   | **2º** | Secundario | 2 | Identidad mínima + **Rol narrativo + Relación con el protagonista** + aspecto con defecto + **carácter 2×2** + función + mini-arc opcional | Conflicto profundo, arco 3 actos, trasfondo extenso, perfil de voz |
   | **3º** | Relleno | 1 | Nombre + **Función** en la escena + 1 rasgo distintivo | Todo lo narrativo |

   **Regla de oro:** si un personaje necesita más de "nombre + función + un rasgo", **no es relleno** —
   hay que subirlo a secundario. Ver los ejemplos en `examples/`.

10. **Arquitectura de capas: skill fundacional AGNÓSTICA AL MUNDO + skill personalizada.** Taxonomía final:
    **Fundacional** (sistema, universal) / **Personalizada de Mundo** (autor, un mundo) / **Personalizada
    Transversal** (autor, cualquier mundo). La fundacional NO puede contener parámetros de un mundo
    específico (Stal, lugares, razas, poderes) — no todos los personajes son de ese mundo. El color de
    mundo lo aporta la **Skill Personalizada de Mundo**, creada desde el Taller de Herramientas y activada
    por mundo. Al crear una ficha en ese mundo, el asistente llama a esa skill y enriquece el personaje.
    Ver `skill-taxonomia.md`.

    ```
    Skill FUNDACIONAL (universal) ──► crea la base del personaje
                                            │
                                            ▼
    Skill de ENRIQUECIMIENTO POR MUNDO ──► añade lo específico del mundo (Stal, lugares, razas, poderes)
    (personalizada, creada en el Taller de Herramientas)
    ```

    Las skills de enriquecimiento tendrán sus propias estructuras — probablemente creadas por la Skill
    Madre al crear las skills personalizadas.

11. **Frontera de autoridad de las Skills Personalizadas** (verificado en `methodology_compiler.py`):
    la skill puede aportar **metodología + conocimiento + campos de mundo**, pero NUNCA reclamar
    campos kernel-owned (`authorization`, `permissions`, `exec`, `commands`, `gates`, `approval`,
    `activate`, `override`, etc.). El manifest está acotado
    (`skill_id/version/name/description/phases/language`, máx 200k chars, máx 12 phases). La skill
    extiende contenido y método, nunca el núcleo de seguridad.

12. **Extender el esquema de datos sin romper el OKF** (verificado en `okf_contract.py`): el OKF
    **tolera campos extra** en el frontmatter (solo valida `type`, versión, mínimos, wikilinks). Por eso
    los campos de mundo (Stal, etc.) pueden agregarse sin romper el validador. El enriquecimiento es una
    **fase acotada post-generación** con 3 invariantes: (a) solo agrega campos declarados en el schema de
    la skill, (b) nunca toca `id/title/type/status/relaciones` (del kernel), (c) respeta `base_revision` +
    digest. Ver `skill-personalizada-de-mundo.md`.

13. **El gap de indexación de campos de mundo** (verificado en `graph_indexer.py`): el grafo indexa hoy
    `id, name, type, status, forward_links, backlinks, relaciones` — **NO indexa campos de mundo** como el
    Stal. Para que el grafo entienda el mundo "sin ambigüedad", la skill debe declarar qué campos de mundo
    se indexan y el índice debe aprenderlos. Ver `skill-personalizada-de-mundo.md` §4.

14. **El alineamiento es una trayectoria emergente `inicial → revelado`, no un campo asignado al inicio.**
    Se deriva al cierre, igual que el **Eneatipo** (precedente de derivación): no se pregunta en fase 1;
    el razonamiento es del asistente. El **eje moral se lee de la CONDUCTA** (lo que el personaje hace y
    está dispuesto a sacrificar), **NO de su autoimagen**; el **eje de orden** se lee de su relación con
    la autoridad y las estructuras. Ambos valores pertenecen a la lista canónica del nivel. El **nivel
    narrativo mide solo densidad** (1º/2º/3º) y no codifica moralidad; sí cambia con la densidad la
    lista de la que se deriva. En 1º nivel la trayectoria vive en el arco acto a acto. Ver
    `systems/alignment-system.md` § "Derivación emergente".

> Los ejemplos de `examples/` se dividen en dos grupos:
> - **`Axill_Garner.md` y `Kae_Turant.md`** = fichas reales del autor (mundo Vibrantes). Traen color de
>   mundo porque son del mundo. Sirven como fieles del formato de salida de **1º nivel**.
> - **`Secundario_Ejemplo.md`, `Relleno_Ejemplo.md` y `Villano_Korrane.md`** = **ilustrativos de
>   estructura** (no canon). Los fundacionales (`Villano_Korrane.md`) son **agnósticos al mundo**:
>   sin Stal, sin lugares, sin razas de mundo. El color de mundo lo aporta la Skill Personalizada
>   por Mundo (decisión #10).
>
> `Villano_Korrane.md` es además un documento **pre-cambio**: usa `VILLANO` como valor de rol y un
> `Alineamiento Moral` único al inicio, ambos superados por la **taxonomía densidad-solo** (decisión
> #14) y el **alineamiento emergente `inicial → revelado`**. El runtime ya no lo sirve: la semilla
> v1.2 publica 3 carriers `adjunto-nivel-*` en `data/methodology/seeds/narrative-character-creation/`.
>
> **Divergencia docs ↔ semilla (PR ⑥, intencional).** Las **3 copias fundacionales originales** que el
> runtime servía como adjuntos (hoy **3 carriers** en la semilla v1.2) viven en `data/methodology/seeds/narrative-character-creation/` y fueron
> **reescritas agnósticas al mundo** en el PR ⑥: sin "Axill"/"Kae"/"Ciudad Mineral"/"Humano
> Vibrante"/"escena del mercado"/"compañía de plataformas" (roles genéricos), errata
> "Cresció"→"Creció" y títulos unificados. Los originales de `examples/` de este README **no** se
> tocaron: son textos **pre-⑥** que conservan el color de mundo. El byte-mirror docs ↔ semilla queda
> **intencionalmente roto** y se acepta (decisión D6, PR ⑥ `copy-polish-pass`).
>
> **Set de 3 (D5 — cierre del registro; aplicado en v1.2).** `Axill_Garner.md` y `Kae_Turant.md`
> **permanecen docs-only**: el runtime sirve **un pin por nivel narrativo** (1º/2º/3º), por lo que un
> segundo carrier de 1º nivel nunca se sirve; además ambos traen color de mundo Vibrantes, que contradice el
> principio fundacional agnóstico (#10). La semilla v1.2 consolida ese argumento con un único pin `1º`
> (`adjunto-nivel-1-unico.md`); los tres pins `1º` de 1.1 quedan en disco byte-idénticos y sin listar.

## Decisiones abiertas (para resolver en la skill)

1. **¿El alineamiento es semilla (se elige primero, brújula de la charla) o etiqueta derivada
   (surge al final, resumen/verificación)?** La filosofía 40/60 inclina a la segunda (diálogo primero,
   estructura emerge), pero el alineamiento es bastante estructural para ser semilla.
2. **¿Qué se pregunta DIRECTAMENTE vs qué emerge del diálogo?** (Pendiente de cerrar).
   Directo casi seguro: nombre, edad, raza/especie, género, sexualidad. El resto emerge o se propone.
3. **Gap de integración en runtime** (ver `skill-library-and-guided-character-creation.md`):
   la `SKILL.md` es un artefacto estático que el runtime no lee. El diseño de contenido de la skill
   necesita conectar con el runtime (prompt dinámico en vez de fijo).
4. **¿Cómo indexa el grafo los campos de mundo (Stal, etc.)?** Dos opciones: (a) genérico — el índice lee
   cualquier campo extra que la skill declare como indexable; (b) **schema por mundo** — la skill declara
   su schema de campos y el índice lo consulta para saber qué indexar. La (b) es más determinista y "sin
   ambigüedad", pero requiere que el índice consulte el schema del mundo activo.

## Nota sobre el legacy

`skills/crear_personaje.md` es el **enfoque legacy "7/12/18 preguntas"** (relleno/secundario/principal
por CANTIDAD de preguntas). Ese enfoque está **descartado**: contradice el principio 40/60 (no
cuestionario). No se debe usar como base de la nueva skill; sirve solo como referencia histórica.

## Archivos relacionados (no rediseñar, son contrato de runtime)

- `docs/architecture/skill-library-and-guided-character-creation.md` — contrato de la biblioteca de
  skills y el flujo guiado de creación de personaje (runtime, máquina de estados, certidumbre, 40/60).
- `skills/narrative-character-creation/SKILL.md` — skill v1.0 actual (rails de comportamiento).
- `skills/narrative-character-creation/references/conversation-examples.md` — ejemplos de técnica de
  exploración (reflejo → tensión → una pregunta).
- `docs/architecture/world-workshop.md` — contrato del Taller de Mundo.
