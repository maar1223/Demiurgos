"""Domain adapter protocol and registry (Phase-1 adapters plug in here)."""

from typing import Protocol, runtime_checkable

from .models import Action, ApplyResult, AuthorizedOperation, NormalizedItem, Preview

@runtime_checkable
class DomainAdapter(Protocol):
    """Read-only discovery plus separately authorized apply."""

    domain: str

    def discover(self) -> list[NormalizedItem]: ...

    def preview(self, item: NormalizedItem, action: Action) -> Preview: ...

    def apply(self, operation: AuthorizedOperation) -> ApplyResult: ...

class AdapterRegistry:
    """Maps domain names to adapters; deterministic and collision-safe."""

    def __init__(self) -> None:
        self._adapters: dict[str, DomainAdapter] = {}

    def register(self, adapter: DomainAdapter) -> None:
        if adapter.domain in self._adapters:
            raise ValueError(f"adapter already registered for domain: {adapter.domain}")
        self._adapters[adapter.domain] = adapter

    def get(self, domain: str) -> DomainAdapter:
        try:
            return self._adapters[domain]
        except KeyError:
            raise KeyError(f"no adapter registered for domain: {domain}") from None

    def domains(self) -> list[str]:
        return sorted(self._adapters)