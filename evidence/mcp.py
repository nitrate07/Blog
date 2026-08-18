"""MCP-compatible tool surface; works without an MCP runtime dependency in the MVP."""

from __future__ import annotations

from .connectors import EvidenceCatalog
from .engine import EvidenceVerifier, compare_claim_evidence
from .models import SourceInput, VerificationRequest
from .sources import SourceFetcher


class EvidenceMCPTools:
    def __init__(self, verifier: EvidenceVerifier | None = None) -> None:
        self.verifier = verifier or EvidenceVerifier()
        self.fetcher: SourceFetcher = self.verifier.fetcher
        self.catalog = EvidenceCatalog()

    async def verify_claim(self, claim: str, sources: list[str], context: str | None = None) -> dict:
        request = VerificationRequest(claim=claim, sources=[SourceInput(url=url) for url in sources], context=context)
        return (await self.verifier.verify(request)).model_dump(mode="json")

    async def search_evidence(self, query: str) -> dict:
        results = await self.catalog.search(query)
        return {"query": query, "results": [result.model_dump(mode="json") for result in results], "note": "Discovery metadata is not evidence; retrieve a source before assigning a verdict."}

    async def get_source(self, url: str) -> dict:
        source = await self.fetcher.fetch(url)
        return {"url": source.url, "title": source.title, "source_quality": source.quality.value, "text": source.text}

    async def compare_evidence(self, claim: str, evidence: str) -> dict:
        verdict, passage, relevance = compare_claim_evidence(claim, evidence)
        return {"claim": claim, "verdict": verdict.value, "passage": passage, "relevance": relevance}


def create_mcp_server():
    """Return a FastMCP server when installed; otherwise return callable tool implementations."""
    tools = EvidenceMCPTools()
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        return tools
    server = FastMCP("ari-kaynak-evidence")
    server.tool()(tools.verify_claim)
    server.tool()(tools.search_evidence)
    server.tool()(tools.get_source)
    server.tool()(tools.compare_evidence)
    return server
