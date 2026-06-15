"""Orchestrate discovery and fetching for a source, with resume support."""

from __future__ import annotations

import logging
from typing import Dict

from tqdm import tqdm

from .client import MediaWikiClient
from .discover import discover_titles
from .fetch import fetch_batch
from .store import SourceStore

log = logging.getLogger("mdrag.pipeline")


def make_client(cfg: Dict, source_cfg: Dict) -> MediaWikiClient:
    return MediaWikiClient(
        api_url=source_cfg["api"],
        contact=cfg.get("contact", "anonymous"),
        use_maxlag=source_cfg.get("use_maxlag", False),
        maxlag=source_cfg.get("maxlag", 5),
        request_delay_seconds=cfg.get("request_delay_seconds", 1.0),
        max_retries=cfg.get("max_retries", 5),
        backoff_base_seconds=cfg.get("backoff_base_seconds", 2.0),
        timeout_seconds=cfg.get("timeout_seconds", 30),
    )


def run_discovery(cfg: Dict, source: str) -> int:
    source_cfg = cfg["sources"][source]
    client = make_client(cfg, source_cfg)
    store = SourceStore(cfg["data_dir"], source)
    disc = source_cfg["discovery"]

    titles = discover_titles(
        client,
        disc["categories"],
        max_depth=disc.get("max_depth", 0),
        include_subcats=disc.get("include_subcats", False),
    )
    n = store.write_titles(titles)
    log.info("[%s] discovered %d candidate pages", source, n)
    return n


def run_fetch(cfg: Dict, source: str) -> int:
    source_cfg = cfg["sources"][source]
    client = make_client(cfg, source_cfg)
    store = SourceStore(cfg["data_dir"], source)

    titles = store.load_titles()
    if not titles:
        log.warning("[%s] no titles found; run discovery first", source)
        return 0

    done = store.load_done()
    pending = [t["pageid"] for t in titles if t["pageid"] not in done]
    log.info(
        "[%s] %d total, %d already done, %d to fetch",
        source, len(titles), len(done), len(pending),
    )

    batch_size = cfg.get("batch_size", 50)
    written = 0
    for i in tqdm(range(0, len(pending), batch_size), desc=f"fetch {source}", unit="batch"):
        batch = pending[i : i + batch_size]
        try:
            records = fetch_batch(client, source, batch)
        except Exception as exc:
            log.error("[%s] batch failed at offset %d: %s", source, i, exc)
            continue  # resume marker means rerun picks these up later
        store.append_pages(records)
        written += len(records)
    log.info("[%s] wrote %d new records (total %d)", source, written, store.count_pages())
    return written


def run_source(cfg: Dict, source: str) -> None:
    run_discovery(cfg, source)
    run_fetch(cfg, source)
