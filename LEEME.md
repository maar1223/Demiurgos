# Demiurgos — Sistema de Creación Narrativa

Bienvenido a Demiurgos, el motor narrativo para Hermes Agent. Crea, indexa y escribe historias con asistencia de IA, manteniendo coherencia de canon y continuidad entre arcos.

Si eres un nuevo usuario, este documento es tu **Punto de Partida**.

---

## 1. El Rol de la IA

Demiurgos opera bajo las reglas establecidas en `Agente_Maestro.md`. Las directrices principales son:

1. **Protector del Canon:** La IA es guardiana de la coherencia. Las reglas del mundo (carpeta `mundos/{mundo_activo}/Lore/`) son sagradas. Si pides algo que contradice el canon, la IA te advertirá y propondrá una solución coherente.
2. **Tono:** Épico, místico y honesto. Sin lenguaje genérico ni complaciente.
3. **Fases:** Demiurgos usa 13 fases narrativas para cada paso del proceso creativo.

---

## 2. Estructura del Proyecto

```
tu-mundo/
├── AGENTS.md                       ← Orquestador (system prompt)
├── .env                            ← DEMIURGOS_WORLD=tu-mundo
├── .demiurgos-estado.json          ← Tracking de arcos
├── mundos/tu-mundo/
│   ├── Lore/                       ← Reglas del mundo, política, tecnología
│   ├── Personajes/                 ← Fichas de personajes
│   ├── sagas/                      ← Relatos y capítulos terminados
│   └── Ideas/                      ← Banco de ideas
├── plantillas/                     ← Catálogos narrativos (Snyder, tramas)
└── .gitignore
```

---

## 3. El Flujo de Trabajo

Demiurgos es **intent-driven**: hablas naturalmente y el orquestador interpreta qué fase necesitas.

| Si dices... | Demiurgos ejecuta... |
|-------------|---------------------|
| "arranquemos" | `/narrative-init` — inicializa el proyecto |
| "crear un personaje" | `/narrative-character-spec` |
| "quiero escribir una historia sobre..." | Explora → Propone → Diseña → Escribe |
| "revisa lo que escribí" | `/narrative-revise` |
| "verifica el canon" | `/narrative-verify` |
| "¿en qué estábamos?" | Recupera el estado y sugiere la siguiente fase |

No necesitas memorizar comandos. La conversación natural es el camino principal.

---

## 4. Cómo Empezar

1. **Instala Demiurgos:** `curl -fsSL https://get.demiurgos.dev | bash`
2. **Elige:** Crear un mundo nuevo o cargar uno existente
3. **Entra a tu mundo:** `cd ~/demiurgos/tu-mundo`
4. **Inicia Hermes:** `hermes`
5. **Di:** "arranquemos"

La IA tomará el control desde ahí, guiándote por las fases narrativas.
