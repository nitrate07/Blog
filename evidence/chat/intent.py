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
    GREETING = "greeting"                   # "Selam", "Merhaba"
    SMALLTALK = "smalltalk"                 # "Nasilsin?", "Iyi misin?"
    IDENTITY = "identity"                   # "Kimsin?", "Sen nesin?"
    THANKS = "thanks"                       # "Tessekurler", "Sagol"
    FAREWELL = "farewell"                   # "Gorusuruz", "Hoscakal"


# Sosyal niyetler — arastirma akisina girmez, dogrudan yanitlanir.
SOCIAL_INTENTS: frozenset[IntentType] = frozenset({
    IntentType.GREETING,
    IntentType.SMALLTALK,
    IntentType.IDENTITY,
    IntentType.THANKS,
    IntentType.FAREWELL,
})

# Sosyal selamlasma pattern'leri. Siralama onemli: ilk eslesen kazanir.
# Bu kontroller follow-up tespitinden ONCE yapilir; aksi halde "nasilsin"
# gibi kisa mesajlar follow-up sanilip bozuk cevaplar uretilir.
SOCIAL_PATTERNS: list[tuple[IntentType, list[str]]] = [
    (IntentType.GREETING, [
        r"^selam([uü]n\s?aleyk[uü]m)?$",
        r"^merhaba(lar)?$",
        r"^s[aə]lam$",
        r"^(g[uü]nayd[iı]n|i[yi]i\s+ak[sş]amlar|i[yi]i\s+geceler|i[yi]i\s+g[uü]nler|h[oö][sş]\s+geldin)$",
        r"^(naber|ne\s+haber|nas[iı]lsin)$",
        r"^(hello|hi|hey|yo|good\s+(morning|afternoon|evening)|howdy)\b",
        r"^selam\s+(arkada[sş]lar|hocam|abi|usta)$",
    ]),
    (IntentType.SMALLTALK, [
        r"nas[iı]l(s?[iı]n|\s+gidiyor|\s+y[sş]in)",
        r"^(iyi\s+m[iü]y[iü]m?|sen\s+i[yi]si\s+n)$",
        r"^keyifler\s+nas[iı]l",
        r"^(how\s+are\s+you|what'?s\s+up|wassup|how'?s\s+it\s+going)",
        r"^[eə]h?e+h[eə]?$",           # "ehuehe", "hehe"
        r"^h[m]+$",                     # "hm", "hmm"
        r"^(ok|tamam|anlad[iı]m|peki|peki|tamm)$",
    ]),
    (IntentType.IDENTITY, [
        r"(sen\s+)?kim(sin|dir|se)?\s*$",
        r"^(ad[iı]n\s+ne|ismin\s+ne|sen\s+nesin|ne\s+sin)\b",
        r"^(who|what)\s+are\s+you\b",
        r"^are\s+you\s+(a\s+|an\s+)?(real\s+)?(doctor|bot|robot|ai|human|person|alive)\b",
        r"bot\s+mu(sun)?\b",
        r"insan\s+m[iı]s[iı]n\b",
        r"ger[cç]ek\s+mi(sin)?\b",
        r"^kendini\s+tan[iı]t",
        r"yard[iı]m\s+ed(er|ebilir)\s+misin",
        r"^(can\s+you\s+help|help\s+me)\b",
    ]),
    (IntentType.THANKS, [
        r"te[sş]ekk[uü]r",
        r"^(sa[gğ]ol|sa[gğ]olas[iı]n|eyvallah|sa[gğ]olun)$",
        r"^(thanks|thank\s+you|thx|ty)\b",
        r"^eline\s+sa[gğ]l[iı]k",
        r"^harika(s[iı]n)?\s*(oldu)?\s*$",
        r"^(s[uü]per|m[uü]kemmel|g[uü]zel)\s*oldu\s*$",
    ]),
    (IntentType.FAREWELL, [
        r"(h[oö][sş][cç]a\s+kal|g[oö]r[uü][sş][uü]r[uü]z|kendine\s+i[yi]i\s+bak)",
        r"^(bye|goodbye|see\s+you|later|cya)\b",
        r"^(i[yi]i\s+g[uü]nler|i[yi]i\s+ak[sş]amlar)\s*$",
        r"^kapat$",
    ]),
]

# Sosyal sayilmayacak durumlar: icinde gercek soru/iddia tasiyan karisik mesajlar
# ("selam, kahve kolesterolu yukseltir mi?") normal akisa girmeli — bu, kelime
# sayisi sinirindan BAGIMSIZ olarak asagidaki _detect_social()'daki konu-veto
# kontroluyle (Topic.GENERAL disinda bir konu varsa sosyal sayilmaz) saglanir.
# Sinir, "cok tesekkur ederim, cok yardimci oldun" gibi hala safca sosyal olan
# ama birden fazla nazik ifade iceren, biraz daha uzun mesajlari da kapsayacak
# sekilde genis tutulur.
_SOCIAL_MAX_WORDS = 8


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
        # NOT (2026-08-29): "neden?" tek basina (baglam olmadan en dogal
        # soru bicimi) eskiden HICBIR pattern'e uymuyordu — hepsi "neden
        # boyle/ozle" gibi daha uzun bir devam gerektiriyordu. Canli test
        # bunu dogruladi: bir hukum sonrasi "neden?" yazmak follow_up_why
        # yerine verify_claim'e dusuyor, has_health_topic bosluguna
        # takilip alakasiz bir "ben nasil calisiyorum" metni donduruyordu.
        # ^...$ ile CAPA'lanmis: yalnizca mesajin TAMAMI bu kisa soru
        # kelimesiyse eslesir — "neden bu ilac zararli" gibi yeni, uzun bir
        # iddiayi YANLISLIKLA yakalamaz.
        r"^neden\s*\??$",
        r"^niye\s*\??$",
        r"^why\s*\??$",
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
        r"kat[ıi]lm[ıi]yorum",
        r"disagree",
        r"yanl[ıi][şs]",
        r"wrong",
        r"hatal[ıi]",
        r"itiraz",
        r"objection",
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
        r"nas[ıi]l\s+çal[ıi][şs][ıi]yorsun",
        r"nas[ıi]l\s+calisiyorsun",
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


def is_interrogative(query: str) -> bool:
    """Soru cumlesi mi? — TR soru eki (mi/mi/mu/mu) veya EN yardimci fiili.

    Modul-seviyesinde bagimsiz fonksiyon (IntentAnalyzer disindan da
    kullanilabilir — bkz. conversation.py'deki has_health_topic kapisi).
    """
    q = query.lower().strip()
    if q.endswith("?"):
        return True
    # TR soru eki: ayri yazilan "mi/mi/mu/mu/mI" + ekleri
    if re.search(r"\b(m[iıì]|m[uü])[nmuü]?\b", q):
        return True
    # EN soru yapisi
    if re.search(r"^(is|are|does|do|did|can|should|will|would|could)\b", q):
        return True
    return False


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

        # 0. Sosyal niyet tespiti (selamlasma, tesekkur, kimlik...)
        #    Follow-up'tan ONCE kontrol edilir; "nasilsin" gibi mesajlar
        #    follow-up sanilip bozuk cevap uretmemesi icin.
        social = self._detect_social(query)
        if social is not None:
            signals.append(f"social:{social.value}")
            return Intent(
                type=social,
                confidence=0.95,
                topic=Topic.GENERAL,
                original_query=query,
                cleaned_query=cleaned,
                raw_signals=signals,
            )

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

    def _is_interrogative(self, query: str) -> bool:
        """Soru cumlesi mi? — TR soru eki (mi/mi/mu/mu) veya EN yardimci fiili.

        Soru cumleleri yeni iddiadir; ayni topic olsa bile follow-up degil.
        Bkz. modul-seviyesindeki is_interrogative() — bu, ona ince bir
        sarmalayici.
        """
        return is_interrogative(query)

    def _detect_social(self, query: str) -> IntentType | None:
        """Kisa, saf sosyal mesajlari tespit et.

        Karisik mesajlar ("selam, kahve kolesterolu yukseltir mi?") sosyal
        sayilmaz — icinde soru/iddia tasidigi icin normal akisa girer.
        """
        q = query.strip().rstrip("?!.,;:").lower()
        if not q or len(q.split()) > _SOCIAL_MAX_WORDS:
            return None
        # Icinde saglik konusu gecen mesaj asla sosyal degil
        if self._detect_topic(q) != Topic.GENERAL:
            return None

        for intent_type, patterns in SOCIAL_PATTERNS:
            for pattern in patterns:
                if re.search(pattern, q):
                    return intent_type
        return None

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
            # Kisa/sohbet disi mesajlar ("merhaba", "ok") follow-up sanilmaz;
            # en az 3 kelime ve somut bir topic gerekir.
            # Ayrica soru cumlesiysen ("...yukseltir mi?") bu YENI iddiadir —
            # ayni konu olsa bile follow-up degil.
            if last_claim and len(query.split()) >= 3:
                is_question = self._is_interrogative(query)
                topic_match = self._detect_topic(query) == self._detect_topic(last_claim)
                if topic_match and self._detect_topic(query) != Topic.GENERAL and not is_question:
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
