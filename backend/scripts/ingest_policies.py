"""Rebuild the policy vector index from the committed corpus.

Reproducible from a fresh clone:
    cd backend && .venv/bin/python -m scripts.ingest_policies

Reads every .md/.txt/.pdf in storage/hr-policies/ (the app-managed
corpus dir, checked into git), dedupes by content hash (the seeded
upload fixtures duplicate two repo-root samples), chunks, embeds, and
writes storage/policy_index.json (gitignored, derived artifact).

Chunking: documents at or below WHOLE_DOC_WORDS stay whole (the seed
corpus is one-liners); longer documents split on paragraphs into
~TARGET_WORDS chunks with OVERLAP_WORDS carried between chunks, so a
real multi-page upload indexes sensibly.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from app.services.ai.embeddings import embed_documents
from app.services.ai.vector_store import Chunk, VectorStore

CORPUS_DIR = Path("storage/hr-policies")
WHOLE_DOC_WORDS = 250
TARGET_WORDS = 180
OVERLAP_WORDS = 30


def read_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        return "\n".join((page.extract_text() or "") for page in PdfReader(path).pages)
    return path.read_text(encoding="utf-8", errors="replace")


def doc_title(text: str, path: Path) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("# ").strip()
        if line:
            return line[:80]
    return path.stem


def chunk_text(text: str) -> list[str]:
    words = text.split()
    if len(words) <= WHOLE_DOC_WORDS:
        return [text.strip()] if text.strip() else []
    # Paragraph-preserving greedy packing with word overlap.
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[list[str]] = [[]]
    for para in paragraphs:
        para_words = para.split()
        if chunks[-1] and len(chunks[-1]) + len(para_words) > TARGET_WORDS:
            overlap = chunks[-1][-OVERLAP_WORDS:]
            chunks.append(list(overlap))
        chunks[-1].extend(para_words)
    return [" ".join(c) for c in chunks if c]


def build_index(corpus_dir: Path = CORPUS_DIR) -> VectorStore:
    store = VectorStore()
    seen_hashes: set[str] = set()
    chunks: list[Chunk] = []

    for path in sorted(corpus_dir.iterdir()):
        if path.suffix.lower() not in (".md", ".txt", ".pdf"):
            continue
        text = read_text(path)
        digest = hashlib.sha256(" ".join(text.split()).lower().encode()).hexdigest()
        if digest in seen_hashes:
            print(f"  skip (duplicate content): {path.name}")
            continue
        seen_hashes.add(digest)
        title = doc_title(text, path)
        for i, piece in enumerate(chunk_text(text)):
            chunks.append(Chunk(id=f"{path.name}#{i}", source=path.name, title=title, text=piece))

    print(f"{len(chunks)} chunks from {len(seen_hashes)} unique documents")
    if chunks:
        store.add(chunks, embed_documents([c.text for c in chunks]))
    return store


def main() -> None:
    if not CORPUS_DIR.is_dir():
        sys.exit(f"corpus dir not found: {CORPUS_DIR} (run from backend/)")
    store = build_index()
    store.persist()
    print(f"index written: {len(store)} chunks")


if __name__ == "__main__":
    main()
