"""Deterministic classification of the relation between two sides."""

from .models import Classification, SourceRef, SourceState

def classify(
    local: SourceRef | None,
    remote: SourceRef | None,
    *,
    ambiguous: bool = False,
) -> Classification:
    """Classify one item, most conservative signal first (fail closed).

    Order: unreadable > invalid > ambiguous > missing side > fingerprint
    equality. Uncertainty wins so nothing is silently merged.
    """
    if local is None and remote is None:
        raise ValueError("an item needs at least one side")

    for ref in (local, remote):
        if ref is not None and ref.state is SourceState.UNREADABLE:
            return Classification.UNREADABLE

    for ref in (local, remote):
        if ref is not None and ref.state is SourceState.INVALID:
            return Classification.INVALID

    if ambiguous:
        return Classification.AMBIGUOUS

    if local is None:
        return Classification.ENGRAM_ONLY
    if remote is None:
        return Classification.LOCAL_ONLY

    if local.fingerprint == remote.fingerprint:
        return Classification.EQUIVALENT
    return Classification.DIVERGENT