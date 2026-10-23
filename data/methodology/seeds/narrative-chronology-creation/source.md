# Creación de Cronologías — Metodología Fundacional

## Propósito

Metodología fundacional para co-crear, junto al Autor, un **suceso** de la
historia de cualquier mundo. Es agnóstica al mundo: aplica a cualquier mundo
cargado en Demiurgos y no contiene parámetros de ninguna ficción concreta. Su
forma es `cronologia` — el tiempo de la ficción: qué ocurrió, cuándo y qué
cambió.

El color del mundo (nombres, eras, calendarios, dinastías) NO pertenece a esta
metodología: lo aporta la **Skill Personalizada de Mundo**, creada por el Autor
desde el Taller de Herramientas y activada por mundo. Al narrar un suceso en ese
mundo, se invoca esa skill y se enriquece el suceso.

## Principio

El método es un **contrato de preguntas mínimas y semánticas** más una
**ramificación por escala**. NO impone un registro fijo de columnas
fecha/causa/consecuencia: eso convertiría la historia en una tabla y dejaría
fuera el tiempo mítico, la cosmología o la memoria contradictoria.

El cuerpo del suceso **emerge** de las respuestas. El envelope, en cambio, es
fijo y vive en **OKF** (identidad, relaciones, mínimos por forma). Las reglas de
la metodología son preguntas que deben tener respuesta, no campos que se
rellenan a la fuerza.

Una advertencia ordena todo lo demás: **una lista de fechas no es historia**. Un
suceso sin cambio no es un suceso, es una efeméride.

## Unidad: el suceso

La unidad de co-creación es **un suceso**, y cada suceso es una **ficha**.
`era` y `proceso` no son fichas-colección: son **escalas** del mismo método.

- Un `evento` puntual es una ficha.
- Un `proceso` es una ficha de tipo `evento` con `orden_fin`: el intervalo es
  dato, no una etiqueta.
- Una `era` es una ficha de tipo `era`: un intervalo con fronteras y un rasgo
  definitorio.

No existe un tipo `proceso` en el kernel: la escala es conversacional. El tipo
de ficha debe ser uno que el kernel mapee a `cronologia` (`evento`, `era`,
`historia`). Si el mundo declara su propio tipo, lo aporta su skill de mundo.

La línea temporal **emerge** del orden y de las relaciones entre fichas. No se
escribe una ficha "cronología" que contenga toda la historia en su cuerpo.

## Modelo temporal

La fecha tiene dos capas, y las dos importan:

- **`fecha`** — texto nativo del mundo, obligatorio para la forma. Es lo que el
  Autor lee: "3ª Era, año 412", "el año de la Gran Marea".
- **`orden`** — número opcional que sitúa el suceso en el eje del mundo.
  `orden_fin` marca el final de un intervalo. Admiten decimales y negativos
  (antes de la época cero).

El **eje se declara una vez por mundo**: época cero y unidad. No se impone un
calendario terrestre. Si el mundo todavía no tiene eje, se pregunta una sola vez
y queda como convención del mundo.

Reglas duras del ancla:

1. Si el Autor no puede situar el suceso en el eje, se **omite** `orden`.
   **Nunca se inventa un número.**
2. `orden` **no sustituye** a `fecha`: una ficha que solo tiene número está
   incompleta.
3. Sin ancla, el suceso se ordena por su predecesor enlazado. Si tampoco lo
   tiene, queda **sin anclar**, y eso se declara, no se disimula.

## Preguntas universales

Toda respuesta se conversa, una pregunta a la vez. Las nueve preguntas son:

1. **Nombre y escala.** ¿Qué es y a qué escala? (`evento` puntual, `proceso`
   con intervalo, `era` con fronteras).
2. **Ubicación temporal.** ¿Cuándo? Fecha nativa y, si se puede, ancla. Es
   **riel**.
3. **Qué ocurrió.** El hecho, en una frase.
4. **Qué cambió.** Antes → después. Es **riel**. Sin esto no hay historia.
5. **Causa.** ¿Qué lo provocó? Puede ser impersonal (un proceso natural) o
   quedar **abierta a propósito** (un misterio).
6. **Agencia.** ¿Quién lo protagonizó o lo sufrió? Se marca **N/A** si el suceso
   es impersonal.
7. **Alcance.** ¿Qué fichas toca? Sistemas, entidades, lugares. Se expresa con
   `relaciones`.
8. **Versión y verdad.** ¿Cuál es su `canon_state`? Si hay relatos rivales,
   ¿cuál es canon y quién recuerda qué?
9. **Encadenado.** ¿Qué lo precede y qué se deriva de él? Da el orden relativo
   cuando las fechas nativas no son comparables.

## Eje de agencia

Los sucesos con **operador** (una guerra, un asesinato, una ley) responden la
causa y la agencia. Los sucesos **impersonales** (una catástrofe natural, un
colapso estelar, una era geológica) declaran la causa como impersonal,
desconocida o abierta y marcan la agencia como **N/A**.

Este eje no cambia las preguntas: cambia cómo se responden la 5 y la 6. La
ubicación temporal y el cambio siguen siendo obligatorios.

## Ramificación por escala

La respuesta a (1) elige un **paquete de vocabulario** que re-instancia las
preguntas 2 y 4 en los términos de la escala:

| Pregunta | `evento` | `proceso` | `era` |
|---|---|---|---|
| 2 · cuándo | una fecha puntual | inicio y fin | fronteras |
| 4 · qué cambió | de golpe | gradualmente, y su punto de no retorno | el rasgo que la define y qué la cierra |

Una `era` no contiene sucesos en su cuerpo: los **enlaza**. Del mismo modo, un
`proceso` no narra cada fase como una ficha hija salvo que el Autor quiera
hacerlo.

## Rieles 40%

Un suceso está **incompleto** si no responde **ubicación temporal (2)** o
**qué cambió (4)**. No son columnas: son preguntas que deben tener respuesta.
La causa (5) y la agencia (6) pueden faltar o marcarse N/A; el riel no se
negocia.

En una `era`, el riel se lee como fronteras (2) y rasgo definitorio con cierre
(4).

## Composición

`Cronología` es la forma donde convergen las demás. Un suceso enlaza:

- el **sistema** cuyas reglas mutan. `Sistema` declara su estabilidad en su
  pregunta 9; el cambio concreto se narra aquí, no en la ficha del sistema;
- la **entidad** que muere, nace, asciende o desaparece;
- el **lugar** que se funda, se pierde o se transforma;
- otros **sucesos**, en cadenas de causa y consecuencia.

El suceso **enlaza, nunca reescribe** la ficha afectada. Para que ficha y
cronología no se contradigan, se declara el **presente narrativo** del mundo: la
ficha describe el mundo en ese presente y el suceso narra cómo llegó ahí. Si no
hay presente declarado, se usa el último suceso canónico.

## Verdad y versiones

La verdad se declara **por suceso**, con `canon_state`. Un mismo hecho puede ser
`canon` para unos y `leyenda` o `creencia` para otros: eso no se resuelve
duplicando el suceso, sino creando una ficha de `creencia` o `leyenda` (forma
`entidad`) enlazada al suceso. El suceso canónico sigue siendo uno.

## Validación anti-sobreajuste

El método se valida contra cuatro casos, y al menos dos NO son épica fantástica:

- **Guerra multiescala** — una era, varios procesos y batallas puntuales
  componen sin añadir preguntas.
- **Biografía** — fechas nativas, causa opcional, agencia siempre presente.
- **Cosmología impersonal** — tiempos enormes, sin agente; causa impersonal y
  agencia N/A.
- **Historia contestada** — un hecho, dos memorias; canon y creencia enlazada.

Si un caso exige una pregunta nueva, el método se revisa; no se parchea el caso.

## Ámbito y frontera

Esta metodología se usa para crear un suceso NUEVO. No aplica a:

- Editar una ficha existente.
- Escribir la prosa narrativa de la historia (eso es oficio del Autor).
- Decidir el gobierno de canon o resolver conflictos entre fuentes.
- Volcar una cronología entera en una sola ficha.
