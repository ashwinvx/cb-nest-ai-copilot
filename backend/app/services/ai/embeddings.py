"""Embedding provider for the Policy RAG.

Local sentence-transformers (all-MiniLM-L6-v2): no vendor key, no
per-query network dependency, deterministic demos. The two-method
interface is the swap point — a hosted provider (e.g. Voyage) replaces
this class without touching the store or the RAG service.

The model (~90MB) downloads to the HF cache on first use; startup cost
is a few seconds, amortized by the lazy singleton.
"""

from __future__ import annotations

from functools import lru_cache

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def _model():
    # Imported lazily: torch is heavy and only needed on RAG paths.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed corpus chunks. Returns unit-normalized vectors, so cosine
    similarity is a plain dot product in the store."""
    return _model().encode(texts, normalize_embeddings=True).tolist()


def embed_query(text: str) -> list[float]:
    return _model().encode([text], normalize_embeddings=True)[0].tolist()
