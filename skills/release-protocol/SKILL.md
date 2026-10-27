---
name: release-protocol
description: "Trigger: publicar, release, version, tag, nueva versión, beta, canal Recomendado, canal Anticipado, actualizar el canal, retirar una versión. How to choose the Demiurgos version number and publish it safely."
license: Apache-2.0
metadata:
  author: Demiurgos
  version: "1.0"
---

## Contrato de Activación

Activa cuando el Owner pide **publicar / sacar / taggear** una versión, **elegir un número de versión**, o **gestionar los canales** Recomendado/Anticipado (incluye actualizar o retirar una versión publicada).

No aplica a: desarrollo normal, commits, PRs ni fases SDD. Esos flujos no publican nada.

## Regla de Oro (va primero)

Publicar es **público** e **irreversible**: una vez empujado el tag, el release es visible y no se deshace.

- **Nunca publicar sin pedido explícito del Owner.**
- El agente decide el **CÓMO** (formato, número, pasos, verificación del canal).
- El Owner decide el **QUÉ** y el **CUÁNDO** (qué entra, qué número, cuándo se publica).

Sin pedido explícito, esta skill **no ejecuta** los pasos de publicación: se limita a explicar y proponer.

## Formato

Mientras Demiurgos esté en **Alfa**, el nombre tiene la forma:

```
v0.<MINOR>.<PATCH>
```

- El `0` queda **fijo** durante todo el Alfa.
- `1.0.0` se reserva para "salió de Alfa" y **no se usa todavía**.

## Cómo elegir el número

| Si el cambio es… | Sube… | Ejemplo |
|---|---|---|
| Un arreglo o algo chico | PATCH (el último) | `0.2.0` → `0.2.1` |
| Algo nuevo o que cambia lo que el usuario ve | MINOR (el del medio) | `0.2.0` → `0.3.0` |

**Regla de bolsillo**: "¿el usuario nota el cambio?" → **sí** = sube el MINOR; **no** = sube el PATCH.

El número es la única decisión de contenido; **no se edita ningún archivo** para "subir la versión".

## Canal Automático

El canal **no se elige a mano**: lo decide el nombre del tag.

- **Sin** `beta` en el nombre → canal **Recomendado** (valor interno `Estable`): para todos.
- **Con** `beta` en el nombre → canal **Anticipado** (valor interno `Beta`): opt-in, para testers.

La palabra `beta` es el interruptor. La pantalla de actualizaciones muestra los canales como **Recomendado** y **Anticipado**; el valor persistido sigue siendo `Estable`/`Beta`.

## Betas

Permite publicar versiones de prueba antes de estabilizar:

- Primero `0.3.0-beta.1`, después `0.3.0-beta.2`, y así.
- Cuando la beta está bien, se publica `0.3.0` (el **mismo número**, sin `beta`) y va al canal **Recomendado**.

## Pasos de Publicación

El agente los ejecuta **solo** con pedido explícito del Owner:

1. **Confirmar el código**: verificar que se publica desde la rama principal (`master`) y que el código a publicar es el correcto.
2. **Elegir el número**: aplicar la regla de arriba (PATCH o MINOR; `beta` si corresponde).
3. **Tag + push**:
   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
4. **Seguir el workflow**: esperar a que GitHub Actions termine y **reportar el resultado**: publicado en Recomendado/Anticipado, o rebotado.

## Qué Hace el Robot (contrato real de `.github/workflows/release.yml`)

El tag `v*` es la **única autoridad**. La mecánica verificada:

- **Disparo por tag**: el workflow escucha `push` a `master` **y** tags `v*`. En un push a `master` es un *dry run* (solo empaqueta); el job `publish` está **guardado por tag** (`startsWith(github.ref, 'refs/tags/v')`).
- **La versión sale del tag**: el número se deriva del nombre del tag (se quita el `v`).
- **Clasificación Beta**: un tag es *prerelease* **si y solo si** el núcleo de versión lleva un `-` (por ejemplo `v0.3.0-beta.1` → prerelease; `v0.3.0` → estable). `beta` en las notas no importa: **el `-` en el nombre es lo que decide**.
- **Canal por puntero**: el canal Recomendado (`Estable`) mueve el puntero **`latest`**; el canal Anticipado (`Beta`) mueve el puntero **separado `latest-beta`** y **nunca** toca `latest`.
- **Fallar es seguro** (fail-closed): si el smoke anónimo (firma + checksums + instalación + arranque) no pasa, el puntero **no se mueve**. Además, una **aserción final** comprueba que una beta no movió `latest`; si lo movió, el release **falla**.

## Checklist de Seguridad

- **Nunca** repetir un número ya publicado.
- **Nunca** borrar ni mover un tag.
- **No** editar archivos para "subir la versión": el tag **ES** la versión.
- **Verificar el canal resultante** después de publicar (Recomendado en `latest`; Anticipado en `latest-beta`).
- Publicar **solo desde el código a entregar** (la rama principal, `master`).
- Publicar **solo** con pedido explícito del Owner.

## Referencias

- `docs/RELEASING.md` — versión humana del protocolo (lenguaje llano).
- `.github/workflows/release.yml` — mecánica real de publicación (clasificación Beta, punteros, aserciones).
- `docs/install/PUBLIC_CHANNEL_RUNBOOK.md` — infraestructura, claves y secretos (acciones del Owner).
