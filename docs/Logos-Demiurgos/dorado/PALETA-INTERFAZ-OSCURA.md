# Paleta de colores — Interfaz OSCURA (fondo oscuro)

> Paleta de la aplicación DEMIURGOS para fondos oscuros.
> El logo **dorado** es el que se usa sobre fondos oscuros (grafito).
> La paleta clara está documentada aparte (ver carpeta del logo gris).

## Regla de identidad (lo más importante)

- **Gris** → fondos claros · **Dorado** → fondos oscuros.
- Texto y detalles son de la misma familia (grafito/dorado) pero en
  **dos niveles**: el texto es lo más claro, los detalles van un paso por debajo.
- **Naranja = ACCIÓN** (CTA, botones primarios, links de acción).
- Nunca competir dos colores como CTAs: el naranja es EL único color de acción.

## Tokens de color (5)

| Token | Hex | Nombre | Rol |
|-------|-----|--------|-----|
| `--parchment-warm` | `#e8e3d8` | Porcelana cálida | Texto principal — lo más claro del lienzo |
| `--logo-gold` | `#d8be98` | Dorado del logo | Detalles (iconos, badges, chevrons, enlaces) |
| `--graphite` | `#12110f` | Grafito cálido | Fondo base / oscuro |
| `--action` | `#ff7f11` | Mandarina | CTA / acción (botón primario) — COMPARTIDO con modo claro |
| `--action-hover` | `#ff3f00` | Llama | Hover / estado activo del CTA — COMPARTIDO con modo claro |

## Estructura de roles (paralela en ambos modos)

| Rol | Oscuro | Claro (ver paleta clara) |
|-----|--------|--------------------------|
| Texto | Porcelana cálida `#e8e3d8` (lo más claro) | Tinta `#1c1a21` (lo más oscuro) |
| Detalles | Dorado del logo `#d8be98` | Carbón del logo `#524f56` |
| Fondo | Grafito `#12110f` | Porcelana `#fffffc` |
| CTA / acción | Mandarina `#ff7f11` | Mandarina `#ff7f11` (unificado) |
| Hover / activo del CTA | Llama `#ff3f00` | Llama `#ff3f00` (unificado) |

## Roles de uso (modo oscuro)

| Rol | Color |
|-----|-------|
| Fondo base | Grafito `#12110f` |
| Texto / tinta principal | Porcelana cálida `#e8e3d8` |
| Detalles (iconos, badges, enlaces, foco) | Dorado del logo `#d8be98` |
| Superficies / cards | Grafito elevado `#1d1b18` |
| Navbar | Grafito `#12110f` |
| Botón de acción (CTA) | Mandarina `#ff7f11` |
| Hover / activo del CTA | Llama `#ff3f00` |

> El CTA (`#ff7f11`) y su hover (`#ff3f00`) son **los mismos en ambos modos**:
> el naranja es la identidad de acción compartida.

## Notas de diseño

- Base **grafito cálido** (no negro puro): el oro/dorado luce mejor sobre un
  casi-negro con matiz cálido que sobre un negro frío.
- El texto es **más claro** que los detalles para que el contenido mande;
  el dorado `#d8be98` queda como detalle (un paso por debajo).
- El CTA mandarina `#ff7f11` es el **mismo que en el modo claro**: el naranja
  es la identidad de acción compartida, y se lee bien sobre grafito cálido.
- El texto va en porcelana cálida `#e8e3d8`, nunca blanco puro `#ffffff`.
