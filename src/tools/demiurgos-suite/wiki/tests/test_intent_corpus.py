"""Contract tests for the synthetic intent corpus (S4, S9).

These tests read only the fixture Markdown and the closed taxonomy. They never
call a model: the corpus fixes decisions and forbidden outcomes, never the
assistant's wording.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

CORPUS = Path(__file__).parent / "fixtures" / "intent-corpus"
LABELS = CORPUS / "labels.yaml"
PROFILES = CORPUS / "profiles"

OPENING = {"start_flow", "activate_skill", "edit"}
NEVER_OPEN = {"answer", "unknown"}
FLOW_STEP = "flow_step"

REGISTERS = {"terse", "verbose-formal", "ambiguous"}
DEPTHS = {"single-turn", "ongoing"}
ATTACHMENTS = {"none", "present"}
REFERENCES = {"none", "named"}

CONVERSATION_KEYS = {
    "id",
    "profile",
    "genre",
    "language",
    "register",
    "depth",
    "attachment",
    "reference",
}

TURN_RE = re.compile(r"^## Turn (\d+) — (\w+)(.*)$", re.MULTILINE)
NAME_RE = re.compile(r"^\d{2}-[a-z0-9-]+\.md$")


def _taxonomy() -> dict:
    data = yaml.safe_load(LABELS.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "labels.yaml must be a mapping"
    return data


def _frontmatter(text: str, where: str) -> tuple[dict, str]:
    assert text.startswith("---\n"), f"{where}: missing YAML frontmatter"
    _, raw, body = text.split("---\n", 2)
    data = yaml.safe_load(raw)
    assert isinstance(data, dict), f"{where}: frontmatter must be a mapping"
    return data, body


def _field(block: str, name: str) -> str | None:
    """Read one `- **Name:**` bullet, including its indented continuation lines.

    Labels are allowed to wrap; a wrapped value must not silently truncate the
    assertion that reads it.
    """
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


def _turns(body: str, where: str) -> list[dict]:
    matches = list(TURN_RE.finditer(body))
    assert matches, f"{where}: no author turns"
    turns = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        turns.append(
            {
                "number": int(match.group(1)),
                "role": match.group(2),
                "block": body[match.end():end],
            }
        )
    return turns


def _conversations() -> list[tuple[Path, dict, list[dict]]]:
    files = sorted(
        path
        for path in PROFILES.glob("*/*.md")
        if path.name != "profile.md"
    )
    assert files, "the corpus has no conversations"
    collected = []
    for path in files:
        where = str(path.relative_to(CORPUS))
        front, body = _frontmatter(path.read_text(encoding="utf-8"), where)
        collected.append((path, front, _turns(body, where)))
    return collected


def test_taxonomy_is_closed_and_complete() -> None:
    taxonomy = _taxonomy()
    classes = set(taxonomy["classes"])

    assert classes == {"answer", "start_flow", "activate_skill", "edit", "unknown"}
    assert FLOW_STEP in taxonomy

    for name in classes:
        opens = taxonomy["classes"][name]["opens_state_machine"]
        assert opens is (name in OPENING), f"{name}: opens_state_machine disagrees"

    assert [rule["id"] for rule in taxonomy["decision_rules"]] == [1, 2, 3, 4, 5, 6]
    assert len(taxonomy["tie_breakers"]) == 3


def test_profile_cards_are_well_formed() -> None:
    directories = sorted(path for path in PROFILES.iterdir() if path.is_dir())
    assert len(directories) >= 1, "no profile directories"

    for directory in directories:
        card = directory / "profile.md"
        assert card.is_file(), f"{directory.name}: missing profile.md"
        front, _ = _frontmatter(card.read_text(encoding="utf-8"), directory.name)

        assert front["id"] == directory.name
        assert front["register"] in REGISTERS, f"{directory.name}: bad register"
        assert front["genre"] and front["language"] and front["axis"]


def test_conversation_frontmatter_declares_the_dimensions() -> None:
    seen_ids = set()
    for path, front, _ in _conversations():
        where = str(path.relative_to(CORPUS))
        assert NAME_RE.match(path.name), f"{where}: bad file name"
        assert set(front) == CONVERSATION_KEYS, f"{where}: unexpected frontmatter keys"
        assert front["profile"] == path.parent.name, f"{where}: profile does not match"
        assert front["register"] in REGISTERS, f"{where}: bad register"
        assert front["depth"] in DEPTHS, f"{where}: bad depth"
        assert front["attachment"] in ATTACHMENTS, f"{where}: bad attachment"
        assert front["reference"] in REFERENCES, f"{where}: bad reference"
        assert front["id"] not in seen_ids, f"{where}: duplicate id"
        seen_ids.add(front["id"])


def test_every_turn_declares_its_contract() -> None:
    for path, _front, turns in _conversations():
        where = str(path.relative_to(CORPUS))
        for turn in turns:
            label = f"{where} turn {turn['number']}"
            raw_class = _field(turn["block"], "Class")
            assert raw_class, f"{label}: missing Class"
            name = _bare(raw_class)
            assert name in OPENING | NEVER_OPEN | {FLOW_STEP}, f"{label}: unknown class {name}"

            target = _field(turn["block"], "Target")
            if name in OPENING:
                assert target, f"{label}: opening class must name its Target"
            else:
                assert not target, f"{label}: only opening classes name a Target"

            assert _field(turn["block"], "Must not"), f"{label}: missing Must not"

            why = _field(turn["block"], "Why")
            assert why, f"{label}: missing Why"
            if name != FLOW_STEP:
                assert "rule" in why or "tie-breaker" in why, (
                    f"{label}: Why must cite a decision rule"
                )

            if name == "answer":
                offer = _field(turn["block"], "Offer expected")
                assert offer, f"{label}: answer turns declare Offer expected"
                assert _bare(offer).lower().startswith(("yes", "no")), (
                    f"{label}: Offer expected must start with yes or no"
                )

            if name in NEVER_OPEN:
                must_not = (_field(turn["block"], "Must not") or "").lower()
                assert "open" in must_not, (
                    f"{label}: non-opening turns must forbid opening"
                )


def test_flow_steps_only_follow_an_opening() -> None:
    for path, _front, turns in _conversations():
        where = str(path.relative_to(CORPUS))
        opened = False
        for turn in turns:
            name = _bare(_field(turn["block"], "Class") or "")
            if name == FLOW_STEP:
                assert turn["number"] > 1, f"{where}: a flow_step cannot open a conversation"
                assert opened, f"{where} turn {turn['number']}: flow_step without an opening"
            if name in OPENING:
                opened = True


def test_coverage_matrix() -> None:
    conversations = _conversations()
    classes: set[str] = set()
    genres: set[str] = set()
    per_profile: dict[str, list[dict]] = {}

    for path, front, turns in conversations:
        genres.add(front["genre"])
        for turn in turns:
            name = _bare(_field(turn["block"], "Class") or "")
            if name != FLOW_STEP:
                classes.add(name)
            per_profile.setdefault(front["profile"], []).append(
                {
                    "class": name,
                    "offer": _field(turn["block"], "Offer expected") or "",
                }
            )

    assert classes == OPENING | NEVER_OPEN, f"uncovered classes: {OPENING | NEVER_OPEN} - {classes}"
    assert len(genres) >= 4, f"expected at least 4 genre families, got {genres}"

    for profile, turns in per_profile.items():
        names = [turn["class"] for turn in turns]
        offers = [turn["offer"].lower().startswith("yes") for turn in turns if turn["class"] == "answer"]
        assert any(offers), f"{profile}: needs an answer with an offer expected"
        assert any(not offer for offer in offers), f"{profile}: needs an answer without an offer"
        assert any(name in OPENING for name in names), f"{profile}: needs an opening turn"

    # Negatives dominate: the expensive error is a false open. Flow steps are
    # not opening decisions, so they never count on either side of the ratio.
    decisions = [
        turn
        for turns in per_profile.values()
        for turn in turns
        if turn["class"] != FLOW_STEP
    ]
    total = len(decisions)
    openings = sum(1 for turn in decisions if turn["class"] in OPENING)
    assert openings * 2 <= total, (
        f"opening turns are {openings}/{total}; the corpus must stay negative-heavy"
    )


def test_dimension_coverage() -> None:
    """S6: the matrix is crossed by dimensions, not just enumerated by persona."""
    conversations = _conversations()
    languages = {front["language"] for _, front, _ in conversations}
    attachments = {front["attachment"] for _, front, _ in conversations}
    references = {front["reference"] for _, front, _ in conversations}
    depths = {front["depth"] for _, front, _ in conversations}
    registers = {front["register"] for _, front, _ in conversations}

    assert "en" in languages, "the corpus needs English utterances"
    assert "es-non-native" in languages, "the corpus needs non-native Spanish"
    assert "present" in attachments, "the corpus needs turns carrying an attachment"
    assert "named" in references, "the corpus needs turns naming an existing entity"
    assert "ongoing" in depths, "the corpus needs ongoing conversations"
    assert "ambiguous" in registers, "the corpus needs an ambiguous register"

    per_profile: dict[str, int] = {}
    for path, front, _ in conversations:
        per_profile[front["profile"]] = per_profile.get(front["profile"], 0) + 1
    for profile, count in per_profile.items():
        assert count >= 8, f"{profile}: wave 2 needs at least 8 conversations, got {count}"

    decisions = sum(
        1
        for _, _, turns in conversations
        for turn in turns
        if _bare(_field(turn["block"], "Class") or "") != FLOW_STEP
    )
    assert decisions >= 180, f"the corpus has {decisions} opening decisions; S6 targets 180-240"


# ---------------------------------------------------------------------------
# Runner harness (T5): the simulated pass validates the measurement, not the
# model. Live evaluation is opt-in and never runs here.
# ---------------------------------------------------------------------------


def _runner():
    import intent_corpus_runner  # noqa: PLC0415

    return intent_corpus_runner


def test_runner_agrees_with_the_contract_parser() -> None:
    runner = _runner()
    mine = {
        _frontmatter(path.read_text(encoding="utf-8"), path.name)[0]["id"]: len(turns)
        for path, _front, turns in _conversations()
    }
    theirs = {
        conversation.id: len(conversation.turns)
        for conversation in runner.load_corpus()
    }
    assert mine == theirs


def test_runner_self_consistency_is_perfect() -> None:
    import asyncio  # noqa: PLC0415

    runner = _runner()
    report = asyncio.run(runner.evaluate(runner.simulated_decider, runner.load_corpus(), "simulated"))

    assert len(report.decisions) == 182
    assert report.false_opens == []
    assert report.false_closes == []
    assert report.unavailable == []
    assert report.expected_no_open > 0 and report.expected_open_scored > 0


def test_runner_counts_a_false_open() -> None:
    """A decider that always opens must show every negative as a false-open."""
    import asyncio  # noqa: PLC0415

    runner = _runner()

    async def always_open(_conversation, turn):
        return runner.Decision(True, "start_flow", raw="always-open")

    report = asyncio.run(runner.evaluate(always_open, runner.load_corpus(), "negative-control"))

    assert len(report.false_opens) == report.expected_no_open
    assert report.false_opens, "the negative control must produce false opens"
    assert report.false_closes == []


def test_report_renders_both_rates() -> None:
    import asyncio  # noqa: PLC0415

    runner = _runner()
    report = asyncio.run(
        runner.evaluate(runner.simulated_decider, runner.load_corpus()[:1], "simulated")
    )
    rendered = runner.render_report(report)

    assert "false-open" in rendered
    assert "false-close" in rendered
    assert "Not measured at the gate" in rendered
    assert "accuracy" not in rendered.lower()
