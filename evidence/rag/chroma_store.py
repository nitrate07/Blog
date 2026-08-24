"""ChromaDB + multilingual sentence-embedding backed vector store.

Drop-in alternative to ArticleVectorStore (store.py) — implements the exact
same public interface (count, upsert_chunks, query, delete_article,
get_article_chunks, list_article_ids, clear) so ArticleRetriever works with
either backend unchanged. Selected via EVIDENCE_RAG_BACKEND=chroma (default
stays "tfidf" — zero behavior change unless explicitly opted in, matching
this project's established convention for new capabilities).

Why this exists: the old store used a hand-rolled TF-IDF + cosine-similarity
index (bag-of-words, no real semantic understanding — a paraphrased or
synonym-heavy claim would score poorly against an article that means the same
thing in different words). This backend uses real sentence embeddings
(paraphrase-multilingual-MiniLM-L12-v2, ~420MB, covers both the site's TR and
EN article pairs) via ChromaDB, which is what the "chroma" directory name
always implied but never actually used until now.

Trade-off, stated plainly: this pulls in torch/transformers/chromadb —
several hundred MB of new dependencies vs. the previous 8-package footprint
(see docs/ai-infrastructure-inventory.md). Worth it for retrieval quality on
a real, growing article archive; not worth it if this project ever needs to
stay minimal-dependency above all else.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .parser import ArticleChunk

logger = logging.getLogger(__name__)

EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
COLLECTION_NAME = "arikaynak_articles"


class ChromaArticleVectorStore:
    """ArticleVectorStore-compatible store backed by real ChromaDB + embeddings."""

    def __init__(
        self,
        persist_directory: str | None = None,
        collection_name: str = COLLECTION_NAME,
    ) -> None:
        import chromadb
        from chromadb.utils import embedding_functions

        self._persist_directory = persist_directory
        self._collection_name = collection_name
        embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL_NAME
        )
        if persist_directory:
            Path(persist_directory).mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=persist_directory)
        else:
            # EphemeralClient's in-memory backend can be shared across
            # instances within the same process — callers that need real
            # isolation (tests!) MUST also pass a unique collection_name.
            self._client = chromadb.EphemeralClient()
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            embedding_function=embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def count(self) -> int:
        return self._collection.count()

    def upsert_chunks(self, chunks: list[ArticleChunk]) -> int:
        if not chunks:
            return 0
        ids = [f"{c.article_id}::{c.chunk_index}" for c in chunks]
        documents = [c.to_embedding_text() for c in chunks]
        metadatas = [c.to_metadata() for c in chunks]
        self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        logger.info(f"Upserted {len(chunks)} chunks (chroma), total: {self.count}")
        return len(chunks)

    def query(
        self,
        text: str,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
        where_document: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.count == 0:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        n_results = min(n_results, self.count)
        result = self._collection.query(
            query_texts=[text],
            n_results=n_results,
            where=where,
            where_document=where_document,
        )
        return {
            "ids": result.get("ids", [[]]),
            "documents": result.get("documents", [[]]),
            "metadatas": result.get("metadatas", [[]]),
            "distances": result.get("distances", [[]]),
        }

    def delete_article(self, article_id: str) -> None:
        self._collection.delete(where={"article_id": article_id})

    def get_article_chunks(self, article_id: str) -> dict[str, Any]:
        result = self._collection.get(where={"article_id": article_id})
        return {
            "ids": result.get("ids", []),
            "documents": result.get("documents", []),
            "metadatas": result.get("metadatas", []),
        }

    def list_article_ids(self) -> list[str]:
        if self.count == 0:
            return []
        result = self._collection.get(include=["metadatas"])
        return sorted({m["article_id"] for m in result.get("metadatas", []) if m})

    def clear(self) -> None:
        self._client.delete_collection(self._collection_name)
        from chromadb.utils import embedding_functions

        embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL_NAME
        )
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            embedding_function=embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
