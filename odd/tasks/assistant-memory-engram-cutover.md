# Assistant memory: cut Engram out of the product

Branch: `feat/assistant-memory-engram-cutover`, based on `master` (`v0.12.1`, `6e81079`).
Delivery: work-unit commits on the feature branch; no push/PR/release unless the Owner asks.
Runners: `.venv/bin/python -m pytest src/tools/demiurgos-suite/wiki/tests/ -q`; `cd frontend && npx vitest run`; `python3 scripts/check_assistant_graph.py`.

## Specs

- **S1** The Owner's intent, verbatim: "lo que pasa es que dijimos que ya no teniamos que instalar engram y depender de un servicio que mantiene alguien mas, que podiamos mantenerlo nosotros mismos con el protocolo que copiamos de como funciona engram y tomando lo que necesitamos para aplicarlo en gestion de narrativa. Pensaba que estaba funcionando asi y que iria perfectamente bien asi. Mi pregunta ahora, es viable realmente? o cometimos un error anteriormente?"
  Acceptance: no product path installs, registers, or calls Engram. Concretely: the graph MCP server defaults to Engram disabled (and keeps an explicit opt-in), the adapter never shells out to the Engram CLI, the CLI-stack installer stops installing Engram and stops registering it in the product Hermes profile, and no product prompt tells the model to use Engram tools.
- **S2** The Owner's observation, verbatim: "ok pero ya no estamos usando engram, recuerdas? o sigue funcionando por debajo y no lo sabia?"
  Acceptance: after provisioning, `<HERMES_HOME>/config.yaml` has no `mcp_servers.engram` entry, and re-running either installer or the provisioning helper never re-adds it. The removal is corrective and idempotent, like `merge_graph_mcp_server`, and preserves every sibling server and unrelated key.
- **S3** The Owner's plan, verbatim: "ok, haz una lista de todo lo que tenemos que hacer para comenzarlo en una nueva sesion. Guardalo en checkpoint y lo comenzamos con contexto fresco"
  Acceptance: this feature closes the checkpoint's FRENTE 1 only (the cut). The per-response duration/sources dropdown (FRENTE 2) is not touched here.
- **S4** The Owner's decision for E1.5, verbatim: "Re-apuntar a AssistantMemoryStore (Recomendado)"
  Acceptance: `lore_conflicts` keeps detecting contradictions, sourced from the product's own accepted memory (`AssistantMemoryStore`) instead of Engram: same `compare_claims` taxonomy and same `{conflicts, entity_path, exists, ...}` shape, with `source_b` naming the memory entry. An unavailable, unreadable, or schema-incompatible store degrades to zero conflicts plus a flag — it never raises into the MCP tool.
- **S5** Evidence: RED observed before each behavior rule; one regression test per existing behavior the change touches (graph server init defaults, `lore_search` shape, provisioning sibling preservation, installer Engram registration); differential check that the assistant SSE envelope is unchanged (this feature touches no assistant turn path).
- **S6** Contracts in `docs/` reflect the cut (`docs/architecture/demiurgos-platform.md` §7.1, plus `docs/architecture/ASSISTANT_WORLD_READING.md` if its gate mentions Engram), and the live `~/.demiurgos/hermes/config.yaml` is healed once as an operational step, reported as evidence.

### Findings that shape the work (evidence, 2026-11-20)

- The installed Engram CLI is **v3.7.2** and has **no `mem` subcommand**; `narrative_utils.engram_search` already returns `[]` on every call. So `lore_conflicts` and the `engram_matches` half of `lore_search` are already dead in production — the cut removes a corpse, and S4 restores a working signal.
- `AssistantMemoryStore` holds **221 live entries** (208 `Vibrantes`, 90 `accepted`) with an `entity` column, so per-entity retrieval is exact enough for claim comparison.
- `~/.demiurgos/hermes/config.yaml` currently registers `engram` with `mem_save,mem_search,mem_context,mem_get_observation,mem_session_summary`. That is the live contamination: the model can call those tools inside the product.
- `install.sh --with-cli-stack` downloads Engram v1.17.0 and runs `hermes mcp add engram` against `$DEMIURGOS_HERMES_HOME`, i.e. the **product** profile. The default web-app installer (`scripts/install-demiurgos.sh`) never touches Engram.
- `merge_graph_mcp_server` is the only provisioning helper that writes that config, and it preserves siblings; a companion corrective removal is the coherent place to heal existing installs.

## Tasks

- [ ] T1 server: `lore_conflicts` compares against `AssistantMemoryStore` (S4). Route: inline. Files: `mcp_adapter.py`, `tests/test_graph_mcp_server.py`.
- [ ] T2 server: remove the Engram plumbing from the server and adapter, and stop `lore_search` advertising it (S1, S5). Route: inline. Files: `graph_mcp_server.py`, `mcp_adapter.py`, `narrative_utils.py`, `tests/test_graph_mcp_server.py`, `tests/test_narrative_utils.py`.
- [ ] T3 provisioning: corrective removal of `mcp_servers.engram`, and the CLI-stack installer stops installing/registering Engram (S1, S2). Route: inline. Files: `hermes_profile_config.py`, `install.sh`, `scripts/install-demiurgos.sh`, `tests/test_graph_mcp_provisioning.py`, `tests/test_installer_hermes_isolation.py`.
- [ ] T4 prompt: drop the Engram long-term-memory paragraph (S1). Route: inline. Files: `api_server.py`, its tests.
- [ ] T5 docs + full verification + mirror (S5, S6). Route: inline. Files: `docs/architecture/demiurgos-platform.md`, this document, `payload_manifest.json` if an entrypoint changed.

## Log

- **L1 (Owner request, verbatim):** "arranquemos desde checkpoint con la sesion que corresponde y que quedó listada para que la hagamos en este momento"
- **L2 (Owner intent, verbatim):** "lo que pasa es que dijimos que ya no teniamos que instalar engram y depender de un servicio que mantiene alguien mas, que podiamos mantenerlo nosotros mismos con el protocolo que copiamos de como funciona engram y tomando lo que necesitamos para aplicarlo en gestion de narrativa. Pensaba que estaba funcionando asi y que iria perfectamente bien asi. Mi pregunta ahora, es viable realmente? o cometimos un error anteriormente?"
- **L3 (Owner observation, verbatim):** "ok pero ya no estamos usando engram, recuerdas? o sigue funcionando por debajo y no lo sabia?"
- **L4 (Owner plan, verbatim):** "ok, haz una lista de todo lo que tenemos que hacer para comenzarlo en una nueva sesion. Guardalo en checkpoint y lo comenzamos con contexto fresco"
- **L5 (Owner decision, verbatim):** "Re-apuntar a AssistantMemoryStore (Recomendado)" — chosen over documenting the loss.
- **L6 (scope discovered, 2026-11-20):** the checkpoint's E1–E4 stopped at the profile and the code; `install.sh --with-cli-stack` also installs Engram and registers it in the product profile, so the cut would not survive a reinstall. Added to scope as T3. Also verified the shipped Engram CLI no longer has `mem`, so the CLI-based half was already dead.
