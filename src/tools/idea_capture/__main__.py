"""Native idea-capture command line (python -m idea_capture).

Commands
--------
smoke   (default)  Safe local dry-run: temporary root, in-memory publisher,
                   synthetic updates. No credentials, no network, no production
                   paths. Exercises fail-closed policy, Save / Change world /
                   Cancel, durable worker processing, and the outbox.
serve              Compatibility-only Telegram long-poll entrypoint. Fail-closed guards:
                   requires TELEGRAM_BOT_TOKEN, a non-empty allowlist in
                   config/idea-capture.yaml, an existing world directory, and
                   single ownership of the bot (PID lock; optional Hermes
                   health probe). Do NOT run against production credentials
                   until staging parity is proven.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .runtime import CONFIG_PATH, run_serve, run_smoke


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m idea_capture",
        description="Native Hermes/Telegram idea capture runtime.")
    parser.add_argument("--config", default=str(CONFIG_PATH),
                        help="config/idea-capture.yaml to load (default repo path)")
    sub = parser.add_subparsers(dest="command")
    sub.required = False

    smoke = sub.add_parser("smoke", help="safe offline dry-run (default)")
    smoke.add_argument("--json", action="store_true", help="print the report as JSON")

    serve = sub.add_parser(
        "serve", help="compatibility-only Telegram long-poll entrypoint (guarded)",
    )
    serve.add_argument("--world", default="", help="active world (or DEMIURGOS_WORLD)")
    serve.add_argument("--mundos", default="", help="mundos root (default <repo>/mundos)")
    serve.add_argument("--state", default="", help="sqlite state path (default <repo>/data/idea-capture.sqlite3)")
    serve.add_argument("--hermes-health-url", default="",
                       help="optional Hermes gateway health probe before starting")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "serve":
        return run_serve(args)
    report = run_smoke(args.config)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["ok"] else 1
    print(f"idea-capture smoke: {'PASS' if report['ok'] else 'FAIL'}")
    print(f"  config        : {report['config_path']}")
    print(f"  authorized    : {report['config']['authorized_private_chats']} private chats, "
          f"{report['config']['authorized_groups']} groups (empty => fail closed)")
    for step in report["steps"]:
        print(f"  [{'OK ' if step['ok'] else 'FAIL'}] {step['name']}"
              + (f" — {step['detail']}" if step.get("detail") else ""))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
