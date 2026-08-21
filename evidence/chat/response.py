"""Dogal cevap uretme — kanitlari kullanici dostu formata cevirir.

Bu modul LLM kullanmaz. Tamamen kural tabanli:
- Intent'e gore format sec
- Kanitlari suni sirala
- Follow-up icin baglam sagla
- Dashboard icin uygun formatta dondur
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .intent import Intent, IntentType, Topic
from .sufficiency import SufficiencyLevel, SufficiencyResult


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
                "Merhaba! Ben **Arı Kaynak Soruşturucusu** — sağlık iddialarını kanıtına inen bir yapay zekâ araştırmacısıyım.\n\n"
                "Bana şüphelendiğiniz herhangi bir sağlık iddiası yazın; şöyle çalışırım:\n"
                "1. Önce kendi doğrulanmış makale arşivimde tararım\n"
                "2. Sonra PubMed, Cochrane, WHO gibi harici tıbbi kaynakları yoklarım\n"
                "3. Çelişkili kanıtları ayıklar, hükmümü damga basarak bildiririm\n\n"
                "Örnek: *\"Kahve kolesterolü yükseltir mi?\"* ya da *\"Günlük aspirin kalp krizinden korur mu?\"*"
            ),
            intent_type=intent.type.value,
            confidence=1.0,
            follow_up_suggestions=[
                "Kahve kolesterolü yükseltir mi?",
                "Kreatin böbreğe zarar verir mi?",
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
                "**Yöntemim:** İddianızı alırım → yerel makale arşivimi ve 19 harici tıbbi kaynağı (PubMed, Cochrane, WHO, NEJM, TÜSEB...) tararım → "
                "kanıtları çapraz kontrol ederim → hükmümü güven skoruyla bildiririm.\n\n"
                "Hükmem yetersiz kanıtla asla kesinleşmez; o zaman açıkça *\"doğrulanamadı\"* derim."
            ),
            intent_type=intent.type.value,
            confidence=1.0,
            follow_up_suggestions=[
                "Hangi kaynakları kullanıyorsun?",
                "Bir iddia soruşturalım",
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

        # Kaynaklari sirala
        sources = self._rank_sources(results)

        lines = [f"**{intent.cleaned_query}**", ""]

        # Verdict ozeti
        verdict = results.get("verdict") or "unverified"
        confidence = results.get("verdict_confidence") or 0
        verdict_display = verdict.replace("_", " ").title()

        lines.append(f"**Hukum:** {verdict_display} (Guven: %{confidence:.0f})")
        lines.append("")

        # Kanit ozeti
        total = results.get("total_sources", 0)
        if total > 0:
            lines.append(f"**{total} kaynak** incelendi.")
            lines.append("")

        # En onemli kaynaklar (max 3)
        external = results.get("external_results", [])[:3]
        if external:
            lines.append("**Onemli kaynaklar:**")
            for i, src in enumerate(external, 1):
                title = src.get("title", "Bilinmeyen")
                journal = src.get("journal", "")
                year = src.get("published_year", "")
                source_str = f"{title}"
                if journal:
                    source_str += f" ({journal}"
                    if year:
                        source_str += f", {year}"
                    source_str += ")"
                lines.append(f"{i}. {source_str}")
            lines.append("")

        # Celişkiler
        contradictions = results.get("contradictions", [])
        if contradictions:
            lines.append(f"**{len(contradictions)} celişkili kanit** tespit edildi.")
            lines.append("")

        text = "\n".join(lines)

        return ChatResponse(
            text=text,
            intent_type=intent.type.value,
            confidence=intent.confidence,
            sources_cited=total,
            follow_up_suggestions=[
                "Neden boyle sonuclandigini acikla",
                "Daha fazla kanit ara",
                "Farkli kaynaklardan kontrol et",
            ],
        )

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

        verdict_display = verdict.replace("_", " ") if isinstance(verdict, str) and verdict != "unknown" else None

        if response_text:
            lines.append(response_text)
        elif verdict_display:
            lines.append(f"Hüküm: **{verdict_display}** — güven seviyesi %{confidence:.0f}.")
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
                if journal:
                    lines.append(f"- {title} ({journal})")
                else:
                    lines.append(f"- {title}")
            lines.append("")

        if health:
            lines.append("**Saglik kuruluslari:**")
            for src in health[:3]:
                title = src.get("title", "Bilinmeyen")
                source = src.get("source", "")
                lines.append(f"- {title} ({source})")

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
