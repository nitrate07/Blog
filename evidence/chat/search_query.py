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

from .turkish_morphology import get_candidate_stems

# Soru kelime/ekleri — arama terimi olarak degersiz, her zaman dusurulur.
_QUESTION_FILLER = {
    "mi", "mı", "mu", "mü", "mıdır", "midir", "mudur", "müdür",
    "nedir", "kimdir", "nasıl", "neden", "niye", "ne",
    "is", "are", "does", "do", "did", "can", "should", "will", "would",
    "what", "why", "how", "the", "a", "an", "of", "in", "on", "for", "to",
    "it", "true", "really", "actually", "gerçekten", "aslında", "bana",
    "hakkında", "bir", "birşey", "şey", "kadar", "daha", "çok", "az",
    "etmek", "eder", "ederim", "verir", "misin", "musun", "mısın", "müsün", "yap", "yapar",
    # NOT (2026-08-29): "doğru"/"yanlış"/"gerçek" — bunlar iddianin KONUSU
    # degil, dogruluk HAKKINDA konusan meta-kelimeler (İngilizce'deki
    # "true" gibi, ki o zaten listede). Canli testle bulundu: "Bu doğru
    # mu?" gibi baglamsiz bir soru, bu kelime sozlukte olmadigi icin
    # "gercek icerik" sayiliyordu — bkz. has_substantive_content.
    "doğru", "yanlış", "gerçek", "öyle", "böyle", "şöyle",
}

# Isaret zamirleri — dilbilgisel olarak soru YAPISINDA olsalar bile (bkz.
# is_interrogative), baglamsiz kullanildiklarinda HICBIR arastirilabilir
# icerik tasimazlar ("Bu doğru mu?" gibi — bkz. has_substantive_content).
_DEMONSTRATIVE_PRONOUNS = frozenset({
    "bu", "şu", "o", "bunu", "şunu", "onu", "bunlar", "şunlar", "onlar",
    "bunun", "şunun", "onun", "buna", "şuna", "ona", "bunda", "şunda", "onda",
    "this", "that", "these", "those",
})

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
    # NOT: bare "c" kasitli olarak yok — tek harf her yerde eslesme riski
    # tasir ("c harfi ile...", listeler vb.). "vitamin c"/"c vitamini" iki-
    # kelimelik kaliplarla, ya da tek basina "vitamin" ile hala yakalanir.
    "vitamin": "vitamin", "d3": "d3",
    "vitamin c": "vitamin c", "c vitamini": "vitamin c",
    "omega": "omega-3", "balıkyağı": "fish oil", "balikyagi": "fish oil",
    "magnesium": "magnesium", "magnezyum": "magnesium", "çinko": "zinc",
    "cinko": "zinc", "demir": "iron", "kalsiyum": "calcium",
    "kreatin": "creatine", "melatonin": "melatonin", "kolajen": "collagen",
    # hastalık/organ
    "kalp": "heart cardiovascular", "böbrek": "kidney", "bobrek": "kidney",
    "karaciğer": "liver", "karaciger": "liver", "mide": "stomach gastric",
    "beyin": "brain", "akciğer": "lung", "akciger": "lung",
    "kemik": "bone skeletal", "eklem": "joint", "cilt": "skin dermal",
    "diş": "dental teeth", "dis": "dental teeth",
    # NOT: bare "göz" kasitli olarak yok — "göz atmak" (bir seye bakmak)
    # gunluk konusmada cok yaygin, saglikla alakasiz. "göz sağlığı"/"göz
    # tembelliği" gibi belirgin kaliplar hala yakalanir.
    "göz sağlığı": "eye health vision", "göz tembelliği": "lazy eye amblyopia",
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
    # NOT (2026-08-29): "aşı" yalnizca 3 karakter oldugu icin genel cekim-eki
    # toleransindan (bkz. _match_term, len(key)>=4 sarti) kasitli olarak
    # HARIC tutuluyor — bu sart, "aşırı" (excessive) gibi kelimelerin "aşı"
    # ile yanlislikla eslesmesini onlemek icin var. Ama bu, Turkce'nin
    # sondan eklemeli yapisinda "aşı"nin TUM cekimli formlarini (aşılar,
    # aşıyı, aşının...) da yakalanmaz hale getiriyordu. Canli testle
    # dogrulandi: "Aşılar otizme neden olur mu?" — saglik yanlis bilgisinin
    # en unlu tek ornegi — "saglik iddiasi olarak taninamadi" hatasi
    # veriyordu. Cozum: fuzzy mekanizmayi degistirmek yerine (ki "aşırı"
    # riskini geri getirir), en yaygin cekimli formlari AYRI, tam-eslesmeli
    # anahtarlar olarak ekliyoruz — "aşırı" ile hicbir cakisma riski yok
    # (farkli tam string'ler).
    "aşılar": "vaccination vaccine", "aşıyı": "vaccination vaccine",
    "aşının": "vaccination vaccine", "aşıya": "vaccination vaccine",
    "aşıda": "vaccination vaccine", "aşısı": "vaccination vaccine",
    "aşılanma": "vaccination", "aşılanmak": "vaccination",
    "antibiyotik": "antibiotic", "ilaç": "medication drug",
    # NOT (2026-08-29): Canli testle bulunan eksik konular — hepsi
    # yaygin, gercek saglik iddialarinda ("bebeklerde bal zararli mi?",
    # "ketojenik diyet epilepsiyi tedavi eder mi?") gecen, ama sozlukte
    # hic karsiligi olmayan terimlerdi.
    "bal": "honey infant botulism", "ketojenik": "ketogenic diet",
    "keto": "ketogenic diet", "epilepsi": "epilepsy seizure",
    "nöbet": "seizure epilepsy",
    "menopoz": "menopause", "hormon tedavisi": "hormone therapy",
    "adhd": "adhd attention deficit", "kemoterapi": "chemotherapy",
    "çölyak": "celiac disease gluten", "astım": "asthma",
    "kabızlık": "constipation", "hamilelik": "pregnancy",
    "kist over": "ovarian cyst pcos", "polikistik over": "pcos polycystic ovary",
    "ilaçları": "medication drug",
    # NOT (2026-08-29): Genis bir tarama (20 cesitli saglik iddiasi) 13/20
    # oraninda eksik cikardi (egzama, sedef, fibromiyalji, otoimmün
    # hastaliklar, bipolar, sizofreni, otizm spektrumu, Down sendromu vb.).
    # Bu, tek tek hastalik ismi eklemenin tek basina yeterli olmadigini
    # gosterdi — sozlukte "hastalik", "sendrom", "bozukluk", "belirti",
    # "teshis" gibi GENEL tibbi baglam kelimeleri bile yoktu. Iki katmanli
    # duzeltme: (1) asagida genel tibbi-baglam isaretleyicileri (bir
    # hastalik ismi sozlukte olmasa bile "X hastaligi/sendromu/bozuklugu"
    # kalibini yakalar, cok daha olceklenebilir), (2) tarama sirasinda
    # bulunan somut, yaygin hastalik isimleri.
    "hastalık": "disease illness", "hastalığı": "disease illness",
    "sendrom": "syndrome", "sendromu": "syndrome",
    "bozukluk": "disorder", "bozukluğu": "disorder",
    "belirti": "symptom", "belirtileri": "symptoms",
    "semptom": "symptom", "semptomları": "symptoms",
    "teşhis": "diagnosis", "kronik": "chronic",
    "otoimmün": "autoimmune", "kalıtsal": "hereditary genetic",
    "tedavi edilebilir": "treatable", "tedavi edilir": "treatable treatment",
    "egzama": "eczema", "sedef": "psoriasis",
    "varis": "varicose veins", "fibromiyalji": "fibromyalgia",
    "inme": "stroke", "bipolar": "bipolar disorder",
    "şizofreni": "schizophrenia", "otizm": "autism",
    "down sendromu": "down syndrome", "romatoid artrit": "rheumatoid arthritis",
    "safra kesesi": "gallbladder gallstone",
    # NOT (2026-08-29): Kullanicinin bizzat bulduğu bir örnek üzerine
    # (kullanici "trigliserid" hakkinda bir soru sordu, sistem taniyamadi)
    # temel kan tahlili degerleri icin ek tarama yapildi.
    "trigliserid": "triglyceride", "hba1c": "hba1c hemoglobin a1c",
    "tsh": "tsh thyroid stimulating hormone",
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

    # =========================================================================
    # KAPSAMLI GENISLETME (2026-08-29) — kullanicinin dogrudan talebi uzerine:
    # "sozluk hazinesini tum dunya geneline yaz". Icd10-cm PyPI paketinden
    # (95.622 ICD-10 kodu, 22 bolum) alinan bolum yapisi sistematik kapsam
    # cercevesi olarak kullanildi — asagidaki girdiler her bolumden yaygin,
    # gercekci saglik iddialarinda gecebilecek terimleri kapsar. ICD-10'un
    # kendisi Ingilizce oldugu icin dogrudan kullanilamadi (Turkce anahtar
    # gerekiyor) — Turkce terimler ve Ingilizce ceviriler dogrudan yazildi.
    # Bu hala TAM/kesin degil (tibbin tamami binlerce terim icerir) ama
    # onceki ~170 girisi ~450+'a cikararak kapsam ciddi olcude genisledi.
    # ICD-10 bolum numaralari asagida yorum olarak belirtildi.
    # =========================================================================

    # --- Bolum I: Enfeksiyon ve parazitik hastaliklar ---
    "kolera": "cholera", "tifo": "typhoid fever", "tüberküloz": "tuberculosis",
    "verem": "tuberculosis", "cüzzam": "leprosy", "boğmaca": "pertussis whooping cough",
    "difteri": "diphtheria", "tetanoz": "tetanus", "menenjit": "meningitis",
    "kızamık": "measles", "kızamıkçık": "rubella", "kabakulak": "mumps",
    "suçiçeği": "chickenpox varicella", "zona": "shingles herpes zoster",
    "uçuk": "cold sore herpes simplex", "hepatit": "hepatitis",
    "hepatit a": "hepatitis a", "hepatit b": "hepatitis b", "hepatit c": "hepatitis c",
    "sıtma": "malaria", "dang humması": "dengue fever", "sarı humma": "yellow fever",
    "zika": "zika virus", "lyme hastalığı": "lyme disease", "şarbon": "anthrax",
    "kuduz": "rabies", "tifüs": "typhus", "sifiliz": "syphilis",
    "bel soğukluğu": "gonorrhea", "gonore": "gonorrhea", "klamidya": "chlamydia",
    "kandida": "candida yeast infection", "uyuz": "scabies", "bit": "lice",
    "solucan": "intestinal worms", "tenya": "tapeworm", "giardia": "giardiasis",
    "toksoplazma": "toxoplasmosis", "kist hidatik": "hydatid cyst echinococcosis",
    "brusella": "brucellosis", "leptospiroz": "leptospirosis", "kızıl": "scarlet fever",
    "impetigo": "impetigo", "covid": "covid-19 coronavirus", "koronavirüs": "coronavirus",
    "mrsa": "mrsa antibiotic resistant staph",

    # --- Bolum II: Neoplazmlar (kanserler/tumorler) ---
    "akciğer kanseri": "lung cancer", "mide kanseri": "stomach cancer gastric cancer",
    "karaciğer kanseri": "liver cancer hepatocellular carcinoma",
    "yumurtalık kanseri": "ovarian cancer", "rahim kanseri": "uterine cancer endometrial cancer",
    "serviks kanseri": "cervical cancer", "rahim ağzı": "cervical cancer cervix",
    "mesane kanseri": "bladder cancer", "böbrek kanseri": "kidney cancer renal cancer",
    "deri kanseri": "skin cancer", "melanom": "melanoma", "lösemi": "leukemia",
    "lenfoma": "lymphoma", "beyin tümörü": "brain tumor", "kemik kanseri": "bone cancer",
    "tiroid kanseri": "thyroid cancer", "testis kanseri": "testicular cancer",
    "mezotelyoma": "mesothelioma", "sarkom": "sarcoma", "karsinom": "carcinoma",
    "iyi huylu": "benign tumor", "kötü huylu": "malignant tumor",
    "metastaz": "metastasis", "biyopsi": "biopsy", "radyoterapi": "radiotherapy radiation therapy",
    "immünoterapi": "immunotherapy", "tümör markırı": "tumor marker",

    # --- Bolum III: Kan hastaliklari ---
    "talasemi": "thalassemia", "orak hücre": "sickle cell anemia",
    "hemofili": "hemophilia", "trombositopeni": "thrombocytopenia",
    "lökopeni": "leukopenia", "nötropeni": "neutropenia",
    "pıhtılaşma bozukluğu": "blood clotting disorder coagulopathy",
    "tromboz": "thrombosis blood clot", "pulmoner emboli": "pulmonary embolism",
    "polisitemi": "polycythemia", "folik asit": "folic acid deficiency",
    "b12 eksikliği": "vitamin b12 deficiency",

    # --- Bolum IV: Endokrin/metabolik (ek) ---
    "hipoglisemi": "hypoglycemia",
    "hipertiroidi": "hyperthyroidism", "hipotiroidi": "hypothyroidism",
    "guatr": "goiter", "hashimoto": "hashimoto's thyroiditis",
    "graves hastalığı": "graves' disease", "addison hastalığı": "addison's disease",
    "cushing sendromu": "cushing's syndrome", "akromegali": "acromegaly",
    "hiperlipidemi": "hyperlipidemia", "metabolik sendrom": "metabolic syndrome",
    "paratiroid": "parathyroid", "testosteron": "testosterone",
    "östrojen": "estrogen", "progesteron": "progesterone", "prolaktin": "prolactin",

    # --- Bolum V: Ruh sagligi (ek) ---
    "obsesif kompulsif": "ocd obsessive compulsive disorder",
    "okb": "ocd obsessive compulsive disorder",
    "travma sonrası": "ptsd post traumatic stress disorder trauma",
    "tssb": "ptsd post traumatic stress disorder",
    "yeme bozukluğu": "eating disorder", "anoreksiya": "anorexia nervosa",
    "bulimia": "bulimia nervosa", "alkol bağımlılığı": "alcohol addiction alcoholism",
    "madde bağımlılığı": "substance abuse addiction",
    "sınırda kişilik": "borderline personality disorder",
    "sosyal fobi": "social phobia social anxiety", "agorafobi": "agoraphobia",
    "demans": "dementia", "alzheimer": "alzheimer's disease",

    # --- Bolum VI: Sinir sistemi (ek) ---
    "parkinson": "parkinson's disease", "multipl skleroz": "multiple sclerosis ms",
    "als": "als amyotrophic lateral sclerosis", "felç": "paralysis stroke",
    "nöropati": "neuropathy", "siyatik": "sciatica", "disk hernisi": "herniated disc",
    "fıtık": "hernia", "beyin sarsıntısı": "concussion", "tremor": "tremor",
    "baş dönmesi": "dizziness vertigo", "vertigo": "vertigo",
    "huntington hastalığı": "huntington's disease",
    "guillain-barre": "guillain-barre syndrome",

    # --- Bolum VII/VIII: Goz ve kulak ---
    "katarakt": "cataract", "glokom": "glaucoma", "miyop": "myopia nearsightedness",
    "hipermetrop": "hyperopia farsightedness", "astigmat": "astigmatism",
    "körlük": "blindness", "retina dekolmanı": "retinal detachment",
    "makula dejenerasyonu": "macular degeneration", "konjonktivit": "conjunctivitis",
    "işitme kaybı": "hearing loss", "kulak çınlaması": "tinnitus", "tinnitus": "tinnitus",
    "orta kulak": "otitis media ear infection",
    "meniere hastalığı": "meniere's disease", "kulak zarı": "eardrum tympanic membrane",

    # --- Bolum IX: Dolasim (ek) ---
    "kalp krizi": "heart attack myocardial infarction", "kalp yetmezliği": "heart failure",
    "aritmi": "arrhythmia", "atriyal fibrilasyon": "atrial fibrillation",
    "koroner arter": "coronary artery disease", "anjina": "angina",
    "kalp çarpıntısı": "heart palpitations", "damar tıkanıklığı": "artery blockage",
    "ateroskleroz": "atherosclerosis", "aort anevrizması": "aortic aneurysm",
    "kalp kapak": "heart valve disease", "kardiyomiyopati": "cardiomyopathy",

    # --- Bolum X: Solunum (ek) ---
    "koah": "copd chronic obstructive pulmonary disease", "bronşit": "bronchitis",
    "zatürre": "pneumonia", "pnömoni": "pneumonia", "akciğer fibrozu": "pulmonary fibrosis",
    "sinüzit": "sinusitis", "alerjik rinit": "allergic rhinitis hay fever",
    "bademcik iltihabı": "tonsillitis",

    # --- Bolum XI: Sindirim (ek) ---
    "reflü": "acid reflux gerd", "mide ülseri": "stomach ulcer peptic ulcer",
    "gastrit": "gastritis", "ishal": "diarrhea", "hemoroid": "hemorrhoids",
    "karaciğer yağlanması": "fatty liver disease", "siroz": "cirrhosis",
    "pankreatit": "pancreatitis", "crohn hastalığı": "crohn's disease",
    "ülseratif kolit": "ulcerative colitis",
    "irritabl bağırsak": "irritable bowel syndrome ibs",
    "apandisit": "appendicitis", "mide bulantısı": "nausea", "kusma": "vomiting",

    # --- Bolum XII: Deri (ek) ---
    "akne": "acne", "sivilce": "acne pimples", "siğil": "wart",
    "siğiller": "wart", "siğillere": "wart", "siğilleri": "wart",
    "vitiligo": "vitiligo", "ürtiker": "hives urticaria", "kurdeşen": "hives urticaria",
    "saç dökülmesi": "hair loss alopecia",

    # --- Bolum XIII: Kas-iskelet (ek) ---
    "skolyoz": "scoliosis", "bel ağrısı": "back pain", "boyun ağrısı": "neck pain",
    "tendinit": "tendinitis", "bursit": "bursitis", "kırık": "bone fracture",
    "burkulma": "sprain", "kas yırtığı": "muscle tear",

    # --- Bolum XIV: Urogenital (ek) ---
    "idrar yolu": "urinary tract infection uti",
    "mesane iltihabı": "cystitis bladder infection",
    "prostat büyümesi": "enlarged prostate bph", "böbrek yetmezliği": "kidney failure",
    "diyaliz": "dialysis", "endometriozis": "endometriosis", "miyom": "uterine fibroid",
    "kısırlık": "infertility",

    # --- Bolum XV: Gebelik ---
    "düşük": "miscarriage", "erken doğum": "premature birth",
    "preeklampsi": "preeclampsia", "gebelik diyabeti": "gestational diabetes",
    "doğum kontrolü": "birth control contraception", "emzirme": "breastfeeding",

    # --- Bolum XVIII: Semptomlar/bulgular ---
    "ateş": "fever", "öksürük": "cough", "yorgunluk": "fatigue",
    "kilo kaybı": "weight loss", "iştahsızlık": "loss of appetite",
    "şişlik": "swelling", "ödem": "edema swelling",

    # =======================================================================
    # GUNDELIK MARUZIYET + GIDA GUVENLIGI + BITKISEL (2026-09-27)
    # ---------------------------------------------------------------------
    # Bu blog'in konusu saglik; ozellikle ilac ve hastalik isimleri
    # sozluge girerken, kullanici sorularinin buyuk kismi HASTALIK DEGIL
    # "gunluk hayatta maruz kalinan sey" idi:
    #
    #   "zerdeçal iltihabı azaltır mı"
    #   "soğuk duş bağışıklığı güçlendirir mi"
    #   "mikrodalga yemeği zehirler mi"
    #
    # Ucunun de sozlukte KARSILIGI YOKTU — ozellikle "iltihap" (neredeyse
    # her tibbi iddianin cekirdegi), "zehir" ve "bitkisel" kavramlari. Bu,
    # onceki genisletmelerden (ICD-10 bolumleri) farkli bir SINIF boslugu:
    # sozluk hastalik/laboratuvar/besin yogundu, "maruziyet" (banyo,
    # giyinme, gida, cevresel kimyasal, ev yapimi bitkisel) ve bunlarin
    # saglik etkileri hic kapsanmiyordu. Asagida o sinif.
    #
    # KAPSAM KURALI: yalnizca saglik ETKISI sorulan sekillerde anlamli olan
    # kelimeler. Cok genel gunluk kelimeler ("yemek", "gıda", "dikkat",
    # "hareket" gibi) BILEREK disarida birakildi: bunlar "yemek yiyorum",
    # "gıda fiyatları arttı" gibi iddia olmayan mesajlari de saglik
    # konusu sanardi ve conversation.py'deki guvenlik kapisi tam da
    # bunlari elemek icin var.
    # =======================================================================

    # --- iltihap / agri (tum tibbi iddialarin cekirdek kavrami) ---
    "iltihap": "inflammation", "iltihabı": "inflammation",
    "anti-inflamatuar": "anti-inflammatory",
    "antioksidant": "antioxidant",
    "ağrı": "pain", "ağrıkesici": "analgesic painkiller",
    "kortizol": "cortisol",

    # --- bitkisel / baharat (en sik "X faydalı mı" iddialarının kaynagi) ---
    "zerdeçal": "turmeric curcumin", "kurkuma": "turmeric curcumin",
    "sarımsak": "garlic", "zencefil": "ginger", "tarçın": "cinnamon",
    "kekik": "thyme oregano", "maydanoz": "parsley", "soğan": "onion",
    "propolis": "propolis",
    "arı sütü": "royal jelly", "bitkisel": "herbal", "bitki çayı": "herbal tea",
    "baharat": "spice", "detoks": "detox",

    # --- gündelik maruziyet / yasam tarzi ---
    # NOT: "soğuk duş" ve "sıcak duş" IKI KELIMELIK anahtar olarak eklendi,
    # bare "soğuk" DEGIL — "bugün hava çok soğuk" bir saglik iddiasi
    # degil (bkz. yukaridaki kapsam kurali ve "göz atmak" notu).
    "soğuk duş": "cold shower cold water immersion",
    "sıcak duş": "warm shower hot water",
    "duş": "shower bathing",
    "soğuk havuz": "cold water swimming",
    "soğuk maruziyet": "cold exposure",
    "sauna": "sauna", "yüzme": "swimming",
    # NOT: bare "güneş" BILEREK yok — gundelik anlami hava durumu ("bugün
    # güneş çok güzel"). Saglik tarafi iki kelimelik anahtarlarla gelir.
    "güneş kremi": "sunscreen", "güneş ışığı": "sunlight sun exposure",
    "güneş çarpması": "sunstroke heat stroke", "güneşlenme": "tanning sun exposure",
    "bronzlaşma": "tanning", "ultraviyole": "ultraviolet",
    "uv ışın": "ultraviolet radiation",
    "hijyen": "hygiene", "el yıkama": "handwashing",
    "dezenfektant": "disinfectant",
    "uyku kalitesi": "sleep quality", "horlama": "snoring",
    "apne": "apnea sleep apnea", "enerji içeceği": "energy drink",

    # --- gida guvenligi / toksikoloji ---
    # NOT: "fırın" BILEREK yok — gundelik anlami firin/ekmek ("fırından
    # ekmek aldım"), saglik iddiasi degil.
    "mikrodalga": "microwave microwave radiation",
    "zehir": "poison toxicity", "zehirlenme": "poisoning intoxication",
    "toksik": "toxic", "toksin": "toxin", "kimyasal": "chemical",
    # NOT: bare "kurşun" BILEREK yok — "kurşun kalem" (pencil) ve mermi
    # anlamlari baskin. Metal anlami iki kelimelik anahtarla gelir.
    "kurşun zehirlenmesi": "lead poisoning heavy metal", "kurşunlu": "lead heavy metal", "kurşun maruziyeti": "lead exposure heavy metal",
    "cıva": "mercury heavy metal",
    "ağır metal": "heavy metal", "konservant": "preservative",
    "katkı maddesi": "food additive", "pesticit": "pesticide",
    "herbisit": "herbicide", "gıda güvenliği": "food safety",
    "kullanma süresi": "expiry date", "işlenmiş gıda": "processed food",
    "paketli gıda": "packaged food",
    "yapay tatlandırıcı": "artificial sweetener",

    # --- emilim / doz / yan etki (takviye iddialarinin ortak dili) ---
    "emilim": "absorption bioavailability", "biyoyararlanım": "bioavailability",
    "metabolizma": "metabolism", "doz": "dosage dose", "dozaj": "dosage",
    "yan etki": "side effect",

    # --- vucut olcumu / beyin ---
    "nabız": "pulse heart rate", "kalp atışı": "heart rate",
    "kan değeri": "blood test value",
    "beslenme": "nutrition diet", "besin": "nutrient",
    # NOT: bare "odak" BILEREK yok — "odak grubu" (focus group) yaygin bir
    # is/iletisim terimidir ve saglik konusu degildir. Ayni kavramin
    # saglik tarafi fiil koku ("odaklanma") ile yakalanir.
    "odaklan": "focus attention", "odaklanma": "focus concentration",
    "konsantrasyon": "concentration", "bilişsel": "cognitive",
    # NOT: bare "hafıza" BILEREK yok — "telefonumun hafızası doldu" (cihaz
    # bellegi) gundelik dilde saglik anlamindan daha sik.
    "hafıza kaybı": "memory loss", "unutkanlık": "forgetfulness memory",
}



def _normalize(text: str) -> str:
    """Türkçe karakterleri eşlenebilir forma indirgeme yapmadan küçültüp temizler.

    Tire (-) korunur: "glp-1" gibi sozlukte tire ile anahtarlanmis terimler
    (_TERM_MAP: "glp-1") tire silinirse iki ayri token'a ("glp", "1")
    bolunur ve hicbiri eslesmez — bu, konsolidasyon sirasinda (bkz. git
    gecmisi) fark edilen gercek bir regresyondu. Tek basina kalan bir
    "-" token'i (ör. cumle ici tire) zararsizdir; _matched_terms dongusu
    onu hicbir kategoriye sokmaz, sessizce dusurulur.
    """
    return re.sub(r"[^\w\s\-çğıöşüÇĞİÖŞÜ]", " ", text.lower()).strip()


# Sozlukte uzun terimler icin Turkce cekim eklerini tolera eden on-eslestirme:
# "kolesterolü" -> "kolesterol" (fark <= 2 karakter ve son harf sesli/ek harfi).
_MAX_SUFFIX_LEN = 3

# Turkce'de ek alirken kelimenin SONUNDaki unsuz yumusur ("unsuz
# yumusamasi"). Yalinca k/ğ/g ve ç/c gruplari icin gecerlidir ve — kritik
# olarak — degisim kelimenin SONUNDA gorunmez, cekimli formun ICINDE
# kalir:
#
#   "bağışıklık" → "bağışıklığı"   (son k, belirtme eki -ı'dan once ğ olur)
#   "çocuk"      → "çocuğu"        (k → ğ)
#   "ağaç"       → "ağacı"         (ç → c)
#
# Bu yuzden onceki katmanin on-eslestirmesi (token.startswith(key))
# bu formlari GOREMIYOR: kok artik token'in one basilmiyor, token
# kokun bir harfi degistirilmis hali. Canli testle bulundu: kullanicinin
# "soğuk duş bağışıklığı güçlendirir mi" sorusunda "bağışıklık"
# sozlukte ANCAK cekimsiz haliyle vardi, mesaj yine de saglik konusu
# olarak taninmiyordu.
#
# Cozum: sozluge her cekimli formu elle eklemek yerine, iki tarafi da
# ayni "unsuz sinifina" indirgeyip karsilastiriyoruz. Kapsam BILINCLI:
# yalnizca k/ğ/g ve ç/c. "ö/ü/u" birlesimi ek uyumu (unsuz yumusamasi
# DEGIL) ve sozluk anahtarlarinda tek bir yararli vakasi yok.
_FOLD_TABLE = str.maketrans({"k": "g", "ğ": "g", "c": "ç", "K": "g", "G": "g", "C": "ç"})
# Fuzzy katmanlarla ayni esik: kisa anahtarlar ("tuz", "ot", "göz") baska
# kelimelerin icinde yanlis eslesir.
_MIN_FOLDED_KEY_LEN = 4


def _fold_unsuz(word: str) -> str:
    """Kelimedeki yumusayan unsuzleri tek bir kanonik harfe indirger.

    "bağışıklık" -> "bağısi̇lıg" ..., yani sozluk anahtari ile onun cekimli
    formu ayni forma duser ve onceki katmanin on-eslestirme kurali
    (startswith + <=3 karakter fark) tekrar calisir.

    Kapsam: k/ğ/g -> g, ç/c -> ç. "glp-1", "d3", "10000" gibi rakam/tire
    iceren token'lar ceviri tablosunda zaten dokunulmaz (T'de gecis yok).
    """
    return word.translate(_FOLD_TABLE)


# Yumusatilmis kok -> deger indeksi. Sozlukten TURETILIR (elle
# yazilmaz), tek kelimelik ve >=4 karakterli anahtarlar icin. Iki-tokenli
# anahtarlar ("soğuk duş") _matched_terms'in iki-tokenli penceresinde
# zaten tam eslesmeyle yakalanir, buraya girmeleri gereksiz.
_FOLDED_TERM_MAP: dict[str, str] = {}
for _key, _value in _TERM_MAP.items():
    if " " in _key or len(_key) < _MIN_FOLDED_KEY_LEN:
        continue
    # setdefault: cakisma olursa ilk (sozluk sirasi) kazanir. Farkli
    # degerli bir cakisma yapisal bir hatadir ve
    # tests/test_term_map_expansion.py'de test edilir.
    _FOLDED_TERM_MAP.setdefault(_fold_unsuz(_key), _value)


# Tek basina token olarak eslesirse asiri genis/belirsiz oldugu icin izin
# listesinden kasitli olarak cikarilan parcalar (ör. "vitamin c" degerinin
# "c" parcasi — herhangi bir yalniz "c" harfini saglik konusu sanar).
_ALLOWED_EN_EXCLUDE: frozenset[str] = frozenset({"c"})

# Sozluk degerlerinden turetilen Ingilizce izin listesi: yalnizca bilinen
# kavram kelimeleri harici API'ye tasinir ("krizinden", "atmak" gibi ASCII
# yazilmis Turkce sozcukler boylece elenir).
_ALLOWED_EN: frozenset[str] = frozenset(
    piece
    for value in _TERM_MAP.values()
    if value
    for piece in value.split()
    if piece not in _ALLOWED_EN_EXCLUDE
)


def _match_term(token: str) -> str | None:
    """Once tam eslesme, sonra Turkce cekim ekini soyan on-eslestirme,
    sonra unSuz yumusamasi (asagida), son olarak (kurulu ise) Zemberek
    morfolojik kok bulma.
    """
    if token in _TERM_MAP:
        return _TERM_MAP[token]
    best: tuple[int, str] | None = None
    for key, value in _TERM_MAP.items():
        if len(key) >= 4 and token.startswith(key):
            diff = len(token) - len(key)
            if 0 < diff <= _MAX_SUFFIX_LEN and (best is None or diff < best[0]):
                best = (diff, value)
    if best:
        return best[1]

    # NOT (2026-09-27): Yukaridaki on-eslestirme katmani TUM cekimli
    # formlari yakalayamaz ve bunun sebebi sozluk boslugu DEGIL, yapISAL
    # bir sinir: Turkce'de ek alirken kelimenin son unsuzu yumusur
    # ("unsuz yumusamasi") ve bu degisim cekimli formun ICINDE kaldigi
    # icin token koke on-ekle basilmiyor — "bağışıklık" (sozlukte var)
    # "bağışıklığı" ile eslesmiyor, ayni sekilde "çocuk"→"çocuğu",
    # "ağaç"→"ağacı". Canli testle bulundu: kullanicinin "soğuk duş
    # bağışıklığı güçlendirir mi" sorusu bu yuzden saglik konusu olarak
    # taninmiyordu. Cozum: sozluk anahtarlarinin her cekimli formunu elle
    # eklemek yerine, iki tarafi da ayni unsuz sinifina indirgeyip
    # yukaridaki on-eslestirme kuralini TEKRAR uygulamak
    # (_fold_unsuz + _FOLDED_TERM_MAP).
    #
    # Bu katman onceki iki katmandan SONRA ve Zemberek'ten ONCE gelir:
    # Zemberek kuruluysa da ayni sonucu verir, ama katman OPSIYONEL bir
    # bagimliliga gore siralamamak icindir — 95MB'lik bir paketin
    # kurulu olup olmamasi eslesme sonucunu DEGISTIRMEDEN ayni davranis
    # uretir.
    folded = _fold_unsuz(token)
    if folded != token:
        if folded in _FOLDED_TERM_MAP:
            return _FOLDED_TERM_MAP[folded]
        best = None
        for key, value in _FOLDED_TERM_MAP.items():
            if folded.startswith(key):
                diff = len(folded) - len(key)
                if 0 < diff <= _MAX_SUFFIX_LEN and (best is None or diff < best[0]):
                    best = (diff, value)
        if best:
            return best[1]

    # NOT (2026-08-29): Yukaridaki iki katman (tam eslesme, >=4 karakterlik
    # anahtarlar icin <=3 karakterlik cekim-eki toleransi) her cekimli formu
    # yakalayamiyordu — ozellikle uzun cekim zincirleri ("kolesterolünü"
    # gibi, diff=3'u asabilir). Zemberek kurulu ise (opsiyonel bagimlilik,
    # bkz. turkish_morphology.py), kelimenin olasi morfolojik koklerinden
    # herhangi biri sozlukte varsa kullanilir — bu, sozluge her cekimli
    # formu elle eklemek yerine GENEL bir cozum. Zemberek kurulu degilse
    # (varsayilan kurulum) bu katman sessizce atlanir, davranis DEGISMEZ.
    #
    # len(key)>=4 sarti BILEREK korunuyor (ustteki katmanla ayni esik):
    # canli testle bulundu — Zemberek "bitmek" (fiil, "bitirmek/sona ermek")
    # icin gecerli bir kok olarak "bit" dondurebiliyor (fiil govdesi olarak
    # dogru), ama bu sozlukteki "bit" (isim, parazit) ile YAZIM OLARAK
    # cakisiyor. Zemberek kelime turunu (POS) filtrelemeden ham kok listesi
    # verdigi icin, kisa anahtarlari (< 4 karakter) bu katmandan haric
    # tutmak, ust katmanin zaten cozdugu ayni sinif hatayi (kisa
    # anahtarlarin baska kelimelerin icinde/govdesinde yanlislikla
    # eslesmesi) burada tekrarlamayi onler.
    for stem in get_candidate_stems(token):
        if len(stem) >= 4 and stem in _TERM_MAP:
            return _TERM_MAP[stem]
    return None


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


def has_turkish_term(text: str) -> bool:
    """Metinde sozlukt BIR TURKCE TERIM dogrudan geciyor mu?

    Amacı "sozde Turkce bir sorguyu sozlukten gecirmek" DEGIL, tam
    tersi: "sozde Turkce OLMAYAN bir sorguyu sozlukten gecirmekten"
    korumak. Metnin Turkce olup olmadigindan karar vermeye calisan
    basit kestirimler (bkz. v2/pipeline/pipeline.py'deki ozel karakter
    sayimi) kucuk iddialarda yanlis cevap veriyordu: "mikrodalga yemeği
    zehirler mi" metninde yalnizca 2 Turkce ozel karakter vardir ve
    kestirim onu "zaten Ingilizce" sayip sorguyu oldugu gibi birakiyordu
    — sozlukte "mikrodalga"/"zehir" olsa bile. Butun metnin Turkce
    oldugunu soyleyemeyiz; sozlukteki terimlerden en az birinin dogrudan
    gectigini soyleyebiliriz.

    DIKKAT: has_health_topic()'ten FARKLI — o fonksiyon sozluk
    DEGERLERINDEKI Ingilizce kelimeleri de kabul eder ("coffee
    cholesterol" icin True doner, cunku "coffee" ve "cholesterol"
    degerlerden gelir). Burada yalnizca TURKCE anahtarlara bakilir; boylece
    "Does coffee raise cholesterol?" gibi Ingilizce bir sorgu yanlis
    yere Turkce sayilmaz.
    """
    if not text:
        return False
    tokens = _normalize(text).split()
    for i, token in enumerate(tokens):
        if token in _TERM_MAP:
            return True
        if i + 1 < len(tokens) and " ".join(tokens[i:i + 2]) in _TERM_MAP:
            return True
    return False


def has_substantive_content(query: str) -> bool:
    """Sorguda arastirilabilir GERCEK bir icerik kelimesi var mi?

    NOT (2026-08-29): has_health_topic()'ten FARKLI, daha DUSUK bir bar —
    sozlukte olan bir SAGLIK terimi degil, herhangi bir anlamli kelime
    arar. conversation.py'deki has_health_topic kapisi, sozlukte
    taninmayan ama GERCEK bir soru olan mesajlari (ör. "trigliserid
    nedir?") arastirmaya izin verecek sekilde gevsetildiginde
    (is_interrogative kontrolu), yeni bir sinif hata ortaya cikti: "Bu
    doğru mu?" gibi baglamsiz, isaret-zamiri-tabanli sorular da
    dilbilgisel olarak "soru" sayildigi icin arastirmaya giriyor, ama
    HICBIR gercek konu icermedikleri icin arsivden rastgele/alakasiz
    sonuclar toplayip dusuk-ama-varolan bir "hukum" uretebiliyorlardı.
    Bu fonksiyon, dolgu kelimeleri (_QUESTION_FILLER) VE isaret
    zamirlerini (_DEMONSTRATIVE_PRONOUNS) cikardiktan sonra en az 3
    karakterlik bir kelime kalip kalmadigini kontrol eder — "bu",
    "doğru", "mu" hepsi elenir, geriye hicbir sey kalmaz.
    """
    tokens = _normalize(query).split()
    for t in tokens:
        if t in _QUESTION_FILLER or t in _DEMONSTRATIVE_PRONOUNS or t in _VERB_SUFFIXES:
            continue
        if len(t) >= 3:
            return True
    return False
