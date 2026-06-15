"""Turn a character record into overlapping text chunks with metadata.

Character bios are long. We split the prose into windows of roughly
``max_chars`` characters with ``overlap_chars`` of overlap, breaking on a
newline or space near the boundary so chunks don't cut mid-word. Every chunk
carries the metadata the RAG layer filters and cites on (character, source,
url, chunk index).
"""

from __future__ import annotations

from typing import Dict, List


def chunk_record(
    rec: Dict,
    *,
    max_chars: int = 1500,
    overlap_chars: int = 200,
) -> List[Dict]:
    text = (rec.get("text") or "").strip()
    if not text:
        return []

    spans = _windows(text, max_chars, overlap_chars)
    chunks: List[Dict] = []
    for i, span in enumerate(spans):
        chunks.append(
            {
                "id": f"{rec['id']}::{i}",
                "text": span,
                "character": rec.get("title", ""),
                "source": rec.get("source", ""),
                "url": rec.get("url", ""),
                "revid": rec.get("revid"),
                "chunk_index": i,
            }
        )
    return chunks


def _windows(text: str, max_chars: int, overlap: int) -> List[str]:
    if max_chars <= 0:
        return [text]
    overlap = max(0, min(overlap, max_chars - 1))

    out: List[str] = []
    n = len(text)
    start = 0
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            # prefer a clean break in the back half of the window
            floor = start + max_chars // 2
            brk = text.rfind("\n", floor, end)
            if brk == -1:
                brk = text.rfind(" ", floor, end)
            if brk != -1 and brk > start:
                end = brk
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return out
