# Demiurgos — Copia de catalogos de Arquetipos Narrativos
# Copia 13 archivos desde mundos/arquetipos-narrativos/ a un mundo destino
# sin sobrescribir archivos existentes que difieran del origen.
#
# Uso: .\scripts\copiar-arquetipos-narrativos.ps1 [-Force]
#   -Force: sobrescribe archivos en conflicto con la version origen

param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# ============================================================
# CONFIGURACION
# ============================================================

$ScriptDir = $PSScriptRoot
$ProjectRoot = Split-Path -Parent $ScriptDir
$SourceDir = Join-Path $ProjectRoot "mundos\arquetipos-narrativos"
$TargetDir = Join-Path $ProjectRoot "mundos\vibrantes\arquetipos-narrativos"

# ============================================================
# FUNCIONES
# ============================================================

function Write-Step { Write-Host ":: $args" -ForegroundColor Yellow }
function Write-Ok { Write-Host "   OK  $args" -ForegroundColor Green }
function Write-Skip { Write-Host "  SKIP $args" -ForegroundColor DarkGray }
function Write-Warn { Write-Host "  WARN $args" -ForegroundColor Magenta }
function Write-ErrorMsg { Write-Host "  ERROR $args" -ForegroundColor Red }

# ============================================================
# LISTA DE LOS 13 ARCHIVOS A COPIAR
# ============================================================

$Archivos = @(
    "01_Arquetipos_Historias_Snyder.md",
    "02_Arquetipos_Personalidad.md",
    "03_Alineamientos_Morales.md",
    "04_Tipos_de_Trama.md",
    "05_Tipos_de_Conflicto.md",
    "06_Dinamicas_de_Grupo.md",
    "07_Beat_Sheet_Snyder.md",
    "09_Dilemas_Filosoficos.md",
    "10_Temas_de_la_Ficcion.md",
    "11_Profesiones_y_Roles.md",
    "12_Locaciones_de_Fantasia.md",
    "13_Miedos_Arquetipicos.md",
    "14_Creacion_de_Villanos.md"
)

# ============================================================
# PRECONDICIONES
# ============================================================

Write-Step "Verificando directorio origen..."
if (-not (Test-Path -LiteralPath $SourceDir -PathType Container)) {
    Write-ErrorMsg "No se encuentra el directorio origen: $SourceDir"
    Write-Host "  El directorio mundos/arquetipos-narrativos/ debe existir con los 13 catalogos."
    exit 1
}
Write-Ok "Origen encontrado: $SourceDir"

Write-Step "Verificando directorio destino..."
if (-not (Test-Path -LiteralPath $TargetDir -PathType Container)) {
    Write-Warn "Destino no existe. Creando: $TargetDir"
    New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
    Write-Ok "Directorio destino creado."
} else {
    Write-Ok "Destino encontrado: $TargetDir"
}

# ============================================================
# COPIADO CON VERIFICACION DE HASH
# ============================================================

Write-Step "Copiando 13 catalogos de arquetipos..."
$Copiados = 0
$YaExistentes = 0
$Conflictos = 0
$Errores = 0

foreach ($Archivo in $Archivos) {
    $OrigenPath = Join-Path $SourceDir $Archivo
    $DestinoPath = Join-Path $TargetDir $Archivo

    if (-not (Test-Path -LiteralPath $OrigenPath -PathType Leaf)) {
        Write-ErrorMsg "Falta archivo origen: $OrigenPath"
        Write-Host "  La operacion se detiene. No se realizaron copias parciales de este archivo."
        $Errores++
        continue
    }

    $HashOrigen = (Get-FileHash -LiteralPath $OrigenPath -Algorithm SHA256).Hash

    if (Test-Path -LiteralPath $DestinoPath -PathType Leaf) {
        $HashDestino = (Get-FileHash -LiteralPath $DestinoPath -Algorithm SHA256).Hash

        if ($HashOrigen -eq $HashDestino) {
            $YaExistentes++
            Write-Skip "Identico: $Archivo"
            continue
        }

        if ($Force) {
            Copy-Item -LiteralPath $OrigenPath -Destination $DestinoPath -Force
            $Copiados++
            Write-Warn "Sobrescrito (--Force): $Archivo"
        } else {
            $Conflictos++
            Write-Warn "Conflicto: $Archivo -- el destino difiere del origen."
            Write-Host "         Origen : $OrigenPath"
            Write-Host "         Destino: $DestinoPath"
            Write-Host "         Usa --Force para sobrescribir con la version origen."
        }
    } else {
        Copy-Item -LiteralPath $OrigenPath -Destination $DestinoPath
        $Copiados++
        Write-Ok "Copiado: $Archivo"
    }
}

# ============================================================
# VALIDACION POST-COPIA
# ============================================================

Write-Step "Validando integridad post-copia..."

$FallasValidacion = 0
foreach ($Archivo in $Archivos) {
    $OrigenPath = Join-Path $SourceDir $Archivo
    $DestinoPath = Join-Path $TargetDir $Archivo

    if (-not (Test-Path -LiteralPath $DestinoPath -PathType Leaf)) {
        Write-Warn "Falta en destino: $Archivo (puede ser un conflicto no resuelto)"
        $FallasValidacion++
        continue
    }

    $HashOrigen = (Get-FileHash -LiteralPath $OrigenPath -Algorithm SHA256).Hash
    $HashDestino = (Get-FileHash -LiteralPath $DestinoPath -Algorithm SHA256).Hash

    if ($HashOrigen -ne $HashDestino) {
        Write-Warn "Hash difiere: $Archivo"
        $FallasValidacion++
    }
}

if ($FallasValidacion -eq 0) {
    Write-Ok "Los $($Archivos.Count) archivos copiados son identicos a sus originales."
}

$ArchivosMd = Get-ChildItem -LiteralPath $TargetDir -Filter "*.md" -ErrorAction SilentlyContinue
$TotalMd = if ($ArchivosMd) { $ArchivosMd.Count } else { 0 }
$Esperados = 15

if ($TotalMd -eq $Esperados) {
    Write-Ok "Total de archivos .md en destino: $TotalMd (esperados $Esperados)"
} else {
    Write-Warn "Total de archivos .md en destino: $TotalMd (esperados $Esperados)"
    if ($ArchivosMd) {
        Write-Host "  Archivos encontrados:"
        foreach ($f in $ArchivosMd) { Write-Host "    $($f.Name)" }
    }
}

Write-Step "Verificando preservacion de archivos existentes..."
$Preservados = @("00_Eneagrama_Stal.md", "08_Escenarios_Adaptados.md")
foreach ($Archivo in $Preservados) {
    $Path = Join-Path $TargetDir $Archivo
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        Write-Ok "Preservado: $Archivo"
    } else {
        Write-Warn "Falta archivo que debia preservarse: $Archivo"
    }
}

# ============================================================
# REPORTE FINAL
# ============================================================

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "         COPIA DE ARQUETIPOS -- REPORTE" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Copiados      : $Copiados"
Write-Host "  Ya existentes : $YaExistentes"
Write-Host "  Conflictos    : $Conflictos"
Write-Host "  Errores       : $Errores"
Write-Host "  Total .md     : $TotalMd / $Esperados esperados"
Write-Host ""
if ($Conflictos -gt 0 -and -not $Force) {
    Write-Host "  NOTA: Hay $Conflictos archivo(s) en conflicto." -ForegroundColor Yellow
    Write-Host "  Ejecuta con --Force para sobrescribirlos." -ForegroundColor Yellow
}
if ($Errores -gt 0) {
    Write-Host "  ATENCION: $Errores archivo(s) origen faltante(s)." -ForegroundColor Red
}
Write-Host "============================================" -ForegroundColor Cyan

if ($Errores -gt 0) { exit 1 }
exit 0