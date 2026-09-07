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
        """Fetch each of `sources`, compare it against `claim`, and return a verdict.

        Use this when you already have candidate source URLs (e.g. from search_evidence
        or your own research) and want a verdict + confidence + per-source evidence
        passages. `context` is optional free text (e.g. who made the claim, or a nuance
        to weigh) passed through to the comparison step.
        """
        request = VerificationRequest(claim=claim, sources=[SourceInput(url=url) for url in sources], context=context)
        return (await self.verifier.verify(request)).model_dump(mode="json")

    async def search_evidence(self, query: str) -> dict:
        """Search Arı Kaynak's own archive for prior case files relevant to `query`.

        Returns discovery metadata (titles, URLs, snippets) only -- NOT evidence. Always
        retrieve a specific source (get_source) or run verify_claim before citing a
        verdict; don't treat a search result's snippet as itself sufficient support.
        """
        results = await self.catalog.search(query)
        return {
            "query": query,
            "result_count": len(results),
            "results": [result.model_dump(mode="json") for result in results],
            "note": "Discovery metadata is not evidence; retrieve a source before assigning a verdict.",
        }

    async def get_source(self, url: str) -> dict:
        """Fetch a single URL and return its extracted text plus provenance metadata.

        `source_quality` classifies the URL as primary/secondary/tertiary/unknown.
        `redirected` is true if `url` redirected elsewhere before being fetched --
        check `url` (the final address) against what you expected. `content_hash` is a
        SHA-256 of the raw response body, for detecting if a source changes between
        two fetches of the same URL.
        """
        source = await self.fetcher.fetch(url)
        return {
            "requested_url": url,
            "url": source.url,
            "redirected": source.url != url,
            "title": source.title,
            "source_quality": source.quality.value,
            "content_hash": source.content_hash,
            "text": source.text,
        }

    async def compare_evidence(self, claim: str, evidence: str) -> dict:
        """Compare `claim` against a specific `evidence` passage you already have in hand.

        Use this instead of verify_claim when you already have the relevant text (e.g.
        a quote from a paper) and don't need this tool to fetch anything itself.
        Returns a verdict, the matched passage, and a relevance score.
        """
        verdict, passage, relevance = compare_claim_evidence(claim, evidence)
        return {"claim": claim, "verdict": verdict.value, "passage": passage, "relevance": relevance}


def create_mcp_server(**fastmcp_kwargs):
    """Return a FastMCP server when installed; otherwise return callable tool implementations.

    `fastmcp_kwargs` is forwarded to the `FastMCP` constructor (e.g. `transport_security=`,
    `streamable_http_path=`) so a caller mounting this onto a real ASGI app behind a real
    hostname can configure the Host/Origin allowlist without this module needing to know
    about deployment concerns.
    """
    tools = EvidenceMCPTools()
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        return tools
    server = FastMCP("ari-kaynak-evidence", **fastmcp_kwargs)
    server.tool()(tools.verify_claim)
    server.tool()(tools.search_evidence)
    server.tool()(tools.get_source)
    server.tool()(tools.compare_evidence)
    return server
