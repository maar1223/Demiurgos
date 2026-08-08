"""Plain-language reports (severity/action labels, no storage jargon) and
bounded previews (file Diff / Engram content; never written to the journal)."""

import difflib
from dataclasses import dataclass

from .models import Action, Classification, NormalizedItem, Preview, SourceRef

_SEVERITY = {Classification.EQUIVALENT: "info", Classification.LOCAL_ONLY: "info",
             Classification.ENGRAM_ONLY: "info", Classification.DIVERGENT: "warning",
             Classification.AMBIGUOUS: "warning", Classification.INVALID: "error",
             Classification.UNREADABLE: "error"}
_ACTION = {Classification.EQUIVALENT: Action.DEFER, Classification.LOCAL_ONLY: Action.KEEP_LOCAL,
           Classification.ENGRAM_ONLY: Action.KEEP_ENGRAM, Classification.DIVERGENT: Action.KEEP_LOCAL,
           Classification.AMBIGUOUS: Action.DEFER, Classification.INVALID: Action.DEFER,
           Classification.UNREADABLE: Action.DEFER}
MAX_DIFF_LINES, MAX_PREVIEW_CHARS = 40, 500


def severity(item: NormalizedItem) -> str:
    return _SEVERITY.get(item.classification, "info")


def action_for(item: NormalizedItem) -> Action:
    return _ACTION.get(item.classification, Action.DEFER)


@dataclass(frozen=True)
class Report:
    lines: list[str]
    counts: dict[str, int]
    actionable: int

    def __str__(self) -> str:
        if not self.lines:
            return "Everything is in agreement."
        return "\n".join(self.lines) + f"\n\n{self.actionable} item(s) need attention."


def build_report(items: list[NormalizedItem]) -> Report:
    counts: dict[str, int] = {}
    lines: list[str] = []
    actionable = 0
    for item in items:
        label = item.classification.label if item.classification else "Needs your choice"
        counts[label] = counts.get(label, 0) + 1
        if item.classification is not Classification.EQUIVALENT:
            actionable += 1
        lines.append(f"[{severity(item)}] {item.domain} · {item.item_key} — {label}."
                     f" {action_for(item).label}.")
    return Report(lines=lines, counts=counts, actionable=actionable)


def scan(registry, domain: str | None = None) -> list[NormalizedItem]:
    """Discover one domain (or all), ordered by (domain, item_key); read-only."""
    domains = [domain] if domain else registry.domains()
    items = [i for name in domains for i in registry.get(name).discover()]
    items.sort(key=lambda i: (i.domain, i.item_key))
    return items


def _text(source: SourceRef | None) -> str:
    if source is None:
        return ""
    raw = source.content.get("text", "")
    return str(raw) if raw else ""


def file_diff(local: SourceRef | None, remote: SourceRef | None) -> str:
    head = f"{local.location if local else '(no local)'} vs {remote.location if remote else '(no saved copy)'}"
    lines = list(difflib.unified_diff(_text(local).splitlines(), _text(remote).splitlines(),
                                      lineterm="", fromfile=local.location if local else "local",
                                      tofile="(saved)"))
    return head + "\n" + "\n".join(lines[:MAX_DIFF_LINES]) + \
        ("\n… more changes omitted" if len(lines) > MAX_DIFF_LINES else "")


def engram_preview(remote: SourceRef | None, *, limit: int = MAX_PREVIEW_CHARS) -> str:
    if remote is None:
        return "(no saved copy)"
    meta = remote.metadata
    topic = meta.get("topic") or "(no topic)"
    title = meta.get("title") or ""
    title = str(title) if title else "(untitled saved copy)"
    content = _text(remote)
    truncated = content[:limit] + ("… (saved copy continues)" if len(content) > limit else "")
    return f"Saved copy · {topic} · {title}\n{truncated}"


def preview_for(item: NormalizedItem, action: Action) -> Preview:
    label = item.classification.label if item.classification else "Ready to review"
    if item.local is not None:
        detail = file_diff(item.local, item.remote)
    elif item.remote is not None:
        detail = engram_preview(item.remote)
    else:
        detail = "(nothing to preview)"
    return Preview(item_key=item.item_key, action=action, label=label, detail=detail)
