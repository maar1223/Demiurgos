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

S7 — Prerequisites. Guided turns persist the Author input; the activity path
relies on the Hermes gateway's per-session transcript replay and must not
duplicate the recent-turn window; the final assistant answer is stored instead
of concatenated cumulative streaming snapshots.

S8 — Backfill. The 2026-11-04 guided session about Ganic is distilled, as far as
the stored transcript allows, into initial memories. This one-time migration is
a no-op on a fresh install.

S9 — Retrieval. Each turn retrieves the top-k relevant entries with FTS5
(`trigram`, language-agnostic) filtered by world/global and injects them into the
semantic gate, the activity prompt and the guided world context. A management
and search API is available for the UI; an assistant on-demand tool is deferred.

S10 — Product-grade. Schema version and migrations from day one; FTS5 capability
check with a fallback; fresh-install test; language-agnostic extraction prompt;
export/forget API; docs for writers. No memory UI panel in v1.

## Tasks

- T1 — Persist guided `author_input` in both stores (`guided_character_protocol.py`, `guided_session_store.py`) + tests. (S7) — `inline` — DONE `4aa7ef0`
- T2 — Activity path: store the final answer, not cumulative streaming snapshots; do not duplicate the gateway-replayed recent turns + test. (S7) — `inline` — DONE
- T3 — `assistant_memory_store.py`: schema (`memory_entries` + FTS5 trigram), `PRAGMA user_version`, FTS fallback, CRUD and retrieval + tests. (S1, S6, S10) — `inline` — DONE
- T4 — Memory curator + deterministic policy: extraction contract, confidence, topic-key upsert, dedupe, conflict, proposal-vs-canon + tests. (S5) — `inline` — DONE
- T5 — Wire writes: guided passive capture, per-turn chat extraction, explicit-save override; session-close distillation deferred (per-turn covers the facts) + tests. (S4, S5) — `inline` — DONE
- T6 — Wire reads: top-k retrieval injected into gate/activity prompt/guided context; management API later; assistant on-demand tool deferred + tests. (S9) — `inline` — DONE
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

D6 — Evidence correction (2026-11-06): not passing `memory_turns` to
`_build_ai_ask_prompt` is deliberate. The Hermes gateway replays the session
transcript for `_channel_session_id(body.session_id)` (`api_server.py:9986-9994`);
embedding the window would duplicate history and inflate the context. The real
defect was persisting `"".join(assistant_parts)` when each `AnswerEvent` already
carries the cumulative snapshot.

E2 — T1 RED/GREEN: `test_commit_records_each_author_turn_in_the_transcript` and
`test_commit_persists_the_author_turn_across_restart` failed with no author turns;
green after `should_record_author_input`. Guided suites 120 passed, api_server
552 passed. T2 RED/GREEN:
`test_stream_stores_the_final_answer_not_cumulative_snapshots` failed with
`"MuyMuy bien"`; green after keeping the last snapshot. Integration 13 passed,
assistant 30 passed.

E3 — T3 evidence: `assistant_memory_store.py` creates `memory_entries` + FTS5
(`trigram` verified active on the repo venv), sets `PRAGMA user_version = 1`,
dedupes by stable `topic_key` with a normalized hash, never demotes an accepted
entry, supports soft/hard forget, and falls back to a LIKE scan. 10 focused tests
pass; the module is in `payload_manifest.json` (188 payload files) and the
freshness/boot suites pass.

E4 — T4 evidence: `memory_curator.py` builds one language-agnostic extraction
prompt, tolerates fenced JSON, clamps confidence, derives a deterministic
`topic_key` from `(world, scope, kind, topic)`, and applies the policy:
threshold 0.7 (bypassable by an explicit save), max 5/turn, a proposal or rumor
never overwrites accepted canon, and a contradictory accepted statement becomes
a separate `conflict` row instead of losing the original. 24 focused store +
curator tests pass; manifest regenerated (189 payload files).

E5 — T5 evidence: `_ASSISTANT_MEMORY` and `_MEMORY_CURATOR` are lazy seams in
`api_server.py`. Per-turn capture runs after `/ai/ask` and `/ai/ask/activity`
close; guided continuation captures the Author turn plus the assistant
question/synthesis and stores provider `observations` passively as `proposal`.
An explicit "recuerda que…" bypasses the confidence threshold. Every write is
fail-open. The conftest replaces the curator with a hermetic no-op so no test
reaches the gateway. Integration 17 passed, guided 170 passed, api_server 552
passed. Session-close distillation is deferred: per-turn capture already covers
the durable facts, and the product has no close event yet.

E6 — T6 evidence: `_memory_context` retrieves the top 5 entries (proposals
excluded) and is injected into the semantic-gate prompt (`semantic_intent.py`),
the activity prompt (`_build_ai_ask_prompt`) and the guided `world_context`.
Every path is fail-open: a store error returns an empty context. Integration 24
passed (including gate and activity injection), combined memory/guided suite 176
passed, api_server 552 passed. The one legacy assertion that the whole test
tmp tree stays empty was narrowed to the world directory, because the memory DB
is now an intended state side effect.
