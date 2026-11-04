# Publicar una versión de Demiurgos

## En una frase

Le pones un **NOMBRE** a la versión y la empujas; un robot (**GitHub Actions**)
hace el resto: arma, firma, sube y acomoda el canal.

## El nombre (formato)

Mientras Demiurgos esté en **Alfa**, el nombre tiene la forma
`v0.<MINOR>.<PATCH>` — por ejemplo `v0.2.0`.

El `0` queda **fijo** durante todo el Alfa. `1.0.0` se reserva para "salió de
Alfa" y **no se usa todavía**.

## Qué número subir

| Si el cambio es… | Sube… | Ejemplo |
|---|---|---|
| Un arreglo o algo chico | el último número (PATCH) | `0.2.0` → `0.2.1` |
| Algo nuevo o que cambia lo que el usuario ve | el del medio (MINOR) | `0.2.0` → `0.3.0` |

**Regla de bolsillo**: "¿esto agrega o cambia algo que el usuario nota?" →
**sí** = sube el del medio; **no** = sube el último.

## Canal (automático según el nombre)

El canal **no se elige a mano**: lo decide el nombre.

- **Sin** `beta` en el nombre → canal **Recomendado** (valor interno `Estable`): para todos.
- **Con** `beta` en el nombre → canal **Anticipado** (valor interno `Beta`): opt-in, para testers.

La palabra `beta` es el interruptor. La pantalla de actualizaciones muestra los
canales con los nombres visibles **Recomendado** y **Anticipado**; el valor que
la app guarda sigue siendo `Estable`/`Beta`, así que el nombre visible nunca se
persiste ni viaja por la API.

## El canal publicado (qué se sirve)

El instalador y el actualizador leen una rama pública, no la descarga de la
release:

```
https://raw.githubusercontent.com/maar1223/demiurgos-releases/main
```

Ese árbol plano contiene:

| Ruta | Para qué |
|---|---|
| `install.sh` / `install.ps1` | el bootstrap de un solo comando |
| `scripts/install-demiurgos.{sh,ps1}` | el core versionado |
| `scripts/lib/verify_checksum.*` | verificación de firma y checksums |
| `scripts/provision-hermes.*` | runtime conversacional (verificado antes de ejecutar) |
| `uv/uv-<target>-<UV_VERSION>.(tar.gz|zip)` | toolchain pineado por plataforma |
| `uv-shas.env` | SHA-256 de cada uv archive, cubierto por la firma |
| `demiurgos-app-<ver>-<cell>.(tar.gz|zip)` | payload por celda (`linux-x86_64`, `linux-aarch64`, `macos-arm64`, `windows-amd64`) |
| `version.json` | nombres de payload por plataforma (compatibilidad) |
| `SHA256SUMS` + `SHA256SUMS.minisig` | manifiesto firmado de todos los artefactos del árbol |
| `latest` / `latest-beta` | punteros de versión por canal (no van en el manifiesto) |

Reglas del pipeline:

- `SHA256SUMS` se regenera sobre el árbol completo en cada publicación (sin los
  punteros, que se mueven después de firmar), así una instalación anclada a una
  versión vieja sigue verificando y funcionando.
- El árbol se empuja **sin** mover los punteros. El smoke anónimo instala desde
  la rama pública real (sin fixture ni override de checksum) y arranca `/health`
  y `/`; recién entonces un job aparte mueve `latest` (estable) o `latest-beta`
  (prerelease). Un prerelease nunca toca `latest`; el puntero del otro canal
  queda intacto.
- Si el canal todavía no tiene ningún release estable (`latest` ausente), el
  instalador resuelve `latest-beta` y lo avisa en pantalla. Es el único caso en
  que un `DEMIURGOS_VERSION=latest` implícito instala una beta.
- El `UV_VERSION` pineado vive en `.github/workflows/release.yml`; los archivos
  `uv-shas.env` se derivan de esos mismos bytes, no se escriben a mano.

## Betas

Primero `0.3.0-beta.1`, después `0.3.0-beta.2`, y así. Cuando la beta cumple los
criterios de promoción (abajo), publicas `0.3.0` (el mismo número, sin `beta`) y
va al canal **Recomendado**.

## Cuándo una beta pasa a Recomendado

La promoción es una decisión del Owner, no automática. Se promueve cuando se
cumplen **todos** estos criterios:

1. **Máquinas reales.** La beta se instaló y se usó en al menos una máquina real
   por cada sistema operativo que se va a prometer (hoy: Windows 10/11 x64;
   macOS arm64 y Linux cuando correspondan).
2. **Sin bloqueantes.** No quedan regresiones P0/P1 abiertas contra la beta; los
   P2 conocidos están triados o aceptados explícitamente.
3. **Gates verdes.** CI del commit y el smoke anónimo post-publicación (firma
   minisign + checksums + instalación de prueba) pasan.
4. **Instalación limpia.** Una instalación desde el canal publicado, en una
   máquina limpia o recién formateada, arranca y sirve `/health` y `/`.
5. **Soak.** Pasaron al menos 3 días desde la beta con uso real y sin nuevos
   bloqueantes.

Si falta cualquiera, se publica otra `-beta.N` en el canal Anticipado. Nunca se
mueve `latest` con una beta: la promoción es el tag sin `beta`.

## Cómo se publica

```bash
git tag v0.2.0
git push origin v0.2.0
```

Al empujar el tag, el robot arma, firma y sube la versión, y acomoda el canal.
Si el chequeo automático falla, **no se publica** (y una beta nunca pisa el canal
**Recomendado**). El comportamiento vive en `.github/workflows/release.yml`.

## Avisos de terceros

Cada artefacto incluye `third-party/hermes/LICENSE` con el aviso MIT de Hermes
(`Copyright (c) 2025 Nous Research`), además del `LICENSE` propio de Demiurgos.
El runtime de Hermes se instala en la máquina del usuario desde el fork público
fijado (`scripts/provision-hermes.sh` / `.ps1`); el artefacto no redistribuye
su árbol de dependencias, pero el aviso viaja igual en el payload.

## Reglas de oro

- **No se edita ningún archivo para "subir la versión"**: el tag **ES** la versión.
- **Nunca** repitas un número ya publicado.
- **Nunca** borres ni muevas un tag.
- Publicar es **público**: requiere **pedido explícito del Owner**.
- Se publica **solo desde el código a entregar** (la rama principal, `master`).
- El robot **rebota** (falla) una beta que intente caer en el canal **Recomendado**.

## Quién lo hace

- **Decide** el Owner: qué número y cuándo.
- **Empuja**: el Owner, o el agente **solo con pedido explícito**.
- **Infraestructura y secretos**: `docs/install/PUBLIC_CHANNEL_RUNBOOK.md`.
