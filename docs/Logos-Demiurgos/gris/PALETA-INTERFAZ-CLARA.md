# Paleta de colores — Interfaz CLARA (fondo claro)

> Paleta de la aplicación DEMIURGOS para fondos claros.
> El logo **gris** es el que se usa sobre fondos claros (blanco/porcelana).
> La paleta oscura está documentada aparte (ver carpeta del logo dorado).

## Regla de identidad (lo más importante)

- **Gris** → fondos claros · **Dorado** → fondos oscuros.
- Texto y detalles son de la misma familia (carbón/plata del logo) pero en
  **dos niveles**: el texto es lo más oscuro, los detalles van un paso por encima.
- **Naranja = ACCIÓN** (CTA, botones primarios, links de acción).
- Nunca competir dos colores como CTAs: el naranja es EL único color de acción.

## Tokens de color (5)

| Token | Hex | Nombre | Rol |
|-------|-----|--------|-----|
| `--ink` | `#1c1a21` | Tinta (carbón profundo) | Texto principal — lo más oscuro del lienzo |
| `--charcoal` | `#524f56` | Carbón del logo | Detalles (iconos, badges, chevrons, enlaces) |
| `--porcelain` | `#fffffc` | Porcelana | Fondo base / claro |
| `--action` | `#ff7f11` | Mandarina | CTA / acción (botón primario) — COMPARTIDO con modo oscuro |
| `--action-hover` | `#ff3f00` | Llama | Hover / estado activo del CTA — COMPARTIDO con modo oscuro |

## Estructura de roles (paralela en ambos modos)

| Rol | Claro | Oscuro (ver paleta oscura) |
|-----|-------|---------------------------|
| Texto | Tinta `#1c1a21` (lo más oscuro) | Porcelana cálida `#e8e3d8` (lo más claro) |
| Detalles | Carbón del logo `#524f56` | Dorado del logo `#d8be98` |
| Fondo | Porcelana `#fffffc` | Grafito `#12110f` |
| CTA / acción | Mandarina `#ff7f11` | Mandarina `#ff7f11` (unificado) |
| Hover / activo del CTA | Llama `#ff3f00` | Llama `#ff3f00` (unificado) |

## Roles de uso (modo claro)

| Rol | Color |
|-----|-------|
| Fondo base | Porcelana `#fffffc` |
| Texto / tinta principal | Tinta `#1c1a21` |
| Detalles (iconos, badges, enlaces, foco) | Carbón del logo `#524f56` |
| Navbar | Porcelana `#fffffc` |
| Botón de acción (CTA) | Mandarina `#ff7f11` |
| Hover / activo del CTA | Llama `#ff3f00` |

> El CTA (`#ff7f11`) y su hover (`#ff3f00`) son **los mismos en ambos modos**:
> el naranja es la identidad de acción compartida.

## Notas de contraste

- El logo **gris** solo se lee bien sobre fondos **claros** (porcelana/blanco);
  sobre carbón oscuro desaparece → usar el logo **dorado**.
- El texto es **más oscuro** que los detalles para que el contenido mande.
- El detalle es el **carbón del logo**, no la plata pura: la plata `#cdc8d6`
  es muy clara y desaparece sobre porcelana.
- CTA naranja sobre porcelana: contraste fuerte, es el único color de acción.
