# Identidad de Marca DEMIURGOS — Guía para el Agente

> Documento de referencia para quien trabaje en la interfaz web de Demiurgos.
> No define la implementación: **indica dónde están los activos de marca y qué
> colores usar**, para que el modo claro/oscuro se construya sobre una base
> coherente.

---

## Regla de identidad (lo primero que hay que saber)

- **Logo GRIS** → se usa sobre fondos **claros**.
- **Logo DORADO** → se usa sobre fondos **oscuros**.
- **Naranja = ACCIÓN** (CTA, botones primarios, links de acción). El naranja
  es **EL único color de acción** y es **el mismo en ambos modos**.
- **Textos y detalles** son de la misma familia del logo de cada versión, pero
  en **dos niveles**:
  - *Modo claro*: el texto es lo más oscuro; los detalles van un paso por encima.
  - *Modo oscuro*: el texto es lo más claro; los detalles van un paso por debajo.
- Nunca competir dos colores como CTA: solo el naranja actúa.

---

## Dónde están los activos de marca

Hay **dos ubicaciones**:

1. **Copia local dentro de este repo** → `docs/Logos-Demiurgos/`.
   Es un espejo de los activos (ya duplicado aquí dentro), pensado para que el
   agente nativo tenga acceso sin salir del proyecto.
2. **Ubicación original (fuente primaria)** → en el sistema de archivos del
   usuario fuera del repo. Es la que tiene autoridad si hay que volver a
   regenerar o consultar el estado original:

```
<home>/Imágenes/Logos de Demiurogs Definitivos/   ← fuente primaria
docs/Logos-Demiurgos/                                          ← copia dentro del repo
```

Estructura (idéntica en ambas ubicaciones):

```
├── README.md                     # guía general de la marca
├── gris/                         # modelo CLARO (logo gris)
│   ├── 01_svg_gris/              # 4 SVG (vectorial, 6 tonos; para web/favicon)
│   │   ├── DEMIURGOS-logo-gris.svg
│   │   ├── DEMIURGOS-logo-horizontal-gris.svg
│   │   ├── letra-D-gris.svg
│   │   └── texto-DEMIURGOS-gris.svg
│   ├── 02_png_suave_gris/        # 4 PNG (degradado continuo, sin bandas)
│   ├── comparativa_lado_a_lado.png
│   └── PALETA-INTERFAZ-CLARA.md  # paleta definitiva del modo claro
├── dorado/                       # modelo OSCURO (logo dorado)
│   ├── 01_svg_dorado/            # 4 SVG (6 tonos; para web/favicon)
│   ├── 02_png_suave_dorado/      # 4 PNG (degradado continuo)
│   ├── comparativa_dorado_lado_a_lado.png
│   └── PALETA-INTERFAZ-OSCURA.md # paleta definitiva del modo oscuro
└── referencias-interface/        # mockups y comparativas visuales
    ├── comparativa_paleta_5colores.png
    ├── mockup_interface_lado_a_lado.png
    ├── mockup_interface_claro.png
    └── mockup_interface_oscuro.png
```

**Regla de formatos de los logos:**
- El **SVG** es siempre vectorial real (colores planos de 6 tonos) — editable/escalable.
- El **degradado suave** SOLO existe como **PNG** (no se vectoriza sin que el peso se dispare).
- Para web → usar **SVG**. Para assets mostrados (documentos, portadas) → **PNG suave**.

---

## Paletas definitivas (fuente de verdad)

Ambos `.md` en la carpeta de logos son **la fuente de verdad** de los colores.
Resumen de 8 colores totales:

### Modo claro (`PALETA-INTERFAZ-CLARA.md`)

| Token | Hex | Rol |
|-------|-----|-----|
| `--ink` | `#1c1a21` | Tinta / texto — lo más oscuro |
| `--charcoal` | `#524f56` | Carbón del logo — detalles (iconos, badges, enlaces) |
| `--porcelain` | `#fffffc` | Fondo base / claro |
| `--action` | `#ff7f11` | CTA — COMPARTIDO con modo oscuro |
| `--action-hover` | `#ff3f00` | Hover del CTA — COMPARTIDO con modo oscuro |

### Modo oscuro (`PALETA-INTERFAZ-OSCURA.md`)

| Token | Hex | Rol |
|-------|-----|-----|
| `--parchment-warm` | `#e8e3d8` | Porcelana cálida / texto — lo más claro |
| `--logo-gold` | `#d8be98` | Dorado del logo — detalles |
| `--graphite` | `#12110f` | Fondo base / oscuro (grafito cálido, NO negro puro) |
| `--action` | `#ff7f11` | CTA — COMPARTIDO con modo claro |
| `--action-hover` | `#ff3f00` | Hover del CTA — COMPARTIDO con modo claro |

### Notas críticas para implementar

- **Base oscura** = grafito **cálido** `#12110f`, nunca `#000`. El logo dorado
  luce mejor sobre un casi-negro con matiz cálido que sobre negro frío.
- **Texto oscuro** = porcelana cálida `#e8e3d8`, nunca blanco puro `#ffffff`.
- **Detalle claro** = carbón del logo `#524f56`; **no** usar la plata `#cdc8d6`
  como color de UI (es muy clara y desaparece sobre porcelana).
- **CTA/hover**: `#ff7f11`/`#ff3f00` son los **mismos en ambos modos**.

---

## Relación con el tema actual (Tailwind)

El tema actual vive en `frontend/tailwind.config.js` y usa una paleta "Taller
frío" con tokens propios (`cripta`, `madero`, `piedra`, `pergamino`, `llamita`…).
Esa paleta **NO es la definitiva**. Cuando se implemente el modo claro/oscuro de
marca, los tokens del tema deben migrarse a los colores de esta guía.

Vínculo sugerido para el tema:

| Token actual | Rol | Color de marca |
|--------------|-----|----------------|
| (fondo) `cripta` | fondo oscuro | → `#12110f` |
| (texto) `pergamino` | texto oscuro | → `#e8e3d8` |
| (detalle) `llamita` | acento/detalle | → `#d8be98` |

El detalle importante: **el acento/detalle pasa a ser el color del logo de cada
versión** (dorado en oscuro, carbón en claro), reemplazando el rol del teal que
se descartó por ser frío y no pegar con la identidad cálida del taller artesano.

---

## Cómo decidir qué logo usar

| Contexto | Logo | Fondo |
|----------|------|-------|
| Navbar / header claro | GRIS | porcelana `#fffffc` |
| Navbar / header oscuro | DORADO | grafito `#12110f` |
| Footer claro | GRIS (o inverso según contraste) | — |
| Footer oscuro | DORADO | grafito `#12110f` |
| Favicon / app icon | GRIS o DORADO | según fondo del ícono |

**Regla:** sobre fondo claro → logo gris; sobre fondo oscuro → logo dorado.
No usar el logo gris sobre carbón (desaparece) ni el dorado sobre porcelana.
