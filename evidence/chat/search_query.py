"""Arama sorgu ureteci — Turkce dogal soruyu akademik API'ler icin Ingilizce anahtar kelimelere cevirir.

PubMed/Crossref/Europe PMC gibi kaynaklar Turkce dogal dil sorulariyle alakasiz
sonuclar donduruyor ("Kahve mi? Starbucks'ta Kahve mi?"). Bu modul iddiadan
sadece arama icin tasidigi kavramlari cikarir:

  "Kahve kolesterolü yükseltir mi?" -> "coffee cholesterol"

Kural tabanidir (LLM kullanmaz): sozluk eslestirme + soru eki/sozcugu ayiklama.
Sozlukte olmayan kavramlar dusurulur; hicbir eslesme yoksa orijinal sorgu doner
(arsiv RAG aramasi Turkce calisir, bu modul yalnizca harici API adimlarindadir).
"""

from __future__ import annotations

import re

# Soru kelime/ekleri — arama terimi olarak degersiz, her zaman dusurulur.
_QUESTION_FILLER = {
    "mi", "mı", "mu", "mü", "mıdır", "midir", "mudur", "müdür",
    "nedir", "kimdir", "nasıl", "neden", "niye", "ne",
    "is", "are", "does", "do", "did", "can", "should", "will", "would",
    "what", "why", "how", "the", "a", "an", "of", "in", "on", "for", "to",
    "it", "true", "really", "actually", "gerçekten", "aslında", "bana",
    "hakkında", "bir", "birşey", "şey", "kadar", "daha", "çok", "az",
    "etmek", "eder", "ederim", "verir", "misin", "musun", "yap", "yapar",
}

# Yaygin fiil kaliplari — kavram zaten terim sozlugunden gelir; fiil gövdesi gürültü.
_VERB_SUFFIXES = (
    "yükseltir", "yükseltır", "düşürür", "arttırır", "arttirir", "azaltır",
    "azaltir", "zarar", "zararlı", "zararli", "faydalı", "faydali", "iyi",
    "kötü", "kotu", "korur", "korurmuyor", "engeller", "neden olur",
    "raise", "raise", "lower", "reduce", "increase", "decrease", "cause",
    "prevent", "protect", "harmful", "beneficial", "good", "bad",
)

# Saglik terimleri TR -> EN. Harici API'lerde anlamlı sonuç için gereken
# çekirdek kavram seti; arşivdeki makale konularına hizalı.
# Saglik terimleri TR -> EN. Harici API'lerde anlamlı sonuç için gereken
# çekirdek kavram seti; arşivdeki makale konularına hizalı.
_TERM_MAP: dict[str, str] = {
    # beslenme
    "kahve": "coffee", "çay": "tea", "cay": "tea",
    "kolesterol": "cholesterol", "ldl": "ldl cholesterol", "hdl": "hdl cholesterol",
    "trigliserit": "triglycerides", "tuz": "salt sodium", "şeker": "sugar",
    "seker": "sugar", "gluten": "gluten", "laktoz": "lactose",
    "kahverengi": "brown", "filtre": "filtered",
    "kafein": "caffeine", "alkol": "alcohol", "et": "red meat",
    "kırmızı": "red", "kirmizi": "red", "zeytinyağı": "olive oil",
    "zeytinyagi": "olive oil", "balık": "fish", "balik": "fish",
    "yumurta": "eggs", "süt": "milk", "sut": "milk", "yoğurt": "yogurt",
    "probiyotik": "probiotic", "prebiyotik": "prebiotic",
    "mikrobiyom": "gut microbiome", "bağırsak": "gut",
    # vitamin/takviye
    "vitamin": "vitamin", "d3": "d3", "c": "c",
    "omega": "omega-3", "balıkyağı": "fish oil", "balikyagi": "fish oil",
    "magnesium": "magnesium", "magnezyum": "magnesium", "çinko": "zinc",
    "cinko": "zinc", "demir": "iron", "kalsiyum": "calcium",
    "kreatin": "creatine", "melatonin": "melatonin", "kolajen": "collagen",
    # hastalık/organ
    "kalp": "heart cardiovascular", "böbrek": "kidney", "bobrek": "kidney",
    "karaciğer": "liver", "karaciger": "liver", "mide": "stomach gastric",
    "beyin": "brain", "akciğer": "lung", "akciger": "lung",
    "kemik": "bone skeletal", "eklem": "joint", "cilt": "skin dermal",
    "diş": "dental teeth", "dis": "dental teeth", "göz": "eye vision",
    "hipertansiyon": "hypertension blood pressure",
    "tansiyon": "blood pressure hypertension",
    "diyabet": "diabetes", "insülin": "insulin", "insulin": "insulin",
    "kanser": "cancer", "tümör": "tumor", "tumor": "cancer tumor",
    "obezite": "obesity", "şişmanlık": "obesity", "kilo": "weight body weight",
    "depresyon": "depression", "anksiyete": "anxiety", "kaygı": "anxiety",
    "stres": "stress", "uyku": "sleep", "uykusuzluk": "insomnia",
    "migren": "migraine", "baş ağrısı": "headache",
    "immün": "immune immunity", "bağışıklık": "immune immunity",
    "enfeksiyon": "infection", "grip": "influenza flu",
    "soğuk algınlığı": "common cold", "aşı": "vaccination vaccine",
    "antibiyotik": "antibiotic", "ilaç": "medication drug",
    # egzersiz/yaşam
    "egzersiz": "exercise physical activity", "spor": "exercise training",
    "koşu": "running aerobic", "yürüyüş": "walking",
    "adım sayısı": "step count daily steps", "günlük adım": "daily step count",
    # NOT: bare "adım" kasıtlı olarak yok — Türkçe'de "benim adım X" (my name
    # is X) ile "adım" (step) ayrım gerektirir; tek başına "adım" cümlenin
    # bir isim tanıtımı mı yoksa adım-sayısı iddiası mı oldugunu ayırt edemez,
    # bu yuzden sadece "adım sayısı"/"günlük adım" gibi belirgin iki-kelimelik
    # kaliplar eslestirilir.
    "ağır kaldırma": "resistance training", "kas": "muscle hypertrophy",
    "esneme": "stretching", "yoga": "yoga", "oruç": "fasting intermittent fasting",
    "açlık": "caloric restriction", "uzun ömür": "longevity",
    "yaşlanma": "aging ageing", "ölüm": "mortality death",
    "sigara": "smoking cigarette", "vapür": "vaping e-cigarette",
    "nargile": "hookah shisha",
    # ilaçlar
    "aspirin": "aspirin", "ibuprofen": "ibuprofen",
    "metformin": "metformin", "statin": "statin statins",
    "ozempik": "semaglutide", "semaglutide": "semaglutide",
    "glp1": "glp-1 glucagon-like peptide-1", "glp-1": "glp-1 glucagon-like peptide-1",
    "parasetamol": "paracetamol acetaminophen",
}


def _normalize(text: str) -> str:
    """Türkçe karakterleri eşlenebilir forma indirgeme yapmadan küçültüp temizler."""
    return re.sub(r"[^\w\sçğıöşüÇĞİÖŞÜ]", " ", text.lower()).strip()


# Sozlukte uzun terimler icin Turkce cekim eklerini tolera eden on-eslestirme:
# "kolesterolü" -> "kolesterol" (fark <= 2 karakter ve son harf sesli/ek harfi).
_MAX_SUFFIX_LEN = 3


# Sozluk degerlerinden turetilen Ingilizce izin listesi: yalnizca bilinen
# kavram kelimeleri harici API'ye tasinir ("krizinden", "atmak" gibi ASCII
# yazilmis Turkce sozcukler boylece elenir).
_ALLOWED_EN: frozenset[str] = frozenset(
    piece
    for value in _TERM_MAP.values()
    if value
    for piece in value.split()
)


def _match_term(token: str) -> str | None:
    """Once tam eslesme, sonra Turkce cekim ekini soyan on-eslestirme."""
    if token in _TERM_MAP:
        return _TERM_MAP[token]
    best: tuple[int, str] | None = None
    for key, value in _TERM_MAP.items():
        if len(key) >= 4 and token.startswith(key):
            diff = len(token) - len(key)
            if 0 < diff <= _MAX_SUFFIX_LEN and (best is None or diff < best[0]):
                best = (diff, value)
    return best[1] if best else None


def _matched_terms(claim: str) -> list[str]:
    """Iddiadan SADECE sozlukte/bilinen-terim olarak taninan kavramlari toplar.

    build_search_query'nin cevirisiyle has_health_topic'in konu-tespiti ayni
    eslestirme mantigini paylasir — burada, tek bir yerde. Bos donerse, mesajda
    HICBIR bilinen saglik/tibbi kavram yok demektir (fallback metni degil).
    """
    if not claim:
        return []
    tokens = _normalize(claim).split()
    out: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        for piece in term.split():
            if piece and piece not in seen:
                seen.add(piece)
                out.append(piece)

    i = 0
    while i < len(tokens):
        two = " ".join(tokens[i:i + 2])
        if two in _TERM_MAP:
            add(_TERM_MAP[two])
            i += 2
            continue
        token = tokens[i]
        mapped = _match_term(token)
        if mapped is not None:
            add(mapped)
        elif token in _QUESTION_FILLER or token in _VERB_SUFFIXES:
            pass
        elif token in _ALLOWED_EN or re.fullmatch(r"[a-z0-9-]{1,4}", token) and any(c.isdigit() for c in token):
            # Bilinen İngilizce terim veya sayı/kısaltma (ldl, hdl, d3, 10000...)
            add(token)
        # Türkçe özel karakterli ve sözlükte olmayan kelime: düşür
        i += 1

    return out


def build_search_query(claim: str) -> str:
    """İddiayı harici API'ler için İngilizce anahtar-kelime sorgusuna çevirir.

    Kural: terim sözlüğünden eşleşenleri sırayla topla; sözlükte olmayan ve
    doldurucu/fiil olan kelimeleri at; eşleşme yoksa temizlenmiş orijinali dön
    (arşiv RAG araması Türkçe çalışır, tamamen boş dönmemesi onun için).

    NOT: bu fonksiyonun "eşleşme yoksa orijinali dön" davranışı, onu bir
    "bu mesajda gerçek bir sağlık konusu var mı?" sinyali olarak KULLANMAYI
    güvenilmez kılar — her zaman dolu bir string döner. Bu amaç için
    has_health_topic() kullanın.
    """
    if not claim:
        return ""
    out = _matched_terms(claim)
    query = " ".join(out)
    if not query:
        return claim.strip()
    return query[:200]


def has_health_topic(claim: str) -> bool:
    """Mesajda sozlukte taninan en az bir saglik/tibbi kavram var mi?

    build_search_query'nin aksine, eslesme yoksa False doner (fallback
    metni degil) — bu yuzden "bu mesaj gercekten arastirmaya deger mi"
    guvenlik kapisi icin dogru fonksiyon budur.
    """
    return bool(_matched_terms(claim))
