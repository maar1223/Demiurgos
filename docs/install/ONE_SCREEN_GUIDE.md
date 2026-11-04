# Guía de una pantalla — instalar Demiurgos

## Antes de empezar

- Necesitas una terminal abierta.
- **No** hace falta ser administrador, ni tener Python, ni Node, ni compilador.
- En Linux/macOS es un solo comando. En Windows son dos: primero Scoop +
  `minisign`, después Demiurgos.
- Sistemas soportados: ver [`SUPPORT_MATRIX.md`](SUPPORT_MATRIX.md).

## Linux y macOS

```bash
curl -fsSL https://github.com/maar1223/demiurgos-releases/releases/latest/download/install.sh | bash
```

## Windows

Abre **PowerShell** (sin administrador) y ejecuta dos pasos.

### 1. Instala Scoop y `minisign` (solo la primera vez)

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force; irm get.scoop.sh | iex; scoop install minisign
```

`minisign` es lo que verifica la firma del instalador. Si ya tienes Scoop, la
línea lo detecta y sigue con `minisign`; si ya tienes ambos, no rompe nada. Deja
Scoop instalado, que además sirve para otras herramientas.

### 2. Instala Demiurgos

```powershell
irm https://github.com/maar1223/demiurgos-releases/releases/latest/download/install.ps1 | iex
```

Las dos líneas van en la **misma ventana** de PowerShell.

### Si Windows bloquea el archivo

Windows marca los archivos descargados de internet. Si el comando se queja:

```powershell
Unblock-File .
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Después **cierra y vuelve a abrir la terminal** y prueba de nuevo.

## Se instala aquí

| | Linux / macOS | Windows |
|---|---|---|
| Raíz | `~/.demiurgos` | `%LOCALAPPDATA%\Demiurgos` |
| Versión actual | `~/.demiurgos/current` | `%LOCALAPPDATA%\Demiurgos\current` |
| Registros | `~/.demiurgos/logs/` | `%LOCALAPPDATA%\Demiurgos\logs\` |

Puedes cambiar la raíz con la variable `DEMIURGOS_HOME` **antes** de instalar.

## Arrancarlo

```bash
~/.demiurgos/current/scripts/start-demiurgos.sh start
```

En Windows:

```powershell
& "$env:LOCALAPPDATA\Demiurgos\current\scripts\start-demiurgos.ps1" start
```

La app queda disponible en `http://127.0.0.1:8000`. En Windows, el launcher abre
el navegador y, si Hermes está provisionado, arranca también el asistente. Si el
asistente aparece pendiente, revisa `logs\demiurgos-gateway.err.log` o arranca
el gateway manualmente en otra ventana:

```powershell
& "$env:LOCALAPPDATA\Demiurgos\current\start-gateway.ps1"
```

Volver a ejecutar el comando de arranque **no** duplica nada: si ya está
corriendo, no arranca una segunda instancia.

## Si algo falla

1. Mira los registros en `logs/` (arriba). Son permanentes: no se borran solos.
2. En Linux/macOS, genera un paquete de diagnóstico para pedir ayuda:

   ```bash
   ~/.demiurgos/current/scripts/collect-diagnostics.sh
   ```

   Deja un `.tar.gz` en la carpeta actual. **Revísalo antes de compartirlo**:
   puede contener rutas locales y el contenido de los registros.

   En Windows, adjunta los archivos de `%LOCALAPPDATA%\Demiurgos\logs\` y usa
   **Perfil → Reporte de errores** dentro de la app (muestra la versión y el
   build).
3. Volver a correr el mismo comando de instalación es seguro e idempotente.

## Lo que esta guía NO promete

- **No** hay instalador con doble clic ni firma de código paga. Por eso el
  sistema puede mostrar una advertencia de seguridad la primera vez. Es el
  precio aceptado de no pagar certificados; el comando de consola es el techo
  real de esta etapa.
- **No** hay actualización automática: se instala una versión fija
  (`DEMIURGOS_VERSION`) y para cambiar de versión se vuelve a correr el comando.
