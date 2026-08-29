"""Dogal cevap uretme — kanitlari kullanici dostu formata cevirir.

Bu modul LLM kullanmaz. Tamamen kural tabanli:
- Intent'e gore format sec
- Kanitlari suni sirala
- Follow-up icin baglam sagla
- Dashboard icin uygun formatta dondur

NOT (2026-08-29): Kullanicinin canli bir ekran goruntusunde fark ettigi
karisik-dil deneyimi uzerine tum sabit sablon metinleri i18n.py'deki
cok-dilli katmana tasindi — her metod artik bir `language: str = "tr"`
parametresi alir. Arsiv/kanit icerigi (dinamik kisim, zaten dogru
sekilde ayri EN/TR makale dosyalarindan geliyor) bu degisiklikten
etkilenmez.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .i18n import DEFAULT_LANGUAGE, normalize_language, t
from .intent import Intent
from .sufficiency import SufficiencyLevel, SufficiencyResult

# Arama/ortusme kontrolunde anlamsiz genel kelimeler.
_CLAIM_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "does", "did", "are",
    "gerçekten", "hakında", "neden", "nedir", "mi", "mı", "mu", "mü",
    "bir", "gibi", "daha", "çok", "var", "yok", "yapar", "eder", "olur",
}

# Ajan adi -> kurum adi (yanitta okunur etiket). Cogu kisaltma dil-bagimsiz
# (WHO, CDC, FDA...); yalnizca "who" (DSÖ/WHO) dile gore degisir — bkz.
# i18n.py "org.who".
ORG_LABELS = {
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


def _org_label(source: str | None, language: str) -> str:
    if source == "who":
        return t("org.who", language)
    return ORG_LABELS.get(source or "", source or "")


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
        language: str = DEFAULT_LANGUAGE,
    ) -> ChatResponse:
        """Intent ve duruma gore cevap olustur."""
        language = normalize_language(language)
        method = getattr(self, f"_respond_{intent.type.value}", self._respond_default)
        return method(intent, sufficiency, investigation_results, previous_context, language)

    # ------------------------------------------------------------------
    # Sosyal niyetler — arastirma gerektirmez, dogrudan uzman yaniti.
    # ------------------------------------------------------------------

    def build_social(self, intent: Intent, language: str = DEFAULT_LANGUAGE) -> ChatResponse:
        """Selamlasma/kucuk konusma/identity icin hazir uzman yaniti."""
        language = normalize_language(language)
        method = getattr(self, f"_social_{intent.type.value}", None)
        if method is None:
            return self._social_greeting(intent, language)
        return method(intent, language)

    def _social_greeting(self, intent: Intent, language: str = DEFAULT_LANGUAGE) -> ChatResponse:
        return ChatResponse(
            text=t("social.greeting.text", language),
            intent_type=intent.type.value,
            confidence=1.0,
            follow_up_suggestions=[
                t("social.greeting.suggestion1", language),
                t("social.greeting.suggestion2", language),
                t("social.greeting.suggestion3", language),
            ],
        )

    def _social_smalltalk(self, intent: Intent, language: str = DEFAULT_LANGUAGE) -> ChatResponse:
        return ChatResponse(
            text=t("social.smalltalk.text", language),
            intent_type=intent.type.value,
            confidence=1.0,
            follow_up_suggestions=[
                t("social.smalltalk.suggestion1", language),
                t("social.smalltalk.suggestion2", language),
            ],
        )

    def _social_identity(self, intent: Intent, language: str = DEFAULT_LANGUAGE) -> ChatResponse:
        return ChatResponse(
            text=t("social.identity.text", language),
            intent_type=intent.type.value,
            confidence=1.0,
            follow_up_suggestions=[
                t("social.identity.suggestion1", language),
                t("social.identity.suggestion2", language),
            ],
        )

    def _unrecognized_claim(self, intent: Intent, language: str = DEFAULT_LANGUAGE) -> ChatResponse:
        """Mesaj bir saglik iddiasi olarak taninamadigi durum icin ayri yanit.

        NOT (2026-08-29): Bu durum eskiden _social_identity ile (gercek
        "sen kimsin?" sorularinin yaniti) AYNI metni paylasiyordu. Canli
        testle dogrulandi: anlamsiz bir girdi (ör. "asdkfjaslkdfj") veya
        yanlislikla yanlis siniflandirilmis bir mesaj, kullaniciya hicbir
        "anlayamadim" sinyali vermeden dogrudan "ben nasil calisiyorum"
        aciklamasina donuyordu — kafa karistirici. Bu, o iki durumu ayirir.
        """
        return ChatResponse(
            text=t("unrecognized.text", language, query=intent.original_query),
            intent_type=intent.type.value,
            confidence=0.3,
            follow_up_suggestions=[
                t("unrecognized.suggestion1", language),
                t("unrecognized.suggestion2", language),
            ],
        )

    def _social_thanks(self, intent: Intent, language: str = DEFAULT_LANGUAGE) -> ChatResponse:
        return ChatResponse(
            text=t("social.thanks.text", language),
            intent_type=intent.type.value,
            confidence=1.0,
            follow_up_suggestions=[
                t("social.thanks.suggestion1", language),
                t("social.thanks.suggestion2", language),
            ],
        )

    def _social_farewell(self, intent: Intent, language: str = DEFAULT_LANGUAGE) -> ChatResponse:
        return ChatResponse(
            text=t("social.farewell.text", language),
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
        language: str = DEFAULT_LANGUAGE,
    ) -> ChatResponse:
        """Yeni iddia dogrulama cevabi."""
        if not sufficiency.is_sufficient:
            return self._build_insufficient_response(intent, sufficiency, language)

        if not results:
            return ChatResponse(
                text=t("verify.no_results.text", language, query=intent.cleaned_query),
                intent_type=intent.type.value,
                confidence=0.3,
                follow_up_suggestions=[
                    t("verify.no_results.suggestion1", language),
                    t("verify.no_results.suggestion2", language),
                ],
            )

        archive = results.get("archive_results", []) or []
        total = results.get("total_sources", 0)
        best_archive = self._best_archive_match(archive, claim=intent.cleaned_query)

        lines = [f"**{intent.cleaned_query}**", ""]

        # --- Arsiv dosyasi: en degerli sonuc; link + kendi hukmu + pasaj ---
        if best_archive:
            lines.extend(self._format_archive_block(best_archive, language))
            lines.append("")

        # --- Hukum ---
        verdict = results.get("verdict") or "unverified"
        confidence = results.get("verdict_confidence") or 0
        archive_verdict = (best_archive or {}).get("verdict") or ""

        if verdict not in ("unverified", "") and confidence:
            verdict_key = f"verdict.{verdict}"
            verdict_display = t(verdict_key, language) if verdict_key in _VERDICT_KEYS else verdict.replace("_", " ").title()
            lines.append(t("verify.verdict_line", language, verdict=verdict_display, confidence=f"{confidence * 100:.0f}"))
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
                lines.append(t("verify.low_confidence_caveat", language))
            if results.get("verdict_conflict"):
                consensus = results.get("consensus") or {}
                parts = " · ".join(
                    f"{(t(f'verdict.{v}', language) if f'verdict.{v}' in _VERDICT_KEYS else v)}: %{int(round(100 * s / max(sum(consensus.values()), 1)))}"
                    for v, s in sorted(consensus.items(), key=lambda kv: -kv[1])
                    if s > 0
                )
                lines.append(t("verify.consensus_conflict", language, parts=parts))
        elif archive_verdict:
            lines.append(t("verify.archive_verdict_only", language, verdict=archive_verdict))
        else:
            lines.append(t("verify.no_verdict", language))
        lines.append("")

        if total > 0:
            breakdown = []
            if archive:
                breakdown.append(t("verify.breakdown.archive", language, n=len(archive)))
            orgs_all = results.get("health_org_results", []) or []
            external_all = results.get("external_results", []) or []
            if external_all:
                breakdown.append(t("verify.breakdown.academic", language, n=len(external_all)))
            if orgs_all:
                breakdown.append(t("verify.breakdown.official", language, n=len(orgs_all)))
            detail = f" ({', '.join(breakdown)})" if breakdown else ""
            lines.append(t("verify.sources_examined", language, total=total, detail=detail))
            lines.append("")

        # --- Resmi kuruluslar (max 4, linkli) ---
        orgs = (results.get("health_org_results", []) or [])[:4]
        if orgs:
            lines.append(t("verify.official_sources_header", language))
            for src in orgs:
                title = (src.get("title") or t("verify.default_org_record", language)).strip()
                url = src.get("url") or ""
                org_name = src.get("organization") or _org_label(src.get("source"), language)
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
            lines.append(t("verify.academic_sources_header", language))
            for i, src in enumerate(external, 1):
                title = (src.get("title") or t("verify.default_unknown_title", language)).strip()
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
            lines.append(t("verify.contradictions_found", language, n=len(contradictions)))
            lines.append("")

        text = "\n".join(lines)

        return ChatResponse(
            text=text,
            intent_type=intent.type.value,
            confidence=intent.confidence,
            sources_cited=total,
            follow_up_suggestions=self._claim_followups(best_archive, language),
        )

    def _best_archive_match(self, archive: list[dict[str, Any]], claim: str = "") -> dict[str, Any] | None:
        """Arsiv sonuclarindan gercekten ilgili dosyayi sec.

        Sadece distance'a bakmak alakasiz dosyalari one cikarabilir; bu yuzden
        iddiadaki icerik tokenlarinin baslik/pasajda ortusmesi sarttir.
        """
        claim_tokens = {
            tok for tok in re.findall(r"[a-zçğıöşü0-9]{3,}", (claim or "").lower())
            if tok not in _CLAIM_STOPWORDS
        }
        candidates = []
        for r in archive:
            if not isinstance(r, dict) or not (r.get("title") or r.get("url")):
                continue
            haystack = f"{r.get('title') or ''} {r.get('passage') or ''}".lower()
            hay_tokens = set(re.findall(r"[a-zçğıöşü0-9]{3,}", haystack))
            hits = sum(1 for tok in claim_tokens if self._token_hit(tok, hay_tokens))
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

    def _format_archive_block(self, src: dict[str, Any], language: str = DEFAULT_LANGUAGE) -> list[str]:
        """Arsiv dosyasini link + hukum + pasaj olarak formatla."""
        title = (src.get("title") or t("archive_block.default_title", language)).replace(" — Arı Kaynak", "")
        url = src.get("url") or ""
        verdict_tr = src.get("verdict") or ""
        rating = src.get("rating_value")
        passage = (src.get("passage") or "").strip()

        out = [t("archive_block.header", language)]
        if url.startswith(("http://", "https://")):
            out.append(f"[{title}]({url})")
        else:
            out.append(title)

        if verdict_tr:
            stars = ""
            if isinstance(rating, int) and 0 <= rating <= 5:
                stars = f" {'●' * rating}{'○' * (5 - rating)}"
            out.append(t("archive_block.stamp", language, verdict=verdict_tr, stars=stars))

        if passage:
            cut = passage[:200].rsplit(" ", 1)[0]
            out.append(f"> {cut}…")
        return out

    def _claim_followups(self, best_archive: dict[str, Any] | None, language: str = DEFAULT_LANGUAGE) -> list[str]:
        """Iddia cevabina ozel takip onerileri."""
        suggestions = []
        if best_archive and best_archive.get("url"):
            suggestions.append(t("followup.open_full_article", language))
        suggestions.extend([
            t("followup.explain_why", language),
            t("followup.search_more_evidence", language),
        ])
        return suggestions

    def _respond_follow_up_why(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        results: dict[str, Any] | None,
        context: dict[str, Any] | None,
        language: str = DEFAULT_LANGUAGE,
    ) -> ChatResponse:
        """'Neden oyle?' cevabi — onceki sonucu acikla."""
        if not context:
            return ChatResponse(
                text=t("why.no_context", language),
                intent_type=intent.type.value,
                confidence=0.5,
                follow_up_suggestions=[t("why.reverify", language)],
            )

        claim = context.get("claim_text", intent.referenced_claim or "")
        verdict = context.get("verdict", "unknown")
        confidence = context.get("confidence", 0)
        response_text = context.get("cited_response", "")
        sources_count = context.get("sources_count", 0)

        lines = [t("why.reasoning_header", language, claim=claim), ""]

        verdict_display = None
        if isinstance(verdict, str) and verdict not in ("unknown", ""):
            key = f"verdict.{verdict}"
            verdict_display = t(key, language) if key in _VERDICT_KEYS else str(verdict).replace("_", " ").title()

        if response_text:
            lines.append(response_text)
        elif verdict_display:
            lines.append(t("why.verdict_with_confidence", language, verdict=verdict_display, confidence=f"{confidence * 100:.0f}"))
            lines.append(t("why.sources_basis", language, n=sources_count))
        else:
            lines.append(t("why.no_filed_verdict", language))
            return ChatResponse(
                text="\n".join(lines),
                intent_type=intent.type.value,
                confidence=0.5,
                follow_up_suggestions=[t("why.reinvestigate", language)],
            )

        lines.append("")
        lines.append(t("why.evidence_chain_header", language))

        # Kaynak detaylari
        steps = context.get("steps", [])
        for step in steps[:5]:
            name = step.get("name", "")
            status = step.get("status", "")
            if name and status == "done":
                lines.append(f"- {t('why.step_done', language, name=name)}")

        text = "\n".join(lines)

        return ChatResponse(
            text=text,
            intent_type=intent.type.value,
            confidence=0.8,
            sources_cited=sources_count,
            follow_up_suggestions=[
                t("why.suggestion_more_evidence", language),
                t("why.suggestion_show_contradictions", language),
            ],
        )

    def _respond_follow_up_more(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        results: dict[str, Any] | None,
        context: dict[str, Any] | None,
        language: str = DEFAULT_LANGUAGE,
    ) -> ChatResponse:
        """'Daha fazla kanit' cevabi."""
        if not results:
            return ChatResponse(
                text=t("more.no_evidence", language),
                intent_type=intent.type.value,
                confidence=0.4,
                follow_up_suggestions=[t("more.try_different_words", language)],
            )

        total = results.get("total_sources", 0)
        external = results.get("external_results", [])
        health = results.get("health_org_results", [])

        lines = [t("more.additional_sources_found", language, n=total), ""]

        if external:
            lines.append(t("verify.academic_sources_header", language))
            for src in external[:5]:
                title = src.get("title", t("verify.default_unknown_title", language))
                journal = src.get("journal", "")
                label = f"{title} ({journal})" if journal else title
                url = src.get("url") or ""
                if url.startswith(("http://", "https://")):
                    lines.append(f"- [{label}]({url})")
                else:
                    lines.append(f"- {label}")
            lines.append("")

        if health:
            lines.append(t("more.official_bodies_header", language))
            for src in health[:4]:
                title = src.get("title", t("verify.default_unknown_title", language))
                source = _org_label(src.get("source"), language)
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
                t("more.suggestion_explain_why", language),
                t("more.suggestion_compare", language),
            ],
        )

    def _respond_follow_up_different(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        results: dict[str, Any] | None,
        context: dict[str, Any] | None,
        language: str = DEFAULT_LANGUAGE,
    ) -> ChatResponse:
        """'Baska kaynak' cevabi."""
        return self._respond_follow_up_more(intent, sufficiency, results, context, language)

    def _respond_challenge_verdict(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        results: dict[str, Any] | None,
        context: dict[str, Any] | None,
        language: str = DEFAULT_LANGUAGE,
    ) -> ChatResponse:
        """'Katilmiyorum' cevabi — celişkili kanitlari on planda."""
        if not results:
            return ChatResponse(
                text=t("challenge.no_results", language),
                intent_type=intent.type.value,
                confidence=0.4,
                follow_up_suggestions=[t("challenge.try_different_angle", language)],
            )

        contradictions = results.get("contradictions", [])
        total = results.get("total_sources", 0)

        lines = [t("challenge.considered_header", language), ""]

        if contradictions:
            lines.append(t("challenge.contradictions_found", language, n=len(contradictions)))
            lines.append("")
            for c in contradictions[:3]:
                title = c.get("title", "")
                excerpt = c.get("text", "")[:200]
                if title:
                    lines.append(f"- **{title}**")
                if excerpt:
                    lines.append(f"  > {excerpt}...")
                lines.append("")
        else:
            lines.append(t("challenge.no_contradictions", language))
            lines.append("")

        lines.append(t("challenge.total_examined", language, n=total))

        text = "\n".join(lines)

        return ChatResponse(
            text=text,
            intent_type=intent.type.value,
            confidence=0.7,
            sources_cited=total,
            follow_up_suggestions=[
                t("challenge.suggestion_more_detail", language),
                t("challenge.suggestion_check_different", language),
            ],
        )

    def _respond_clarify_context(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        results: dict[str, Any] | None,
        context: dict[str, Any] | None,
        language: str = DEFAULT_LANGUAGE,
    ) -> ChatResponse:
        """'Aslinda su kastettim' cevabi."""
        return ChatResponse(
            text=t("clarify.text", language),
            intent_type=intent.type.value,
            confidence=0.6,
            follow_up_suggestions=[t("clarify.suggestion", language)],
        )

    def _respond_explore_topic(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        results: dict[str, Any] | None,
        context: dict[str, Any] | None,
        language: str = DEFAULT_LANGUAGE,
    ) -> ChatResponse:
        """'Bu konuda ne biliyorsun?' cevabi."""
        topic = intent.topic.value
        lines = [
            t("explore.header", language, topic=topic.title()),
            "",
            t("explore.summary_intro", language),
        ]

        if results:
            total = results.get("total_sources", 0)
            lines.append(t("explore.sources_examined", language, n=total))
        else:
            lines.append(t("explore.no_sources", language))

        lines.append("")
        lines.append(t("explore.ask_verify", language))

        text = "\n".join(lines)

        return ChatResponse(
            text=text,
            intent_type=intent.type.value,
            confidence=0.6,
            follow_up_suggestions=[
                t("explore.suggestion_verify", language),
                t("explore.suggestion_more_sources", language),
            ],
        )

    def _respond_meta_question(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        results: dict[str, Any] | None,
        context: dict[str, Any] | None,
        language: str = DEFAULT_LANGUAGE,
    ) -> ChatResponse:
        """Sistem hakkinda soru cevabi."""
        return ChatResponse(
            text=t("meta.text", language),
            intent_type=intent.type.value,
            confidence=0.9,
        )

    def _respond_default(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        results: dict[str, Any] | None,
        context: dict[str, Any] | None,
        language: str = DEFAULT_LANGUAGE,
    ) -> ChatResponse:
        """Varsayilan cevap."""
        return ChatResponse(
            text=t("default.text", language),
            intent_type=intent.type.value,
            confidence=0.3,
            follow_up_suggestions=[t("default.suggestion", language)],
        )

    def _build_insufficient_response(
        self,
        intent: Intent,
        sufficiency: SufficiencyResult,
        language: str = DEFAULT_LANGUAGE,
    ) -> ChatResponse:
        """Yetersiz kanit durumunda cevap."""
        return ChatResponse(
            text=t("insufficient.text", language, query=intent.cleaned_query),
            intent_type=intent.type.value,
            confidence=sufficiency.confidence,
            follow_up_suggestions=[
                t("insufficient.suggestion_rephrase", language),
                t("insufficient.suggestion_browse", language),
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


_VERDICT_KEYS = {
    "verdict.supported", "verdict.mostly_supported", "verdict.partly_supported",
    "verdict.misleading", "verdict.unsupported", "verdict.unverified",
}
