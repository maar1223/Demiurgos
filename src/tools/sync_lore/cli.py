"""
cli.py — CLI entry point for sync-lore.

Parses args, resolves configuration, and dispatches to the pipeline.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .schemas import ProviderConfig


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_ENDPOINT = "https://opencode.ai/zen/go/v1"
DEFAULT_MODEL = "qwen3.6-plus"
DEFAULT_TIMEOUT = 60
DEFAULT_API_KEY_ENV = "QWEN_API_KEY"
DEFAULT_MODE = "text"
DEFAULT_OUTPUT = "./output"
DEFAULT_WORKERS = 5


# ---------------------------------------------------------------------------
# Configuration resolver
# ---------------------------------------------------------------------------

def build_config(args: argparse.Namespace) -> tuple[ProviderConfig, dict]:
    """
    Build ProviderConfig and runtime options from resolved priority:

        CLI flags > config file > env vars > defaults

    Returns:
        (ProviderConfig, runtime_opts dict)
        runtime_opts contains: input_path, mode, dry_run, output, engram, workers
    """
    # Start with defaults
    provider = "qwen"
    endpoint = DEFAULT_ENDPOINT
    model = DEFAULT_MODEL
    timeout = DEFAULT_TIMEOUT
    api_key_env = DEFAULT_API_KEY_ENV

    # Priority 4: defaults (already set)

    # Priority 3: environment variables
    if os.environ.get("QWEN_ENDPOINT"):
        endpoint = os.environ["QWEN_ENDPOINT"]
    if os.environ.get("QWEN_MODEL"):
        model = os.environ["QWEN_MODEL"]
    if os.environ.get("QWEN_TIMEOUT"):
        try:
            timeout = int(os.environ["QWEN_TIMEOUT"])
        except ValueError:
            pass
    if os.environ.get("QWEN_PROVIDER"):
        provider = os.environ["QWEN_PROVIDER"]

    # Priority 2: config file (--config)
    if args.config:
        config_path = Path(args.config)
        if not config_path.exists():
            print(f"ERROR: Config file not found: {args.config}", file=sys.stderr)
            sys.exit(1)
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                file_config = json.load(f)
            if not isinstance(file_config, dict):
                print(f"ERROR: Config file {args.config} must be a JSON object", file=sys.stderr)
                sys.exit(1)
            if "provider" in file_config:
                provider = file_config["provider"]
            if "endpoint" in file_config:
                endpoint = file_config["endpoint"]
            if "model" in file_config:
                model = file_config["model"]
            if "timeout" in file_config:
                timeout = int(file_config["timeout"])
            if "api_key_env" in file_config:
                api_key_env = file_config["api_key_env"]
        except json.JSONDecodeError as exc:
            print(f"ERROR: Invalid JSON in config file {args.config}: {exc}", file=sys.stderr)
            sys.exit(1)

    # Priority 1: CLI flags (highest priority)
    # (CLI flags for provider/model/endpoint would be added via extras,
    #  but spec defines config priority via --config JSON file)

    provider_config = ProviderConfig(
        provider=provider,
        endpoint=endpoint,
        model=model,
        timeout=timeout,
        api_key_env=api_key_env,
    )

    runtime_opts = {
        "input_path": Path(args.input) if args.input else Path("."),
        "mode": args.mode,
        "dry_run": args.dry_run,
        "output": Path(args.output),
        "engram": args.engram,
        "workers": args.workers,
    }

    return provider_config, runtime_opts


# ---------------------------------------------------------------------------
# CLI definition
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser with all 7 flags."""
    parser = argparse.ArgumentParser(
        prog="sync-lore",
        description="sync-lore \u2014 Lore ingestion tool. "
                    "Extracts structured entities from narrative lore documents (.md, .docx, .pdf) "
                    "and builds a queryable lore-index.json.",
    )
    # Positional: input path
    parser.add_argument(
        "input",
        nargs="?",
        default=".",
        help="File or directory to process (default: current directory)",
    )
    # Flag 1: --mode
    parser.add_argument(
        "--mode",
        choices=["text", "images", "both"],
        default=DEFAULT_MODE,
        help="Processing mode (default: text)",
    )
    # Flag 2: --dry-run
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview processing plan without LLM calls or file output",
    )
    # Flag 3: --output
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="Output directory for lore-index.json (default: ./output)",
    )
    # Flag 4: --config
    parser.add_argument(
        "--config",
        default=None,
        help="Provider config JSON file (provider, endpoint, model, timeout, api_key_env)",
    )
    # Flag 5: --engram
    parser.add_argument(
        "--engram",
        action="store_true",
        help="Persist lore-index.json to Engram memory",
    )
    # Flag 6: --workers
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Max concurrent LLM calls (default: 5)",
    )
    return parser


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point for sync-lore CLI."""
    parser = _build_parser()
    args = parser.parse_args()

    # Resolve configuration
    provider_config, runtime_opts = build_config(args)

    # Validate input path exists
    input_path = runtime_opts["input_path"]
    if not input_path.exists():
        print(f"ERROR: Input path does not exist: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Validate API key for non-dry-run modes
    if not runtime_opts["dry_run"]:
        api_key = os.environ.get(provider_config.api_key_env) or os.environ.get("OPENCODE_API_KEY") or os.environ.get("OPENCODE_GO_API_KEY")
        if not api_key:
            print(
                f"\u26a0 {provider_config.provider} API key not set "
                f"({provider_config.api_key_env}, OPENCODE_API_KEY, or OPENCODE_GO_API_KEY)",
                file=sys.stderr,
            )
            sys.exit(1)

    # Discover world (may be None for generic mode)
    from .utils.world import discover_world
    world = discover_world()
    if world:
        print(f"\U0001f30d Mundo activo: {world}", file=sys.stderr)
    else:
        print("\u2139 Modo gen\u00e9rico — sin mundo asociado", file=sys.stderr)

    mode = runtime_opts["mode"]
    workers = runtime_opts["workers"]
    output_dir = runtime_opts["output"]

    print(f"Provider: {provider_config.provider} ({provider_config.model})", file=sys.stderr)
    print(f"Mode: {mode}", file=sys.stderr)
    print(f"Input: {input_path}", file=sys.stderr)
    print(f"Output: {output_dir}", file=sys.stderr)

    # ---- Dry-run: preview without LLM calls ----
    if runtime_opts["dry_run"]:
        print("\n[Dry-run mode — no LLM calls, no output written]", file=sys.stderr)
        from .lore_indexer import _scan_files
        files = _scan_files(input_path)
        if not files:
            print("  No supported files found.", file=sys.stderr)
            sys.exit(0)

        # Group by format
        md_files = [f for f in files if f.suffix.lower() == ".md"]
        docx_files = [f for f in files if f.suffix.lower() == ".docx"]
        pdf_files = [f for f in files if f.suffix.lower() == ".pdf"]

        print(f"\n  Files to process: {len(files)}", file=sys.stderr)
        if md_files:
            print(f"    .md:  {len(md_files)}", file=sys.stderr)
        if docx_files:
            print(f"    .docx: {len(docx_files)}", file=sys.stderr)
        if pdf_files:
            print(f"    .pdf: {len(pdf_files)}", file=sys.stderr)

        # Estimate chunks
        from .utils.chunker import estimate_tokens
        total_est = 0
        for f in files:
            try:
                text = f.read_text(encoding="utf-8") if f.suffix == ".md" else ""
                total_est += estimate_tokens(text)
            except Exception:
                pass

        print(f"  Estimated tokens: ~{total_est}", file=sys.stderr)
        print(f"  Estimated chunks: ~{max(1, total_est // 2000)}", file=sys.stderr)
        print(f"  Provider: {provider_config.provider} ({provider_config.model})", file=sys.stderr)
        print(f"  World: {world or 'generic'}", file=sys.stderr)
        print(f"  Mode: {mode}", file=sys.stderr)
        print(f"  Workers: {workers}", file=sys.stderr)
        print(f"  Output: {output_dir}/lore-index.json", file=sys.stderr)
        if runtime_opts["engram"]:
            print(f"  Engram: yes (topic: lore/{world or 'generic'}/index)", file=sys.stderr)
        print("\n  Pipeline ready. Run without --dry-run to process.", file=sys.stderr)
        sys.exit(0)

    # ---- Live mode: full pipeline ----
    print("\n[Live mode — processing files]", file=sys.stderr)

    # Load provider
    from .providers import load_provider
    provider = load_provider(provider_config)

    # Run pipeline
    from .lore_indexer import process_lore
    chunk_results, image_entries, files_processed, files_omitted, chunks_failed = process_lore(
        input_path=input_path,
        provider=provider,
        mode=mode,
        workers=workers,
    )

    # Build index
    from .index_builder import build_index
    index = build_index(
        chunk_results=chunk_results,
        image_entries=image_entries,
        world=world,
        mode=mode,
    )

    # Update meta with pipeline stats
    index.meta.chunks_processed = len(chunk_results)

    # Persist
    from .persistence import write_lore_index, try_engram_save, print_report
    output_path = write_lore_index(index, output_dir)

    engram_ok = False
    if runtime_opts["engram"]:
        engram_ok = try_engram_save(index, world)

    # Report
    print_report(
        index=index,
        output_path=output_path,
        engram_ok=engram_ok,
        files_processed=files_processed,
        files_omitted=files_omitted,
        chunks_failed=chunks_failed,
        images_processed=len(image_entries),
    )


if __name__ == "__main__":
    main()
