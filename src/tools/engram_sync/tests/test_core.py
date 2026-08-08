"""Unit tests: models, canonicalize, compare, adapter protocol/registry."""

from datetime import datetime

import pytest

from engram_sync.adapter import AdapterRegistry, DomainAdapter
from engram_sync.canonicalize import canonical_json, fingerprint
from engram_sync.compare import classify
from engram_sync.models import Action, Classification, NormalizedItem, SourceRef, SourceState

def ref(**kw):
    d = dict(location="loc", revision="r", identity={}, metadata={},
             content={}, fingerprint="", state=SourceState.PRESENT)
    d.update(kw)
    return SourceRef(**d)

def test_models_contracts():
    assert {c.value for c in Classification} == {"equivalent", "local-only",
                                                 "engram-only", "divergent",
                                                 "invalid", "unreadable",
                                                 "ambiguous"}
    assert {a.value for a in Action} == {"keep-local", "keep-engram", "defer"}
    assert Action.KEEP_LOCAL.label == "Keep my version"
    for c in Classification:
        assert c.label and "engram" not in c.label.lower()
    item = NormalizedItem(domain="ideas", item_key="k", local=ref())
    assert item.remote is None and item.classification is None

def test_canonical_representation():
    assert canonical_json({"b": 1, "a": {"d": 2, "c": 3}}) == '{"a":{"c":3,"d":2},"b":1}'
    assert canonical_json({"at": datetime(2026, 1, 1)}) == '{"at":"2026-01-01T00:00:00"}'

def test_volatile_fields_excluded_by_default():
    with_scan = {"content": "x", "scan_time": "2026-08-07T00:00:00"}
    assert canonical_json(with_scan) == canonical_json({"content": "x"})
    assert canonical_json(with_scan, exclude_volatile=False) != '{"content":"x"}'

def test_fingerprint_stable_and_sensitive():
    assert fingerprint({"c": "h"}) == fingerprint({"c": "h"})
    assert fingerprint({"c": "h"}) != fingerprint({"c": "h!"})
    assert len(fingerprint({"c": "h"})) == 64

def test_classify_sides():
    assert classify(ref(), None) is Classification.LOCAL_ONLY
    assert classify(None, ref()) is Classification.ENGRAM_ONLY
    assert classify(ref(fingerprint="a"), ref(fingerprint="a")) is Classification.EQUIVALENT
    assert classify(ref(fingerprint="a"), ref(fingerprint="b")) is Classification.DIVERGENT

def test_classify_fail_closed_order():
    assert classify(ref(fingerprint="a", state=SourceState.INVALID),
                    ref(fingerprint="b")) is Classification.INVALID
    assert classify(ref(state=SourceState.UNREADABLE),
                    ref(state=SourceState.INVALID)) is Classification.UNREADABLE
    assert classify(ref(fingerprint="a"), ref(fingerprint="a"), ambiguous=True) \
        is Classification.AMBIGUOUS

def test_classify_missing_both_raises():
    with pytest.raises(ValueError):
        classify(None, None)

class FakeAdapter:
    domain = "ideas"

    def discover(self): return []
    def preview(self, item, action): return None
    def apply(self, operation): return None

def test_registry_register_get_domains():
    reg = AdapterRegistry()
    adapter = FakeAdapter()
    reg.register(adapter)
    assert reg.get("ideas") is adapter and reg.domains() == ["ideas"]

def test_registry_errors():
    reg = AdapterRegistry()
    reg.register(FakeAdapter())
    with pytest.raises(ValueError):
        reg.register(FakeAdapter())
    with pytest.raises(KeyError):
        reg.get("nope")

def test_protocol_shape():
    assert isinstance(FakeAdapter(), DomainAdapter)