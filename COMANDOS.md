# Demiurgos — Guía Rápida

> **Paradigma: Intent-Driven.** Habla naturalmente y Demiurgos interpreta tu intención. No necesitas memorizar comandos.
>
> Los comandos listados abajo son **atajos opcionales** para cuando quieras ser explícito.

---

## Fases Narrativas (13 skills)

| Fase | Comando | Qué produce |
|------|---------|-------------|
| Init | `/narrative-init` | Inicializa el proyecto narrativo |
| Explore | `/narrative-explore` | Reporte de lore, personajes, contexto |
| Propose | `/narrative-propose` | Propuesta de arco (logline, MICE) |
| World Spec | `/narrative-world-spec` | Reglas y restricciones del mundo |
| Character Spec | `/narrative-character-spec` | Fichas de personaje |
| Design | `/narrative-design` | Beats Snyder, capítulos |
| Tasks | `/narrative-tasks` | Escenas desglosadas |
| Outline | `/narrative-outline` | Contexto completo para escribir |
| Draft | `/narrative-draft` | Prosa narrativa |
| Revise | `/narrative-revise` | Revisión estructural y de voz |
| Verify | `/narrative-verify` | Validación de canon |
| Archive | `/narrative-archive` | Cierre de arco + CHANGELOG |
| Idea Bank | `/narrative-idea` | Captura, búsqueda, sync de ideas |

---

## Orden de fases

```
narrative-init → explore (opcional) → propose → world-spec ∥ character-spec
                                                      ↓
                                                  design → tasks → outline → draft → revise → verify → archive
```

---

## Atajos mentales

- **Habla naturalmente** — es el camino principal. Di "sigamos" o "¿en qué estábamos?" y el orquestador entiende.
- **`/narrative-verify`** — verifica antes de archivar SIEMPRE.

---

## Lo que NUNCA pasa

- El planner **no escribe** archivos (solo artefactos en Engram)
- El writer **no toca** `Lore/` ni `Personajes/` (solo `sagas/`)
- El validator **no edita** borradores (solo verifica y archiva)
