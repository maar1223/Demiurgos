# Demiurgos

**English** · [Español](README.md)

**Your fictional world, organized and connected.** Demiurgos is a web application that runs on your own computer to write, organize and connect the lore of any fictional world. It works with Markdown files (**OKF** format), and includes an editor, an entity graph, a document importer and an AI assistant. It is not tied to a single universe: **Vibrantes** is an example world, not a requirement.

> **Status:** beta, under active development. The Core is free; workshops are optional and a one-time purchase. Source code is not distributed publicly by default.

---

## Install in 3 steps

Demiurgos installs **into your user folder** and requires no Python, Node or compiler. You only need to prepare two tools once: `git` (to download the assistant) and `minisign` (to verify the signature of the downloaded files). The Demiurgos installer does not need administrator rights; the preparation block may ask for your password to install those system tools.

### First: prepare `git` and `minisign` (one time only)

**Windows 10/11** — open PowerShell and run the whole block:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
irm get.scoop.sh | iex
scoop install git minisign
```

**macOS (Apple Silicon, macOS 13 or newer)** — open Terminal:

```bash
# If you do not have Homebrew, install it first from https://brew.sh
brew install git minisign
```

**Linux** — open Terminal:

```bash
# Debian / Ubuntu
sudo apt install git minisign
# Fedora: sudo dnf install git minisign
# Arch:   sudo pacman -S git minisign
```

### Step 1 — Install Demiurgos

**Linux / macOS:**

```bash
curl -fsSL https://raw.githubusercontent.com/maar1223/demiurgos-releases/main/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/maar1223/demiurgos-releases/main/install.ps1 | iex
```

### Step 2 — Wait for it to finish

The installer verifies the signature and checksums of everything it downloads **before** running it. It then installs the application and the assistant. It takes a few minutes depending on your connection; do not close the window. At the end you will see:

```
install-demiurgos: done. Start Demiurgos with:
  ...
```

### Step 3 — Open Demiurgos

| System | How to open it |
|---|---|
| **Linux** | Applications menu → **Demiurgos**. The browser opens (no terminal window). |
| **Windows** | Start menu → **Demiurgos**. The browser opens. |
| **macOS** | There is no shortcut yet: run the command below. |

```bash
# Linux / macOS
~/.demiurgos/current/scripts/start-demiurgos.sh start
```

```powershell
# Windows
& "$env:LOCALAPPDATA\Demiurgos\current\scripts\start-demiurgos.ps1" start
```

The app is available at **http://127.0.0.1:8000** and the browser opens by itself. If it does not open, enter that address manually. The **desktop** shortcut is optional:

```bash
# Linux: add the desktop icon
~/.demiurgos/current/scripts/start-demiurgos.sh install --desktop
```

```powershell
# Windows: add the desktop icon
& "$env:LOCALAPPDATA\Demiurgos\current\scripts\start-demiurgos.ps1" install -Desktop
```

---

## Will it work on my computer?

| System | Supported? |
|---|---|
| Windows 10 / 11, 64-bit | ✅ |
| macOS 13 or newer, **Apple Silicon** (M1/M2/M3…) | ✅ |
| Linux 64-bit (x86_64 or ARM64), glibc 2.28 or newer | ✅ |
| macOS on an **Intel** processor | ❌ |
| macOS older than 13 | ❌ |
| Linux musl / Alpine | ❌ |

Check your version:

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

If your system is not listed, the installer stops at the beginning with a clear message and leaves nothing half-installed.

---

## If something fails

| Message or symptom | What to do |
|---|---|
| `minisign is required to verify the signed manifest` | Install `minisign` with the block above and run the command again. |
| `is git installed?` or the assistant fails | Install `git` with the block above and run the command again. |
| Windows blocks the script (`ExecutionPolicy`) | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` and try again. |
| `Intel Macs are not supported` | Intel Macs are not supported at this stage. |
| `macOS 13 or newer is required` | Update macOS. |
| `musl/Alpine is not supported` or `glibc 2.28 or newer` | Use a glibc-based Linux distribution (Debian, Ubuntu, Fedora…). |
| The browser did not open | Open **http://127.0.0.1:8000** manually. |
| The app does not start | Check the logs in `~/.demiurgos/logs/` (Linux/macOS) or `%LOCALAPPDATA%\Demiurgos\logs\` (Windows). |
| You need to ask for help | Linux/macOS: `~/.demiurgos/current/scripts/collect-diagnostics.sh` produces a `.tar.gz`. Review it before sharing. Windows: use **Profile → Error report** inside the app. |

Running the same install command again is safe: it does not duplicate anything and repairs what is missing.

---

## After installing

| What | Where |
|---|---|
| Application | `~/.demiurgos` (Linux/macOS) · `%LOCALAPPDATA%\Demiurgos` (Windows) |
| Your worlds and data | `Documents/Demiurgos` (your Documents folder) |
| Logs | `~/.demiurgos/logs` · `%LOCALAPPDATA%\Demiurgos\logs` |
| Menu entry | Linux: `~/.local/share/applications/Demiurgos.desktop` · Windows: Start menu |

- **Update:** run the same install command again. There are no silent updates or changes you did not ask for.
- **Uninstall:** stop the app first, then delete the application folder. Your worlds stay untouched in `Documents/Demiurgos`; delete them only if you want to.
- **Change the data folder:** use `--data-root PATH` at install time, or the setting inside the app.

```bash
# Linux / macOS: stop before deleting
~/.demiurgos/current/scripts/start-demiurgos.sh stop
rm -rf ~/.demiurgos
rm -f ~/.local/share/applications/Demiurgos.desktop
# Optional: rm -rf "Documents/Demiurgos"   ← deletes your worlds
```

```powershell
# Windows
& "$env:LOCALAPPDATA\Demiurgos\current\scripts\start-demiurgos.ps1" stop
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Demiurgos"
# Optional: delete "Documents\Demiurgos"      ← deletes your worlds
```

---

## First steps

On first launch, Demiurgos walks you through **onboarding**: pick the interface language, configure the AI provider, and create a new world or import an existing one. Existing installations never go back to onboarding.

- **Create a world:** start empty and use the editor or the World Workshop.
- **Import a world:** accepts Markdown, Word (`.docx`), PDF and Notion exports. The flow is **upload → analyze → review → approve → execute**, with rollback.
- **Assistant:** the side panel talks to the assistant. Nothing is saved until you approve the diff.
- **Trash:** deleted content goes to a 30-day recycle bin, per file and per world.

---

## What you can do

| Feature | What it does |
|---|---|
| **Wiki and editor** | Create, edit, restore and compare OKF files; history and `draft`/`stable` states. |
| **Entity graph** | Entities, links and backlinks derived from your files, with search. |
| **Importer** | Word, PDF, Markdown and Notion → clean Markdown with OKF frontmatter. |
| **AI assistant** | Streaming chat, edit suggestions and approval by diff. |
| **Guided creation** | Character workshop with a confirmation protocol and diskless proposals. |
| **Ideas** | Idea bank with versions and optional Telegram capture. |
| **Methodologies and workshops** | Workshops that the author can edit and compile. |
| **Local vault** | One local account, optional password and EFF recovery words, 100% offline. |
| **Trash** | 30-day retention per file and per world. |

---

## Advanced configuration

Configuration is optional and environment-based; no `.env` is required for the vault. The most useful variables:

| Variable | Default | Purpose |
|---|---|---|
| `DEMIURGOS_LANGUAGE` | `es` | Interface language. |
| `DEMIURGOS_API_PORT` / `DEMIURGOS_GATEWAY_PORT` | `8000` / `8642` | Change them if a port is taken. |
| `DEMIURGOS_AUTH_MODE` | `local-dev` | `local-dev` (local session) or `credentials` (password vault). |
| `DEMIURGOS_TEXT_PROVIDER/ENDPOINT/MODEL` | opencode-go | Assistant provider. |
| `DEMIURGOS_DATA_ROOT` | `Documents/Demiurgos` | Data folder (does not write the pointer; use `--data-root` to make it permanent). |

The full reference is in [`.env.example`](.env.example). Demiurgos runs as a local application on `127.0.0.1`; remote/VPS deployment is outside the MVP scope.

---

## For developers

The one-command install is the supported path for users. To work on the code:

```bash
git clone https://github.com/maar1223/Demiurgos.git
cd Demiurgos
python3 -m venv .venv
.venv/bin/pip install -r src/tools/demiurgos-suite/requirements.txt
cd frontend && npm install && cd ..
./scripts/start-demiurgos.sh start
```

Tests: `pytest src/tools/demiurgos-suite/wiki/tests/` and `cd frontend && npm test`. The technical stack, product decisions and architecture live in [`docs/`](docs/), and the detailed install guide is [`docs/install/ONE_SCREEN_GUIDE.md`](docs/install/ONE_SCREEN_GUIDE.md).

---

## Status and license

- **Proprietary freeware:** the Core is free; workshops are an optional one-time purchase.
- The installed version is never blocked: an expired update window never degrades what you already have.
- Worlds are private: the content of `mundos/` is outside the repository and is never published.
- Built by [@maar1223](https://github.com/maar1223).
- Versión en español: [README.md](README.md)

*"Assume nothing. If in doubt, look for the context in the project."*
