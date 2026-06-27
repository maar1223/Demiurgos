# Narrative Conventions — Vibrantes Universe

Project-specific narrative conventions for the Vibrantes universe. These apply to ALL arcs unless explicitly overridden.

## Ecosistema Narrativo

Vibrantes uses an **Ecosistema Narrativo** model:
- **No main plot**: There is no "main" storyline. Stories coexist independently within the same world.
- **Independent arcs**: Each story stands on its own. Characters from different arcs can cross paths organically.
- **Ecosystem, not franchise**: Stories don't have to connect or build toward a shared climax. They simply inhabit the same world.
- **Optional crossing**: Characters CAN meet across stories, but it's never required.

### Agent Behavior
- NEVER ask for "main plot" or "temporal location" — these concepts don't apply.
- NEVER assume a story is "primary" or "secondary." All arcs are equal peers.
- When proposing an arc, treat existing canon as ENVIRONMENT, not as a series to be continued.

## Stal Ranking System

Characters have Stal ranks using the Eneagrama de Stal (E1 through E9):

| Rank | Nivel | Descripción |
|------|-------|------------|
| E1 | Iniciado | Básico, primeros pasos |
| E2 | Practicante | Control básico |
| E3 | Competente | Uso rutinario |
| E4 | Avanzado | Maestría técnica |
| E5 | Principal | Experto, liderazgo (ej: Daest) |
| E6 | Maestro | Enseña a otros |
| E7 | Virtuoso | Nivel leyenda |
| E8 | Trascendente | Casi divino |
| E9 | Inmortal | Rango mítico (ej: Sonar) |

### Agent Behavior
- Respect Stal ranks when writing character capabilities.
- An E3 should not perform feats that an E5 would struggle with.
- Ranks imply hierarchy in the Stal society — higher ranks command respect.

## Technical Lore

### Vibrastal
- Mineral fundamental del universo.
- 4 fases: Sólido, Líquido, Gas, Plasma.
- Los Umbrales son portales/zonas de transición dimensional.
- El Colgante de las Cuatro Fases es una herramienta de sintonización.

### Áyagars
- Seres con capacidad de manipular Vibrastal.
- Existen en diferentes niveles de poder (alineado con rangos Stal).

### Agent Behavior
- NEVER invent new Vibrastal properties without author approval.
- The 4 phases are fixed canon — no "fifth phase" unless the author establishes it.
- Umbrales are dimensional — respect their established mechanics.

## Character Conventions

- Character sheets live in `{mundo_activo}/Personajes/` as individual Markdown files.
- Each character file follows a consistent structure: Identidad Básica, Apariencia, Trasfondo, Habilidades, Relaciones, Arco.
- Timeline events in character backstories must match `{mundo_activo}/Lore/Eventos.md` or `{mundo_activo}/Lore/CHANGELOG.md`.

## Writing Conventions

- **Spanish**: All narrative prose is written in Spanish (Rioplatense warmth, not excessive slang).
- **Close third person**: Default narrative distance. Character POV colors perception.
- **Show, don't tell**: Prefer sensory detail over exposition.
- **Lore through experience**: World rules are revealed through character interaction, not narration.

## File Structure

```
Vibrantes/
├── {mundo_activo}/Lore/           ← World rules, magic system, timeline, geography
├── {mundo_activo}/Personajes/     ← Character sheets (one per character)
├── {mundo_activo}/sagas/        ← Written stories (organized by arc)
└── Demiurgos/      ← The narrative engine source (this project)
```
