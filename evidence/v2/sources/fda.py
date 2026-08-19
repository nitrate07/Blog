"""FDA Agent — searches US Food and Drug Administration."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .health_base import HealthOrgAgent

logger = logging.getLogger(__name__)


class FDAAgent(HealthOrgAgent):
    """Searches FDA drug approvals and safety alerts.
    
    Flow:
    1. Search FDA drug labels API → get results
    2. Return metadata + passage (drug description)
    """
    
    name = "fda"
    source_type = "regulatory"
    
    DRUG_URL = "https://api.fda.gov/drug/label.json"
    
    async def _search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
        resp = await client.get(self.DRUG_URL, params={
            "search": f"openfda.brand_name:{query}+OR+openfda.generic_name:{query}",
            "limit": limit,
        })
        resp.raise_for_status()
        data = resp.json()
        
        results = []
        for item in data.get("results", [])[:limit]:
            openfda = item.get("openfda", {})
            brand = openfda.get("brand_name", [""])[0] if openfda.get("brand_name") else ""
            generic = openfda.get("generic_name", [""])[0] if openfda.get("generic_name") else ""
            description = item.get("description", [""])[0] if item.get("description") else ""
            
            results.append({
                "source": self.name,
                "organization": "US Food and Drug Administration",
                "title": f"{brand or generic} - FDA Drug Label",
                "url": f"https://api.fda.gov/drug/label.json?search=openfda.brand_name:{brand}",
                "brand_name": brand,
                "generic_name": generic,
                "passage": description[:2000],
                "source_type": self.source_type,
            })
        return results
