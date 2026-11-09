# Guided field plan and the questionnaire path

Branch: `feat/guided-field-plan`, based on `master` (`0e86b70`). Delivery: work-unit commits; no push/PR unless the Owner asks.
Runners: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/`; `cd frontend && npx vitest run`; `cd frontend && npm run typecheck`.

## Specs

- **S1 (Owner proposal, verbatim):** "Que opinas de que la creacion de personajes tenga 2 caminos que pueda tomar el autor segun lo que esté buscando. 1. 40/60 (lo que ya tenemos) 2. Rellenar el cuestionario (aunque haciendo las preguntas y dando contexto, no de una manera fria o burocratica)". The author chooses the path at session start; the choice is pinned in the session like the methodology.
- **S2 (Owner decision, verbatim):** "yo creo que deberia ser exactamente las etiquetas correspondientes al nivel pero el usuario puede saltarse alguno si no quiere rellenarla en ese momento o aun no sabe como será esa parte de dicho personaje." The fields path iterates exactly the labels of the resolved level's specimen, in order. Every field can be skipped; a skipped field stays pending and revisitable, never "answered".
- **S3 (Owner requirement, verbatim):** "ahi aparte de hacer la pregunta podria ejemplos, que debe describir y demas. El usuario responde y pasa a la siguiente pregunta. Si el usuario se quiere explayar mas en alguna respuesta o no está muy claro puede hacer enfasis en eso y hablar durante varios turnos de eso con el agente, y cuando el agente tenga la respuesta que buscaba pasa a lo siguiente." Each field carries what it expects and examples; the assistant may stay on one field for several turns; it advances when it has enough or the author asks to move on.
- **S4 Single source of truth:** one `FieldPlan` per level feeds (a) the sheet renderer, (b) the questionnaire prompt/progress, and (c) the coverage state. The renderer and the questionnaire never keep parallel label lists.
- **S5 Ficha readability:** the body renders the labels that have a value; the missing ones are a compact `## Pendientes` list, not a wall of `_(pendiente)_`. Provider `observations` are internal notes: they may fill a canonical label, but they are never dumped as ficha content. Real unmapped author facts (canon/proposals) are still kept as `**Etiqueta:** valor`.
- **S6 Explore path unchanged:** the 40/60 path keeps its current minimum gate and author satisfaction; both paths share the store, envelope, gate and serializer. The `fast`/`full` depth stays orthogonal to the path.
- **S7 Tests:** every rule above is pinned; the specimen label drift check stays.

## Tasks

- [ ] T1 branch + feature document + Engram mirror (S1–S7). Route: inline.
- [x] T2 `FieldPlan` per level in `guided_character_body.py`: structured specs (key, label, probes, prose, optional, hint, examples); renderer refactor (S4, S5); expanded mapping; compact `Pendientes`; tests. Route: inline. Evidence: real Ganic candidate now renders 9 narrative labels (Conflicto, Carácter, Vínculos, Condición, Detonante, etc.) with 0 `_(pendiente)_` and a compact `## Pendientes`; body suite 18 passed, domain 60 passed.
- [ ] T3 backend fields path: pinned path, current field injection, coverage/progress, skip, prompt, completion (S1–S3, S6). Route: inline.
- [ ] T4 frontend: path choice at start, field progress, skip/advance control, es/en copy (S1–S3). Route: inline.
- [ ] T5 docs + full verification (S7). Route: delegated verifier if a high-risk item is named.

## Log

- **L1 (Owner proposal, verbatim):** "lo que dices me gusta pero te quiero proponer algo. Que opinas de que la creacion de personajes tenga 2 caminos que pueda tomar el autor segun lo que esté buscando. 1. 40/60 (lo que ya tenemos) 2. Rellenar el cuestionario (aunque haciendo las preguntas y dando contexto, no de una manera fria o burocratica). Digamos que está en: Cual es su aspecto? ahi aparte de hacer la pregunta podria ejemplos, que debe describir y demas. El usuario responde y pasa a la siguiente pregunta. Si el usuario se quiere explayar mas en alguna respuesta o no está muy claro puede hacer enfasis en eso y hablar durante varios turnos de eso con el agente, y cuando el agente tenga la respuesta que buscaba pasa a lo siguiente. Al menos esto es como me imagino este segundo flujo guiado"
- **L2 (Owner decision, verbatim):** "yo creo que deberia ser exactamente las etiquetas correspondientes al nivel pero el usuario puede saltarse alguno si no quiere rellenarla en ese momento o aun no sabe como será esa parte de dicho personaje."
- **L3 (diagnosis evidence, 2026-11-08):** the created `mundos/Vibrantes/personajes/ganic.md` had 9 canonical labels filled, 27 `_(pendiente)_`, and 64 `## Otros datos` entries. The data was collected by the 40/60 conversation but mis-mapped; observations (internal notes) were dumped. The session stayed `phase: conversation` after creation, which is why the create/diff cards persisted (UI guard fixed in `0e86b70`).
