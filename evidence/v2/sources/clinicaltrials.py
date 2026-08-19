"""ClinicalTrials Agent — searches ClinicalTrials.gov for clinical trials."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .health_base import HealthOrgAgent

logger = logging.getLogger(__name__)


class ClinicalTrialsAgent(HealthOrgAgent):
    """Searches ClinicalTrials.gov for clinical trial registrations.
    
    Flow:
    1. Search ClinicalTrials API → get studies
    2. Return metadata + passage (brief summary)
    """
    
    name = "clinicaltrials"
    source_type = "clinical_trial"
    
    API_URL = "https://clinicaltrials.gov/api/v2/studies"
    
    async def _search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[dict[str, Any]]:
        resp = await client.get(self.API_URL, params={
            "query.cond": query,
            "pageSize": limit,
        })
        resp.raise_for_status()
        data = resp.json()
        
        results = []
        for study in data.get("studies", []):
            protocol = study.get("protocolSection", {})
            ident = protocol.get("identificationModule", {})
            status = protocol.get("statusModule", {})
            desc = protocol.get("descriptionModule", {})
            
            title = ident.get("officialTitle", "") or ident.get("briefTitle", "")
            nct = ident.get("nctId", "")
            
            results.append({
                "source": self.name,
                "organization": "US National Library of Medicine",
                "title": title,
                "url": f"https://clinicaltrials.gov/study/{nct}",
                "nct_id": nct,
                "status": status.get("overallStatus", ""),
                "passage": desc.get("briefSummary", "")[:2000],
                "source_type": self.source_type,
            })
        return results
