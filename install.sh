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

# ── Stage 6: Main Menu ────────────────────────────────────
main_menu() {
    header "Demiurgos listo"
    
    ok "Hermes Agent operativo"
    ok "Engram conectado (memoria persistente)"
    ok "Demiurgos skills cargadas (13 fases narrativas)"
    
    echo ""
    echo -e "${BOLD}¿Qué querés hacer?${NC}"
    echo "  [1] Crear un mundo nuevo (empezar desde cero)"
    echo "  [2] Cargar un mundo existente (ya tenés archivos de lore)"
    echo ""
    
    local choice
    while true; do
        ask "Opción [1/2]:"
        read -r choice
        case "$choice" in
            1) create_new_world; break;;
            2) load_existing_world; break;;
            *) warn "Elegí 1 o 2";;
        esac
    done
}

# ── Language Selection ──────────────────────────────────
select_language() {
    echo ""
    echo -e "${BOLD}¿En qué idioma querés trabajar?${NC}"
    echo "  [1]  English"
    echo "  [2]  中文 (Chinese · 简体中文)"
    echo "  [3]  हिन्दी (Hindi)"
    echo "  [4]  Español (neutro)"
    echo "  [5]  Español (rioplatense · voseo)"
    echo "  [6]  Français"
    echo "  [7]  العربية (Arabic)"
    echo "  [8]  বাংলা (Bengali)"
    echo "  [9]  Português"
    echo "  [10] Русский (Russian)"
    echo "  [11] اردو (Urdu)"
    echo ""
    
    local choice
    while true; do
        ask "Idioma [1-11]:"
        read -r choice
        case "$choice" in
            1)  DEMIURGOS_LANG="en";   LANG_NAME="English"; break;;
            2)  DEMIURGOS_LANG="zh";   LANG_NAME="中文 (Chinese)"; break;;
            3)  DEMIURGOS_LANG="hi";   LANG_NAME="हिन्दी (Hindi)"; break;;
            4)  DEMIURGOS_LANG="es";   LANG_NAME="Español (neutro)"; break;;
            5)  DEMIURGOS_LANG="es-ar"; LANG_NAME="Español (rioplatense)"; break;;
            6)  DEMIURGOS_LANG="fr";   LANG_NAME="Français"; break;;
            7)  DEMIURGOS_LANG="ar";   LANG_NAME="العربية (Arabic)"; break;;
            8)  DEMIURGOS_LANG="bn";   LANG_NAME="বাংলা (Bengali)"; break;;
            9)  DEMIURGOS_LANG="pt";   LANG_NAME="Português"; break;;
            10) DEMIURGOS_LANG="ru";   LANG_NAME="Русский (Russian)"; break;;
            11) DEMIURGOS_LANG="ur";   LANG_NAME="اردو (Urdu)"; break;;
            *) warn "Elegí un número del 1 al 11";;
        esac
    done
    
    ok "Idioma: $LANG_NAME"
    echo "$DEMIURGOS_LANG"
}

# ── Flow 1: Create New World ──────────────────────────────
create_new_world() {
    header "Crear mundo nuevo"
    
    # Ask world name
    local world_name
    while true; do
        ask "¿Nombre de tu mundo? (ej: thalassia):"
        read -r world_name
        if [ -n "$world_name" ]; then
            break
        fi
    done
    
    # Sanitize name (lowercase, no spaces)
    world_name=$(echo "$world_name" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
    
    # Select language
    DEMIURGOS_LANG=$(select_language)
    
    local world_dir="$HOME/demiurgos/$world_name"
    
    if [ -d "$world_dir" ]; then
        fail "El directorio $world_dir ya existe. Elegí otro nombre o usá [2] para cargar un mundo existente."
    fi
    
    # Create structure
    mkdir -p "$world_dir/mundos/$world_name"/{Lore,Personajes,sagas,Ideas}
    ok "Estructura creada en $world_dir"
    
    # Copy AGENTS.md (orchestrator)
    cp "$DEMIURGOS_HOME/repo/AGENTS.md" "$world_dir/AGENTS.md"
    ok "Orquestador copiado (AGENTS.md)"
    
    # Create .env
    cat > "$world_dir/.env" <<EOF
# Demiurgos — Configuración de mundo
DEMIURGOS_WORLD=$world_name
DEMIURGOS_LANGUAGE=$DEMIURGOS_LANG
EOF
    ok ".env configurado (DEMIURGOS_WORLD=$world_name, idioma=$DEMIURGOS_LANG)"
    
    # Create .gitignore
    cat > "$world_dir/.gitignore" <<EOF
.env
.demiurgos-estado.*
EOF
    
    # Create initial .demiurgos-estado.json
    cat > "$world_dir/.demiurgos-estado.json" <<EOF
{
  "version": 1,
  "mundo_activo": "$world_name",
  "last_session": "",
  "arcos": {},
  "sesiones": []
}
EOF
    ok "Estado inicial creado"
    
    # Offer catalogs
    echo ""
    ask "¿Copiar catálogos narrativos universales? (Snyder, arquetipos, tramas) [S/n]:"
    read -r copy_catalogs
    if [ "$copy_catalogs" != "n" ] && [ "$copy_catalogs" != "N" ]; then
        local catalogs_source="$DEMIURGOS_HOME/repo/mundos/Arquetipos"
        local catalogs_target="$world_dir/mundos/$world_name/Arquetipos"
        mkdir -p "$catalogs_target"
        cp "$catalogs_source"/* "$catalogs_target/" 2>/dev/null || true
        ok "Catálogos copiados (Snyder beats, arquetipos, tramas, conflictos)"
    fi
    
    # Done
    echo ""
    header "✅ $world_name listo"
    echo ""
    echo -e "  Para empezar a crear:"
    echo -e "    ${BOLD}cd $world_dir${NC}"
    echo -e "    ${BOLD}hermes${NC}"
    echo ""
    echo -e "  Después decí ${BOLD}\"arranquemos\"${NC} o ${BOLD}\"crear un personaje\"${NC}"
    echo ""
}

# ── Flow 2: Load Existing World ───────────────────────────
load_existing_world() {
    header "Cargar mundo existente"
    
    # Ask for directory
    local source_dir
    while true; do
        ask "📂 Ruta de tu mundo (arrastrá la carpeta o escribí la ruta):"
        read -r source_dir
        
        # Expand ~
        source_dir="${source_dir/#\~/$HOME}"
        
        if [ -d "$source_dir" ]; then
            break
        fi
        warn "Directorio no encontrado: $source_dir"
    done
    
    ok "Directorio: $source_dir"
    
    # Detect world name from directory name
    local world_name
    world_name=$(basename "$source_dir")
    
    # Count files
    step "Escaneando archivos de lore..."
    local md_count img_count docx_count
    md_count=$(find "$source_dir" -name "*.md" -type f 2>/dev/null | wc -l | tr -d ' ')
    img_count=$(find "$source_dir" -name "*.jpg" -o -name "*.png" -o -name "*.webp" 2>/dev/null | wc -l | tr -d ' ')
    docx_count=$(find "$source_dir" -name "*.docx" -type f 2>/dev/null | wc -l | tr -d ' ')
    
    ok "$md_count archivos .md encontrados"
    [ "$img_count" -gt 0 ] && ok "$img_count imágenes detectadas"
    [ "$docx_count" -gt 0 ] && ok "$docx_count documentos .docx"
    
    # Run sync-lore if available
    local sync_lore="$DEMIURGOS_HOME/repo/src/tools/sync-lore"
    if [ -f "$sync_lore/__main__.py" ] && command -v python3 &>/dev/null; then
        step "Indexando con sync-lore..."
        python3 "$sync_lore" --world "$source_dir" --output "$source_dir/.demiurgos-index" 2>/dev/null && {
            ok "Contenido indexado y categorizado"
            ok "Índice persistido en Engram"
        } || warn "sync-lore no pudo ejecutarse (requiere dependencias Python). Podés indexar después manualmente."
    else
        warn "sync-lore no disponible (Python 3 requerido). El mundo se cargará sin indexación automática."
    fi
    
    # Ensure AGENTS.md exists
    if [ ! -f "$source_dir/AGENTS.md" ]; then
        cp "$DEMIURGOS_HOME/repo/AGENTS.md" "$source_dir/AGENTS.md"
        ok "AGENTS.md copiado (orquestador)"
    fi
    
    # Ensure .env has DEMIURGOS_WORLD
    if [ -f "$source_dir/.env" ]; then
        if ! grep -q "DEMIURGOS_WORLD" "$source_dir/.env" 2>/dev/null; then
            echo "DEMIURGOS_WORLD=$world_name" >> "$source_dir/.env"
            ok "DEMIURGOS_WORLD=$world_name agregado a .env"
        fi
    else
        cat > "$source_dir/.env" <<EOF
DEMIURGOS_WORLD=$world_name
EOF
        ok ".env creado (DEMIURGOS_WORLD=$world_name)"
    fi
    
    # Done
    echo ""
    header "✅ $world_name listo"
    echo ""
    echo -e "  Para empezar a trabajar:"
    echo -e "    ${BOLD}cd $source_dir${NC}"
    echo -e "    ${BOLD}hermes${NC}"
    echo ""
    echo -e "  Decí ${BOLD}\"¿en qué estábamos?\"${NC} para recuperar el estado anterior."
    echo ""
}

# ── Main ───────────────────────────────────────────────────
main() {
    check_prerequisites
    install_hermes
    install_engram
    configure_engram "$DEMIURGOS_HOME/bin/engram"
    install_demiurgos
    main_menu
}

main "$@"
