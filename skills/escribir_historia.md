# Skill: Escribir Historia

Skill del Sistema de Creación Narrativa (SCN) de Vibrantes.
Propósito: Guiar la escritura de relatos narrativos completos (formato libre) mediante preguntas estructuradas. Tú eliges las piezas narrativas, la IA ensambla el relato.

Flujo general:
**Semilla → Alcance → Protagonista → Piezas Narrativas → Arquitectura → Reparto → Ambientación → Escritura**

---

## FASE 0: LA SEMILLA

Decisiones fundacionales antes de elegir cualquier catálogo. Definen el rumbo de toda la historia.

### P0.1: Logline (máx 25 palabras)

La historia en una frase. Debe responder: ¿quién, quiere qué, qué pasa si no lo consigue?

**Regla:** Si no puedes contar tu historia en 25 palabras, no sabes qué historia es todavía.

> *Ejemplo: "Un tal Daest descubre que la mujer que lo crió no solo asesinó a su Orden, sino que sus órdenes vienen de algo más allá de su comprensión."*

### P0.2: Tipo MICE (Orson Scott Card)

¿Qué tipo de historia es? Elegir el dominante:

| Tipo | La historia promete... | Comienza cuando... | Termina cuando... |
|------|----------------------|--------------------|--------------------|
| **Milieu** | Viajar a un mundo extraño y entenderlo | El protagonista sale de su mundo conocido | El protagonista vuelve (o decide quedarse) |
| **Idea** | Descubrir una verdad oculta | Aparece una pregunta sin respuesta | La verdad se revela |
| **Character** | Que alguien cambie | El protagonista está insatisfecho consigo mismo | El protagonista se transforma |
| **Event** | Reparar algo que está roto en el mundo | Una amenaza altera el orden establecido | El orden se restaura (o no) |

**Importante:** El tipo MICE determina el ORDEN de las decisiones siguientes. Una historia Character pone al protagonista primero. Una historia Event pone la amenaza primero. Una historia Milieu pone el mundo primero.

### P0.3: Tema de la historia (una frase)

¿Qué quiere decir esta historia? No es el argumento — es la verdad que el lector se lleva.

> *Ejemplo: "El poder se demuestra soltando, no controlando."*

El Tema se enuncia en el beat 2 (Tema Expuesto) y se demuestra en el Final.

### P0.4: Contrato con el lector (una frase)

¿Qué prometes al lector? Si cumples esto, el lector queda satisfecho aunque la historia sea triste.

> *Ejemplo: "Prometo una historia de traición y redención donde la verdad es más poderosa que la fuerza."*

**Checkpoint FASE 0:** ¿Puedes contar el logline a alguien y que quiera leerla? Si no, revisa.

---

## FASE 1: ALCANCE

### P1: Extensión

| Opción | Palabras | Ideal para |
|--------|----------|------------|
| **Relato Largo** | < 10.000 | Historia de personaje, evento puntual |
| **Novela Ligera** | < 20.000 | Arco completo de personaje o saga menor |
| **Novela** | < 50.000 | Saga completa o múltiples arcos |

### P2: Ubicación en el universo

| Opción | Significado |
|--------|-------------|
| **Historia Paralela** | Mismo mundo, personajes distintos al main. No interactúa con la trama principal. |
| **Precuela** | Ocurre antes de la línea principal (Saga 01). Contexto o pasado. |
| **Simultánea** | Ocurre al mismo tiempo que otra historia. Los eventos pueden cruzarse. |
| **Secuela** | Ocurre después de otro evento. Muestra consecuencias. |
| **Independiente** | En otra región/nación, personajes completamente nuevos. Bajo requisito de canon. |

### P3: Título provisional (texto libre)

---

## FASE 2: PROTAGONISTA(S)

(Para historias tipo Event o Milieu, el protagonista se define después del mundo o la amenaza — pero se registra aquí.)

### P4: ¿Personaje existente o nuevo?

- **Existente:** cargar ficha desde `mundos/vibrantes/Personajes/`
- **Nuevo:** invocar `skill:crear_personaje.md` con rango Principal

Si la historia tiene múltiples protagonistas, repetir por cada uno.

### P5: Objetivo en esta historia (texto libre)

Describe brevemente qué busca lograr, enfrentar o descubrir.

---

## FASE 3: PIEZAS NARRATIVAS

> **Filtro según MICE (de FASE 0):**
> - **Character:** prioriza Conflictos internos (vs Sí Mismo, Autodescubrimiento) y Dilemas de identidad
> - **Event:** prioriza Conflictos externos (vs Individuo, vs Sociedad) y Dilemas de acción
> - **Idea:** prioriza Tramas de Revelación y Conflictos de conocimiento
> - **Milieu:** prioriza Tramas de Viaje y Conflictos con el entorno

### P6: Tipo de Trama

| # | Trama | Esencia | Ejemplo en Vibrantes |
|---|---|---|---|
| 1 | Misión de Escolta | Proteger algo/alguien de A a B | Gema de Sold inestable que atrae Áyagars |
| 2 | Infiltración / Robo | Entrar, tomar, salir | Stal 07 para burlar seguridad de un Pozo de Flud |
| 3 | Defensa de Asedio | Defender posición fija | Santuario de Dottua contra mercenarios de Saatia |
| 4 | Revelación Detectivesca | Conectar pistas, descubrir | Dvex analiza ondas de resonancia |
| 5 | Supervivencia en el Vacío | Entorno hostil, recursos escasos | Tormenta mística sin recarga de Staler |
| 6 | Duelo Jerárquico | Demostrar superioridad | Combate ritual entre Directores Stal 01 |

### P7: Conflicto principal

| # | Conflicto | Esencia |
|---|---|---|
| 1 | Individuo vs Individuo | Dos personas, mismos objetivos |
| 2 | Individuo vs Sociedad | Principios vs sistema |
| 3 | Individuo vs Naturaleza | Entorno letal |
| 4 | Individuo vs Sí Mismo | Lucha interna |
| 5 | Individuo vs Destino | Cambiar lo predeterminado |
| 6 | Individuo vs Religión/Ideología | Creencias cerradas |
| 7 | Individuo vs Prejuicios | Discriminación |
| 8 | Individuo vs Tecnología | Dvex que reemplazan humanos |
| 9 | Bien vs Mal | Dualidad clásica |
| 10 | Rechazo por la Diferencia | Aceptación propia |
| 11 | Viaje de Autodescubrimiento | Búsqueda de identidad |
| 12 | Salvar algo Preciado | Proteger lo que importa |
| 13 | Vencer el Pasado | Redención |

### P8: Dilema filosófico

| # | Dilema | Pregunta central |
|---|---|---|
| 1 | Libre albedrío vs Predeterminación | ¿Somos dueños de nuestra energía? |
| 2 | Destino Consciente | ¿Puedes ser libre sabiendo tu destino? |
| 3 | La Fuerza Superior | ¿Existencia predecible o anomalía? |
| 4 | Bien vs Mal Absoluto | ¿Pureza total o escala de grises? |
| 5 | El Fin justifica los Medios | ¿Acción mala por causa noble? |
| 6 | El Sacrificio del Mal | ¿El bien exige sacrificio? |
| 7 | Ley Moral vs Ley Humana | ¿Ley Stal sobre leyes humanas? |
| 8 | Justicia en el Caos | ¿Principios si el orden nace del caos? |
| 9 | Naturaleza vs Crianza | ¿Stal o crianza define quién eres? |
| 10 | Responsabilidad del Pasado | ¿Eres responsable si tu vibración cambió? |
| 11 | Bondad en la Crueldad | ¿Ser bueno donde sobrevive el fuerte? |
| 12 | Realidad Subjetiva | ¿Verdad absoluta o según proyección? |
| 13 | Interés Propio vs Bien Común | ¿Se puede servir a ambos? |
| 14 | Derechos Individuales vs Mal Mayor | ¿Sacrificar a uno para salvar muchos? |
| 15 | Ley del más Fuerte | ¿Justificable que gane el poderoso? |
| 16 | Igualdad Humana | ¿Valor moral vs castas de Stales? |
| 17 | Origen del Saber | ¿Instinto, memoria o visión divina? |
| 18 | Verdad Contextual | ¿Límites entre real y moral? |
| 19 | Historia de los Vencedores | ¿Crónicas de Directores o Inertes? |

### P9: Tema de ficción

| # | Tema | Categoría |
|---|---|---|
| 1 | Héroes inesperados | Héroes y Poder |
| 2 | El héroe se juzga solo | Héroes y Poder |
| 3 | Héroes con destino incierto | Héroes y Poder |
| 4 | Dioses entre nosotros | Héroes y Poder |
| 5 | Pequeño Gigante | Héroes y Poder |
| 6 | El bien contra el mal | Conflicto y Sistema |
| 7 | Revolución contra la opresión | Conflicto y Sistema |
| 8 | Corrupción política | Conflicto y Sistema |
| 9 | El lado oscuro del poder | Conflicto y Sistema |
| 10 | Divide y vencerás | Conflicto y Sistema |
| 11 | Secretos y conspiraciones | Misterio y Descubrimiento |
| 12 | En busca de respuestas | Misterio y Descubrimiento |
| 13 | Nuevos descubrimientos | Misterio y Descubrimiento |
| 14 | Artefactos milagrosos | Misterio y Descubrimiento |
| 15 | Puzzles y Enigmas | Misterio y Descubrimiento |
| 16 | Destino inexorable | Tiempo y Destino |
| 17 | Vencer el pasado | Tiempo y Destino |
| 18 | Mirar al pasado para comprender | Tiempo y Destino |
| 19 | Herencia del mundo antiguo | Tiempo y Destino |
| 20 | Redención | Transformación Humana |
| 21 | Descubrirse a sí mismo | Transformación Humana |
| 22 | Batallas internas y externas | Transformación Humana |
| 23 | Amor imposible | Transformación Humana |
| 24 | Fuerza social y liberación | Transformación Humana |
| 25 | Enigmáticas criaturas | Ecosistema y Mística |
| 26 | Cambio climático | Ecosistema y Mística |
| 27 | Alquimia y Robótica | Ecosistema y Mística |
| 28 | La magia existe | Ecosistema y Mística |

---

## FASE 4: ARQUITECTURA

### P10: Arquetipo de Historia (Snyder)

Elegir UNO de los 10 arquetipos. Consulta `mundos/vibrantes/Arquetipos/01_Arquetipos_Historias_Snyder.md` para la referencia completa con reglas, promesas, y trampas de cada uno.

| # | Arquetipo | Regla | Ejemplo Vibrantes |
|---|---|---|---|
| 1 | Monstruo en Casa | Espacio cerrado + pecado + monstruo | Mineros atrapados con Áyagar hostil |
| 2 | Vellocino de Oro | Viaje + meta + descubrimiento interno | Cruzar 9 naciones para purificar Vibrastal |
| 3 | Genio de la Lámpara | Deseo mágico que da una lección | Inerte despierta Stal 01, cuerpo no aguanta |
| 4 | Tipo con Problema | Común vs amenaza extraordinaria | Comerciante en conspiración política |
| 5 | Ritos de Pasaje | Dolor de atravesar etapa vital | Vinculación con primer Áyagar |
| 6 | Amor de Colegas | Opuestos que se necesitan | Guardián Ekkor + proscrito Saatia |
| 7 | Whodunnit | Misterio + investigador + verdad | Asesinato del Director del Pozo |
| 8 | Triunfo del Tonto | Subestimado vence al sistema | Cuidador de Áyagars salva Consejo |
| 9 | Institucional | Individuo vs sistema cerrado | Rebelión contra leyes de los 9 Stals |
| 10 | Superhéroe | Poder inmenso + soledad | Primer humano con poder Aetter |

**Prueba de fuego:** ¿Tu historia funciona igual si le cambias el arquetipo? Si sí, no has encontrado el dominante.

### P11: Los 15 Beats de Snyder

Consulta `mundos/vibrantes/Arquetipos/07_Beat_Sheet_Snyder.md` para la referencia completa.

Con el Arquetipo de Historia ya elegido (P10), asigna los 15 beats a tu historia. No todos pesan igual — el arquetipo determina cuáles son más extensos y cuáles más breves.

| # | Beat | % aprox | ¿Qué pasa en MI historia? |
|---|------|---------|--------------------------|
| 1 | Imagen de Apertura | 1% | |
| 2 | Tema Expuesto | 5% | |
| 3 | Presentación | 1–10% | |
| 4 | Catalizador | 10% | |
| 5 | Debate | 10–20% | |
| 6 | Paso al Acto 2 | 20% | |
| 7 | Historia B | 22% | |
| 8 | Diversión y Juegos | 20–55% | |
| 9 | Punto Medio | 55% | |
| 10 | Malos se Acercan | 55–75% | |
| 11 | Todo está Perdido | 75% | |
| 12 | Noche Oscura del Alma | 75–85% | |
| 13 | Paso al Acto 3 | 85% | |
| 14 | Final | 85–99% | |
| 15 | Imagen Final | 99–100% | |

Para cada beat, usa las **señales de alerta** del archivo de referencia para validar que cumple su función.

### P12: ¿Dividir en capítulos? (solo Novela Ligera/Novela)

- **No:** estructura continua
- **Sí:** ¿cuántos? ¿títulos o ideas para cada uno?

---

## FASE 5: REPARTO

### P13: Antagonista
Existente (cargar de `mundos/vibrantes/Personajes/`) o nuevo (`skill:crear_personaje.md`)

### P14: Secundarios (0-3)
Cada uno: existente o nuevo (`skill:crear_personaje.md` - rango Secundario)

### P15: Rellenos (solo listar nombre + función)

---

## FASE 6: AMBIENTACIÓN

### P16: Nación

| # | Nación | Color | Ambiente |
|---|---|---|---|
| 1 | Ekkor | Azul cian | Perfección, orden, montañas frías |
| 2 | Dottua | Verde esmeralda | Naturaleza, templos, bosques |
| 3 | Teena | Dorado | Llanos, expansión |
| 4 | Chaart | Turquesa | Mar, tecnología |
| 5 | Pannj | Aguamarina | Agua, paz |
| 6 | Chaae | Blanco plateado | Hielo, páramo |
| 7 | Saatia | Naranja/rojo | Desierto, conflicto |
| 8 | Atherr | Verde/púrpura | Ríos, mezcla cultural |
| 9 | Nafaar | Violeta/negro | Misterio, mística oscura |

### P17: Escenario
Real adaptado (`mundos/vibrantes/Arquetipos/08_Escenarios_Adaptados.md`) o fantasía (`mundos/vibrantes/Arquetipos/12_Locaciones_de_Fantasia.md`)

### P18: Época o momento histórico (texto libre)

---

## FASE 7: ENSAMBLAJE POR CAPAS

### Capa 1: Escaleta (outline detallado)
IA genera: resumen 1 párrafo + estructura por actos/capítulos + lista de escenas → **Tú apruebas o ajustas antes de seguir**

### Capa 2: Escritura por capítulos
IA escribe, tú revisas y das feedback tras cada uno

### Capa 3: Validación de canon
Cruzar contra `mundos/vibrantes/Lore/`, Simetría Sagrada, fichas de personaje. Reporte de incoherencias → correcciones.

### Capa 4: Guardado en `mundos/vibrantes/sagas/[Protagonista]/[Titulo].md`
Incluye metadatos: fecha, extensión, piezas narrativas usadas

```
---
*Metadatos*
- **Skill usado:** escribir_historia.md / crear_personaje.md
- **Fecha:** [dd/mm/aaaa]
- **Extensión:** [X] palabras
- **Logline:** [frase]
- **Tipo MICE:** [Milieu / Idea / Character / Event]
- **Trama:** [X] | **Conflicto:** [X] | **Dilema:** [X] | **Tema:** [X]
- **Arquetipo Snyder:** [X]
- **Protagonista:** [Nombre] | **Antagonista:** [Nombre]
- **Nación:** [X] | **Ubicación temporal:** [Precuela/Paralela/etc]
- **Capítulos:** [X]
```
---

## VALIDACIÓN (pre-escritura)

- [ ] Logline clara y prometedora (FASE 0)
- [ ] Tipo MICE coherente con Trama y Conflicto elegidos
- [ ] Arquetipo Snyder dominante identificado
- [ ] Cada beat de Snyder tiene una escena asignada (aunque sea tentativa)
- [ ] Eneatipo-Stal compatible
- [ ] Trama y Conflicto coherentes entre sí
- [ ] Dilema aparece en la historia (no decorativo)
- [ ] Antagonista con entidad suficiente
- [ ] Ambientación respeta el lore de la nación
- [ ] Personajes existentes mantienen su ficha

---

## APÉNDICE: GUÍA DE ESTILO

- **Tono:** Épico-místico
- **Narrador:** 3ra persona limitada
- **Diálogos:** Naturales con jerga del lore (Stal, Flud, Sold, Dvex, Ayagar)
- **Descripciones:** Sensoriales (vibración, sonido, olores)
- **Capítulos:** 1500-4000 palabras recomendado
- **Una idea por escena**
- **Mostrar, no contar:** usar vibración y entorno para emociones
- **Estructura de escena:** cada escena debe mover AL MENOS UN beat de Snyder

---

## REFERENCRUZADA

| Elemento | Archivo |
|----------|---------|
| Logline + MICE + Tema | FASE 0 de esta skill |
| Arquetipos Snyder (10) | `mundos/vibrantes/Arquetipos/01_Arquetipos_Historias_Snyder.md` |
| Beat Sheet Snyder (15 beats) | `mundos/vibrantes/Arquetipos/07_Beat_Sheet_Snyder.md` |
| Tramas | `mundos/vibrantes/Arquetipos/04_Tipos_de_Trama.md` |
| Conflictos | `mundos/vibrantes/Arquetipos/05_Tipos_de_Conflicto.md` |
| Dilemas | `mundos/vibrantes/Arquetipos/09_Dilemas_Filosoficos.md` |
| Temas | `mundos/vibrantes/Arquetipos/10_Temas_de_la_Ficcion.md` |
| Dinámicas | `mundos/vibrantes/Arquetipos/06_Dinamicas_de_Grupo.md` |
| Escenarios | `mundos/vibrantes/Arquetipos/08_Escenarios_Adaptados.md` y `12_Locaciones_de_Fantasia.md` |
| Crear personaje | `skills/crear_personaje.md` |
| Verificar canon | `skills/verificar_canon.md` |
| Lore y naciones | `mundos/vibrantes/Lore/*` |
