"""Minimal persistent vector store for the policy corpus.

Brute-force cosine over normalized vectors (numpy dot product). At
corpus scale (tens to low thousands of chunks) this is microseconds;
a dedicated vector DB would add dependencies to search 30 vectors.
Persistence is one JSON file, rebuilt reproducibly from the committed
corpus by scripts/ingest_policies.py.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

INDEX_PATH = Path("storage/policy_index.json")


@dataclass
class Chunk:
    id: str          # e.g. "leave_policy.md#0"
    source: str      # source file name
    title: str       # document title (first heading or file name)
    text: str


@dataclass
class Hit:
    chunk: Chunk
    score: float


class VectorStore:
    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._matrix: np.ndarray | None = None

    def __len__(self) -> int:
        return len(self._chunks)

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must align")
        self._chunks.extend(chunks)
        new = np.asarray(vectors, dtype=np.float32)
        self._matrix = new if self._matrix is None else np.vstack([self._matrix, new])

    def search(self, query_vector: list[float], top_k: int = 4, min_score: float = 0.25) -> list[Hit]:
        """Top-k by cosine similarity (vectors are unit-normalized, so
        dot product == cosine). min_score filters unrelated queries so
        the RAG can answer "not in the policies" instead of grasping."""
        if self._matrix is None or not self._chunks:
            return []
        scores = self._matrix @ np.asarray(query_vector, dtype=np.float32)
        order = np.argsort(scores)[::-1][:top_k]
        return [
            Hit(chunk=self._chunks[i], score=float(scores[i]))
            for i in order
            if float(scores[i]) >= min_score
        ]

    def persist(self, path: Path = INDEX_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "chunks": [asdict(c) for c in self._chunks],
            "vectors": self._matrix.tolist() if self._matrix is not None else [],
        }
        path.write_text(json.dumps(payload))

    @classmethod
    def load(cls, path: Path = INDEX_PATH) -> "VectorStore":
        store = cls()
        if not path.exists():
            return store
        payload = json.loads(path.read_text())
        chunks = [Chunk(**c) for c in payload.get("chunks", [])]
        vectors = payload.get("vectors", [])
        if chunks and vectors:
            store.add(chunks, vectors)
        return store
