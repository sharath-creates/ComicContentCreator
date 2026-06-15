"""Fetch full page content for discovered titles, in batches of up to 50.

For each page we request:
  - prop=extracts (explaintext)  -> clean prose
  - prop=revisions (content)     -> raw wikitext, for infobox parsing
  - prop=categories              -> category labels
  - prop=pageprops               -> wikibase id etc. (when present)
  - prop=info                    -> canonical url, last revid

Returns one normalized record per page.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from .client import MediaWikiClient
from .parse import parse_infobox

log = logging.getLogger("mdrag.fetch")

LICENSE_BY_SOURCE = {
    "wikipedia_en": "CC BY-SA 4.0",
    "marvel_fandom": "CC BY-SA 3.0",
    "dc_fandom": "CC BY-SA 3.0",
}


def fetch_batch(client: MediaWikiClient, source: str, pageids: List[int]) -> List[Dict]:
    """Fetch a batch of pageids (<=50) and return normalized records."""
    params = {
        "action": "query",
        "pageids": "|".join(str(p) for p in pageids),
        "prop": "extracts|revisions|categories|pageprops|info",
        "explaintext": "1",
        "exsectionformat": "plain",
        "rvprop": "content|ids",
        "rvslots": "main",
        "cllimit": "max",
        "inprop": "url",
        "redirects": "1",
    }
    data = client.get(params)
    pages = data.get("query", {}).get("pages", [])
    records = []
    for page in pages:
        if page.get("missing"):
            continue
        records.append(_normalize(source, page))
    return records


def _normalize(source: str, page: Dict) -> Dict:
    title = page.get("title", "")
    extract = page.get("extract", "") or ""

    wikitext = ""
    revid = None
    revs = page.get("revisions") or []
    if revs:
        rev = revs[0]
        revid = rev.get("revid")
        # formatversion=2 nests content under slots.main.content
        slots = rev.get("slots") or {}
        main = slots.get("main") or {}
        wikitext = main.get("content") or rev.get("content") or ""

    categories = [c.get("title", "") for c in (page.get("categories") or [])]
    pageprops = page.get("pageprops") or {}

    return {
        "id": f"{source}:{page['pageid']}",
        "pageid": page["pageid"],
        "source": source,
        "title": title,
        "url": page.get("fullurl", ""),
        "revid": revid,
        "text": extract,
        "infobox": parse_infobox(wikitext),
        "categories": categories,
        "wikibase_item": pageprops.get("wikibase_item"),
        "license": LICENSE_BY_SOURCE.get(source, "CC BY-SA"),
    }
