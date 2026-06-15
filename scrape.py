#!/usr/bin/env python3
"""Phase 1 CLI: extract Marvel & DC character data to local JSONL.

Usage:
  python scrape.py discover [--source NAME]   # find character page titles
  python scrape.py fetch    [--source NAME]   # download content (resumable)
  python scrape.py run      [--source NAME]   # discover + fetch
  python scrape.py status                     # how much is on disk

Omit --source to process every source in config.yaml.
"""

from __future__ import annotations

import argparse
import logging
import sys

import yaml

from mdrag.pipeline import run_discovery, run_fetch, run_source
from mdrag.store import SourceStore


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_sources(cfg: dict, source: str | None) -> list:
    if source:
        if source not in cfg["sources"]:
            sys.exit(f"unknown source '{source}'. options: {list(cfg['sources'])}")
        return [source]
    return list(cfg["sources"])


def cmd_status(cfg: dict) -> None:
    print(f"{'source':<18}{'titles':>10}{'fetched':>10}")
    print("-" * 38)
    for src in cfg["sources"]:
        store = SourceStore(cfg["data_dir"], src)
        print(f"{src:<18}{len(store.load_titles()):>10}{store.count_pages():>10}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Marvel/DC extraction (Phase 1)")
    parser.add_argument("command", choices=["discover", "fetch", "run", "status"])
    parser.add_argument("--source", help="single source name (default: all)")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config(args.config)

    if args.command == "status":
        cmd_status(cfg)
        return

    for src in resolve_sources(cfg, args.source):
        if args.command == "discover":
            run_discovery(cfg, src)
        elif args.command == "fetch":
            run_fetch(cfg, src)
        elif args.command == "run":
            run_source(cfg, src)

    if args.command != "status":
        print("\nDone. Current state:")
        cmd_status(cfg)


if __name__ == "__main__":
    main()
