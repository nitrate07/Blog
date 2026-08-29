"""Paylasilan HTTP retry/backoff yardimcisi — tum kaynak ajanlari icin tek yer.

Once HealthOrgAgent._get_with_retry olarak yalnizca 6 HTML-scraping ajaninda
(nice, ecdc, ema, esc, tuseb, google_scholar) vardi. Canli veriyle dogrulandi
(2026-08-29): asil onemli akademik kaynaklar — PubMed, Crossref, Europe PMC,
OpenAlex, ve journal_base.py uzerinden 8 dergi ajani (jama, bmj, lancet,
nejm, who, cdc, cochrane, aha) — bu yardimciyi HIC kullanmiyordu:
- PubMed/Crossref/EuropePMC/OpenAlex: SourceAgent'tan turuyorlar
  (HealthOrgAgent'tan degil), kendi ham client.get()+raise_for_status()
  cagrilarini yapiyorlardi, tek bir gecici hatada (zaman asimi, 503) o
  turdaki aramayi tamamen kaybediyorlardi.
- journal_base.py: KENDI retry dongusu vardi ama hatali — yalniz 429 icin
  gercekten tekrar deniyordu; baska HERHANGI bir exception (zaman asimi,
  baglanti hatasi, 5xx) `for attempt in range(3)` dongusunun ortasinda
  olsa bile aninda `return []` ile tum denemeyi birakiyordu, kalan
  denemeleri hic kullanmadan.
- ClinicalTrialsAgent / FDAAgent: HealthOrgAgent'tan turuyorlar (yardimci
  miras yoluyla zaten mevcuttu) ama _search icinde hic cagirmiyorlardi.

Bu modul, hepsinin tek bir yerden, tutarli sekilde kullanabilecegi
bagimsiz bir fonksiyon saglar.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Gecici sayilan HTTP durum kodlari — bunlar icin tekrar denenir. 403/404
# gibi kalici hatalar burada YOK: WHO IRIS'in bot-korumasi (403) ornegi
# gosteriyor ki bunlar tekrar denemekle duzelmez (bkz. who.py docstring).
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
DEFAULT_MAX_RETRIES = 2  # ilk deneme + en fazla 2 tekrar = en fazla 3 toplam deneme
DEFAULT_BACKOFF_SECONDS = 0.4  # denemeler arasi: 0.4s, 0.8s (ustel)


async def get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    agent_name: str = "unknown",
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    retryable_status_codes: frozenset[int] = RETRYABLE_STATUS_CODES,
    **kwargs: Any,
) -> httpx.Response:
    """GET + gecici hatalar icin ustel geri-cekilmeli tekrar deneme.

    YALNIZCA gecici sinifina giren hatalari (baglanti zaman asimi/kopmasi,
    429/5xx) tekrar dener; kalici hatalari (403 bot-engelleme, 404 gibi)
    TEKRAR DENEMEZ — hemen firlatir. Cagiran taraf acisindan davranis:
    basarisizlikta ayni exception turleri firlar (httpx.HTTPStatusError /
    TimeoutException / ConnectError), yalnizca gecici hatalarda birden
    fazla deneme yapilmis olur.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = await client.get(url, **kwargs)
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
            last_exc = e
        else:
            if resp.status_code not in retryable_status_codes:
                resp.raise_for_status()
                return resp
            last_exc = httpx.HTTPStatusError(
                f"{resp.status_code} (retryable status)",
                request=resp.request,
                response=resp,
            )

        if attempt < max_retries:
            delay = backoff_seconds * (2 ** attempt)
            logger.debug(
                f"{agent_name}: retryable failure on attempt {attempt + 1} "
                f"for {url!r}, retrying in {delay}s: {last_exc}"
            )
            await asyncio.sleep(delay)

    assert last_exc is not None
    raise last_exc
