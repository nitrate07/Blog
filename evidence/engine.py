"""Deterministic, evidence-first verification engine for the MVP."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from .models import EvidenceItem, SourceQuality, Verdict, VerificationRequest, VerificationResponse
from .providers import VerificationProvider, default_provider
from .sources import RetrievedSource, SourceFetcher

_STOPWORDS = {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it", "of", "on", "or", "that", "the", "this", "to", "was", "were", "with"}
# NOT (2026-08-29): _NEGATIONS/_QUALIFIERS eskiden yalnizca Ingilizce
# kelimeler iceriyordu — bu, Turkce iddia/pasaj ciftlerinde olumsuzlama
# ve nitelik-belirteci tespitinin (bkz. compare_claim_evidence)
# HICBIR ZAMAN calismadigi anlamina geliyordu (bu fonksiyon
# evidence/chat/conversation.py'nin de kullandigi cekirdek bir islev).
# Yaygin Turkce formlar eklendi.
_NEGATIONS = {
    "not", "no", "never", "neither", "none", "without", "doesn't", "doesnt", "didn't", "didnt",
    "değil", "degil", "yok", "hiçbir", "hicbir", "hiç", "hic", "etmiyor", "etmez",
}
_QUALIFIERS = {
    "may", "might", "possible", "possibly", "associated", "association", "limited", "uncertain", "preliminary", "suggests", "suggest",
    "olabilir", "muhtemelen", "sınırlı", "sinirli", "belirsiz", "öngörüyor", "ongoruyor",
    "işaret", "isaret", "ilişkili", "iliskili", "bağlantılı", "baglantili",
}

logger = logging.getLogger(__name__)


def _tokens(value: str) -> set[str]:
    """Metni kelime kumesine ayirir.

    NOT (2026-08-29): Regex eskiden yalnizca [a-z0-9] (ASCII) yakaliyordu
    — Turkce ozel karakterler (ç, ğ, ı, ö, ş, ü) kelime SINIRI sayilip
    kelimeleri parcaliyordu (ör. "sağlığına" -> kayboluyordu, "gösteriyor"
    -> "steriyor" oluyordu). Bu, compare_claim_evidence'in TUM Turkce
    iddia/pasaj karsilastirmalarini (kelime ortusmesi, negasyon/nitelik
    tespiti) sessizce bozan sistemik bir hataydi — yalnizca ozel
    karakter icermeyen kisa/basit kelimeler dogru eslesiyordu.
    """
    return {word for word in re.findall(r"[a-z0-9çğıöşü]+", value.lower()) if len(word) > 2 and word not in _STOPWORDS}


def _sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]


# NOT (2026-08-29): Kullanicinin "GitHub'daki acik kaynaklara bak" talebi
# uzerine incelenen humanchaos/factcheck projesinden (bkz. docs/ai-
# infrastructure-roadmap.md) uyarlandi. O proje, LLM'lerin buyuk sayilarda
# halusinasyon gorme egilimine karsi somut bir kod-seviyesi guvenlik agi
# kullaniyor: iddia edilen deger kanittaki degerden >=10x farkliysa,
# hukum otomatik olarak gecersiz kilinir ("math_outlier"). Saglik yanlis
# bilgisinde bu cok yaygin bir kalip: "riski %500 artirir" gibi abartili
# yuzdeler/kat sayilariyla — kelime ortusmesi ("kahve", "kanser", "risk",
# "artirir") yuksek olsa bile SAYININ KENDISI kanitla celiskili olabilir.
# compare_claim_evidence bu ana kadar SADECE kelime ortusmesine bakiyordu,
# sayisal buyuklugu hic kontrol etmiyordu.
#
# Tasarim: yalnizca AYNI BIRIM (yuzde-yuzde, kat-kat) karsilastirilir —
# birimler arasi donusum (ör. "%50" ile "2 kat" karsilastirmak) kendi
# varsayimlarimizin hatasini guvenlik kontrolune sokma riski tasir, bu
# yuzden BILEREK yapilmiyor; farkli birimler varsa kontrol atlanir (flag
# yok), yanlis-pozitif riskini asgariye indirir.
_PERCENT_RE = re.compile(r"(?:%\s*(\d+(?:[.,]\d+)?))|(?:(\d+(?:[.,]\d+)?)\s*%)|(?:yüzde\s*(\d+(?:[.,]\d+)?))|(?:(\d+(?:[.,]\d+)?)\s*percent)", re.IGNORECASE)
_MULTIPLIER_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:kat[ıi]?|misli|times|fold)\b", re.IGNORECASE)

# Bu esigin uzerindeki oran farki "math_outlier" olarak isaretlenir —
# humanchaos/factcheck'in 10x esigine benzer ama biraz daha temkinli
# (5x), makul yuvarlamalari ("iki kattan fazla" ~ "2.3 kat" gibi)
# yanlislikla yakalamamak icin.
_OUTLIER_RATIO_THRESHOLD = 5.0


def _extract_magnitudes(text: str) -> tuple[list[float], list[float]]:
    """Metinden yuzde ve kat-carpani buyukluklerini ayri ayri cikarir.

    Returns:
        (yuzdeler, kat_carpanlari) — her biri bulunan sayisal degerlerin listesi.
    """
    percents: list[float] = []
    for m in _PERCENT_RE.finditer(text):
        raw = next((g for g in m.groups() if g), None)
        if raw:
            try:
                percents.append(float(raw.replace(",", ".")))
            except ValueError:
                continue

    multipliers: list[float] = []
    for m in _MULTIPLIER_RE.finditer(text):
        try:
            multipliers.append(float(m.group(1).replace(",", ".")))
        except ValueError:
            continue

    return percents, multipliers


def check_numeric_consistency(claim: str, passage: str) -> dict[str, object]:
    """Iddiadaki sayisal buyukluk (yuzde/kat) kanittakiyle AYNI BIRIMDE
    kiyaslandiginda buyuk oranda tutarsizsa isaretler.

    Returns:
        {"outlier": bool, "claim_value": float | None, "evidence_value": float | None,
         "unit": str | None, "ratio": float | None}
        "outlier" False ise diger alanlar bilgilendirme amaclidir (kontrol
        atlandiysa ya da tutarliysa None/False donebilir) — cagiran taraf
        yalnizca "outlier" alanina bakarak karar vermeli.
    """
    claim_pct, claim_mult = _extract_magnitudes(claim)
    ev_pct, ev_mult = _extract_magnitudes(passage)

    def _closest_ratio_outlier(claim_vals: list[float], ev_vals: list[float], unit: str) -> dict | None:
        if not claim_vals or not ev_vals:
            return None
        # En buyuk iddia degeri ile en yakin kanit degerini kiyasla —
        # iddialar genelde tek, carpici bir rakam vurgular.
        claim_v = max(claim_vals)
        closest = min(ev_vals, key=lambda v: abs(v - claim_v))
        if claim_v <= 0 or closest <= 0:
            return None
        ratio = max(claim_v, closest) / min(claim_v, closest)
        if ratio >= _OUTLIER_RATIO_THRESHOLD:
            return {
                "outlier": True,
                "claim_value": claim_v,
                "evidence_value": closest,
                "unit": unit,
                "ratio": round(ratio, 1),
            }
        return None

    result = _closest_ratio_outlier(claim_pct, ev_pct, "%") or _closest_ratio_outlier(claim_mult, ev_mult, "kat")
    if result:
        return result
    return {"outlier": False, "claim_value": None, "evidence_value": None, "unit": None, "ratio": None}


def compare_claim_evidence(claim: str, text: str) -> tuple[Verdict, str, float]:
    """Return a conservative deterministic comparison and the most relevant sentence.

    NOT (2026-08-29): En sonda bir sayisal-tutarlilik guvenlik agi var —
    bkz. check_numeric_consistency. Kelime ortusmesi SUPPORTED/PARTIALLY_
    SUPPORTED'a isaret etse bile, iddianin vurguladigi sayi (%/kat) en
    alakali pasajdaki ayni-birimli sayidan >=5x farkliysa, hukum
    UNSUPPORTED'a dusurulur — "kahve kanseri %500 artirir" gibi abartili
    saglik yanlis bilgisi kaliplarina karsi somut bir koruma.
    """
    claim_tokens = _tokens(claim)
    ranked = []
    for sentence in _sentences(text):
        overlap = len(claim_tokens & _tokens(sentence)) / max(len(claim_tokens), 1)
        ranked.append((overlap, sentence))
    relevance, passage = max(ranked, default=(0.0, ""), key=lambda item: item[0])
    passage_tokens = _tokens(passage)
    if relevance < 0.28:
        return Verdict.UNVERIFIED, passage, round(relevance, 2)

    numeric_check = check_numeric_consistency(claim, passage)
    if numeric_check["outlier"]:
        logger.warning(
            f"Numeric outlier detected: claim cites {numeric_check['claim_value']}"
            f"{numeric_check['unit']} vs evidence {numeric_check['evidence_value']}"
            f"{numeric_check['unit']} (ratio {numeric_check['ratio']}x) — downgrading to UNSUPPORTED"
        )
        return Verdict.UNSUPPORTED, passage, round(relevance, 2)

    if _NEGATIONS & passage_tokens:
        return Verdict.UNSUPPORTED, passage, round(relevance, 2)
    if _QUALIFIERS & passage_tokens:
        return Verdict.PARTIALLY_SUPPORTED, passage, round(relevance, 2)
    if relevance >= 0.5:
        return Verdict.SUPPORTED, passage, round(relevance, 2)
    return Verdict.PARTIALLY_SUPPORTED, passage, round(relevance, 2)


_QUALITY_SCORE = {SourceQuality.PRIMARY: 1.0, SourceQuality.SECONDARY: 0.75, SourceQuality.TERTIARY: 0.35, SourceQuality.UNKNOWN: 0.5}


class EvidenceVerifier:
    def __init__(self, fetcher: SourceFetcher | None = None, provider: VerificationProvider | None = None) -> None:
        self.fetcher = fetcher or SourceFetcher()
        self.provider = provider or default_provider()

    async def verify(self, request: VerificationRequest) -> VerificationResponse:
        evidence: list[EvidenceItem] = []
        comparisons: list[tuple[Verdict, float, SourceQuality]] = []
        for source_input in request.sources:
            try:
                source: RetrievedSource = await self.fetcher.fetch(str(source_input.url))
            except Exception as exc:
                logger.warning("Failed to fetch source %s: %s", source_input.url, exc)
                continue
            deterministic, passage, relevance = compare_claim_evidence(request.claim, source.text)
            provider_verdict = await self.provider.compare(request.claim, passage, request.context)
            verdict = provider_verdict or deterministic
            if passage and relevance >= 0.28:
                evidence.append(EvidenceItem(source_url=source.url, source_type=source.quality, title=source.title, passage=passage, relevance=relevance, source_content_hash=source.content_hash))
                comparisons.append((verdict, relevance, source.quality))
        if not comparisons:
            return self._response(request.claim, Verdict.UNVERIFIED, 0.0, [], SourceQuality.UNKNOWN)
        # A direct contradiction has priority: never average it away with a weak match.
        unsupported = [item for item in comparisons if item[0] is Verdict.UNSUPPORTED]
        best = max(comparisons, key=lambda item: item[1] * _QUALITY_SCORE[item[2]])
        verdict = Verdict.UNSUPPORTED if unsupported and max(item[1] for item in unsupported) >= best[1] - 0.1 else best[0]
        quality = max((item[2] for item in comparisons), key=lambda q: _QUALITY_SCORE[q])
        confidence = round(min(0.95, best[1] * (0.55 + 0.4 * _QUALITY_SCORE[quality])), 2)
        if verdict is Verdict.UNVERIFIED:
            confidence = 0.0
        return self._response(request.claim, verdict, confidence, evidence, quality)

    @staticmethod
    def _response(claim: str, verdict: Verdict, confidence: float, evidence: list[EvidenceItem], quality: SourceQuality) -> VerificationResponse:
        return VerificationResponse(verdict=verdict, confidence=confidence, claim=claim, evidence=evidence, source_quality=quality, checked_at=datetime.now(timezone.utc))
