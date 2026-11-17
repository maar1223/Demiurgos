---
id: 04-escritor-terror
genre: horror
language: es
register: terse
axis: third person without a creation verb; naming as the source of dread
conversations: [01-consult, 02-edit, 03-drift]
---

# Perfil 04 — El escritor de terror cósmico

## Quién es

Escribe terror cósmico en tercera persona y no negocia el tono. Frases cortas,
casi sin adjetivos. Habla de lo que no se puede mirar de frente y prefiere
dejarlo así. No pide permiso para escribir: cuenta lo que ya está en el pueblo,
en el pozo, en la casa del fondo.

## Voz (muestra)

> "No quiero describirla. Si la describo, deja de dar miedo. Que el lector sepa
> sólo lo que el pueblo se anima a decir en voz baja."

## Ejes que ataca

- **Tercera persona sin verbo de creación**: nombra a *la entidad*, *la cosa*,
  *el visitante*, *el pozo*, y nunca dice *personaje*. El sujeto de la frase es
  lo que da miedo, no quien escribe.
- **Nombrar como origen del miedo**: el nombre no adorna, decide. Cuando el
  nombre aparece, la historia cambia de dueño.
- **Registro seco**: una o dos oraciones por turno. La brevedad no es descuido:
  el matcher léxico lee igual un turno seco que un comando.
- **Vocabulario de género**: *entidad*, *pozo*, *pueblo*, *voz baja*. Ninguno
  está en `_NEW_CHARACTER_TERMS`; sólo *personaje* aparece, y este perfil no lo
  usa.

## Errores que este perfil debe exponer

1. Un enunciado en tercera persona sobre *la entidad* leído como pedido de
   creación, aunque no haya verbo de creación: el sujeto es la cosa.
2. Un turno que pide un nombre convertido en apertura de flujo, cuando el autor
   no manda ni pregunta nada.
3. Una pregunta de criterio sobre el miedo tratada como activación de método,
   cuando sólo menciona cómo escribe.
4. Un pedido de cambio de nombre (*Vhoros*, no *Vhoro*) aplicado sin diff ni
   confirmación, o desviado a una creación guiada.
