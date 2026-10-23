# Creación de Entidades — Metodología Fundacional

## Propósito

Metodología fundacional para co-crear, junto al Autor, una **entidad** de
cualquier mundo: un lugar, una facción, una criatura, un artefacto, una cultura
o una especie. Es agnóstica al mundo: aplica a cualquier mundo cargado en
Demiurgos y no contiene parámetros de ninguna ficción concreta. Su forma es
`entidad` — lo que **es** el mundo: sus geografías, sus gentes, sus cosas y sus
seres, independientemente de las reglas que los gobiernan.

El color del mundo (nombres propios, topónimos, linajes, idiomas) NO pertenece a
esta metodología: lo aporta la **Skill Personalizada de Mundo**, creada por el
Autor desde el Taller de Herramientas y activada por mundo.

## Principio

El método es un **contrato de preguntas mínimas y semánticas** más una
**ramificación por clase de entidad**. NO impone un registro fijo de columnas
"descripción / historia / poderes": eso convertiría una ciudad, una religión y
una especie en la misma ficha y dejaría fuera lo que cada una tiene de propio.

El cuerpo **emerge** de las respuestas. El envelope, en cambio, es fijo y vive
en **OKF** (identidad, relaciones, mínimos por forma). Las reglas de la
metodología son preguntas que deben tener respuesta, no campos que se rellenan a
la fuerza.

Una advertencia ordena todo lo demás: **una entidad sin clase es un nombre
suelto**. La clase no es una etiqueta decorativa: es el eje que decide qué
vocabulario aplica al resto de las preguntas.

## Unidad: la entidad y su clase

La unidad de co-creación es **una entidad**, y cada entidad es una **ficha**. Un
lugar, una facción, una criatura, un artefacto, una cultura o una especie son
**clases de la misma forma**, no formas distintas: comparten preguntas y cambian
el vocabulario con que se responden.

La clase se persiste como campo (`clase`), no como tipo: la ficha se escribe con
`type: Entidad`. Ese `type` genérico es deliberado — el dominio es un parámetro,
no una rama del motor — y por eso la clase es un mínimo obligatorio: sin ella el
índice no podría distinguir un lugar de una criatura.

Una entidad no contiene colecciones en su cuerpo: una cultura no guarda sus
subculturas como fichas hijas, una facción no guarda a todos sus miembros y una
especie no narra cada ejemplar. Las **enlaza**.

## Preguntas universales

Toda respuesta se conversa, una pregunta a la vez. Las nueve preguntas son:

1. **Nombre y clase.** ¿Qué es y de qué clase? (`lugar`, `facción`, `criatura`,
   `artefacto`, `cultura`, `especie`). Es **riel**: sin clase no hay rama.
2. **Qué es.** Una frase que lo defina para alguien que no conoce el mundo.
3. **Rasgo definitorio.** ¿Qué la hace ser ella y no otra de su clase? Es
   **riel**: sin esto hay descripción, no entidad.
4. **Origen o historia.** ¿Cómo llegó a ser lo que es? Puede ser geología,
   fundación, evolución, fabricación, migración o tradición.
5. **Función o papel.** ¿Qué permite, impide u organiza en el mundo? ¿A quién
   sirve, a quién enfrenta, qué lugar ocupa?
6. **Relaciones.** ¿Qué otras fichas toca? Otros lugares, sistemas, personajes,
   sucesos. Se expresa con `relaciones` y wikilinks.
7. **Estado de verdad.** ¿Cuál es su `canon_state`? Si hay versiones rivales,
   ¿cuál es canon y quién cree qué?
8. **Composición** *(condicional, si es colectiva)*: ¿quiénes la forman, cómo se
   reconoce a un miembro, qué grados o variantes tiene? Se marca **N/A** para
   una entidad singular (un artefacto único, una ciudad concreta).
9. **Encadenado.** ¿Qué la contiene y qué contiene? ¿Qué la sostiene y de qué
   depende? Da el contexto que las respuestas anteriores no capturan.

## Ramificación por clase

La respuesta a (1) elige un **paquete de vocabulario** que re-instancia las
preguntas (3), (4) y (8) en los términos de la clase:

| Pregunta | `lugar` | `facción` | `criatura` | `artefacto` | `cultura` | `especie` |
|---|---|---|---|---|---|---|
| 3 · rasgo | geografía y frontera | quiénes la unen y qué las une | forma de vida y comportamiento | qué hace y qué exige portarlo | costumbres y valores | biología y rasgos compartidos |
| 4 · origen | geología o historia | fundación o escisión | evolución o creación | quién lo fabricó y por qué | tradición o migración | evolución o creación |
| 8 · composición | quién vive ahí | miembros y grados | etapas y variantes | partes y portadores | subculturas y linajes | subespecies y variantes |

La clase es **única**: se rechazan las etiquetas combinadas ("lugar-facción",
"criatura-artefacto") porque vuelven ambigua la rama. Una entidad que se comporta
distinto a su clase lo **describe en el cuerpo**, no en la clase.

## Rieles 40%

Una entidad está **incompleta** si no responde **clase (1)** o **rasgo
definitorio (3)**. No son columnas: son preguntas que deben tener respuesta. Las
demás pueden faltar, marcarse N/A o quedar abiertas a propósito, pero el riel no
se negocia.

En una entidad colectiva, el riel se lee como **clase (1)** y **rasgo compartido
(3)**; la composición (8) aclara quiénes lo encarnan, no lo sustituye.

## Frontera con Sistema

`Sistema` es la forma de las **reglas**: qué permite el mundo, qué exige y dónde
está su límite. `Entidad` es la forma de **lo que existe**: el lugar, la
organización, el ser, la cosa.

Un poder innato, una tecnología, una ley de la naturaleza o una economía **no
se describen aquí como reglas**: se declaran en un `Sistema` enlazado. La
entidad puede decir que una criatura respira bajo el agua o que un artefacto
"funciona"; el **cómo y a qué costo** pertenece al sistema.

La prueba es simple: si la pregunta es "¿qué puede hacer y qué no?", es Sistema;
si es "¿qué es y qué lugar ocupa?", es Entidad.

## Frontera con Cronología

`Cronología` es la forma del **tiempo**: qué ocurrió, cuándo y qué cambió. La
entidad describe el mundo en su **presente narrativo**; los sucesos que la
formaron se narran como fichas de cronología **enlazadas**, nunca dentro de su
cuerpo.

- La fundación de un lugar, la escisión de una facción, la extinción de una
  especie o la forja de un artefacto son **sucesos**: viven en `Cronología`.
- La entidad **enlaza, nunca reescribe** la ficha afectada.

## Frontera con Personaje

Una **persona con nombre, deseo y arco** es un `Personaje` y vive en
`personajes/`. Una **criatura** o una **cultura** describe la clase, el arquetipo
o el colectivo; un individuo concreto de esa clase que protagoniza una historia
es un personaje enlazado.

Si el foco es "quién es y qué quiere", es Personaje; si es "qué es y cómo se
reconoce", es Entidad.

## Verdad y versiones

La verdad se declara **por entidad**, con `canon_state`. Un mismo lugar puede ser
`canon` para unos y `leyenda` para otros: eso se resuelve creando una ficha de
`creencia` o `leyenda` enlazada, no duplicando la entidad. La ficha canónica
sigue siendo una.

## Validación anti-sobreajuste

El método se valida contra seis casos, y al menos dos NO son épica fantástica:

- **Ciudad** — lugar con geografía, historia y función; sin preguntas extra.
- **Gremio** — facción con miembros, grados y origen; la (8) hace el trabajo.
- **Idioma** — cultura con costumbres y linajes, no con "poderes".
- **Empresa** — facción moderna: fundación, función y composición.
- **Especie** — biología y variantes; la (8) distingue subespecies.
- **Reliquia** — artefacto único: la (8) se marca N/A y el riel sigue en pie.

Si un caso exige una pregunta nueva, el método se revisa; no se parchea el caso.

## Ámbito y frontera

Esta metodología se usa para crear una entidad NUEVA. No aplica a:

- Editar una ficha existente.
- Escribir la prosa narrativa del mundo (eso es oficio del Autor).
- Decidir el gobierno de canon o resolver conflictos entre fuentes.
- Declarar reglas, costos o límites (eso es `Sistema`).
- Narrar sucesos o eras (eso es `Cronología`).
