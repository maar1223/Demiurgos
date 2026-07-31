# Skill: Crear Personaje

Skill del Sistema de Creación Narrativa (SCN) de Vibrantes.
Propósito: Guiar la creación de personajes mediante preguntas estructuradas. Tú eliges las opciones, la IA ensambla y valida.

---

## 0. DETERMINAR RANGO NARRATIVO

Primera pregunta siempre: ¿Qué rango tiene este personaje?

| Rango | Descripción | Profundidad |
|---|---|---|
| **RELLENO** | Aparece una vez, fondo decorativo, función puntual | 7 preguntas |
| **SECUNDARIO** | Soporta la trama, varias apariciones, relevancia media | 12 preguntas\* |
| **PRINCIPAL** | Motor de la historia, arco completo | 18 preguntas\* |
| **INMORTAL** | Ser divino/mítico, escala mayor, reglas especiales | 10 preguntas |

\*Incluye FASE opcional de Perfil de Villano (no cuenta en el total base).

Según la respuesta, ir a la sección correspondiente.

---

## 0.1 RANGO: RELLENO (7 preguntas)

Solo lo esencial para que sea coherente sin profundidad innecesaria.

### P1: Nombre
Texto libre.

### P2: Edad
Número.

### P3: Nación de origen
(ver tabla de naciones al final)

### P4: Descripción Física
Rasgos básicos para darle cuerpo al personaje: rostro, complexión, vestimenta, marca de Vibrante (si tiene), algún detalle distintivo.

### P5: Eneatipo (1-9)

| # | Eneatipo | Pasión | Stal | Poder |
|---|---|---|---|---|
| 1 | Perfeccionista | Ira reprimida | Stal 01 - Director | Orden, estructura, estabilización |
| 2 | Ayudador | Orgullo | Stal 02 - Conector | Conexión, soporte emocional |
| 3 | Triunfador | Vanidad | Stal 03 - Proyector | Ilusiones, camuflaje |
| 4 | Individualista | Envidia | Stal 04 - Vibrante | Resonancia emocional pura |
| 5 | Observador | Avaricia | Stal 05 - Aislador | Procesamiento información |
| 6 | Leal | Miedo | Stal 06 - Estable | Campos de fuerza, protección |
| 7 | Entusiasta | Gula | Stal 07 - Ilusor | Expansión, ilusiones lúdicas |
| 8 | Desafiante | Lujuria | Stal 08 - Impactador | Fuerza bruta, dominio |
| 9 | Pacificador | Pereza | Stal 09 - Armonizador | Mediación, calma |

### P6: Profesión (lista rápida)

Ofrecer lista completa del catálogo (ver Apéndice C).

### P7: Alineamiento (filtrado: solo Relleno)

| # | Alineamiento | Descripción |
|---|---|---|
| 1 | Social Moral | Bien común, prioriza comunidad |
| 2 | Neutral Moral | Principios morales sin facción |
| 3 | Rebelde Moral | Principios contra autoridad |
| 4 | Social Neutral | Bienestar social sin facción |
| 5 | Neutral | Completamente imparcial |
| 6 | Rebelde Neutral | Rebeldía por libertad personal |
| 7 | Social Mezquino | Comunidad para beneficio propio |
| 8 | Neutral Mezquino | Egoísmo sin inclinación |
| 9 | Rebelde Mezquino | Beneficio propio rompiendo reglas |

### Salida RELLENO

```
## [NOMBRE]

### Identidad Base
- **Rango:** Relleno
- **Edad:** [X]
- **Nación:** [X]
- **Descripción Física:** [X]
- **Eneatipo:** [X] - [Nombre]
- **Stal:** [XX] - [Nombre]
- **Profesión:** [X]
- **Alineamiento:** [X]
```

---

## 0.2 RANGO: SECUNDARIO (12 preguntas)*

### P1: Nombre
Texto libre. ¿Apodo? (opcional)

### P2: Edad
Número.

### P3: Género (opcional)

### P4: Nación
¿Nación de origen? ¿Nación actual (si es diferente)?

### P5: Descripción Física
Rasgos para visualizar al personaje: rostro y mirada, complexión y altura, vestimenta y estilo, marca de Vibrante (ubicación y color), detalles únicos (cicatrices, tics, deformidades). La IA debe guiar con preguntas si el usuario no ofrece suficiente detalle.

### P6: Eneatipo (1-9)

(igual que en RELLENO — mostrar tabla completa)

### P7: Subtipo

Cada Eneatipo tiene 3 subtipos. Mostrar según el Eneatipo elegido:

| Eneatipo | Conservación | Social | Sexual/Transmisor |
|---|---|---|---|
| 1 - Perfeccionista | Mejora entorno inmediato | Mejora social, crítico de sistemas | Perfeccionar relaciones íntimas |
| 2 - Ayudador | Ser especial para alguien | Reconocimiento social | Encanto en relaciones |
| 3 - Triunfador | Seguridad material | Prestigio social | Ser deseado por otros |
| 4 - Individualista | Autocomparación, inadecuación | Validación grupal | Autoafirmación en relaciones |
| 5 - Observador | Aislamiento, privacidad | Grupos intelectuales | Selectividad extrema |
| 6 - Leal | Bienestar personal | Pertenencia a grupos | Cercanía en relaciones |
| 7 - Entusiasta | Comodidad personal | Causas sociales | Seducción |
| 8 - Desafiante | Territorialidad | Justicia propia | Dominio en relaciones |
| 9 - Pacificador | Indulgencia | Sacrificio grupal | Fusión con otro |

### P8: Profesión

(ver catálogo completo en Apéndice C)

### P9: Arquetipo 7x7

49 arquetipos basados en cruce de ejes: ¿Qué busca? × ¿Cómo lo consigue?

**Ejes verticales (qué busca):** Innovación, Pasión, Poder, Prestigio, Confianza, Mística, Alerta
**Ejes horizontales (cómo lo consigue):** Innovación, Pasión, Poder, Prestigio, Confianza, Mística, Alerta

Mostrar los 49 arquetipos (ver Apéndice B).

### P10: Alineamiento (filtrado: Principal + Secundario)

(ver Apéndice A - sección Principal/Secundario)

### P11: Miedo Arquetípico

(ver Apéndice G)

### FASE 7: PERFIL DE VILLANO (P12, opcional)

Solo si el personaje cumple función de villano (antagonista moralmente activo, no un simple rival o fuerza opuesta). Idéntico al del rango Principal (ver sección correspondiente).

### Salida SECUNDARIO

```
## [NOMBRE]

### Identidad Base
- **Rango:** Secundario
- **Edad:** [X]
- **Género:** [X]
- **Nación de origen:** [X]
- **Nación actual:** [X]
- **Descripción Física:** [X]
- **Eneatipo:** [X] - [Nombre]
- **Stal:** [XX] - [Nombre]
- **Subtipo:** [X]
- **Profesión:** [X]
- **Arquetipo:** [X] (Busca: X, Lo consigue: Y)

### Psicología y Carácter
- **Alineamiento:** [X]
- **Miedo:** [X]
- **Teme:** [descripción del miedo]
- **Fortalezas:** [derivadas de Eneatipo + Arquetipo]
- **Debilidades:** [derivadas de Eneatipo + Arquetipo]

### Perfil de Villano (opcional — solo si aplica)
- **¿Cree que es una buena persona?:** [justificación]
- **¿Qué lo hace un oponente digno?:** [cualidades]
- **Presencia en escena:** [cómo genera tensión]
- **Inteligencia y habilidad:** [por qué lo siguen]
- **Decisión difícil:** [sacrificio]
- **Faceta humana:** [bondad o vulnerabilidad]
- **Persuasión:** [cómo convence]
- **Rasgos personales:** [orgullo, engaño, venganza]
```

---

## 0.3 RANGO: PRINCIPAL (18 preguntas*, 5 fases + FASE 7 opcional)

### FASE 1: IDENTIDAD BASE (P1-P5)

#### P1: Nombre
Texto libre. ¿Apodo? (opcional)

#### P2: Edad
Número.

#### P3: Género (opcional)

#### P4: Nación
¿Nación de origen? ¿Nación actual (si es diferente)?

#### P5: Descripción Física
Rasgos detallados para visualizar al personaje: rostro y expresión, complexión y presencia, vestimenta y estilo personal, marca de Vibrante (ubicación exacta, color, forma), detalles únicos (cicatrices, tics, deformidades, marcas de guerra). La IA debe guiar con preguntas específicas si el usuario no ofrece suficiente detalle, explorando cómo la apariencia refleja su psicología.

### FASE 2: NÚCLEO (P6-P7)

#### P6: Eneatipo (1-9)
(mostrar tabla completa)

#### P7: Subtipo
(mostrar tabla completa)

### FASE 3: IDENTIDAD SOCIAL (P8-P9)

#### P8: Profesión
(ver Apéndice C)

#### P9: Arquetipo 7x7
(ver Apéndice B — mostrar los 49)

### FASE 4: BRÚJULA MORAL (P10-P12)

#### P10: Rango narrativo (ya es Principal, confirmar)
#### P11: Alineamiento (completo: 25 opciones Principal/Secundario)
(ver Apéndice A)
#### P12: Miedo Arquetípico (12 opciones)
(ver Apéndice G)

### FASE 5: ROL EN LA HISTORIA (P13-P16)

#### P13: Tipo de Trama con la que resuena

| # | Trama | Dinámica | Giro Vibrante |
|---|---|---|---|
| 1 | Misión de Escolta | Proteger objeto/persona A→B | Gema de Sold inestable atrae Áyagars |
| 2 | Infiltración/Robo | Entrar, tomar, salir | Stal 07 para burlar seguridad |
| 3 | Defensa de Asedio | Defender posición fija | Tramas de mística en santuario |
| 4 | Revelación Detectivesca | Conectar pistas, descubrir | Dvex analiza ondas de resonancia |
| 5 | Supervivencia en el Vacío | Entorno hostil, recursos escasos | Tormenta mística sin recarga |
| 6 | Duelo Jerárquico | Demostrar superioridad | Combate ritual Stal vs Stal |

#### P14: Conflicto principal

| # | Conflicto | Esencia |
|---|---|---|
| 1 | Individuo vs Individuo | Dos personas, mismos objetivos |
| 2 | Individuo vs Sociedad | Principios vs sistema |
| 3 | Individuo vs Naturaleza | Entorno letal |
| 4 | Individuo vs Sí Mismo | Lucha interna |
| 5 | Individuo vs Destino | Cambiar lo predeterminado |
| 6 | Individuo vs Religión/Ideología | Creencias cerradas |
| 7 | Individuo vs Prejuicios | Discriminación |
| 8 | Individuo vs Tecnología | Herramientas que dividen |
| 9 | Bien vs Mal | Dualidad clásica |
| 10 | Rechazo por la Diferencia | Aceptación propia y ajena |
| 11 | Viaje de Autodescubrimiento | Búsqueda de identidad |
| 12 | Salvar algo Preciado | Proteger lo que importa |
| 13 | Vencer el Pasado | Redención |

#### P15: Dilema Filosófico

| # | Dilema | Pregunta |
|---|---|---|
| 1 | Libre albedrío vs Predeterminación | ¿Somos dueños de nuestra energía? |
| 2 | Destino Consciente | ¿Puedes ser libre sabiendo tu destino? |
| 3 | La Fuerza Superior | ¿Existencia predecible o anomalía? |
| 4 | Bien vs Mal Absoluto | ¿Pureza total o escala de grises? |
| 5 | El Fin justifica los Medios | ¿Acción mala por causa noble? |
| 6 | El Sacrificio del Mal | ¿Bien exige sacrificio? |
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
| 19 | La Historia de los Vencedores | ¿Crónicas de Directores o de Inertes? |

#### P16: Tema de Ficción

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

### FASE 6: RELACIONES (P17)

#### P17: Dinámica de Grupo

| # | Dinámica | Foco | Tensión |
|---|---|---|---|
| 1 | Mentor y su Legado | Stal 01 enseña a Inerte | Alumno supera, maestro teme |
| 2 | Alianza Inestable | Enemigos obligados a colaborar | ¿Quién traiciona primero? |
| 3 | Triángulo de Rivalidad | 3 compiten por mismo objetivo | Alianzas 2v1 cambiantes |
| 4 | Vínculo de Sangre y Stal | Familia Stal con hijo Inerte | Lealtad vs jerarquía |
| 5 | Escuadrón de Descartados | Grupo que no encaja | Pertenencia vs redención |
| 6 | Máquina y su Conductor | Mecánico Dvin y su Dvex | Herramienta vs ser vivo |

### FASE 7: PERFIL DE VILLANO (P18, opcional)

Solo si el personaje cumple función de **villano** — un antagonista moralmente activo que cree estar justificado y tiene un código propio. No aplica a antagonistas simples (rivales, sistemas, desastres naturales).

La IA pregunta al llegar aquí:

> *"Este personaje parece tener perfil de villano. ¿Quieres aplicar las preguntas del Apéndice I para desarrollarlo como tal?"*

Si la respuesta es sí, la IA despliega las 8 preguntas una por una (ver Apéndice I). Cada respuesta se registra en la ficha bajo una nueva sección "Perfil de Villano".

#### P18: ¿Aplica perfil de villano?
Sí / No (si No, saltar directamente a la salida de ficha)

### Salida PRINCIPAL (formato completo)

```
## [NOMBRE]

### Identidad Base
- **Rango:** Principal
- **Edad:** [X]
- **Género:** [X]
- **Nación de origen:** [X]
- **Nación actual:** [X]
- **Descripción Física:** [X]
- **Eneatipo:** [X] - [Nombre] (Subtipo: [X])
- **Stal:** [XX] - [Nombre]
- **Profesión:** [X]
- **Arquetipo:** [X] (Busca: X, Lo consigue: Y)

### Psicología y Carácter
- **Alineamiento:** [X]
- **Miedo:** [X]
- **Teme:** [descripción]
- **Fortalezas:** [según Eneatipo + Arquetipo]
- **Debilidades:** [según Eneatipo + Arquetipo]

### Rol Narrativo
- **Trama que resuena:** [X]
- **Conflicto principal:** [X]
- **Dilema filosófico:** [X]
- **Tema de ficción:** [X]
- **Dinámica de grupo:** [X] (si aplica)

### Arco Potencial
(Sugerencia de evolución basada en Eneatipo + Alineamiento + Miedo)

### Perfil de Villano (opcional — solo si aplica)
- **¿Cree que es una buena persona?:** [justificación de sus actos]
- **¿Qué lo hace un oponente digno?:** [cualidades que retan al héroe]
- **Presencia en escena:** [cómo genera tensión]
- **Inteligencia y habilidad:** [por qué lo siguen]
- **Decisión difícil:** [sacrificio para mantener poder]
- **Faceta humana:** [momento de bondad o vulnerabilidad]
- **Persuasión:** [cómo convence a otros]
- **Rasgos personales:** [orgullo, engaño, venganza]
```

---

## 0.4 RANGO: INMORTAL (13 preguntas)

Similar a PRINCIPAL pero con variaciones:

### P0: Nombre + Edad (inmemorial) + Género + Nación de dominio
### P1-P2: Eneatipo + Subtipo (igual)
### P3: Sin profesión terrenal (preguntar: ¿Qué es? ¿Un dios, un espíritu, un Áyagar titánico?)
### P4: Arquetipo 7x7 (filtrado por escala divina)
### P5: Confirmar rango Inmortal
### P6: Alineamiento (filtrado: solo Inmortales - 24 opciones)
### P7: Miedo (filtrado: existenciales + místicos)
### P8-P11: Trama, Conflicto, Dilema, Tema (los mismos, a escala cósmica)

### Salida INMORTAL

```
## [NOMBRE]

### Identidad Base
- **Rango:** Inmortal
- **Naturaleza:** [Dios/Espíritu/Áyagar/Entidad]
- **Eneatipo:** [X] - [Nombre]
- **Stal:** [XX] - [Nombre]
- **Arquetipo:** [X]
- **Nación de dominio:** [X]

### Psicología Cósmica
- **Alineamiento:** [X]
- **Miedo:** [X]
- **Motivación divina:** [X]
- **Limitaciones:** [X]
```

---

## VALIDACIÓN (post-ensamblaje)

La IA debe verificar antes de entregar el resultado:

- [ ] Simetría Sagrada: Eneatipo [X] → Stal [XX] correcto
- [ ] Compatibilidad Arquetipo ↔ Eneatipo (sin contradicciones obvias)
- [ ] Alineamiento dentro del rango correcto (Relleno/Secundario/Principal/Inmortal)
- [ ] Coherencia Miedo ↔ Alineamiento (no contradictorios)
- [ ] Si hay contradicción: preguntar al usuario si prefiere ajustar o mantener (puede ser una anomalía intencional)

---

## APÉNDICE A: ALINEAMIENTOS COMPLETOS

### Relleno (9)
Social Moral, Neutral Moral, Rebelde Moral, Social Neutral, Neutral, Rebelde Neutral, Social Mezquino, Neutral Mezquino, Rebelde Mezquino

### Principal / Secundario (25)
Legal Benigno, Social Benigno, Neutral Benigno, Rebelde Benigno, Caótico Benigno, Legal Moral, Social Moral, Neutral Moral, Rebelde Moral, Caótico Moral, Legal Neutral, Social Neutral, Neutral, Rebelde Neutral, Caótico Neutral, Legal Mezquino, Social Mezquino, Neutral Mezquino, Rebelde Mezquino, Caótico Mezquino, Legal Maligno, Social Maligno, Neutral Maligno, Rebelde Maligno, Caótico Maligno

### Inmortales (24)
Axiomático Virtuoso, Legal Virtuoso, Social Virtuoso, Neutral Virtuoso, Rebelde Virtuoso, Caótico Virtuoso, Anárquico Virtuoso, Axiomático Benigno, Axiomático Moral, Axiomático Neutral, Axiomático Mezquino, Axiomático Maligno, Axiomático Vil, Legal Vil, Social Vil, Neutral Vil, Rebelde Vil, Caótico Vil, Anárquico Vil, Anárquico Benigno, Anárquico Moral, Anárquico Neutral, Anárquico Mezquino, Anárquico Maligno

---

## APÉNDICE B: ARQUETIPOS 7x7 (49)

Ejes: ¿Qué busca? (vertical) × ¿Cómo lo consigue? (horizontal)

| | INNOVACIÓN | PASIÓN | PODER | PRESTIGIO | CONFIANZA | MÍSTICA | ALERTA |
|---|---|---|---|---|---|---|---|
| **INNOVACIÓN** | Anarquista | Estrella Rock | Inconforme | Pionero | Artesano | Provocador | Chispa |
| **PASIÓN** | Catalizador | Dramático | Loco | Talentoso | Amado | Intriga | Orquestador |
| **PODER** | Agente Cambio | Capitán | Agresor | Maestro | Guardián | Mente Maestra | Defensor |
| **PRESTIGIO** | Vanguardista | Conocedor | Vencedor | Imperial | Inversión Segura | Arquitecto | Erudito |
| **CONFIANZA** | Evolucionario | Auténtico | Serio | Diplomático | Viejo Soldado | Ancla | Buen Ciudadano |
| **MÍSTICA** | Arma Secreta | Sutil | Fuerza Oculta | Soldado Real | Sabio | Candado | Arquero |
| **ALERTA** | Compositor | Coordinador | Experto | Director | Mediador | Detective | Controlador |

---

## APÉNDICE C: PROFESIONES Y ROLES

### Magia y Mística
Mago/Hechicero, Arqueólogo de Runas, Vidente Dimensional, Intérprete, Chamán Místico, Herborista Mítico, Vigilante del Espectro, Detector de Magia, Psicomago, Maestro de Almas

### Guerreros y Protectores
Paladín, Caballero Buscacorazones, Cazador de Demonios, Asesino de Reyes, Asesino de Dragones, Mercenario, Maestro de Armas Elemental, Guardián de Portales, Protector Solar, Shinobi Archer, Espadachín Místico

### Tecnología y Creación
Tecnoalquimista, Alquimista de Almas, Constructor Mecánico, Inventor de Bots, Carpintero de Realidades, Constructor Astral, Robotólogo Biomédico

### Exploración y Ciencia
Navegante Astral, Explorador Galáctico, Recogedor de Datos, Comandante Astrónomo, Nómada Dimensional, Viajero del Tiempo, Ecologista del Augurio

### Roles Sociales
Rey/Reina, Emperatriz Estelar, Bardo, Músico de Resonancia, Plañidero, Buscador de Tesoros, Cazador de Secretos, Monje, Sacerdotisa Interdimensional

---

## APÉNDICE D: NACIONES (9)

| # | Nación | Color | Ambiente |
|---|---|---|---|
| 1 | Ekkor | Azul cian | Perfección, orden, montañas frías |
| 2 | Dottua | Verde esmeralda | Naturaleza, templos de meditación |
| 3 | Teena | Dorado | Llanos, expansión, libertad |
| 4 | Chaart | Turquesa | Mar, tecnología, innovación |
| 5 | Pannj | Aguamarina | Agua, paz, espiritualidad |
| 6 | Chaae | Blanco plateado | Hielo, páramo, resistencia |
| 7 | Saatia | Naranja/rojo | Desierto, aridez, conflicto |
| 8 | Atherr | Verde/púrpura | Ríos, mezcla cultural |
| 9 | Nafaar | Violeta/negro | Misterio, mística oscura |

---

## APÉNDICE E: TRAMAS (6)

1. Misión de Escolta | 2. Infiltración/Robo | 3. Defensa de Asedio | 4. Revelación Detectivesca | 5. Supervivencia en el Vacío | 6. Duelo Jerárquico

## APÉNDICE G: MIEDOS ARQUETÍPICOS (12)

### Existenciales
1. Extinción (Muerte): pánico a que la propia vibración se apague
2. Soledad (Abandono): ser el único Inerte o exiliado
3. Pérdida de Identidad: Vibrastal consuma la mente
4. Destino: condenado por profecía de Sold

### Sociales
5. Juicio (Vergüenza): que descubran un pecado
6. Traición: desconfianza paranoica
7. Insignificancia: ser solo un Inerte
8. Rechazo: no encajar en la jerarquía Stal

### Tecnológicos/Místicos
9. Desconexión: perder vínculo con Áyagar
10. Control (Esclavitud): ser manipulado
11. Corrupción: Flud amargo destruye desde dentro
12. Abismo: lo que acecha en la Gran Cueva

---

## APÉNDICE H: REFERENCRUZADA CON LORE

| Elemento | Archivo fuente |
|---|---|
| Eneatipo detallado | `mundos/vibrantes/lore/eneagrama_stal/e[x].md` |
| Simetría Sagrada | `mundos/vibrantes/lore/00_eneagrama_stal.md` |
| Lore mundo | `mundos/vibrantes/Lore/*` |
| Naciones | `mundos/vibrantes/Lore/Politica_y_Territorios/*` |

**Para plantillas narrativas** (arquetipos, alineamientos, profesiones, miedos, tramas, conflictos, dilemas, temas, dinámicas, ficha de personaje, creación de villanos): usar el **Catalog Discovery Protocol** de AGENTS.md para encontrar la plantilla adecuada en `plantillas/_catalog.json`.

---

## APÉNDICE I: CREACIÓN DE VILLANOS (PREGUNTAS OPCIONALES)

Usar esta guía después de completar la ficha base si el personaje cumple función de villano (antagonista con maldad activa, código propio y justificación moral). No aplicar a antagonistas simples como rivales, sistemas o fuerzas naturales. Para el desarrollo completo de cada punto, usar el **Catalog Discovery Protocol** de AGENTS.md para encontrar la plantilla de creación de villanos en `plantillas/_catalog.json`.

- **¿Cree que es una buena persona?** — ¿Cómo justifica sus acciones como necesarias o correctas?
- **¿Qué lo hace un oponente digno?** — ¿Qué cualidades obligan al héroe a esforzarse al máximo?
- **¿Cómo es su presencia en escena?** — ¿Qué genera tensión cuando aparece?
- **¿Qué habilidades lo hacen inteligente y hábil?** — ¿Por qué lo siguen, más allá del miedo?
- **¿Qué decisión difícil ha tomado para mantener su poder?** — ¿ sacrificó algo o a alguien?
- **¿Cuál es su faceta humana?** — ¿Qué momento de bondad o vulnerabilidad lo complejiza?
- **¿Cómo persuade a otros de seguirlo?** — ¿Con qué argumentos convence?
- **¿En qué se manifiestan su orgullo, engaño y venganza?** — ¿Cómo filtran sus decisiones cotidianas?
