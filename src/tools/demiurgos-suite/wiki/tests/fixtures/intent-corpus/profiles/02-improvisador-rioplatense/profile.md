---
id: 02-improvisador-rioplatense
genre: science-fiction
language: es-AR
register: terse
axis: genre vocabulary outside the hardcoded character list, informal imperative
conversations: [01-consult, 02-command, 03-drift]
---

# Perfil 02 — El improvisador rioplatense

## Quién es

Escribe cyberpunk y no planea: improvisa sobre la marcha y se impacienta cuando
le piden un esquema. Habla en ráfagas cortas, con voseo, chistes y una
honestidad brusca. Le importa que el mundo tenga textura, no que tenga un
manual.

## Voz (muestra)

> che, la nave tiene cuarenta personas y ninguna me cae bien. necesito que la
> tripulación tenga un traidor pero que no se note en la primera escena.

## Ejes que ataca

- **Vocabulario de género fuera de la lista**: *tripulación*, *androide*, *IA
  antagonista*, *corporación*, *dron*. Ninguno está en
  `_NEW_CHARACTER_TERMS`; *personaje* casi no aparece, y cuando aparece no viene
  solo.
- **Imperativo informal**: "armame", "meteme", "activá". El mandato llega sin
  fórmula de cortesía y sin la palabra que el matcher espera.
- **Registro telegráfico**: dos o tres oraciones cortas, en minúsculas, con
  chistes. Una pregunta de criterio ocupa el mismo espacio que un comando.

## Errores que este perfil debe exponer

1. Un imperativo de sistema ("armame el sistema de facciones") cerrado como
   consulta porque no dice *personaje* ni *crear*.
2. Una pregunta de método con vocabulario denso ("¿cómo se arma una tripulación
   que no sea genérica?") abierta como flujo por la densidad léxica.
3. Un "necesito que la tripulación tenga un traidor" tratado como mandato sin
   incertidumbre explícita ni consentimiento.
4. Un pedido de método ("activá el método de cronologías") confundido con
   `start_flow` en vez de `activate_skill`.
