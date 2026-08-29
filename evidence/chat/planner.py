"""Kanit planlama — hangi arastirma adimlari gerektigini belirler.

Intent analizinden gelen niyete gore:
- Hangi kaynaklara bakilacagini
- Hangi sirayla aranacagini
- Her adimda ne aranacagini planlar
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from .intent import Intent
from .search_query import build_search_query


class StepType(str, Enum):
    """Plan adimi turleri."""
    SEARCH_EXTERNAL = "search_external"       # PubMed, Europe PMC, Crossref, dergiler
    SEARCH_ARCHIVE = "search_archive"         # Mevcut Arı Kaynak arsivi
    SEARCH_HEALTH_ORG = "search_health_org"  # WHO, CDC, NICE, TUSEB vb.
    CHECK_CONTRADICTIONS = "check_contradictions"  # Celişkileri kontrol et
    LOOKUP_PREVIOUS = "lookup_previous"       # Onceki dogrulamalara bak
    ASK_CLARIFICATION = "ask_clarification"   # Kullaniciya soru sor


class StepPriority(str, Enum):
    """Adim oncelikleri."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class PlanStep:
    """Tek bir arastirma adimi."""
    step_type: StepType
    priority: StepPriority
    description: str
    search_query: str | None = None
    source_filter: list[str] | None = None  # Hangi kaynaklar taranacak
    limit: int = 5
    skip: bool = False  # Bu adimi atla


@dataclass
class InvestigationPlan:
    """Tam arastirma plani."""
    intent: Intent
    steps: list[PlanStep] = field(default_factory=list)
    estimated_sources: int = 0
    priority_reason: str = ""

    def high_priority_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.priority == StepPriority.HIGH and not s.skip]

    def all_active_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if not s.skip]


class Planner:
    """Intent'e gore arastirma plani olusturucu.

    Her niyet turu icin farkli strateji:
    - verify_claim: Tum kaynaklari tar, kanit topla
    - follow_up_why: Mevcut sonucu acikla, ek kanit gerekirse bul
    - follow_up_more: Sadece ek kaynak ara
    - challenge_verdict: Celişkili kanitlari on planda ara
    - clarify_context: Kullanicidan netlestirme iste
    """

    def create_plan(self, intent: Intent) -> InvestigationPlan:
        """Intent'e gore arastirma plani olustur."""
        method = getattr(self, f"_plan_{intent.type.value}", self._plan_default)
        plan = method(intent)
        plan.estimated_sources = sum(s.limit for s in plan.all_active_steps())
        return plan

    def _plan_verify_claim(self, intent: Intent) -> InvestigationPlan:
        """Yeni iddia dogrulama plani — en kapsamli arastirma.

        Gorev alanlari ayriktir: arsiv Turkce orijinal sorguyla, harici
        akademik/resmi kanallar Ingilizce anahtar-kelime sorgusuyla arar
        (PubMed/Crossref/WHO gibi API'ler Turkce dogal dilde alakasiz sonuc dondurur).
        """
        claim = intent.cleaned_query
        en_query = build_search_query(claim)

        steps = [
            PlanStep(
                step_type=StepType.SEARCH_ARCHIVE,
                priority=StepPriority.HIGH,
                description="Mevcut Arı Kaynak arsivinde ara",
                search_query=claim,
                limit=5,
            ),
            PlanStep(
                step_type=StepType.SEARCH_EXTERNAL,
                priority=StepPriority.HIGH,
                description="Akademik kaynaklarda ara (PubMed, Europe PMC, dergiler)",
                search_query=en_query,
                source_filter=["pubmed", "crossref", "europepmc", "openalex", "nejm", "jama", "lancet", "bmj", "aha", "cochrane"],
                limit=5,
            ),
            PlanStep(
                step_type=StepType.SEARCH_HEALTH_ORG,
                priority=StepPriority.MEDIUM,
                description="Resmi saglik kurumlarinda ara (WHO, CDC, NICE, TUSEB)",
                search_query=en_query,
                limit=3,
            ),
            PlanStep(
                step_type=StepType.CHECK_CONTRADICTIONS,
                priority=StepPriority.MEDIUM,
                description="Celişkili kanitlari kontrol et",
                search_query=en_query,
                limit=3,
            ),
        ]

        return InvestigationPlan(
            intent=intent,
            steps=steps,
            priority_reason="Yeni iddia dogrulama — tum kaynaklar taranacak",
        )

    def _plan_follow_up_why(self, intent: Intent) -> InvestigationPlan:
        """'Neden oyle?' plani — onceki sonucu acikla."""
        steps = [
            PlanStep(
                step_type=StepType.LOOKUP_PREVIOUS,
                priority=StepPriority.HIGH,
                description="Onceki dogrulama sonucunu ve kanitlarini getir",
                search_query=intent.referenced_claim,
                limit=10,
            ),
            PlanStep(
                step_type=StepType.SEARCH_EXTERNAL,
                priority=StepPriority.MEDIUM,
                description="Ek aciklayici kanit ara (e.g. mekanizma calismalari)",
                search_query=build_search_query(intent.cleaned_query),
                limit=3,
            ),
        ]

        return InvestigationPlan(
            intent=intent,
            steps=steps,
            priority_reason="Onceki sonucun nedenini acikla — kanit zincirini geriye donuk goster",
        )

    def _plan_follow_up_more(self, intent: Intent) -> InvestigationPlan:
        """'Daha fazla kanit' plani — ek kaynak ara."""
        # Baglamdaki onceki iddia asil konudur; "daha fazla kanit goster"
        # gibi komut metni arama sorgusu OLAMAZ.
        base = intent.referenced_claim or intent.cleaned_query or intent.original_query
        en_query = build_search_query(base)
        steps = [
            PlanStep(
                step_type=StepType.SEARCH_EXTERNAL,
                priority=StepPriority.HIGH,
                description="Ek akademik makaleler ara",
                search_query=en_query,
                source_filter=["pubmed", "crossref", "europepmc", "openalex", "nejm", "jama", "lancet", "bmj"],
                limit=8,
            ),
            PlanStep(
                step_type=StepType.SEARCH_HEALTH_ORG,
                priority=StepPriority.HIGH,
                description="Ek resmi saglik kurumu kaynaklari ara",
                search_query=en_query,
                limit=5,
            ),
        ]

        return InvestigationPlan(
            intent=intent,
            steps=steps,
            priority_reason="Ek kanit arama — mevcut sonuca guvenilirlik kat",
        )

    def _plan_follow_up_different(self, intent: Intent) -> InvestigationPlan:
        """'Baska kaynak' plani — farkli perspektif."""
        base = intent.referenced_claim or intent.original_query
        en_query = build_search_query(base)
        steps = [
            PlanStep(
                step_type=StepType.SEARCH_HEALTH_ORG,
                priority=StepPriority.HIGH,
                description="Farkli resmi kurumlardan bak (WHO, NICE, ESC)",
                search_query=en_query,
                limit=5,
            ),
            PlanStep(
                step_type=StepType.SEARCH_EXTERNAL,
                priority=StepPriority.HIGH,
                description="Farkli journal'lardan makaleler",
                search_query=en_query,
                source_filter=["nejm", "lancet", "jama", "bmj"],
                limit=5,
            ),
        ]

        return InvestigationPlan(
            intent=intent,
            steps=steps,
            priority_reason="Farkli perspektif — cesitli kaynaklardan dogrulama",
        )

    def _plan_challenge_verdict(self, intent: Intent) -> InvestigationPlan:
        """'Katilmiyorum' plani — celişkili kanitlari on planda ara."""
        base = intent.referenced_claim or intent.cleaned_query or intent.original_query
        en_query = build_search_query(base)
        challenge_query = en_query
        steps = [
            PlanStep(
                step_type=StepType.SEARCH_EXTERNAL,
                priority=StepPriority.HIGH,
                description="Celişkili kanitlari one cikararak ara",
                search_query=en_query,
                source_filter=["pubmed", "crossref", "europepmc", "openalex", "nejm", "jama", "lancet", "bmj"],
                limit=8,
            ),
            PlanStep(
                step_type=StepType.CHECK_CONTRADICTIONS,
                priority=StepPriority.HIGH,
                description="Celişkili kanitlari detayli analiz et",
                search_query=challenge_query,
                limit=5,
            ),
            PlanStep(
                step_type=StepType.SEARCH_HEALTH_ORG,
                priority=StepPriority.MEDIUM,
                description="Resmi kılavuzlarda farkli gorus kontrol et",
                search_query=challenge_query,
                limit=3,
            ),
        ]

        return InvestigationPlan(
            intent=intent,
            steps=steps,
            priority_reason="Itiraz durumu — celişkili kanitlar oncelikli",
        )

    def _plan_clarify_context(self, intent: Intent) -> InvestigationPlan:
        """'Aslinda su kastettim' plani — baglami netlestir."""
        steps = [
            PlanStep(
                step_type=StepType.ASK_CLARIFICATION,
                priority=StepPriority.HIGH,
                description="Kullaniciya netlestirme sorusu sor",
            ),
        ]

        return InvestigationPlan(
            intent=intent,
            steps=steps,
            priority_reason="Baglam netlestirme — kullanicidan ek bilgi gerekiyor",
        )

    def _plan_explore_topic(self, intent: Intent) -> InvestigationPlan:
        """'Bu konuda ne biliyorsun?' plani — genel arastirma."""
        steps = [
            PlanStep(
                step_type=StepType.SEARCH_ARCHIVE,
                priority=StepPriority.HIGH,
                description="Mevcut makalelerde konuyu ara",
                search_query=intent.cleaned_query,
                limit=5,
            ),
            PlanStep(
                step_type=StepType.SEARCH_EXTERNAL,
                priority=StepPriority.MEDIUM,
                description="Genel bakis icin derleme makaleleri ara",
                search_query=build_search_query(intent.cleaned_query),
                source_filter=["pubmed", "crossref"],
                limit=3,
            ),
        ]

        return InvestigationPlan(
            intent=intent,
            steps=steps,
            priority_reason="Konu kesfi — genel bakis ve mevcut icerik",
        )

    def _plan_meta_question(self, intent: Intent) -> InvestigationPlan:
        """Sistem hakkinda soru — arastirma gerekmez."""
        steps = [
            PlanStep(
                step_type=StepType.ASK_CLARIFICATION,
                priority=StepPriority.HIGH,
                description="Sistem hakkinda bilgi ver",
            ),
        ]

        return InvestigationPlan(
            intent=intent,
            steps=steps,
            priority_reason="Meta soru — arastirma gerekmez, aciklama yeterli",
        )

    def _plan_default(self, intent: Intent) -> InvestigationPlan:
        """Varsayilan plan — verify_claim gibi davransin."""
        return self._plan_verify_claim(intent)

    def refine_plan(
        self,
        plan: InvestigationPlan,
        investigation: Any,
        sufficiency: Any,
    ) -> InvestigationPlan:
        """Yetersiz kanit sonrasi plani gercekten degistirir (kor tekrar degil).

        Modern arastirma ajanlarinin (Claude/ChatGPT/Gemini deep research,
        OpenCode'un agentic dongusu) ortak deseni: "yetersiz" sinyali geldiginde
        ayni sorguyu ayni kaynaklara tekrar atmak degil, nerede az sonuc
        alindigini teshis edip o noktada kaynak havuzunu/limiti genisletmek,
        zaten yeterli veya deterministik/statik (ayni girdiyle ayni cikti
        dondurecek) adimlari tekrar calistirmamaktir.

        Somut kurallar:
        - SEARCH_ARCHIVE, LOOKUP_PREVIOUS, ASK_CLARIFICATION: statik/yerel,
          ayni sorguyla tekrar aramanin faydasi yok — retry'de atlanir.
        - Zaten yeterli sonuc getirmis adimlar (limitin yarisindan fazla):
          retry'de atlanir — gereksiz API cagrisi yapilmaz.
        - Az/hic sonuc getirmis SEARCH_EXTERNAL / SEARCH_HEALTH_ORG /
          CHECK_CONTRADICTIONS adimlari: kaynak havuzu kategorinin
          tamamina genisletilir, limit artirilir, oncelik HIGH'a cekilir.
        """
        # Donguesel import: investigator.py ust seviyede planner.py'den
        # PlanStep/InvestigationPlan import ediyor; bu yuzden ACADEMIC_SOURCES /
        # HEALTH_ORG_SOURCES buradan fonksiyon icinde (cagri anindan, her iki
        # modul de yuklendikten sonra) import edilir — dongusel import hatasi
        # olusturmaz.
        from .investigator import ACADEMIC_SOURCES, HEALTH_ORG_SOURCES

        counts_by_step_type: dict[str, int] = {}
        for sr in getattr(investigation, "step_results", []):
            counts_by_step_type[sr.step.step_type.value] = (
                counts_by_step_type.get(sr.step.step_type.value, 0) + sr.count
            )

        STATIC_STEP_TYPES = {StepType.SEARCH_ARCHIVE, StepType.LOOKUP_PREVIOUS, StepType.ASK_CLARIFICATION}
        WIDENABLE_STEP_TYPES = {StepType.SEARCH_EXTERNAL, StepType.SEARCH_HEALTH_ORG, StepType.CHECK_CONTRADICTIONS}

        new_steps: list[PlanStep] = []
        for step in plan.steps:
            if step.skip or step.step_type in STATIC_STEP_TYPES:
                new_steps.append(replace(step, skip=True))
                continue

            count = counts_by_step_type.get(step.step_type.value, 0)
            low_yield = count < max(2, step.limit // 2)

            if not low_yield:
                # Zaten yeterli getirdi — retry'de tekrar cagirma.
                new_steps.append(replace(step, skip=True))
                continue

            if step.step_type in WIDENABLE_STEP_TYPES:
                full_pool = HEALTH_ORG_SOURCES if step.step_type == StepType.SEARCH_HEALTH_ORG else ACADEMIC_SOURCES
                widened = sorted(set(full_pool) | set(step.source_filter or []))
                new_steps.append(replace(
                    step,
                    source_filter=widened,
                    limit=min(step.limit + 4, 10),
                    priority=StepPriority.HIGH,
                    description=f"{step.description} (genisletilmis kaynak havuzu, retry)",
                ))
            else:
                new_steps.append(step)

        refined = InvestigationPlan(
            intent=plan.intent,
            steps=new_steps,
            priority_reason=f"Retry — teshis: {sufficiency.suggested_action}",
        )
        refined.estimated_sources = sum(s.limit for s in refined.all_active_steps())
        return refined
