# Taxonomía de Skills de Demiurgos

> **Referencia de arquitectura.**
> Define cómo se clasifican las skills de Demiurgos. Este vocabulario vive en el código, los prompts,
> el UI del Taller de Herramientas y la documentación — por eso se fija acá para que no se reinterprete.

## El árbol de skills

```
Skills
├── Fundacional (del sistema, universal)        ← vienen con Demiurgos
└── Personalizadas (del autor)
    ├── De Mundo (atada a un mundo)            ← Stal, lugares, razas, poderes
    └── Transversal (aplica a cualquier mundo)  ← método / vocabulario del autor
```

## Definición de cada rama

| Rama | Origen | Ámbito | Qué aporta | Activación |
|---|---|---|---|---|
| **Fundacional** | Sistema | Universal | Esqueleto de personaje/ficha (identidad, carácter, Eneatipo, Subtipo, Arquetipo, Alineamiento, conflicto, arco) | Siempre |
| **Personalizada de Mundo** | Autor (Taller de Herramientas) | Un mundo concreto | Conocimiento y **campos indexables** del mundo (Stal, razas, lugares, poderes) | Solo en ese mundo |
| **Personalizada Transversal** | Autor (Taller de Herramientas) | Cualquier mundo | Método / vocabulario / convenciones del autor (cómo hace las cosas, criterios propios) | Siempre |

## La frontera funcional entre las dos personalizadas

- **De Mundo** → se activa **solo en ese mundo**; puede agregar **campos indexables** de ese mundo
  (que el grafo entiende sin ambigüedad). Es la que enriquece el OKF con el color del mundo.
- **Transversal** → se activa **siempre**; aporta **método y vocabulario** que valen para cualquier mundo,
  pero **NO** agregar campos indexables de un mundo (porque un campo de un mundo no le aplica a otro).
  Si una transversal necesita referenciar un mundo, lo hace desde su contenido (texto), no desde el
  sistema de campos.

Esta separación le dice al backend exactamente qué esperar de cada una: qué se activa dónde y si puede
extender el esquema de datos.

## Mapeo con el backend existente (verificado)

- `SkillRouter.TRANSVERSAL_SKILLS` → ya modela el concepto **transversal** (las narrativas que aplican siempre).
- `methodology_library.activate(world, skill_id, version)` + `active_for(world)` → ya modela la activación
  **por mundo**.
- `methodology_compiler.compile_methodology()` → es el compilador de **todas** las personalizadas
  (manifest acotado + Markdown + phases), con la frontera de autoridad.

## Relación con la Skill Fundacional de personajes

La **Skill Fundacional** crea la base universal del personaje. Las **Personalizadas** la extienden:
- **De Mundo** → enriquece con el color/campos del mundo (Stal, etc.).
- **Transversal** → ajusta el método/criterios para cómo el autor prefiere trabajar.

Cadena: *Fundacional crea la base → Personalizada (por mundo y/o transversal) la extiende.*

## Ver también

- [`skill-personalizada-de-mundo.md`](skill-personalizada-de-mundo.md) — arquitectura de la skill por mundo
- [`README.md`](README.md) — decisiones del diseño de la skill de personajes
