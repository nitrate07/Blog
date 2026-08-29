"""build_search_query birim testleri — Turkce sorudan Ingilizce anahtar kelime uretimi."""

import pytest

from evidence.chat.search_query import build_search_query, has_health_topic


class TestKnownTranslations:
    """Sozlukteki terimler dogru Ingilizce karsiliklara donusmeli."""

    def test_documented_example(self):
        assert build_search_query("Kahve kolesterolü yükseltir mi?") == "coffee cholesterol"

    def test_multi_term_query(self):
        assert build_search_query("Zeytinyağı kalp sağlığına faydalı mıdır?") == \
            "olive oil heart cardiovascular"

    @pytest.mark.parametrize("claim, expected", [
        ("Çay içmek iyi mi?", "tea"),
        ("Kreatin böbreğe zarar verir mi?", "creatine"),
        ("Balık yağı omega içerir mi", "fish omega-3"),
        ("Vitamin D3 kemiğe iyi gelir mi?", "vitamin d3"),
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
