"""Discover character page titles by walking a wiki's category tree.

Strategy: breadth-first over categories. For each category, page through its
members. Pages (namespace 0) become candidate characters; subcategories are
queued for the next depth level if include_subcats is on.

Yields dicts: {"pageid": int, "title": str}. The caller dedups by pageid.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Dict, Iterator, List, Set

from .client import MediaWikiClient

log = logging.getLogger("mdrag.discover")


def discover_titles(
    client: MediaWikiClient,
    categories: List[str],
    *,
    max_depth: int = 0,
    include_subcats: bool = False,
) -> Iterator[Dict]:
    seen_pages: Set[int] = set()
    seen_cats: Set[str] = set()

    # queue items: (category_title, depth)
    queue: deque = deque()
    for cat in categories:
        title = cat if cat.lower().startswith("category:") else f"Category:{cat}"
        queue.append((title, 0))
        seen_cats.add(title)

    while queue:
        cat_title, depth = queue.popleft()
        log.info("scanning %s (depth %d)", cat_title, depth)

        for member in _iter_category_members(client, cat_title):
            ns = member.get("ns")
            if ns == 0:  # an article -> candidate character page
                pid = member["pageid"]
                if pid not in seen_pages:
                    seen_pages.add(pid)
                    yield {"pageid": pid, "title": member["title"]}
            elif ns == 14 and include_subcats and depth < max_depth:
                sub = member["title"]
                if sub not in seen_cats:
                    seen_cats.add(sub)
                    queue.append((sub, depth + 1))


def _iter_category_members(client: MediaWikiClient, cat_title: str) -> Iterator[Dict]:
    """Page through every member of one category (pages and subcategories)."""
    cont: Dict = {}
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": cat_title,
            "cmlimit": "500",
            "cmtype": "page|subcat",
            # NB: 'ns' is NOT a valid cmprop value (MediaWiki returns ns by
            # default); requesting it triggers an API warning. Keep it out.
            "cmprop": "ids|title|type",
        }
        params.update(cont)
        data = client.get(params)
        for m in data.get("query", {}).get("categorymembers", []):
            yield m
        cont = data.get("continue", {})
        if not cont:
            break
