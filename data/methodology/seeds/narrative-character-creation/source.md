# Creación de Personajes — Metodología Fundacional

## Propósito

Metodología fundacional para co-crear, junto al Autor, un personaje narrativo
**NUEVO** en cualquier mundo. Es universal: aplica a cualquier mundo cargado en
Demiurgos y no contiene parámetros de ningún mundo específico. El esqueleto de
la ficha es el mismo para todos los personajes: **identidad, carácter,
Eneatipo, Subtipo, Arquetipo, Alineamiento, conflicto y arco**.

El color de mundo (Stal, lugares, razas, poderes de un mundo concreto) NO
pertenece a esta metodología: lo aporta la **Skill Personalizada de Mundo**,
creada por el Autor desde el Taller de Herramientas y activada por mundo. Al
crear una ficha en ese mundo, se invoca esa skill y se enriquece el personaje.

## Principio 40/60

El 40/60 es el **comportamiento del asistente**, no una regla matemática ni un
cuestionario:

- El **40% determinista** son las anclas de canon: identidad y datos duros que
  el Autor declara. Son la base estable de la ficha.
- El **60% flexible** es el diálogo: la exploración creativa que hace volar al
  Autor. No es "el 40% del texto".

La metodología NO usa formularios ni conteos fijos de preguntas (el enfoque
legacy "7/12/18" está descartado: contradice el principio 40/60). Se conversa,
una pregunta a la vez.

## Principios de co-creación

1. **Nada persiste sin aprobación explícita.** El asistente no tiene
   autoridad de escritura: todo queda en propuesta diskless hasta que el Autor
   aprueba explícitamente.
2. **Distinguir siempre los tipos de contenido:** **hechos** (dichos por el
   Autor), **propuestas**, **hipótesis**, **desconocidos** y **conflictos**.
   Nunca se presentan detalles inventados como canon.
3. **Una pregunta a la vez.** Jamás se lanzan formularios ni listas de campos
   a rellenar.
4. **Las salvaguardas son del servidor** (gate mínimo de identidad + deseo,
   revisiones, token de confirmación, digest de contenido). La metodología no
   las evita ni las reemplaza: trabaja dentro de ellas.
5. **La ficha activa es contexto, no objetivo.** Si existe una ficha activa,
   se confirma primero si el destino es el personaje NUEVO o una edición. Las
   referencias nombradas son contexto, salvo selección explícita del Autor.

## Ámbito y frontera

Esta metodología se usa para crear un personaje NUEVO. No aplica a:

- Editar una ficha existente.
- Rosters de personajes dentro de un arco.
- Consultas de lore.

| Situación | Acción |
|---|---|
| Personaje nuevo | Esta metodología |
| Editar ficha / roster de arco | Otro flujo (spec de personaje) |
| Modo rápido ("sin preguntas") | Supuestos marcados como tales; se salta el gate mínimo |
| Ancla faltante | Una pregunta por identidad (nombre) o deseo definidor |

## Proceso de co-creación

1. **Objetivo y contexto.** Confirmar personaje NUEVO, el mundo y la relación
   con la ficha activa (si existe).
2. **Consulta de grafo.** Buscar referencias nombradas en el grafo
   (search → read → links) para anclar el contexto. Contexto acotado: sin
   rutas internas ni provenance visible.
3. **Rol y profundidad.** Preguntar por el rol narrativo y la profundidad
   deseados, de forma conversacional, sin rangos fijos.
4. **Anclas mínimas.** Recoger **identidad + deseo definidor** (gate del
   servidor) y, si aplica, un conflicto significativo y una relación/rol
   clave. Pequeño, no exhaustivo.
5. **Exploración adaptativa.** Reflejar lo dicho, identificar UNA tensión
   prometedora y hacer UNA pregunta enfocada. Opciones solo si ayudan (máx.
   5). Se profundiza el mundo, no se recogen campos.
6. **Certeza y provenance.** Etiquetar hechos, propuestas, hipótesis,
   desconocidos y conflictos con su origen. Confirmar la certeza cuando un
   dato contradice o amplía el mundo.
7. **Convergencia.** Cuando hay anclas y el Autor está satisfecho, resumir y
   ofrecer la propuesta.
8. **Propuesta diskless.** Serializar la ficha en `personajes/{slug}.md` con
   status "proposed". No se escribe nada en canon.
9. **Aceptar o rechazar.** El Autor aprueba o descarta cada propuesta. Solo la
   aceptación la convierte en canon.
10. **Aprobación final.** Diff con digest enlazado al token de confirmación.
    Se persiste SOLO tras la aprobación explícita.
11. **Persistencia e indexado.** Reconciliar el grafo tras crear
    (indexed/pending/dirty/failed; reintentar si no indexa).

## Formato de ficha (esqueleto universal)

La ficha usa un formato **acotado**, no inflado. Los campos son universales de
personaje; ningún campo depende de un mundo concreto.

### Identidad Base

Nombre, apodo, edad, raza/especie (a definir por el mundo; si se omite, se
describe de forma agnóstica), lugar de origen (universal, sin nombrar un mundo
específico), género, sexualidad, familia, estudios, trabajo, religión (se
describe sin nombrar una religión de mundo), posesiones valiosas y metas.

### Aspecto Físico

Descripción breve y memorable del cuerpo, la postura y los rasgos distintivos.
Un defecto o detalle físico pequeño suele bastar para hacerlo inolvidable.

### Psicología y Carácter

- **Virtudes (3)** y **Defectos (3)**: rasgos que definen cómo es el
  personaje y cómo se relaciona con el mundo.
- **Adora / Odia / Teme:** preferencias y miedos cortos y concretos.
- **Fortalezas / Debilidades:** capacidades y grietas que explican su
  comportamiento.

### Psique (sistema)

- **Eneatipo:** uno de los 9 eneatipos (con su nombre), con el descentramiento
  bajo estrés cuando aplica.
- **Subtipo:** uno por personaje, de los tres instintos (conservación, social,
  sexual/transmisor).
- **Arquetipo:** según la profundidad del rol (3, 2 o 1 arquetipo).
- **Alineamiento inicial:** cómo se lee el personaje al inicio; se deriva al cierre.
- **Alineamiento revelado:** qué revela su conducta final; se deriva al cierre.

### Motivaciones

- **Conflicto interno:** la tensión psicológica que sostiene al personaje.
- **Conflicto externo:** la fuerza del mundo que se le opone.
- **Rol en la historia:** la función narrativa que cumple ante el lector.

### Trasfondo

Historia previa que explica quién es y por qué actúa como actúa. La extensión
escala con el nivel narrativo (completa en 1º, mínima en 2º, inexistente en 3º).

### Arco de Personaje

Trayectoria **interna**, agnóstica a trama: no nombra eventos de una historia
específica. Estructura en Actos (I, II1, II2, III) para personajes de 1º
nivel; los demás niveles no llevan arco completo.

En el 1º nivel el arco sostiene la trayectoria del Alineamiento acto a acto
(`inicial` → `revelado`): la trayectoria vive en el arco, no se pregunta como
campo.

## Densidad por nivel narrativo

La profundidad NO es "más texto": es estructura que escala con el peso del
rol. Cada nivel tiene su propio recorte:

| Nivel | Rol | Arquetipos | Qué se mantiene | Qué se omite |
|---|---|---|---|---|
| **1º** | Principal / Coprotagonista / Antagonista / Villano | 3 | Todo el formato fundacional completo | — |
| **2º** | Secundario | 2 | Identidad mínima + rol narrativo + relación con el protagonista + aspecto con defecto + carácter 2×2 + función + mini-arc opcional | Conflicto profundo, arco 3 actos, trasfondo extenso, perfil de voz |
| **3º** | Relleno | 1 | Nombre + función en la escena + 1 rasgo distintivo | Todo lo narrativo |

**Regla de oro:** si un personaje necesita más de "nombre + función + un
rasgo", NO es relleno — hay que subirlo a secundario.

## Sistema psíquico

### Eneatipo

Nueve tipos de personalidad (E1 El Perfeccionista, E2 El Ayudador, E3 El
Triunfador, E4 El Individualista, E5 El Observador, E6 El Leal, E7 El
Entusiasta, E8 El Desafiante, E9 El Pacificador). Cada eneatipo tiene una
pasión dominante, una herida y un camino de crecimiento.

**Regla de derivación:** el eneatipo **emerge de la descripción final**, no se
pregunta en la fase 1. El razonamiento de derivación es del asistente, no del
personaje: se lee la esencia final del personaje (su lealtad, su miedo, su
motor) y se deriva el eneatipo y el subtipo. El descentramiento bajo estrés
describe cómo se comporta el personaje cuando pierde el equilibrio.

### Subtipo

Cada personaje tiene UN subtipo, basado en su instinto primario:

- **Conservación:** seguridad personal, entorno controlado, bienestar material.
- **Social:** pertenencia a grupos y comunidades, cumplimiento de normas por
  protección.
- **Sexual/Transmisor:** conexiones intensas y personales, búsqueda de
  vínculos profundos.

### Arquetipo (7×7, 49 arquetipos)

Los arquetipos son moldes psicológicos universales (no estereotipos) que dan
consistencia y profundidad. Se organizan en dos ejes: **"Qué busca"** × **"Lo
consigue con"**. La **grieta** entre lo que el personaje busca y cómo lo
consigue es la fuente del conflicto interno.

La generación usa moldes simultáneos e independientes, por par
Fila × Columna, rellenando huecos para que calce. La profundidad escala con el
rol: 3 arquetipos (1º nivel), 2 (2º nivel), 1 (3º nivel).

### Alineamiento

Sistema de alineamientos **propio**, organizado por nivel del personaje —
NO es D&D. Dos ejes: **orden × moral**. El eje de orden habla de la relación
con la autoridad y las estructuras; el eje moral habla de la calidad de las
acciones (benigno, moral, neutral, mezquino, maligno, vil). Cada nivel tiene
su propia lista:

- **Relleno:** 9 alineamientos (Social/Neutral/Rebelde × Moral/Neutral/Mezquino).
- **Principal o Secundario:** 25 alineamientos (Legal/Social/Neutral/Rebelde/
  Caótico × Benigno/Moral/Neutral/Mezquino/Maligno).
- **Inmortales:** 24 alineamientos (Axiomático/Legal/Social/Neutral/Rebelde/
  Caótico/Anárquico × Virtuoso/Benigno/Moral/Neutral/Mezquino/Maligno/Vil).

**Regla de derivación:** el alineamiento **emerge de la descripción final**, no
se pregunta en la fase 1. El razonamiento de derivación es del asistente, no
del personaje: se lee la conducta final y se derivan los dos valores
(`inicial` y `revelado`). El **eje moral** se lee de la CONDUCTA —lo que el
personaje hace y lo que está dispuesto a sacrificar—, NO de su autoimagen; el
**eje de orden** se lee de su relación con la autoridad y las estructuras.
Ambos valores pertenecen a la lista canónica del nivel.

Guardrails: no confundir los ejes ("Legal" es orden/autoridad, "Moral" es
calidad). La lista de cada nivel es la fuente canónica; esta metodología cita
la fuente, nunca la redefine. El **eje moral** NO se deriva de la autoimagen:
el desalineamiento entre autoimagen y conducta es material del arco (`inicial`
vs `revelado`).

El **espécimen de 1º nivel** enseña la regla con personajes de moralidad
**AMBIGUA**: ningún ejemplo muestra un giro moral inequívoco —ni héroe ni
villano claros—, porque la ambigüedad es el material del arco, no su excepción.
Las etiquetas morales describen CONDUCTA, nunca el formato ni el rol.

## Herramientas de diagnóstico (lente del asistente)

Son herramientas internas de construcción y validación de la psique. NO son
campos que el Autor rellena ni van en la ficha:

- **11 creencias irracionales (Ellis):** alimentan el **conflicto interno**.
  Universal: aplica a cualquier personaje.
- **15 puntos del villano arquetípico:** alimentan el **rol en la historia** y
  la validación del personaje. Lente aplicable a antagonistas y a cualquier
  personaje cuya conducta se revele como tal.

## Guardarraíles

1. **Agnóstica al mundo:** nunca usar vocabulario de un mundo concreto (Stal,
   lugares, razas, poderes de mundo). El enriquecimiento por mundo entra en
   una capa aparte, provista por la Skill Personalizada de Mundo.
2. **Formato acotado:** el canon de formato es el ejemplo de 1º nivel
   acotado. La sobre-generación es un contra-patrón: más texto no es más
   profundidad.
3. **La ficha activa no se edita de paso:** si el Autor quiere editar, se va
   al flujo de edición, no se mezcla con la creación.
4. **La distinción fóbico/contrafóbico no pertenece a este sistema:** no se
   usa.
5. **La metodología extiende contenido y método, nunca el núcleo del
   servidor:** los campos de seguridad, permisos y ejecución son del servidor.