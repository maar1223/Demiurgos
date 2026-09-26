# Reglas de Lenguaje

## Regla dura — Español neutro en TODO texto en español

Todo texto en español del proyecto debe estar en **español neutro estricto**:
cero voseo, cero regionalismos, cero modismos locales (Rioplatense/Argentina u otros).

Aplica **siempre que el idioma sea español**, sin importar dónde viva el texto:

- **Interfaz (UI)**: textos, labels, placeholders, `aria-label`/`title`/`alt`, toasts,
  banners, estados vacíos/carga/error, diálogos, menús.
- **Catálogo `es`** (`frontend/src/i18n/messages.ts`) y cualquier string visible en español del frontend.
- **Mensajes del backend** que ve el usuario (detalles de error, mensajes de estado).
- **Prompts de la IA** (system prompt / instrucciones) y **contenido generado** cuando sea en español.
- **Documentación** del repo (guías, README, comentarios de cara al usuario).
- **Skills** (`skills/**/*.md`) y cualquier plantilla o contenido narrativo en español.

Cuando el idioma elegido sea **inglés**, el texto debe ser **inglés íntegro** (sin mezclar idiomas).
Cuando sea **español**, debe ser **español neutro íntegro** (sin voseo ni modismos).

## Español neutro estricto — cero voseo, cero regionalismos

### Verbos prohibidos (voseo → forma neutra)

| No decir | En su lugar |
|----------|-------------|
| vos | tú (o impersonal) |
| contás | cuentas |
| tenés | tienes |
| sabés | sabes |
| podés | puedes |
| pensás | piensas |
| entendés | entiendes |
| decís | dices |
| venís | vienes |
| querés | quieres |
| sos | eres |
| andá, mirá, tomá, hacé, decí, vení | ve, mira, toma, haz, di, ven |

### Imperativos voseo → imperativo neutro

| No decir | En su lugar |
|----------|-------------|
| iniciá | inicia |
| verificá | verifica |
| creá | crea |
| seleccioná | selecciona |
| configurá | configura |
| completá | completa |
| ingresá | ingresa |
| confirmá | confirma |
| revisá | revisa |
| guardá | guarda |
| arrastrá | arrastra |
| tocá | toca |
| elegí | elige |
| dejá / dejalo | deja / déjalo |
| activá | activa |
| gestioná | gestiona |
| eliminá | elimina |
| restaurá | restaura |
| demostrá | demuestra |
| abrí | abre |
| escribí | escribe |
| esperá | espera |
| finalizá | finaliza |
| arrancá | empieza |
| construí / mantenelo | construye / mantenlo |
| usá / probá | usa / prueba |
| agregá / quitá | agrega / quita |
| mové / buscá | mueve / busca |

### Expresiones prohibidas

| No decir | En su lugar |
|----------|-------------|
| dale (como afirmación) | adelante, de acuerdo, ok |
| che | (no usar) |
| viste (como muletilla) | ¿entiendes? / ¿ves? |
| recién (temporal) | apenas / acabo de |
| nomás (refuerzo) | simplemente / solo |
| de una | de acuerdo |
| lo de ayer | lo que pasó ayer |
| qué sé yo | no sé / cualquier cosa |
| al toque | enseguida / rápido |
| un montón | mucho / bastante |
| del montón | común / normal |

### Cómo se aplica (obligatorio)

- Antes de crear o editar **cualquier** texto en español, revisarlo contra estas tablas.
- **Guards automáticos** que ya bloquean voseo en el chrome de la app (corren en `npm test`):
  - `frontend/src/i18n/__tests__/catalogueGuard.test.ts` — paridad es/en + blocklist + mojibake.
  - `frontend/src/i18n/__tests__/hardcodedLiteralGuard.test.ts` — literales hardcodeados en app chrome.
- Estos guards **NO cubren** `skills/`, `mundos/`, `plantillas/`, `ideas/`: allí la regla se aplica
  a mano (revisión humana).
- La fuente única del blocklist es `frontend/src/i18n/forbidden.json` (compartida con el guard de backend).
  Si aparece un voseo/regionalismo nuevo que el guard no detecta, **ampliar ese archivo** y re-correr los tests.

### Recordatorio

- La regla aplica a **todo texto en español del proyecto**, no solo al lenguaje de la IA.
- En la conversación directa, el autor puede hablar como quiera.
- Auto-check antes de cada respuesta o edición de texto en español.
- Si el usuario señala un error, agradecer y corregir sin excusas.
