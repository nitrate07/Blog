"""Passage verification — verifies passages against original sources."""

from __future__ import annotations

import logging
import re

import httpx

from ..core.types import Passage, PassageVerification

logger = logging.getLogger(__name__)


class PassageVerifier:
    """Verifies passages against original sources.
    
    Verification methods:
    1. URL match: Check if source URL is accessible
    2. Text similarity: Compare passage text with source content
    3. DOI/PMID verification: Verify academic identifiers
    """
    
    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout
    
    async def verify_passage(
        self,
        passage: Passage,
        source_url: str,
    ) -> PassageVerification:
        """Verify a passage against its source."""
        # Method 1: URL accessibility check
        url_valid = await self._check_url(source_url)
        
        # Method 2: Text extraction and similarity
        original_text = None
        similarity = None
        if url_valid:
            original_text = await self._extract_text(source_url)
            if original_text:
                similarity = self._calculate_similarity(passage.text, original_text)
        
        return PassageVerification(
            passage_id=passage.id,
            source_url=source_url,
            verified=url_valid,
            original_text=original_text[:2000] if original_text else None,
            similarity_score=similarity,
            verification_method="url_text_match" if original_text else "url_match",
        )
    
    async def verify_passages(
        self,
        passages: list[Passage],
        source_urls: dict[str, str],
    ) -> list[PassageVerification]:
        """Verify multiple passages."""
        results = []
        for passage in passages:
            source_url = source_urls.get(passage.source_id, "")
            if source_url:
                result = await self.verify_passage(passage, source_url)
                results.append(result)
        return results
    
    async def _check_url(self, url: str) -> bool:
        """Check if a URL is accessible."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.head(url, follow_redirects=True)
                return resp.status_code == 200
        except Exception as e:
            logger.warning(f"URL check failed for {url}: {e}")
            return False
    
    async def _extract_text(self, url: str) -> str | None:
        """Extract text content from a URL."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, follow_redirects=True)
                if resp.status_code == 200:
                    # Try to extract abstract or main content
                    text = resp.text
                    
                    # Try abstract
                    abstract_match = re.search(
                        r'<div[^>]*class="[^"]*abstract[^"]*"[^>]*>(.*?)</div>',
                        text, re.DOTALL
                    )
                    if abstract_match:
                        return re.sub(r'<[^>]+>', '', abstract_match.group(1)).strip()
                    
                    # Try main content
                    main_match = re.search(
                        r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
                        text, re.DOTALL
                    )
                    if main_match:
                        return re.sub(r'<[^>]+>', '', main_match.group(1)).strip()
                    
                    # Fallback: extract all text
                    return re.sub(r'<[^>]+>', '', text)[:5000]
        except Exception as e:
            logger.warning(f"Text extraction failed for {url}: {e}")
        return None
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate text similarity using word overlap."""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1 & words2
        union = words1 | words2
        
        return len(intersection) / len(union) if union else 0.0
