"""Source Orchestrator — runs all agents in parallel and combines results."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..core.interfaces import SourceAgent

logger = logging.getLogger(__name__)


class SourceOrchestrator:
    """Orchestrates all source agents in parallel.
    
    Flow:
    1. Run all (or selected) agents in parallel
    2. Collect results from each agent
    3. Deduplicate by URL
    4. Return combined results
    """
    
    def __init__(self, agents: list[SourceAgent] | None = None) -> None:
        self.agents = agents or []
    
    async def search(
        self,
        query: str,
        limit_per_agent: int = 5,
        sources: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run all (or selected) agents in parallel.
        
        Args:
            query: Search query
            limit_per_agent: Max results per agent
            sources: If provided, only run these agents (by name)
        
        Returns:
            {
                "query": str,
                "results": list[dict],  # deduplicated
                "total_results": int,
                "agents_succeeded": int,
                "agents_failed": int,
                "agent_stats": list[dict],
            }
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
        seen: set[str] = set()
        deduplicated: list[dict[str, Any]] = []
        for item in all_results:
            url = item.get("url", "").rstrip("/").lower()
            if url and url not in seen:
                seen.add(url)
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
        """List all available agents."""
        return [
            {"name": a.name, "source_type": a.source_type}
            for a in self.agents
        ]
