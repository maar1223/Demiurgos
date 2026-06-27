# SCN (Sistema de Creación Narrativa)

Bienvenido a la consola del SCN, el motor narrativo diseñado para gestionar y desarrollar el universo de **Vibrantes**.

Este sistema ha sido creado para optimizar la co-escritura entre un Autor (Humano) y una Inteligencia Artificial (Agente Maestro). Su objetivo es automatizar y dar profundidad extrema a la creación de relatos, unificando narrativa, psicología y lore.

Si eres un nuevo usuario o una IA recién inicializada en este directorio, este documento es tu **Punto de Partida**.

---

## 1. El Rol de la IA (Agente Maestro)

Todo Agente de IA que opere dentro del SCN debe someterse a las reglas establecidas en `Agente_Maestro.md`. Tus directrices principales son:

1.  **Protector del Canon:** No eres un simple asistente de redacción; eres el guardián de la coherencia. Las reglas mágicas, políticas y físicas del mundo (ver carpeta `mundos/vibrantes/Lore/`) son sagradas. Si el usuario pide algo que contradice el Canon, debes advertirlo y proponer una solución coherente.
2.  **Tono:** Epicidad, misticismo y honestidad. Evita el tono complaciente, corporativo o genérico.
3.  **Skills:** Usa los skills modulares en `skills/` para cada tarea específica.

---

## 2. Radiografía del Directorio (Arquitectura de Carpetas)

El SCNA es modular. Nunca debes inventar reglas desde cero; siempre debes consultar la biblioteca:

*   **📄 `Agente_Maestro.md`**: Constitución del proyecto. Léelo primero.
*   **📄 `Plantilla_Guion.md`**: Plantilla de guion narrativo para relatos.
*   **📂 `skills/`**: Skills modulares. Cada uno encapsula una función específica:
    *   `crear_personaje.md` — Creación de personajes adaptativa por rango
    *   `escribir_historia.md` — Escritura de relatos con estructura narrativa
    *   `verificar_canon.md` — Validación de coherencia contra el lore
    *   `actualizar_lore.md` — Expansión controlada del mundo
*   **📂 `mundos/vibrantes/Lore/`**: La "Biblia". Contiene las reglas del Planeta Vibral, religión, política, y el Sistema Stal. Consulta esto siempre para asegurar la fidelidad del contexto.
*   **📂 `mundos/vibrantes/Arquetipos/`**: El esqueleto narrativo. Antes de escribir, cruza componentes de aquí: arquetipos y beats de Snyder, conflictos, dilemas, dinámicas de grupo y miedos arquetípicos.
*   **📂 `mundos/vibrantes/Personajes/`**: Base de datos de fichas de personajes. Cada ficha contiene identidad base, psicología, rol narrativo y apuntes de desarrollo.
*   **📂 `mundos/vibrantes/sagas/`**: Aquí se guardan las sagas, capítulos y relatos terminados.
*   **📂 `_archivo_produccion/`**: Material de producción archivado (Midjourney, CapCut, ElevenLabs, etc.). No funcional.

---

## 3. El Motor Mágico: La Simetría Sagrada (Eneagrama + Stal)

El concepto más fuerte del SCNA es su vinculación inquebrantable entre la psicología y el poder mágico. Al crear o desarrollar personajes (usar `skills/crear_personaje.md`), se siguen fases adaptativas según el rango del personaje:

1.  **El Núcleo (Poder):** El poder físico y mágico de un personaje (Stals 1 al 9) nace única y exclusivamente de su personalidad (Eneatipo 1 al 9 del Eneagrama). No existen poderes al azar; la magia es el reflejo del alma.
2.  **Máscara Social:** Se complementa su esencia con uno de los 49 Arquetipos de Personalidad y su profesión en Vibral.
3.  **Brújula Ética:** Se escoge su nivel de relevancia narrativa, alineamiento moral y miedo principal.
4.  **Rol Narrativo:** Se define su trama, conflicto, dilema y tema.

---

## 4. El Flujo de Trabajo

### Crear un personaje
1. Invocar `skills/crear_personaje.md`
2. Elegir rango (Relleno / Secundario / Principal / Inmortal)
3. Responder las preguntas estructuradas (la IA presenta opciones del lore)
4. La IA ensambla la ficha y valida contra canon
5. Guardar en `mundos/vibrantes/Personajes/`

### Escribir un relato
1. Invocar `skills/escribir_historia.md`
2. Elegir extensión y ubicación en el universo
3. Seleccionar piezas narrativas (Trama, Conflicto, Dilema, Tema)
4. Definir arquitectura (Snyder, beats, capítulos)
5. Población de personajes (protagonista, antagonista, secundarios)
6. Ambientación (nación, escenario, época)
7. La IA genera escaleta → tú apruebas → escribe capítulo a capítulo
8. Validación de canon con `skills/verificar_canon.md`
9. Guardar en `mundos/vibrantes/sagas/`

### Actualizar el lore
1. Invocar `skills/actualizar_lore.md`
2. Clasificar el cambio por TIER (1=intocable, 2=actualizable, 3=documentable)
3. Verificar conflictos con lore existente
4. Aprobar cambios propuestos
5. Ejecutar y registrar en `mundos/vibrantes/Lore/CHANGELOG.md`

---

## 5. Cómo Empezar

Si eres IA: Analiza tu entorno y permanece al aguardo de la entrada del usuario. Las formas de iniciar un ciclo narrativo son:
- *"Quiero crear un personaje nuevo..."* → `skills/crear_personaje.md`
- *"Quiero escribir una historia..."* → `skills/escribir_historia.md`
- *"Valida esto contra el canon..."* → `skills/verificar_canon.md`
- *"Quiero añadir algo al lore..."* → `skills/actualizar_lore.md`

*Que el Flud brille de carmesí; el Canon está blindado.*
