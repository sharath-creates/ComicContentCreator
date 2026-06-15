#!/usr/bin/env python3
"""Phase 2 CLI: ingest raw JSONL into ChromaDB (chunk + embed + index).

Usage:
  python ingest.py index  [--source NAME] [--force]   # build/update the index
  python ingest.py status                              # what's indexed
  python ingest.py query "your question" [-k 5] [--source NAME]

Runs after Phase 1 has produced data/raw/<source>.pages.jsonl.
"""

from __future__ import annotations

import argparse
import logging
import sys

import yaml

from mdrag.catalog import Catalog
from mdrag.index import build_index, query_index


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def cmd_status(cfg: dict) -> None:
    store = cfg.get("storage", {})
    cat = Catalog(store.get("catalog_path", "data/catalog.sqlite"))
    chars, chunks = cat.stats()
    print(f"indexed characters: {chars}   total chunks: {chunks}")
    print(f"{'source':<18}{'characters':>12}{'chunks':>10}")
    print("-" * 40)
    for source, c, ch in cat.by_source():
        print(f"{source:<18}{c:>12}{ch:>10}")
    cat.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Marvel/DC ingest (Phase 2)")
    p.add_argument("command", choices=["index", "status", "query"])
    p.add_argument("text", nargs="?", help="query text (for the query command)")
    p.add_argument("--source")
    p.add_argument("-k", type=int, default=5)
    p.add_argument("--force", action="store_true", help="re-index even if unchanged")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config(args.config)

    if args.command == "status":
        cmd_status(cfg)
    elif args.command == "index":
        srcs = [args.source] if args.source else None
        totals = build_index(cfg, srcs, force=args.force)
        print(
            f"indexed {totals['characters']} characters "
            f"({totals['chunks']} chunks), skipped {totals['skipped']} unchanged"
        )
        cmd_status(cfg)
    elif args.command == "query":
        if not args.text:
            sys.exit('query needs text, e.g.  python ingest.py query "who is Venom?"')
        hits = query_index(cfg, args.text, k=args.k, source=args.source)
        for i, h in enumerate(hits, 1):
            m = h["metadata"]
            print(f"\n[{i}] {m['character']}  ({m['source']})  dist={h['distance']:.3f}")
            print(f"    {h['text'][:240].strip()}...")
            print(f"    {m['url']}")


if __name__ == "__main__":
    main()
