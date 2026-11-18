"""Intent corpus runner: simulated or live evaluation of the opening decision.

The corpus fixes the expected decision per author turn. This module loads it,
runs one decider per turn and renders a report with the two error rates kept
apart.

- ``--simulated`` proves the harness against its own labels. It never proves a
  model: agreement here is agreement with the contract, nothing more.
- ``--live`` runs the real semantic gate plus the real server policy
  (``_guided_open_profile``) and is opt-in because it costs provider calls.

Usage (from the repo root):

    .venv/bin/python src/tools/demiurgos-suite/wiki/tests/intent_corpus_runner.py --simulated
    .venv/bin/python src/tools/demiurgos-suite/wiki/tests/intent_corpus_runner.py --live --limit 12
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

import yaml

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "fixtures" / "intent-corpus"
PROFILES = CORPUS / "profiles"
REPO_ROOT = HERE.parents[4]
EVIDENCE = REPO_ROOT / "odd" / "evidence" / "intent-corpus"

OPENING = {"start_flow", "activate_skill", "edit"}
FLOW_STEP = "flow_step"
# The gate contract today cannot express a skill activation or an edit
# opening; they are reported apart instead of being scored as model misses.
NOT_MEASURED_AT_GATE = {"activate_skill", "edit"}

TURN_RE = re.compile(r"^## Turn (\d+) — (\w+)", re.MULTILINE)


@dataclass(frozen=True)
class Turn:
    number: int
    text: str
    expected_class: str
    expected_target: str | None
    must_not: str
    why: str

    @property
    def expected_opens(self) -> bool:
        return self.expected_class in OPENING


@dataclass(frozen=True)
class Conversation:
    path: Path
    id: str
    profile: str
    genre: str
    language: str
    turns: tuple[Turn, ...]


@dataclass(frozen=True)
class Decision:
    opens: bool
    class_name: str | None
    target: str | None = None
    raw: str = ""
    error: str | None = None


@dataclass
class TurnResult:
    conversation: Conversation
    turn: Turn
    decision: Decision

    @property
    def expected_opens(self) -> bool:
        return self.turn.expected_opens

    @property
    def scored(self) -> bool:
        """False when the expected class has no expressible gate outcome."""
        return not (self.turn.expected_class in NOT_MEASURED_AT_GATE and self.expected_opens)

    @property
    def false_open(self) -> bool:
        return self.decision.opens and not self.expected_opens

    @property
    def false_close(self) -> bool:
        return self.scored and self.expected_opens and not self.decision.opens


@dataclass
class Report:
    mode: str
    results: list[TurnResult] = field(default_factory=list)
    digest: str = ""
    generated_at: str = ""

    @property
    def decisions(self) -> list[TurnResult]:
        return [r for r in self.results if r.turn.expected_class != FLOW_STEP]

    @property
    def false_opens(self) -> list[TurnResult]:
        return [r for r in self.decisions if r.false_open]

    @property
    def false_closes(self) -> list[TurnResult]:
        return [r for r in self.decisions if r.false_close]

    @property
    def unavailable(self) -> list[TurnResult]:
        return [r for r in self.decisions if r.decision.error]

    @property
    def expected_no_open(self) -> int:
        return sum(1 for r in self.decisions if not r.expected_opens)

    @property
    def expected_open_scored(self) -> int:
        return sum(1 for r in self.decisions if r.scored and r.expected_opens)

    def rate(self, count: int, total: int) -> str:
        return f"{count}/{total} ({count / total:.1%})" if total else f"{count}/0 (n/a)"


_decider = Callable[[Conversation, Turn], Awaitable[Decision]]


def _field(block: str, name: str) -> str | None:
    marker = f"- **{name}:**"
    lines = block.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith(marker):
            continue
        parts = [line[len(marker):].strip()]
        for follow in lines[index + 1:]:
            if follow.strip() and follow.startswith((" ", "\t")):
                parts.append(follow.strip())
                continue
            break
        return " ".join(part for part in parts if part) or None
    return None


def _bare(value: str) -> str:
    return value.strip().strip("`").strip()


def _utterance(block: str) -> str:
    lines = []
    for line in block.splitlines():
        if line.startswith(">"):
            lines.append(line[1:].strip())
        elif lines and not line.strip():
            continue
        elif lines:
            break
    return " ".join(lines).strip()


def load_corpus(root: Path = CORPUS) -> list[Conversation]:
    conversations: list[Conversation] = []
    for path in sorted((root / "profiles").glob("*/*.md")):
        if path.name == "profile.md":
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise ValueError(f"{path}: missing frontmatter")
        _, raw, body = text.split("---\n", 2)
        front = yaml.safe_load(raw)
        turns: list[Turn] = []
        matches = list(TURN_RE.finditer(body))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            block = body[match.end():end]
            raw_class = _field(block, "Class")
            if raw_class is None:
                raise ValueError(f"{path} turn {match.group(1)}: missing Class")
            raw_target = _field(block, "Target")
            turns.append(
                Turn(
                    number=int(match.group(1)),
                    text=_utterance(block),
                    expected_class=_bare(raw_class),
                    expected_target=_bare(raw_target) if raw_target else None,
                    must_not=_field(block, "Must not") or "",
                    why=_field(block, "Why") or "",
                )
            )
        conversations.append(
            Conversation(
                path=path,
                id=str(front["id"]),
                profile=str(front["profile"]),
                genre=str(front["genre"]),
                language=str(front["language"]),
                turns=tuple(turns),
            )
        )
    return conversations


def corpus_digest(root: Path = CORPUS) -> str:
    sha = hashlib.sha256()
    for path in sorted((root / "profiles").glob("*/*.md")):
        sha.update(path.name.encode())
        sha.update(path.read_bytes())
    return sha.hexdigest()[:12]


async def simulated_decider(conversation: Conversation, turn: Turn) -> Decision:
    """Return the contract's own label: harness validation, never evidence."""
    return Decision(
        opens=turn.expected_opens,
        class_name=turn.expected_class,
        target=turn.expected_target,
        raw="simulated",
    )


def _live_session(world: str):
    """Import the server lazily so the simulated mode has no side effects."""
    sys.path.insert(0, str(HERE.parent))
    import api_server  # noqa: PLC0415
    from semantic_intent import SemanticContext  # noqa: PLC0415

    # Resolve the same gateway key the app resolves during startup. The module
    # adapter captured an empty key at import, so it is rebound here exactly as
    # ``_lifespan`` does. The key is never printed or stored.
    api_server._adopt_existing_state_once()
    if not api_server._GATEWAY_KEY:
        key = api_server._load_project_env("HERMES_GATEWAY_KEY")
        if key:
            api_server._GATEWAY_KEY = key
            api_server.ACTIVITY_ADAPTER.api_key = key
            api_server._hermes_client = None
    if not api_server._GATEWAY_KEY:
        raise SystemExit(
            "no Hermes gateway key: set HERMES_GATEWAY_KEY or run from the data root"
        )

    class LiveSession:
        async def decide(self, conversation: Conversation, turn: Turn) -> Decision:
            result = await api_server._semantic_gate(
                world, turn.text, context=SemanticContext(),
            )
            decision = result.decision
            if decision is None:
                return Decision(
                    opens=False, class_name=None, raw="unavailable",
                    error=result.reason or "unavailable",
                )
            state = decision.state
            raw = (
                f"state={state} guided={decision.guided} "
                f"explicitness={decision.guided_explicitness}"
            )
            if state in api_server.CONTINUATION_STATES:
                return Decision(True, "start_flow", raw=raw)
            if state in {"allow", "clarify"}:
                profile = api_server._guided_open_profile(turn.text, decision)
                if profile is not None:
                    return Decision(True, "start_flow", profile.flow_id, raw)
                return Decision(False, "answer" if state == "allow" else "unknown", raw=raw)
            return Decision(False, None, raw=raw)

    return LiveSession()


async def evaluate(
    decider: _decider,
    conversations: list[Conversation],
    mode: str,
    concurrency: int = 1,
) -> Report:
    """Run one decision per turn. Order is preserved; the gate is stateless."""
    report = Report(
        mode=mode,
        digest=corpus_digest(),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    pairs = [
        (conversation, turn)
        for conversation in conversations
        for turn in conversation.turns
    ]
    limit = max(1, concurrency)
    semaphore = asyncio.Semaphore(limit)

    async def one(conversation: Conversation, turn: Turn) -> TurnResult:
        async with semaphore:
            return TurnResult(conversation, turn, await decider(conversation, turn))

    report.results = list(await asyncio.gather(*(one(c, t) for c, t in pairs)))
    return report


def render_report(report: Report) -> str:
    lines = [
        f"# Intent corpus run — {report.mode}",
        "",
        f"- Generated: {report.generated_at}",
        f"- Corpus digest: `{report.digest}`",
        f"- Conversations: {len({r.conversation.id for r in report.results})}",
        f"- Author turns: {len(report.results)}",
        f"- Opening decisions: {len(report.decisions)}",
        "",
        "## Rates",
        "",
        f"- **false-open**: {report.rate(len(report.false_opens), report.expected_no_open)}"
        " — the expensive error: the reply is replaced and a writing flow opens.",
        f"- **false-close**: {report.rate(len(report.false_closes), report.expected_open_scored)}"
        " — the cheap error: the author retries.",
        f"- unavailable: {len(report.unavailable)}",
        "",
        "## By expected class",
        "",
        "| class | turns | actual opens | false opens | false closes |",
        "|---|---|---|---|---|",
    ]
    classes = sorted({r.turn.expected_class for r in report.decisions})
    for name in classes:
        rows = [r for r in report.decisions if r.turn.expected_class == name]
        lines.append(
            f"| `{name}` | {len(rows)} | {sum(1 for r in rows if r.decision.opens)} "
            f"| {sum(1 for r in rows if r.false_open)} "
            f"| {sum(1 for r in rows if r.false_close)} |"
        )

    lines += ["", "## Failures", ""]
    failures = report.false_opens + report.false_closes
    if not failures:
        lines.append("None.")
    for result in failures:
        kind = "FALSE-OPEN" if result.false_open else "FALSE-CLOSE"
        lines += [
            f"- **{kind}** `{result.conversation.profile}` {result.conversation.path.name} "
            f"turn {result.turn.number}",
            f"  - expected `{result.turn.expected_class}`"
            f"{f' → {result.turn.expected_target}' if result.turn.expected_target else ''}",
            f"  - actual `{result.decision.class_name}`"
            f"{f' → {result.decision.target}' if result.decision.target else ''}"
            f" ({result.decision.raw})",
            f"  - author: {result.turn.text}",
        ]

    if report.unavailable:
        lines += ["", "## Unavailable", ""]
        for result in report.unavailable:
            lines.append(
                f"- `{result.conversation.profile}` {result.conversation.path.name} "
                f"turn {result.turn.number}: {result.decision.error}"
            )

    ignored = [
        r for r in report.decisions
        if r.turn.expected_class in NOT_MEASURED_AT_GATE and r.expected_opens
    ]
    if report.mode.startswith("live"):
        lines += [
            "",
            "## Limits",
            "",
            "Context is world-less (`SemanticContext()`): the gate classified each",
            "utterance without a world ficha or graph, because the corpus is",
            "world-agnostic. A run with real world context is a separate fidelity pass.",
        ]

    lines += [
        "",
        "## Not measured at the gate",
        "",
        f"{len(ignored)} opening turns are `edit` or `activate_skill`. The gate contract",
        "has no field for either, so they are excluded from the false-close rate instead",
        "of being scored as misses. A zero here is a capability gap, not a pass.",
        "",
    ]
    return "\n".join(lines)


def _trim(conversations: list[Conversation], limit: int) -> list[Conversation]:
    """Cap the corpus round-robin so a smoke run spans profiles, not one folder."""
    kept: dict[int, list[Turn]] = {id(c): [] for c in conversations}
    remaining = limit
    index = 0
    while remaining > 0:
        progressed = False
        for conversation in conversations:
            if remaining <= 0:
                break
            if index < len(conversation.turns):
                kept[id(conversation)].append(conversation.turns[index])
                remaining -= 1
                progressed = True
        if not progressed:
            break
        index += 1
    return [
        Conversation(
            c.path, c.id, c.profile, c.genre, c.language, tuple(kept[id(c)]),
        )
        for c in conversations
        if kept[id(c)]
    ]


async def _main_async(args: argparse.Namespace) -> int:
    conversations = load_corpus()
    if args.only:
        conversations = [
            c for c in conversations if args.only in c.path.name or args.only in c.profile
        ]
    if args.limit:
        conversations = _trim(conversations, args.limit)

    if args.live:
        decider = _live_session(args.world).decide
        mode = f"live (gateway {args.gateway or 'env default'})"
    else:
        decider = simulated_decider
        mode = "simulated (contract self-consistency — not evidence of model behavior)"

    report = await evaluate(decider, conversations, mode, concurrency=args.concurrency)
    rendered = render_report(report)
    if args.out:
        target = Path(args.out)
    elif args.live:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        target = EVIDENCE / f"{stamp}-live.md"
    else:
        target = None
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
        print(f"report: {target}")
    print(rendered)
    return 0 if not (report.false_opens or report.false_closes or report.unavailable) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulated", action="store_true", help="contract self-check (default)")
    parser.add_argument("--live", action="store_true", help="run the real gate (costs calls)")
    parser.add_argument("--limit", type=int, default=0, help="cap author turns")
    parser.add_argument("--only", default="", help="filter by profile or file name")
    parser.add_argument("--out", default="", help="report path")
    parser.add_argument("--world", default="__intent_corpus__", help="world id for the gate")
    parser.add_argument("--gateway", default="", help="label only; the URL comes from env")
    parser.add_argument(
        "--concurrency", type=int, default=1,
        help="parallel gate calls (the gate is stateless; 4 is a safe default)",
    )
    args = parser.parse_args(argv)
    if args.live and args.simulated:
        parser.error("--live and --simulated are mutually exclusive")
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
