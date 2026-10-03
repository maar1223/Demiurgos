# Runbook — publicar el canal público (acciones del Autor)

> Estas acciones son **del Autor**, no del agente: crean cuentas remotas y
> custodian una clave privada. El resto del pipeline ya está escrito; esto es
> lo único que falta para que el primer release sea posible.

## 0. Estado actual

- El código del pipeline existe (`.github/workflows/release.yml`), pero el paso
  de publicación está **guardado por tag**: no hace nada mientras no se empuje
  un tag `vX.Y.Z`.
- Las claves del canal son **placeholders**. El consumidor verifica la firma
  *fail-closed*: sin clave real, la instalación se rechaza (a propósito).

## 1. Crear el canal público

Crear un repositorio **público** llamado `demiurgos-releases` (nombre de trabajo
`<owner>/demiurgos-releases`). El repo privado del código **no** se toca: el
canal publica artefactos, no fuente del repositorio.

## 2. Generar la clave de firma

```bash
minisign -G -p minisign.pub -s minisign.key
```

- `minisign.pub` se puede compartir (se embebe en los bootstraps).
- `minisign.key` **nunca** se versiona ni se imprime.
- Si protegés la clave con contraseña, guardala como secreto aparte.

## 3. Cargar los secretos del repositorio

En el repo del código (el privado, que corre el workflow):

| Secreto | Contenido |
|---|---|
| `MINISIGN_SECRET_KEY` | el **archivo `minisign.key` completo** |
| `MINISIGN_PUBKEY` | la línea `RWS…` de `minisign.pub` |
| `MINISIGN_KEY_PASSWORD` | la contraseña, **solo** si la clave está protegida |
| `PUBLISH_TOKEN` | token acotado con permiso de publicar en el canal público |

## 4. Reemplazar el placeholder de la clave pública

Buscar todas las apariciones (excluyendo este runbook, que menciona el literal):

```bash
rg -n 'RWSREPLACE-ME-WITH-THE-REAL-MINISIGN-PUBLIC-KEY' --hidden -g '!docs/install/PUBLIC_CHANNEL_RUNBOOK.md'
```

La clave real va en **cuatro** archivos:

- `install.sh` (variable `DEFAULT_MINISIGN_PUBKEY`)
- `install.ps1` (variable `$defaultMinisignPubkey`)
- `scripts/lib/verify_checksum.sh` (variable `DEFAULT_MINISIGN_PUBKEY`)
- `scripts/lib/verify_checksum.ps1` (variable `$DefaultMinisignPubkey`)

> `scripts/install-demiurgos.sh` **no** lleva la clave: usa `verify_minisig` de
> `scripts/lib/verify_checksum.sh`. El seam `MINISIGN_PUBKEY` (variable de
> entorno) sigue existiendo para pruebas; la clave embebida es la que usa el
> usuario final.

## 5. Emitir el primer release

```bash
git tag vX.Y.Z && git push origin vX.Y.Z
```

El pipeline construye el frontend una sola vez, empaqueta por sistema, audita el
payload, firma `SHA256SUMS`, publica en el canal con `--repo` explícito, y
**solo si** el smoke anónimo posterior pasa, mueve `latest`.

## 6. Verificar la descarga anónima (obligatorio antes de difundir)

Sin credenciales, desde una máquina limpia:

```bash
curl -fsSL https://github.com/<owner>/demiurgos-releases/install.sh -o install.sh
sha256sum install.sh            # comparar con lo publicado
```

Después: instalar de verdad, arrancar y comprobar `/health` y `/`. **Si esto no
pasa, no se difunde nada.**

## 7. Recién entonces: realinear la documentación

La tarea 9.2 (secciones de instalación de `README.md`, `README.es.md`,
`LEEME.md`, `COMANDOS.md`) está **bloqueada a propósito** hasta que el paso 6
esté verificado. La regla es simple: la documentación sigue a la evidencia, no
a la intención.

## Verificación de cierre

```bash
rg -n "in development|en desarrollo" README.md README.es.md LEEME.md COMANDOS.md
```

Debe dejar de encontrar promesas de instalación obsoletas **después** del paso
7. Antes de eso, encontrarlas es lo correcto.
