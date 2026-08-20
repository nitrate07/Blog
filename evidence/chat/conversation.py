"""Ana konusma yoneticisi — tum akisi koordine eder.

Akis (yeni):
1. User → Conversation Context
2. Intent / Question Understanding
3. Investigation Planner
4. AI Tools + Graph + Timeline + Evidence
5. Sufficiency Check
6. Need more evidence? → YES → Research again → NO → Continue
7. Answer Planner
8. Natural Conversational Response
9. → User

Bu sinif dashboard icin tasarlanmistir:
- Tek kullanicili session yonetimi
- Onceki konusma baglami takibi
- Follow-up sorulari destegi
- Kanit zinciri gorunurlugu
- Loop mekanizması: yetersiz kanit durumunda tekrar arastirma
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .intent import Intent, IntentAnalyzer, IntentType
from .investigator import EvidenceInvestigator, InvestigationResult
from .planner import InvestigationPlan, Planner
from .response import ChatResponse, ResponseBuilder
from .sufficiency import SufficiencyChecker, SufficiencyResult
from .answer import AnswerPlanner, AnswerPlan

logger = logging.getLogger(__name__)


@dataclass
class ConversationTurn:
    """Tek bir konusma turu."""
    user_query: str
    intent: Intent
    plan: InvestigationPlan | None = None
    investigation: InvestigationResult | None = None
    sufficiency: SufficiencyResult | None = None
    response: ChatResponse | None = None
    duration_ms: float = 0.0
    timestamp: str = ""


@dataclass
class ConversationState:
    """Konusma durumu — session boyunca saklanir."""
    session_id: str = ""
    turns: list[ConversationTurn] = field(default_factory=list)
    current_claim: str | None = None
    current_verdict: str | None = None
    current_confidence: float = 0.0
    last_verification: dict[str, Any] | None = None
    turn_count: int = 0

    def last_user_query(self) -> str | None:
        if self.turns:
            return self.turns[-1].user_query
        return None

    def last_assistant_response(self) -> str | None:
        if self.turns and self.turns[-1].response:
            return self.turns[-1].response.text
        return None

    def get_history_for_api(self) -> list[dict[str, str]]:
        """LLM icin konusma gecmisi."""
        messages = []
        for turn in self.turns:
            messages.append({"role": "user", "content": turn.user_query})
            if turn.response:
                messages.append({"role": "assistant", "content": turn.response.text})
        return messages


class ConversationManager:
    """Tum konusma akisini yoneten ana sinif.

    Dashboard backend'inden boyle kullanilir:
    ```python
    manager = ConversationManager(orchestrator, llm_provider, db)
    response = await manager.handle_message("GLP-1 kilo vermede etkili mi?")
    ```
    """

    MAX_RETRIES = 2  # Yetersiz kanit durumunda max tekrar
    MAX_INVESTIGATION_LOOPS = 3  # Max arastirma dongusu

    def __init__(
        self,
        orchestrator: Any | None = None,
        llm_provider: Any | None = None,
        db: Any | None = None,
        graph_store: Any | None = None,
    ) -> None:
        self.intent_analyzer = IntentAnalyzer()
        self.planner = Planner()
        self.investigator = EvidenceInvestigator(
            orchestrator=orchestrator,
            graph_store=graph_store,
            db=db,
        )
        self.sufficiency_checker = SufficiencyChecker()
        self.answer_planner = AnswerPlanner()
        self.response_builder = ResponseBuilder()
        self.llm_provider = llm_provider
        self.db = db

        self.state = ConversationState()

    async def handle_message(self, user_query: str) -> ChatResponse:
        """Kullanici mesajini isle ve cevap don.

        Yeni akis:
        1. Intent analizi
        2. Plan olusturma
        3. Arastirma (loop ile)
        4. Yeterlilik kontrolu
        5. Daha fazla kanit gerekli mi? → Evet → 3'e don
        6. Answer Planner
        7. Cevap uretimi
        """
        start = time.monotonic()

        # 1. Intent analizi
        intent = self.intent_analyzer.analyze(
            query=user_query,
            conversation_history=self.state.get_history_for_api(),
            last_claim=self.state.current_claim,
            last_verdict=self.state.current_verdict,
        )
        logger.info(f"Intent: {intent.type.value} (confidence: {intent.confidence:.2f})")

        # 2. Plan olusturma
        plan = self.planner.create_plan(intent)
        logger.info(f"Plan: {len(plan.all_active_steps())} steps")

        # 3. Arastirma (loop ile — need_more_evidence durumunda tekrar ara)
        investigation = await self._investigate_with_loop(plan, intent)

        # 4. Yeterlilik kontrolu
        metrics = self.sufficiency_checker.extract_metrics(
            archive_results=investigation.archive_results,
            external_results=investigation.external_results,
            health_org_results=investigation.health_org_results,
            contradictions=investigation.contradictions,
        )
        sufficiency = self.sufficiency_checker.check(
            intent=intent,
            metrics=metrics,
            previous_verdict=self.state.current_verdict,
        )
        logger.info(f"Sufficiency: {sufficiency.level.value}")

        # 5. Answer Planner — cevap yapilandirmasini belirle
        answer_plan = self.answer_planner.plan(
            intent=intent,
            sufficiency=sufficiency,
            evidence_count=investigation.total_sources,
            contradiction_count=len(investigation.contradictions),
            has_previous_context=self.state.last_verification is not None,
        )
        logger.info(f"Answer format: {answer_plan.format.value}")

        # 6. Cevap uretimi
        results_dict = {
            "archive_results": investigation.archive_results,
            "external_results": investigation.external_results,
            "health_org_results": investigation.health_org_results,
            "contradictions": investigation.contradictions,
            "total_sources": investigation.total_sources,
            "verdict": self.state.current_verdict,
            "verdict_confidence": self.state.current_confidence,
            "timeline": investigation.timeline.to_dict(),
        }

        response = self.response_builder.build(
            intent=intent,
            sufficiency=sufficiency,
            investigation_results=results_dict,
            previous_context=self.state.last_verification,
        )

        # 7. State guncelle
        duration = (time.monotonic() - start) * 1000
        turn = ConversationTurn(
            user_query=user_query,
            intent=intent,
            plan=plan,
            investigation=investigation,
            sufficiency=sufficiency,
            response=response,
            duration_ms=duration,
        )
        self.state.turns.append(turn)
        self.state.turn_count += 1

        # Onceki dogrulama bilgisini guncelle
        if intent.type == IntentType.VERIFY_CLAIM:
            self.state.current_claim = intent.cleaned_query
            self.state.current_verdict = investigation.all_results[0].get("verdict") if investigation.all_results else None
            self.state.last_verification = {
                "claim_text": intent.cleaned_query,
                "verdict": self.state.current_verdict,
                "confidence": investigation.all_results[0].get("quality_score", 0) if investigation.all_results else 0,
                "sources_count": investigation.total_sources,
                "steps": [],
            }

        logger.info(f"Turn completed in {duration:.0f}ms")

        return response

    async def _investigate_with_loop(
        self,
        plan: InvestigationPlan,
        intent: Intent,
    ) -> InvestigationResult:
        """Arastirma dongusu — need_more_evidence durumunda tekrar ara."""
        investigation = await self.investigator.investigate(plan)

        # Loop kontrolu
        for loop in range(self.MAX_INVESTIGATION_LOOPS):
            # Yeterlilik kontrolu
            metrics = self.sufficiency_checker.extract_metrics(
                archive_results=investigation.archive_results,
                external_results=investigation.external_results,
                health_org_results=investigation.health_org_results,
                contradictions=investigation.contradictions,
            )
            sufficiency = self.sufficiency_checker.check(
                intent=intent,
                metrics=metrics,
                previous_verdict=self.state.current_verdict,
            )

            # Daha fazla kanit gerekli mi?
            if not sufficiency.need_more_evidence:
                logger.info(f"Sufficiency reached at loop {loop + 1}")
                break

            if sufficiency.retry_with_different_sources:
                logger.info(f"Loop {loop + 1}: Retrying with different sources")
                investigation = await self.investigator.investigate(plan)
            else:
                logger.info(f"Loop {loop + 1}: No more retries needed")
                break

        return investigation

    def reset(self) -> None:
        """Session'i sifirla."""
        self.state = ConversationState()

    def get_state(self) -> ConversationState:
        """Mevcut durumu dondur."""
        return self.state

    def get_stats(self) -> dict[str, Any]:
        """Session istatistiklerini dondur."""
        return {
            "session_id": self.state.session_id,
            "turn_count": self.state.turn_count,
            "total_duration_ms": sum(t.duration_ms for t in self.state.turns),
            "intent_distribution": self._intent_distribution(),
            "total_sources_found": sum(
                t.investigation.total_sources
                for t in self.state.turns
                if t.investigation
            ),
        }

    def _intent_distribution(self) -> dict[str, int]:
        """Intent dagilimini hesapla."""
        dist: dict[str, int] = {}
        for turn in self.state.turns:
            intent_type = turn.intent.type.value
            dist[intent_type] = dist.get(intent_type, 0) + 1
        return dist
