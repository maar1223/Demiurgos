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

## Betas

Primero `0.3.0-beta.1`, después `0.3.0-beta.2`, y así. Cuando la beta está bien,
publicas `0.3.0` (el mismo número, sin `beta`) y va al canal **Recomendado**.

## Cómo se publica

```bash
git tag v0.2.0
git push origin v0.2.0
```

Al empujar el tag, el robot arma, firma y sube la versión, y acomoda el canal.
Si el chequeo automático falla, **no se publica** (y una beta nunca pisa el canal
**Recomendado**). El comportamiento vive en `.github/workflows/release.yml`.

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
