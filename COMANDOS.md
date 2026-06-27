# Demiurgos — Guía Rápida

> **Paradigma: Intent-Driven (desde 2026-05-15)**
>
> **No necesitás memorizar comandos.** Hablá naturalmente y Demiurgos interpreta tu intención:
> - *"Quiero crear un personaje"* → lanza el agente correcto
> - *"Escribamos el siguiente capítulo"* → sabe en qué fase estás y avanza
> - *"¿En qué estábamos?"* → recupera el estado del arco activo
>
> Los comandos listados abajo son **atajos opcionales** para cuando quieras ser explícito. El camino feliz es la conversación natural.

---

## 🌊 El Ciclo Narrativo (NEC)

```
/narrative-new "nombre-del-arco"
    │
    ├─→ EXPLORAR (automático) ──→ PROPONER ──→ [VOS APROBÁS]
    │
    ├─→ /narrative-continue ──→ WORLD SPEC ──┐
    │                              ∥ (paralelo)
    │                           CHARACTER SPEC┘
    │
    ├─→ /narrative-continue ──→ DESIGN (beats, outline)
    │
    ├─→ /narrative-continue ──→ TASKS (escenas desglosadas)
    │
    ├─→ /narrative-write ──→ OUTLINE (contexto) → DRAFT → REVISE
    │
    └─→ /narrative-verify → /narrative-archive
```

## 📋 Todos los comandos

### Arranque

| Comando | Qué hace | Cuándo usarlo |
|---------|----------|---------------|
| `/narrative-init` | Inicializa el motor narrativo en tu proyecto | **Una sola vez** al principio |
| `/narrative-onboard` | Tour guiado por todo el sistema | Cuando querés aprender el flujo |

### Planificar un arco nuevo

| Comando | Qué hace | Cuándo usarlo |
|---------|----------|---------------|
| `/narrative-new "nombre"` | Explora lore existente + crea propuesta | Al empezar un arco nuevo |
| `/narrative-ff "nombre"` | Fast-forward: propuesta → specs → diseño → tareas | Si ya sabés qué querés escribir |
| `/narrative-explore "tema"` | Investiga lore sin crear nada | Para tantear ideas antes de comprometerte |
| `/narrative-continue` | Avanza a la siguiente fase pendiente | Después de aprobar una fase |

### Escribir

| Comando | Qué hace | Cuándo usarlo |
|---------|----------|---------------|
| `/narrative-write` | Escribe escenas/capítulos en mundos/vibrantes/sagas/ | Cuando el planning está listo |
| `/narrative-continue` | Sigue escribiendo la siguiente tanda | Para sesiones de escritura por lotes |

### Verificar y cerrar

| Comando | Qué hace | Cuándo usarlo |
|---------|----------|---------------|
| `/narrative-verify` | Verifica canon, continuidad, consistencia | Después de terminar el borrador |
| `/narrative-archive` | Cierra el arco, actualiza CHANGELOG | Cuando está todo verificado y aprobado |

### Ayuda

| Comando | Qué hace | Cuándo usarlo |
|---------|----------|---------------|
| `/narrative-help` | Muestra esta guía | Cuando estás perdido 😅 |

---

## 🧭 ¿En qué fase estoy? ¿Qué comando uso?

| Si estoy... | Uso... |
|-------------|--------|
| Recién arrancando el proyecto | `/narrative-init` |
| Con una idea vaga | `/narrative-explore "mi idea"` |
| Con una idea clara, quiero planificar | `/narrative-new "nombre-del-arco"` |
| Ya tengo propuesta aprobada, quiero specs | `/narrative-continue` |
| Ya tengo specs, quiero diseño de beats | `/narrative-continue` |
| Ya tengo diseño, quiero tareas | `/narrative-continue` |
| Ya tengo tareas, quiero escribir | `/narrative-write` |
| Ya escribí, quiero seguir | `/narrative-continue` o `/narrative-write` |
| Terminé el borrador | `/narrative-verify` |
| Verifiqué, todo OK | `/narrative-archive` |

---

## ⚡ Atajos mentales

- **Hablá naturalmente** — es el camino principal. Decí "sigamos" o "¿en qué estábamos?" y el orquestador entiende.
- **`/narrative-continue`** — atajo explícito para avanzar una fase
- **`/narrative-ff`** — atajo para ir rápido si ya tenés la historia en la cabeza
- **`/narrative-write`** — atajo para saltar directo a escritura (si el planning está completo)
- **`/narrative-verify`** — verificá antes de archivar SIEMPRE

---

## 💡 Banco de Ideas

Capturá ideas espontáneas desde el celu o el chat y sincronizalas con tu proyecto.

| Comando | Subcomando | Qué hace |
|---------|------------|----------|
| `/narrative-idea` | `capture` | Guarda una idea (texto o voz) en el banco |
| `/narrative-idea` | `browse` | Lista ideas con filtros por tipo, tags, fecha |
| `/narrative-idea` | `search <query>` | Busca ideas por contenido o tags |
| `/narrative-idea` | `sync` | Sincroniza ideas capturadas desde el celu (Sheets → local) |
| `/narrative-idea` | `promote` | Promueve una idea a propuesta de arco narrativo |

**Setup**: Para capturar desde el celu necesitás un bot de Telegram + Google Sheets (ver `Demiurgos/src/tools/sync-ideas.py`). Desde el chat, la captura es directa y no requiere configuración.

> 💡 El sync del banco de ideas se ejecuta automáticamente al iniciar sesión en Vibrantes.

---

## 🚫 Lo que NUNCA pasa (boundaries)

- El planner **no escribe** archivos (solo artefactos en Engram)
- El writer **no toca** mundos/vibrantes/Personajes/ ni mundos/vibrantes/Lore/ (solo mundos/vibrantes/sagas/)
- El validator **no edita** borradores (solo verifica y archiva)
