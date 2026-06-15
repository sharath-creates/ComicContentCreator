"""Local storage + resume checkpoints for one source.

Layout under data_dir (per source <name>):
  <name>.titles.jsonl   discovered candidate pages (pageid, title)
  <name>.pages.jsonl    fetched character records (append-only, one per line)
  <name>.done.txt       pageids already written (resume marker)

Append-only JSONL means a crash never corrupts past work, and re-running skips
anything whose pageid is already in <name>.done.txt.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterator, Set


class SourceStore:
    def __init__(self, data_dir: str, source: str) -> None:
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.source = source
        self.titles_path = self.dir / f"{source}.titles.jsonl"
        self.pages_path = self.dir / f"{source}.pages.jsonl"
        self.done_path = self.dir / f"{source}.done.txt"

    # ---- discovery side ----
    def write_titles(self, titles: Iterator[Dict]) -> int:
        n = 0
        with self.titles_path.open("w", encoding="utf-8") as f:
            for t in titles:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
                n += 1
        return n

    def load_titles(self) -> list:
        if not self.titles_path.exists():
            return []
        with self.titles_path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    # ---- fetch side ----
    def load_done(self) -> Set[int]:
        if not self.done_path.exists():
            return set()
        with self.done_path.open(encoding="utf-8") as f:
            return {int(x) for x in f.read().split() if x.strip()}

    def append_pages(self, records: list) -> None:
        with self.pages_path.open("a", encoding="utf-8") as pf, \
             self.done_path.open("a", encoding="utf-8") as df:
            for rec in records:
                pf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                df.write(f"{rec['pageid']}\n")
            pf.flush()
            df.flush()
            os.fsync(pf.fileno())
            os.fsync(df.fileno())

    def count_pages(self) -> int:
        if not self.pages_path.exists():
            return 0
        with self.pages_path.open(encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
