"""Manual CLI: scan shows what differs and confirm applies an explicit choice.
Daemon triggers live in :mod:`engram_sync.daemon` and never auto-apply work."""

import argparse
import json
import os
import sys
from pathlib import Path

from .adapter import AdapterRegistry
from .adapters import register_phase1
from .confirm import ConfirmError, ConfirmedChoice
from .engram_client import EngramClient, EngramError
from .integration import apply_confirmation
from .models import Action
from .views import build_report

WORLD = os.environ.get("DEMIURGOS_WORLD") or "vibrantes"


def _registry(root: Path, *, write: bool = False) -> AdapterRegistry:
    client = EngramClient(mode="read-write" if write else "read")
    return register_phase1(AdapterRegistry(), client, WORLD,
                           ideas_primary=str(root / "mundos" / "Ideas"),
                           ideas_secondary=str(root / "mundos" / WORLD / "ideas"),
                           estado=str(root / ".demiurgos-estado.json"),
                           templates_catalog=str(root / "plantillas" / "_catalog.json"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="engram-sync",
        description="Reconcile your workspace with saved memory — no writes without your confirmation.")
    parser.add_argument("--root", default=".", metavar="PATH",
                        help="workspace root (accepted before or after the command)")
    sub = parser.add_subparsers(dest="command", required=True)
    p_scan = sub.add_parser("scan", help="scan and report differences")
    p_scan.add_argument("--root", dest="root", default=argparse.SUPPRESS,
                        metavar="PATH", help="workspace root")
    p_scan.add_argument("domain", nargs="?", default=None,
                        help="domain: ideas, arc-state, templates, or 'domains'")
    p_scan.add_argument("--session-start", action="store_true",
                        help="informational counts only; never repairs")
    p_scan.set_defaults(func=_scan_cmd)
    p_report = sub.add_parser("report", help="alias for scan")
    p_report.add_argument("--root", dest="root", default=argparse.SUPPRESS,
                          metavar="PATH", help="workspace root")
    p_report.set_defaults(func=_scan_cmd)
    p_confirm = sub.add_parser("confirm", help="apply an explicit choice from a JSON file")
    p_confirm.add_argument("--root", dest="root", default=argparse.SUPPRESS,
                           metavar="PATH", help="workspace root")
    p_confirm.add_argument("choices", help="JSON file of confirmed choices")
    p_confirm.add_argument("--confirm", default="", help="required exact confirmation token: APPLY")
    p_confirm.add_argument("--dry-run", action="store_true",
                           help="validate the operation without journal or data writes")
    p_confirm.set_defaults(func=_confirm_cmd)
    return parser


def _scan_cmd(args) -> int:
    registry = _registry(Path(args.root))
    if args.domain == "domains":
        print("\n".join(registry.domains()))
        return 0
    items = []
    for name in [args.domain] if args.domain else registry.domains():
        try:
            items.extend(registry.get(name).discover())
        except EngramError as err:
            print(f"note: saved memory is unreachable for {name} ({err}); "
                  "local data is unchanged.", file=sys.stderr)
    report = build_report(items)
    if args.session_start:
        print(f"Session start: {report.actionable} item(s) differ from saved memory.")
        print("Nothing was changed.")
        return 0
    print(report)
    return 0


def _confirm_cmd(args) -> int:
    root = Path(args.root)
    from .journal import RunJournal
    journal = RunJournal(root / ".demiurgos-sync")
    try:
        payload = json.loads(Path(args.choices).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("confirmation") != "APPLY":
            raise ValueError("choices file must contain confirmation=APPLY")
        rows = payload.get("choices")
        if not isinstance(rows, list):
            raise ValueError("choices must be a list")
        choices = [ConfirmedChoice(domain=r["domain"], item_key=r["item_key"],
                                   action=Action(r["action"]),
                                   source_revision=r["source_revision"]) for r in rows]
    except (OSError, TypeError, ValueError, KeyError) as err:
        print(f"not applied: invalid choices file ({err})", file=sys.stderr)
        return 2
    try:
        results = apply_confirmation(_registry(root, write=not args.dry_run), choices,
                                      journal, confirmation=args.confirm,
                                      dry_run=args.dry_run)
    except ConfirmError as err:
        print(f"not applied: {err}", file=sys.stderr)
        return 2
    for result in results:
        flag = "applied" if result.applied else "not applied"
        print(f"{flag}: {result.item_key} — {result.message}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
