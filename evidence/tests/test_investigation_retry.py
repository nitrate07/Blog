"""Arastirma retry dongusu icin testler.

Onceki surumde `_investigate_with_loop`, yetersiz kanit durumunda ayni
plani ayni sorguyla tekrar calistiriyordu — bu neredeyse hicbir zaman
sufficiency'yi iyilestirmiyordu (deterministik/statik kaynaklar ayni
sonucu, ayni dar source_filter da genelde ayni sonucu dondurur).

Bu dosya, gercek duzeltmeyi test eder:
- `Planner.refine_plan`: dusuk verimli adimlarin kaynak havuzunu genisletir,
  zaten yeterli veya statik/yerel adimlari retry'de atlar.
- `ConversationManager._merge_investigations`: iki turun sonuclarini
  url'e gore tekillestirerek birlestirir (retry sonucu atilmaz).
"""

from __future__ import annotations

import pytest

from evidence.chat.intent import Intent, IntentType, Topic
from evidence.chat.investigator import (
    ACADEMIC_SOURCES,
    HEALTH_ORG_SOURCES,
    InvestigationResult,
    StepResult,
)
from evidence.chat.planner import (
    InvestigationPlan,
    Planner,
    PlanStep,
    StepPriority,
    StepType,
)


def _make_intent() -> Intent:
    return Intent(
        type=IntentType.VERIFY_CLAIM,
        confidence=0.9,
        topic=Topic.GENERAL,
        original_query="kahve kolesterolü yükseltir mi?",
        cleaned_query="kahve kolesterolü yükseltir mi?",
    )


def _make_step(step_type: StepType, *, limit: int = 5, source_filter=None) -> PlanStep:
    return PlanStep(
        step_type=step_type,
        priority=StepPriority.HIGH,
        description=f"test step {step_type.value}",
        search_query="coffee cholesterol",
        source_filter=source_filter,
        limit=limit,
    )


def _make_step_result(step: PlanStep, n_results: int) -> StepResult:
    results = [{"url": f"https://example.com/{step.step_type.value}/{i}", "title": f"r{i}"} for i in range(n_results)]
    return StepResult(step=step, success=True, results=results)


class TestRefinePlan:
    """Planner.refine_plan gercekten farkli bir plan uretmeli."""

    def test_low_yield_external_step_widens_source_pool(self):
        intent = _make_intent()
        step = _make_step(StepType.SEARCH_EXTERNAL, limit=5, source_filter=["pubmed"])
        plan = InvestigationPlan(intent=intent, steps=[step])

        investigation = InvestigationResult(plan=plan)
        investigation.step_results = [_make_step_result(step, n_results=1)]  # dusuk verim

        planner = Planner()
        sufficiency = type("S", (), {"suggested_action": "test"})()
        refined = planner.refine_plan(plan, investigation, sufficiency)

        active = refined.all_active_steps()
        assert len(active) == 1
        refined_step = active[0]
        assert refined_step.priority == StepPriority.HIGH
        assert set(refined_step.source_filter or []) >= set(ACADEMIC_SOURCES)
        assert refined_step.limit > step.limit

    def test_high_yield_step_is_skipped_on_retry(self):
        """Yeterli sonuc getirmis bir adim retry'de tekrar cagrilmamali."""
        intent = _make_intent()
        step = _make_step(StepType.SEARCH_HEALTH_ORG, limit=4)
        plan = InvestigationPlan(intent=intent, steps=[step])

        investigation = InvestigationResult(plan=plan)
        investigation.step_results = [_make_step_result(step, n_results=4)]  # yeterli

        planner = Planner()
        sufficiency = type("S", (), {"suggested_action": "test"})()
        refined = planner.refine_plan(plan, investigation, sufficiency)

        assert refined.all_active_steps() == []

    def test_archive_step_never_retried(self):
        """Yerel/statik arsiv aramasi ayni sorguyla ayni sonucu verir — retry'de atlanmali."""
        intent = _make_intent()
        step = _make_step(StepType.SEARCH_ARCHIVE, limit=5)
        plan = InvestigationPlan(intent=intent, steps=[step])

        investigation = InvestigationResult(plan=plan)
        investigation.step_results = [_make_step_result(step, n_results=0)]  # hic sonuc yok bile olsa

        planner = Planner()
        sufficiency = type("S", (), {"suggested_action": "test"})()
        refined = planner.refine_plan(plan, investigation, sufficiency)

        assert refined.all_active_steps() == []

    def test_health_org_widens_to_health_org_pool_not_academic(self):
        intent = _make_intent()
        step = _make_step(StepType.SEARCH_HEALTH_ORG, limit=3, source_filter=["who"])
        plan = InvestigationPlan(intent=intent, steps=[step])

        investigation = InvestigationResult(plan=plan)
        investigation.step_results = [_make_step_result(step, n_results=0)]

        planner = Planner()
        sufficiency = type("S", (), {"suggested_action": "test"})()
        refined = planner.refine_plan(plan, investigation, sufficiency)

        active = refined.all_active_steps()
        assert len(active) == 1
        widened_sources = set(active[0].source_filter or [])
        assert widened_sources >= set(HEALTH_ORG_SOURCES)
        assert not (widened_sources - set(HEALTH_ORG_SOURCES) - {"who"})


class TestMergeInvestigations:
    """ConversationManager._merge_investigations retry sonuclarini kaybetmemeli."""

    def test_merge_deduplicates_by_url_and_unions_results(self):
        from evidence.chat.conversation import ConversationManager

        intent = _make_intent()
        plan = InvestigationPlan(intent=intent, steps=[])

        base = InvestigationResult(plan=plan)
        base.external_results = [{"url": "https://a.com/1", "title": "A"}]
        base.all_results = list(base.external_results)
        base.total_sources = 1

        extra = InvestigationResult(plan=plan)
        extra.external_results = [
            {"url": "https://a.com/1", "title": "A (duplicate)"},  # ayni url — tekillesmeli
            {"url": "https://b.com/2", "title": "B"},  # yeni
        ]
        extra.all_results = list(extra.external_results)

        merged = ConversationManager._merge_investigations(base, extra)

        urls = {r["url"] for r in merged.external_results}
        assert urls == {"https://a.com/1", "https://b.com/2"}
        assert merged.total_sources == 2

    def test_merge_preserves_first_turn_title_on_duplicate(self):
        """Ayni url tekrar geldiginde ilk turdaki kayit korunmali (retry onu ezmez)."""
        from evidence.chat.conversation import ConversationManager

        intent = _make_intent()
        plan = InvestigationPlan(intent=intent, steps=[])

        base = InvestigationResult(plan=plan)
        base.external_results = [{"url": "https://a.com/1", "title": "Original"}]
        base.all_results = list(base.external_results)

        extra = InvestigationResult(plan=plan)
        extra.external_results = [{"url": "https://a.com/1", "title": "Retry version"}]
        extra.all_results = list(extra.external_results)

        merged = ConversationManager._merge_investigations(base, extra)

        assert len(merged.external_results) == 1
        assert merged.external_results[0]["title"] == "Original"
