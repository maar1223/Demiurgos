"""Unit tests for the verified-evidence store (S5)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _path in (str(_HERE.parent), str(_HERE.parents[2])):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from relation_evidence import (
    forget,
    load_evidence,
    record,
    record_many,
    store_path,
    verified_ids,
)


def test_record_and_load_roundtrip(tmp_path: Path) -> None:
    assert record(tmp_path, left="alpha", right="beta", side="alpha", quote="Alpha names Beta.")
    stored = load_evidence(tmp_path)
    assert len(stored) == 1
    assert stored[("alpha", "beta")].side == "alpha"
    assert stored[("alpha", "beta")].quote == "Alpha names Beta."


def test_pair_is_unordered_so_a_second_side_does_not_duplicate(tmp_path: Path) -> None:
    record(tmp_path, left="alpha", right="beta", side="alpha", quote="Alpha names Beta.")
    record(tmp_path, left="beta", right="alpha", side="beta", quote="Beta names Alpha.")
    stored = load_evidence(tmp_path)
    assert list(stored) == [("alpha", "beta")]
    assert stored[("alpha", "beta")].side == "beta"


def test_record_rejects_unusable_input(tmp_path: Path) -> None:
    assert not record(tmp_path, left="alpha", right="beta", side="gamma", quote="q")
    assert not record(tmp_path, left="alpha", right="beta", side="alpha", quote="   ")
    assert not record(tmp_path, left="alpha", right="alpha", side="alpha", quote="q")
    assert load_evidence(tmp_path) == {}


def test_identical_record_is_a_noop(tmp_path: Path) -> None:
    assert record(tmp_path, left="a1", right="b1", side="a1", quote="A names B.")
    assert not record(tmp_path, left="a1", right="b1", side="a1", quote="A names B.")
    assert not store_path(tmp_path).with_name("x").exists()


def test_verified_ids_returns_the_pair_when_the_quote_survives(tmp_path: Path) -> None:
    record(tmp_path, left="alpha", right="beta", side="alpha", quote="Alpha names Beta.")
    body = "Intro. Alpha names Beta in passing. Outro."
    assert verified_ids(tmp_path, source_key="alpha", body=body) == {"beta"}


def test_verified_ids_ignores_the_side_that_does_not_store_it(tmp_path: Path) -> None:
    record(tmp_path, left="alpha", right="beta", side="alpha", quote="Alpha names Beta.")
    assert verified_ids(tmp_path, source_key="beta", body="Alpha names Beta.") == set()


def test_verified_ids_self_invalidates_when_the_body_changes(tmp_path: Path) -> None:
    record(tmp_path, left="alpha", right="beta", side="alpha", quote="Alpha names Beta.")
    rewritten = "Alpha now talks about something else entirely."
    assert verified_ids(tmp_path, source_key="alpha", body=rewritten) == set()


def test_forget_drops_the_pair_and_is_order_independent(tmp_path: Path) -> None:
    record(tmp_path, left="alpha", right="beta", side="alpha", quote="Alpha names Beta.")
    assert forget(tmp_path, "beta", "alpha")
    assert not forget(tmp_path, "alpha", "beta")
    assert load_evidence(tmp_path) == {}


def test_corrupt_store_is_ignored(tmp_path: Path) -> None:
    path = store_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    assert load_evidence(tmp_path) == {}


def test_record_many_writes_sorted_deduped_entries(tmp_path: Path) -> None:
    added = record_many(
        tmp_path,
        [
            ("zeta", "alpha", "alpha", "Alpha names Zeta."),
            ("beta", "alpha", "alpha", "Alpha names Beta."),
            ("beta", "alpha", "alpha", "Alpha names Beta."),
        ],
    )
    assert added == 2
    data = json.loads(store_path(tmp_path).read_text(encoding="utf-8"))
    assert [entry["pair"] for entry in data["evidenced"]] == [["alpha", "beta"], ["alpha", "zeta"]]
