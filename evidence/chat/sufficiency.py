"""Yeterlilik kontrolu — toplanan kanit yeterli mi?

Dashboard context'inde kullanici her zaman tatmin olmayabilir.
Yeterlilik kontrolu:
- Yeterli kaynak var mi?
- Kalite yeterli mi?
- Celişki var mi ve bu onemli mi?
- Tekrar arastirma gerekli mi?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .intent import Intent, IntentType


class SufficiencyLevel(str, Enum):
    """Yeterlilik seviyeleri."""
    SUFFICIENT = "sufficient"             # Yeterli — cevap ver
    PARTIALLY_SUFFICIENT = "partial"     # Kısmen yeterli —sinirli cevap
    INSUFFICIENT = "insufficient"        # Yetersiz — tekrar ara veya sor
    NEEDS_CLARIFICATION = "clarification"  # Kullanicidan netlestirme gerekli


@dataclass
class SufficiencyResult:
    """Yeterlilik analiz sonucu."""
    level: SufficiencyLevel
    confidence: float  # 0.0 - 1.0
    reasons: list[str] = field(default_factory=list)
    suggested_action: str = ""
    should_retry: bool = False
    retry_with_different_sources: bool = False
    need_more_evidence: bool = False  # Daha fazla kanit gerekli mi?

    @property
    def is_sufficient(self) -> bool:
        return self.level in (SufficiencyLevel.SUFFICIENT, SufficiencyLevel.PARTIALLY_SUFFICIENT)

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "confidence": round(self.confidence, 3),
            "reasons": self.reasons,
            "suggested_action": self.suggested_action,
            "should_retry": self.should_retry,
            "need_more_evidence": self.need_more_evidence,
        }


@dataclass
class SufficiencyMetrics:
    """Yeterlilik metrikleri."""
    total_sources: int = 0
    archive_count: int = 0
    external_count: int = 0
    health_org_count: int = 0
    contradiction_count: int = 0
    avg_quality: float = 0.0
    has_primary_source: bool = False
    has_health_org: bool = False
    has_recent_source: bool = False  # Son 2 yil


class SufficiencyChecker:
    """Kanit yeterliligini kontrol eden motor.

    Faktorler:
    1. Kaynak sayisi (min 2 gerekli, 5+ ideal)
    2. Kaynak cesitliligi (akademik + kurumsal)
    3. Kaynak kalitesi (birincil kaynak var mi?)
    4. Celişki durumu (ciddi celişki var mi?)
    5. Intent'e gore ozel kosullar
    """

    # Intent'e gore minimum kosullar
    MIN_SOURCES: dict[IntentType, int] = {
        IntentType.VERIFY_CLAIM: 3,
        IntentType.FOLLOW_UP_WHY: 1,
        IntentType.FOLLOW_UP_MORE: 2,
        IntentType.FOLLOW_UP_DIFFERENT: 2,
        IntentType.CHALLENGE_VERDICT: 3,
        IntentType.EXPLORE_TOPIC: 2,
        IntentType.CLARIFY_CONTEXT: 0,
        IntentType.META_QUESTION: 0,
    }

    def check(
        self,
        intent: Intent,
        metrics: SufficiencyMetrics,
        previous_verdict: str | None = None,
    ) -> SufficiencyResult:
        """Yeterlilik kontrolu yap."""
        # Meta ve clarify icin ozel durum
        if intent.type in (IntentType.META_QUESTION, IntentType.CLARIFY_CONTEXT):
            return SufficiencyResult(
                level=SufficiencyLevel.SUFFICIENT,
                confidence=1.0,
                reasons=["Bu tur sorular icin kanit gerekmez"],
                suggested_action="Dogrudan cevap ver",
            )

        reasons: list[str] = []
        score = 0.0

        # 1. Kaynak sayisi kontrolu
        min_required = self.MIN_SOURCES.get(intent.type, 3)
        if metrics.total_sources >= min_required:
            score += 0.3
            reasons.append(f"Yeterli kaynak: {metrics.total_sources} (min: {min_required})")
        elif metrics.total_sources >= min_required - 1:
            score += 0.15
            reasons.append(f"Sinirli kaynak: {metrics.total_sources} (min: {min_required})")
        else:
            reasons.append(f"Yetersiz kaynak: {metrics.total_sources} (min: {min_required})")

        # 2. Kaynak cesitliligi
        source_types = sum([
            1 if metrics.archive_count > 0 else 0,
            1 if metrics.external_count > 0 else 0,
            1 if metrics.health_org_count > 0 else 0,
        ])
        if source_types >= 2:
            score += 0.25
            reasons.append(f"Farkli kaynak turleri: {source_types}")
        elif source_types == 1:
            score += 0.1
            reasons.append("Tek kaynak turu")

        # 3. Kaynak kalitesi
        if metrics.has_primary_source:
            score += 0.2
            reasons.append("Birincil kaynak mevcut (RCT, kohort)")

        if metrics.has_health_org:
            score += 0.1
            reasons.append("Resmi saglik kurumu kaynagi mevcut")

        # 4. Celişki durumu
        if metrics.contradiction_count > 0:
            if intent.type == IntentType.CHALLENGE_VERDICT:
                # Itiraz durumunda celişki iyi bir sey
                score += 0.15
                reasons.append(f"Celişkili kanitlar bulundu ({metrics.contradiction_count}) — itiraz icin onemli")
            else:
                # Normal durumda celişki guveni dusur
                score -= 0.1
                reasons.append(f"Celişkili kanitlar ({metrics.contradiction_count}) — dikkatli ol")
        else:
            score += 0.05

        # 5. Intent'e gore ozel kosullar
        if intent.type == IntentType.FOLLOW_UP_WHY:
            # onceki sonucu biliyorsa yeterli olabilir
            if previous_verdict:
                score += 0.2
                reasons.append("Onceki sonuc mevcut — aciklama yapilabilir")

        if intent.type == IntentType.FOLLOW_UP_MORE:
            # Daha fazla kanit istiyorsa, mevcut kaynak sayisi onemli
            if metrics.total_sources >= 5:
                score += 0.2
                reasons.append("Yeterli ek kaynak mevcut")

        # Sonucu belirle
        if score >= 0.6:
            level = SufficiencyLevel.SUFFICIENT
            action = "Tam cevap ver — kanitlar yeterli"
            should_retry = False
            need_more = False
        elif score >= 0.4:
            level = SufficiencyLevel.PARTIALLY_SUFFICIENT
            action = "Sinirli cevap ver — kaynak kisitlarini belirt"
            should_retry = False
            need_more = False
        elif score >= 0.2:
            level = SufficiencyLevel.INSUFFICIENT
            action = "Tekrar arastir — farkli kaynaklar dene"
            should_retry = True
            need_more = True
        else:
            level = SufficiencyLevel.NEEDS_CLARIFICATION
            action = "Kullaniciya sor — daha spesifik ol"
            should_retry = False
            need_more = False

        return SufficiencyResult(
            level=level,
            confidence=min(score, 1.0),
            reasons=reasons,
            suggested_action=action,
            should_retry=should_retry,
            retry_with_different_sources=score < 0.3,
            need_more_evidence=need_more,
        )

    def extract_metrics(
        self,
        archive_results: list[dict],
        external_results: list[dict],
        health_org_results: list[dict],
        contradictions: list[dict],
    ) -> SufficiencyMetrics:
        """Arama sonuclarindan metrikleri cikar."""
        all_results = archive_results + external_results + health_org_results

        total_quality = 0
        quality_count = 0
        has_primary = False
        has_health = len(health_org_results) > 0
        has_recent = False

        for r in all_results:
            quality = r.get("quality_score", 0)
            if quality > 0:
                total_quality += quality
                quality_count += 1

            source_type = r.get("source_type", "")
            if source_type in ("primary", "clinical_trial"):
                has_primary = True

            year = r.get("published_year")
            if year and isinstance(year, (int, float)) and year >= 2022:
                has_recent = True

        return SufficiencyMetrics(
            total_sources=len(all_results),
            archive_count=len(archive_results),
            external_count=len(external_results),
            health_org_count=len(health_org_results),
            contradiction_count=len(contradictions),
            avg_quality=(total_quality / quality_count) if quality_count > 0 else 0.0,
            has_primary_source=has_primary,
            has_health_org=has_health,
            has_recent_source=has_recent,
        )
