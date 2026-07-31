# /sync — Sincronizar Demiurgos con Google Drive

Dispara la sincronización unidireccional de todo el contenido narrativo local hacia Google Drive.

## Qué sincroniza
- `mundos/` — Todos los mundos, personajes, lore, sagas
- `Ideas/` — Banco de Ideas global
- `plantillas/` — Catálogos de arquetipos compartidos
- `_archivo_produccion/` — Assets de producción (imágenes, video, audio)

## Qué NO sincroniza
- Código (`src/`, `skills/`, `.atl/`)
- Configuración con credenciales (`.env`)
- Git (`.git/`)
- Temporales (`output/`, `.tmp.driveupload/`)

## Implementación
Ejecuta: `powershell -File scripts/sync-now.ps1` desde la raíz del proyecto.
Reporta el resultado al Autor.

## Watcher automático
Si el Autor quiere sincronización automática (cada vez que guarda un archivo), ejecutar:
`powershell -File scripts/start-sync.ps1`
El watcher espera 60 segundos de inactividad tras el último cambio antes de sincronizar.
