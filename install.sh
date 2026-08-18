#!/usr/bin/env bash
# ============================================================
# Demiurgos — One-Command Installer
# Usage: curl -fsSL https://get.demiurgos.dev | bash
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

# ── Helpers ───────────────────────────────────────────────
header()  { echo -e "\n${CYAN}${BOLD}╔══════════════════════════════════════╗${NC}"; echo -e "${CYAN}${BOLD}║${NC}  $1"; echo -e "${CYAN}${BOLD}╚══════════════════════════════════════╝${NC}\n"; }
step()    { echo -e "${YELLOW}→${NC} $1"; }
ok()      { echo -e "  ${GREEN}✓${NC} $1"; }
warn()    { echo -e "  ${YELLOW}⚠${NC} $1"; }
fail()    { echo -e "  ${RED}✗${NC} $1"; exit 1; }
ask()     { echo -ne "${CYAN}?${NC} $1 "; }

# ── Stage 1: Prerequisites ────────────────────────────────
check_prerequisites() {
    header "Demiurgos — Instalador"
    
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
            fail "'$cmd' no está instalado. Instalalo primero (apt install $cmd / brew install $cmd)."
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
            fail "Hermes Agent se instaló pero no está en el PATH. Reiniciá la terminal o ejecutá: export PATH=\$HOME/.hermes/bin:\$PATH"
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
    
    curl -fsSL "$download_url" -o "$engram_bin" || fail "No se pudo descargar Engram. Verificá tu conexión."
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
            fail "No se pudo clonar Demiurgos. Verificá tu conexión a GitHub."
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
            warn "No se pudo crear el perfil demiurgos-mcp. Creálo manualmente con: hermes profile create demiurgos-mcp"
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

# ── Main ───────────────────────────────────────────────────
main() {
    check_prerequisites
    install_hermes
    install_engram
    configure_engram "$DEMIURGOS_HOME/bin/engram"
    install_demiurgos
    configure_mcp_profile
}

main "$@"
