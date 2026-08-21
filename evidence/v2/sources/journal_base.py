"""Crossref tabanlı dergi ajanı temeli.

Yayıncı sitelerinin HTML aramaları (NEJM, JAMA, Lancet...) bot korumaları
nedeniyle sürekli 403 dönüyordu. Bu temel sınıf aynı dergileri Crossref'in
açık meta veri API'si üzerinden arar: JSON, kararlı, DOI'li sonuçlar.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from ..core.interfaces import SourceAgent

logger = logging.getLogger(__name__)


class CrossrefJournalAgent(SourceAgent):
    """Belirli bir dergi(ler)in içeriğini Crossref üzerinden arar.

    Alt sınıflar şunları ayarlar:
    - name / source_type / organization
    - CONTAINER_TITLES: derginin Crossref kayıtlı ad(lar)ı
    """

    name = "journal"
    source_type = "academic"
    organization = ""
    CONTAINER_TITLES: tuple[str, ...] = ()

    API_URL = "https://api.crossref.org/works"

    def __init__(self, timeout: float = 20.0, user_agent: str = "AriKaynak/2.0 (mailto:research@arikaynak.org)") -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if not query or not self.CONTAINER_TITLES:
            return []
        timeout = httpx.Timeout(self.timeout)
        headers = {"User-Agent": self.user_agent}

        params: dict[str, Any] = {
            "query.bibliographic": query,
            "query.container-title": " ".join(self.CONTAINER_TITLES[:2]),
            "filter": "type:journal-article",
            "rows": limit * 3,
            "select": "DOI,title,container-title,published,URL,abstract",
        }
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            resp = None
            for attempt in range(3):
                try:
                    r = await client.get(self.API_URL, params=params)
                    if r.status_code == 429:
                        # Ayni IP'den paralel ajanlar rate-limit'e takilabilir;
                        # kisa beklemeyle bir-iki kez dene.
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    r.raise_for_status()
                    resp = r
                    break
                except Exception as e:
                    logger.warning(f"{self.name} search failed: {e}")
                    return []
            if resp is None:
                logger.info(f"{self.name}: rate-limited, sonuc yok")
                return []

        items = resp.json().get("message", {}).get("items", [])
        wanted = {t.lower() for t in self.CONTAINER_TITLES}
        results: list[dict[str, Any]] = []
        for item in items:
            container = next(iter(item.get("container-title", []) or []), "")
            if wanted and container.lower() not in wanted:
                continue
            doi = item.get("DOI")
            title = next(iter(item.get("title", []) or []), None)
            url = item.get("URL") or (f"https://doi.org/{doi}" if doi else None)
            if not title or not url:
                continue
            dates = item.get("published", {}).get("date-parts", [[]])
            year = dates[0][0] if dates and dates[0] else None
            abstract = item.get("abstract", "")
            if abstract:
                abstract = re.sub(r"<[^>]+>", "", abstract)[:2000]
            results.append({
                "source": self.name,
                "organization": self.organization,
                "title": title,
                "url": url,
                "doi": doi,
                "journal": container,
                "published_year": year,
                "passage": abstract,
                "source_type": self.source_type,
            })
            if len(results) >= limit:
                break
        return results
