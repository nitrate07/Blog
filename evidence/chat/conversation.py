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

from .intent import SOCIAL_INTENTS, Intent, IntentAnalyzer, IntentType
from .investigator import EvidenceInvestigator, InvestigationResult
from .planner import InvestigationPlan, Planner
from .response import ChatResponse, ResponseBuilder
from .search_query import build_search_query
from .sufficiency import SufficiencyChecker, SufficiencyResult
from .answer import AnswerPlanner, AnswerPlan

logger = logging.getLogger(__name__)

# Kaynak guven agirliklari — hukum sentezinde kalite carpani olarak kullanilir.
_SOURCE_QUALITY = {
    "archive": 1.0,
    "cochrane": 1.0,
    "who": 0.95,
    "cdc": 0.95,
    "ecdc": 0.95,
    "nice": 0.95,
    "tuseb": 0.95,
    "fda": 0.9,
    "ema": 0.9,
    "esc": 0.9,
    "aha": 0.9,
    "nejm": 1.0,
    "jama": 1.0,
    "lancet": 1.0,
    "bmj": 1.0,
    "clinicaltrials": 0.85,
    "pubmed": 0.85,
    "europepmc": 0.85,
    "openalex": 0.75,
    "crossref": 0.7,
}


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

        # 1b. Sosyal niyetler (selamlasma, tesekkur, kimlik...) — arastirma yok,
        #     dogrudan uzman yaniti. Bu mesajlar iddia degildir; state'i bozmaz.
        #     llm_provider ayarliysa sabit sablon yerine daha dogal bir yanit
        #     denenir (bkz. social_chat.narrate_social) — basarisiz olursa
        #     sabit sablona geri doner (fail-closed, sifir davranis degisikligi
        #     garantisi llm_provider=None icin).
        if intent.type in SOCIAL_INTENTS:
            response = self.response_builder.build_social(intent)
            if self.llm_provider is not None:
                from .social_chat import narrate_social

                narrated = await narrate_social(
                    intent_type=intent.type.value,
                    user_message=user_query,
                    recent_history=self.state.get_history_for_api(),
                    provider=self.llm_provider,
                )
                if narrated is not None:
                    response.text = narrated
            duration = (time.monotonic() - start) * 1000
            self.state.turns.append(ConversationTurn(
                user_query=user_query,
                intent=intent,
                response=response,
                duration_ms=duration,
            ))
            self.state.turn_count += 1
            return response

        # 2. Plan olusturma — ama once guvenlik kapisi: "iddia" gorunumlu
        #    mesaj icinde aranabilir bir saglik konusu yoksa (orn. "nasıl
        #    çalışıyorsun?") bosuna 20 aji harekete getirme; aciklama ver.
        if intent.type == IntentType.VERIFY_CLAIM and not build_search_query(intent.cleaned_query):
            response = self.response_builder._social_identity(intent)
            duration = (time.monotonic() - start) * 1000
            self.state.turns.append(ConversationTurn(
                user_query=user_query,
                intent=intent,
                response=response,
                duration_ms=duration,
            ))
            self.state.turn_count += 1
            return response

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

        # 5b. Hukum sentezi — kanit pasajlari uzerinden deterministik hukum uret.
        #     Arsiv damgasi varsa onceliklidir; yoksa pasajlar motorun
        #     deterministik karsilastirmasindan gecer (LLM kullanilmaz).
        verdict_info = self._derive_verdict(intent.cleaned_query, investigation)

        # 6. Cevap uretimi
        results_dict = {
            "archive_results": investigation.archive_results,
            "external_results": investigation.external_results,
            "health_org_results": investigation.health_org_results,
            "contradictions": investigation.contradictions,
            "total_sources": investigation.total_sources,
            "verdict": verdict_info["verdict"],
            "verdict_confidence": verdict_info["confidence"],
            "verdict_conflict": verdict_info["conflict"],
            "consensus": verdict_info["consensus"],
            "timeline": investigation.timeline.to_dict(),
        }

        response = self.response_builder.build(
            intent=intent,
            sufficiency=sufficiency,
            investigation_results=results_dict,
            previous_context=self.state.last_verification,
        )
        # 6b. Aciklayici (LLM) + Duzenleyici — llm_provider yoksa veya hukum
        #     yoksa metin degismeden kural-tabanli kalir (bkz. _narrate_response).
        response.text = await self._narrate_response(
            claim=intent.cleaned_query,
            verdict_info=verdict_info,
            results_dict=results_dict,
            rule_based_text=response.text,
        )
        # Kaynak gorunurlugu: arayuzun kart olarak gosterebilecegi yapisal liste.
        response.metadata["sources"] = self._collect_source_metadata(investigation)
        response.metadata["verdict"] = verdict_info["verdict"]
        response.metadata["verdict_confidence"] = verdict_info["confidence"]
        response.sources_cited = investigation.total_sources

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
            self.state.current_verdict = verdict_info["verdict"]
            self.state.current_confidence = verdict_info["confidence"]
            self.state.last_verification = {
                "claim_text": intent.cleaned_query,
                "verdict": verdict_info["verdict"],
                "confidence": verdict_info["confidence"],
                "sources_count": investigation.total_sources,
                "steps": [],
            }

        logger.info(f"Turn completed in {duration:.0f}ms")

        return response

    async def _narrate_response(
        self,
        claim: str,
        verdict_info: dict[str, Any],
        results_dict: dict[str, Any],
        rule_based_text: str,
    ) -> str:
        """Aciklayici (LLM) + Duzenleyici katmani.

        llm_provider ayarli DEGILSE ya da bu turda deterministik bir hukum
        uretilemediyse (verdict_info["verdict"] None), bugunku davranisla
        BIREBIR ayni sekilde kural-tabanli metni degistirmeden dondurur —
        bu, llm_provider=None olan test/CI varsayilaninda sifir davranis
        degisikligi garanti eder.

        LLM taslagi uretilse bile, duzenleyici (editor.edit_and_validate)
        saglanmayan bir kaynaga atif yaptigini tespit ederse taslak REDDEDILIR
        ve yine kural-tabanli metne donulur — dogrulanmamis metin kullaniciya
        asla gosterilmez (fail-closed).
        """
        if self.llm_provider is None or not verdict_info.get("verdict"):
            return rule_based_text

        from .editor import edit_and_validate, narrate_verdict

        matches: list[dict[str, Any]] = []
        for r in (
            list(results_dict.get("archive_results", []))
            + list(results_dict.get("external_results", []))
            + list(results_dict.get("health_org_results", []))
        ):
            url = r.get("url")
            if not url:
                continue
            matches.append({
                "title": r.get("title") or "",
                "url": url,
                "source_type": r.get("source_type") or "unknown",
                "quality_score": _SOURCE_QUALITY.get(r.get("source", ""), 0.7),
                "text": r.get("passage") or r.get("text") or "",
            })

        draft = await narrate_verdict(
            claim=claim,
            verdict=verdict_info["verdict"],
            confidence=verdict_info["confidence"],
            matches=matches,
            provider=self.llm_provider,
        )
        if draft is None:
            return rule_based_text

        edited = edit_and_validate(draft, matches)
        if edited is None:
            return rule_based_text

        return edited

    def _derive_verdict(self, claim: str, investigation: InvestigationResult) -> dict[str, Any]:
        """Kanit pasajlarindan deterministik hukum sentezi (LLM yok).

        Oncelik: arsiv damgasi (rating_value) > pasaj karsilastirmasi.
        Toplama kurallari engine.py ile aynidir: dogrudan celiski ortalanmaz,
        en iyi alaka*kalite kazanir; alaka esigi altinda hukum verilmez.
        """
        from evidence.engine import compare_claim_evidence

        en_query = build_search_query(claim)
        comparisons: list[tuple[str, float, float]] = []  # (verdict, relevance, quality)

        for r in investigation.archive_results:
            quality = _SOURCE_QUALITY.get("archive", 1.0)
            rating = r.get("rating_value")
            distance = r.get("distance")
            if isinstance(rating, int) and rating >= 1:
                verdict = {5: "supported", 4: "mostly_supported", 3: "partly_supported"}.get(rating, "unsupported")
                relevance = max(0.3, min(1.0, 1.0 - float(distance))) if isinstance(distance, (int, float)) else 0.6
            else:
                verdict, _, relevance = compare_claim_evidence(claim, r.get("passage") or "")
                verdict = verdict.value
                if relevance < 0.28:
                    continue
            comparisons.append((verdict, relevance, quality))

        for r in investigation.external_results + investigation.health_org_results:
            passage = (r.get("passage") or "").strip()
            if not passage:
                continue
            quality = _SOURCE_QUALITY.get(r.get("source", ""), 0.7)
            verdict, _, relevance = compare_claim_evidence(en_query, passage)
            if relevance < 0.28:
                continue
            comparisons.append((verdict.value, relevance, quality))

        if not comparisons:
            return {"verdict": None, "confidence": 0.0, "consensus": {}, "conflict": False}

        # engine.py ile ayni kural: cok zayif "karsi" kanit hukumu devirmesin.
        unsupported = [c for c in comparisons if c[0] == "unsupported" and c[1] >= 0.35]
        best = max(comparisons, key=lambda c: c[1] * c[2])
        if unsupported and max(c[1] * c[2] for c in unsupported) >= best[1] * best[2] - 0.05:
            verdict = "unsupported"
            confidence = max(c[1] * c[2] for c in unsupported)
        else:
            verdict = best[0]
            confidence = best[1] * best[2]

        # Ajanlar-arasi uzlasi profili: her hukum yonunun agirlikli oyu.
        consensus: dict[str, float] = {}
        for v, rel, qual in comparisons:
            consensus[v] = round(consensus.get(v, 0.0) + rel * qual, 2)

        # Tartisma sinyali: arsiv damgasi ile harici kaynaklar ayri yone gidiyorsa
        # bunu acikca bildir — tek bir kaynagi mutlaklastirmadan.
        archive_verdicts = {c[0] for c in comparisons[: len(investigation.archive_results)]} if investigation.archive_results else set()
        external_verdicts = {c[0] for c in comparisons[len(investigation.archive_results):]}
        conflict = bool(
            archive_verdicts
            and external_verdicts
            and verdict not in (archive_verdicts & external_verdicts)
            and len(archive_verdicts | external_verdicts) > 1
        )
        return {"verdict": verdict, "confidence": round(min(0.9, confidence), 2), "consensus": consensus, "conflict": conflict}

    def _collect_source_metadata(self, investigation: InvestigationResult) -> list[dict[str, Any]]:
        """Yanita eklenecek yapisal kaynak listesi — arayuz kartlari icin."""
        sources: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        def add(items: list[dict[str, Any]], category: str, limit: int) -> None:
            for r in items[:limit]:
                url = r.get("url") or ""
                key = url.rstrip("/").lower()
                if not url or key in seen_urls:
                    continue
                seen_urls.add(key)
                sources.append({
                    "title": r.get("title") or "",
                    "url": url,
                    "source": r.get("source") or "",
                    "category": category,
                    "verdict": r.get("verdict"),
                    "published_year": r.get("published_year") or r.get("year"),
                })

        add(investigation.archive_results, "archive", 3)
        add(investigation.health_org_results, "health_org", 4)
        add(investigation.external_results, "academic", 5)
        return sources

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
