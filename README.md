# Demiurgos

[English](README.en.md) · **Español**

**Tu mundo ficticio, ordenado y conectado.** Demiurgos es una aplicación web que se ejecuta en tu propia computadora para escribir, organizar y conectar el lore de cualquier mundo ficticio. Trabaja con archivos Markdown (formato **OKF**), incluye editor, grafo de entidades, importador de documentos y un asistente de IA. No está atada a un universo concreto: **Vibrantes** es un mundo de ejemplo, no un requisito.

> **Estado:** beta, en desarrollo activo. El Core es gratuito; los talleres son opcionales y de compra única. El código fuente no se distribuye públicamente por defecto.

---

## Instalar en 3 pasos

Demiurgos se instala **en tu carpeta de usuario** y no necesita Python, Node ni compilador. Solo hay que preparar dos herramientas una vez: `git` (para descargar el asistente) y `minisign` (para verificar la firma de los archivos). El instalador de Demiurgos no pide administrador; el bloque de preparación sí puede pedir tu contraseña para instalar esas herramientas del sistema.

### Antes: prepara `git` y `minisign` (solo la primera vez)

**Windows 10/11** — abre PowerShell y ejecuta el bloque completo:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
irm get.scoop.sh | iex
scoop install git minisign
```

**macOS (Apple Silicon, macOS 13 o superior)** — abre Terminal:

```bash
# Si no tienes Homebrew:
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install git minisign
```

**Linux** — abre Terminal:

```bash
# Debian / Ubuntu
sudo apt install git minisign
# Fedora: sudo dnf install git minisign
# Arch:   sudo pacman -S git minisign
```

### Paso 1 — Instala Demiurgos

**Linux / macOS:**

```bash
curl -fsSL https://raw.githubusercontent.com/maar1223/demiurgos-releases/main/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/maar1223/demiurgos-releases/main/install.ps1 | iex
```

### Paso 2 — Espera a que termine

El instalador verifica la firma y los checksums de todo lo que descarga **antes** de ejecutarlo. Después instala la aplicación y el asistente. Tarda unos minutos según tu conexión; no cierres la ventana. Al final verás:

```
install-demiurgos: done. Start Demiurgos with:
  ...
```

### Paso 3 — Abre Demiurgos

| Sistema | Cómo abrirlo |
|---|---|
| **Linux** | Menú de aplicaciones → **Demiurgos**. Se abre una terminal que inicia los servicios y luego el navegador. |
| **Windows** | Menú Inicio → **Demiurgos**. Se abre el navegador. |
| **macOS** | Todavía no hay acceso directo: ejecuta el comando de abajo. |

```bash
# Linux / macOS
~/.demiurgos/current/scripts/start-demiurgos.sh start
```

```powershell
# Windows
& "$env:LOCALAPPDATA\Demiurgos\current\scripts\start-demiurgos.ps1" start
```

La aplicación queda en **http://127.0.0.1:8000** y el navegador se abre solo. Si no se abre, entra a esa dirección a mano. El acceso directo **en el escritorio** es opcional:

```bash
# Linux: agrega el icono al escritorio
~/.demiurgos/current/scripts/start-demiurgos.sh install --desktop
```

```powershell
# Windows: agrega el icono al escritorio
& "$env:LOCALAPPDATA\Demiurgos\current\scripts\start-demiurgos.ps1" install -Desktop
```

---

## ¿Funciona en mi equipo?

| Sistema | ¿Soportado? |
|---|---|
| Windows 10 / 11, 64 bits | ✅ |
| macOS 13 o superior, **Apple Silicon** (M1/M2/M3…) | ✅ |
| Linux 64 bits (x86_64 o ARM64), glibc 2.28 o superior | ✅ |
| macOS con procesador **Intel** | ❌ |
| macOS anterior a 13 | ❌ |
| Linux musl / Alpine | ❌ |

Para comprobar tu versión:

```bash
# macOS
sw_vers -productVersion && uname -m
# Linux
ldd --version | head -1 && uname -m
```

```powershell
# Windows
winver
```

Si tu sistema no está en la lista, el instalador se detiene al principio con un mensaje claro y no deja nada a medias.

---

## Si algo falla

| Mensaje o síntoma | Qué hacer |
|---|---|
| `minisign is required to verify the signed manifest` | Instala `minisign` con el bloque de arriba y vuelve a ejecutar el comando. |
| `is git installed?` o falla el asistente | Instala `git` con el bloque de arriba y vuelve a ejecutar el comando. |
| Windows bloquea el script (`ExecutionPolicy`) | Ejecuta `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` y prueba otra vez. |
| `Intel Macs are not supported` | Los Mac con Intel no están soportados en esta etapa. |
| `macOS 13 or newer is required` | Actualiza macOS. |
| `musl/Alpine is not supported` o `glibc 2.28 or newer` | Usa una distribución Linux basada en glibc (Debian, Ubuntu, Fedora…). |
| El navegador no se abrió | Abre **http://127.0.0.1:8000** a mano. |
| La app no arranca | Mira los registros en `~/.demiurgos/logs/` (Linux/macOS) o `%LOCALAPPDATA%\Demiurgos\logs\` (Windows). |
| Necesitas pedir ayuda | Linux/macOS: `~/.demiurgos/current/scripts/collect-diagnostics.sh` genera un `.tar.gz`. Revísalo antes de compartirlo. Windows: usa **Perfil → Reporte de errores** dentro de la app. |

Volver a ejecutar el mismo comando de instalación es seguro: no duplica nada y repara lo que falte.

---

## Después de instalar

| Qué | Dónde |
|---|---|
| Programa | `~/.demiurgos` (Linux/macOS) · `%LOCALAPPDATA%\Demiurgos` (Windows) |
| Tus mundos y datos | `Documentos/Demiurgos` (tu carpeta de Documentos) |
| Registros | `~/.demiurgos/logs` · `%LOCALAPPDATA%\Demiurgos\logs` |
| Acceso del menú | Linux: `~/.local/share/applications/Demiurgos.desktop` · Windows: menú Inicio |

- **Actualizar:** vuelve a ejecutar el mismo comando de instalación. No hay actualizaciones silenciosas ni cambios sin que los pidas.
- **Desinstalar:** primero detén la app y luego borra la carpeta del programa. Tus mundos quedan intactos en `Documentos/Demiurgos`; bórralos solo si tú quieres.
- **Cambiar la carpeta de datos:** usa `--data-root RUTA` al instalar, o el ajuste dentro de la app.

```bash
# Linux / macOS: detener antes de borrar
~/.demiurgos/current/scripts/start-demiurgos.sh stop
rm -rf ~/.demiurgos
rm -f ~/.local/share/applications/Demiurgos.desktop
# Opcional: rm -rf "Documentos/Demiurgos"   ← borra tus mundos
```

```powershell
# Windows
& "$env:LOCALAPPDATA\Demiurgos\current\scripts\start-demiurgos.ps1" stop
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Demiurgos"
# Opcional: borra "Documentos\Demiurgos"      ← borra tus mundos
```

---

## Primeros pasos

Al abrirla por primera vez, Demiurgos te guía con el **onboarding**: eliges el idioma de la interfaz, configuras el proveedor de IA y creas un mundo nuevo o importas uno existente. Las instalaciones que ya existen nunca vuelven al onboarding.

- **Crear un mundo:** empieza vacío y usa el editor o el Taller de Mundo.
- **Importar un mundo:** acepta Markdown, Word (`.docx`), PDF y exportaciones de Notion. El flujo es **subir → analizar → revisar → aprobar → ejecutar**, con rollback.
- **Asistente:** el panel lateral conversa con el asistente. Nada se guarda sin que apruebes el diff.
- **Papelera:** lo borrado va a una papelera de 30 días, por archivo y por mundo.

---

## Qué puedes hacer

| Función | Qué hace |
|---|---|
| **Wiki y editor** | Crear, editar, restaurar y comparar archivos OKF; historial y estados `draft`/`stable`. |
| **Grafo de entidades** | Entidades, enlaces y backlinks derivados de tus archivos, con búsqueda. |
| **Importador** | Word, PDF, Markdown y Notion → Markdown limpio con frontmatter OKF. |
| **Asistente de IA** | Chat con streaming, sugerencias de edición y aprobación por diff. |
| **Creación guiada** | Taller de personajes con protocolo de confirmación y propuestas sin escribir en disco. |
| **Ideas** | Banco de ideas con versiones y captura opcional por Telegram. |
| **Metodologías y talleres** | Talleres editables y compilables por el autor. |
| **Bóveda local** | Una cuenta local, contraseña opcional y palabras de recuperación EFF, 100% offline. |
| **Papelera** | Retención de 30 días por archivo y por mundo. |

---

## Configuración avanzada

La configuración es opcional y por variables de entorno; no hace falta un `.env` para la bóveda. Las más útiles:

| Variable | Valor por defecto | Para qué |
|---|---|---|
| `DEMIURGOS_LANGUAGE` | `es` | Idioma de la interfaz. |
| `DEMIURGOS_API_PORT` / `DEMIURGOS_GATEWAY_PORT` | `8000` / `8642` | Cambiar si el puerto está ocupado. |
| `DEMIURGOS_AUTH_MODE` | `local-dev` | `local-dev` (sesión local) o `credentials` (bóveda con contraseña). |
| `DEMIURGOS_TEXT_PROVIDER/ENDPOINT/MODEL` | opencode-go | Proveedor del asistente. |
| `DEMIURGOS_DATA_ROOT` | `Documentos/Demiurgos` | Carpeta de datos (no escribe el puntero; usa `--data-root` para que sea permanente). |

El detalle completo está en [`.env.example`](.env.example). Demiurgos se ejecuta como aplicación local en `127.0.0.1`; el despliegue remoto/VPS está fuera del alcance del MVP.

---

## Para desarrolladores

La instalación de un comando es la vía soportada para usuarios. Para trabajar sobre el código:

```bash
git clone https://github.com/maar1223/Demiurgos.git
cd Demiurgos
python3 -m venv .venv
.venv/bin/pip install -r src/tools/demiurgos-suite/requirements.txt
cd frontend && npm install && cd ..
./scripts/start-demiurgos.sh start
```

Pruebas: `pytest src/tools/demiurgos-suite/wiki/tests/` y `cd frontend && npm test`. El stack técnico, las decisiones de producto y la arquitectura están en [`docs/`](docs/), y la guía de instalación detallada en [`docs/install/ONE_SCREEN_GUIDE.md`](docs/install/ONE_SCREEN_GUIDE.md).

---

## Estado y licencia

- **Freeware propietario:** el Core es gratuito; los talleres son una compra única opcional.
- La versión instalada nunca se bloquea: una ventana de actualización vencida no degrada lo que ya tienes.
- Los mundos son privados: el contenido de `mundos/` está fuera del repositorio y nunca se publica.
- Hecho por [@maar1223](https://github.com/maar1223).
- English version: [README.en.md](README.en.md)

*"No asumir nada. Si tienes dudas, busca el contexto en el proyecto."*
