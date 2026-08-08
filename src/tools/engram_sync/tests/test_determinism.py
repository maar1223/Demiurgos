"""RED: determinism — malformed Idea, identical results, zero writes (1.1)."""

from engram_sync.canonicalize import fingerprint
from engram_sync.compare import classify
from engram_sync.models import Classification, SourceRef, SourceState

def _build_invalid_ref(location: str) -> SourceRef:
    identity = {"id": 71, "slug": "portal-stones"}
    metadata = {"timestamp": 1779711257}  # epoch seconds: schema violation
    content = {"body": "Portal stones connect the vaults."}
    return SourceRef(location=location, revision="rev-1", identity=identity,
                     metadata=metadata, content=content,
                     fingerprint=fingerprint({"identity": identity, "metadata": metadata,
                                              "content": content}),
                     state=SourceState.INVALID)

def _full_fingerprint(ref: SourceRef) -> str:
    return fingerprint({"identity": ref.identity, "metadata": ref.metadata, "content": ref.content})

def test_scan_repeats_identically_with_zero_writes(tmp_path, malformed_idea_file, tree_snapshot):
    original_text = malformed_idea_file.read_text(encoding="utf-8")
    before = tree_snapshot(tmp_path)

    first = _build_invalid_ref(str(malformed_idea_file))
    first_canonical = _full_fingerprint(first)
    first_class = classify(first, None)

    second = _build_invalid_ref(str(malformed_idea_file))
    second_canonical = _full_fingerprint(second)
    second_class = classify(second, None)

    assert first == second
    assert first.fingerprint == second.fingerprint
    assert first_canonical == second_canonical
    assert first_class is Classification.INVALID  # actionable and deterministic
    assert second_class is Classification.INVALID

    # Zero writes: nothing created, modified, or resized during the scan.
    assert tree_snapshot(tmp_path) == before
    assert malformed_idea_file.read_text(encoding="utf-8") == original_text