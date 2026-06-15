"""Embedding backends. Pluggable so the index/query code never imports a
specific model directly, which keeps it testable with a lightweight stub.

Default backend is sentence-transformers with a local BGE model (free, runs on
CPU or GPU). BGE retrieval works best when *queries* (not passages) are given a
short instruction prefix; that prefix lives in config as ``query_instruction``.
"""

from __future__ import annotations

from typing import List, Protocol


class Embedder(Protocol):
    dim: int
    def encode(self, texts: List[str], *, is_query: bool = False) -> List[List[float]]: ...


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, query_instruction: str = "", device: str | None = None):
        from sentence_transformers import SentenceTransformer  # lazy: heavy import

        self.model = SentenceTransformer(model_name, device=device)
        self.query_instruction = query_instruction
        self.dim = self.model.get_sentence_embedding_dimension()

    def encode(self, texts: List[str], *, is_query: bool = False) -> List[List[float]]:
        if is_query and self.query_instruction:
            texts = [self.query_instruction + t for t in texts]
        embs = self.model.encode(
            texts,
            normalize_embeddings=True,   # cosine-ready unit vectors
            convert_to_numpy=True,
            show_progress_bar=False,
            batch_size=64,
        )
        return embs.tolist()


def build_embedder(cfg: dict) -> Embedder:
    store = cfg.get("storage", {})
    return SentenceTransformerEmbedder(
        model_name=store.get("embed_model", "BAAI/bge-large-en-v1.5"),
        query_instruction=store.get(
            "query_instruction",
            "Represent this sentence for searching relevant passages: ",
        ),
        device=store.get("device"),
    )
