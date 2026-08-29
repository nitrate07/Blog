"""Canli uctan-uca prob ile bulunan iki gercek dogruluk hatasi icin testler
(2026-08-29 oturumu).

Bulgular:
1. `_derive_verdict`'te arsiv sonuclarinin relevance'i `max(0.3, ...)` ile
   tabanliydi — TF-IDF benzerlik skoru ne kadar dusuk olursa olsun (tamamen
   alakasiz bir eslesme bile) kullaniciya gosterilen guven yuzdesi HER ZAMAN
   sabit %30 goruntuleniyordu, eslesme kalitesinden bagimsiz olarak.
2. `_execute_search_archive` disaridaki/saglik-kurumu aramalarinin aksine
   `prune_irrelevant` suzgecinden gecmiyordu — tutarsizlik.
3. Dusuk-guvenli bir hukum (best_archive=None ama yine de bir verdict
   uretildi) kullaniciya hicbir uyari olmadan kendinden emin bir ifadeyle
   ("Buyuk Olcude Destekleniyor") sunuluyordu.

Gercek arsiv verisiyle dogrulandi: "Vitamin D eksikligi kemik sagligini
etkiler mi?" sorgusu arsivde hicbir dogrudan kaynak olmamasina ragmen
"vitamin" kelimesini paylasan alakasiz makaleleri (vaping/vitamin E,
kaya tuzu) kaynak gosterip yine de yuksek-guvenli bir hukum veriyordu.
"""

from __future__ import annotations

import pytest

from evidence.chat.conversation import ConversationManager
from evidence.chat.intent import Intent, IntentType, Topic
from evidence.chat.investigator import InvestigationPlan, InvestigationResult, prune_irrelevant
from evidence.chat.response import ResponseBuilder


def _make_intent(query: str = "test claim") -> Intent:
    return Intent(
        type=IntentType.VERIFY_CLAIM,
        confidence=0.9,
        topic=Topic.GENERAL,
        original_query=query,
        cleaned_query=query,
    )


def _archive_result(title: str, passage: str, rating: int, distance: float, url: str = "https://example.com/x") -> dict:
    return {
        "source": "archive",
        "title": title,
        "url": url,
        "passage": passage,
        "verdict": {5: "supported", 4: "mostly_supported", 3: "partly_supported"}.get(rating, "unsupported"),
        "rating_value": rating,
        "distance": distance,
        "category": "archive",
    }


class TestDeriveVerdictConfidenceFloor:
    """Onceki hata: relevance her zaman en az 0.3'e tabanliydi, gercek
    eslesme kalitesinden bagimsiz olarak — kullaniciya HER arsiv-tabanli
    hukum icin sabit '%30 guven' gosteriliyordu."""

    def test_low_relevance_match_produces_low_confidence_not_floored_to_30_percent(self):
        manager = ConversationManager()
        plan = InvestigationPlan(intent=_make_intent(), steps=[])
        investigation = InvestigationResult(plan=plan)
        # Cok zayif bir eslesme: distance=0.90 -> ham relevance=0.10
        investigation.archive_results = [
            _archive_result("Alakasiz bir makale", "hicbir ortak konu yok", rating=4, distance=0.90),
        ]

        result = manager._derive_verdict("test claim", investigation)

        # Eskiden bu her zaman >= 0.3 olurdu (taban). Artik ham degere yakin olmali.
        assert result["confidence"] < 0.15
        assert result["confidence"] == pytest.approx(0.10, rel=1e-6)

    def test_high_relevance_match_produces_higher_confidence_than_low_relevance_one(self):
        """Iki farkli kalitedeki eslesme artik birbirinden ayirt edilebilir
        guven degerleri uretmeli — eskiden ikisi de sabit 0.3'te esitlenirdi."""
        manager = ConversationManager()
        plan = InvestigationPlan(intent=_make_intent(), steps=[])

        weak = InvestigationResult(plan=plan)
        weak.archive_results = [_archive_result("Zayif", "az ilgili", rating=4, distance=0.90)]

        strong = InvestigationResult(plan=plan)
        strong.archive_results = [_archive_result("Guclu", "cok ilgili", rating=4, distance=0.60)]

        weak_result = manager._derive_verdict("test claim", weak)
        strong_result = manager._derive_verdict("test claim", strong)

        assert strong_result["confidence"] > weak_result["confidence"]

    def test_missing_distance_falls_back_to_default_not_floor(self):
        """distance hic yoksa (nadir durum) makul bir varsayilana duser."""
        manager = ConversationManager()
        plan = InvestigationPlan(intent=_make_intent(), steps=[])
        investigation = InvestigationResult(plan=plan)
        r = _archive_result("X", "Y", rating=4, distance=0.5)
        del r["distance"]
        investigation.archive_results = [r]

        result = manager._derive_verdict("test claim", investigation)
        assert result["confidence"] == pytest.approx(0.6, rel=1e-6)




class TestArchiveSearchPruning:
    """_execute_search_archive artik search_external/search_health_org ile
    tutarli sekilde prune_irrelevant kullanmali."""

    def test_completely_unrelated_query_gets_pruned(self):
        """Saglikla hicbir ilgisi olmayan bir sorgu, TF-IDF'in yanlislikla
        yuksek skor verdigi bir sonucu bile eleyebilmeli."""
        unrelated_results = [
            {"title": "Egzersiz ve Kalp Sagligi", "passage": "Egzersizin kalp uzerindeki etkileri incelendi."},
        ]
        pruned = prune_irrelevant(unrelated_results, "İstanbul trafiği ne zaman rahatlar")
        assert pruned == []

    def test_relevant_query_is_not_pruned(self):
        results = [
            {"title": "Kahve ve Kolesterol İlişkisi", "passage": "Filtresiz kahve tüketimi kolesterol seviyelerini etkileyebilir."},
        ]
        pruned = prune_irrelevant(results, "Kahve kolesterolü yükseltir mi?")
        assert len(pruned) == 1


class TestLowConfidenceCaveat:
    """best_archive bulunamadiginda (gercekten ilgili tek bir kaynak yok)
    ama yine de bir hukum uretildiginde, kullaniciya acik bir uyari
    gosterilmeli — eskiden bu durumda hicbir uyari olmadan kendinden emin
    bir ifade ('Büyük Ölçüde Destekleniyor') gösteriliyordu."""

    def test_caveat_shown_when_no_strong_archive_match_but_verdict_exists(self):
        builder = ResponseBuilder()
        intent = _make_intent("Vitamin D eksikliği kemik sağlığını etkiler mi?")
        results = {
            "archive_results": [
                # Baslik/pasaj iddiayla yeterince ortusmuyor -> best_archive=None
                {"title": "Alakasiz Bir Konu", "passage": "Tamamen farkli bir sey.", "distance": 0.9},
            ],
            "external_results": [],
            "health_org_results": [],
            "total_sources": 1,
            "verdict": "mostly_supported",
            "verdict_confidence": 0.11,
        }
        response = builder._respond_verify_claim(
            intent=intent, sufficiency=_full_sufficiency(), results=results, context=None,
        )
        assert "⚠️" in response.text
        assert "düşük güvenle" in response.text

    def test_no_caveat_when_strong_archive_match_exists(self):
        builder = ResponseBuilder()
        intent = _make_intent("Kahve kolesterolü yükseltir mi?")
        results = {
            "archive_results": [
                {
                    "title": "Kahve Kolesterol İlişkisi",
                    "passage": "Kahve kolesterolü yükseltir mi konusunu inceleyen bir çalışma.",
                    "distance": 0.3,
                    "rating_value": 4,
                    "verdict": "mostly_supported",
                    "url": "https://example.com/kahve",
                },
            ],
            "external_results": [],
            "health_org_results": [],
            "total_sources": 1,
            "verdict": "mostly_supported",
            "verdict_confidence": 0.7,
        }
        response = builder._respond_verify_claim(
            intent=intent, sufficiency=_full_sufficiency(), results=results, context=None,
        )
        assert "⚠️" not in response.text


def _full_sufficiency():
    from evidence.chat.sufficiency import SufficiencyLevel, SufficiencyResult
    return SufficiencyResult(level=SufficiencyLevel.SUFFICIENT, confidence=0.8)
