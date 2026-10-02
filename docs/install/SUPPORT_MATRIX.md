# Matriz de soporte — instalación de Demiurgos

> Fuente de verdad de las plataformas soportadas por el instalador de un solo
> comando. Deriva de la decisión **#3579** (matriz achicada) y del contrato de
> layout congelado en `docs/architecture/INSTALL_LAYOUT.md`.
>
> Estado: **decidida**. La versión mínima exacta de macOS la confirma la prueba
> de dependencias (*closure proof*, D3) antes de publicar el primer release.

## Lo que soportamos

| Plataforma | Arquitectura | Requisito mínimo |
|---|---|---|
| Windows 10 / 11 | x86_64 | — (rutas largas habilitadas) |
| macOS | **arm64 (Apple Silicon)** | macOS ≥ 13 |
| Linux | x86_64 / aarch64 | **glibc ≥ 2.28** |

En **todos** los sistemas soportados funciona el paquete completo: la
aplicación, el servidor de la interfaz y el **importador de documentos
`.docx` / `.pdf`**. No hay funciones que aparezcan o desaparezcan según el
sistema.

## Lo que NO soportamos

| Plataforma | Motivo | Qué hace el instalador |
|---|---|---|
| macOS **Intel** (x86_64) | no hay ruedas binarias de una dependencia del importador para esa arquitectura | frena al inicio con un mensaje claro y ofrece la vía manual |
| macOS **anterior a la versión mínima** | dependencias del sistema demasiado viejas | frena nombrando la versión requerida |
| Linux **musl / Alpine** | el conjunto de dependencias obligatorias no resuelve sin compilador | frena con el mensaje explícito de no soportado |
| Linux con **glibc < 2.28** | ídem | frena nombrando el piso de glibc |

## Mensajes de rechazo (textuales)

El instalador no falla a mitad de camino: dice exactamente por qué.

```
error: Intel Macs are not supported: Demiurgos requires macOS on Apple Silicon
       (arm64). Manual install alternative: run Demiurgos from source on this
       machine — see the installation guide
error: macOS 13 or newer is required (found 12.7); upgrade macOS and re-run —
       or use the manual install alternative from the installation guide
error: musl/Alpine is not supported: the wheels-only install cannot satisfy the
       dependency closure on musl. Manual install alternative: use a glibc-based
       Linux distribution, or run Demiurgos from source — see the installation guide
error: glibc 2.28 or newer is required (found 2.27); ...
```

## Por qué es una lista corta

Cada sistema que prometemos tiene que servir **entero**. Cuando el conjunto de
dependencias obligatorias no resuelve sin compilador en una plataforma, esa
plataforma queda afuera en lugar de entregar una instalación a medias. Ampliar
esta matriz es una decisión explícita del Autor, no un efecto secundario.

## Vía manual (sistemas no soportados)

Quien esté en una plataforma no soportada puede ejecutar Demiurgos desde el
código fuente con su propio Python. Esa vía **no** la cubre el instalador de un
comando y **no** recibe soporte oficial; está documentada como salida honesta,
no como alternativa equivalente.
