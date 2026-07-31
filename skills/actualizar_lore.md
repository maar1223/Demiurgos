# Skill: Actualizar Lore

Skill del Sistema de Creación Narrativa (SCN) de Vibrantes.
Propósito: Añadir, expandir o corregir el lore del mundo de Vibral sin romper el canon existente. El lore es un organismo vivo — este skill asegura que crezca con coherencia.

---

## REGLA FUNDAMENTAL

Los **Stalers** (poderes específicos de cada Stal) y la **Simetría Sagrada** (Eneatipo↔Stal) son **leyes físicas inmutables** del mundo de Vibral. No se crean nuevos Stalers, no se rompe el mapeo Eneatipo-Stal. Lo que evoluciona son las **aplicaciones creativas** de esas leyes, igual que en la realidad no creamos nueva gravedad pero sí nuevos cohetes.

| Esto NO se puede | Esto SÍ se puede |
|---|---|
| Añadir un Stal 10 | Un personaje combina Stalers existentes de forma innovadora |
| Crear un nuevo Staler para Stal 05 | Un artesano encuentra una aleación Flud-Sold con nueva propiedad |
| Cambiar propiedades del Vibrastal | Un culto desarrolla un ritual nuevo usando Vent de forma creativa |
| Romper Eneatipo↔Stal | Un personaje documenta un uso que nadie había imaginado |

---

## FASE 0: ¿QUÉ VAS A AÑADIR?

| Opción | Descripción | Tipicamente afecta a |
|---|---|---|
| **Uso creativo de Staler** | Nueva forma de usar un Staler existente | Historia del personaje, no lore base |
| **Nueva ubicación / región** | Lugar, ruina, santuario, ciudad | `mundos/vibrantes/Lore/Politica_y_Territorios/*`, `mundos/vibrantes/Lore/Planeta_Vibral.md` |
| **Nueva criatura / animal** | Fauna vibrante, especies | `mundos/vibrantes/Lore/Planeta_Vibral.md` |
| **Nueva tecnología / invento** | Artefacto, máquina, herramienta | `mundos/vibrantes/Lore/Tecnologia.md` |
| **Nueva tradición / costumbre** | Ritual, festividad, arte | `mundos/vibrantes/Lore/Cultura.md`, `mundos/vibrantes/Lore/Religion.md` |
| **Nueva facción / conflicto** | Grupo político, secta, alianza | `mundos/vibrantes/Lore/Politica_y_Territorios/*` |
| **Nuevo término de lore** | Palabra o concepto nuevo | `mundos/vibrantes/Lore/Indice_de_Terminos.md` |
| **Corrección / expansión** | Ajustar algo existente | Según corresponda |

---

## FASE 1: CLASIFICACIÓN POR TIER

Determinar en qué tier cae el cambio.

### TIER 1 — INTOCABLE (no se edita, solo se comenta)

| Archivo | Motivo |
|---|---|
| `mundos/vibrantes/Lore/El_Origen.md` | Mitología fundacional del mundo |
| `mundos/vibrantes/Lore/Vibrastal.md` | Propiedades físicas del Vibrastal (5 estados: Sold, Gelat, Flud, Vent, Aett) |
| `mundos/vibrantes/Lore/Sistema_Stal/Stal_XX_*.md` | Los 3 Stalers por Stal son FIJOS (1 negativo, 1 positivo, 1 neutral) |
| `mundos/vibrantes/lore/00_eneagrama_stal.md` | Simetría Sagrada: Eneatipo X ↔ Stal X (inviolable) |
| `mundos/vibrantes/Lore/Ayagars/*` | Naturaleza y formas de los Áyagars |

Si el cambio propuesto cae en TIER 1:
1. Señalar que esto es una **regla fundamental** del mundo
2. Preguntar: "¿Estás seguro de que quieres cambiar esto? ¿Es un retcon intencional?"
3. Si el usuario confirma: permitir con nota explícita

Si el cambio es un **uso creativo** de algo TIER 1 (ej: usar un Staler de forma nueva):
→ NO se modifica el archivo TIER 1
→ Se documenta en la historia del personaje o como "Técnica Avanzada"

### TIER 2 — ACTUALIZABLE

| Archivo | Qué se puede añadir |
|---|---|
| `mundos/vibrantes/Lore/Planeta_Vibral.md` | Fauna, geografía, biomas nuevos |
| `mundos/vibrantes/Lore/Tecnologia.md` | Inventos, artefactos (usando tecnología existente) |
| `mundos/vibrantes/Lore/Cultura.md` | Tradiciones, arte, música, leyendas |
| `mundos/vibrantes/Lore/Religion.md` | Cultos, rituales, creencias nuevas |
| `mundos/vibrantes/Lore/Politica_y_Territorios/Region_XX_*.md` | Facciones, conflictos, personajes políticos |
| `mundos/vibrantes/Lore/Indice_de_Terminos.md` | Nuevos términos con definición |

### TIER 3 — DOCUMENTABLE EN HISTORIA (sin modificar lore base)

| Qué | Dónde se documenta |
|---|---|
| Uso creativo de Staler existente | En la ficha del personaje o relato |
| Combinación innovadora de Stalers | En la ficha del personaje o relato |
| Aplicación no documentada de tecnología | En el relato o en tecnología como "nota de uso" |
| Interpretación cultural de un término | En `Cultura.md` o `Religion.md` (TIER 2) si aplica |

Ejemplo: Daest usa **Flotación Vibrante** (Staler neutral de Stal 05) no solo para levitar, sino como base estable para su **Distanciamiento Astral**. Esto no es un nuevo Staler — es un uso creativo de los existentes. Se documenta en la ficha del personaje, no en `Stal_05_Aislador.md`.

---

## FASE 2: MAPEO DE IMPACTO

Buscar en todo `mundos/vibrantes/Lore/` y `plantillas/_catalog.json` (usar el **Catalog Discovery Protocol** de AGENTS.md) si el nuevo elemento:

- [ ] **Existe ya** con otro nombre → avisar para evitar duplicados
- [ ] **Contradice** algo existente → marcar conflicto
- [ ] **Expande** algo existente sin romperlo → compatible
- [ ] **Es completamente nuevo** → sin conflictos previos

Para usos creativos de Stalers:
- [ ] El Staler usado pertenece al Stal correcto
- [ ] El uso propuesto no viola la descripción del Staler (negativo/positivo/neutral)
- [ ] El uso propuesto no requiere un poder que el Staler no tiene

---

## FASE 3: PROPUESTA DE CAMBIOS

La IA presenta:

```
## Propuesta de actualización de lore

### Elemento: [nombre]

### Clasificación: [TIER 1 / TIER 2 / TIER 3]

### Archivos afectados:
1. [archivo 1] → [cambio propuesto]
2. [archivo 2] → [cambio propuesto]

### Conflictos detectados:
- [ninguno / descripción del conflicto]

### Acción requerida:
- [ ] Aprobar todo
- [ ] Ajustar propuesta
- [ ] Rechazar
```

→ **Tú decides.** Sin tu aprobación no se ejecuta nada.

---

## FASE 4: EJECUCIÓN + CHANGELOG

### 4a: Aplicar cambios a archivos TIER 2 (si aplica)
- Se modifica el archivo de lore correspondiente
- Se añade contenido nuevo sin eliminar el existente
- Si es una corrección: se marca como "Actualizado en [fecha]"

### 4b: Registrar en `mundos/vibrantes/Lore/CHANGELOG.md`

Cada entrada sigue este formato:

```
## [YYYY-MM-DD] - [Título del cambio]

**Tipo:** Adición / Expansión / Corrección
**Origen:** Historia o personaje que lo motivó

### Cambios:
- `[archivo]`: [descripción del cambio]

### Verificación de canon:
- [ ] Simetría Sagrada respetada
- [ ] Sin contradicciones con lore existente
- [ ] Stalers existentes, no creados
```

---

## APÉNDICE A: LISTA DE ARCHIVOS POR TIER

### TIER 1 (Intocable — consultar antes de cambiar)
- `mundos/vibrantes/Lore/El_Origen.md`
- `mundos/vibrantes/Lore/Vibrastal.md`
- `mundos/vibrantes/Lore/Sistema_Stal/Stal_01_Director.md` a `Stal_09_Mediador.md`
- `mundos/vibrantes/Lore/Ayagars/00_Naturaleza_y_Vinculos.md`
- `mundos/vibrantes/Lore/Ayagars/Formas_por_Stal/*`
- `mundos/vibrantes/Lore/Ayagars/Dvins_por_Stal/*`
- `mundos/vibrantes/Lore/Ayagars/Dvex_por_Stal/*`
- `mundos/vibrantes/Lore/Ayagars/Aetters_Gigantes.md`
- `mundos/vibrantes/lore/00_eneagrama_stal.md`

### TIER 2 (Actualizable)
- `mundos/vibrantes/Lore/Planeta_Vibral.md`
- `mundos/vibrantes/Lore/Tecnologia.md`
- `mundos/vibrantes/Lore/Cultura.md`
- `mundos/vibrantes/Lore/Religion.md`
- `mundos/vibrantes/Lore/Politica_y_Territorios/*`
- `mundos/vibrantes/Lore/Indice_de_Terminos.md`
- Usar el **Catalog Discovery Protocol** de AGENTS.md para encontrar plantillas de escenarios, profesiones y miedos en `plantillas/_catalog.json`
- `skills/crear_personaje.md` (nuevas opciones en apéndices)
- `skills/verificar_canon.md` (nuevas reglas de validación)

### TIER 3 (Documentable en historia)
- Usos creativos de Stalers
- Combinaciones innovadoras de tecnologías existentes
- Interpretaciones culturales de términos del lore

---

## APÉNDICE B: GUÍA RÁPIDA

```
¿Nuevo Staler?             → ❌ No. Los Stalers son fijos.
¿Nuevo uso de Staler?      → ✅ Sí. Documentar en historia/personaje.
¿Nueva criatura?           → ✅ Sí. Añadir a Planeta_Vibral.md.
¿Nueva tecnología?         → ✅ Sí. Añadir a Tecnologia.md.
¿Nueva nación?             → ⚠️ Precaución. ¿Encaja en las 9 existentes?
¿Nuevo término?            → ✅ Sí. Añadir a Indice_de_Terminos.md.
¿Cambiar origen del mundo? → ❌ A menos que sea retcon intencional.
¿Añadir facción política?  → ✅ Sí. Añadir a archivo de nación.
```

---

## APÉNDICE C: REFERENCRUZADA

| Si añades... | Revisar también... |
|---|---|
| Fauna nueva en nación | `Planeta_Vibral.md`, archivo de nación |
| Invento tecnológico | `Tecnologia.md`, ¿usa Dvin/Dvex? |
| Ritual religioso | `Religion.md`, ¿cultura asociada? |
| Lugar nuevo | Archivo de nación, `Planeta_Vibral.md` |
| Término nuevo | `Indice_de_Terminos.md` |
| Uso creativo de Staler | Archivo Stal correspondiente (solo consulta) |
