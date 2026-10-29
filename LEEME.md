# Demiurgos — Plataforma de Lore y Worldbuilding

Bienvenido a Demiurgos, la plataforma web de worldbuilding y gestión de lore: frontend React, backend FastAPI, grafo de entidades, memoria persistente (Engram) y asistente conversacional (Hermes). Gestiona cualquier mundo ficticio en **formato OKF** (Markdown + frontmatter YAML) sin acoplarse a un universo concreto.

Si eres un usuario nuevo, este documento es tu **Punto de Partida**.

---

## 1. Estado de la instalación

> ✅ **La instalación oficial ya está disponible**, en un solo comando desde el canal público firmado. Linux / macOS: `curl -fsSL https://github.com/maar1223/demiurgos-releases/releases/latest/download/install.sh | bash`; Windows (PowerShell): `irm https://github.com/maar1223/demiurgos-releases/releases/latest/download/install.ps1 | iex`. También puedes arrancar Demiurgos desde el repositorio: clonar → crear `venv` → `npm install` → launchers (ver sección 4). `install.sh` sin flags instala la app web; el stack CLI de desarrollo (Hermes, Engram y las skills narrativas) es opt-in con `bash install.sh --with-cli-stack`.

---

## 2. El Rol de la IA

Demiurgos opera bajo las reglas establecidas en `Agente_Maestro.md`. Las directrices principales son:

1. **Protector del Canon:** La IA es guardiana de la coherencia. Las reglas del mundo (carpeta `mundos/{mundo_activo}/lore/`) son sagradas. Si pides algo que contradice el canon, la IA te advertirá y propondrá una solución coherente.
2. **Tono:** Épico, místico y honesto. Sin lenguaje genérico ni complaciente.
3. **Fases:** El subsistema narrativo de Demiurgos usa 13 fases para el proceso creativo guiado por intención (vía Hermes).

---

## 3. Estructura del Proyecto

```
Demiurgos/
├── frontend/                    ← App web (React + Vite + TypeScript + Tailwind)
├── src/tools/demiurgos-suite/   ← Backend FastAPI y subsistema narrativo
│   └── wiki/                    ← api_server.py, grafo, importador, bóveda
├── mundos/                      ← Datos de los mundos (formato OKF)
│   └── {mundo}/
│       ├── lore/                ← Reglas del mundo, política, tecnología
│       ├── personajes/          ← Fichas de personajes
│       ├── sagas/               ← Relatos y capítulos terminados
│       ├── ideas/               ← Banco de ideas
│       └── ...
├── scripts/                     ← Launchers y utilidades (Linux/macOS)
├── start-demiurgos.ps1          ← Launcher de Windows
├── plantillas/                  ← Catálogos narrativos (Snyder, tramas)
├── docs/                        ← Documentación técnica y de arquitectura
└── install.sh                   ← Bootstrap de la app web (stack CLI opcional con --with-cli-stack)
```

---

## 4. Cómo Empezar

1. **Clona el repositorio:** `git clone https://github.com/maar1223/Demiurgos.git && cd Demiurgos`
2. **Prepara el backend:**
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r src/tools/demiurgos-suite/requirements.txt
   ```
3. **Prepara el frontend:** `cd frontend && npm install && cd ..`
4. **Arranca la plataforma:**
   - Linux / macOS: `./scripts/start-demiurgos.sh start`
   - Windows: `powershell -ExecutionPolicy Bypass -File start-demiurgos.ps1`
5. **Abre la app:** `http://127.0.0.1:8000` — el primer arranque muestra el onboarding (idioma, proveedores LLM, crear o importar un mundo).

> **Opcional:** si quieres el stack CLI de desarrollo (Hermes Agent, Engram y las skills narrativas de las 13 fases), usa el flag opt-in: `bash install.sh --with-cli-stack`. No es necesario para usar la app web (`install.sh` sin flags instala la app web).

---

## 5. El Flujo de Trabajo Narrativo (vía Hermes)

El subsistema narrativo es **intent-driven**: hablas naturalmente y el orquestador interpreta qué fase necesitas. Se usa desde Hermes, no desde la app web.

| Si dices... | Demiurgos ejecuta... |
|-------------|---------------------|
| "arranquemos" | `/narrative-init` — inicializa el proyecto |
| "crear un personaje" | `/narrative-character-spec` |
| "quiero escribir una historia sobre..." | Explora → Propone → Diseña → Escribe |
| "revisa lo que escribí" | `/narrative-revise` |
| "verifica el canon" | `/narrative-verify` |
| "¿en qué estábamos?" | Recupera el estado y sugiere la siguiente fase |

No necesitas memorizar comandos. La conversación natural es el camino principal.