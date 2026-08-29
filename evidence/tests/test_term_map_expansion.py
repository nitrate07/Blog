"""Kapsamli sozluk genisletmesi (2026-08-29) icin testler.

Kullanicinin dogrudan talebi uzerine ("sozluk hazinesini tum dunya
geneline yaz"), _TERM_MAP icd10-cm PyPI paketinin (95.622 ICD-10 kodu,
22 bolum) bolum yapisi cerceve alinarak 171 girisd en 388 benzersiz
girise cikarildi.

Bu dosya iki seyi test eder:
1. _TERM_MAP'in KENDISININ yapisal butunlugu (duplicate key yok, 3+
   kelimelik "olu" anahtar yok — bu ikisi genisletme sirasinda gercekten
   bulunan hatalardi, otomatik test olarak kilitleniyor ki gelecekte
   sozluge eklenen yeni girdiler de bu hatalari otomatik yakalasin).
2. Yeni eklenen kategorilerden ornek terimlerin gercekten calistigi.
"""

from __future__ import annotations

import ast
from pathlib import Path

from evidence.chat.search_query import _TERM_MAP, has_health_topic


def _term_map_source_keys() -> list[str]:
    """_TERM_MAP literal'ini kaynaktan AST ile parse edip TUM key'leri
    (Python'un sessizce sildigi duplicate'ler dahil) dondurur."""
    path = Path(__file__).parent.parent / "chat" / "search_query.py"
    src = path.read_text()
    start = src.index("_TERM_MAP: dict[str, str] = {")
    brace_start = src.index("{", start)
    depth = 0
    i = brace_start
    while True:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    literal = src[brace_start:i + 1]
    tree = ast.parse("x = " + literal)
    dict_node = tree.body[0].value
    return [k.value for k in dict_node.keys]


class TestTermMapStructuralIntegrity:
    """Genisletme sirasinda gercekten bulunan iki sinif hatayi otomatik
    test olarak kilitler — gelecekte sozluge yeni girdi eklerken bu
    testler o hatalari tekrar sessizce gecirmez."""

    def test_no_duplicate_keys(self):
        """Python dict literal'i duplicate key'lerde SESSIZCE son degeri
        kullanir — ilk tanimin ne oldugu asla goruntuye gelmez. Bu,
        genisletme sirasinda 'tümör' anahtarinin iki kez tanimlanmasiyla
        gercekten yasandi (biri sessizce digerini eziyordu)."""
        keys = _term_map_source_keys()
        seen: dict[str, int] = {}
        dupes = []
        for idx, k in enumerate(keys):
            if k in seen:
                dupes.append(k)
            seen[k] = idx
        assert dupes == [], f"Tekrarlanan anahtarlar: {dupes}"

    def test_no_unmatchable_three_plus_word_keys(self):
        """_matched_terms yalnizca 2-token pencereleri kontrol eder (bkz.
        search_query.py, 'two = tokens[i:i+2]') — 3+ kelimelik bir anahtar
        YAPISAL OLARAK hicbir zaman eslesemez. Genisletme sirasinda 14
        boyle anahtar bulundu (ör. 'derin ven trombozu', 'idrar yolu
        enfeksiyonu') — hepsi calisan 2-kelimelik alt diziler haline
        getirildi. Bu test, gelecekte boyle bir anahtarin sessizce
        eklenmesini engeller."""
        broken = [k for k in _TERM_MAP if len(k.split()) > 2]
        assert broken == [], f"Yapisal olarak eslesemeyen (3+ kelimelik) anahtarlar: {broken}"


class TestComprehensiveExpansionCoverage:
    """Yeni eklenen ICD-10 bolumlerinden ornek terimler — genisletmenin
    gercekten calistigini dogrular."""

    def test_infectious_diseases(self):
        assert has_health_topic("Kolera nasıl bulaşır?") is True
        assert has_health_topic("Verem tedavi edilebilir mi?") is True
        assert has_health_topic("Tifo aşısı etkili mi?") is True

    def test_cancers(self):
        assert has_health_topic("Akciğer kanseri sigara ile mi ilgili?") is True
        assert has_health_topic("Lösemi çocuklarda görülür mü?") is True
        assert has_health_topic("Rahim ağzı kanseri HPV ile mi ilgili?") is True
        assert has_health_topic("İyi huylu tümör tehlikeli mi?") is True

    def test_blood_disorders(self):
        assert has_health_topic("Talasemi genetik mi?") is True
        assert has_health_topic("Tromboz uzun uçuşlarla mı ilgili?") is True
        assert has_health_topic("Orak hücre anemisi nedir?") is True

    def test_endocrine_metabolic(self):
        assert has_health_topic("Hashimoto tiroidi etkiler mi?") is True
        assert has_health_topic("Cushing sendromu nedir?") is True

    def test_mental_health(self):
        assert has_health_topic("OKB tedavi edilebilir mi?") is True
        assert has_health_topic("TSSB tedavi edilebilir mi?") is True
        assert has_health_topic("Sınırda kişilik bozukluğu nedir?") is True

    def test_neurological(self):
        assert has_health_topic("Parkinson hastalığı kalıtsal mı?") is True
        assert has_health_topic("Multipl skleroz nedir?") is True

    def test_eye_ear(self):
        assert has_health_topic("Katarakt ameliyatı riskli mi?") is True
        assert has_health_topic("Tinnitus kalıcı mı?") is True

    def test_cardiovascular(self):
        assert has_health_topic("Kalp krizi belirtileri nelerdir?") is True
        assert has_health_topic("Koroner arter hastalığı belirtileri nelerdir?") is True

    def test_respiratory(self):
        assert has_health_topic("KOAH sigara ile mi ilgili?") is True
        assert has_health_topic("Zatürre tehlikeli mi?") is True

    def test_digestive(self):
        assert has_health_topic("Reflü geceleri kötüleşir mi?") is True
        assert has_health_topic("İrritabl bağırsak sendromu stresle mi ilgili?") is True

    def test_skin(self):
        assert has_health_topic("Akne hormonal mı?") is True
        assert has_health_topic("HPV siğillere neden olur mu?") is True

    def test_musculoskeletal(self):
        assert has_health_topic("Skolyoz ameliyat gerektirir mi?") is True

    def test_genitourinary(self):
        assert has_health_topic("İdrar yolu enfeksiyonu kadınlarda mı sık görülür?") is True

    def test_pregnancy(self):
        assert has_health_topic("Preeklampsi tehlikeli mi?") is True

    def test_symptoms(self):
        assert has_health_topic("Ateş kaç derece tehlikelidir?") is True


class TestExpansionNoFalsePositiveRegression:
    """Genisletme, mevcut yanlis-pozitif korumalarini bozmamali."""

    def test_unrelated_sentences_still_false(self):
        unrelated = [
            "bugün hava çok güzel", "şu ürüne bir göz atar mısın?",
            "benim adım Ümit", "aşırı yorgunum bugün ama sağlıkla ilgisi yok",
            "yarın toplantı saat kaçta?", "futbol maçı ne zaman başlıyor",
            "arabamın lastiği patladı",
        ]
        for q in unrelated:
            assert has_health_topic(q) is False, f"Yanlis pozitif: {q!r}"

    def test_bit_exact_match_not_false_positive_inside_other_words(self):
        """Yeni eklenen kisa anahtar 'bit' (bit/parazit), 'bitmek' gibi
        kelimelerin icinde yanlislikla tetiklenmemeli (exact-match-only,
        3 karakter oldugu icin fuzzy suffix toleransindan haric)."""
        assert has_health_topic("bu iş bitmek üzere") is False
        assert has_health_topic("ödevi bitirdim") is False
