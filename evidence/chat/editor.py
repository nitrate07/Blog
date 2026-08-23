"""Aciklayici (LLM narrator) + Duzenleyici (kaynak-guvenligi editoru).

Iki asamali koruma:
1. narrate_verdict() — LLM'e SADECE saglanan kanitlari yorumlatir. Basarisiz
   olursa (provider yok, hata, bos yanit) None doner; cagiran taraf mevcut
   kural-tabanli (Turkce) metne geri doner. interpret_with_llm'in aksine,
   burada asla ingilizce dolgu-metin fallback'i disari sizmaz — basarisizlik
   her zaman acikca None ile isaretlenir.
2. edit_and_validate() — LLM taslagini kanit listesine karsi dogrular.
   Taslakta, saglanan kanitlarda olmayan (uydurulmus) bir URL varsa metni
   REDDEDER (None doner). Bu, saglik iddialari dogrulayan bir sitede
   dogrulanmamis/halusinasyon iceren metnin kullaniciya asla gosterilmemesini
   saglar (fail-closed).
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s)\]}>\"']+")


def _clean_url(url: str) -> str:
    return url.rstrip(".,;:)]}>\"'")


async def narrate_verdict(
    claim: str,
    verdict: str,
    confidence: float,
    matches: list[dict[str, Any]],
    provider: Any | None,
) -> str | None:
    """LLM'e motorun hukmunu, sadece saglanan kanitlara dayanarak yorumlat.

    Returns:
        LLM'in ham taslak metni, ya da basarisizlik/provider yoksa None.
        None hicbir zaman "hata metni" degildir — sadece "kullanma" sinyalidir.
    """
    if provider is None or not matches:
        return None

    sources_lines = []
    for i, m in enumerate(matches[:5], 1):
        title = m.get("title") or "Bilinmeyen kaynak"
        url = m.get("url") or ""
        sources_lines.append(f"{i}. {title} — {url}")
    sources_text = "\n".join(sources_lines)

    prompt = f"""Sen bir kanit-dogrulama yorumcususun, kanit KAYNAGI degilsin.

KURALLAR:
- SADECE asagida verilen kaynaklara atif yapabilirsin.
- Verilmeyen hicbir kanit, calisma veya URL uydurma.
- Iddianin dilinde yanit ver (iddia Turkce ise Turkce, Ingilizce ise Ingilizce).
- Kisa ve acik ol (en fazla 4-5 cumle); her onemli noktada ilgili kaynagin URL'sini belirt.
- Kanit yetersiz veya celiskiliyse bunu acikca soyle, hukmu abartma.

Iddia: {claim}
Motorun hukmu: {verdict} (guven: {confidence:.0%})

Saglanan kaynaklar (SADECE bunlara atif yapabilirsin, baska hicbir sey uydurma):
{sources_text}

Yukaridaki hukmu bu kaynaklara dayanarak kullanici dostu, kisa bir sekilde acikla."""

    try:
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
