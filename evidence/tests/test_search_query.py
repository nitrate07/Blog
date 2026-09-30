"""build_search_query birim testleri — Turkce sorudan Ingilizce anahtar kelime uretimi."""

import pytest

from evidence.chat.search_query import (
    build_search_query,
    has_health_topic,
    has_turkish_term,
)


class TestKnownTranslations:
    """Sozlukteki terimler dogru Ingilizce karsiliklara donusmeli."""

    def test_documented_example(self):
        assert build_search_query("Kahve kolesterolü yükseltir mi?") == "coffee cholesterol"

    def test_multi_term_query(self):
        assert build_search_query("Zeytinyağı kalp sağlığına faydalı mıdır?") == \
            "olive oil heart cardiovascular"

    @pytest.mark.parametrize("claim, expected", [
        ("Çay içmek iyi mi?", "tea"),
        # NOT (2026-09-27): "böbreğe"/"kemiğe" belirtme hali ekleri mutevaziyet
        # (k→ğ, ö→ü) yuzunden kok one-ekle basmiyordu; sozlukte "böbrek"/
        # "kemik" vardi ama cekimli form atliyordu. unsuz katmani bunu
        # duzeltince sorgu artik organi da iceriyor (daha ilgili bir arama).
        ("Kreatin böbreğe zarar verir mi?", "creatine kidney"),
        ("Balık yağı omega içerir mi", "fish omega-3"),
        ("Vitamin D3 kemiğe iyi gelir mi?", "vitamin d3 bone skeletal"),
    ])
    def test_term_map_translations(self, claim, expected):
        assert build_search_query(claim) == expected


class TestQuestionFillerRemoval:
    """Soru kalip/eki ve doldurucu sozcukler temizlenmeli."""

    def test_nedir_removed(self):
        assert build_search_query("kahve nedir") == "coffee"

    def test_gercekten_and_acaba_removed(self):
        assert build_search_query("Kahve gerçekten kolesterolü yükseltir mi acaba?") == \
            "coffee cholesterol"

    def test_question_particle_dedupes_repeats(self):
        assert build_search_query("kahve mi çay mı kahve") == "coffee tea"


class TestUnknownTerms:
    """Sozlukte olmayan kavramlar elenmeli; hic eslesme yoksa orijinal korunmali."""

    def test_unknown_words_preserved_when_no_match(self):
        claim = "xyzabc krizinden atmak"
        assert build_search_query(claim) == claim

    def test_ascii_english_terms_pass_through(self):
        assert build_search_query("coffee cholesterol") == "coffee cholesterol"

    def test_known_abbreviation_ldl(self):
        assert build_search_query("LDL yükseltir mi tereyağı") == "ldl cholesterol"


class TestPrefixMatching:
    """Cekimli halller kok terime on-eslestirme ile yakalanmali."""

    def test_inflected_kolesterolu(self):
        assert build_search_query("kolesterolü düşürür mü") == "cholesterol"

    def test_inflected_stresi(self):
        assert build_search_query("stresi azaltır mı uyku") == "stress sleep"


class TestSafeInputs:
    """Bos/girdisiz girdi hata firlatmadan guvenli deger donmeli."""

    def test_empty_string(self):
        assert build_search_query("") == ""

    def test_none_argument(self):
        assert build_search_query(None) == ""

    def test_whitespace_only(self):
        assert build_search_query("   ") == ""


class TestHasHealthTopic:
    """has_health_topic — build_search_query'nin aksine, eslesme yoksa False
    doner (fallback metni degil). Guvenlik kapisi icin dogru sinyal budur."""

    def test_true_for_real_health_claim(self):
        assert has_health_topic("Kahve kolesterolü yükseltir mi?") is True

    def test_false_for_name_introduction(self):
        # Regresyon: eskiden "adım" (step) sozlukte tekti ve "benim adım
        # Ümit" gibi bir isim tanitimini "steps walking" saglik konusuyla
        # eslestirip botun sahte bir hukum uretmesine yol aciyordu.
        assert has_health_topic("benim adım Ümit") is False

    def test_false_for_unrelated_smalltalk(self):
        assert has_health_topic("bugün hava çok güzel") is False

    def test_false_for_empty(self):
        assert has_health_topic("") is False
        assert has_health_topic(None) is False

    def test_true_for_step_count_compound(self):
        # "adim sayisi"/"gunluk adim" gibi belirgin iki-kelimelik kaliplar
        # hala taniniyor olmali — sadece tek basina "adim" kaldirildi.
        assert has_health_topic("günlük adım sayısı yeterli mi?") is True

    def test_false_for_goz_atmak_idiom(self):
        # Regresyon: bare "göz" -> "eye vision" eslesmesi "göz atmak" (bir
        # seye bakmak) gibi cok yaygin, saglikla alakasiz bir deyimi de
        # yakaliyordu.
        assert has_health_topic("şu ürüne bir göz atar mısın?") is False

    def test_true_for_goz_sagligi_compound(self):
        assert has_health_topic("göz sağlığı için havuç yemeli miyim?") is True

    def test_false_for_bare_letter_c(self):
        # Regresyon: bare "c" -> "c" eslesmesi herhangi bir yalniz "c"
        # harfini vitamin C sanıyordu.
        assert has_health_topic("c harfi ile başlayan bir kelime söyle") is False

    def test_true_for_vitamin_c_compound(self):
        assert has_health_topic("vitamin c bağışıklığa iyi gelir mi?") is True
        assert has_health_topic("c vitamini soğuk algınlığına iyi gelir mi?") is True


class TestHasTurkishTerm:
    """has_turkish_term — metinde sözlükteki TÜRKÇE anahtarlardan (terim)
    biri doğrudan geçiyor mu. has_health_topic'ten FARKLI olarak sozluk
    DEĞERLERİNDEKİ İngilizce kelimeleri kabul etmez; bu ayrım sayesinde
    v2/pipeline.py "sorgu zaten İngilizce mi?" kestirimini güvenle
    besleyebiliyor (İngilizce sorgular aynen döner)."""

    @pytest.mark.parametrize("text", [
        "Mikrodalga yemeği zehirler mi?",
        "c vitamini soguk alginligina iyi gelir mi",  # diyakritiksiz Turkce
        "zerdeçal iltihabı azaltır mı",
        "soğuk duş bağışıklığı güçlendirir mi",
    ])
    def test_true_for_turkish_claim(self, text):
        assert has_turkish_term(text) is True

    @pytest.mark.parametrize("text", [
        "Does coffee raise cholesterol levels?",  # sozluk DEGERLERI
        "coffee cholesterol",
        "asdkfjaslkdfj qwerty zxcvbn",
        "Where should I put my glasses?",
        "",
    ])
    def test_false_for_non_turkish(self, text):
        assert has_turkish_term(text) is False

    def test_none_safe(self):
        assert has_turkish_term(None) is False


class TestInflectedVaccineForms:
    """Regresyon (2026-08-29): canli testle bulundu — "aşı" yalniz 3 karakter
    oldugu icin genel cekim-eki toleransindan (len(key)>=4 sarti, "aşırı"
    gibi kelimelerle yanlis eslesmeyi onlemek icin) haric tutuluyordu. Bu,
    Turkce'nin sondan eklemeli yapisinda TUM cekimli "aşı" formlarini
    (aşılar, aşıyı, aşının...) yakalanmaz hale getiriyordu — en carpici
    ornek: "Aşılar otizme neden olur mu?" (saglik yanlis bilgisinin en
    unlu tek ornegi) "saglik iddiasi olarak taninamadi" hatasi veriyordu."""

    def test_asilar_plural_recognized(self):
        assert has_health_topic("Aşılar otizme neden olur mu?") is True

    def test_asiyi_accusative_recognized(self):
        assert has_health_topic("Aşıyı ne zaman yaptırmalıyım?") is True

    def test_asinin_genitive_recognized(self):
        assert has_health_topic("Aşının yan etkileri nelerdir?") is True

    def test_asiri_not_falsely_matched_via_vaccine_stem(self):
        """Kritik: "aşı" icin eklenen yeni cekimli formlar, "aşırı"
        (excessive) kelimesiyle CAKISMAMALI — bu tam olarak len(key)>=4
        sartinin baslangicta onlemeye calistigi hataydi."""
        from evidence.chat.search_query import _match_term
        assert _match_term("aşırı") is None

    def test_asiri_egzersiz_still_matches_via_egzersiz_not_asi(self):
        """"aşırı egzersiz" saglik konusu olarak taninmali ama bunun nedeni
        "egzersiz" kelimesi olmali, "aşırı"nin "aşı" ile yanlis eslesmesi
        degil."""
        assert has_health_topic("aşırı egzersiz zararlı mı?") is True


class TestPreviouslyMissingTopics:
    """Regresyon (2026-08-29): canli testle bulunan, sozlukte hic karsiligi
    olmayan yaygin saglik konulari."""

    def test_honey_infant_botulism(self):
        assert has_health_topic("Bebeklerde bal zararlı mı?") is True

    def test_ketogenic_diet(self):
        assert has_health_topic("Ketojenik diyet epilepsiyi tedavi eder mi?") is True

    def test_epilepsy_bare(self):
        assert has_health_topic("Epilepsi hastaları spor yapabilir mi?") is True


class TestSecondSweepMissingTopics:
    """Regresyon (2026-08-29): ilk duzeltmeden sonra yapilan ikinci, daha
    genis bir tarama (24 cesitli iddia) 7 daha eksik konu buldu."""

    def test_menopause_hormone_therapy(self):
        assert has_health_topic("Menopoz sırasında hormon tedavisi güvenli mi?") is True

    def test_adhd_medication_plural(self):
        assert has_health_topic("ADHD ilaçları çocuklarda büyümeyi durdurur mu?") is True

    def test_chemotherapy(self):
        assert has_health_topic("Kemoterapi saç dökülmesine neden olur mu?") is True

    def test_celiac(self):
        assert has_health_topic("Çölyak hastalığı nedir?") is True

    def test_asthma_medication(self):
        assert has_health_topic("Astım ilaçları bağımlılık yapar mı?") is True

    def test_ovarian_cyst_pregnancy(self):
        assert has_health_topic("Kist over hastalarında hamilelik zor mu?") is True

    def test_constipation(self):
        assert has_health_topic("Kabızlık lifli gıdalarla düzelir mi?") is True


class TestGenericMedicalStructureMarkers:
    """Regresyon (2026-08-29): ucuncu, daha da genis bir tarama (20 cesitli
    hastalik/durum) 13/20 oraninda eksik cikardi — tek tek hastalik ismi
    eklemenin tek basina yeterli olmadigini gosterdi. Sozluge genel tibbi
    baglam isaretleyicileri ("hastalık", "sendrom", "bozukluk", "belirti",
    "teşhis", "kronik", "otoimmün", "kalıtsal") eklendi — bunlar, spesifik
    bir hastalik ismi sozlukte olmasa bile "X hastaligi/sendromu/bozuklugu"
    kalibini tibbi baglam olarak tanir, cok daha olceklenebilir bir yaklasim."""

    def test_generic_disease_suffix_recognized_even_for_unlisted_condition(self):
        """"filanca hastalığı" kalibi, "filanca" sozlukte olmasa bile
        "hastalığı" sayesinde tibbi baglam olarak taninmali."""
        assert has_health_topic("Xyzabc hastalığı bulaşıcı mıdır?") is True

    def test_generic_syndrome_suffix_recognized(self):
        assert has_health_topic("Kronik yorgunluk sendromu nedir?") is True

    def test_generic_disorder_suffix_recognized(self):
        assert has_health_topic("Bipolar bozukluk kalıtsal mı?") is True

    def test_eczema_psoriasis_varicose(self):
        assert has_health_topic("Egzama nemlendirici ile geçer mi?") is True
        assert has_health_topic("Sedef hastalığı bulaşıcı mı?") is True
        assert has_health_topic("Varis çorabı damar sağlığına iyi gelir mi?") is True

    def test_fibromyalgia_stroke_bipolar_schizophrenia_autism(self):
        assert has_health_topic("Fibromiyalji gerçek bir hastalık mı?") is True
        assert has_health_topic("İnme belirtileri nelerdir?") is True
        assert has_health_topic("Şizofreni tedavi edilebilir mi?") is True
        assert has_health_topic("Otizm spektrum bozukluğu nedir?") is True

    def test_down_syndrome_rheumatoid_arthritis_gallbladder(self):
        assert has_health_topic("Down sendromu testleri güvenilir mi?") is True
        assert has_health_topic("Romatoid artrit otoimmün bir hastalık mı?") is True
        assert has_health_topic("Safra kesesi taşı ameliyatla mı alınır?") is True

    def test_unrelated_sentences_still_correctly_false(self):
        """Yeni genel isaretleyiciler, alakasiz cumleleri yanlislikla
        yakalamamali — bunlar hala mevcut yanlis-pozitif korumalariyla
        (aşırı/göz/adım) uyumlu kalmali."""
        assert has_health_topic("bugün hava çok güzel") is False
        assert has_health_topic("şu ürüne bir göz atar mısın?") is False
        assert has_health_topic("benim adım Ümit") is False
        assert has_health_topic("aşırı yorgunum bugün ama sağlıkla ilgisi yok") is False


class TestLabValueTerms:
    """Regresyon (2026-08-29): kullanicinin kendisi "trigliserid" hakkinda
    soru sordu ve sistem taniyamadi — kolesterol kadar temel bir kan
    tahlili degeri sozlukte hic yoktu. Ek tarama TSH ve HbA1c'yi de
    eksik buldu."""

    def test_triglyceride(self):
        assert has_health_topic("trigliserid yüksekliği tehlikeli mi") is True

    def test_hba1c(self):
        assert has_health_topic("HbA1c testi ne işe yarar") is True

    def test_tsh(self):
        assert has_health_topic("TSH yüksekliği tiroid sorunu mu") is True


class TestDailyExposureAndFoodSafety:
    """Regresyon (2026-09-27): kullanicinin bildirdigi uc gercek vaka —
    "saglik sorulari arastirilmiyor" — sozlukte KARSILIGI OLMAYAN
    gunluk-maruziyet sinifinda kaldi:

      "zerdeçal iltihabı azaltır mı"
      "soğuk duş bağışıklığı güçlendirir mi"
      "mikrodalga yemeği zehirler mi"

    Onceki genisletmeler ICD-10 bolumlerinden (hastalik, test, besin)
    terim toplamisti; bu ucu de "maruziyet" (banyo, gida, cevresel
    kimyasal, bitkisel) eksik sinifti. Ayrica "iltihap" — neredeyse her
    tibbi iddianin cekirdek kavrami — sozlukte HIC yoktu."""

    @pytest.mark.parametrize("claim", [
        "zerdeçal iltihabı azaltır mı",
        "soğuk duş bağışıklığı güçlendirir mi",
        "mikrodalga yemeği zehirler mi",
    ])
    def test_reported_claims_recognized_as_health_topics(self, claim):
        assert has_health_topic(claim) is True

    @pytest.mark.parametrize("claim, expected_concepts", [
        ("zerdeçal iltihabı azaltır mı", ("turmeric", "inflammation")),
        ("soğuk duş bağışıklığı güçlendirir mi", ("shower", "immune")),
        ("mikrodalga yemeği zehirler mi", ("microwave", "poison")),
    ])
    def test_reported_claims_produce_english_query(self, claim, expected_concepts):
        """Sadece taninmak degil, harici API'ye (PubMed/Crossref) anlamli
        bir Ingilizce sorgu cikarmak da gerekiyor — aksi halde arsivde
        Turkce metinle arama yapilir ve alakasiz sonuc doner."""
        query = build_search_query(claim)
        for concept in expected_concepts:
            assert concept in query.lower(), f"{claim!r} -> {query!r} ({concept} yok)"

    @pytest.mark.parametrize("claim", [
        # ayni sinifin diger uyeleri — tek tek vaka eklemek yerine sinifi
        # temsil eden bir kume
        "sarımsak gripten korur mu",
        "bitkisel çay uykuyu düzeltir mi",
        "gıda güvenliği için ne yapmalı",
        "kurşun maruziyeti zararlı mı",
        "kullanma süresi dolmuş yoğurt zararlı mı",
        "zencefil mide ağrısını azaltır mı",
        "propolis bağışıklığı güçlendirir mi",
        "saunayın kalbe zararı var mı",
    ])
    def test_whole_exposure_class_recognized(self, claim):
        assert has_health_topic(claim) is True

    def test_cold_shower_matched_as_phrase_not_bare_so_cuk(self):
        """"soğuk duş" IKI KELIMELIK anahtar; bare "soğuk" DEGIL —
        "bugün hava çok soğuk" bir saglik iddiasi degil (aynı mantikla
        "göz atmak" icin bare "göz" kaldirilmisti)."""
        assert has_health_topic("bugün hava çok soğuk") is False
        assert has_health_topic("soğuk duş kas ağrısını azaltır mı") is True

    def test_generic_food_words_stay_out(self):
        """Kapsam kurali: gunluk yemek kelimeleri ("yemek", "gıda", "dikkat")
        BILEREK sozluk disi birakildi — "yemek yiyorum", "yemek tarifi nasil
        yapilir" gibi iddia olmayan mesajlar saglik konusu sanilmasin."""
        assert has_health_topic("yemek tarifi nasıl yapılır") is False
        assert has_health_topic("dün çok güzel yemek yedik") is False

    def test_business_odak_grubu_stays_out(self):
        """Kapsam kurali: "odak grubu" yaygin bir is terimidir. Saglik
        tarafi fiil koku ("odaklan") ile yakalanir, bare "odak" ile
        degil."""
        assert has_health_topic("odak grubu nasıl kurulur") is False
        assert has_health_topic("odaklanma için ne yapmalı") is True


class TestUnsuzYumusamasiKatmani:
    """Regresyon (2026-09-27): Turkce'de ek alirken kelimenin son unsuzu
    yumusur (unsuz yumusamasi) ve bu degisim cekimli formun ICINDE
    kaldigi icin onceki on-eslestirme katmani goremiyordu:

        "bağışıklık" (sozlukte VAR) → "bağışıklığı" → eslesmiyordu

    Kullanicinin "soğuk duş bağışıklığı güçlendirir mi" sorusu bu yuzden
    saglik konusu olarak taninmiyordu. Cozum: iki taraf da ayni unsuz
    sinifina indirgenip on-eslestirme kurali tekrar uygulaniyor."""

    @pytest.mark.parametrize("token, expected", [
        ("bağışıklığı", "immune immunity"),
        ("bağışıklığını", "immune immunity"),
        ("kolesterolü", "cholesterol"),
        ("böbreğe", "kidney"),
        ("kemiğe", "bone skeletal"),
    ])
    def test_inflected_forms_match_their_root(self, token, expected):
        from evidence.chat.search_query import _match_term
        assert _match_term(token) == expected

    def test_root_form_still_unchanged(self):
        from evidence.chat.search_query import _match_term
        assert _match_term("bağışıklık") == "immune immunity"

    def test_whole_claim_recognized(self):
        assert has_health_topic("bağışıklığı güçlendiren besinler var mı") is True

    def test_key_length_threshold_preserved(self):
        """Katman, diger fuzzy katmanlarla ayni >=4 karakter esigini
        korumali — kisa anahtarlar ("tuz", "ot", "göz") baska kelimelerin
        icinde yanlis eslesmesin."""
        from evidence.chat.search_query import _FOLDED_TERM_MAP
        assert all(len(k) >= 4 for k in _FOLDED_TERM_MAP)
        assert "tuz" not in _FOLDED_TERM_MAP

    @pytest.mark.parametrize("token", [
        # eslesmesi gerekenler: ne cekimli formu ne de baska bir kelime
        "aşırı",        # (excessive) — "aşı" (vaccine) ile karışmamalı
        "gözle",        # "göz atmak" deyimi
        "adım",         # "benim adım Ümit" — isim tanıtımı
        "çiçek",        # ğ/ç içeren ama sozlukte olmayan kelime
        "yağmur",       # "yağ" 3 karakter — >=4 eşiği onu dışarı bırakmalı
        "c harfi",      # bare "c"
    ])
    def test_no_new_false_positives(self, token):
        from evidence.chat.search_query import _match_term
        assert _match_term(token) is None

    def test_known_exact_matches_are_not_shadowed_by_folding(self):
        """Katman sadece onceki iki katman BASARISIZ oldugunda devreye
        giriyor — tam eslesme her zaman oncelikli."""
        from evidence.chat.search_query import _match_term
        assert _match_term("kahve") == "coffee"
        assert _match_term("glp-1") == "glp-1 glucagon-like peptide-1"
        assert _match_term("hba1c") == "hba1c hemoglobin a1c"


class TestHasSubstantiveContent:

    """has_substantive_content — has_health_topic'ten farkli, daha dusuk
    bir bar: sozlukte olan bir SAGLIK terimi degil, herhangi bir anlamli
    kelime arar. conversation.py'deki has_health_topic kapisinin
    is_interrogative ile gevsetilmesi sonrasi bulunan bir regresyonu
    (baglamsiz isaret-zamiri sorulari) onlemek icin eklendi."""

    def test_demonstrative_pronoun_only_question_has_no_content(self):
        from evidence.chat.search_query import has_substantive_content
        assert has_substantive_content("Bu doğru mu?") is False
        assert has_substantive_content("Öyle mi?") is False
        assert has_substantive_content("Böyle mi?") is False
        assert has_substantive_content("Şunu yapar mısın?") is False

    def test_real_topic_word_counts_as_content(self):
        from evidence.chat.search_query import has_substantive_content
        assert has_substantive_content("trigliserid nedir?") is True
        assert has_substantive_content("İlaç zararlı mı?") is True
        assert has_substantive_content("Kanser") is True

    def test_nonsense_word_with_sufficient_length_counts_as_content(self):
        """Bilincli tasarim: bu fonksiyon 'gercek bir saglik terimi mi'
        sormuyor (o has_health_topic'in isi) — yalnizca 'arastirmaya
        deger, dolgu-disi bir kelime var mi' sorusuna cevap verir.
        Anlamsiz ama yeterince uzun bir kelime de gecer — arastirma
        denenir, muhtemelen 'yeterli kanit yok' ile sonuclanir, ki bu
        'tanıyamadım'dan daha dogru bir sonuçtur."""
        from evidence.chat.search_query import has_substantive_content
        assert has_substantive_content("Xyzabc123 tehlikeli mi") is True


class TestEverydaySentencesAreNotHealthTopics:
    """LF:turkish-word-collision guard: a dictionary key that is also an
    everyday word turns small talk into a "health claim" ('adım' → 'benim
    adım Ümit' → 'Destekleniyor %85'). Each sentence below uses the everyday
    sense of a word whose health sense is in the dictionary only as a
    two-word key. Add a line here whenever a new ambiguous word is added."""

    @pytest.mark.parametrize("sentence", [
        "bugün güneş çok güzel",
        "hava güneşli mi",
        "fırından yeni ekmek aldım",
        "telefonumun hafızası doldu",
        "telefonumun hafızası doldu mu",
        "kurşun kalem nerede",
        "bahçeye bitki diktim",
        "benim adım Ümit",
    ])
    def test_everyday_sense_not_health(self, sentence):
        assert has_health_topic(sentence) is False

    @pytest.mark.parametrize("claim", [
        "güneş kremi cilt kanserini önler mi",
        "bitki çayı uykuya iyi gelir mi",
        "kurşun zehirlenmesi zekayı etkiler mi",
        "hafıza kaybı b12 eksikliğinden olur mu",
    ])
    def test_health_sense_still_recognized(self, claim):
        assert has_health_topic(claim) is True
