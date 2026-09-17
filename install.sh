#!/usr/bin/env bash
# ============================================================
# Demiurgos — Preparación del entorno de desarrollo CLI
# Instala el stack CLI de desarrollo: Hermes Agent, Engram
# (memoria persistente) y las skills narrativas de Demiurgos.
# NO instala la plataforma web: la instalación oficial
# (Docker, Windows, Linux) está EN DESARROLLO y aún no está
# disponible. La app web se arranca desde el repositorio con
# los launchers (scripts/start-demiurgos-linux.sh, start-demiurgos.ps1).
# También prepara el entorno Python del checkout (.venv) y crea el puntero
# inicial del data-root, para que los procesos iniciados fuera de un launcher
# puedan resolver la carpeta de datos de autor (ver
# src/tools/demiurgos-suite/wiki/data_root.py).
# ============================================================
set -euo pipefail

# ── Colores ───────────────────────────────────────────────
BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m' # Sin color

# ── Rutas ─────────────────────────────────────────────────
DEMIURGOS_HOME="${DEMIURGOS_HOME:-$HOME/.demiurgos}"
DEMIURGOS_REPO="https://github.com/maar1223/Demiurgos.git"
ENGRAM_VERSION="1.17.0"
ENGRAM_REPO="Gentleman-Programming/engram"
HERMES_INSTALL_URL="https://hermes-agent.nousresearch.com/install.sh"
HERMES_CONFIG="$HOME/.hermes/config.yaml"

# Rutas relativas al checkout que usan las etapas de entorno Python y data-root.
REQUIREMENTS_REL="src/tools/demiurgos-suite/requirements.txt"
WIKI_REL="src/tools/demiurgos-suite/wiki"

# ── Utilidades ────────────────────────────────────────────
header()  { echo -e "\n${CYAN}${BOLD}╔══════════════════════════════════════╗${NC}"; echo -e "${CYAN}${BOLD}║${NC}  $1"; echo -e "${CYAN}${BOLD}╚══════════════════════════════════════╝${NC}\n"; }
step()    { echo -e "${YELLOW}→${NC} $1"; }
ok()      { echo -e "  ${GREEN}✓${NC} $1"; }
warn()    { echo -e "  ${YELLOW}⚠${NC} $1"; }
fail()    { echo -e "  ${RED}✗${NC} $1"; exit 1; }
ask()     { echo -ne "${CYAN}?${NC} $1 "; }

# Raíz del checkout que contiene el entorno Python y el data-root.
# Gana el propio directorio del script cuando parece el repositorio de Demiurgos;
# en caso contrario se usa el clon creado por install_demiurgos.
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

# ── Etapa 1: Requisitos previos ───────────────────────────
check_prerequisites() {
    header "Demiurgos — Preparación del entorno CLI de desarrollo"
    
    # Detectar el sistema operativo
    case "$(uname -s)" in
        Linux)  OS="linux";;
        Darwin) OS="darwin";;
        *)      fail "Sistema operativo no soportado: $(uname -s). Se requiere Linux o macOS.";;
    esac
    
    # Detectar la arquitectura
    case "$(uname -m)" in
        x86_64)  ARCH="amd64";;
        aarch64|arm64) ARCH="arm64";;
        *)       fail "Arquitectura no soportada: $(uname -m)";;
    esac
    
    ok "Sistema detectado: $OS/$ARCH"
    
    # Verificar las herramientas requeridas
    for cmd in curl git; do
        if ! command -v "$cmd" &>/dev/null; then
            fail "'$cmd' no está instalado. Instálalo primero (apt install $cmd / brew install $cmd)."
        fi
    done
    ok "Herramientas base: curl, git disponibles"
}

# ── Etapa 2: Instalar Hermes Agent ────────────────────────
install_hermes() {
    step "Instalando Hermes Agent..."
    
    if command -v hermes &>/dev/null; then
        ok "Hermes Agent ya instalado ($(hermes --version 2>/dev/null || echo 'versión desconocida'))"
        return 0
    fi
    
    curl -fsSL "$HERMES_INSTALL_URL" | bash || fail "No se pudo instalar Hermes Agent."
    
    # Asegurar que hermes esté en el PATH
    if ! command -v hermes &>/dev/null; then
        export PATH="$HOME/.hermes/bin:$PATH"
        if ! command -v hermes &>/dev/null; then
            fail "Hermes Agent se instaló pero no está en el PATH. Reinicia la terminal o ejecuta: export PATH=\$HOME/.hermes/bin:\$PATH"
        fi
    fi
    
    ok "Hermes Agent instalado"
}

# ── Etapa 3: Instalar Engram ──────────────────────────────
install_engram() {
    step "Instalando Engram (memoria persistente)..."
    
    local engram_bin="$DEMIURGOS_HOME/bin/engram"
    
    if [ -f "$engram_bin" ]; then
        ok "Engram ya instalado en $engram_bin"
        export PATH="$DEMIURGOS_HOME/bin:$PATH"
        return 0
    fi
    
    # Intentar primero la instalación global
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

# ── Etapa 4: Configurar Engram MCP en Hermes ──────────────
configure_engram() {
    step "Conectando Engram a Hermes..."
    
    local engram_path="${1:-$DEMIURGOS_HOME/bin/engram}"
    
    # Verificar si ya está configurado
    if [ -f "$HERMES_CONFIG" ] && grep -q "engram" "$HERMES_CONFIG" 2>/dev/null; then
        ok "Engram ya configurado en Hermes"
        return 0
    fi
    
    # Intentar primero con la CLI de hermes
    if command -v hermes &>/dev/null; then
        hermes mcp add engram --command "$engram_path" --args mcp --args --tools=agent 2>/dev/null && {
            ok "Engram conectado a Hermes (vía CLI)"
            return 0
        }
    fi
    
    # Alternativa: inyectar en config.yaml
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

# ── Etapa 5: Instalar las skills de Demiurgos ─────────────
install_demiurgos() {
    step "Instalando Demiurgos skills..."
    
    if [ -d "$DEMIURGOS_HOME/repo" ]; then
        ok "Demiurgos ya instalado en $DEMIURGOS_HOME/repo"
    else
        git clone --depth 1 "$DEMIURGOS_REPO" "$DEMIURGOS_HOME/repo" 2>/dev/null || \
            fail "No se pudo clonar Demiurgos. Verifica tu conexión a GitHub."
        ok "Demiurgos clonado"
    fi
    
    # Agregar las skills a los directorios externos de Hermes
    local skills_path="$DEMIURGOS_HOME/repo/skills"
    
    if [ -f "$HERMES_CONFIG" ] && grep -q "$skills_path" "$HERMES_CONFIG" 2>/dev/null; then
        ok "Skills ya registradas en Hermes"
        return 0
    fi
    
    # Inyectar external_dirs en el config.yaml de Hermes
    if grep -q "external_dirs:" "$HERMES_CONFIG" 2>/dev/null; then
        if ! grep -q "$skills_path" "$HERMES_CONFIG" 2>/dev/null; then
            # Agregar la ruta bajo la lista external_dirs existente
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

# ── Etapa 5.5: Configurar el perfil demiurgos-mcp ─────────
configure_mcp_profile() {
    step "Configurando perfil demiurgos-mcp (MCP serve)..."
    
    if hermes profile list 2>/dev/null | grep -q "demiurgos-mcp"; then
        ok "Perfil demiurgos-mcp ya existe"
        return 0
    fi
    
    # Crear el perfil clonando los valores por defecto (o desde demiurgos-core si está disponible)
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
    
    # Asegurar que los toolsets sean correctos para MCP serve
    local profile_config="$HOME/.hermes/profiles/demiurgos-mcp/config.yaml"
    if [ -f "$profile_config" ]; then
        # Agregar terminal, skills y mcp a los toolsets si faltan
        for toolset in terminal skills mcp; do
            if ! grep -q "  - $toolset" "$profile_config" 2>/dev/null; then
                sed -i "/^toolsets:/a\\  - $toolset" "$profile_config" 2>/dev/null || true
            fi
        done
        ok "Toolsets del perfil actualizados (file, terminal, clarify, skills, mcp)"
    fi
}

# ── Etapa 6: Entorno Python + dependencias ────────────────
# Los launchers ejecutan la API con "$PROJECT_ROOT/.venv/bin/python", así que
# el checkout necesita su propio entorno virtual. Todo aquí es de mejor esfuerzo:
# un intérprete ausente avisa y retorna en vez de abortar el instalador.
prepare_python_env() {
    step "Preparando el entorno Python del checkout..."

    local root requirements venv_python
    root="$(checkout_root)"
    requirements="$root/$REQUIREMENTS_REL"
    venv_python="$root/.venv/bin/python"

    if ! command -v python3 &>/dev/null; then
        warn "No se encontró python3 en el PATH. Se omiten el entorno virtual y las dependencias de Python."
        warn "Instala Python 3.11+ (por ejemplo: apt install python3 python3-venv) y vuelve a ejecutar este script."
        warn "Sin él los launchers no pueden arrancar: esperan $venv_python."
        return 0
    fi

    if [ ! -f "$requirements" ]; then
        warn "No se encontró el archivo de requisitos: $requirements. Se omiten las dependencias de Python."
        warn "Ejecuta este script desde la raíz del checkout de Demiurgos para instalarlas."
        return 0
    fi

    # Idempotente: un entorno existente se reutiliza tal cual, nunca se recrea,
    # así que volver a ejecutar el instalador no puede romper un venv que funciona.
    if [ -x "$venv_python" ]; then
        ok "El entorno virtual ya existe: $root/.venv"
    elif ! python3 -m venv "$root/.venv"; then
        warn "No se pudo crear el entorno virtual en $root/.venv (¿está instalado python3-venv?)."
        warn "Instálalo y vuelve a ejecutar este script. El resto de los pasos de instalación no se ven afectados."
        return 0
    else
        ok "Entorno virtual creado: $root/.venv"
    fi

    if "$venv_python" -m pip install -r "$requirements"; then
        ok "Dependencias de Python instaladas"
    else
        warn "Falló pip install. El resto de los pasos de instalación no se ven afectados."
        warn "Reintenta manualmente con: $venv_python -m pip install -r $requirements"
        return 0
    fi
}

# ── Etapa 7: Creación del puntero del data-root ───────────
# Los launchers exportan DEMIURGOS_DATA_ROOT, pero un proceso iniciado a mano
# (hermes, cron, una API arrancada directamente) no tiene launcher y resuelve el
# data-root a partir del puntero inicial escrito aquí. El propio write_pointer()
# del proyecto define tanto el esquema del registro como su ubicación, así que es
# la única fuente de verdad; el registro se relee para demostrar que el resolver lo acepta.
configure_data_root() {
    step "Configurando el puntero del data-root..."

    local root wiki_dir venv_python
    root="$(checkout_root)"
    wiki_dir="$root/$WIKI_REL"
    venv_python="$root/.venv/bin/python"

    if [ ! -x "$venv_python" ]; then
        warn "No hay un intérprete utilizable en $venv_python. Se omite el puntero del data-root."
        warn "Los procesos iniciados fuera de un launcher resuelven el data-root solo a partir de ese puntero."
        return 0
    fi

    if [ ! -f "$wiki_dir/data_root.py" ]; then
        warn "No se encontró el módulo del resolver en $wiki_dir/data_root.py. Se omite el puntero del data-root."
        return 0
    fi

    local status=0 detail
    detail="$("$venv_python" - "$wiki_dir" "$root" <<'PY'
import sys
from pathlib import Path

# Importar el resolver propio del proyecto: una única fuente de verdad para la
# ruta del puntero (platformdirs.user_config_dir("demiurgos")) y el esquema del registro.
sys.path.insert(0, sys.argv[1])
from data_root import pointer_path, read_pointer, write_pointer

checkout = Path(sys.argv[2]).resolve()
existing = read_pointer()

# Solo bootstrap: nunca se reorienta en silencio un data-root que el usuario ya eligió.
if existing is not None and existing != checkout:
    print(
        f"el data-root ya está configurado en {existing}; se deja intacto "
        f"(solo bootstrap). Reoriéntalo editando {pointer_path()}."
    )
    raise SystemExit(3)

write_pointer(checkout)

# Releer el archivo para que el instalador demuestre que el resolver acepta el registro.
recorded = read_pointer()
if recorded != checkout:
    raise SystemExit(f"discrepancia al releer: se escribió {checkout} pero se leyó {recorded}")
print(pointer_path())
PY
)" || status=$?

    case "$status" in
        0)
            ok "Puntero del data-root escrito y verificado: $detail"
            ok "Data-root: $root"
            ;;
        3)
            warn "$detail"
            ;;
        *)
            warn "No se pudo escribir el puntero del data-root mediante write_pointer() del resolver."
            warn "Los procesos iniciados fuera de un launcher no resolverán un data-root hasta que se escriba."
            ;;
    esac
}

# ── Principal ──────────────────────────────────────────────
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
