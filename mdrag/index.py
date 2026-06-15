"""Phase 2 orchestrator: raw JSONL -> chunks -> embeddings -> ChromaDB + catalog.

Reads each source's ``<source>.pages.jsonl`` from Phase 1, chunks every record,
embeds the chunks, and upserts them into a persistent ChromaDB collection.
Resumable: a character whose revision is already in the SQLite catalog is
skipped, so re-running only indexes new or changed pages.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable, List, Optional

from tqdm import tqdm

from .catalog import Catalog
from .chunk import chunk_record

log = logging.getLogger("mdrag.index")

COLLECTION = "comics"


def _chroma_collection(chroma_path: str):
    import chromadb

    client = chromadb.PersistentClient(path=chroma_path)
    return client.get_or_create_collection(
        COLLECTION, metadata={"hnsw:space": "cosine"}
    )


def _iter_records(jsonl_path: Path) -> Iterable[dict]:
    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def build_index(
    cfg: dict,
    sources: Optional[List[str]] = None,
    *,
    embedder=None,
    force: bool = False,
) -> dict:
    store = cfg.get("storage", {})
    raw_dir = Path(cfg["data_dir"])
    chroma_path = store.get("chroma_path", "data/chroma")
    catalog_path = store.get("catalog_path", "data/catalog.sqlite")
    max_chars = store.get("chunk_max_chars", 1500)
    overlap = store.get("chunk_overlap_chars", 200)
    embed_batch = store.get("embed_batch", 128)

    if embedder is None:
        from .embed import build_embedder
        embedder = build_embedder(cfg)

    coll = _chroma_collection(chroma_path)
    catalog = Catalog(catalog_path)
    sources = sources or list(cfg["sources"])

    totals = {"characters": 0, "chunks": 0, "skipped": 0}
    for source in sources:
        path = raw_dir / f"{source}.pages.jsonl"
        if not path.exists():
            log.warning("[%s] no pages file at %s; skipping", source, path)
            continue

        records = list(_iter_records(path))
        for rec in tqdm(records, desc=f"index {source}", unit="char"):
            if not force and catalog.is_indexed(rec["id"], rec.get("revid")):
                totals["skipped"] += 1
                continue

            chunks = chunk_record(rec, max_chars=max_chars, overlap_chars=overlap)
            if not chunks:
                catalog.upsert_character(
                    rec["id"], source, rec.get("title", ""),
                    rec.get("url", ""), rec.get("revid"), 0,
                )
                continue

            _upsert_chunks(coll, embedder, chunks, embed_batch)
            catalog.upsert_character(
                rec["id"], source, rec.get("title", ""),
                rec.get("url", ""), rec.get("revid"), len(chunks),
            )
            totals["characters"] += 1
            totals["chunks"] += len(chunks)

    catalog.close()
    return totals


def _upsert_chunks(coll, embedder, chunks: List[dict], batch: int) -> None:
    for i in range(0, len(chunks), batch):
        part = chunks[i : i + batch]
        texts = [c["text"] for c in part]
        embeddings = embedder.encode(texts, is_query=False)
        coll.upsert(
            ids=[c["id"] for c in part],
            documents=texts,
            embeddings=embeddings,
            metadatas=[
                {
                    "character": c["character"],
                    "source": c["source"],
                    "url": c["url"],
                    "chunk_index": c["chunk_index"],
                }
                for c in part
            ],
        )


def query_index(
    cfg: dict,
    text: str,
    *,
    k: int = 5,
    source: Optional[str] = None,
    embedder=None,
) -> list:
    store = cfg.get("storage", {})
    chroma_path = store.get("chroma_path", "data/chroma")

    if embedder is None:
        from .embed import build_embedder
        embedder = build_embedder(cfg)

    coll = _chroma_collection(chroma_path)
    q_emb = embedder.encode([text], is_query=True)
    where = {"source": source} if source else None
    res = coll.query(query_embeddings=q_emb, n_results=k, where=where)

    out = []
    for doc, meta, dist in zip(
        res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        out.append({"text": doc, "metadata": meta, "distance": dist})
    return out
