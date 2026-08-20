"""AI tools ile arastirma — planlanan adimlari yurutur.

Mevcut pipeline ve source orchestrator'unu kullanarak:
- PubMed, Crossref, journal'lar
- WHO, CDC, ESC gibi saglik kuruluslari
- Mevcut Arı Kaynak arsivi
- Celişki tespiti
- Timeline: arastirma sureci boyunca adimlarin kronolojik kaydi
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .planner import InvestigationPlan, PlanStep, StepType

logger = logging.getLogger(__name__)


@dataclass
class TimelineEntry:
    """Tek bir timeline girdisi — arastirma adiminin kronolojik kaydi."""
    timestamp: str
    step_type: str
    description: str
    status: str  # "started", "completed", "failed"
    duration_ms: float = 0.0
    result_count: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "step_type": self.step_type,
            "description": self.description,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 1),
            "result_count": self.result_count,
            "details": self.details,
        }


@dataclass
class Timeline:
    """Arastirma suresinin kronolojik kaydi.

    Dashboard'da gosterilebilir:
    - Hangi adim ne zaman basladi/tamamlandi
    - Her adim kac kaynak buldu
    - Toplam sure
    """
    entries: list[TimelineEntry] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""

    def start(self) -> None:
        self.started_at = datetime.now(timezone.utc).isoformat()

    def add_entry(
        self,
        step_type: str,
        description: str,
        status: str,
        duration_ms: float = 0.0,
        result_count: int = 0,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.entries.append(TimelineEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            step_type=step_type,
            description=description,
            status=status,
            duration_ms=duration_ms,
            result_count=result_count,
            details=details or {},
        ))

    def complete(self) -> None:
        self.completed_at = datetime.now(timezone.utc).isoformat()

    @property
    def total_duration_ms(self) -> float:
        return sum(e.duration_ms for e in self.entries)

    @property
    def total_results(self) -> int:
        return sum(e.result_count for e in self.entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_duration_ms": round(self.total_duration_ms, 1),
            "total_results": self.total_results,
            "entries": [e.to_dict() for e in self.entries],
        }


@dataclass
class StepResult:
    """Tek bir arastirma adimi sonucu."""
    step: PlanStep
    success: bool
    results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    duration_ms: float = 0.0

    @property
    def count(self) -> int:
        return len(self.results)


@dataclass
class InvestigationResult:
    """Tum arastirma sonucu."""
    plan: InvestigationPlan
    step_results: list[StepResult] = field(default_factory=list)
    timeline: Timeline = field(default_factory=Timeline)
    all_results: list[dict[str, Any]] = field(default_factory=list)
    archive_results: list[dict[str, Any]] = field(default_factory=list)
    external_results: list[dict[str, Any]] = field(default_factory=list)
    health_org_results: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    previous_verification: dict[str, Any] | None = None
    total_sources: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"Arastirma tamamlandi: {self.total_sources} kaynak, "
            f"{len(self.archive_results)} arsiv, "
            f"{len(self.external_results)} akademik, "
            f"{len(self.health_org_results)} kurum, "
            f"{len(self.contradictions)} celişki, "
            f"sure: {self.timeline.total_duration_ms:.0f}ms"
        )


class EvidenceInvestigator:
    """Planlanan arastirma adimlarini yuruten motor.

    Mevcut orchestrator ve pipeline'i kullanarak paralel arastirma yapar.
    """

    def __init__(
        self,
        orchestrator: Any | None = None,
        graph_store: Any | None = None,
        db: Any | None = None,
    ) -> None:
        """
        Args:
            orchestrator: SourceOrchestrator instance (PubMed, Crossref vb.)
            graph_store: EvidenceGraph store (onceki dogrulamalar icin)
            db: EvidenceDatabase (persisted veriler icin)
        """
        self.orchestrator = orchestrator
        self.graph_store = graph_store
        self.db = db

    async def investigate(self, plan: InvestigationPlan) -> InvestigationResult:
        """Tum plan adimlarini yurut."""
        result = InvestigationResult(plan=plan)
        result.timeline.start()

        # Adimlari oncelige gore sirala, sonra paralel calistir
        active_steps = plan.all_active_steps()

        # High priority once
        high_steps = [s for s in active_steps if s.priority.value == "high"]
        medium_steps = [s for s in active_steps if s.priority.value == "medium"]
        low_steps = [s for s in active_steps if s.priority.value == "low"]

        # Once yuksek onceliklileri calistir
        if high_steps:
            high_results = await self._run_steps_parallel(high_steps)
            result.step_results.extend(high_results)

        # Sonra orta ve dusuk onceliklileri paralel
        remaining = medium_steps + low_steps
        if remaining:
            remaining_results = await self._run_steps_parallel(remaining)
            result.step_results.extend(remaining_results)

        # Timeline'i guncelle
        for sr in result.step_results:
            result.timeline.add_entry(
                step_type=sr.step.step_type.value,
                description=sr.step.description,
                status="completed" if sr.success else "failed",
                duration_ms=sr.duration_ms,
                result_count=sr.count,
                details={"error": sr.error} if sr.error else {},
            )

        result.timeline.complete()

        # Sonuclari kategorize et
        self._categorize_results(result)

        return result

    async def _run_steps_parallel(self, steps: list[PlanStep]) -> list[StepResult]:
        """Birden fazla adimi paralel calistir."""
        tasks = [self._run_single_step(step) for step in steps]
        return list(await asyncio.gather(*tasks, return_exceptions=False))

    async def _run_single_step(self, step: PlanStep) -> StepResult:
        """Tek bir arastirma adimini calistir."""
        import time
        start = time.monotonic()

        try:
            method = getattr(self, f"_execute_{step.step_type.value}", None)
            if method is None:
                return StepResult(
                    step=step,
                    success=False,
                    error=f"Bilinmeyen adim tipi: {step.step_type.value}",
                )

            results = await method(step)
            duration = (time.monotonic() - start) * 1000

            return StepResult(
                step=step,
                success=True,
                results=results,
                duration_ms=duration,
            )

        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            logger.warning(f"Step '{step.step_type.value}' failed: {e}")
            return StepResult(
                step=step,
                success=False,
                error=str(e),
                duration_ms=duration,
            )

    async def _execute_search_external(self, step: PlanStep) -> list[dict[str, Any]]:
        """Harici kaynaklarda ara (PubMed, Crossref, journal'lar)."""
        if not self.orchestrator or not hasattr(self.orchestrator, "search"):
            return []

        query = step.search_query or ""
        result = await self.orchestrator.search(query, limit_per_agent=step.limit)
        all_results = result.get("results", [])

        # Kaynak tipine gore filtrele
        if step.source_filter:
            all_results = [
                r for r in all_results
                if r.get("source") in step.source_filter
            ]

        return all_results[:step.limit]

    async def _execute_search_archive(self, step: PlanStep) -> list[dict[str, Any]]:
        """Mevcut Arı Kaynak arsivinde ara."""
        if not self.orchestrator or not hasattr(self.orchestrator, "search"):
            return []

        query = step.search_query or ""
        result = await self.orchestrator.search(query, limit_per_agent=step.limit)
        all_results = result.get("results", [])

        archive = [r for r in all_results if r.get("source") == "archive"]
        return archive[:step.limit]

    async def _execute_search_health_org(self, step: PlanStep) -> list[dict[str, Any]]:
        """Saglik kuruluslarinda ara (WHO, CDC, ESC vb.)."""
        if not self.orchestrator or not hasattr(self.orchestrator, "search"):
            return []

        query = step.search_query or ""
        result = await self.orchestrator.search(query, limit_per_agent=step.limit)
        all_results = result.get("results", [])

        health_orgs = [
            r for r in all_results
            if r.get("source") not in ("archive", "pubmed", "crossref")
        ]
        return health_orgs[:step.limit]

    async def _execute_check_contradictions(self, step: PlanStep) -> list[dict[str, Any]]:
        """Celişkili kanitlari kontrol et."""
        if not self.orchestrator or not hasattr(self.orchestrator, "search"):
            return []

        query = step.search_query or ""
        result = await self.orchestrator.search(query, limit_per_agent=step.limit)
        all_results = result.get("results", [])

        # Celişki gostergelerini ara
        contradiction_keywords = [
            "contradict", "no evidence", "ineffective", "no benefit",
            "risk", "harm", "side effect", "caelişki", "etkisiz", "zarar",
        ]

        contradictions = []
        for r in all_results:
            text = (r.get("text", "") + " " + r.get("title", "")).lower()
            if any(kw in text for kw in contradiction_keywords):
                contradictions.append(r)

        return contradictions[:step.limit]

    async def _execute_lookup_previous(self, step: PlanStep) -> list[dict[str, Any]]:
        """Onceki dogrulama sonuclarina bak."""
        if not self.db:
            return []

        claim = step.search_query
        if not claim:
            return []

        # DB'den onceki dogrulamalari getir
        try:
            records = self.db.get_verification_history(limit=10)
            matching = [
                r for r in records
                if claim and claim.lower() in (r.get("claim_text", "").lower())
            ]
            return matching
        except Exception as e:
            logger.warning(f"Failed to lookup previous verifications: {e}")
            return []

    async def _execute_ask_clarification(self, step: PlanStep) -> list[dict[str, Any]]:
        """Kullanici netlestirmesi gerekli — bos sonuc don."""
        return []

    def _categorize_results(self, result: InvestigationResult) -> None:
        """Sonuclari kategorilere ayir ve toplam sayiyi hesapla."""
        all_results = []

        for sr in result.step_results:
            if not sr.success:
                if sr.error:
                    result.errors.append(sr.error)
                continue

            for r in sr.results:
                r["_step_type"] = sr.step.step_type.value
                r["_priority"] = sr.step.priority.value
                all_results.append(r)

                source = r.get("source", "")
                if source == "archive":
                    result.archive_results.append(r)
                elif source in ("pubmed", "crossref", "nejm", "jama", "lancet", "bmj"):
                    result.external_results.append(r)
                else:
                    result.health_org_results.append(r)

        result.all_results = all_results
        result.total_sources = len(all_results)
