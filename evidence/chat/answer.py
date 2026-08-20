"""Answer Planner — cevabin nasil yapilandirilacagini belirler.

Sufficiency check'ten sonra, response oncesinde:
- Intent'e gore cevap formati sec
- Kanitlari onem sirasina koy
- Eksik parcalari belirt
- Dashboard icin uygun yapıyı olustur

Bu katman LLM kullanmaz — tamamen kural tabanli karar verir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .intent import Intent, IntentType, Topic
from .sufficiency import SufficiencyLevel, SufficiencyResult


class AnswerFormat(str, Enum):
    """Cevap formatlari."""
    FULL_VERIFICATION = "full_verification"     # Tam dogrulama raporu
    QUICK_SUMMARY = "quick_summary"             # Hizli ozet
    EXPLANATION = "explanation"                 # Neden-sonuc aciklamasi
    EVIDENCE_LIST = "evidence_list"             # Kanit listesi
    CLARIFICATION = "clarification"             # Netlestirme sorusu
    COUNTER_EVIDENCE = "counter_evidence"       # Celişkili kanitlar
    META_INFO = "meta_info"                     # Sistem hakkinda bilgi


class AnswerSection(str, Enum):
    """Cevap bolumleri."""
    HEADER = "header"                    # Baslik ve iddia
    VERDICT = "verdict"                  # Hukum
    SUMMARY = "summary"                  # Ozet
    EVIDENCE_ANALYSIS = "evidence"       # Kanit analizi
    SOURCES = "sources"                  # Kaynak listesi
    CONTRADICTIONS = "contradictions"    # Celişkiler
    METHODOLOGY = "methodology"          # Yontem notu
    CONFIDENCE = "confidence"            # Guven aciklamasi
    FOLLOW_UP = "follow_up"             # Sonraki adim onerileri
    TIMELINE = "timeline"               # Arastirma suresi
    PROVENANCE = "provenance"            # Kaynak zinciri


@dataclass
class AnswerPlan:
    """Cevap plani — hangi bolumlerin olacagini ve sirasini belirler."""
    format: AnswerFormat
    sections: list[AnswerSection] = field(default_factory=list)
    priority_sections: list[AnswerSection] = field(default_factory=list)
    excluded_sections: list[AnswerSection] = field(default_factory=list)
    evidence_limit: int = 5
    include_timeline: bool = False
    include_provenance: bool = False
    tone: str = "neutral"  # neutral, cautious, confident, explanatory
    language: str = "tr"   # tr, en

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format.value,
            "sections": [s.value for s in self.sections],
            "priority_sections": [s.value for s in self.priority_sections],
            "evidence_limit": self.evidence_limit,
            "include_timeline": self.include_timeline,
            "include_provenance": self.include_provenance,
            "tone": self.tone,
        }


class AnswerPlanner:
    """Cevap yapilandirmasini planlayan motor.

    Intent + Sufficiency + Evidence sonucuna gore:
    - Hangi format kullanilacak
    - Hangi bolumler olacak
    - Kanitlar nasil sunulacak
    """

    def plan(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        evidence_count: int = 0,
        contradiction_count: int = 0,
        has_previous_context: bool = False,
    ) -> AnswerPlan:
        """Cevap plani olustur."""
        method = getattr(self, f"_plan_{intent.type.value}", self._plan_default)
        plan = method(intent, sufficiency, evidence_count, contradiction_count, has_previous_context)

        # Sufficiency'e gore ayarla
        if sufficiency.level == SufficiencyLevel.INSUFFICIENT:
            plan.excluded_sections.append(AnswerSection.EVIDENCE_ANALYSIS)
            plan.excluded_sections.append(AnswerSection.CONTRADICTIONS)
            plan.tone = "cautious"
        elif sufficiency.level == SufficiencyLevel.PARTIALLY_SUFFICIENT:
            plan.evidence_limit = min(plan.evidence_limit, 3)
            plan.tone = "cautious"

        return plan

    def _plan_verify_claim(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        evidence_count: int,
        contradiction_count: int,
        has_previous: bool,
    ) -> AnswerPlan:
        """Yeni iddia dogrulama — en kapsamli cevap."""
        sections = [
            AnswerSection.HEADER,
            AnswerSection.VERDICT,
            AnswerSection.SUMMARY,
            AnswerSection.EVIDENCE_ANALYSIS,
            AnswerSection.SOURCES,
        ]

        if contradiction_count > 0:
            sections.append(AnswerSection.CONTRADICTIONS)

        sections.extend([
            AnswerSection.METHODOLOGY,
            AnswerSection.CONFIDENCE,
            AnswerSection.FOLLOW_UP,
        ])

        return AnswerPlan(
            format=AnswerFormat.FULL_VERIFICATION,
            sections=sections,
            priority_sections=[AnswerSection.VERDICT, AnswerSection.SUMMARY],
            evidence_limit=5,
            include_timeline=True,
            include_provenance=True,
            tone="neutral",
        )

    def _plan_follow_up_why(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        evidence_count: int,
        contradiction_count: int,
        has_previous: bool,
    ) -> AnswerPlan:
        """'Neden oyle?' — aciklama odakli."""
        sections = [
            AnswerSection.HEADER,
            AnswerSection.VERDICT,
            AnswerSection.EXPLANATION if AnswerSection.EXPLANATION else AnswerSection.SUMMARY,
            AnswerSection.EVIDENCE_ANALYSIS,
            AnswerSection.SOURCES,
        ]

        return AnswerPlan(
            format=AnswerFormat.EXPLANATION,
            sections=sections,
            priority_sections=[AnswerSection.VERDICT, AnswerSection.EVIDENCE_ANALYSIS],
            evidence_limit=3,
            include_provenance=True,
            tone="explanatory",
        )

    def _plan_follow_up_more(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        evidence_count: int,
        contradiction_count: int,
        has_previous: bool,
    ) -> AnswerPlan:
        """'Daha fazla kanit' — kanit listesi odakli."""
        sections = [
            AnswerSection.HEADER,
            AnswerSection.EVIDENCE_ANALYSIS,
            AnswerSection.SOURCES,
            AnswerSection.FOLLOW_UP,
        ]

        return AnswerPlan(
            format=AnswerFormat.EVIDENCE_LIST,
            sections=sections,
            priority_sections=[AnswerSection.EVIDENCE_ANALYSIS],
            evidence_limit=8,
            include_provenance=True,
            tone="neutral",
        )

    def _plan_follow_up_different(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        evidence_count: int,
        contradiction_count: int,
        has_previous: bool,
    ) -> AnswerPlan:
        """'Baska kaynak' — cesitli kaynaklar."""
        return self._plan_follow_up_more(intent, sufficiency, evidence_count, contradiction_count, has_previous)

    def _plan_challenge_verdict(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        evidence_count: int,
        contradiction_count: int,
        has_previous: bool,
    ) -> AnswerPlan:
        """'Katilmiyorum' — celişkili kanitlar on planda."""
        sections = [
            AnswerSection.HEADER,
            AnswerSection.VERDICT,
            AnswerSection.CONTRADICTIONS,
            AnswerSection.EVIDENCE_ANALYSIS,
            AnswerSection.SOURCES,
            AnswerSection.CONFIDENCE,
        ]

        return AnswerPlan(
            format=AnswerFormat.COUNTER_EVIDENCE,
            sections=sections,
            priority_sections=[AnswerSection.CONTRADICTIONS, AnswerSection.EVIDENCE_ANALYSIS],
            evidence_limit=5,
            include_provenance=True,
            tone="neutral",
        )

    def _plan_clarify_context(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        evidence_count: int,
        contradiction_count: int,
        has_previous: bool,
    ) -> AnswerPlan:
        """Netlestirme sorusu."""
        return AnswerPlan(
            format=AnswerFormat.CLARIFICATION,
            sections=[AnswerSection.HEADER, AnswerSection.FOLLOW_UP],
            tone="neutral",
        )

    def _plan_explore_topic(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        evidence_count: int,
        contradiction_count: int,
        has_previous: bool,
    ) -> AnswerPlan:
        """Konu kesfi — genel bakis."""
        sections = [
            AnswerSection.HEADER,
            AnswerSection.SUMMARY,
            AnswerSection.SOURCES,
            AnswerSection.FOLLOW_UP,
        ]

        return AnswerPlan(
            format=AnswerFormat.QUICK_SUMMARY,
            sections=sections,
            evidence_limit=3,
            tone="neutral",
        )

    def _plan_meta_question(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        evidence_count: int,
        contradiction_count: int,
        has_previous: bool,
    ) -> AnswerPlan:
        """Sistem hakkinda bilgi."""
        return AnswerPlan(
            format=AnswerFormat.META_INFO,
            sections=[AnswerSection.HEADER],
            tone="neutral",
        )

    def _plan_default(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        evidence_count: int,
        contradiction_count: int,
        has_previous: bool,
    ) -> AnswerPlan:
        """Varsayilan plan."""
        return self._plan_verify_claim(intent, sufficiency, evidence_count, contradiction_count, has_previous)
