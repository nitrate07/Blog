"""Base class for health organization agents."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..core.interfaces import SourceAgent

logger = logging.getLogger(__name__)


class HealthOrgAgent(SourceAgent):
    """Base class for all health organization agents.
    
    Subclasses must implement:
    - name
    - source_type
    - _search(client, query, limit) -> list[dict]
    """
    
    def __init__(self, timeout: float = 30.0, user_agent: str = "AriKaynak/2.0") -> None:
        self.timeout = timeout
        self.user_agent = user_agent
    
    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(self.timeout)
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": self.user_agent},
            follow_redirects=True,
        ) as client:
            try:
                return await self._search(client, query, limit)
            except Exception as e:
                logger.warning(f"{self.name} search failed: {e}")
                return []
    
    async def _search(
        self, client: httpx.AsyncClient, query: str, limit: int
    ) -> list[dict[str, Any]]:
        """Subclasses must implement this method."""
        raise NotImplementedError
