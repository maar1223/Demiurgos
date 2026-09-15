# Sistema de Alineamientos de Personajes

> **Referencia de la Skill de creación de personajes.**
> **Fuente canónica:** [`eneagrama-arquetipos-alineamientos.md`](eneagrama-arquetipos-alineamientos.md)
> (autor, un solo lugar). Este archivo es la GUÍA DE USO (cómo aplicar), NO redefine los valores.
> El sistema NO es el grid de 9 de D&D (Lawful Good / Chaotic Evil). Es custom y se organiza
> **por nivel del personaje**, no como matriz genérica.

## Qué es y cómo se lee

> **Los alineamientos son la forma en como el personaje Actúa frente a las situaciones y determinan
> en gran medida las decisiones que toma.** Al escoger un alineamiento hay que saber en qué punto se
> encuentra y, en consecuencia, **con qué extremo tendrá sus decisiones el personaje.**

Combinan **dos ejes** que se cruzan en cada valor:
- **Relación con el orden/autoridad** (columna): Axiomático · Legal · Social · Neutral · Rebelde · Caótico · Anárquico.
- **Calidad moral** (fila): Virtuoso · Benigno · Moral · Neutral · Mezquino · Maligno · Vil.

Cada alineamiento = un valor de cada eje. Ej.: **Legal Mezquino** (obedece el sistema pero lo usa para su
beneficio ruin) = una contradicción que es motor de conflicto.

## Estructura: el alcance del alineamiento depende del nivel del personaje

**La fuente canónica NO organiza los alineamientos en una matriz con rectángulos — los organiza en
tres LISTAS según el nivel del personaje.** Esto encaja exactamente con la densidad por rol:

| Nivel del personaje | Alineamientos disponibles | Dónde está la lista |
|---|---|---|
| **Relleno** | 9 valores (franja central, sin extremos) | Fuente canónica § "Relleno" |
| **Principal / Secundario** | 25 valores (columnas Social→Caótico × filas Benigno→Maligno) | Fuente canónica § "Principal o Secundario" |
| **Inmortal / No mortal / Dios** | 24 valores (columnas Axiomático/Anárquico + filas extremas Virtuoso/Vil) | Fuente canónica § "Inmortales" |

> **Eje C (psique inmortal):** los alineamientos de la lista "Inmortales" son exactamente los que la
> fuente reserva para seres de larga vida / no mortales / dioses. El alcance del alineamiento ya está
> resuelto por nivel — no hay que deducir rectángulos.

## Los tres alcances (resumen; valores íntegros en la fuente canónica)

**Relleno (9):** Social Moral · Neutral Moral · Rebelde Moral · Social Neutral · Neutral · Rebelde
Neutral · Social Mezquino · Neutral Mezquino · Rebelde Mezquino.

**Principal / Secundario (25):** Legal/Social/Neutral/Rebelde/Caótico × Benigno/Moral/Neutral/Mezquino/
Maligno, más los de la lista de Relleno (que quedan incluidos).

**Inmortales (24):** los que caen en Axiomático, Anárquico, o en las filas extremas Virtuoso/Vil.
Ej.: Axiomático Virtuoso, Legal Virtuoso, ..., Anárquico Vil, Anárquico Maligno, etc.

> ⚠️ Consultar SIEMPRE la lista íntegra en la fuente canónica antes de derivar un alineamiento.

## Derivación emergente (cómo se obtiene)

> **El alineamiento NO se pregunta en la fase 1: emerge de la descripción final**, igual que el
> **Eneatipo**. El razonamiento de derivación es del asistente, no del personaje: se lee la conducta
> final y se derivan los dos valores (`inicial` → `revelado`).

- **Eje moral = CONDUCTA, no autoimagen.** Se lee de lo que el personaje **hace** y de lo que está
  dispuesto a **sacrificar** — nunca de cómo se percibe o se presenta a sí mismo.
- **Eje de orden = relación con la autoridad y las estructuras** (sostiene el sistema o vive dentro de
  él, frente a regirse por su propio código o quedar fuera).
- **`inicial`** = cómo se lee el personaje al comenzar; **`revelado`** = qué revela su conducta final.
  El **desalineamiento autoimagen ↔ conducta** es material del arco, no un campo extra.
- Ambos valores pertenecen a la **lista canónica del nivel** (esta guía cita la fuente, nunca la
  redefine). La lista cambia con la densidad del rol; el **nivel mide densidad, no moralidad**.

## Cómo se usa en la ficha (formato canónico)

El alineamiento es un **campo de la ficha visible** (identidad/psique), no solo diagnóstico interno.
Son **dos valores derivados al cierre** — `Alineamiento inicial` (cómo se lee el personaje al
comenzar) y `Alineamiento revelado` (qué revela su conducta final) —, no un campo que se elija al
principio. La **lista** de la que se derivan depende del nivel (ver tabla de arriba): en primer nivel
va junto a Eneatipo + Subtipo + Stal + Arquetipo; en niveles menores se recorta según lo que el rol
requiera.

---

# Guardrails para la skill (anti-alucinación)

1. **NO es D&D.** Sistema custom, organizado por nivel, no el grid de 9. El asistente no debe usar
   vocabulario de D&D ("Lawful", "Chaotic", "Neutral Good").
2. **No confundir los ejes.** "Legal" es un valor del eje de **orden/autoridad**. "Moral" es un valor del
   eje de **calidad moral**. La tentación del LLM es colapsar ambos ("Legal Moral" leído como "bueno legal").
3. **El desalineamiento entre ejes es fuente de conflicto.** «Legal Mezquino» = obediente al sistema pero
   ruin → hipocresía → conflicto interno. «Anárquico Vil» = ejes alineados → villano plano salvo otra capa.
4. **La skill detecta ese desalineamiento** para hacer la pregunta de fricción (el 60% flexible).
5. **La fuente manda.** Cualquier valor de alineamiento debe pertenecer a la lista del nivel correcto en
   `eneagrama-arquetipos-alineamientos.md`. Nunca inventar una combinación fuera de esas listas.
6. **El eje moral NO se deriva de la autoimagen.** El desalineamiento entre cómo el personaje se percibe
   y cómo actúa (`inicial` vs `revelado`) es material del arco, no una tercera etiqueta.
