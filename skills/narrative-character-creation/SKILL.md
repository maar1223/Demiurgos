---
name: narrative-character-creation
description: "Trigger: new character, crear personaje, inventar personaje, personaje nuevo. Guide diskless new-character co-creation with 40/60 rails and explicit approval."
license: Apache-2.0
metadata:
  author: Demiurgos
  version: "1.0"
---

## Contrato de Activación

Activa cuando el Autor quiere crear un personaje NUEVO ("crea/inventa un personaje", "necesito un personaje para...", "un hermano de X"). No aplica a: editar una ficha existente, rosters de personajes dentro de un arco (`narrative-character-spec`) ni consultas de lore.

## Reglas Duras

- Hermes NO tiene autoridad de escritura: nada persiste hasta la aprobación explícita del Autor sobre la propuesta diskless.
- Distingue SIEMPRE: **hechos** (dichos por el Autor), **propuestas**, **hipótesis**, **desconocidos** y **conflictos**. Nunca presentes detalles inventados como canon.
- Una pregunta a la vez. Jamás formularios ni conteos fijos (el legacy 7/12/18 queda en `skills/crear_personaje.md`, fuera de uso aquí).
- El servidor posee las salvaguardas (gate mínimo identidad+deseo, revisiones, token de confirmación, digest de contenido). No las evites ni las reemplaces.
- La ficha activa es contexto, no objetivo: si existe una, confirma si el destino es el personaje NUEVO o una edición. Referencias (p. ej. Rhyz) son contexto salvo selección explícita.

## Decision Gates

| Situación | Acción |
|-----------|--------|
| Personaje nuevo | Este skill |
| Editar ficha / roster de arco | Otro flujo (`narrative-character-spec`) |
| Modo rápido ("sin preguntas") | Supuestos marcados; saltar gate mínimo |
| Ancla faltante | Una pregunta por identidad (nombre) o deseo definidor |

## Pasos de Ejecución

1. **Objetivo**: confirma personaje NUEVO, mundo y relación con la ficha activa.
2. **Semilla y contexto de grafo**: consulta el grafo (search→read→links) para referencias nombradas; contexto acotado, sin rutas internas ni provenance visible.
3. **Rol y profundidad**: rol narrativo y profundidad deseados, conversacional, sin rangos fijos.
4. **Anclas mínimas**: identidad + deseo definidor (gate del servidor), luego conflicto significativo y relación/rol clave si aplica. Pequeño, no exhaustivo.
5. **Exploración adaptativa**: refleja lo dicho, identifica una tensión prometedora y haz UNA pregunta enfocada; opciones solo si ayudan (máx. 5). Profundiza el mundo, no recojas campos. Ver ejemplos en references.
6. **Certeza y provenance**: etiqueta hechos/propuestas/hipótesis/desconocidos/conflictos con su origen; confirma la certeza cuando un dato contradice o amplía el mundo.
7. **Convergencia**: cuando haya anclas y el Autor esté satisfecho, resume y ofrece la propuesta.
8. **Propuesta diskless**: serializa `personajes/{slug}.md` con status "proposed"; no escribas nada.
9. **Aceptar/rechazar**: el Autor aprueba o descarta cada propuesta; solo la aceptación la vuelve canon.
10. **Aprobación final**: diff con digest enlazado al token de confirmación; persiste SOLO tras la aprobación explícita.
11. **Persistencia e indexado**: reconcilia el grafo tras crear (indexed/pending/dirty/failed; reintenta si no indexa).

## Contrato de Salida

Devuelve: `status`, `executive_summary`, `artifacts`, `next_recommended`, `risks`, `skill_resolution`. Persiste el resultado en Engram.

## Referencias

- `references/conversation-examples.md` — ejemplos fuertes de exploración creativa (reflejo → tensión → una pregunta → opciones cuando ayudan).
