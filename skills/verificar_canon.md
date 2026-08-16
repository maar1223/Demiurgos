# Skill: Verificar Canon

Skill del Sistema de Creación Narrativa (SCN) de Vibrantes.
Propósito: Validar cualquier contenido (personaje, relato, escenario, elemento suelto) contra el lore establecido. Cada verificación consulta los archivos fuente — no asume nada.

---

## ENTRADA

### P1: ¿Qué verificamos?

| Opción | Descripción |
|---|---|
| **Personaje** | Cargar ficha desde `mundos/vibrantes/Personajes/` |
| **Relato** | Cargar desde `mundos/vibrantes/sagas/` |
| **Escenario** | Descripción de ubicación o escena |
| **Elemento suelto** | Texto libre: frase, concepto, evento |

---

## FASE 1: SIMETRÍA SAGRADA

> Consultar: `mundos/vibrantes/lore/00_eneagrama_stal.md`, `mundos/vibrantes/lore/eneagrama_stal/e*.md`

### 1a: Eneatipo ↔ Stal

| Eneatipo | Stal | ¿Coincide? |
|---|---|---|
| 1. Perfeccionista | 01 - Directores | Consultar `00_eneagrama_stal.md` |
| 2. Ayudador | 02 - Conectores | |
| 3. Triunfador | 03 - Proyectores | |
| 4. Individualista | 04 - Vibrantes | |
| 5. Observador | 05 - Aisladores | |
| 6. Leal | 06 - Estables | |
| 7. Entusiasta | 07 - Ilusores | |
| 8. Desafiante | 08 - Impactores | |
| 9. Pacificador | 09 - Armonizadores | |

- [ ] El Stal del personaje coincide exactamente con su Eneatipo
- [ ] Si NO coincide: ¿es intencional? (preguntar al autor, no asumir error)

### 1b: Subtipo

| Eneatipo | Conservación | Social | Sexual/Transmisor |
|---|---|---|---|
| Consultar `mundos/vibrantes/lore/eneagrama_stal/e[x].md` sección "Subtipos" |

- [ ] El subtipo elegido existe para ese Eneatipo
- [ ] La descripción del subtipo es coherente con la personalidad del personaje

### 1c: Arquetipo 7x7

> Consultar: usar el **Catalog Discovery Protocol** de AGENTS.md para encontrar la plantilla de arquetipos de personalidad en `plantillas/_catalog.json`

- [ ] El arquetipo existe en la matriz (49 opciones)
- [ ] El arquetipo no contradice la naturaleza del Eneatipo
  - Ej: "El Controlador" (Alerta×Alerta) sería tenso con Eneatipo 7 (espíritu libre)
  - Ej: "El Sabio" (Mística×Confianza) encaja naturalmente con Eneatipo 5

---

## FASE 2: COHERENCIA DE PERSONAJE

> Consultar: `mundos/vibrantes/Personajes/*` y `plantillas/_catalog.json` (usar el **Catalog Discovery Protocol** de AGENTS.md para alineamientos, profesiones y miedos)

### 2a: Rango y Alineamiento

| Rango | Alineamientos permitidos | Consultar |
|---|---|---|
| Relleno | 9 opciones | `plantillas/_catalog.json` — buscar "alineamiento" |
| Secundario | 25 opciones | `plantillas/_catalog.json` — buscar "alineamiento" |
| Principal | 25 opciones | `plantillas/_catalog.json` — buscar "alineamiento" |
| Inmortal | 24 opciones | - "Inmortales" |

- [ ] El alineamiento pertenece al rango correcto
- [ ] El alineamiento no contradice el miedo (sin asumir — marcar solo si hay evidencia clara)

### 2b: Profesión

> Consultar: `plantillas/_catalog.json` — buscar "profesión" (usar el **Catalog Discovery Protocol**)

- [ ] La profesión existe en el catálogo
- [ ] La profesión es compatible con el Eneatipo (sentido común, no regla estricta)

### 2c: Miedo

> Consultar: `plantillas/_catalog.json` — buscar "miedo" (usar el **Catalog Discovery Protocol**)

- [ ] El miedo está en el catálogo (12 opciones)
- [ ] El miedo pertenece a la categoría correcta (Existencial/Social/Tecnológico-Místico)

### 2d: Nombre único

- [ ] No existe otro personaje con el mismo nombre en `mundos/vibrantes/Personajes/`
- [ ] Si existe: ¿es el mismo personaje o hay conflicto?

---

## FASE 3: COHERENCIA DEL MUNDO (LORE)

> Consultar: `mundos/vibrantes/Lore/Indice_de_Terminos.md`, `mundos/vibrantes/Lore/El_Origen.md`, `mundos/vibrantes/Lore/Planeta_Vibral.md`, `mundos/vibrantes/Lore/Tecnologia.md`, `mundos/vibrantes/Lore/Politica_y_Territorios/*`, `mundos/vibrantes/Lore/Sistema_Stal/*`, `mundos/vibrantes/Lore/Ayagars/*`

### 3a: Términos del lore

- [ ] Stal se usa como "especialización vibratoria" o "el Áyagar primigenio" — no genéricamente
- [ ] Staler se usa como "poder vibrante específico" — no como sinónimo de Stal
- [ ] Flud es líquido (azul claro, almacena vibración) — no se confunde con Sold o Vent
- [ ] Sold es sólido (azul oscuro, transmite vibración)
- [ ] Vent es gas (casi transparente, potencia vibración)
- [ ] Gelat es gelatinoso (regula y aísla)
- [ ] Inerte: 4/5 de la población SIN vínculo — no se usa como insulto genérico
- [ ] Áyagar: reptiles vibrantes maleables que nacen del Flud — no "espíritus" o "demonios"
- [ ] Dvin: simbiogénesis interna (patrón en el cuello) — consultar `mundos/vibrantes/Lore/Ayagars/Dvins_por_Stal/*`
- [ ] Dvex: dispositivo externo — consultar `mundos/vibrantes/Lore/Ayagars/Dvex_por_Stal/*`

### 3b: Stal — capacidades específicas

> Consultar el archivo correspondiente en `mundos/vibrantes/Lore/Sistema_Stal/Stal_XX_Nombre.md` para validar Stalers

| Stal | Stalers (poderes) | Consultar |
|---|---|---|
| 01 Director | Represión Vibrante (-), Vibración Perfecta (+), Escáner Vibrante (N) | `Stal_01_Director.md` |
| 02 Conector | | `Stal_02_Conector.md` |
| 03 Proyector | | `Stal_03_Proyector.md` |
| 04 Vibrante | | `Stal_04_Vibrante.md` |
| 05 Aislador | Manto de Inexistencia (-), Distanciamiento Astral (+), Flotación Vibrante (N) | `Stal_05_Aislador.md` |
| 06 Estable | | `Stal_06_Estable.md` |
| 07 Ilusor | | `Stal_07_Ilusor.md` |
| 08 Impactador | | `Stal_08_Impactador.md` |
| 09 Armonizador | | `Stal_09_Armonizador.md` |

- [ ] El personaje usa Stalers que existen para su Stal
- [ ] Stalers negativos (-) se usan como efecto negativo, no como poder principal
- [ ] Stalers neutrales (N) y positivos (+) se usan según su función

### 3c: Nación

> Consultar: `mundos/vibrantes/Lore/Politica_y_Territorios/Region_XX_Nombre.md`, `00_Estilo_Naciones.md`

| Nación | Color | Estilo |
|---|---|---|
| Ekkor | Azul cian | Perfección, orden, montañas frías |
| Dottua | Verde esmeralda | Naturaleza, templos |
| Teena | Dorado | Llanos, expansión |
| Chaart | Turquesa | Mar, tecnología |
| Pannj | Aguamarina | Agua, paz |
| Chaae | Blanco plateado | Hielo, páramo |
| Saatia | Naranja/rojo | Desierto, conflicto |
| Atherr | Verde/púrpura | Ríos, mezcla |
| Nafaar | Violeta/negro | Misterio, mística |

- [ ] El color usado corresponde a la nación
- [ ] La atmósfera descrita respeta el estilo de la nación
- [ ] Personajes de la nación actúan según su cultura (consultar archivo de nación)

### 3d: Tecnología y cronología

> Consultar: `mundos/vibrantes/Lore/Tecnologia.md`

- [ ] La tecnología mencionada existe en la línea temporal de Vibral
- [ ] VIT: cápsulas de Gelat con Flud+Vent (dopaje, adicción, efecto secundario)
- [ ] Armadura Vibrante: para Inertes o quienes perdieron el vínculo (controversia religiosa)
- [ ] Módulos de Absorción: almohadillas (caseras) o pilares de Sold (industriales)
- [ ] Reloj de Terremotos: esfera de Sold+Flud, predice sismos
- [ ] HVA: herramientas sin vínculo, 1 Staler, necesitan fuente externa

---

## FASE 4: COHERENCIA NARRATIVA (solo si aplica a relato)

> Consultar: `mundos/vibrantes/Personajes/*` y `plantillas/_catalog.json` (usar el **Catalog Discovery Protocol** de AGENTS.md para tramas, conflictos, dilemas y temas)

- [ ] La Trama elegida existe en el catálogo (6 opciones)
- [ ] El Conflicto principal está en el catálogo (13 opciones)
- [ ] La Trama y el Conflicto no son contradictorios
- [ ] El Dilema filosófico está en el catálogo y aparece en la historia
- [ ] El Tema de ficción está en el catálogo (28 opciones)
- [ ] El Arquetipo Snyder coincide con la estructura del relato
- [ ] Los beats de Snyder están mapeados y cumplen su función narrativa
- [ ] El personaje principal actúa dentro de su alineamiento (o hay razón narrativa para el cambio)
- [ ] El antagonista tiene entidad para el conflicto planteado

---

## SALIDA: REPORTE DE CANON

```
# Reporte de Canon: [Nombre del elemento verificado]

## Resumen
✅ [N] verificaciones aprobadas
⚠️ [N] advertencias
❌ [N] violaciones

---

## ✅ Aprobado
Elementos que cumplen con el lore establecido.
- [Elemento 1] → archivo de referencia
- [Elemento 2] → archivo de referencia

---

## ⚠️ Advertencias
Inconsistencias menores que NO rompen el canon pero pueden pulirse.
- [Elemento]: [Descripción del problema leve]
  → Referencia: [Archivo source, línea]
  → Sugerencia: [Ajuste opcional]

---

## ❌ Violaciones
Problemas que contradicen directamente el lore establecido.
- [Elemento]: [Descripción del problema]
  → Referencia: [Archivo source, línea]
  → Corrección propuesta: [Solución concreta]
  → ¿Confirmas la corrección o es intencional?

---

## 📋 Archivos consultados
- [Archivo 1]
- [Archivo 2]
- ...
```

---

## REGLA DE ORO

Ante una posible violación de canon:
1. Marcar la incoherencia con su referencia exacta
2. Preguntar al autor: "¿Es intencional o hay que corregir?"
3. **Nunca corregir sin consultar** — el autor puede tener una razón narrativa
4. Si es intencional: registrarlo como excepción documentada
