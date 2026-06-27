#!/usr/bin/env bash
# Demiurgos — Copy universal narrative catalogs to a world
# Usage: ./copiar-arquetipos.sh <world-name> [--force]
#   --force: overwrite conflicting files with the source version
set -euo pipefail

WORLD_NAME="${1:-}"
FORCE=false
[[ "${2:-}" == "--force" ]] && FORCE=true

if [[ -z "$WORLD_NAME" ]]; then
    echo "Usage: copiar-arquetipos.sh <world-name> [--force]"
    echo "  world-name: name of the world under mundos/"
    echo "  --force:    overwrite conflicting files"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SOURCE_DIR="$PROJECT_ROOT/mundos/Arquetipos"
TARGET_DIR="$PROJECT_ROOT/mundos/$WORLD_NAME/Arquetipos"

# Catalogs to copy (13 files)
FILES=(
    "01_Arquetipos_Historias_Snyder.md"
    "02_Arquetipos_Personalidad.md"
    "03_Alineamientos_Morales.md"
    "04_Tipos_de_Trama.md"
    "05_Tipos_de_Conflicto.md"
    "06_Dinamicas_de_Grupo.md"
    "07_Beat_Sheet_Snyder.md"
    "09_Dilemas_Filosoficos.md"
    "10_Temas_de_la_Ficcion.md"
    "11_Profesiones_y_Roles.md"
    "12_Locaciones_de_Fantasia.md"
    "13_Miedos_Arquetipicos.md"
    "14_Creacion_de_Villanos.md"
)

PRESERVED=("00_Eneagrama_Stal.md" "08_Escenarios_Adaptados.md")

# ── Preconditions ──────────────────────────────────────
echo ":: Verificando directorio origen..."
if [[ ! -d "$SOURCE_DIR" ]]; then
    echo "  ERROR: No se encuentra el directorio origen: $SOURCE_DIR"
    echo "  El directorio mundos/Arquetipos/ debe existir con los catálogos."
    exit 1
fi
echo "   OK  Origen: $SOURCE_DIR"

echo ":: Verificando directorio destino..."
if [[ ! -d "$TARGET_DIR" ]]; then
    echo "  WARN Destino no existe. Creando: $TARGET_DIR"
    mkdir -p "$TARGET_DIR"
    echo "   OK  Directorio destino creado."
else
    echo "   OK  Destino: $TARGET_DIR"
fi

# ── Copy with hash verification ────────────────────────
echo ":: Copiando ${#FILES[@]} catálogos..."
COPIED=0
EXISTING=0
CONFLICTS=0
ERRORS=0

for file in "${FILES[@]}"; do
    src="$SOURCE_DIR/$file"
    dst="$TARGET_DIR/$file"

    if [[ ! -f "$src" ]]; then
        echo "  ERROR Falta archivo origen: $src"
        ((ERRORS++))
        continue
    fi

    if [[ -f "$dst" ]]; then
        if cmp -s "$src" "$dst"; then
            ((EXISTING++))
            echo "  SKIP Idéntico: $file"
            continue
        fi

        if $FORCE; then
            cp "$src" "$dst"
            ((COPIED++))
            echo "  WARN Sobrescrito (--force): $file"
        else
            ((CONFLICTS++))
            echo "  WARN Conflicto: $file — el destino difiere del origen"
            echo "        Usa --force para sobrescribir con la versión origen."
        fi
    else
        cp "$src" "$dst"
        ((COPIED++))
        echo "   OK  Copiado: $file"
    fi
done

# ── Post-copy validation ───────────────────────────────
echo ":: Validando integridad..."
FAILS=0

for file in "${FILES[@]}"; do
    dst="$TARGET_DIR/$file"
    if [[ ! -f "$dst" ]]; then
        echo "  WARN Falta en destino: $file (puede ser un conflicto no resuelto)"
        ((FAILS++))
        continue
    fi
    if ! cmp -s "$SOURCE_DIR/$file" "$dst"; then
        echo "  WARN Contenido difiere: $file"
        ((FAILS++))
    fi
done

if [[ $FAILS -eq 0 ]]; then
    echo "   OK  Los ${#FILES[@]} archivos copiados son idénticos a sus originales."
fi

# ── Check preserved files ──────────────────────────────
echo ":: Verificando preservación de archivos existentes..."
for file in "${PRESERVED[@]}"; do
    if [[ -f "$TARGET_DIR/$file" ]]; then
        echo "   OK  Preservado: $file"
    else
        echo "  WARN Falta archivo que debía preservarse: $file"
    fi
done

# ── Report ─────────────────────────────────────────────
TOTAL_MD=$(find "$TARGET_DIR" -maxdepth 1 -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
EXPECTED=15

echo ""
echo "============================================"
echo "         COPIA DE ARQUETIPOS — REPORTE"
echo "============================================"
echo ""
echo "  Copiados      : $COPIED"
echo "  Ya existentes : $EXISTING"
echo "  Conflictos    : $CONFLICTS"
echo "  Errores       : $ERRORS"
echo "  Total .md     : $TOTAL_MD / $EXPECTED esperados"
echo ""
if [[ $CONFLICTS -gt 0 && "$FORCE" != "true" ]]; then
    echo "  NOTA: Hay $CONFLICTS archivo(s) en conflicto."
    echo "  Ejecuta con --force para sobrescribirlos."
fi
echo "============================================"

[[ $ERRORS -gt 0 ]] && exit 1
exit 0
