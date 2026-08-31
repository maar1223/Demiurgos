# DEMIURGOS — Identidad de marca (logos y paletas)

Guía de los activos de marca definitivos: dónde está cada cosa y cómo usarla.

## Regla de identidad (lo primero)

- **Gris** → fondos **claros** · **Dorado** → fondos **oscuros**.
- Los **detalles de la UI heredan el color del logo de su versión**
  (en claro: carbón del logo gris; en oscuro: dorado del logo dorado).
- **Naranja = ACCIÓN** (CTA, botones primarios, links). El naranja es **EL único
  color de acción** y es **el mismo en ambos modos**.
- Texto y detalles van en **dos niveles**:
  - Modo claro: el texto es lo más oscuro, el detalle un paso por encima.
  - Modo oscuro: el texto es lo más claro, el detalle un paso por debajo.
- Nunca competir dos colores como CTA.

## Regla de formatos

- El **SVG** es SIEMPRE vectorial real (colores planos de 6 tonos) — editable/escalable.
- El **degradado suave** SOLO existe como **PNG** (no se vectoriza sin que el peso se dispare).
- Para web → **SVG**. Para assets mostrados (documentos, portadas) → **PNG suave**.

## Estructura de carpetas

```
Logos de Demiurogs Definitivos/
├── gris/                          # modelo CLARO (logo gris)
│   ├── 01_svg_gris/               # 4 SVG (6 tonos, vectorial)
│   ├── 02_png_suave_gris/         # 4 PNG (degradado continuo, sin bandas)
│   ├── comparativa_lado_a_lado.png
│   └── PALETA-INTERFAZ-CLARA.md   # paleta definitiva del modo claro
├── dorado/                        # modelo OSCURO (logo dorado)
│   ├── 01_svg_dorado/             # 4 SVG (6 tonos, vectorial)
│   ├── 02_png_suave_dorado/       # 4 PNG (degradado continuo)
│   ├── comparativa_dorado_lado_a_lado.png
│   └── PALETA-INTERFAZ-OSCURA.md  # paleta definitiva del modo oscuro
└── referencias-interface/         # mockups y comparativas visuales
    ├── comparativa_paleta_5colores.png
    ├── mockup_interface_lado_a_lado.png
    ├── mockup_interface_claro.png
    └── mockup_interface_oscuro.png
```

## Contenido de cada carpeta

### `gris/` (logo gris, fondos claros)

| Archivo | Acabado | Uso |
|---------|---------|-----|
| `01_svg_gris/DEMIURGOS-logo-gris.svg` | 6 tonos (vectorial) | Logo completo — web/favicon |
| `01_svg_gris/DEMIURGOS-logo-horizontal-gris.svg` | 6 tonos (vectorial) | Logo horizontal |
| `01_svg_gris/letra-D-gris.svg` | 6 tonos (vectorial) | Solo la D (isotipo) |
| `01_svg_gris/texto-DEMIURGOS-gris.svg` | 6 tonos (vectorial) | Solo texto (wordmark) |
| `02_png_suave_gris/*.png` | Degradado continuo | Para mostrar en pantalla |
| `PALETA-INTERFAZ-CLARA.md` | — | Colores del modo claro |

### `dorado/` (logo dorado, fondos oscuros)

| Archivo | Acabado | Uso |
|---------|---------|-----|
| `01_svg_dorado/DEMIURGOS-logo-6tonos.svg` | 6 tonos (vectorial) | Logo completo — web/favicon |
| `01_svg_dorado/DEMIURGOS-logo-horizontal-6tonos.svg` | 6 tonos (vectorial) | Logo horizontal |
| `01_svg_dorado/letra-D-6tonos.svg` | 6 tonos (vectorial) | Solo la D (isotipo) |
| `01_svg_dorado/texto-DEMIURGOS-6tonos.svg` | 6 tonos (vectorial) | Solo texto (wordmark) |
| `02_png_suave_dorado/*.png` | Degradado continuo | Para mostrar en pantalla |
| `PALETA-INTERFAZ-OSCURA.md` | — | Colores del modo oscuro |

## ¿Qué logo usar?

| Contexto | Logo | Fondo |
|----------|------|-------|
| Navbar / header claro | GRIS | porcelana `#fffffc` |
| Navbar / header oscuro | DORADO | grafito `#12110f` |
| Favicon / app icon | GRIS o DORADO | según fondo del ícono |

**Regla:** sobre fondo claro → logo gris; sobre fondo oscuro → logo dorado.
No usar el logo gris sobre carbón (desaparece) ni el dorado sobre porcelana.

## ¿Qué color usar? (paletas definitivas)

8 colores totales. Cada modo tiene su texto, detalle y fondo; el CTA y su hover
son compartidos.

| Rol | Modo claro | Modo oscuro |
|-----|-----------|-------------|
| Texto | `#1c1a21` | `#e8e3d8` |
| Detalles | `#524f56` | `#d8be98` |
| Fondo | `#fffffc` | `#12110f` |
| CTA | `#ff7f11` | `#ff7f11` |
| Hover CTA | `#ff3f00` | `#ff3f00` |

La fuente de verdad detallada está en `PALETA-INTERFAZ-CLARA.md` y
`PALETA-INTERFAZ-OSCURA.md`.
