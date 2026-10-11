# Guía de una pantalla — instalar Demiurgos

## Antes de empezar

- Necesitás una terminal abierta. Un comando. Nada más.
- **No** hace falta ser administrador, ni tener Python, ni Node, ni compilador.
- Sistemas soportados: ver [`SUPPORT_MATRIX.md`](SUPPORT_MATRIX.md).

## Linux y macOS

```bash
curl -fsSL https://github.com/maar1223/demiurgos-releases/releases/latest/download/install.sh | bash
```

## Windows

Abrí **PowerShell** y pegá:

```powershell
irm https://github.com/maar1223/demiurgos-releases/releases/latest/download/install.ps1 | iex
```

### Si Windows bloquea el archivo

Windows marca los archivos descargados de internet. Si el comando se queja:

```powershell
Unblock-File .
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Después **cerrá y volvé a abrir la terminal** y probá de nuevo.

## Se instala acá

| | Linux / macOS | Windows |
|---|---|---|
| Raíz | `~/.demiurgos` | `%LOCALAPPDATA%\Demiurgos` |
| Versión actual | `~/.demiurgos/current` | `%LOCALAPPDATA%\Demiurgos\current` |
| Registros | `~/.demiurgos/logs/` | `%LOCALAPPDATA%\Demiurgos\logs\` |

Podés cambiar la raíz con la variable `DEMIURGOS_HOME` **antes** de instalar.

## Arrancarlo

```bash
~/.demiurgos/current/scripts/start-demiurgos.sh start
```

En Windows:

```powershell
& "$env:LOCALAPPDATA\Demiurgos\current\scripts\start-demiurgos.ps1" start
```

Se abre en el navegador. Volver a ejecutar el comando **no** duplica nada: si ya
está corriendo, no arranca una segunda instancia.

## Si algo falla

1. Mirá los registros en `logs/` (arriba). Son permanentes: no se borran solos.
2. Generá un paquete de diagnóstico para pedir ayuda:

   ```bash
   ~/.demiurgos/current/scripts/collect-diagnostics.sh
   ```

   Deja un `.tar.gz` en la carpeta actual. **Revisalo antes de compartirlo**:
   puede contener rutas locales y el contenido de los registros.
3. Volver a correr el mismo comando de instalación es seguro e idempotente.

## Lo que esta guía NO promete

- **No** hay instalador con doble clic ni firma de código paga. Por eso el
  sistema puede mostrar una advertencia de seguridad la primera vez. Es el
  precio aceptado de no pagar certificados; el comando de consola es el techo
  real de esta etapa.
- **No** hay actualización automática: se instala una versión fija
  (`DEMIURGOS_VERSION`) y para cambiar de versión se vuelve a correr el comando.
