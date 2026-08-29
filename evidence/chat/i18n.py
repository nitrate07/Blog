"""Çok dilli metin katmanı (i18n) — response.py'nin sabit şablon metinleri için.

NOT (2026-08-29): Kullanıcının canlı bir ekran görüntüsünde fark ettiği
karışık-dil deneyimi üzerine eklendi: backend'in TÜM sabit metinleri
(hüküm etiketleri, öneri düğmeleri, durum mesajları) hardcoded Türkçe'ydi
— EVIDENCE_LANGUAGE config değeri hiçbir yerde okunmuyordu, hangi
sayfadan (ask.html EN / tr/ask.html TR) istek geldiğine bakılmıyordu.

Bu modül cevap üretiminin DEĞİŞKEN kısmını (arşiv metni, kanıt pasajları
— zaten doğru şekilde ayrı EN/TR makale dosyalarından geliyor) DEĞİL,
SABİT ŞABLON metinlerini (hüküm etiketleri, öneri metinleri, durum
satırları) kapsar.
"""

from __future__ import annotations

SUPPORTED_LANGUAGES = ("tr", "en")
DEFAULT_LANGUAGE = "tr"


def normalize_language(language: str | None) -> str:
    """Desteklenmeyen/None bir dil kodu gelirse güvenli varsayılana düşer."""
    if language and language.lower() in SUPPORTED_LANGUAGES:
        return language.lower()
    return DEFAULT_LANGUAGE


_T: dict[str, dict[str, str]] = {
    # --- Hüküm etiketleri (VERDICT_TR'nin yerini alır) ---
    "verdict.supported": {"tr": "Destekleniyor", "en": "Supported"},
    "verdict.mostly_supported": {"tr": "Büyük Ölçüde Destekleniyor", "en": "Largely Supported"},
    "verdict.partly_supported": {"tr": "Kısmen Destekleniyor", "en": "Partly Supported"},
    "verdict.misleading": {"tr": "Yanıltıcı", "en": "Misleading"},
    "verdict.unsupported": {"tr": "Desteklenmiyor", "en": "Unsupported"},
    "verdict.unverified": {"tr": "Doğrulanamadı", "en": "Unverified"},

    # --- Kurum etiketleri (yalnizca kisaltma disinda cevrilenler) ---
    "org.who": {"tr": "DSÖ (WHO)", "en": "WHO"},

    # --- Sosyal: selamlama ---
    "social.greeting.text": {
        "tr": (
            "Merhaba! Nasıl yardımcı olabilirim?\n\n"
            "Ben **Arı Kaynak Soruşturucusu**yüm — sağlık iddialarını kanıtına inen bir yapay zekâ araştırmacısı.\n\n"
            "**İddianız nedir? Hemen sorgulayalım.**\n"
            "Şüphelendiğiniz herhangi bir sağlık iddiasını yazın; önce kendi doğrulanmış arşivimi,\n"
            "sonra PubMed, Cochrane ve resmi sağlık kuruluşlarını (DSÖ, CDC, TÜSEB...) tarar,\n"
            "kanıtları çapraz kontrol edip hükmümü kaynaklarıyla birlikte bildiririm."
        ),
        "en": (
            "Hello! How can I help?\n\n"
            "I'm the **Arı Kaynak Investigator** — an AI researcher that traces health claims back to the evidence.\n\n"
            "**What's your claim? Let's check it now.**\n"
            "Write any health claim you're suspicious of; I'll search my own verified archive first,\n"
            "then PubMed, Cochrane, and official health bodies (WHO, CDC, TÜSEB...),\n"
            "cross-check the evidence, and report my verdict with sources."
        ),
    },
    "social.greeting.suggestion1": {"tr": "Kahve kolesterolü yükseltir mi?", "en": "Does coffee raise cholesterol?"},
    "social.greeting.suggestion2": {"tr": "Günlük aspirin kalp krizinden korur mu?", "en": "Does daily aspirin prevent heart attacks?"},
    "social.greeting.suggestion3": {"tr": "Nasıl çalışıyorsun?", "en": "How do you work?"},

    # --- Sosyal: kucuk konusma ---
    "social.smalltalk.text": {
        "tr": (
            "İyiyim, teşekkür ederim — dosya başında bekliyorum. 😊\n\n"
            "Asıl uzmanlık alanım sağlık iddialarını kanıtlarıyla sorgulamak. "
            "Duyduğunuz bir iddia varsa yazın, hemen soruşturmaya açalım."
        ),
        "en": (
            "I'm well, thank you — sitting at my desk. 😊\n\n"
            "My real specialty is checking health claims against the evidence. "
            "If you've heard a claim, write it and let's investigate it right away."
        ),
    },
    "social.smalltalk.suggestion1": {"tr": "Vitamin D eksikliği kemiklere zarar verir mi?", "en": "Does vitamin D deficiency harm bones?"},
    "social.smalltalk.suggestion2": {"tr": "10.000 adım gerçekten gerekli mi?", "en": "Are 10,000 steps really necessary?"},

    # --- Sosyal: kimlik ---
    "social.identity.text": {
        "tr": (
            "Ben **Arı Kaynak Soruşturucusu**yum — viral sağlık iddialarını birincil bilimsel kaynaklara kadar takip eden bir yapay zekâ.\n\n"
            "**Yöntemim:** İddianızı alırım → yerel makale arşivimi ve 20 harici tıbbi kaynağı (PubMed, Europe PMC, Cochrane, DSÖ, CDC, TÜSEB...) tararım → "
            "kanıtları çapraz kontrol ederim → hükmümü güven skoruyla bildiririm.\n\n"
            "Hükmüm yetersiz kanıtla asla kesinleşmez; o zaman açıkça *\"doğrulanamadı\"* derim."
        ),
        "en": (
            "I'm the **Arı Kaynak Investigator** — an AI that traces viral health claims back to primary scientific sources.\n\n"
            "**My method:** I take your claim → search my local article archive and 20 external medical sources (PubMed, Europe PMC, Cochrane, WHO, CDC, TÜSEB...) → "
            "cross-check the evidence → report my verdict with a confidence score.\n\n"
            "My verdict is never confident with insufficient evidence; in that case I clearly say *\"unverified\"*."
        ),
    },
    "social.identity.suggestion1": {"tr": "Hangi kaynakları kullanıyorsun?", "en": "Which sources do you use?"},
    "social.identity.suggestion2": {"tr": "Bir iddia soruşturalım", "en": "Let's investigate a claim"},

    # --- Tanınmayan iddia ---
    "unrecognized.text": {
        "tr": (
            "'{query}' mesajınızı belirli bir sağlık iddiası olarak tanıyamadım.\n\n"
            "Bir sağlık/tıp iddiasını (ör. \"kahve kolesterolü yükseltir mi?\") doğrudan yazarsanız "
            "hemen araştırmaya başlarım."
        ),
        "en": (
            "I couldn't recognize '{query}' as a specific health claim.\n\n"
            "If you write a health/medical claim directly (e.g. \"does coffee raise cholesterol?\"), "
            "I'll start researching right away."
        ),
    },
    "unrecognized.suggestion1": {"tr": "Bir iddia yaz, hemen araştırayım", "en": "Write a claim and I'll research it now"},
    "unrecognized.suggestion2": {"tr": "Nasıl çalıştığımı anlat", "en": "Explain how you work"},

    # --- Sosyal: tesekkur ---
    "social.thanks.text": {
        "tr": (
            "Rica ederim! Dosyanız her zaman açık.\n\n"
            "Aklınıza takılan başka bir sağlık iddiası olursa yazmanız yeterli."
        ),
        "en": (
            "You're welcome! Your file stays open.\n\n"
            "If another health claim crosses your mind, just write it."
        ),
    },
    "social.thanks.suggestion1": {"tr": "Başka bir iddia soruştur", "en": "Investigate another claim"},
    "social.thanks.suggestion2": {"tr": "Arşivdeki popüler dosyaları göster", "en": "Show popular files in the archive"},

    # --- Sosyal: veda ---
    "social.farewell.text": {
        "tr": "Hoşça kalın! Arşiv her gün büyüyor — yeni bir iddiayla geri geldiğinizde kapımız açık.",
        "en": "Goodbye! The archive grows every day — our door is open when you come back with a new claim.",
    },

    # --- verify_claim: kanit bulunamadi (results tamamen bos) ---
    "verify.no_results.text": {
        "tr": "'{query}' icin kanit bulunamadi. Daha spesifik bir soru sorabilir misiniz?",
        "en": "No evidence found for '{query}'. Could you ask a more specific question?",
    },
    "verify.no_results.suggestion1": {"tr": "Daha spesifik bir soru sor", "en": "Ask a more specific question"},
    "verify.no_results.suggestion2": {"tr": "Farkli kelimelerle ifade et", "en": "Phrase it with different words"},

    # --- verify_claim: hukum satiri ---
    "verify.verdict_line": {"tr": "**Hüküm:** {verdict} (güven %{confidence})", "en": "**Verdict:** {verdict} (confidence {confidence}%)"},
    "verify.low_confidence_caveat": {
        "tr": (
            "⚠️ Bu hüküm arşivdeki hiçbir makaleyle güçlü bir doğrudan "
            "örtüşme bulamadı — aşağıdaki kaynaklar yalnızca kısmen "
            "ilgili olabilir, düşük güvenle değerlendirin."
        ),
        "en": (
            "⚠️ This verdict didn't find a strong, direct match with any archive "
            "article — the sources below may only be partially relevant, "
            "treat with low confidence."
        ),
    },
    "verify.consensus_conflict": {
        "tr": "⚠ **Ajan uzlaşısı:** Kaynaklar farklı yönlere işaret ediyor ({parts}). İki sinyali de değerlendirin.",
        "en": "⚠ **Source consensus:** Sources point in different directions ({parts}). Weigh both signals.",
    },
    "verify.archive_verdict_only": {
        "tr": (
            "**Hüküm:** Arşivimizdeki eşleşen dosya bu iddiayı "
            "**\"{verdict}\"** olarak damgalamış. "
            "Aşağıdaki dosyadan kanıt zincirini inceleyebilirsiniz."
        ),
        "en": (
            "**Verdict:** The matching file in our archive stamped this claim as "
            "**\"{verdict}\"**. "
            "You can review the evidence chain in the file below."
        ),
    },
    "verify.no_verdict": {
        "tr": "**Hüküm:** Doğrulanamadı — henüz yeterli kanıt zinciri kurulamadı.",
        "en": "**Verdict:** Unverified — not enough of an evidence chain has been established yet.",
    },
    "verify.sources_examined": {"tr": "**{total} kaynak** incelendi{detail}.", "en": "**{total} sources** examined{detail}."},
    "verify.breakdown.archive": {"tr": "{n} arşiv", "en": "{n} archive"},
    "verify.breakdown.academic": {"tr": "{n} akademik", "en": "{n} academic"},
    "verify.breakdown.official": {"tr": "{n} resmi kurum", "en": "{n} official body"},
    "verify.official_sources_header": {"tr": "**Resmi kuruluş kaynakları:**", "en": "**Official body sources:**"},
    "verify.default_org_record": {"tr": "Kurum kaydı", "en": "Institutional record"},
    "verify.academic_sources_header": {"tr": "**Akademik kaynaklar:**", "en": "**Academic sources:**"},
    "verify.default_unknown_title": {"tr": "Bilinmeyen", "en": "Unknown"},
    "verify.contradictions_found": {
        "tr": "⚠️ **{n} çelişkili kanıt** tespit edildi — hüküm dikkatle okuyun.",
        "en": "⚠️ **{n} contradicting piece(s) of evidence** found — read the verdict carefully.",
    },

    # --- Arsiv blogu ---
    "archive_block.header": {"tr": "📁 **Arşivimizdeki dosya:**", "en": "📁 **File from our archive:**"},
    "archive_block.default_title": {"tr": "Arşiv dosyası", "en": "Archive file"},
    "archive_block.stamp": {"tr": "Damga: **{verdict}**{stars}", "en": "Stamp: **{verdict}**{stars}"},

    # --- Iddia takip onerileri ---
    "followup.open_full_article": {"tr": "Bu dosyanın tam makalesini aç", "en": "Open the full article for this file"},
    "followup.explain_why": {"tr": "Neden böyle sonuçlandığını açıkla", "en": "Explain why it concluded this way"},
    "followup.search_more_evidence": {"tr": "Daha fazla kanıt ara", "en": "Search for more evidence"},

    # --- follow_up_why ---
    "why.no_context": {
        "tr": "Onceki dogrulama sonucu bulunamadi. Yeniden dogrulama yapmami ister misiniz?",
        "en": "No previous verification result found. Would you like me to verify it again?",
    },
    "why.reverify": {"tr": "Yeniden dogrula", "en": "Verify again"},
    "why.reasoning_header": {"tr": "**'{claim}' için hüküm gerekçesi:**", "en": "**Reasoning for the verdict on '{claim}':**"},
    "why.verdict_with_confidence": {
        "tr": "Hüküm: **{verdict}** — güven seviyesi %{confidence}.",
        "en": "Verdict: **{verdict}** — confidence level {confidence}%.",
    },
    "why.sources_basis": {"tr": "Bu sonuç {n} kaynağın incelenmesiyle oluşturuldu.", "en": "This result was formed by examining {n} sources."},
    "why.no_filed_verdict": {
        "tr": "Bu konuda henüz dosyalanmış bir hüküm yok. İddiayı yeniden soruşturmamı ister misiniz?",
        "en": "There's no filed verdict on this yet. Would you like me to investigate the claim again?",
    },
    "why.reinvestigate": {"tr": "Yeniden soruştur", "en": "Investigate again"},
    "why.evidence_chain_header": {"tr": "**Kanit zinciri:**", "en": "**Evidence chain:**"},
    "why.step_done": {"tr": "{name}: Tamamlandi", "en": "{name}: Done"},
    "why.suggestion_more_evidence": {"tr": "Daha fazla kanit ara", "en": "Search for more evidence"},
    "why.suggestion_show_contradictions": {"tr": "Celişkili kanitlari goster", "en": "Show contradicting evidence"},

    # --- follow_up_more ---
    "more.no_evidence": {
        "tr": "Ek kanit bulunamadi. Farkli bir arama sorgusu deneyebilir misiniz?",
        "en": "No additional evidence found. Could you try a different search query?",
    },
    "more.try_different_words": {"tr": "Farkli kelimelerle ara", "en": "Search with different words"},
    "more.additional_sources_found": {"tr": "**{n} ek kaynak** bulundu.", "en": "**{n} additional source(s)** found."},
    "more.official_bodies_header": {"tr": "**Resmi kuruluşlar:**", "en": "**Official bodies:**"},
    "more.suggestion_explain_why": {"tr": "Neden boyle sonuclandigini acikla", "en": "Explain why it concluded this way"},
    "more.suggestion_compare": {"tr": "Bu kanitlari karsilastir", "en": "Compare this evidence"},

    # --- challenge_verdict ---
    "challenge.no_results": {
        "tr": "Celişkili kanit arastirmasi yapildi ancak sonuc bulunamadi.",
        "en": "A search for contradicting evidence was run but found no results.",
    },
    "challenge.try_different_angle": {"tr": "Farkli bir bakis acisi dene", "en": "Try a different angle"},
    "challenge.considered_header": {"tr": "**Itiraziniz degerlendirildi.**", "en": "**Your objection was considered.**"},
    "challenge.contradictions_found": {"tr": "**{n} celişkili kanit** bulundu:", "en": "**{n} contradicting piece(s) of evidence** found:"},
    "challenge.no_contradictions": {
        "tr": "Celişkili kanit bulunamadi. Mevcut kanitlar tutarli.",
        "en": "No contradicting evidence found. The available evidence is consistent.",
    },
    "challenge.total_examined": {"tr": "Toplam {n} kaynak incelendi.", "en": "A total of {n} sources were examined."},
    "challenge.suggestion_more_detail": {"tr": "Daha detayli acikla", "en": "Explain in more detail"},
    "challenge.suggestion_check_different": {"tr": "Farkli kaynaklar kontrol et", "en": "Check different sources"},

    # --- clarify_context ---
    "clarify.text": {
        "tr": "Anladim, lutfen durumu netlestirin. Tam olarak neyi dogrulamami istiyorsunuz?",
        "en": "I understand, please clarify. What exactly would you like me to verify?",
    },
    "clarify.suggestion": {"tr": "Spesifik bir soru sor", "en": "Ask a specific question"},

    # --- explore_topic ---
    "explore.header": {"tr": "**{topic}** hakkinda bilinenler:", "en": "**What's known about {topic}:**"},
    "explore.summary_intro": {"tr": "Mevcut kaynaklarin ozeti:", "en": "Summary of available sources:"},
    "explore.sources_examined": {"tr": "- {n} kaynak incelendi", "en": "- {n} sources examined"},
    "explore.no_sources": {"tr": "- Bu konuda yeterli kaynak bulunamadi", "en": "- Not enough sources found on this topic"},
    "explore.ask_verify": {"tr": "Belirli bir iddia dogrulamami ister misiniz?", "en": "Would you like me to verify a specific claim?"},
    "explore.suggestion_verify": {"tr": "Bu konuda bir iddia dogrula", "en": "Verify a claim on this topic"},
    "explore.suggestion_more_sources": {"tr": "Daha fazla kaynak bul", "en": "Find more sources"},

    # --- meta_question ---
    "meta.text": {
        "tr": (
            "Arı Kaynak Evidence Engine, saglik iddialarini bilimsel kaynaklara karsi "
            "dogrulayan bir sistemdir. PubMed, Crossref, WHO, CDC gibi kaynaklari tarar "
            "ve kanit tabanli sonuclar uretir. LLM yalnizca yorumcu olarak kullanilir "
            "— kanit uretmez."
        ),
        "en": (
            "Arı Kaynak Evidence Engine is a system that verifies health claims against "
            "scientific sources. It searches sources like PubMed, Crossref, WHO, and CDC "
            "and produces evidence-based results. The LLM is only used as an interpreter "
            "— it never generates evidence."
        ),
    },

    # --- default ---
    "default.text": {
        "tr": "Sorunuzu anlayamadim. Lutfen daha spesifik bir soru sorun.",
        "en": "I didn't understand your question. Please ask a more specific question.",
    },
    "default.suggestion": {"tr": "Spesifik bir saglik iddiasi dogrula", "en": "Verify a specific health claim"},

    # --- SSE akis durum etiketi ---
    "stream.researching_sources": {"tr": "Kaynaklar araştırılıyor", "en": "Researching sources"},

    # --- yetersiz kanit ---
    "insufficient.text": {
        "tr": (
            "**'{query}'** için henüz yeterli kanıt toplayamadım.\n\n"
            "Bu, iddianın yanlış olduğu anlamına gelmez — şu an arşivimde ve "
            "erişebildiğim kaynaklarda bunu destekleyen ya da çürüten yeterli "
            "kanıt bulamadım. Hükmümü ancak kanıta dayanarak veririm.\n\n"
            "**Şunları deneyebilirsiniz:**\n"
            "- İddiayı farklı kelimelerle ifade edin\n"
            "- Daha spesifik bir alt iddiaya odaklanın\n"
            "- Arşivdeki benzer dosyalara göz atın"
        ),
        "en": (
            "**'{query}'** — I haven't gathered enough evidence yet.\n\n"
            "This doesn't mean the claim is false — I currently can't find enough "
            "evidence in my archive or accessible sources to support or refute it. "
            "I only give a verdict based on evidence.\n\n"
            "**You could try:**\n"
            "- Rephrasing the claim with different words\n"
            "- Focusing on a more specific sub-claim\n"
            "- Browsing similar files in the archive"
        ),
    },
    "insufficient.suggestion_rephrase": {"tr": "Farklı kelimelerle tekrar sor", "en": "Ask again with different words"},
    "insufficient.suggestion_browse": {"tr": "Arşivde benzer dosya var mı?", "en": "Are there similar files in the archive?"},
}


def t(key: str, language: str, **kwargs: object) -> str:
    """Verilen anahtarın, verilen dildeki metnini döndürür.

    Bilinmeyen key/language kombinasyonunda TR'ye, o da yoksa key'in
    kendisine (görünür bir "eksik çeviri" işareti — sessiz başarısızlık
    değil) düşer. Asla exception fırlatmaz; format placeholder eksikse
    ham metni döner.
    """
    lang = normalize_language(language)
    entry = _T.get(key)
    if entry is None:
        return key
    text = entry.get(lang) or entry.get(DEFAULT_LANGUAGE)
    if text is None:
        return key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
