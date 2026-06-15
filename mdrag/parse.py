"""Parse the infobox out of raw wikitext into a flat dict.

Character pages on these wikis carry a template (Marvel/DC use a
"Character Infobox" / "Marvel Database" style template) with the structured
facts: real name, alignment, affiliation, first appearance, etc. We pull every
template parameter generically rather than hard-coding field names, since
template schemas differ between Wikipedia, Marvel Fandom, and DC Fandom.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import mwparserfromhell

log = logging.getLogger("mdrag.parse")


def parse_infobox(wikitext: Optional[str]) -> Dict[str, str]:
    if not wikitext:
        return {}
    try:
        code = mwparserfromhell.parse(wikitext)
    except Exception as exc:  # parsing should never crash the run
        log.warning("infobox parse failed: %s", exc)
        return {}

    out: Dict[str, str] = {}
    for template in code.filter_templates():
        name = str(template.name).strip().lower()
        # Heuristic: only mine templates that look like an infobox/character box.
        if "infobox" not in name and "character" not in name and "database" not in name:
            continue
        for param in template.params:
            key = str(param.name).strip().lower()
            value = param.value.strip_code().strip()
            if key and value and key not in out:
                out[key] = value
    return out
