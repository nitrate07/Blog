"""Iddia-bolme (claim decomposition) testleri (2026-08-29).

assafelovic/gpt-researcher'in (GitHub'da en populer acik kaynak "deep
research" ajani, 28k+ yildiz) planner->execution->publisher mimarisinden
ilham alinarak eklendi: LLM mevcutsa, bir iddia 2-4 farkli arastirma
acisina bolunup PARALEL arastirilir; yoksa mevcut tek-sorgulu davranis
degismeden kalir (fail-closed).
"""

from __future__ import annotations

import pytest

from evidence.chat.intent import Intent, IntentType, Topic
from evidence.chat.planner import Planner, StepType, _decompose_claim


class ToolCapableProvider:
    """test_editor.py'deki ayni desen — tool-calling destekleyen sahte saglayici."""

    supports_tools = True

    def __init__(self, tool_result: dict | None = None, raises: bool = False):
        self.tool_result = tool_result
        self.raises = raises
        self.last_prompt: str | None = None

    async def generate_with_tool(self, prompt: str, tool: dict) -> dict | None:
        self.last_prompt = prompt
        if self.raises:
            raise RuntimeError("provider unavailable")
        return self.tool_result


class PlainProvider:
    """supports_tools olmayan/False olan bir saglayici — tool yoluna hic girmemeli."""

    supports_tools = False

    async def generate(self, prompt: str) -> str:
        return "text"


def _make_intent(query: str = "kahve kolesterolü yükseltir mi?") -> Intent:
    return Intent(
        type=IntentType.VERIFY_CLAIM,
        confidence=0.9,
        topic=Topic.GENERAL,
        original_query=query,
        cleaned_query=query,
    )


class TestDecomposeClaim:
    @pytest.mark.asyncio
    async def test_no_provider_returns_empty(self):
        result = await _decompose_claim("claim", "coffee cholesterol", provider=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_provider_without_tool_support_returns_empty(self):
        result = await _decompose_claim("claim", "coffee cholesterol", provider=PlainProvider())
        assert result == []

    @pytest.mark.asyncio
    async def test_valid_subquestions_returned(self):
        provider = ToolCapableProvider(tool_result={
            "subquestions": [
                "coffee cafestol LDL mechanism",
                "filtered vs unfiltered coffee cholesterol",
                "coffee consumption cardiovascular meta-analysis",
            ],
        })
        result = await _decompose_claim("kahve kolesterolü yükseltir mi?", "coffee cholesterol", provider)
        assert result == [
            "coffee cafestol LDL mechanism",
            "filtered vs unfiltered coffee cholesterol",
            "coffee consumption cardiovascular meta-analysis",
        ]

    @pytest.mark.asyncio
    async def test_single_subquestion_treated_as_failure(self):
        """1 alt-soru gercek bir 'bolme' degildir — bos liste donmeli
        (augment_with_subquestions bunu 'plan degismesin' sinyali sayar)."""
        provider = ToolCapableProvider(tool_result={"subquestions": ["only one"]})
        result = await _decompose_claim("claim", "en query", provider)
        assert result == []

    @pytest.mark.asyncio
    async def test_provider_exception_returns_empty(self):
        provider = ToolCapableProvider(raises=True)
        result = await _decompose_claim("claim", "en query", provider)
        assert result == []

    @pytest.mark.asyncio
    async def test_none_result_returns_empty(self):
        provider = ToolCapableProvider(tool_result=None)
        result = await _decompose_claim("claim", "en query", provider)
        assert result == []

    @pytest.mark.asyncio
    async def test_malformed_result_shape_returns_empty(self):
        provider = ToolCapableProvider(tool_result={"subquestions": "not a list"})
        result = await _decompose_claim("claim", "en query", provider)
        assert result == []

    @pytest.mark.asyncio
    async def test_more_than_four_subquestions_capped_at_four(self):
        provider = ToolCapableProvider(tool_result={
            "subquestions": [f"query {i}" for i in range(7)],
        })
        result = await _decompose_claim("claim", "en query", provider)
        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_blank_strings_filtered_out(self):
        provider = ToolCapableProvider(tool_result={
            "subquestions": ["real query one", "  ", "", "real query two"],
        })
        result = await _decompose_claim("claim", "en query", provider)
        assert result == ["real query one", "real query two"]


class TestAugmentWithSubquestions:
    @pytest.mark.asyncio
    async def test_no_provider_leaves_plan_unchanged(self):
        planner = Planner()
        intent = _make_intent()
        plan = planner.create_plan(intent)
        original_step_count = len(plan.steps)

        augmented = await planner.augment_with_subquestions(
            plan, intent.cleaned_query, "coffee cholesterol", provider=None,
        )
        assert len(augmented.steps) == original_step_count

    @pytest.mark.asyncio
    async def test_valid_decomposition_adds_parallel_search_steps(self):
        planner = Planner()
        intent = _make_intent()
        plan = planner.create_plan(intent)
        original_step_count = len(plan.steps)

        provider = ToolCapableProvider(tool_result={
            "subquestions": ["coffee cafestol mechanism", "unfiltered coffee LDL trial"],
        })
        augmented = await planner.augment_with_subquestions(
            plan, intent.cleaned_query, "coffee cholesterol", provider,
        )

        assert len(augmented.steps) == original_step_count + 2
        new_steps = augmented.steps[original_step_count:]
        assert all(s.step_type == StepType.SEARCH_EXTERNAL for s in new_steps)
        assert {s.search_query for s in new_steps} == {
            "coffee cafestol mechanism", "unfiltered coffee LDL trial",
        }

    @pytest.mark.asyncio
    async def test_failed_decomposition_leaves_plan_unchanged(self):
        planner = Planner()
        intent = _make_intent()
        plan = planner.create_plan(intent)
        original_step_count = len(plan.steps)

        provider = ToolCapableProvider(raises=True)
        augmented = await planner.augment_with_subquestions(
            plan, intent.cleaned_query, "coffee cholesterol", provider,
        )
        assert len(augmented.steps) == original_step_count

    @pytest.mark.asyncio
    async def test_estimated_sources_increases_with_augmentation(self):
        planner = Planner()
        intent = _make_intent()
        plan = planner.create_plan(intent)
        original_estimate = plan.estimated_sources

        provider = ToolCapableProvider(tool_result={
            "subquestions": ["angle one query", "angle two query"],
        })
        augmented = await planner.augment_with_subquestions(
            plan, intent.cleaned_query, "coffee cholesterol", provider,
        )
        assert augmented.estimated_sources > original_estimate


class TestCategorizeResultsDeduplication:
    """_categorize_results — coklu alt-soru arastirmasi ayni makaleyi farkli
    sorgularla birden fazla kez bulabilir; URL bazinda tekillestirme olmadan
    bu, "X kaynak incelendi" sayisini sisirir. Bu davranisi kilitler."""

    def test_duplicate_url_across_steps_counted_once(self):
        from evidence.chat.investigator import EvidenceInvestigator, InvestigationResult, StepResult
        from evidence.chat.planner import InvestigationPlan, PlanStep, StepPriority, StepType

        intent = _make_intent()
        step1 = PlanStep(step_type=StepType.SEARCH_EXTERNAL, priority=StepPriority.HIGH, description="d1", search_query="q1")
        step2 = PlanStep(step_type=StepType.SEARCH_EXTERNAL, priority=StepPriority.HIGH, description="d2", search_query="q2")
        plan = InvestigationPlan(intent=intent, steps=[step1, step2])

        result = InvestigationResult(plan=plan)
        result.step_results = [
            StepResult(step=step1, success=True, results=[
                {"source": "pubmed", "url": "https://pubmed.ncbi.nlm.nih.gov/111/", "title": "Study A"},
            ]),
            StepResult(step=step2, success=True, results=[
                {"source": "pubmed", "url": "https://pubmed.ncbi.nlm.nih.gov/111/", "title": "Study A (found again via different query)"},
                {"source": "pubmed", "url": "https://pubmed.ncbi.nlm.nih.gov/222/", "title": "Study B"},
            ]),
        ]

        investigator = EvidenceInvestigator()
        investigator._categorize_results(result)

        assert result.total_sources == 2  # 3 sonuc geldi ama 1 tanesi duplicate
        urls = {r["url"] for r in result.external_results}
        assert urls == {
            "https://pubmed.ncbi.nlm.nih.gov/111/",
            "https://pubmed.ncbi.nlm.nih.gov/222/",
        }

    def test_results_without_url_never_deduplicated_against_each_other(self):
        """URL'si olmayan sonuclar (ör. bazi contradiction/passage kayitlari)
        birbirine karsi yanlislikla tekillestirlmemeli."""
        from evidence.chat.investigator import EvidenceInvestigator, InvestigationResult, StepResult
        from evidence.chat.planner import InvestigationPlan, PlanStep, StepPriority, StepType

        intent = _make_intent()
        step1 = PlanStep(step_type=StepType.SEARCH_EXTERNAL, priority=StepPriority.HIGH, description="d1", search_query="q1")
        plan = InvestigationPlan(intent=intent, steps=[step1])

        result = InvestigationResult(plan=plan)
        result.step_results = [
            StepResult(step=step1, success=True, results=[
                {"source": "pubmed", "title": "No URL A"},
                {"source": "pubmed", "title": "No URL B"},
            ]),
        ]

        investigator = EvidenceInvestigator()
        investigator._categorize_results(result)

        assert result.total_sources == 2


class TestSourceQualityCompleteness:
    """Regresyon (2026-08-29): "google_scholar" _SOURCE_QUALITY haritasinda
    hic yoktu, sessizce .get(source, 0.7) varsayilanina dusuyordu. Bu test,
    her kayitli kaynak ajaninin acik bir kalite skoruna sahip oldugunu
    kilitler — gelecekte yeni bir ajan eklenip harita guncellenmezse bu
    test kirilir (sessiz varsayilana dusme yerine)."""

    def test_all_registered_source_agents_have_explicit_quality_score(self):
        import importlib
        import inspect
        import pkgutil

        from evidence.chat.conversation import _SOURCE_QUALITY
        import evidence.v2.sources as sources_pkg

        agent_names: set[str] = set()
        for _, modname, _ in pkgutil.iter_modules(sources_pkg.__path__):
            module = importlib.import_module(f"evidence.v2.sources.{modname}")
            for attr in vars(module).values():
                if not inspect.isclass(attr):
                    continue
                name = attr.__dict__.get("name")  # yalnizca SINIFIN KENDI tanimladigi, mirasla gelmeyen
                # "journal" (CrossrefJournalAgent taban sinifi) her zaman
                # alt siniflar tarafindan override edilir, canli bir kaynak
                # adi olarak asla yuzeye cikmaz — kasitli olarak haric.
                if isinstance(name, str) and name and name != "journal":
                    agent_names.add(name)

        missing = agent_names - set(_SOURCE_QUALITY.keys())
        assert missing == set(), f"_SOURCE_QUALITY'de kalite skoru olmayan kaynaklar: {missing}"

    def test_google_scholar_has_explicit_conservative_score(self):
        from evidence.chat.conversation import _SOURCE_QUALITY
        assert "google_scholar" in _SOURCE_QUALITY
        assert _SOURCE_QUALITY["google_scholar"] < _SOURCE_QUALITY["pubmed"]
