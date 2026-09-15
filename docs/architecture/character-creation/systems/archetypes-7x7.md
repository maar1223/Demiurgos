# Arquetipos de Personalidad (7×7) — Generador de Tensión

> **Referencia de la Skill de creación de personajes.**
> **Fuente canónica:** [`eneagrama-arquetipos-alineamientos.md`](eneagrama-arquetipos-alineamientos.md)
> (autor, un solo lugar) — contiene los **49 arquetipos** con su descripción de una línea
> (numerados 1–49). Este archivo es la GUÍA DE USO (los ejes y la lectura de la grieta), NO redefine las
> descripciones. La matriz cruzada fue reconstruida y NO es autoritativa frente a la fuente.

## Qué es

Un arquetipo de personalidad es un conjunto de características y patrones de comportamiento que definen
a un tipo de personaje en la narrativa. Son moldes que representan patrones psicológicos básicos y
universales, ayudando a crear personajes con personalidades consistentes y reconocibles. **No son
estereotipos** — son esquemas que dan profundidad y claridad a un personaje cuando se desarrollan bien.

## Cómo se lee (los ejes)

La matriz **7×7** cruza dos ejes:

- **Qué Busca** (fila) — la motivación central del personaje.
- **Lo Consigue Con** (columna) — el método que usa para lograrlo.

La **intersección** da el arquetipo (ej.: "Qué busca: Confianza" × "Lo consigue con: Mística" =
**El Ancla**). Los ejes son: **Innovación · Pasión · Poder · Prestigio · Confianza · Mística · Alerta**.

## Lectura de la grieta (lo importante para la skill)

El arquetipo en la **diagonal** (busca X y lo consigue con X) es coherente — poca tensión.
El arquetipo **fuera de la diagonal** (busca X pero lo consigue con Y) tiene una **grieta interna**:
persigue algo que su método contradice. Esa grieta ES el conflicto interno, y es sobre lo que la skill
debe hacer la pregunta de fricción.

> Los **49 arquetipos numerados con descripción** están en la fuente canónica
> (`eneagrama-arquetipos-alineamientos.md` § "49 arquetipos de personalidad"). Los nombres y
> descripciones de la fuente son autoritativos; la matriz cruzada de este folder es solo orientativa.

## Profundidad por tipo de personaje (número de arquetipos)

> **Más arquetipos = más profundidad.** La cantidad escala según el peso del rol (coherente con la
> densidad del formato: la profundidad NO es "más texto" — es estructura que escala con el rol).

| Nivel | Rol | Nº de arquetipos |
|---|---|---|
| **1º** | Principal / Antagonista / Coprotagonista | **3** |
| **2º** | Secundario | **2** |
| **3º** | Relleno | **1** |

## Mecánica de generación (validada con el proto-Demiurgos, Excel/Google Sheets ~2021)

> **Cómo se relacionan los arquetipos entre sí — CONFIRMADO** por el proto-Demiurgos del autor
> (software en Excel/Google Sheets con macros, ~2021). NO hay jerarquía de "dominante/fricción/
> transformación" (hipótesis descartada). Los arquetipos son **moldes simultáneos e independientes**
> que coexisten; las contradicciones entre ellos son la profundidad, no un defecto.

**La mecánica del proto (a replicar en la skill, pero conversacional):**

1. **Elegir el nivel** del personaje → determina la cantidad de arquetipos
   (Relleno=1 / Secundario=2 / Principal, Antagonista, Coprotagonista=3).
2. **Elegir/randomizar cada arquetipo** usando un par `Fila × Columna` del grid 7×7. Cada intersección
   da un arquetipo distinto (ej. `3×7` = "El Viejo Soldado", `1×1` = "El Anarquista", `6×5` = "El Arquero").
   En el proto se randomizaban; en la skill el asistente los **propone** al autor (o randomiza si el autor
   lo pide) — el autor confirma.
3. **Derivar el alineamiento** al cierre según el nivel (lista del nivel: Relleno=9 ·
   Principal-Secundario=25 · Inmortal=24); es una **trayectoria emergente `inicial → revelado`**, no un
   campo de la fase 1 (ver `alignment-system.md` § "Derivación emergente").
4. **El 40/60 aplica acá de lleno:** los **arquetipos** son las **ANCLAS deterministas** (el 40% — no
   negociables); el alineamiento se **deriva** al cierre. El **60% flexible** es que el creador
   **rellené los huecos y haga que todo
   calce** (aspecto, carácter, conflicto, trasfondo, arco) — haciendo que los moldes convivan.

**Por qué funciona:** al randomizar/combinar arquetipos de forma impredecible, el creador **no siempre
genera el mismo personaje**. La combinación siempre distinta produce personajes vivos, diferentes entre
sí, que luego se obligan a convivir en el mismo mundo — siendo tan dispares como para que la interacción
genere historia. Es creación con variedad genuina, no plantillas repetidas.

**Cómo se aplica en la skill:** el asistente NO ordena los arquetipos en una jerarquía. Los presenta como
moldes coexistentes (posiblemente contradictorios) y guía al autor para que el resto de la ficha **calce**
con ellos, sin forzarlos a ser coherentes. La contradicción es el material del personaje.
