"""LLM destekli sosyal sohbet katmani (selamlasma, kucuk konusma, kimlik,
tesekkur, veda).

Kural-tabanli sabit sablonlar (response.py'deki ResponseBuilder._social_*
metodlari) HER ZAMAN calisir durumdaki tek garantili yol olarak kalir. Bu
modul, llm_provider ayarliysa o sabit metinlerin yerine daha dogal,
degisken ve baglam-farkindalikli bir yanit URETMEYE CALISIR — basarisiz
olursa (provider yok, hata, bos/asiri uzun yanit) None doner ve cagiran
taraf mevcut sabit sablona geri doner. llm_provider=None oldugu her durumda
(test/CI varsayilani dahil) davranis bugunkuyle birebir aynidir.

Bu katman asla bir saglik iddiasi hukmu vermez veya kanit yorumlamaz —
sadece kisa, dostane bir sohbet yaniti uretir. Gercek iddia dogrulamasi
VERIFY_CLAIM akisinin (bkz. editor.py) isidir; buradaki LLM'e acikca bu
sinirin disina cikmamasi soylenir.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_REPLY_CHARS = 500

_SOCIAL_LABELS: dict[str, str] = {
    "greeting": "bir selamlasma",
    "smalltalk": "gundelik bir hal hatir sorma",
    "identity": "botun kim oldugunu soran bir soru",
    "thanks": "bir tesekkur",
    "farewell": "bir vedalasma",
    "general_chat": "gundelik, saglik iddiasi olmayan bir sohbet mesaji (ör. kendini tanitma, gundelik bir yorum)",
}


async def narrate_social(
    intent_type: str,
    user_message: str,
    recent_history: list[dict[str, str]],
    provider: Any | None,
) -> str | None:
    """Sosyal bir mesaja LLM ile dogal, kisa bir yanit uretmeyi dener.

    Args:
        intent_type: Intent.type.value (ör. "greeting", "smalltalk", ...).
        user_message: Kullanicinin o anki mesaji (ham).
        recent_history: get_history_for_api() ciktisi — [{"role", "content"}, ...].
            Provider generate_with_history() destekliyorsa gercek rol-etiketli
            mesaj olarak da gecirilir (bkz. LLMProvider.generate_with_history);
            desteklemiyorsa (ör. testlerdeki FakeProvider) sessizce eski
            generate(prompt) yoluna doner, davranis degismez.
        provider: LLMProvider.generate(prompt) uygulayan nesne, ya da None.

    Returns:
        LLM'in ham yanit metni, ya da basarisizlik/provider yoksa None.
        None hicbir zaman "hata metni" degildir — sadece "sabit sablonu kullan"
        sinyalidir.
    """
    if provider is None:
        return None

    label = _SOCIAL_LABELS.get(intent_type, "gundelik bir mesaj")

    history_lines = []
    for turn in recent_history[-4:]:
        role = "Kullanici" if turn.get("role") == "user" else "Sen"
        content = (turn.get("content") or "")[:200]
        if content:
            history_lines.append(f"{role}: {content}")
    history_text = "\n".join(history_lines) if history_lines else "(yok — ilk mesaj)"

    prompt = f"""Sen Ari Kaynak Sorusturucusu'sun — saglik iddialarini kanitlarina kadar
takip eden, dostane ama profesyonel bir yapay zeka arastirmaci karakterisin.

Kullanicinin su anki mesaji {label} niteliginde, bir saglik iddiasi degil.

KURALLAR:
- Mesajin dilinde yanit ver (Turkce ise Turkce, Ingilizce ise Ingilizce).
- Kisa ol: en fazla 2-3 cumle.
- Dostane ve dogal ol, ama karakterinden (saglik iddialarini kanita dayali
  arastiran bir uzman) kopma.
- ASLA bir saglik iddiasi hakkinda hukum verme, yorum yapma veya bilgi
  uydurma — bu senin simdiki isin degil. Kullanici gercek bir saglik iddiasi
  sorarsa, onu iddiayi yazmasi icin nazikce yonlendir, kendin yanitlama.
- En fazla 1 emoji kullanabilirsin, zorunlu degil.

Son konusma gecmisi:
{history_text}

Kullanicinin su anki mesaji: {user_message}

Kisa, dostane bir yanit yaz."""

    try:
        if recent_history and hasattr(provider, "generate_with_history"):
            text = await provider.generate_with_history(prompt, recent_history)
        else:
            text = await provider.generate(prompt)
    except Exception as e:  # pragma: no cover - provider'a gore hata tipi degisir
        logger.warning(f"Social narrator LLM call failed: {e}")
        return None

    text = (text or "").strip()
    if not text or len(text) > MAX_REPLY_CHARS:
        return None
    return text
