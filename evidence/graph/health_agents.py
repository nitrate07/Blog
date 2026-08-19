"""Health organization agents — search global health institutions for evidence.

Each agent searches one specific health organization or database.
These are supplementary evidence sources beyond PubMed/Crossref/Archive.

PRINCIPLE: Agents discover metadata from sources.
They do NOT interpret or judge — that's the Evidence Engine's job.
"""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from ..config import Settings, settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# WHO (World Health Organization)
# ---------------------------------------------------------------------------

class WHOAgent:
    """Searches WHO IRIS (Institutional Repository) and WHO news."""
    name = "who"
    source_type = "international_organization"
    iris_endpoint = "https://iris.who.int/rest/api/search"
    news_endpoint = "https://www.who.int/api/hubs/topstories"

    def __init__(self, config: Settings | None = None) -> None:
        self.config = config or settings

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        timeout = httpx.Timeout(self.config.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": self.config.user_agent}) as client:
            try:
                resp = await client.get(self.iris_endpoint, params={
                    "query": query,
                    "dte": "2020-01-01",
                    "scope": "WHO archives",
                    "sort": "created",
                    "rpp": limit,
                    "pageRender": "false",
                })
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("resultSet", []):
                    title = item.get("metadata", [])
                    title_text = ""
                    doi = None
                    for m in title:
                        if m.get("key") == "dc.title":
                            title_text = m.get("value", "")
                        if m.get("key") == "dc.identifier.doi":
                            doi = m.get("value", "")
                    if title_text:
                        results.append({
                            "source": "who",
                            "organization": "World Health Organization",
                            "title": title_text,
                            "url": f"https://iris.who.int/handle/{item.get('handle', '')}",
                            "doi": doi,
                            "source_type": "international_organization",
                        })
            except Exception as e:
                logger.warning(f"WHO IRIS search failed: {e}")
        return results[:limit]


# ---------------------------------------------------------------------------
# CDC (US Centers for Disease Control and Prevention)
# ---------------------------------------------------------------------------

class CDCAgent:
    """Searches CDC MMWR (Morbidity and Mortality Weekly Report) and guidelines."""
    name = "cdc"
    source_type = "government"
    search_endpoint = "https://search.cdc.gov/search/"

    def __init__(self, config: Settings | None = None) -> None:
        self.config = config or settings

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(self.config.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            try:
                resp = await client.get(self.search_endpoint, params={
                    "query": query,
                    "t": "true",
                    "s": "relevance",
                    "d": "",
                    "action": "search",
                    "output": "json",
                })
                resp.raise_for_status()
                data = resp.json()
                results: list[dict[str, Any]] = []
                for item in data.get("results", [])[:limit]:
                    results.append({
                        "source": "cdc",
                        "organization": "US Centers for Disease Control and Prevention",
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "description": item.get("content", "")[:300],
                        "source_type": "government",
                    })
                return results
            except Exception as e:
                logger.warning(f"CDC search failed: {e}")
                return []


# ---------------------------------------------------------------------------
# ECDC (European Centre for Disease Prevention and Control)
# ---------------------------------------------------------------------------

class ECDCAgent:
    """Searches ECDC publications and surveillance data."""
    name = "ecdc"
    source_type = "international_organization"
    api_endpoint = "https://www.ecdc.europa.eu/sites/default/files/media/en/publications-and-data/Search/"

    def __init__(self, config: Settings | None = None) -> None:
        self.config = config or settings

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(self.config.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            try:
                resp = await client.get(
                    "https://www.ecdc.europa.eu/en/publications-data",
                    params={"search": query},
                )
                resp.raise_for_status()
                text = resp.text
                results: list[dict[str, Any]] = []
                # Extract publication links from HTML
                pattern = r'href="(/en/publications-data/[^"]+)"[^>]*>([^<]+)<'
                matches = re.findall(pattern, text)
                for href, title in matches[:limit]:
                    results.append({
                        "source": "ecdc",
                        "organization": "European Centre for Disease Prevention and Control",
                        "title": title.strip(),
                        "url": f"https://www.ecdc.europa.eu{href}",
                        "source_type": "international_organization",
                    })
                return results
            except Exception as e:
                logger.warning(f"ECDC search failed: {e}")
                return []


# ---------------------------------------------------------------------------
# Cochrane Library
# ---------------------------------------------------------------------------

class CochraneAgent:
    """Searches Cochrane Library for systematic reviews."""
    name = "cochrane"
    source_type = "systematic_review"
    api_endpoint = "https://api.cochrane.com/search"

    def __init__(self, config: Settings | None = None) -> None:
        self.config = config or settings

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(self.config.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.get(self.api_endpoint, params={
                    "search": query,
                    "page": 1,
                    "pagesize": limit,
                })
                resp.raise_for_status()
                data = resp.json()
                results: list[dict[str, Any]] = []
                for item in data.get("results", []):
                    results.append({
                        "source": "cochrane",
                        "organization": "Cochrane Collaboration",
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "doi": item.get("doi"),
                        "source_type": "systematic_review",
                    })
                return results
            except Exception as e:
                logger.warning(f"Cochrane search failed: {e}")
                return []


# ---------------------------------------------------------------------------
# ClinicalTrials.gov
# ---------------------------------------------------------------------------

class ClinicalTrialsAgent:
    """Searches ClinicalTrials.gov for clinical trial registrations."""
    name = "clinicaltrials"
    source_type = "clinical_trial"
    api_endpoint = "https://clinicaltrials.gov/api/v2/studies"

    def __init__(self, config: Settings | None = None) -> None:
        self.config = config or settings

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(self.config.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.get(self.api_endpoint, params={
                    "query.cond": query,
                    "pageSize": limit,
                })
                resp.raise_for_status()
                data = resp.json()
                results: list[dict[str, Any]] = []
                for study in data.get("studies", []):
                    protocol = study.get("protocolSection", {})
                    ident = protocol.get("identificationModule", {})
                    status = protocol.get("statusModule", {})
                    title = ident.get("officialTitle", "") or ident.get("briefTitle", "")
                    nct = ident.get("nctId", "")
                    results.append({
                        "source": "clinicaltrials",
                        "organization": "US National Library of Medicine",
                        "title": title,
                        "url": f"https://clinicaltrials.gov/study/{nct}",
                        "nct_id": nct,
                        "status": status.get("overallStatus", ""),
                        "source_type": "clinical_trial",
                    })
                return results
            except Exception as e:
                logger.warning(f"ClinicalTrials search failed: {e}")
                return []


# ---------------------------------------------------------------------------
# FDA (US Food and Drug Administration)
# ---------------------------------------------------------------------------

class FDAAgent:
    """Searches FDA drug approvals, safety alerts, and guidance documents."""
    name = "fda"
    source_type = "regulatory"
    drug_endpoint = "https://api.fda.gov/drug/label.json"
    enforcement_endpoint = "https://api.fda.gov/drug/enforcement.json"

    def __init__(self, config: Settings | None = None) -> None:
        self.config = config or settings

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(self.config.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            results: list[dict[str, Any]] = []
            # Search drug labels
            try:
                resp = await client.get(self.drug_endpoint, params={
                    "search": f"openfda.brand_name:{query}+OR+openfda.generic_name:{query}",
                    "limit": limit,
                })
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("results", [])[:limit]:
                    openfda = item.get("openfda", {})
                    brand = openfda.get("brand_name", [""])[0] if openfda.get("brand_name") else ""
                    generic = openfda.get("generic_name", [""])[0] if openfda.get("generic_name") else ""
                    results.append({
                        "source": "fda",
                        "organization": "US Food and Drug Administration",
                        "title": f"{brand or generic} - FDA Drug Label",
                        "url": f"https://api.fda.gov/drug/label.json?search=openfda.brand_name:{brand}",
                        "brand_name": brand,
                        "generic_name": generic,
                        "source_type": "regulatory",
                    })
            except Exception as e:
                logger.warning(f"FDA search failed: {e}")
            return results[:limit]


# ---------------------------------------------------------------------------
# EMA (European Medicines Agency)
# ---------------------------------------------------------------------------

class EMAAgent:
    """Searches EMA for European drug assessments and safety reports."""
    name = "ema"
    source_type = "regulatory"
    search_endpoint = "https://www.ema.europa.eu/en/search"

    def __init__(self, config: Settings | None = None) -> None:
        self.config = config or settings

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(self.config.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            try:
                resp = await client.get(self.search_endpoint, params={
                    "search_api_fulltext": query,
                    "f%5B0%5D": "sm_type:ema_search_result",
                })
                resp.raise_for_status()
                text = resp.text
                results: list[dict[str, Any]] = []
                pattern = r'href="(/en/medicines/[^"]+)"[^>]*>([^<]+)<'
                matches = re.findall(pattern, text)
                for href, title in matches[:limit]:
                    results.append({
                        "source": "ema",
                        "organization": "European Medicines Agency",
                        "title": title.strip(),
                        "url": f"https://www.ema.europa.eu{href}",
                        "source_type": "regulatory",
                    })
                return results
            except Exception as e:
                logger.warning(f"EMA search failed: {e}")
                return []


# ---------------------------------------------------------------------------
# Google Scholar (via SerpAPI or direct)
# ---------------------------------------------------------------------------

class GoogleScholarAgent:
    """Searches Google Scholar for academic papers."""
    name = "google_scholar"
    source_type = "academic"
    api_endpoint = "https://scholar.google.com/scholar"

    def __init__(self, config: Settings | None = None) -> None:
        self.config = config or settings

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(self.config.request_timeout_seconds)
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            try:
                resp = await client.get(self.api_endpoint, params={
                    "q": query,
                    "hl": "en",
                    "num": limit,
                }, headers=headers)
                resp.raise_for_status()
                text = resp.text
                results: list[dict[str, Any]] = []
                # Extract results from HTML
                pattern = r'<h3[^>]*class="gs_rt"[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>'
                matches = re.findall(pattern, text, re.DOTALL)
                for url, title in matches[:limit]:
                    clean_title = re.sub(r'<[^>]+>', '', title).strip()
                    results.append({
                        "source": "google_scholar",
                        "organization": "Google Scholar",
                        "title": clean_title,
                        "url": url,
                        "source_type": "academic",
                    })
                return results
            except Exception as e:
                logger.warning(f"Google Scholar search failed: {e}")
                return []


# ---------------------------------------------------------------------------
# Combined Health Organizations Search Agent
# ---------------------------------------------------------------------------

class HealthOrgSearchAgent:
    """Orchestrates all health organization agents in parallel.
    
    Available agents:
    - WHO (Dünya Sağlık Örgütü)
    - CDC (ABD Hastalık Kontrol Merkezi)
    - ECDC (Avrupa Hastalık Kontrol Merkezi)
    - Cochrane (Sistematik Derlemeler)
    - ClinicalTrials (Klinik Araştırmalar)
    - FDA (ABD İlaç Dairesi)
    - EMA (Avrupa İlaç Ajansı)
    - Google Scholar (Akademik Makaleler)
    """

    def __init__(self, config: Settings | None = None) -> None:
        self.config = config or settings
        self.agents = [
            WHOAgent(self.config),
            CDCAgent(self.config),
            ECDCAgent(self.config),
            CochraneAgent(self.config),
            ClinicalTrialsAgent(self.config),
            FDAAgent(self.config),
            EMAAgent(self.config),
            GoogleScholarAgent(self.config),
        ]

    async def search(
        self,
        query: str,
        limit_per_agent: int = 5,
        sources: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run all (or selected) agents in parallel and combine results.
        
        Args:
            query: Search query
            limit_per_agent: Max results per agent
            sources: If provided, only run these agents (by name)
        """
        agents_to_run = self.agents
        if sources:
            agents_to_run = [a for a in self.agents if a.name in sources]

        tasks = [agent.search(query, limit_per_agent) for agent in agents_to_run]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_results: list[dict[str, Any]] = []
        agent_stats: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0

        for agent, result in zip(agents_to_run, results):
            if isinstance(result, Exception):
                logger.warning(f"Agent {agent.name} failed: {result}")
                agent_stats.append({"name": agent.name, "status": "failed", "count": 0})
                failed += 1
                continue
            succeeded += 1
            agent_stats.append({"name": agent.name, "status": "ok", "count": len(result)})
            for item in result:
                item["agent"] = agent.name
                all_results.append(item)

        # Deduplicate by URL
        seen: dict[str, set[str]] = {}
        deduplicated: list[dict[str, Any]] = []
        for item in all_results:
            url = item.get("url", "").rstrip("/").lower()
            if url and url not in seen:
                seen[url] = {url}
                deduplicated.append(item)
            elif not url:
                deduplicated.append(item)

        return {
            "query": query,
            "results": deduplicated,
            "total_results": len(deduplicated),
            "agents_succeeded": succeeded,
            "agents_failed": failed,
            "agent_stats": agent_stats,
        }

    def list_agents(self) -> list[dict[str, str]]:
        return [
            {"name": a.name, "source_type": a.source_type}
            for a in self.agents
        ]
