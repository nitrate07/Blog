"""Dogal cevap uretme — kanitlari kullanici dostu formata cevirir.

Bu modul LLM kullanmaz. Tamamen kural tabanli:
- Intent'e gore format sec
- Kanitlari suni sirala
- Follow-up icin baglam sagla
- Dashboard icin uygun formatta dondur
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .intent import Intent
from .sufficiency import SufficiencyLevel, SufficiencyResult

# Arama/ortusme kontrolunde anlamsiz genel kelimeler.
_CLAIM_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "does", "did", "are",
    "gerçekten", "hakında", "neden", "nedir", "mi", "mı", "mu", "mü",
    "bir", "gibi", "daha", "çok", "var", "yok", "yapar", "eder", "olur",
}

# Ajan adi -> kurum adi (yanitta okunur etiket).
ORG_TR = {
    "who": "DSÖ (WHO)",
    "cdc": "CDC",
    "ecdc": "ECDC",
    "fda": "FDA",
    "ema": "EMA",
    "nice": "NICE",
    "esc": "ESC",
    "aha": "AHA",
    "tuseb": "TÜSEB",
    "clinicaltrials": "ClinicalTrials.gov",
    "nejm": "NEJM",
    "jama": "JAMA",
    "lancet": "The Lancet",
    "bmj": "BMJ",
    "cochrane": "Cochrane",
    "pubmed": "PubMed",
    "europepmc": "Europe PMC",
    "openalex": "OpenAlex",
    "crossref": "Crossref",
}


@dataclass
class ChatResponse:
    """Kullaniciya donulecek cevap."""
    text: str
    intent_type: str
    confidence: float
    sources_cited: int = 0
    follow_up_suggestions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "response": self.text,
            "intent": self.intent_type,
            "confidence": round(self.confidence, 3),
            "sources_cited": self.sources_cited,
            "follow_up_suggestions": self.follow_up_suggestions,
            "metadata": self.metadata,
        }


class ResponseBuilder:
    """Kural tabanli cevap uretici.

    LLM kullanmaz — tamamen deterministik.
    Intent ve sufficiency durumuna gore formatlanmis cevap olusturur.
    """

    def build(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        investigation_results: dict[str, Any] | None = None,
        previous_context: dict[str, Any] | None = None,
    ) -> ChatResponse:
        """Intent ve duruma gore cevap olustur."""
        method = getattr(self, f"_respond_{intent.type.value}", self._respond_default)
        return method(intent, sufficiency, investigation_results, previous_context)

    # ------------------------------------------------------------------
    # Sosyal niyetler — arastirma gerektirmez, dogrudan uzman yaniti.
    # ------------------------------------------------------------------

    def build_social(self, intent: Intent) -> ChatResponse:
        """Selamlasma/kucuk konusma/identity icin hazir uzman yaniti."""
        method = getattr(self, f"_social_{intent.type.value}", None)
        if method is None:
            return self._social_greeting(intent)
        return method(intent)

    def _social_greeting(self, intent: Intent) -> ChatResponse:
        return ChatResponse(
            text=(
                "Merhaba! Nasıl yardımcı olabilirim?\n\n"
                "Ben **Arı Kaynak Soruşturucusu**yüm — sağlık iddialarını kanıtına inen bir yapay zekâ araştırmacısı.\n\n"
                "**İddianız nedir? Hemen sorgulayalım.**\n"
                "Şüphelendiğiniz herhangi bir sağlık iddiasını yazın; önce kendi doğrulanmış arşivimi,\n"
                "sonra PubMed, Cochrane ve resmi sağlık kuruluşlarını (DSÖ, CDC, TÜSEB...) tarar,\n"
                "kanıtları çapraz kontrol edip hükmümü kaynaklarıyla birlikte bildiririm."
            ),
            intent_type=intent.type.value,
            confidence=1.0,
            follow_up_suggestions=[
                "Kahve kolesterolü yükseltir mi?",
                "Günlük aspirin kalp krizinden korur mu?",
                "Nasıl çalışıyorsun?",
            ],
        )

    def _social_smalltalk(self, intent: Intent) -> ChatResponse:
        return ChatResponse(
            text=(
                "İyiyim, teşekkür ederim — dosya başında bekliyorum. 😊\n\n"
                "Asıl uzmanlık alanım sağlık iddialarını kanıtlarıyla sorgulamak. "
                "Duyduğunuz bir iddia varsa yazın, hemen soruşturmaya açalım."
            ),
            intent_type=intent.type.value,
            confidence=1.0,
            follow_up_suggestions=[
                "Vitamin D eksikliği kemiklere zarar verir mi?",
                "10.000 adım gerçekten gerekli mi?",
            ],
        )

    def _social_identity(self, intent: Intent) -> ChatResponse:
        return ChatResponse(
            text=(
                "Ben **Arı Kaynak Soruşturucusu**yum — viral sağlık iddialarını birincil bilimsel kaynaklara kadar takip eden bir yapay zekâ.\n\n"
                "**Yöntemim:** İddianızı alırım → yerel makale arşivimi ve 20 harici tıbbi kaynağı (PubMed, Europe PMC, Cochrane, DSÖ, CDC, TÜSEB...) tararım → "
                "kanıtları çapraz kontrol ederim → hükmümü güven skoruyla bildiririm.\n\n"
                "Hükmüm yetersiz kanıtla asla kesinleşmez; o zaman açıkça *\"doğrulanamadı\"* derim."
            ),
            intent_type=intent.type.value,
            confidence=1.0,
            follow_up_suggestions=[
                "Hangi kaynakları kullanıyorsun?",
                "Bir iddia soruşturalım",
            ],
        )

    def _unrecognized_claim(self, intent: Intent) -> ChatResponse:
        """Mesaj bir saglik iddiasi olarak taninamadigi durum icin ayri yanit.

        NOT (2026-08-29): Bu durum eskiden _social_identity ile (gercek
        "sen kimsin?" sorularinin yaniti) AYNI metni paylasiyordu. Canli
        testle dogrulandi: anlamsiz bir girdi (ör. "asdkfjaslkdfj") veya
        yanlislikla yanlis siniflandirilmis bir mesaj, kullaniciya hicbir
        "anlayamadim" sinyali vermeden dogrudan "ben nasil calisiyorum"
        aciklamasina donuyordu — kafa karistirici. Bu, o iki durumu ayirir.
        """
        return ChatResponse(
            text=(
                f"'{intent.original_query}' mesajınızı belirli bir sağlık iddiası olarak tanıyamadım.\n\n"
                "Bir sağlık/tıp iddiasını (ör. \"kahve kolesterolü yükseltir mi?\") doğrudan yazarsanız "
                "hemen araştırmaya başlarım."
            ),
            intent_type=intent.type.value,
            confidence=0.3,
            follow_up_suggestions=[
                "Bir iddia yaz, hemen araştırayım",
                "Nasıl çalıştığımı anlat",
            ],
        )

    def _social_thanks(self, intent: Intent) -> ChatResponse:
        return ChatResponse(
            text=(
                "Rica ederim! Dosyanız her zaman açık.\n\n"
                "Aklınıza takılan başka bir sağlık iddiası olursa yazmanız yeterli."
            ),
            intent_type=intent.type.value,
            confidence=1.0,
            follow_up_suggestions=[
                "Başka bir iddia soruştur",
                "Arşivdeki popüler dosyaları göster",
            ],
        )

    def _social_farewell(self, intent: Intent) -> ChatResponse:
        return ChatResponse(
            text=(
                "Hoşça kalın! Arşiv her gün büyüyor — yeni bir iddiayla geri geldiğinizde kapımız açık."
            ),
            intent_type=intent.type.value,
            confidence=1.0,
            follow_up_suggestions=[],
        )

    def _respond_verify_claim(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        results: dict[str, Any] | None,
        context: dict[str, Any] | None,
    ) -> ChatResponse:
        """Yeni iddia dogrulama cevabi."""
        if not sufficiency.is_sufficient:
            return self._build_insufficient_response(intent, sufficiency)

        if not results:
            return ChatResponse(
                text=f"'{intent.cleaned_query}' icin kanit bulunamadi. Daha spesifik bir soru sorabilir misiniz?",
                intent_type=intent.type.value,
                confidence=0.3,
                follow_up_suggestions=["Daha spesifik bir soru sor", "Farkli kelimelerle ifade et"],
            )

        archive = results.get("archive_results", []) or []
        total = results.get("total_sources", 0)
        best_archive = self._best_archive_match(archive, claim=intent.cleaned_query)

        lines = [f"**{intent.cleaned_query}**", ""]

        # --- Arsiv dosyasi: en degerli sonuc; link + kendi hukmu + pasaj ---
        if best_archive:
            lines.extend(self._format_archive_block(best_archive))
            lines.append("")

        # --- Hukum ---
        verdict = results.get("verdict") or "unverified"
        confidence = results.get("verdict_confidence") or 0
        archive_verdict = (best_archive or {}).get("verdict") or ""

        if verdict not in ("unverified", "") and confidence:
            verdict_display = self.VERDICT_TR.get(verdict, verdict.replace("_", " ").title())
            lines.append(f"**Hüküm:** {verdict_display} (güven %{confidence * 100:.0f})")
            # NOT (2026-08-29): best_archive (yukarida, _best_archive_match ile
            # hesaplandi) zaten "gercekten ilgili mi" sorusuna dogru cevap
            # veriyor (>=2 ortak terim + iddianin yarisi kurali) — ama bu bilgi
            # eskiden yalniz "📁 Arşivimizdeki dosya" bloğunu gösterip
            # göstermemeyi etkiliyordu, Hüküm satırının kendisini değil. Sonuç:
            # best_archive=None (yani hiçbir arşiv sonucu iddiayla gerçekten
            # örtüşmüyor) olsa bile "Hüküm" satırı yine de "Büyük Ölçüde
            # Destekleniyor" gibi kendinden emin bir ifade + düşük bir yüzde
            # (ör. %11) gösterebiliyordu — çoğu okuyucu yüzdeyi değil, kelimeyi
            # görür. Artık bu durumda acik bir uyari ekleniyor.
            if not best_archive and archive:
                lines.append(
                    "⚠️ Bu hüküm arşivdeki hiçbir makaleyle güçlü bir doğrudan "
                    "örtüşme bulamadı — aşağıdaki kaynaklar yalnızca kısmen "
                    "ilgili olabilir, düşük güvenle değerlendirin."
                )
            if results.get("verdict_conflict"):
                consensus = results.get("consensus") or {}
                parts = " · ".join(
                    f"{self.VERDICT_TR.get(v, v)}: %{int(round(100 * s / max(sum(consensus.values()), 1)))}"
                    for v, s in sorted(consensus.items(), key=lambda kv: -kv[1])
                    if s > 0
                )
                lines.append(f"⚠ **Ajan uzlaşısı:** Kaynaklar farklı yönlere işaret ediyor ({parts}). İki sinyali de değerlendirin.")
        elif archive_verdict:
            lines.append(
                f"**Hüküm:** Arşivimizdeki eşleşen dosya bu iddiayı "
                f"**\"{archive_verdict}\"** olarak damgalamış. "
                f"Aşağıdaki dosyadan kanıt zincirini inceleyebilirsiniz."
            )
        else:
            lines.append("**Hüküm:** Doğrulanamadı — henüz yeterli kanıt zinciri kurulamadı.")
        lines.append("")

        if total > 0:
            breakdown = []
            if archive:
                breakdown.append(f"{len(archive)} arşiv")
            orgs_all = results.get("health_org_results", []) or []
            external_all = results.get("external_results", []) or []
            if external_all:
                breakdown.append(f"{len(external_all)} akademik")
            if orgs_all:
                breakdown.append(f"{len(orgs_all)} resmi kurum")
            detail = f" ({', '.join(breakdown)})" if breakdown else ""
            lines.append(f"**{total} kaynak** incelendi{detail}.")
            lines.append("")

        # --- Resmi kuruluslar (max 4, linkli) ---
        orgs = (results.get("health_org_results", []) or [])[:4]
        if orgs:
            lines.append("**Resmi kuruluş kaynakları:**")
            for src in orgs:
                title = (src.get("title") or "Kurum kaydı").strip()
                url = src.get("url") or ""
                org_name = src.get("organization") or ORG_TR.get(src.get("source"), src.get("source", ""))
                year = src.get("published_year")
                label = f"{org_name}: {title}" if org_name and org_name not in title else title
                if year:
                    label += f" ({year})"
                if url.startswith(("http://", "https://")):
                    lines.append(f"- [{label}]({url})")
                else:
                    lines.append(f"- {label}")
            lines.append("")

        # --- Harici akademik kaynaklar (max 5, linkli) ---
        external = (results.get("external_results", []) or [])[:5]
        if external:
            lines.append("**Akademik kaynaklar:**")
            for i, src in enumerate(external, 1):
                title = (src.get("title") or "Bilinmeyen").strip()
                journal = src.get("journal") or ""
                year = src.get("published_year") or src.get("year") or ""
                label = title
                meta = " — " + " · ".join(x for x in ([journal, str(year)] if year else [journal]) if x)
                if meta:
                    label += meta
                url = src.get("url") or ""
                if url.startswith(("http://", "https://")):
                    lines.append(f"{i}. [{label}]({url})")
                else:
                    lines.append(f"{i}. {label}")
            lines.append("")

        # --- Celişkiler ---
        contradictions = results.get("contradictions", []) or []
        if contradictions:
            lines.append(f"⚠️ **{len(contradictions)} çelişkili kanıt** tespit edildi — hüküm dikkatle okuyun.")
            lines.append("")

        text = "\n".join(lines)

        return ChatResponse(
            text=text,
            intent_type=intent.type.value,
            confidence=intent.confidence,
            sources_cited=total,
            follow_up_suggestions=self._claim_followups(best_archive),
        )

    # Arsiv verdict'lerini Turkce etiketlere cevir
    VERDICT_TR = {
        "supported": "Destekleniyor",
        "mostly_supported": "Büyük Ölçüde Destekleniyor",
        "partly_supported": "Kısmen Destekleniyor",
        "misleading": "Yanıltıcı",
        "unsupported": "Desteklenmiyor",
        "unverified": "Doğrulanamadı",
    }

    def _best_archive_match(self, archive: list[dict[str, Any]], claim: str = "") -> dict[str, Any] | None:
        """Arsiv sonuclarindan gercekten ilgili dosyayi sec.

        Sadece distance'a bakmak alakasiz dosyalari one cikarabilir; bu yuzden
        iddiadaki icerik tokenlarinin baslik/pasajda ortusmesi sarttir.
        """
        claim_tokens = {
            t for t in re.findall(r"[a-zçğıöşü0-9]{3,}", (claim or "").lower())
            if t not in _CLAIM_STOPWORDS
        }
        candidates = []
        for r in archive:
            if not isinstance(r, dict) or not (r.get("title") or r.get("url")):
                continue
            haystack = f"{r.get('title') or ''} {r.get('passage') or ''}".lower()
            hay_tokens = set(re.findall(r"[a-zçğıöşü0-9]{3,}", haystack))
            hits = sum(1 for t in claim_tokens if self._token_hit(t, hay_tokens))
            # En az 2 ortak terim VE iddianin en az yarisi — yoksa ilgisizdir.
            if len(claim_tokens) >= 2 and hits >= 2 and hits / len(claim_tokens) >= 0.5:
                candidates.append(r)
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda r: r.get("distance", 999) if isinstance(r.get("distance"), (int, float)) else 999,
        )[0]

    @staticmethod
    def _token_hit(token: str, hay_tokens: set[str]) -> bool:
        """Token ortusmesi — tam veya 4+ harflik kok payi (cekimlere dayanikli)."""
        if token in hay_tokens:
            return True
        if len(token) >= 4:
            return any(h.startswith(token) or token.startswith(h) for h in hay_tokens if len(h) >= 4)
        return False

    def _format_archive_block(self, src: dict[str, Any]) -> list[str]:
        """Arsiv dosyasini link + hukum + pasaj olarak formatla."""
        title = (src.get("title") or "Arşiv dosyası").replace(" — Arı Kaynak", "")
        url = src.get("url") or ""
        verdict_tr = src.get("verdict") or ""
        rating = src.get("rating_value")
        passage = (src.get("passage") or "").strip()

        out = ["📁 **Arşivimizdeki dosya:**"]
        if url.startswith(("http://", "https://")):
            out.append(f"[{title}]({url})")
        else:
            out.append(title)

        if verdict_tr:
            stars = ""
            if isinstance(rating, int) and 0 <= rating <= 5:
                stars = f" {'●' * rating}{'○' * (5 - rating)}"
            out.append(f"Damga: **{verdict_tr}**{stars}")

        if passage:
            cut = passage[:200].rsplit(" ", 1)[0]
            out.append(f"> {cut}…")
        return out

    def _claim_followups(self, best_archive: dict[str, Any] | None) -> list[str]:
        """Iddia cevabina ozel takip onerileri."""
        suggestions = []
        if best_archive and best_archive.get("url"):
            suggestions.append("Bu dosyanın tam makalesini aç")
        suggestions.extend([
            "Neden böyle sonuçlandığını açıkla",
            "Daha fazla kanıt ara",
        ])
        return suggestions

    def _respond_follow_up_why(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        results: dict[str, Any] | None,
        context: dict[str, Any] | None,
    ) -> ChatResponse:
        """'Neden oyle?' cevabi — onceki sonucu acikla."""
        if not context:
            return ChatResponse(
                text="Onceki dogrulama sonucu bulunamadi. Yeniden dogrulama yapmami ister misiniz?",
                intent_type=intent.type.value,
                confidence=0.5,
                follow_up_suggestions=["Yeniden dogrula"],
            )

        claim = context.get("claim_text", intent.referenced_claim or "")
        verdict = context.get("verdict", "unknown")
        confidence = context.get("confidence", 0)
        response_text = context.get("cited_response", "")
        sources_count = context.get("sources_count", 0)

        lines = [f"**'{claim}' için hüküm gerekçesi:**", ""]

        verdict_display = (
            self.VERDICT_TR.get(verdict, str(verdict).replace("_", " ").title())
            if isinstance(verdict, str) and verdict not in ("unknown", "")
            else None
        )

        if response_text:
            lines.append(response_text)
        elif verdict_display:
            lines.append(f"Hüküm: **{verdict_display}** — güven seviyesi %{confidence * 100:.0f}.")
            lines.append(f"Bu sonuç {sources_count} kaynağın incelenmesiyle oluşturuldu.")
        else:
            lines.append(
                "Bu konuda henüz dosyalanmış bir hüküm yok. "
                "İddiayı yeniden soruşturmamı ister misiniz?"
            )
            return ChatResponse(
                text="\n".join(lines),
                intent_type=intent.type.value,
                confidence=0.5,
                follow_up_suggestions=["Yeniden soruştur"],
            )

        lines.append("")
        lines.append("**Kanit zinciri:**")

        # Kaynak detaylari
        steps = context.get("steps", [])
        for step in steps[:5]:
            name = step.get("name", "")
            status = step.get("status", "")
            if name and status == "done":
                lines.append(f"- {name}: Tamamlandi")

        text = "\n".join(lines)

        return ChatResponse(
            text=text,
            intent_type=intent.type.value,
            confidence=0.8,
            sources_cited=sources_count,
            follow_up_suggestions=[
                "Daha fazla kanit ara",
                "Celişkili kanitlari goster",
            ],
        )

    def _respond_follow_up_more(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        results: dict[str, Any] | None,
        context: dict[str, Any] | None,
    ) -> ChatResponse:
        """'Daha fazla kanit' cevabi."""
        if not results:
            return ChatResponse(
                text="Ek kanit bulunamadi. Farkli bir arama sorgusu deneyebilir misiniz?",
                intent_type=intent.type.value,
                confidence=0.4,
                follow_up_suggestions=["Farkli kelimelerle ara"],
            )

        total = results.get("total_sources", 0)
        external = results.get("external_results", [])
        health = results.get("health_org_results", [])

        lines = [f"**{total} ek kaynak** bulundu.", ""]

        if external:
            lines.append("**Akademik kaynaklar:**")
            for src in external[:5]:
                title = src.get("title", "Bilinmeyen")
                journal = src.get("journal", "")
                label = f"{title} ({journal})" if journal else title
                url = src.get("url") or ""
                if url.startswith(("http://", "https://")):
                    lines.append(f"- [{label}]({url})")
                else:
                    lines.append(f"- {label}")
            lines.append("")

        if health:
            lines.append("**Resmi kuruluşlar:**")
            for src in health[:4]:
                title = src.get("title", "Bilinmeyen")
                source = ORG_TR.get(src.get("source"), src.get("source", ""))
                label = f"{source}: {title}" if source and source not in title else title
                url = src.get("url") or ""
                if url.startswith(("http://", "https://")):
                    lines.append(f"- [{label}]({url})")
                else:
                    lines.append(f"- {label}")

        text = "\n".join(lines)

        return ChatResponse(
            text=text,
            intent_type=intent.type.value,
            confidence=0.7,
            sources_cited=total,
            follow_up_suggestions=[
                "Neden boyle sonuclandigini acikla",
                "Bu kanitlari karsilastir",
            ],
        )

    def _respond_follow_up_different(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        results: dict[str, Any] | None,
        context: dict[str, Any] | None,
    ) -> ChatResponse:
        """'Baska kaynak' cevabi."""
        return self._respond_follow_up_more(intent, sufficiency, results, context)

    def _respond_challenge_verdict(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        results: dict[str, Any] | None,
        context: dict[str, Any] | None,
    ) -> ChatResponse:
        """'Katilmiyorum' cevabi — celişkili kanitlari on planda."""
        if not results:
            return ChatResponse(
                text="Celişkili kanit arastirmasi yapildi ancak sonuc bulunamadi.",
                intent_type=intent.type.value,
                confidence=0.4,
                follow_up_suggestions=["Farkli bir bakis acisi dene"],
            )

        contradictions = results.get("contradictions", [])
        total = results.get("total_sources", 0)

        lines = ["**Itiraziniz degerlendirildi.**", ""]

        if contradictions:
            lines.append(f"**{len(contradictions)} celişkili kanit** bulundu:")
            lines.append("")
            for c in contradictions[:3]:
                title = c.get("title", "")
                text = c.get("text", "")[:200]
                if title:
                    lines.append(f"- **{title}**")
                if text:
                    lines.append(f"  > {text}...")
                lines.append("")
        else:
            lines.append("Celişkili kanit bulunamadi. Mevcut kanitlar tutarli.")
            lines.append("")

        lines.append(f"Toplam {total} kaynak incelendi.")

        text = "\n".join(lines)

        return ChatResponse(
            text=text,
            intent_type=intent.type.value,
            confidence=0.7,
            sources_cited=total,
            follow_up_suggestions=[
                "Daha detayli acikla",
                "Farkli kaynaklar kontrol et",
            ],
        )

    def _respond_clarify_context(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        results: dict[str, Any] | None,
        context: dict[str, Any] | None,
    ) -> ChatResponse:
        """'Aslinda su kastettim' cevabi."""
        return ChatResponse(
            text="Anladim, lutfen durumu netlestirin. Tam olarak neyi dogrulamami istiyorsunuz?",
            intent_type=intent.type.value,
            confidence=0.6,
            follow_up_suggestions=["Spesifik bir soru sor"],
        )

    def _respond_explore_topic(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        results: dict[str, Any] | None,
        context: dict[str, Any] | None,
    ) -> ChatResponse:
        """'Bu konuda ne biliyorsun?' cevabi."""
        topic = intent.topic.value
        lines = [
            f"**{topic.title()}** hakkinda bilinenler:",
            "",
            "Mevcut kaynaklarin ozeti:",
        ]

        if results:
            total = results.get("total_sources", 0)
            lines.append(f"- {total} kaynak incelendi")
        else:
            lines.append("- Bu konuda yeterli kaynak bulunamadi")

        lines.append("")
        lines.append("Belirli bir iddia dogrulamami ister misiniz?")

        text = "\n".join(lines)

        return ChatResponse(
            text=text,
            intent_type=intent.type.value,
            confidence=0.6,
            follow_up_suggestions=[
                "Bu konuda bir iddia dogrula",
                "Daha fazla kaynak bul",
            ],
        )

    def _respond_meta_question(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        results: dict[str, Any] | None,
        context: dict[str, Any] | None,
    ) -> ChatResponse:
        """Sistem hakkinda soru cevabi."""
        return ChatResponse(
            text=(
                "Arı Kaynak Evidence Engine, saglik iddialarini bilimsel kaynaklara karsi "
                "dogrulayan bir sistemdir. PubMed, Crossref, WHO, CDC gibi kaynaklari tarar "
                "ve kanit tabanli sonuclar uretir. LLM yalnizca yorumcu olarak kullanilir "
                "— kanit uretmez."
            ),
            intent_type=intent.type.value,
            confidence=0.9,
        )

    def _respond_default(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        results: dict[str, Any] | None,
        context: dict[str, Any] | None,
    ) -> ChatResponse:
        """Varsayilan cevap."""
        return ChatResponse(
            text="Sorunuzu anlayamadim. Lutfen daha spesifik bir soru sorun.",
            intent_type=intent.type.value,
            confidence=0.3,
            follow_up_suggestions=["Spesifik bir saglik iddiasi dogrula"],
        )

    def _build_insufficient_response(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
    ) -> ChatResponse:
        """Yetersiz kanit durumunda cevap."""
        return ChatResponse(
            text=(
                f"**'{intent.cleaned_query}'** için henüz yeterli kanıt toplayamadım.\n\n"
                "Bu, iddianın yanlış olduğu anlamına gelmez — şu an arşivimde ve "
                "erişebildiğim kaynaklarda bunu destekleyen ya da çürüten yeterli "
                "kanıt bulamadım. Hükmümü ancak kanıta dayanarak veririm.\n\n"
                "**Şunları deneyebilirsiniz:**\n"
                "- İddiayı farklı kelimelerle ifade edin\n"
                "- Daha spesifik bir alt iddiaya odaklanın\n"
                "- Arşivdeki benzer dosyalara göz atın"
            ),
            intent_type=intent.type.value,
            confidence=sufficiency.confidence,
            follow_up_suggestions=[
                "Farklı kelimelerle tekrar sor",
                "Arşivde benzer dosya var mı?",
            ],
        )

    def _rank_sources(self, results: dict[str, Any]) -> list[dict[str, Any]]:
        """Kaynaklari kaliteye gore sirala."""
        all_results = results.get("all_results", [])
        return sorted(
            all_results,
            key=lambda x: (
                x.get("quality_score", 0),
                1 if x.get("source_type") == "primary" else 0,
            ),
            reverse=True,
        )
