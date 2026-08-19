"""TF-IDF backed vector store for article chunks with scikit-learn."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .parser import ArticleChunk

logger = logging.getLogger(__name__)


class ArticleVectorStore:
    def __init__(self, persist_directory: str | None = None) -> None:
        self._persist_directory = persist_directory
        self._vectorizer = TfidfVectorizer(
            max_features=10000,
            ngram_range=(1, 2),
            stop_words="english",
            sublinear_tf=True,
        )
        self._ids: list[str] = []
        self._chunks: list[ArticleChunk] = []
        self._documents: list[str] = []
        self._matrix: Any | None = None
        self._fitted = False
        if persist_directory:
            self._load_from_disk()

    @property
    def count(self) -> int:
        return len(self._ids)

    def _load_from_disk(self) -> None:
        if not self._persist_directory:
            return
        store_dir = Path(self._persist_directory)
        if not store_dir.exists():
            return
        ids_file = store_dir / "ids.json"
        chunks_file = store_dir / "chunks.json"
        matrix_file = store_dir / "matrix.npy"
        if not (ids_file.exists() and chunks_file.exists() and matrix_file.exists()):
            return
        try:
            self._ids = json.loads(ids_file.read_text())
            raw_chunks = json.loads(chunks_file.read_text())
            self._chunks = [ArticleChunk(**c) for c in raw_chunks]
            self._documents = [c.to_embedding_text() for c in self._chunks]
            self._matrix = np.load(matrix_file)
            self._fitted = True
            logger.info(f"Loaded {len(self._ids)} chunks from disk")
        except Exception as e:
            logger.warning(f"Failed to load from disk: {e}")

    def _save_to_disk(self) -> None:
        if not self._persist_directory:
            return
        store_dir = Path(self._persist_directory)
        store_dir.mkdir(parents=True, exist_ok=True)
        (store_dir / "ids.json").write_text(json.dumps(self._ids))
        raw_chunks = []
        for c in self._chunks:
            raw_chunks.append({
                "article_id": c.article_id,
                "chunk_index": c.chunk_index,
                "title": c.title,
                "heading": c.heading,
                "text": c.text,
                "language": c.language,
                "category": c.category,
                "verdict": c.verdict,
                "rating_value": c.rating_value,
                "claim_reviewed": c.claim_reviewed,
                "file_number": c.file_number,
                "source_url": c.source_url,
                "chunk_type": c.chunk_type,
            })
        (store_dir / "chunks.json").write_text(json.dumps(raw_chunks, ensure_ascii=False))
        if self._matrix is not None:
            np.save(store_dir / "matrix.npy", self._matrix)

    def upsert_chunks(self, chunks: list[ArticleChunk]) -> int:
        if not chunks:
            return 0
        for chunk in chunks:
            chunk_id = f"{chunk.article_id}::{chunk.chunk_index}"
            if chunk_id in self._ids:
                idx = self._ids.index(chunk_id)
                self._chunks[idx] = chunk
                self._documents[idx] = chunk.to_embedding_text()
            else:
                self._ids.append(chunk_id)
                self._chunks.append(chunk)
                self._documents.append(chunk.to_embedding_text())
        self._rebuild_index()
        self._save_to_disk()
        logger.info(f"Upserted {len(chunks)} chunks, total: {self.count}")
        return len(chunks)

    def _rebuild_index(self) -> None:
        if not self._documents:
            self._matrix = None
            self._fitted = False
            return
        self._matrix = self._vectorizer.fit_transform(self._documents)
        self._fitted = True

    def query(
        self,
        text: str,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
        where_document: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._fitted or self._matrix is None or self.count == 0:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        query_vec = self._vectorizer.transform([text])
        similarities = cosine_similarity(query_vec, self._matrix).flatten()
        candidate_indices = list(range(self.count))
        if where:
            candidate_indices = [i for i in candidate_indices if self._match_where(i, where)]
        if not candidate_indices:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        scored = [(i, similarities[i]) for i in candidate_indices]
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:n_results]
        return {
            "ids": [[self._ids[i] for i, _ in top]],
            "documents": [[self._documents[i] for i, _ in top]],
            "metadatas": [[self._chunks[i].to_metadata() for i, _ in top]],
            "distances": [[round(1.0 - sim, 4) for _, sim in top]],
        }

    def _match_where(self, idx: int, where: dict[str, Any]) -> bool:
        meta = self._chunks[idx].to_metadata()
        if "$and" in where:
            return all(self._match_where(idx, cond) for cond in where["$and"])
        if "$or" in where:
            return any(self._match_where(idx, cond) for cond in where["$or"])
        for key, value in where.items():
            if isinstance(value, dict) and "$in" in value:
                if meta.get(key) not in value["$in"]:
                    return False
            elif meta.get(key) != value:
                return False
        return True

    def delete_article(self, article_id: str) -> None:
        indices_to_remove = [i for i, c in enumerate(self._chunks) if c.article_id == article_id]
        if not indices_to_remove:
            return
        for i in sorted(indices_to_remove, reverse=True):
            del self._ids[i]
            del self._chunks[i]
            del self._documents[i]
        self._rebuild_index()
        self._save_to_disk()

    def get_article_chunks(self, article_id: str) -> dict[str, Any]:
        indices = [i for i, c in enumerate(self._chunks) if c.article_id == article_id]
        return {
            "ids": [self._ids[i] for i in indices],
            "documents": [self._documents[i] for i in indices],
            "metadatas": [self._chunks[i].to_metadata() for i in indices],
        }

    def list_article_ids(self) -> list[str]:
        return sorted({c.article_id for c in self._chunks})

    def clear(self) -> None:
        self._ids = []
        self._chunks = []
        self._documents = []
        self._matrix = None
        self._fitted = False
        self._save_to_disk()
