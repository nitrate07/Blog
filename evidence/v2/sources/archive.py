"""Archive Agent — searches Arı Kaynak articles via RAG retrieval."""

from __future__ import annotations

import logging
from typing import Any

from ..core.interfaces import SourceAgent

logger = logging.getLogger(__name__)


class ArchiveAgent(SourceAgent):
    """Searches existing Arı Kaynak articles via RAG retrieval.
    
    Flow:
    1. RAG search → get relevant chunks
    2. Return metadata + passage (chunk text)
    """
    
    name = "archive"
    source_type = "primary"
    
    def __init__(self, retriever: Any) -> None:
        """Initialize with an ArticleRetriever instance."""
        self.retriever = retriever
    
    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        try:
            results = self.retriever.retrieve(query=query, n_results=limit)
        except Exception as e:
            logger.warning(f"Archive search failed: {e}")
            return []
        
        return [
            {
                "source": self.name,
                "article_id": r.article_id,
                "title": r.title,
                "url": r.source_url,
                "passage": r.text,
                "verdict": r.verdict,
                "rating_value": r.rating_value,
                "distance": r.distance,
                "category": r.category,
                "source_type": self.source_type,
            }
            for r in results
        ]
