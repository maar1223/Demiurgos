# -*- coding: utf-8 -*-
"""Unit tests for the golden-set runner ``scripts/eval_assistant.py`` (T2.2).

The runner is a dev tool (not part of the payload). These tests exercise its
pure logic — fact/citation/forbidden evaluation, corpus loading, the SSE event
folding and the ``--validate-only`` gate — with no network and no live gateway.

Contract: ``odd/tasks/assistant-runtime-evolution.md`` (Phase 2, S7) and
``src/tools/demiurgos-suite/wiki/tests/fixtures/assistant-golden/README.md``.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
RUNNER = REPO_ROOT / "scripts" / "eval_assistant.py"
FIXTURES = (
    REPO_ROOT
    / "src"
    / "tools"
    / "demiurgos-suite"
    / "wiki"
    / "tests"
    / "fixtures"
    / "assistant-golden"
    / "worlds"
)


def _load_runner():
    spec = importlib.util.spec_from_file_location("eval_assistant", RUNNER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve the module's namespace.
    sys.modules["eval_assistant"] = module
    spec.loader.exec_module(module)
    return module


def _case(**overrides):
    case = {
        "id": "w-01-case",
        "level": "C",
        "question": "¿Qué clima hace en Chaart?",
        "source_paths": ["lore/regiones/chaart.md"],
        "expected_facts": [{"name": "climate", "any_of": ["frío", "helado"]}],
        "must_not": {"codes": ["invented_canon", "uncited_source"], "strings": ["tropical"]},
    }
    case.update(overrides)
    return case


def test_normalize_strips_accents_and_case():
    m = _load_runner()
    assert m.normalize("  Frío,  SECO ") == "frio, seco"


def test_evaluate_pass_when_facts_and_citation_present():
    m = _load_runner()
    answer = "En Chaart el clima es frío y seco. Fuente: lore/regiones/chaart.md"
    result = m.evaluate_case(_case(), answer, [])
    assert result.verdict == "pass", result
    assert result.facts_matched == ["climate"]
    assert result.missing_facts == []
    assert result.forbidden_hits == []
    assert result.citation_ok is True


def test_evaluate_fails_missing_fact():
    m = _load_runner()
    answer = "En Chaart hace un clima templado. Fuente: lore/regiones/chaart.md"
    result = m.evaluate_case(_case(), answer, [])
    assert result.verdict == "fail"
    assert result.missing_facts == ["climate"]


def test_evaluate_fails_forbidden_string():
    m = _load_runner()
    answer = "Chaart tiene clima tropical. Fuente: lore/regiones/chaart.md"
    result = m.evaluate_case(_case(), answer, [])
    assert result.verdict == "fail"
    assert result.forbidden_hits == ["tropical"]


def test_evaluate_fails_uncited_source():
    m = _load_runner()
    answer = "En Chaart el clima es frío y seco, según la ficha."
    result = m.evaluate_case(_case(), answer, [])
    assert result.verdict == "fail"
    assert result.citation_ok is False


def test_evaluate_accepts_basename_citation():
    m = _load_runner()
    answer = "El clima es frío (chaart.md)."
    result = m.evaluate_case(_case(), answer, [])
    assert result.citation_ok is True


def test_evaluate_all_fact_groups_must_match():
    m = _load_runner()
    case = _case(
        expected_facts=[
            {"name": "founder", "any_of": ["Maelis"]},
            {"name": "year", "any_of": ["312"]},
        ]
    )
    answer = "La fundó Maelis. Fuente: lore/regiones/chaart.md"
    result = m.evaluate_case(case, answer, [])
    assert result.verdict == "fail"
    assert result.facts_matched == ["founder"]
    assert result.missing_facts == ["year"]


def test_evaluate_language_mismatch_is_advisory_not_a_fail():
    m = _load_runner()
    # Facts are satisfied cross-lingually; only the language signal differs.
    case = _case(
        language="es",
        expected_facts=[{"name": "climate", "any_of": ["cold", "frío"]}],
    )
    english = "The climate is cold and dry. Source: lore/regiones/chaart.md"
    result = m.evaluate_case(case, english, [], world_language="es")
    # Facts/citation pass; the wrong-language signal is advisory only.
    assert result.language == "mismatch"
    assert result.verdict == "pass", result


def test_evaluate_tool_evidence_none_and_complete():
    m = _load_runner()
    answer = "En Chaart el clima es frío. Fuente: lore/regiones/chaart.md"
    none = m.evaluate_case(_case(), answer, [])
    assert none.tool_evidence == "none"
    complete = m.evaluate_case(
        _case(), answer, [{"name": "graph_read", "ok": True}]
    )
    assert complete.tool_evidence == "complete"


def test_corpus_digest_is_stable_and_changes(tmp_path):
    m = _load_runner()
    world = tmp_path / "w"
    (world / "lore").mkdir(parents=True)
    (world / "world.yaml").write_text("name: w\ndescription: x\nsource: fixture\n", encoding="utf-8")
    (world / "lore" / "a.md").write_text("# a\n", encoding="utf-8")
    d1 = m.corpus_digest(tmp_path)
    d2 = m.corpus_digest(tmp_path)
    assert d1 == d2
    (world / "lore" / "a.md").write_text("# a changed\n", encoding="utf-8")
    assert m.corpus_digest(tmp_path) != d1


def test_validate_world_accepts_shipped_example():
    m = _load_runner()
    errors = m.validate_world(FIXTURES / "example-chaart")
    assert errors == [], errors


def test_validate_world_rejects_bad_level(tmp_path):
    m = _load_runner()
    world = tmp_path / "bad"
    world.mkdir()
    (world / "world.yaml").write_text(
        "name: bad\ndescription: x\nsource: fixture\n", encoding="utf-8"
    )
    (world / "cases.yaml").write_text(
        yaml_dump(
            {
                "world": "bad",
                "cases": [
                    {
                        "id": "bad-01",
                        "level": "Z",
                        "question": "q",
                        "source_paths": ["lore/a.md"],
                        "expected_facts": [{"name": "f", "any_of": ["x"]}],
                        "must_not": {"codes": ["invented_canon"]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    errors = m.validate_world(world)
    assert any("level" in e for e in errors), errors


def test_consume_events_accumulates_deltas_and_tools():
    m = _load_runner()
    events = [
        {"run_id": "r1", "event": "tool.started", "tool": "mcp__x__graph_read"},
        {"run_id": "r1", "event": "tool.completed", "tool": "mcp__x__graph_read", "error": False},
        {"run_id": "r1", "event": "message.delta", "delta": "En Chaart "},
        {"run_id": "r1", "event": "message.delta", "delta": "el clima es frío."},
        {"run_id": "r1", "event": "run.completed", "output": "En Chaart el clima es frío."},
    ]
    answer, tools, status = m.consume_events(events)
    assert answer == "En Chaart el clima es frío."
    assert tools == [{"name": "graph_read", "ok": True}]
    assert status == "succeeded"


def test_consume_events_uses_terminal_output_when_no_deltas():
    m = _load_runner()
    events = [
        {"run_id": "r1", "event": "run.completed", "output": "Only terminal text."},
    ]
    answer, tools, status = m.consume_events(events)
    assert answer == "Only terminal text."
    assert status == "succeeded"


def test_evaluate_world_end_to_end_with_fake_answers():
    m = _load_runner()
    world = m.load_world(FIXTURES / "example-chaart")

    def answer_for(question):
        if "clima" in question:
            return "El clima es frío. Fuente: lore/regiones/chaart.md", [
                {"name": "graph_read", "ok": True}
            ], "succeeded"
        return "No sé.", [], "succeeded"

    results = m.evaluate_world(world, answer_for)
    by_id = {r["id"]: r["verdict"] for r in results}
    assert by_id["example-chaart-01-clima"] == "pass"
    assert by_id["example-chaart-02-fundadora"] == "fail"


def test_render_report_includes_per_world_and_overall_counts():
    m = _load_runner()
    results = [
        {"id": "a", "verdict": "pass", "facts_matched": ["f"], "citation_ok": True,
         "language": "ok", "tool_evidence": "complete"},
        {"id": "b", "verdict": "fail", "missing_facts": ["g"], "citation_ok": False,
         "language": "unknown", "tool_evidence": "none"},
    ]
    report = m.render_report(
        meta={"Corpus digest": "abc"}, worlds=[("example-chaart", results)]
    )
    assert "## example-chaart" in report
    assert "pass: 1/2" in report
    assert "Overall: 1/2 pass" in report
    assert "missing: g" in report


def test_cli_validate_only_exit_zero_on_example():
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--validate-only", "--corpus", str(FIXTURES)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "example-chaart" in proc.stdout


def test_cli_validate_only_exit_nonzero_on_broken(tmp_path):
    world = tmp_path / "broken"
    world.mkdir()
    (world / "world.yaml").write_text(
        "name: broken\ndescription: x\nsource: fixture\n", encoding="utf-8"
    )
    (world / "cases.yaml").write_text(
        yaml_dump({"world": "broken", "cases": []}), encoding="utf-8"
    )
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--validate-only", "--corpus", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0


def yaml_dump(obj) -> str:
    import yaml  # local import: only the tests use PyYAML

    return yaml.safe_dump(obj, sort_keys=False, allow_unicode=True)
