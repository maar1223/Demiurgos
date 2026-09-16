#!/usr/bin/env bash
# ============================================================
# Demiurgos — Preparación del entorno de desarrollo CLI
# Instala el stack CLI de desarrollo: Hermes Agent, Engram
# (memoria persistente) y las skills narrativas de Demiurgos.
# NO instala la plataforma web: la instalación oficial
# (Docker, Windows, Linux) está EN DESARROLLO y aún no está
# disponible. La app web se arranca desde el repositorio con
# los launchers (scripts/start-demiurgos-linux.sh, start-demiurgos.ps1).
# Also prepares the checkout Python environment (.venv) and bootstraps the
# data-root pointer, so processes started outside a launcher can resolve the
# author-data folder (see src/tools/demiurgos-suite/wiki/data_root.py).
# ============================================================
set -euo pipefail

# ── Colors ────────────────────────────────────────────────
BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# ── Paths ─────────────────────────────────────────────────
DEMIURGOS_HOME="${DEMIURGOS_HOME:-$HOME/.demiurgos}"
DEMIURGOS_REPO="https://github.com/maar1223/Demiurgos.git"
ENGRAM_VERSION="1.17.0"
ENGRAM_REPO="Gentleman-Programming/engram"
HERMES_INSTALL_URL="https://hermes-agent.nousresearch.com/install.sh"
HERMES_CONFIG="$HOME/.hermes/config.yaml"

# Checkout-relative paths used by the Python environment and data-root stages.
REQUIREMENTS_REL="src/tools/demiurgos-suite/requirements.txt"
WIKI_REL="src/tools/demiurgos-suite/wiki"

# ── Helpers ───────────────────────────────────────────────
header()  { echo -e "\n${CYAN}${BOLD}╔══════════════════════════════════════╗${NC}"; echo -e "${CYAN}${BOLD}║${NC}  $1"; echo -e "${CYAN}${BOLD}╚══════════════════════════════════════╝${NC}\n"; }
step()    { echo -e "${YELLOW}→${NC} $1"; }
ok()      { echo -e "  ${GREEN}✓${NC} $1"; }
warn()    { echo -e "  ${YELLOW}⚠${NC} $1"; }
fail()    { echo -e "  ${RED}✗${NC} $1"; exit 1; }
ask()     { echo -ne "${CYAN}?${NC} $1 "; }

# Root of the checkout that owns the Python environment and the data root.
# The script's own directory wins when it looks like the Demiurgos repo;
# otherwise fall back to the clone performed by install_demiurgos.
checkout_root() {
    local here
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ -f "$here/$REQUIREMENTS_REL" ]; then
        printf '%s' "$here"
    elif [ -f "$DEMIURGOS_HOME/repo/$REQUIREMENTS_REL" ]; then
        printf '%s' "$DEMIURGOS_HOME/repo"
    else
        printf '%s' "$here"
    fi
}

# ── Stage 1: Prerequisites ────────────────────────────────
check_prerequisites() {
    header "Demiurgos — Preparación del entorno CLI de desarrollo"
    
    # Detect OS
    case "$(uname -s)" in
        Linux)  OS="linux";;
        Darwin) OS="darwin";;
        *)      fail "Sistema operativo no soportado: $(uname -s). Se requiere Linux o macOS.";;
    esac
    
    # Detect architecture
    case "$(uname -m)" in
        x86_64)  ARCH="amd64";;
        aarch64|arm64) ARCH="arm64";;
        *)       fail "Arquitectura no soportada: $(uname -m)";;
    esac
    
    ok "Sistema detectado: $OS/$ARCH"
    
    # Check required tools
    for cmd in curl git; do
        if ! command -v "$cmd" &>/dev/null; then
            fail "'$cmd' no está instalado. Instálalo primero (apt install $cmd / brew install $cmd)."
        fi
    done
    ok "Herramientas base: curl, git disponibles"
}

# ── Stage 2: Install Hermes Agent ─────────────────────────
install_hermes() {
    step "Instalando Hermes Agent..."
    
    if command -v hermes &>/dev/null; then
        ok "Hermes Agent ya instalado ($(hermes --version 2>/dev/null || echo 'versión desconocida'))"
        return 0
    fi
    
    curl -fsSL "$HERMES_INSTALL_URL" | bash || fail "No se pudo instalar Hermes Agent."
    
    # Ensure hermes is in PATH
    if ! command -v hermes &>/dev/null; then
        export PATH="$HOME/.hermes/bin:$PATH"
        if ! command -v hermes &>/dev/null; then
            fail "Hermes Agent se instaló pero no está en el PATH. Reinicia la terminal o ejecuta: export PATH=\$HOME/.hermes/bin:\$PATH"
        fi
    fi
    
    ok "Hermes Agent instalado"
}

# ── Stage 3: Install Engram ───────────────────────────────
install_engram() {
    step "Instalando Engram (memoria persistente)..."
    
    local engram_bin="$DEMIURGOS_HOME/bin/engram"
    
    if [ -f "$engram_bin" ]; then
        ok "Engram ya instalado en $engram_bin"
        export PATH="$DEMIURGOS_HOME/bin:$PATH"
        return 0
    fi
    
    # Try global install first
    if command -v engram &>/dev/null; then
        ok "Engram encontrado en PATH ($(command -v engram))"
        return 0
    fi
    
    mkdir -p "$DEMIURGOS_HOME/bin"
    
    local download_url="https://github.com/$ENGRAM_REPO/releases/download/v$ENGRAM_VERSION/engram-${OS}-${ARCH}"
    if [ "$OS" = "windows" ]; then
        download_url="${download_url}.exe"
    fi
    
    curl -fsSL "$download_url" -o "$engram_bin" || fail "No se pudo descargar Engram. Verifica tu conexión."
    chmod +x "$engram_bin"
    
    export PATH="$DEMIURGOS_HOME/bin:$PATH"
    ok "Engram $ENGRAM_VERSION instalado"
}

# ── Stage 4: Configure Engram MCP in Hermes ───────────────
configure_engram() {
    step "Conectando Engram a Hermes..."
    
    local engram_path="${1:-$DEMIURGOS_HOME/bin/engram}"
    
    # Check if already configured
    if [ -f "$HERMES_CONFIG" ] && grep -q "engram" "$HERMES_CONFIG" 2>/dev/null; then
        ok "Engram ya configurado en Hermes"
        return 0
    fi
    
    # Try hermes CLI first
    if command -v hermes &>/dev/null; then
        hermes mcp add engram --command "$engram_path" --args mcp --args --tools=agent 2>/dev/null && {
            ok "Engram conectado a Hermes (vía CLI)"
            return 0
        }
    fi
    
    # Fallback: inject into config.yaml
    if [ ! -f "$HERMES_CONFIG" ]; then
        mkdir -p "$(dirname "$HERMES_CONFIG")"
        echo "---" > "$HERMES_CONFIG"
    fi
    
# Inyectar bloque MCP en config.yaml (sin sobrescribir mcp: existente)
if grep -q "^mcp:" "$HERMES_CONFIG" 2>/dev/null; then
    # mcp: ya existe — agregar engram debajo
    if ! grep -q "engram:" "$HERMES_CONFIG" 2>/dev/null; then
        cat >> "$HERMES_CONFIG" <<EOF
  engram:
    type: stdio
    command: $engram_path
    args: ["mcp", "--tools=agent"]
EOF
    fi
else
    # mcp: no existe — agregar todo el bloque
    cat >> "$HERMES_CONFIG" <<EOF

mcp:
  engram:
    type: stdio
    command: $engram_path
    args: ["mcp", "--tools=agent"]
EOF
fi

    
    ok "Engram conectado a Hermes"
}

# ── Stage 5: Install Demiurgos Skills ─────────────────────
install_demiurgos() {
    step "Instalando Demiurgos skills..."
    
    if [ -d "$DEMIURGOS_HOME/repo" ]; then
        ok "Demiurgos ya instalado en $DEMIURGOS_HOME/repo"
    else
        git clone --depth 1 "$DEMIURGOS_REPO" "$DEMIURGOS_HOME/repo" 2>/dev/null || \
            fail "No se pudo clonar Demiurgos. Verifica tu conexión a GitHub."
        ok "Demiurgos clonado"
    fi
    
    # Add skills to Hermes external dirs
    local skills_path="$DEMIURGOS_HOME/repo/skills"
    
    if [ -f "$HERMES_CONFIG" ] && grep -q "$skills_path" "$HERMES_CONFIG" 2>/dev/null; then
        ok "Skills ya registradas en Hermes"
        return 0
    fi
    
    # Inject external_dirs into Hermes config.yaml
    if grep -q "external_dirs:" "$HERMES_CONFIG" 2>/dev/null; then
        if ! grep -q "$skills_path" "$HERMES_CONFIG" 2>/dev/null; then
            # Add path under existing external_dirs list
            sed -i "/external_dirs:/a\\    - $skills_path" "$HERMES_CONFIG"
        fi
    else
        cat >> "$HERMES_CONFIG" <<EOF

skills:
  external_dirs:
    - $skills_path
EOF
    fi
    ok "Skills registradas (13 fases narrativas)"
}

# ── Stage 5.5: Configure demiurgos-mcp profile ─────────────
configure_mcp_profile() {
    step "Configurando perfil demiurgos-mcp (MCP serve)..."
    
    if hermes profile list 2>/dev/null | grep -q "demiurgos-mcp"; then
        ok "Perfil demiurgos-mcp ya existe"
        return 0
    fi
    
    # Create profile cloning defaults (or from demiurgos-core if available)
    local clone_source=""
    if hermes profile list 2>/dev/null | grep -q "demiurgos-core"; then
        clone_source="--clone-from demiurgos-core"
    fi
    
    hermes profile create demiurgos-mcp $clone_source \
        --description "Demiurgos MCP serve — narrative agent with file, terminal, clarify, skills, mcp toolsets" \
        --no-alias 2>/dev/null || {
            warn "No se pudo crear el perfil demiurgos-mcp. Créalo manualmente con: hermes profile create demiurgos-mcp"
            return 1
        }
    
    ok "Perfil demiurgos-mcp creado"
    
    # Ensure toolsets are correct for MCP serve
    local profile_config="$HOME/.hermes/profiles/demiurgos-mcp/config.yaml"
    if [ -f "$profile_config" ]; then
        # Add terminal, skills, mcp to toolsets if missing
        for toolset in terminal skills mcp; do
            if ! grep -q "  - $toolset" "$profile_config" 2>/dev/null; then
                sed -i "/^toolsets:/a\\  - $toolset" "$profile_config" 2>/dev/null || true
            fi
        done
        ok "Toolsets del perfil actualizados (file, terminal, clarify, skills, mcp)"
    fi
}

# ── Stage 6: Python environment + dependencies ────────────
# The launchers run the API with "$PROJECT_ROOT/.venv/bin/python", so the
# checkout needs its own virtual environment. Everything here is best-effort:
# a missing interpreter warns and returns instead of aborting the installer.
prepare_python_env() {
    step "Preparing the checkout Python environment..."

    local root requirements venv_python
    root="$(checkout_root)"
    requirements="$root/$REQUIREMENTS_REL"
    venv_python="$root/.venv/bin/python"

    if ! command -v python3 &>/dev/null; then
        warn "python3 was not found on PATH. Skipping the virtual environment and the Python dependencies."
        warn "Install Python 3.11+ (for example: apt install python3 python3-venv) and re-run this script."
        warn "Without it the launchers cannot start: they expect $venv_python."
        return 0
    fi

    if [ ! -f "$requirements" ]; then
        warn "Requirements file not found: $requirements. Skipping the Python dependencies."
        warn "Run this script from the Demiurgos checkout root to install them."
        return 0
    fi

    # Idempotent: an existing environment is reused as-is, never recreated, so
    # re-running the installer cannot break a working venv.
    if [ -x "$venv_python" ]; then
        ok "Virtual environment already present: $root/.venv"
    elif ! python3 -m venv "$root/.venv"; then
        warn "Could not create the virtual environment at $root/.venv (is python3-venv installed?)."
        warn "Install it, then re-run this script. The remaining install steps are unaffected."
        return 0
    else
        ok "Virtual environment created: $root/.venv"
    fi

    if "$venv_python" -m pip install -r "$requirements"; then
        ok "Python dependencies installed"
    else
        warn "pip install failed. The remaining install steps are unaffected."
        warn "Retry manually with: $venv_python -m pip install -r $requirements"
        return 0
    fi
}

# ── Stage 7: Data-root pointer bootstrap ──────────────────
# The launchers export DEMIURGOS_DATA_ROOT, but a process started by hand
# (hermes, cron, a directly started API) has no launcher and resolves the data
# root from the bootstrap pointer written here. The project's own write_pointer()
# owns both the record schema and its location, so it is the single source of
# truth; the record is read back to prove the resolver accepts it.
configure_data_root() {
    step "Configuring the data root pointer..."

    local root wiki_dir venv_python
    root="$(checkout_root)"
    wiki_dir="$root/$WIKI_REL"
    venv_python="$root/.venv/bin/python"

    if [ ! -x "$venv_python" ]; then
        warn "No usable interpreter at $venv_python. Skipping the data-root pointer."
        warn "Processes started outside a launcher resolve the data root from that pointer only."
        return 0
    fi

    if [ ! -f "$wiki_dir/data_root.py" ]; then
        warn "Resolver module not found at $wiki_dir/data_root.py. Skipping the data-root pointer."
        return 0
    fi

    local status=0 detail
    detail="$("$venv_python" - "$wiki_dir" "$root" <<'PY'
import sys
from pathlib import Path

# Import the project's own resolver: one source of truth for the pointer path
# (platformdirs.user_config_dir("demiurgos")) and the record schema.
sys.path.insert(0, sys.argv[1])
from data_root import pointer_path, read_pointer, write_pointer

checkout = Path(sys.argv[2]).resolve()
existing = read_pointer()

# Bootstrap only: never silently repoint a data root the user already chose.
if existing is not None and existing != checkout:
    print(
        f"data root already configured at {existing}; left untouched "
        f"(bootstrap only). Repoint it by editing {pointer_path()}."
    )
    raise SystemExit(3)

write_pointer(checkout)

# Read the file back so the installer proves the resolver accepts the record.
recorded = read_pointer()
if recorded != checkout:
    raise SystemExit(f"read-back mismatch: wrote {checkout} but read {recorded}")
print(pointer_path())
PY
)" || status=$?

    case "$status" in
        0)
            ok "Data root pointer written and verified: $detail"
            ok "Data root: $root"
            ;;
        3)
            warn "$detail"
            ;;
        *)
            warn "Could not write the data-root pointer through the resolver's write_pointer()."
            warn "Processes started outside a launcher will not resolve a data root until it is written."
            ;;
    esac
}

# ── Main ───────────────────────────────────────────────────
main() {
    check_prerequisites
    install_hermes
    install_engram
    configure_engram "$DEMIURGOS_HOME/bin/engram"
    install_demiurgos
    configure_mcp_profile
    prepare_python_env
    configure_data_root
}

main "$@"
