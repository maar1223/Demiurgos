# Assistant cross-session memory

Objective: the Demiurgos assistant remembers durable facts from past sessions
(chat and guided flows) across all worlds, using a product-owned local store.
No runtime dependency on Engram. Branch: `feat/assistant-memory` (from
`feat/guided-conversation-contract`, HEAD `9808516`). Delivery: work-unit
commits; push/PR are the Owner's decision. Runner: `.venv/bin/python -m pytest`.

## Specs

S1 — Cross-session recall. The assistant can recall facts stated in previous
sessions (different `session_id`) and uses them when answering. Verbatim:
"exactamente, quiero que pueda acordarse de cosas que se hablaron en sesiones
pasadas" and "solo quiero que tenga memoria entre sesiones y guarde los detalles
importantes cada que el LLM lo considere conveniente."

S2 — One world-agnostic store. Every world loaded in Demiurgos uses the same
memory store; entries carry their world as metadata, and user preferences may be
global. Verbatim: "Esa memoria deberia ser agnostica para todos los mundos que
funcionen dentro de Demiurgos."

S3 — Separated from code memory. The product memory is its own SQLite file and
never reads or writes the coding agent's Engram store. Verbatim: "Pero tienen
que estar separadas del codigo en si."

S4 — Capture every turn, cheaply. The assistant attempts capture on each turn and
skips trivial or blocked turns. Verbatim: "ok me parece bien por turno".

S5 — The LLM proposes, deterministic policy decides. A Curator extracts
0..N candidates; confidence, topic-key upsert, dedupe, conflict and
proposal-vs-canon rules decide what is stored. Guided deltas remain `proposal`
until the Author accepts them and only `accepted_canon` becomes a durable fact.
Verbatim: "deberia guardarse lo que merece guardarse, sin embargo quien decide
eso? la Skill debe tener esa instruccion? o es el gate de Demiurgos quien decide
eso?"

S6 — Ships with a fresh install. State lives in the platform state directory,
survives app updates, needs no external daemon, and starts empty for a new user.
Verbatim: "cuando una persona instale Demiurgos en su PC, todo esto funcionará
correctamente?" and "Demiurgos es monousuario tambien. No es un servicio en la
nube ni un SAAS."

S7 — Prerequisites. Guided turns persist the Author input, the activity path
injects the recent-turn window, and the final assistant answer is stored instead
of concatenated streaming partials.

S8 — Backfill. The 2026-11-04 guided session about Ganic is distilled, as far as
the stored transcript allows, into initial memories. This one-time migration is
a no-op on a fresh install.

S9 — Retrieval. Each turn retrieves the top-k relevant entries with FTS5
(`trigram`, language-agnostic) filtered by world/global and injects them into the
assistant prompt. A deeper on-demand search is available to the assistant.

S10 — Product-grade. Schema version and migrations from day one; FTS5 capability
check with a fallback; fresh-install test; language-agnostic extraction prompt;
export/forget API; docs for writers. No memory UI panel in v1.

## Tasks

- T1 — Persist guided `author_input` in both stores (`guided_character_protocol.py`, `guided_session_store.py`) + tests. (S7) — `inline`
- T2 — Activity path: pass `memory_turns` to `_build_ai_ask_prompt`; persist the final answer, not streaming partials + tests. (S7) — `inline`
- T3 — `assistant_memory_store.py`: schema (`memory_entries` + FTS5 trigram), `PRAGMA user_version`, FTS fallback, CRUD and retrieval + tests. (S1, S6, S10) — `inline`
- T4 — Memory curator + deterministic policy: extraction contract, confidence, topic-key upsert, dedupe, conflict, proposal-vs-canon + tests. (S5) — `inline`
- T5 — Wire writes: guided passive capture, per-turn chat extraction, session-close distillation + tests. (S4, S5) — `inline`
- T6 — Wire reads: top-k retrieval injected into gate/prompt; optional on-demand search tool + tests. (S9) — `inline`
- T7 — Ganic backfill: one-time distillation from the stored guided transcript + test. (S8) — `inline`
- T8 — Product-grade: migrations, FTS fallback test, fresh-install test, export/forget API, docs. (S10) — `inline`
- T9 — End-to-end verification: session A introduces Ganic, session B recalls it; full suite. (S1) — `inline`

## Log

L1 (verbatim Owner request): "exactamente, quiero que pueda acordarse de cosas
que se hablaron en sesiones pasadas, al final eso ayuda muchisimo, pero la cosa
es, va y lee todas las conversaciones? o guardaria detalles importantes en
Engram? porque la segunda opcion es la que me parece realmente interesante, ya
que asi puede ir a buscar en la base de datos SQL de Engram y encontrar la info
de la que habla el usuario."

L2 (verbatim): "ok, pero Demiurgos deberia al instalar poder crear un proyecto
nuevo en Engram para que toda la memoria se guarde alli. Esa memoria deberia ser
agnostica para todos los mundos que funcionen dentro de Demiurgos. Pero tienen
que estar separadas del codigo en si. Ahora, deberia guardarse lo que merece
guardarse, sin embargo quien decide eso? la Skill debe tener esa instruccion? o
es el gate de Demiurgos quien decide eso? hay que pensarlo muy bien."

L3 (verbatim): "ya va, pero consideras que esto podemos hacerlo mejor sin Engram
en si? no tenemos que usarlo obligatoriamente, solo quiero que tenga memoria
entre sesiones y guarde los detalles importantes cada que el LLM lo considere
conveniente. Podrias basarte en Engram para hacerlo (aunque no se si seria
reinventar la rueda)"

L4 (verbatim): "ok me parece bien por turno".

L5 (verbatim): "ok pero recuerda que Demiurgos es monousuario tambien. No es un
servicio en la nube ni un SAAS."

L6 (verbatim): "ok, y cuando una persona instale Demiurgos en su PC, todo esto
funcionará correctamente? o es un apaño solo para mi caso especifico? porque no
es esto lo que quiero. Estoy programando Demiurgos para que escritores de todo
el mundo se lo bajen en sus computadoras y puedan trabajar en sus propios
mundos"

L7 (verbatim): "adelante".

D1 — Decision (2026-11-06): product-owned SQLite store, not Engram at runtime.
Engram is a separate single-user daemon for coding agents; the product needs
proposal-vs-canon semantics it does not model, and a fresh install must not
require it. We borrow its model (`topic_key` upsert, dedupe, `superseded_by`,
`review_after`, soft delete, FTS5), not its process.

D2 — Decision: two capture channels. Passive from the guided provider's existing
`observations`/`delta` (no extra LLM call) and from the transcript; active
per-turn extraction for chat; session-close distillation.

D3 — Decision: the Gate only admits (real session, not blocked). A Curator
extracts. A deterministic policy decides. Skills may declare memory hints but
never get write authority.

D4 — Verified on the bundled runtime (Python 3.12.8 / SQLite 3.47.1): FTS5 with
`trigram` tokenizer works. `resolve_state_root` uses `platformdirs`, so state is
per-OS-user and outside the versioned app directory.

D5 — Known risk: the 2026-11-04 guided session ended with an empty
`candidate_json` after 30 revisions. If deltas are not being generated, passive
caption from the candidate is empty; the Curator still extracts from the
transcript. Investigate during T5.

E1 — Audit evidence (2026-11-06): guided session `guided-b172977b6c6347b3b5e832c0596870f8`
stored 31 messages, only 3 with `author_input`; `commit()` never appends the
Author turn (`guided_session_store.py:307-344`). `_build_ai_ask_prompt` accepts
`memory_turns` but its only caller does not pass it (`api_server.py:9679`,
`api_server.py:10026`). The activity path persists `"".join(assistant_parts)`,
which concatenates streaming partials (`api_server.py:10151-10152`).
