# MVP readiness audit — wave 2 (AUD-07, AUD-08, AUD-09, AUD-10)

Branch: `fix/mvp-audit-wave-2` · Base: `master` (`801f7aa`) · Delivery: work-unit commits on the feature branch; merge and push are the Owner's decision. Test runner: `.venv/bin/python -m pytest`.

## Specs

- **S1 (AUD-09) — neutral Spanish only.** Owner request, verbatim: "el ES-AR ya no lo quiero, prefiero solo español neutro". The product exposes only `es` (neutral). No `es-ar` locale is offered or rendered anywhere; the retired `web-config-ui` wizard carries no `es-ar` entry and `REGLAS_LENGUAJE.md` documents no regional exception. Incoming regional codes (for example `es-AR`) still normalize to `es`. Acceptance: `available_languages()` has no `es-ar`; no template button; the language rules have no exception; the audit records AUD-09 resolved with its closing commit.
- **S2 (AUD-07) — VPS out of the MVP.** Owner decision (2026-11-03): remote/VPS deployment is out of MVP scope. The VPS promise was removed from `README.md` and `README.es.md`, and the obsolete per-platform activation line (which listed a server/VPS seat, already void under decision #3840) was dropped. No configurable bind and no proxy guide; the server stays loopback-only by design. Acceptance: neither README promises VPS and no activation line lists a server seat.
- **S3 (AUD-08) — auth default outside the installer.** PENDING Owner decision: fail closed, or seed `local-dev` on the manual path too. Acceptance from the audit: no install runs without auth by default; tests cover the default.
- **S4 (AUD-10) — docs ↔ code drift.** Reconcile the four claims the audit names and label each with `[ACTUAL]`/`[OBJETIVO]`: compiled-methodology bridge, Engram obligation, `requirements` macOS x86_64 target, README (es) Hermes framing. Two embedded decisions remain pending: whether Intel macOS becomes a supported target (the closure cell now passes) and how the Engram obligation is worded for the shipped runtime (SQLite) versus the agent workflow. Acceptance from the audit: the constitution and contracts do not contradict the runtime.

## Tasks

- T1 — AUD-09 retire `es-ar` — inline — done (`5badeaf`); focused tests `test_retirement_gate.py` + `test_demiurgos_language.py` + `web-config-ui/tests` = 78 passed.
- T2 — AUD-07 VPS out of the MVP — inline — done (README.md + README.es.md claims removed).
- T3 — AUD-08 auth default — blocked on S3 decision.
- T4 — AUD-10 docs drift — blocked on the two embedded S4 decisions.

## Log

- **L1** (Owner, verbatim): "continua desde checkpoint. Ah y por cierto el ES-AR ya no lo quiero, prefiero solo español neutro"
- **L2** Checkpoint state: waves 0 and 1 complete and merged (`master` = `801f7aa`); wave 2 pending (AUD-07, AUD-08, AUD-09, AUD-10). AUD-07/08 need product/security decisions; AUD-09 was previously deferred by an Owner decision that is now reversed.
- **L3** (Owner, earlier, now reversed) "Decisión: es-ar rioplatense se conserva como opción de idioma" (Engram #3887). Reversed by L1: `es-ar` is retired.
- **L4** AUD-09 implementation: removed the `es-ar` dictionary from `src/tools/web-config-ui/i18n.py`, its `_LANGUAGE_NAMES` entry, its docstring/doctests and the `screen_lang.html` button; replaced the `REGLAS_LENGUAJE.md` exception with a no-regional-variants rule. Kept the `es-*` → `es` normalization as migration for incoming codes.
- **L5** Verification: 78 focused tests pass; `available_languages()` is 10 languages without `es-ar`; `t("es-ar", …)` and `get_language_name("es-ar")` fall back as expected. Note: `i18n.py` is CRLF — edits must preserve CRLF or the diff explodes.
- **L6** Next: Owner decision on S2 (VPS) and S3 (auth default); then AUD-10 with its two embedded decisions.
- **L7** (Owner decisions, 2026-11-03) VPS: "Quitar VPS del MVP". Razonamiento previo verificado: VPS nunca se eliminó del MVP; lo que se eliminó (decisión #3840) fue el modelo de venta/activación. La promesa técnica seguía en `README.md:62` / `README.es.md:61` sin guía ni auth. Se retiran ambos README y la activación por plataforma. Dokploy/containers queda descartado: no hay Dockerfile y G8 lo dejó como canal futuro paralelo.
- **L8** Next: Owner decision on S3 (auth default outside the installer); then AUD-10.
