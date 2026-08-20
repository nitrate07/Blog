"""Kullanici niyet analizi — soruyu anlayip dogru arama stratejisi belirler.

Dashboard context'inde kullanici genellikle:
- Bir iddiayi dogrulamak ister
- Onceki dogrulamanin neden oyle oldugunu sorar
- Daha fazla kanit ister
- Farkli bir kaynaktan bakmani ister
- Sonuca itiraz eder
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class IntentType(str, Enum):
    """Kullanici niyet turleri."""
    VERIFY_CLAIM = "verify_claim"           # Yeni bir iddiayi dogrula
    FOLLOW_UP_WHY = "follow_up_why"        # "Neden oyle?" - onceki sonucun nedeni
    FOLLOW_UP_MORE = "follow_up_more"      # "Daha fazla kanit" - ek kaynak ara
    FOLLOW_UP_DIFFERENT = "follow_up_different"  # "Baska kaynak" - farkli perspektif
    CHALLENGE_VERDICT = "challenge_verdict"  # "Katilmiyorum" - sonuca itiraz
    CLARIFY_CONTEXT = "clarify_context"    # "Aslinda su kastettim" - baglami netlestir
    EXPLORE_TOPIC = "explore_topic"         # "Bu konuda ne biliyorsun?" - genel arastirma
    META_QUESTION = "meta_question"         # "Nasal calisiyorsun?" - sistem hakkinda


class Topic(str, Enum):
    """Saglik konu kategorileri."""
    GLP1 = "glp1"
    EXERCISE = "exercise"
    CARDIOVASCULAR = "cardiovascular"
    CANCER = "cancer"
    DIABETES = "diabetes"
    VITAMIN_D = "vitamin_d"
    OMEGA3 = "omega3"
    PROBIOTIC = "probiotic"
    VACCINE = "vaccine"
    NUTRITION = "nutrition"
    SLEEP = "sleep"
    MENTAL_HEALTH = "mental_health"
    DRUGS = "drugs"
    AGING = "aging"
    GENERAL = "general"


# Topic keyword mapping
TOPIC_KEYWORDS: dict[Topic, list[str]] = {
    Topic.GLP1: ["glp-1", "glp1", "semaglutide", "liraglutide", "ozempic", "wegovy", "rybelsus"],
    Topic.EXERCISE: ["egzersiz", "exercise", "physical activity", "fiziksel aktivite", "spor", "workout"],
    Topic.CARDIOVASCULAR: ["kalp", "heart", "cardiovascular", "kardiyovasküler", "cardiac", "hipertansiyon", "hypertension", "kolesterol", "cholesterol"],
    Topic.CANCER: ["kanser", "cancer", "tumor", "tümör", "onkoloji", "oncology"],
    Topic.DIABETES: ["diyabet", "diabetes", "insulin", "insülin", "tip 2", "type 2"],
    Topic.VITAMIN_D: ["vitamin d", "vitamin d3", "d vitamini", "vitamin d deficiency"],
    Topic.OMEGA3: ["omega-3", "omega 3", "fish oil", "balık yağı", "epa", "dha"],
    Topic.PROBIOTIC: ["probiyotik", "probiotic", "microbiome", "mikrobiyom", "bağırsak", "gut"],
    Topic.VACCINE: ["aşı", "vaccine", "vaccination", "aşılama", "immunization"],
    Topic.NUTRITION: ["beslenme", "nutrition", "diet", "diyet", "food", "gıda", "protein", "vitamin"],
    Topic.SLEEP: ["sleep", "uyku", "insomnia", "uykusuzluk", "melatonin"],
    Topic.MENTAL_HEALTH: ["depression", "depresyon", "anxiety", "anksiyete", "stres", "stress", "mental health"],
    Topic.DRUGS: ["drug", "medication", "ilaç", "pharmaceutical", "aspirin", "ibuprofen", "metformin", "antibiyotik", "antibiotic"],
    Topic.AGING: ["aging", "yaşlanma", "longevity", "anti-aging", "youth", "gençlik"],
}


# Follow-up signal patterns
FOLLOW_UP_PATTERNS: dict[IntentType, list[str]] = {
    IntentType.FOLLOW_UP_WHY: [
        r"neden\s+(boyle|öyle|böyle)",
        r"niye\s+(boyle|öyle|böyle)",
        r"why\s+(is|was|did|does)",
        r"neden\s+(öyle|boyle\s+sonucland)",
        r"acikla\s+",
        r"explain\s+",
    ],
    IntentType.FOLLOW_UP_MORE: [
        r"daha\s+fazla",
        r"more\s+(evidence|source|kanit|kaynak)",
        r"baska\s+(kaynak|kaynaklar)",
        r"additional\s+(source|evidence)",
        r"ek\s+",
    ],
    IntentType.FOLLOW_UP_DIFFERENT: [
        r"farkli\s+(kaynak|perspektif|yaklasim)",
        r"different\s+(source|perspective|approach)",
        r"bastan\s+bak",
        r"look\s+(again|at\s+other)",
        r"check\s+other",
    ],
    IntentType.CHALLENGE_VERDICT: [
        r"katilmiyorum",
        r"disagree",
        r"yanlis",
        r"wrong",
        r"hatali",
        r"itiraz",
        r"objection",
        r"ama\s+",
        r"but\s+",
    ],
    IntentType.CLARIFY_CONTEXT: [
        r"aslinda",
        r"actually",
        r"kastim",
        r"i\s+mean",
        r"benim\s+icin",
        r"for\s+my\s+case",
    ],
    IntentType.EXPLORE_TOPIC: [
        r"ne\s+biliyorsun",
        r"what\s+do\s+you\s+know",
        r"anlat\s+",
        r"tell\s+me\s+about",
        r"hakkinda\s+bilgi",
    ],
    IntentType.META_QUESTION: [
        r"nasil\s+calisiyorsun",
        r"how\s+do\s+you\s+work",
        r"hangi\s+kaynak",
        r"which\s+source",
        r"sistemi\s+",
    ],
}


@dataclass
class Intent:
    """Tanaltilmis kullanici niyeti."""
    type: IntentType
    confidence: float  # 0.0 - 1.0
    topic: Topic
    original_query: str
    cleaned_query: str  # Prefix'lerden arindirilmis
    referenced_claim: str | None = None  # Follow-up ise onceki iddia
    context_clarification: str | None = None  # Baglam netlestirme
    raw_signals: list[str] = field(default_factory=list)


class IntentAnalyzer:
    """Kullanici niyetini analiz eden motor.

    Dashboard context'inde kullanici tipik olarak:
    1. Bir saglik iddiasi sorar → verify_claim
    2. Sonucu gorunce "neden?" der → follow_up_why
    3. "Daha fazla kanit" der → follow_up_more
    4. "Katilmiyorum" der → challenge_verdict
    """

    def analyze(
        self,
        query: str,
        conversation_history: list[dict[str, str]] | None = None,
        last_claim: str | None = None,
        last_verdict: str | None = None,
    ) -> Intent:
        """Kullanici sorusunu analiz et.

        Args:
            query: Kullanici sorusu
            conversation_history: Onceki konusma [role, content]
            last_claim: Onceki dogrulanan iddia
            last_verdict: Onceki sonuc
        """
        cleaned = self._clean_query(query)
        signals: list[str] = []

        # 1. Follow-up tespiti
        intent_type, followup_confidence = self._detect_followup(
            query, conversation_history, last_claim, last_verdict, signals,
        )

        # 2. Topic tespiti
        topic = self._detect_topic(query)

        # 3. Yeni iddia tespiti
        if intent_type == IntentType.VERIFY_CLAIM:
            cleaned = self._extract_claim(cleaned)
            followup_confidence = 0.9

        return Intent(
            type=intent_type,
            confidence=followup_confidence,
            topic=topic,
            original_query=query,
            cleaned_query=cleaned,
            referenced_claim=last_claim if intent_type != IntentType.VERIFY_CLAIM else None,
            raw_signals=signals,
        )

    def _clean_query(self, query: str) -> str:
        """Query'den gereksiz prefix ve suffix'leri temizle."""
        q = query.strip()

        prefixes = [
            "is it true that", "does ", "can ", "should ", "is ",
            "are ", "what about ", "tell me about ", "explain ",
            "verify ", "check ", "fact check ", "did ",
            "bana söyle ", "anlat ", "doğrula ", "kontrol et ",
            "hakkında bilgi ver ", "nedir ", "nasıl ",
        ]
        for prefix in prefixes:
            if q.lower().startswith(prefix):
                q = q[len(prefix):].strip()
                break

        return q.rstrip("?!.")

    def _extract_claim(self, query: str) -> str:
        """Query'den iddiayi cikar."""
        claim = query.rstrip("?!")
        if not claim.endswith("?"):
            claim = claim + "?"
        return claim

    def _detect_followup(
        self,
        query: str,
        history: list[dict[str, str]] | None,
        last_claim: str | None,
        last_verdict: str | None,
        signals: list[str],
    ) -> tuple[IntentType, float]:
        """Follow-up niyetini tespit et."""
        query_lower = query.lower()

        #Once pattern matching dene
        for intent_type, patterns in FOLLOW_UP_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    signals.append(f"pattern:{pattern}")
                    # History varsa guveni artir
                    confidence = 0.85 if history and len(history) > 2 else 0.7
                    return intent_type, confidence

        # History'de onceki sorgu varsa baglami kontrol et
        if history and len(history) >= 2:
            last_user_msg = ""
            for msg in reversed(history):
                if msg.get("role") == "user":
                    last_user_msg = msg.get("content", "").lower()
                    break

            # Onceki soruyla ayni topic mi?
            if last_claim:
                topic_match = self._detect_topic(query) == self._detect_topic(last_claim)
                if topic_match and len(query.split()) <= 5:
                    signals.append("topic_continuation")
                    return IntentType.FOLLOW_UP_WHY, 0.6

        # Hiçbir pattern eslesmediyse yeni iddia varsay
        return IntentType.VERIFY_CLAIM, 0.9

    def _detect_topic(self, text: str) -> Topic:
        """Text'ten saglik konusunu tespit et."""
        text_lower = text.lower()
        scores: dict[Topic, int] = {}

        for topic, keywords in TOPIC_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[topic] = score

        if scores:
            return max(scores, key=scores.get)

        return Topic.GENERAL
