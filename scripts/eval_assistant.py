#!/usr/bin/env python3
"""Level-C golden-set runner for the Demiurgos assistant (dev tool, S7).

The assistant reading the author's world is the product's differentiator. This
runner asks the assistant the corpus questions and reports, per case, whether
the answer came from the world: the expected facts are present, the cited source
path is cited, and no forbidden string appears. It never scores the wording.

Contract: ``odd/tasks/assistant-runtime-evolution.md`` (Phase 2, S7) and the
corpus format in
``src/tools/demiurgos-suite/wiki/tests/fixtures/assistant-golden/README.md``.

Two modes:

``--validate-only``
    Load and validate the corpus (schema + OKF fichas for fixture worlds) and
    print the case inventory. No network, deterministic, CI-safe.

live (default)
    Ask each case's ``question`` to the Hermes gateway (``/capabilities``,
    ``/runs``, ``/runs/{id}/events``) and evaluate the answers. Only
    ``source: data-root`` worlds are asked by default: a fixture world lives in
    the corpus, not in the running gateway's ``mundos`` directory, so a live run
    would be blind. The report goes to ``odd/evidence/assistant-golden/``.

The runner is read-only: it never writes to a world and is not part of the
install payload (like ``scripts/check_assistant_graph.py``).

Usage::

    python3 scripts/eval_assistant.py --validate-only
    python3 scripts/eval_assistant.py --gateway http://127.0.0.1:8642
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

import yaml

# Reuse the server-owned OKF validator when run from the checkout (stdlib-only),
# exactly like scripts/check_assistant_graph.py reuses the product resolver.
_WIKI = Path(__file__).resolve().parents[1] / "src" / "tools" / "demiurgos-suite" / "wiki"
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))
try:  # pragma: no cover - only absent outside the checkout
    from okf_contract import validate as okf_validate  # noqa: E402
except Exception:  # pragma: no cover
    okf_validate = None  # type: ignore[assignment]

DEFAULT_CORPUS = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "tools"
    / "demiurgos-suite"
    / "wiki"
    / "tests"
    / "fixtures"
    / "assistant-golden"
    / "worlds"
)
DEFAULT_REPORT_DIR = Path(__file__).resolve().parents[1] / "odd" / "evidence" / "assistant-golden"

LEVELS = ("C",)
MUST_NOT_CODES = (
    "invented_canon",
    "claimed_authority",
    "blind_answer",
    "uncited_source",
    "wrong_language",
    "wrong_tone",
)
# Codes the runner cannot decide by substring/citation; the report asks a human
# (or a later judge pass) to look at the answer.
JUDGED_CODES = frozenset({"invented_canon", "claimed_authority", "blind_answer", "wrong_tone"})
_REQUIRED_FEATURES = (
    "run_submission",
    "run_status",
    "run_events_sse",
    "run_stop",
    "tool_progress_events",
)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_LANG_RE = re.compile(r"^[a-z]{2}(-[A-Za-z0-9]+)?$")
_ES_MARKERS = frozenset(
    "el la los las de del que y en un una es por con para al se no su sus lo como mas".split()
)
_EN_MARKERS = frozenset(
    "the of and to in is a that for with it as was are on be this from or an".split()
)


# ---------------------------------------------------------------------------
# Text + evaluation
# ---------------------------------------------------------------------------


def normalize(text: str) -> str:
    """Lowercase and strip accents so fact matching ignores case and tildes."""
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped.lower()).strip()


@dataclass
class CaseResult:
    id: str
    verdict: str  # pass | fail
    facts_matched: list[str] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    forbidden_hits: list[str] = field(default_factory=list)
    citation_ok: bool = False
    language: str = "unknown"  # ok | mismatch | unknown
    judge_flags: list[str] = field(default_factory=list)
    tool_evidence: str = "none"  # complete | incomplete | none
    status: str = "unknown"
    tools: list[dict[str, Any]] = field(default_factory=list)
    answer_chars: int = 0
    answer: str | None = None


def _language_verdict(expected: str | None, answer: str) -> str:
    if not expected:
        return "unknown"
    tokens = re.findall(r"[^\W\d_]+", normalize(answer))
    es = sum(1 for t in tokens if t in _ES_MARKERS)
    en = sum(1 for t in tokens if t in _EN_MARKERS)
    base = expected.split("-")[0].lower()
    if base == "es":
        if es == 0 and en >= 2:
            return "mismatch"
        return "ok" if es > 0 else "unknown"
    if base == "en":
        if en == 0 and es >= 2:
            return "mismatch"
        return "ok" if en > 0 else "unknown"
    return "unknown"


def _citation_ok(source_paths: Sequence[str], answer: str) -> bool:
    if not source_paths:
        return True
    haystack = answer.replace("\\", "/").lower()
    for source in source_paths:
        normalized = source.replace("\\", "/").lower()
        if normalized in haystack:
            return True
        base = normalized.rsplit("/", 1)[-1]
        if base and base in haystack:
            return True
    return False


def _tool_evidence(tools: Sequence[Mapping[str, Any]]) -> str:
    if not tools:
        return "none"
    if any(bool(t.get("ok")) for t in tools):
        return "complete"
    return "incomplete"


def evaluate_case(
    case: Mapping[str, Any],
    answer: str,
    tools: Sequence[Mapping[str, Any]],
    *,
    world_language: str | None = None,
) -> CaseResult:
    """Deterministically evaluate one answer against one case."""
    normalized_answer = normalize(answer)
    matched: list[str] = []
    missing: list[str] = []
    for group in case.get("expected_facts", []):
        name = group.get("name", "")
        options = [normalize(str(o)) for o in group.get("any_of", [])]
        if any(option and option in normalized_answer for option in options):
            matched.append(name)
        else:
            missing.append(name)

    forbidden: list[str] = []
    for literal in case.get("must_not", {}).get("strings", []):
        needle = normalize(str(literal))
        if needle and needle in normalized_answer:
            forbidden.append(literal)

    citation = _citation_ok(case.get("source_paths", []), answer)
    expected_lang = case.get("language") or world_language
    language = _language_verdict(expected_lang, answer)

    declared = case.get("must_not", {}).get("codes", [])
    judge_flags = [code for code in declared if code in JUDGED_CODES]
    if "wrong_language" in declared and language == "mismatch":
        judge_flags.append("wrong_language")

    verdict = "pass" if (not missing and not forbidden and citation) else "fail"
    return CaseResult(
        id=str(case.get("id", "?")),
        verdict=verdict,
        facts_matched=matched,
        missing_facts=missing,
        forbidden_hits=forbidden,
        citation_ok=citation,
        language=language,
        judge_flags=judge_flags,
        tool_evidence=_tool_evidence(tools),
        status="unknown",
        tools=[dict(t) for t in tools],
        answer_chars=len(answer),
    )


def _canonical_tool(name: object) -> str | None:
    if not isinstance(name, str) or not name.strip():
        return None
    if name.startswith("mcp__") and "__" in name:
        parts = name.split("__", 2)
        if len(parts) == 3:
            return parts[2]
    return name


def consume_events(
    events: Iterable[Mapping[str, Any]], *, run_id: str | None = None
) -> tuple[str, list[dict[str, Any]], str]:
    """Fold a Hermes run event stream into (answer, tools, status)."""
    parts: list[str] = []
    tools: list[dict[str, Any]] = []
    status = "unknown"
    for event in events:
        if not isinstance(event, Mapping):
            continue
        if run_id is not None and event.get("run_id") != run_id:
            continue
        kind = event.get("event")
        if kind == "message.delta":
            delta = event.get("delta")
            if isinstance(delta, str) and delta:
                parts.append(delta)
        elif kind == "tool.completed":
            canonical = _canonical_tool(event.get("tool"))
            error = event.get("error")
            if canonical and isinstance(error, bool):
                tools.append({"name": canonical, "ok": not error})
        elif kind == "run.completed":
            if not parts:
                output = event.get("output")
                if isinstance(output, str) and output:
                    parts.append(output)
            status = "succeeded"
        elif kind in ("run.failed", "run.cancelled"):
            status = "failed"
    return "".join(parts), tools, status


# ---------------------------------------------------------------------------
# Corpus loading and validation
# ---------------------------------------------------------------------------


def _read_yaml(path: Path) -> Mapping[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: expected a mapping")
    return data


def load_world(world_dir: Path) -> dict[str, Any]:
    descriptor = _read_yaml(world_dir / "world.yaml")
    cases_doc = _read_yaml(world_dir / "cases.yaml")
    return {
        "slug": world_dir.name,
        "descriptor": descriptor,
        "cases": list(cases_doc.get("cases", [])),
    }


def _validate_descriptor(descriptor: Mapping[str, Any], slug: str) -> list[str]:
    errors: list[str] = []
    for key in ("name", "description", "source"):
        if not isinstance(descriptor.get(key), str) or not str(descriptor.get(key)).strip():
            errors.append(f"world.yaml: missing {key!r}")
    name = descriptor.get("name")
    if isinstance(name, str) and not _SLUG_RE.match(name):
        errors.append(f"world.yaml: name {name!r} is not a slug")
    if isinstance(name, str) and name != slug:
        errors.append(f"world.yaml: name {name!r} must equal the directory {slug!r}")
    source = descriptor.get("source")
    if source not in ("fixture", "data-root"):
        errors.append(f"world.yaml: source {source!r} not in ['fixture', 'data-root']")
    lang = descriptor.get("language")
    if lang is not None and (not isinstance(lang, str) or not _LANG_RE.match(lang)):
        errors.append(f"world.yaml: language {lang!r} is not a language tag")
    return errors


def validate_cases_document(doc: Mapping[str, Any], slug: str) -> list[str]:
    errors: list[str] = []
    if doc.get("world") != slug:
        errors.append(f"cases.yaml: world {doc.get('world')!r} must equal {slug!r}")
    cases = doc.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("cases.yaml: 'cases' must be a non-empty list")
        return errors
    seen: set[str] = set()
    for i, case in enumerate(cases):
        where = f"cases[{i}]"
        if not isinstance(case, dict):
            errors.append(f"{where}: expected a mapping")
            continue
        case_id = case.get("id")
        if not isinstance(case_id, str) or not _SLUG_RE.match(case_id):
            errors.append(f"{where}.id: {case_id!r} is not a slug")
        elif case_id in seen:
            errors.append(f"{where}.id: duplicate {case_id!r}")
        else:
            seen.add(case_id)
        if case.get("level") not in LEVELS:
            errors.append(f"{where}.level: {case.get('level')!r} not in {list(LEVELS)}")
        if not isinstance(case.get("question"), str) or not case["question"].strip():
            errors.append(f"{where}.question: required non-empty string")
        lang = case.get("language")
        if lang is not None and (not isinstance(lang, str) or not _LANG_RE.match(lang)):
            errors.append(f"{where}.language: {lang!r} is not a language tag")
        sources = case.get("source_paths")
        if not isinstance(sources, list) or not sources or not all(
            isinstance(s, str) and s.strip() for s in sources
        ):
            errors.append(f"{where}.source_paths: required non-empty string list")
        elif len(set(sources)) != len(sources):
            errors.append(f"{where}.source_paths: duplicates")
        facts = case.get("expected_facts")
        if not isinstance(facts, list) or not facts:
            errors.append(f"{where}.expected_facts: required non-empty list")
        else:
            for j, group in enumerate(facts):
                gwhere = f"{where}.expected_facts[{j}]"
                if not isinstance(group, dict):
                    errors.append(f"{gwhere}: expected a mapping")
                    continue
                if not isinstance(group.get("name"), str) or not _SLUG_RE.match(group["name"]):
                    errors.append(f"{gwhere}.name: not a slug")
                options = group.get("any_of")
                if not isinstance(options, list) or not options or not all(
                    isinstance(o, str) and o.strip() for o in options
                ):
                    errors.append(f"{gwhere}.any_of: required non-empty string list")
        must_not = case.get("must_not")
        if not isinstance(must_not, dict):
            errors.append(f"{where}.must_not: required mapping")
        else:
            codes = must_not.get("codes")
            if not isinstance(codes, list) or not all(c in MUST_NOT_CODES for c in codes):
                errors.append(f"{where}.must_not.codes: subset of {list(MUST_NOT_CODES)}")
            strings = must_not.get("strings")
            if strings is not None and (
                not isinstance(strings, list)
                or not all(isinstance(s, str) and s.strip() for s in strings)
            ):
                errors.append(f"{where}.must_not.strings: string list")
    return errors


def validate_world(world_dir: Path, *, check_fichas: bool = True) -> list[str]:
    """Validate one world directory. Returns a list of error strings ([] = OK)."""
    try:
        world = load_world(world_dir)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [f"{world_dir.name}: {exc}"]
    slug = world["slug"]
    errors = _validate_descriptor(world["descriptor"], slug)
    errors += validate_cases_document(
        {"world": slug, "cases": world["cases"]}, slug
    )
    if check_fichas and world["descriptor"].get("source") == "fixture":
        for case in world["cases"]:
            for source in case.get("source_paths", []):
                target = world_dir / source
                if not target.is_file():
                    errors.append(f"{case.get('id')}: missing ficha {source}")
                    continue
                if okf_validate is not None:
                    result = okf_validate(target.read_text(encoding="utf-8"))
                    if not getattr(result, "ok", False):
                        errors.append(
                            f"{case.get('id')}: {source} is not valid OKF "
                            f"({getattr(result, 'issues', ())})"
                        )
    return errors


def corpus_digest(worlds_dir: Path) -> str:
    digest = hashlib.sha256()
    root = Path(worlds_dir)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def discover_worlds(worlds_dir: Path) -> list[Path]:
    if not worlds_dir.is_dir():
        return []
    return sorted(
        (p for p in worlds_dir.iterdir() if p.is_dir() and (p / "world.yaml").is_file()),
        key=lambda p: p.name,
    )


# ---------------------------------------------------------------------------
# Live transport (documented Hermes API server contract)
# ---------------------------------------------------------------------------


def resolve_base(value: str | None) -> str:
    url = (value or os.getenv("HERMES_GATEWAY_URL") or "http://127.0.0.1:8642").rstrip("/")
    suffix = "/v1/chat/completions"
    if url.endswith(suffix):
        url = url[: -len(suffix)]
    return url


def resolve_key(value: str | None) -> str:
    return value or os.getenv("HERMES_GATEWAY_KEY") or os.getenv("API_SERVER_KEY") or ""


def _headers(key: str, *, accept: str = "application/json") -> dict[str, str]:
    headers = {"Accept": accept, "Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def probe(base: str, key: str, *, timeout: float = 10.0) -> None:
    request = urllib.request.Request(f"{base}/capabilities", headers=_headers(key))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SystemExit(
            f"gateway unreachable at {base}/capabilities ({exc}); start Demiurgos first"
        )
    features = body.get("features") if isinstance(body, dict) else None
    enabled = (
        {name for name, on in features.items() if on is True}
        if isinstance(features, dict)
        else set()
    )
    missing = [f for f in _REQUIRED_FEATURES if f not in enabled]
    if missing:
        raise SystemExit(f"gateway capabilities missing {missing}; cannot run the eval")


def start_run(base: str, key: str, prompt: str, *, timeout: float = 30.0) -> str:
    body = json.dumps({"input": prompt}).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/runs", data=body, headers=_headers(key), method="POST"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    run_id = payload.get("run_id") if isinstance(payload, dict) else None
    if not isinstance(run_id, str) or not run_id:
        raise RuntimeError("gateway returned an invalid run submission")
    return run_id


def iter_sse(url: str, key: str, *, timeout: float) -> Iterator[dict[str, Any]]:
    request = urllib.request.Request(url, headers=_headers(key, accept="text/event-stream"))
    data_lines: list[str] = []
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw in response:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line == "":
                if data_lines:
                    try:
                        payload = json.loads("\n".join(data_lines))
                    except ValueError:
                        payload = None
                    if isinstance(payload, dict):
                        yield payload
                data_lines = []
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
    if data_lines:
        try:
            payload = json.loads("\n".join(data_lines))
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            yield payload


def answer_assistant(base: str, key: str, prompt: str, *, timeout: float = 300.0) -> tuple[str, list[dict[str, Any]], str]:
    run_id = start_run(base, key, prompt)
    events = iter_sse(f"{base}/runs/{run_id}/events", key, timeout=timeout)
    bounded = _bounded(events, timeout)
    return consume_events(bounded, run_id=run_id)


def _bounded(events: Iterator[dict[str, Any]], budget: float) -> Iterator[dict[str, Any]]:
    deadline = time.monotonic() + budget
    for event in events:
        if time.monotonic() > deadline:
            return
        yield event


# ---------------------------------------------------------------------------
# Evaluation and report
# ---------------------------------------------------------------------------


def evaluate_world(
    world: Mapping[str, Any],
    answer_for: Callable[[str], tuple[str, list[dict[str, Any]], str]],
    *,
    keep_answers: bool = False,
) -> list[dict[str, Any]]:
    language = world["descriptor"].get("language")
    results: list[dict[str, Any]] = []
    for case in world["cases"]:
        try:
            answer, tools, status = answer_for(str(case.get("question", "")))
        except Exception as exc:  # a transport failure is data, not a crash
            results.append(
                {
                    "id": case.get("id"),
                    "verdict": "error",
                    "error": str(exc),
                    "judge_flags": [],
                    "tools": [],
                    "status": "error",
                    "answer_chars": 0,
                }
            )
            continue
        result = evaluate_case(case, answer, tools, world_language=language)
        result.status = status
        record = asdict(result)
        if not keep_answers:
            record.pop("answer", None)
        else:
            record["answer"] = answer
        results.append(record)
    return results


def _sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            cwd=Path(__file__).resolve().parents[1],
        ).stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def render_report(
    *,
    meta: Mapping[str, Any],
    worlds: Sequence[tuple[str, Sequence[Mapping[str, Any]]]],
) -> str:
    lines: list[str] = ["# Assistant golden-set run", ""]
    for key, value in meta.items():
        lines.append(f"- {key}: {value}")
    total = 0
    passed = 0
    for slug, results in worlds:
        w_pass = sum(1 for r in results if r.get("verdict") == "pass")
        w_total = len(results)
        total += w_total
        passed += w_pass
        lines.append("")
        lines.append(f"## {slug}")
        lines.append("")
        lines.append(f"- pass: {w_pass}/{w_total}")
        lines.append("")
        lines.append("| case | verdict | facts | citation | language | tool evidence | notes |")
        lines.append("|---|---|---|---|---|---|---|")
        for result in results:
            notes = []
            if result.get("missing_facts"):
                notes.append("missing: " + ", ".join(result["missing_facts"]))
            if result.get("forbidden_hits"):
                notes.append("forbidden: " + ", ".join(result["forbidden_hits"]))
            if result.get("judge_flags"):
                notes.append("judge: " + ", ".join(result["judge_flags"]))
            if result.get("error"):
                notes.append("error: " + str(result["error"]))
            facts = ", ".join(result.get("facts_matched") or []) or "—"
            citation = "yes" if result.get("citation_ok") else "no"
            lines.append(
                f"| {result.get('id')} | {result.get('verdict')} | {facts} | {citation} "
                f"| {result.get('language')} | {result.get('tool_evidence')} "
                f"| {'; '.join(notes) or '—'} |"
            )
            if result.get("answer") is not None:
                lines.append(f"| | | | | | | {result['answer']!r} |")
    lines.append("")
    lines.append(f"**Overall: {passed}/{total} pass**")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _default_out() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return DEFAULT_REPORT_DIR / f"{stamp}-{_sha()}.md"


def _validate_only(corpus: Path) -> int:
    worlds = discover_worlds(corpus)
    if not worlds:
        print(f"no worlds under {corpus}", file=sys.stderr)
        return 2
    failed = False
    total_cases = 0
    for world_dir in worlds:
        errors = validate_world(world_dir)
        try:
            world = load_world(world_dir)
            count = len(world["cases"])
        except Exception:
            count = 0
        total_cases += count
        if errors:
            failed = True
            print(f"FAIL {world_dir.name}")
            for error in errors:
                print(f"  - {error}")
        else:
            source = world["descriptor"].get("source")
            print(f"OK   {world_dir.name} ({count} cases, source={source})")
    print(f"\n{len(worlds)} world(s), {total_cases} case(s), digest {corpus_digest(corpus)}")
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Level-C golden-set runner for the assistant")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS), help="corpus worlds directory")
    parser.add_argument("--world", action="append", default=[], help="only this world slug (repeatable)")
    parser.add_argument("--gateway", default=None, help="gateway base URL (default HERMES_GATEWAY_URL)")
    parser.add_argument("--key", default=None, help="gateway key (default HERMES_GATEWAY_KEY/API_SERVER_KEY)")
    parser.add_argument("--out", default=None, help="report path (default odd/evidence/assistant-golden/<date>-<sha>.md)")
    parser.add_argument("--timeout", type=float, default=300.0, help="per-case stream budget in seconds")
    parser.add_argument("--validate-only", action="store_true", help="validate the corpus; no network")
    parser.add_argument("--include-answers", action="store_true", help="include answer text in the report")
    parser.add_argument("--allow-fixture-live", action="store_true", help="ask fixture worlds too (needs a stack indexing them)")
    parser.add_argument("--fail-on-fail", action="store_true", help="exit nonzero when any case fails")
    args = parser.parse_args(argv)

    corpus = Path(args.corpus)
    if args.validate_only:
        return _validate_only(corpus)

    worlds = discover_worlds(corpus)
    if args.world:
        wanted = set(args.world)
        worlds = [w for w in worlds if w.name in wanted]
    if not worlds:
        print(f"no worlds to run under {corpus}", file=sys.stderr)
        return 2

    base = resolve_base(args.gateway)
    key = resolve_key(args.key)
    probe(base, key)

    selected: list[tuple[str, list[dict[str, Any]]]] = []
    skipped: list[str] = []
    for world_dir in worlds:
        world = load_world(world_dir)
        if world["descriptor"].get("source") != "data-root" and not args.allow_fixture_live:
            skipped.append(world["slug"])
            continue
        results = evaluate_world(
            world,
            lambda prompt: answer_assistant(base, key, prompt, timeout=args.timeout),
            keep_answers=args.include_answers,
        )
        selected.append((world["slug"], results))
        for result in results:
            mark = "PASS" if result.get("verdict") == "pass" else "FAIL"
            print(f"{mark} {result.get('id')} [{result.get('verdict')}]")

    if skipped:
        print(
            "skipped fixture world(s) not indexed by the live gateway: "
            + ", ".join(skipped)
            + " (use --allow-fixture-live to override)"
        )
    if not selected:
        print("no data-root world to run; nothing measured", file=sys.stderr)
        return 2

    meta = {
        "Generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "Backend": _sha(),
        "Gateway": base,
        "Corpus digest": corpus_digest(corpus),
        "Corpus": str(corpus),
    }
    report = render_report(meta=meta, worlds=selected)
    out = Path(args.out) if args.out else _default_out()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"report: {out}")

    failed = any(r.get("verdict") != "pass" for _, results in selected for r in results)
    return 1 if (failed and args.fail_on_fail) else 0


if __name__ == "__main__":
    raise SystemExit(main())
