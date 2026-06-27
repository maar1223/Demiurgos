# Proyecto Demiurgos

Motor de Ingeniería Narrativa basado en la arquitectura de Gentle-AI + OpenCode.

## Objetivo

Adaptar el flujo Spec-Driven Development (SDD) de Gentle-AI para la creación de sagas literarias complejas de ciencia-ficción/fantasía, evitando errores de continuidad, invención de lore y ediciones no autorizadas.

## Paradigma: Intent-Driven (NO command-driven)

**Hablás naturalmente. El orquestador interpreta tu intención.** No necesitás memorizar comandos ni saber en qué fase estás.

Ejemplos de lo que podés decir:
- *"Quiero crear un personaje nuevo"* → el orquestador lanza `narrative-character-spec`
- *"Arranquemos un arco sobre los Áyagars"* → explora lore, propone, pregunta antes de seguir
- *"Escribamos el próximo capítulo"* → verifica estado actual, lanza `narrative-draft`
- *"¿En qué estábamos?"* → busca el estado en Engram y te dice qué fase sigue

Los comandos `/narrative-*` quedan como atajos opcionales para cuando quieras ser explícito.

## Arquitectura

**Overlay sobre Gentle-AI**: Demiurgos NO es un fork completo. Es una capa de dominio narrativo que se instala COMO EXTENSIÓN de Gentle-AI en `~/.config/opencode/`.

- Gentile-AI mantiene el **runtime** (delegación, protocolo MCP, TUI, sistema SDD)
- Demiurgos agrega el **dominio narrativo** (agentes, skills, interpretación de intención)
- Convivencia pacífica: proyectos técnicos usan SDD, proyectos narrativos usan SDD + Demiurgos

### 4 Orquestadores Jerárquicos

1. **Meta-Orquestador** (`Demiurgos-Orchestrator`) — coordina el ciclo de vida del arco/saga, interpreta intención natural, NUNCA escribe
2. **Planificador Narrativo** — explora, propone, especifica, diseña y desglosa tareas (read-only)
3. **Escritor Narrativo** — escribe borradores en `mundos/vibrantes/sagas/`, revisa (write scope acotado)
4. **Validador Narrativo** — verifica canon, consistencia, archiva (write solo CHANGELOG)

### 3 Mini-SDDs especializados

- **Planner** (6 ejecutores): explore → propose → world-spec ∥ character-spec → design → tasks
- **Writer** (3 ejecutores): outline → draft → revise
- **Validator** (2 ejecutores): verify → archive

Base teórica: Blake Snyder (15 beats, Save the Cat), Orson Scott Card (MICE Quotient), Brandon Sanderson (3 Leyes de la Magia, Promises→Progress→Payoff).

## Instalación

```powershell
# Desde el directorio de Demiurgos:
.\install.ps1
```

El instalador:
1. Verifica OpenCode + Gentle-AI instalados
2. Mergea agentes narrativos en `~/.config/opencode/opencode.json`
3. Copia commands, prompts y skills a `~/.config/opencode/`
4. Appendea reglas del meta-orquestador en `AGENTS.md`
5. Copia plugins TUI + logo

Es **NO destructivo**: no toca nada de Gentle-AI existente.

## Estructura del proyecto

```
Demiurgos/
├── README.md                 ← este archivo
├── src/                      ← fuentes a instalar
│   ├── opencode.json         ← fragmento con 15 agentes narrativos
│   ├── AGENTS.md             ← reglas del meta-orquestador (a appendear)
│   ├── commands/             ← 8 slash commands narrativos
│   ├── prompts/narrative/    ← 10 prompt stubs
│   ├── skills/               ← 11 skills ejecutores + _shared/
│   ├── plugins/              ← TUI plugin (logo)
│   └── tui-plugins/
├── install.ps1               ← instalador para Windows
└── install.sh                ← instalador para Linux/Mac
```

## Estado de construcción

- [x] Paso 1 — Estructura de directorios overlay (Demiurgos/src/)
- [x] Paso 2 — `src/opencode.json` — 12 agentes narrativos
- [x] Paso 3 — `src/prompts/narrative/Demiurgos-Orchestrator.md` — prompt del meta-orquestador
- [x] Paso 4 — `src/commands/` — 8 commands narrativos
- [x] Paso 5 — `src/prompts/narrative/` — 11 prompt stubs
- [x] Paso 6 — `src/skills/narrative-*/` — 11 skills ejecutores
- [x] Paso 7 — `src/skills/_shared/` — archivos compartidos
- [x] Paso 8 — Plugin TUI + logo
- [x] Paso 9 — `install.ps1` — script instalador overlay
- [x] Paso 10 — Prompt del orquestador reescrito como intent-driven (interpretación de lenguaje natural)
- [ ] Paso 11 — Prueba con material de Vibrantes
- [ ] Paso 12 — `install.sh` para Linux/Mac

## Referencias

- Proyecto base: Vibrantes (universo Stal/Eneagrama/Áyagars)
- Framework base: Gentle-AI 1.27.3+ sobre OpenCode 1.15.0
- Memoria persistente: Engram MCP
- Directorio de instalación: `~/.config/opencode/` (overlay sobre Gentle-AI)
