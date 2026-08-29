"""Aciklayici (LLM narrator) + Duzenleyici (kaynak-guvenligi editoru).

Uc asamali koruma:
1. narrate_verdict() once, provider tool-calling destekliyorsa (supports_tools),
   YAPISAL bir atif yolunu dener: LLM'e URL'leri metne gomdurmek yerine, tool
   input_schema'sinin enum ile SADECE saglanan kaynak URL'lerine kisitladigi bir
   "source_urls_used" alani doldurtur — boylece API katmaninin kendisi LLM'in
   olmayan bir URL uretmesini yapisal olarak zorlastirir (bkz. _build_cite_tool).
   Bu yol basarisiz olursa (provider tool desteklemiyor, hata, bos/gecersiz yanit)
   eski serbest-metin yoluna (asagida) geri doner.
2. Serbest-metin yolu — LLM'e SADECE saglanan kanitlari yorumlatir. Basarisiz
   olursa (provider yok, hata, bos yanit) None doner; cagiran taraf mevcut
   kural-tabanli (Turkce) metne geri doner. interpret_with_llm'in aksine,
   burada asla ingilizce dolgu-metin fallback'i disari sizmaz — basarisizlik
   her zaman acikca None ile isaretlenir.
3. edit_and_validate() — HER IKI yoldan donen metni de kanit listesine karsi
   dogrular (savunma katmanlari — tool-schema'nin enum kisitlamasina bile kor
   guvenilmez). Taslakta, saglanan kanitlarda olmayan (uydurulmus) bir URL
   varsa metni REDDEDER (None doner). Bu, saglik iddialari dogrulayan bir
   sitede dogrulanmamis/halusinasyon iceren metnin kullaniciya asla
   gosterilmemesini saglar (fail-closed).
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s)\]}>\"']+")


def _clean_url(url: str) -> str:
    return url.rstrip(".,;:)]}>\"'")


_CITE_TOOL_NAME = "report_explanation"


def _build_cite_tool(allowed_urls: list[str]) -> dict[str, Any]:
    """Tool schema whose 'source_urls_used' field is enum-constrained to the
    exact URLs offered this turn — makes citing a nonexistent source a schema
    violation rather than something only caught after the fact by regex."""
    return {
        "name": _CITE_TOOL_NAME,
        "description": "Report the user-facing explanation and which of the provided sources were actually used.",
        "input_schema": {
            "type": "object",
            "properties": {
                "explanation": {
                    "type": "string",
                    "description": "Short user-facing explanation (max 4-5 sentences), in the same language as the claim.",
                },
                "source_urls_used": {
                    "type": "array",
                    "items": {"type": "string", "enum": allowed_urls},
                    "description": "URLs from the provided source list that were actually referenced in the explanation.",
                },
            },
            "required": ["explanation", "source_urls_used"],
        },
    }


async def _narrate_verdict_via_tool(prompt: str, allowed_urls: list[str], provider: Any) -> str | None:
    """Structured-citation path — see module docstring. None on any failure."""
    tool = _build_cite_tool(allowed_urls)
    try:
        result = await provider.generate_with_tool(prompt, tool)
    except Exception as e:  # pragma: no cover - provider'a gore hata tipi degisir
        logger.warning(f"Structured narrator tool call failed: {e}")
        return None

    if not result:
        return None

    explanation = (result.get("explanation") or "").strip()
    if not explanation:
        return None

    cited = result.get("source_urls_used")
    if not isinstance(cited, list) or any(u not in allowed_urls for u in cited):
        # Savunma katmani: enum kisitlamasina bile kor guvenilmez.
        logger.warning("Structured narrator returned an out-of-list URL — rejecting")
        return None

    return explanation


async def narrate_verdict(
    claim: str,
    verdict: str,
    confidence: float,
    matches: list[dict[str, Any]],
    provider: Any | None,
    recent_history: list[dict[str, str]] | None = None,
    language: str = "tr",
) -> str | None:
    """LLM'e motorun hukmunu, sadece saglanan kanitlara dayanarak yorumlat.

    Args:
        recent_history: get_history_for_api() ciktisi — onceki turlari gercek
            rol-etiketli mesajlar olarak gecirmek icin (provider destekliyorsa,
            bkz. LLMProvider.generate_with_history). Takip sorulari ("peki
            cocuklarda?") icin baglam sagliyor; provider bunu desteklemiyorsa
            sessizce yok sayilir, davranis degismez.

    Returns:
        LLM'in ham taslak metni, ya da basarisizlik/provider yoksa None.
        None hicbir zaman "hata metni" degildir — sadece "kullanma" sinyalidir.
    """
    if provider is None or not matches:
        return None

    sources_lines = []
    allowed_urls: list[str] = []
    for i, m in enumerate(matches[:5], 1):
        title = m.get("title") or "Bilinmeyen kaynak"
        url = m.get("url") or ""
        sources_lines.append(f"{i}. {title} — {url}")
        if url:
            allowed_urls.append(url)
    sources_text = "\n".join(sources_lines)

    # NOT (2026-08-29): "Iddianin dilinde yanit ver" (mesajdan tahmin)
    # yerine artik ConversationManager.language'dan gelen acik sinyal
    # kullaniliyor — bkz. narrate_social'daki ayni degisiklik/gerekce.
    language_instruction = "Turkce yaz." if language != "en" else "Write in English."

    prompt = f"""Sen bir kanit-dogrulama yorumcususun, kanit KAYNAGI degilsin.

KURALLAR:
- SADECE asagida verilen kaynaklara atif yapabilirsin.
- Verilmeyen hicbir kanit, calisma veya URL uydurma.
- {language_instruction}
- Kisa ve acik ol (en fazla 4-5 cumle); her onemli noktada ilgili kaynagin URL'sini belirt.
- Kanit yetersiz veya celiskiliyse bunu acikca soyle, hukmu abartma.

Iddia: {claim}
Motorun hukmu: {verdict} (guven: {confidence:.0%})

Saglanan kaynaklar (SADECE bunlara atif yapabilirsin, baska hicbir sey uydurma):
{sources_text}

Yukaridaki hukmu bu kaynaklara dayanarak kullanici dostu, kisa bir sekilde acikla."""

    if getattr(provider, "supports_tools", False) and allowed_urls:
        structured = await _narrate_verdict_via_tool(prompt, allowed_urls, provider)
        if structured is not None:
            return structured

    try:
        if recent_history and hasattr(provider, "generate_with_history"):
            text = await provider.generate_with_history(prompt, recent_history)
        else:
            text = await provider.generate(prompt)
    except Exception as e:  # pragma: no cover - provider'a gore hata tipi degisir
        logger.warning(f"Narrator LLM call failed: {e}")
        return None

    text = (text or "").strip()
    return text or None


def edit_and_validate(draft_text: str, evidence_matches: list[dict[str, Any]]) -> str | None:
    """LLM taslagini kanit listesine karsi dogrula; gecerse temizlenmis metni dondur.

    Taslakta gecen her URL, evidence_matches icindeki bir URL ile birebir
    (kirpilmis) eslesmelidir. Eslesmeyen bir URL varsa taslak REDDEDILIR
    (None doner) — dogrulanmamis metin asla kullaniciya gosterilmez.
    """
    if not draft_text or not draft_text.strip():
        return None

    allowed_urls = {
        _clean_url(m["url"])
        for m in evidence_matches
        if m.get("url")
    }

    cited_urls = {_clean_url(u) for u in _URL_RE.findall(draft_text)}
    hallucinated = cited_urls - allowed_urls
    if hallucinated:
        logger.warning(f"Editor rejected LLM draft — unverified citations: {hallucinated}")
        return None

    cleaned = re.sub(r"\n{3,}", "\n\n", draft_text.strip())
    return cleaned
