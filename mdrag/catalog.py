"""SQLite catalog of indexed characters: provenance + chunk counts.

Lets you answer "what's indexed", "which source", "how many chunks", and
"has this revision already been indexed" without scanning ChromaDB.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional, Tuple


class Catalog:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS characters (
                id        TEXT PRIMARY KEY,
                source    TEXT,
                title     TEXT,
                url       TEXT,
                revid     INTEGER,
                n_chunks  INTEGER,
                indexed_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        self.conn.commit()

    def is_indexed(self, char_id: str, revid: Optional[int]) -> bool:
        row = self.conn.execute(
            "SELECT revid FROM characters WHERE id = ?", (char_id,)
        ).fetchone()
        return bool(row) and row[0] == revid

    def upsert_character(
        self, char_id: str, source: str, title: str, url: str,
        revid: Optional[int], n_chunks: int,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO characters (id, source, title, url, revid, n_chunks)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                source=excluded.source, title=excluded.title, url=excluded.url,
                revid=excluded.revid, n_chunks=excluded.n_chunks,
                indexed_at=datetime('now')
            """,
            (char_id, source, title, url, revid, n_chunks),
        )
        self.conn.commit()

    def stats(self) -> Tuple[int, int]:
        row = self.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(n_chunks), 0) FROM characters"
        ).fetchone()
        return int(row[0]), int(row[1])

    def by_source(self):
        return self.conn.execute(
            "SELECT source, COUNT(*), COALESCE(SUM(n_chunks),0) "
            "FROM characters GROUP BY source ORDER BY source"
        ).fetchall()

    def close(self) -> None:
        self.conn.close()
