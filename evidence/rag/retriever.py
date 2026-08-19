"""RAG retriever: query -> embed -> search -> context assembly."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .parser import ArticleChunk, parse_all_articles
from .store import ArticleVectorStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievalResult:
    article_id: str
    title: str
    heading: str | None
    text: str
    verdict: str
    rating_value: int
    category: str
    chunk_type: str
    distance: float
    source_url: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "title": self.title,
            "heading": self.heading,
            "text": self.text,
            "verdict": self.verdict,
            "rating_value": self.rating_value,
            "category": self.category,
            "chunk_type": self.chunk_type,
            "distance": round(self.distance, 4),
            "source_url": self.source_url,
        }


class ArticleRetriever:
    def __init__(self, store: ArticleVectorStore) -> None:
        self.store = store

    def index_articles(
        self,
        articles_dir: Path,
        tr_dir: Path | None = None,
    ) -> dict[str, Any]:
        chunks = parse_all_articles(articles_dir, tr_dir)
        if not chunks:
            return {"indexed": 0, "chunks": 0, "articles": 0}
        article_ids = {c.article_id for c in chunks}
        for aid in article_ids:
            self.store.delete_article(aid)
        upserted = self.store.upsert_chunks(chunks)
        return {
            "indexed": upserted,
            "chunks": len(chunks),
            "articles": len(article_ids),
        }

    def retrieve(
        self,
        query: str,
        n_results: int = 5,
        language: str | None = None,
        category: str | None = None,
        chunk_types: list[str] | None = None,
    ) -> list[RetrievalResult]:
        where_conditions: list[dict[str, Any]] = []
        if language:
            where_conditions.append({"language": language})
        if category:
            where_conditions.append({"category": category})
        if chunk_types:
            where_conditions.append({"chunk_type": {"$in": chunk_types}})
        where = None
        if len(where_conditions) == 1:
            where = where_conditions[0]
        elif len(where_conditions) > 1:
            where = {"$and": where_conditions}
        raw = self.store.query(text=query, n_results=n_results, where=where)
        results: list[RetrievalResult] = []
        ids = raw.get("ids", [[]])[0] if raw.get("ids") else []
        documents = raw.get("documents", [[]])[0] if raw.get("documents") else []
        metadatas = raw.get("metadatas", [[]])[0] if raw.get("metadatas") else []
        distances = raw.get("distances", [[]])[0] if raw.get("distances") else []
        for i, doc_id in enumerate(ids):
            meta = metadatas[i] if i < len(metadatas) else {}
            dist = distances[i] if i < len(distances) else 1.0
            results.append(RetrievalResult(
                article_id=meta.get("article_id", ""),
                title=meta.get("title", ""),
                heading=meta.get("heading") or None,
                text=documents[i] if i < len(documents) else "",
                verdict=meta.get("verdict", ""),
                rating_value=int(meta.get("rating_value", "0")),
                category=meta.get("category", ""),
                chunk_type=meta.get("chunk_type", ""),
                distance=dist,
                source_url=meta.get("source_url", ""),
            ))
        return results

    def build_context(
        self,
        query: str,
        n_results: int = 5,
        max_context_length: int = 4000,
        language: str | None = None,
    ) -> str:
        results = self.retrieve(query, n_results=n_results, language=language)
        if not results:
            return "No relevant articles found."
        context_parts: list[str] = []
        current_length = 0
        for result in results:
            entry = (
                f"FILE No. {result.article_id} | Verdict: {result.verdict} ({result.rating_value}/5)\n"
                f"Title: {result.title}\n"
                f"Section: {result.heading or 'Overview'}\n"
                f"{result.text}\n"
                f"Source: {result.source_url}\n"
            )
            if current_length + len(entry) > max_context_length:
                break
            context_parts.append(entry)
            current_length += len(entry)
        return "\n---\n".join(context_parts)

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_chunks": self.store.count,
            "article_ids": self.store.list_article_ids(),
        }
