"""Conversational Investigator — AgentProvenance dashboard icin interaktif kanit arastirma katmani.

Bu modul genel amacli bir chatbot degildir. Dashboard kullanicisinin gercek niyetini anlayarak,
onceki konusma baglamini takip ederek, follow-up sorularini cozebilecek sekilde tasarlanmistir.

Akis:
1. User → Conversation Context
2. Intent / Question Understanding
3. Investigation Planner
4. AI Tools + Graph + Timeline + Evidence
5. Sufficiency Check
6. Need more evidence? → YES → Research again → NO → Continue
7. Answer Planner
8. Natural Conversational Response
9. → User
"""

from .answer import AnswerPlanner, AnswerPlan, AnswerFormat
from .conversation import ConversationManager, ConversationState
from .intent import Intent, IntentAnalyzer, IntentType, Topic
from .investigator import EvidenceInvestigator, Timeline, TimelineEntry
from .planner import InvestigationPlan, PlanStep, Planner
from .response import ResponseBuilder
from .sufficiency import SufficiencyChecker, SufficiencyMetrics, SufficiencyResult

__all__ = [
    "AnswerPlanner",
    "AnswerPlan",
    "AnswerFormat",
    "ConversationManager",
    "ConversationState",
    "Intent",
    "IntentAnalyzer",
    "IntentType",
    "Topic",
    "InvestigationPlan",
    "PlanStep",
    "Planner",
    "EvidenceInvestigator",
    "Timeline",
    "TimelineEntry",
    "SufficiencyChecker",
    "SufficiencyMetrics",
    "SufficiencyResult",
    "ResponseBuilder",
]
