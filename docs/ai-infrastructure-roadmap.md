# AI Altyapısını Güçlendirme — Araştırma Notu

> Hazırlanma tarihi: 2026-08-24 · Dal: `main` · Bu belge **eylem önerisi değil, araştırma
> notudur** — "daha sonra açıp bakalım" amacıyla yazıldı. [`ai-infrastructure-inventory.md`](ai-infrastructure-inventory.md)'deki
> "mevcut durum" tespitlerine karşılık, burada dışarıdaki somut açık kaynak/ücretsiz seçenekler
> listeleniyor. Hiçbiri şimdi uygulanmadı; hepsi ayrı, kendi PR'ını hak eden işler.

---

## Ek bulgu (bu notu hazırlarken doğrulandı): sözlük tekrarı hâlâ canlı

> **Çözüldü (2026-08-29):** İki sözlük birleştirildi —
> `evidence/v2/pipeline/pipeline.py`'deki `TURKISH_TO_ENGLISH_QUERIES` ve
> alt-dize/oran tabanlı eşleştirme tamamen kaldırıldı;
> `translate_query_to_english()` artık `evidence/chat/search_query.py`'deki
> tek, tokenize edilmiş `_TERM_MAP`'e delege ediyor. Aşağıdaki bulgu artık
> tarihsel — güncel kod tabanını yansıtmıyor.

`evidence/chat/search_query.py`'deki `_TERM_MAP`'ten bugün `"adım"`/`"göz"`/`"c"` bare
girdileri kaldırıldı (PR #26/#27). Ama **aynı kavramın ikinci, bağımsız bir kopyası**
`evidence/v2/pipeline/pipeline.py`'deki `TURKISH_TO_ENGLISH_QUERIES` sözlüğünde duruyor
(satır ~67, 46 giriş) ve orada **bare `"göz": "eye health vision macular degeneration"`
hâlâ mevcut**. Bu sözlük farklı bir eşleştirme algoritması kullanıyor (alt-dize/oran
tabanlı, `translate_query_to_english()`) ve muhtemelen farklı bir uç noktayı besliyor
(`/v1/verify` REST akışı, konuşmacı `/v1/investigator/chat` değil) — yani bugünkü sohbet
botu bug'ıyla birebir aynı tetiklenme yolunda değil, ama **aynı sınıf hatayı** başka bir
API yüzeyinde taşıyor olabilir. Kontrol edilip iki sözlüğün birleştirilmesi (ya da aşağıdaki
Türkçe NLP çözümlerinden biriyle ikisinin birden değiştirilmesi) gerekiyor.

---

## 1. Türkçe NLP — sözlük yerine gerçek morfoloji

Bugünkü "adım/göz/c" bug sınıfının kökü: kelimeleri bağlamsız, salt yüzey biçimiyle
eşleştirmek. Gerçek bir morfolojik çözümleyici bunu yapısal olarak çözer.

| Proje | Ne yapar | Lisans | Durum | Neden Arı Kaynak'a uyar |
|---|---|---|---|---|
| **Zeyrek** (`obulat/zeyrek`) | Zemberek'in saf Python portu — morfolojik analiz (kök+ek ayrıştırma) | permissive | Aktif, pip ile kurulur, JVM gerekmez | "adım" (step) ile "ad-ım" (isim+iyelik ekini) ek analiziyle ayırt eder — bugünkü sözlük-silme yamalarının yerini gerçek çözüm alır |
| **spaCy Türkçe modelleri** (`turkish-nlp-suite/turkish-spacy-models`, ör. `tr_core_news_trf`) | Tam pipeline: POS, bağımlılık ayrıştırma, NER, lemmatizer | MIT/spaCy-model | Aktif (HF üzerinde güncel) | En büyük kazanç: `_TERM_MAP`'in tamamının yerini gerçek varlık/iddia çıkarımı alabilir — "benim adım Ümit" bir isim-verme yapısı olarak ayrıştırılır, token eşleşmesi değil. Model ağırlıkları büyük (yüzlerce MB) |
| Zemberek-NLP (orijinal, Java) | Tam özellikli ama | Apache 2.0 | **Durgun** (son gerçek sürüm 2019) | JVM bağımlılığı + bakımsızlık nedeniyle Zeyrek'i tercih edin |

**Not:** İki sözlüğün (yukarıdaki "ek bulgu") birleştirilmesi bu araştırmadan bağımsız,
daha acil bir iş; Türkçe NLP kütüphanesi entegrasyonu ise onun yerini alacak daha büyük,
ayrı bir proje.

> **Kısmen uygulandı (2026-08-29, kullanıcı talebiyle "GitHub'da eksigimize uyan bir
> şey var mı" — `zemberek-python` bulundu):** Yukarıdaki tablodaki değerlendirme
> güncellenmeli — `zemberek-python` (PyPI, `Libr-AI` değil ayrı bir proje, Zeyrek'ten
> FARKLI ve ondan daha köklü bir Python portu) test edildi ve **Zeyrek'ten önemli
> ölçüde daha iyi** çıktı:
> - PyPI'dan doğrudan kurulur, **HuggingFace/internet erişimi gerekmez** — Zeyrek/spaCy
>   entegrasyonunun bu oturumda tıkandığı tam nokta buydu, artık aşıldı.
> - Karmaşık çekim zincirlerini ("kolesterolünü", "hastalıklarından", "trigliseridin")
>   doğru köke indirgiyor — bu, sözlüğe her çekimli formu elle eklemek yerine (önceki
>   PR'larda "aşı" için yapılan gibi) GENEL bir çözüm.
> - ~1.1ms/çağrı — gerçek zamanlı sohbet için pratik (tek seferlik ~4s başlatma
>   maliyeti hariç).
>
> **Uygulanan (dar, güvenli kapsam):** `evidence/chat/turkish_morphology.py` (opsiyonel,
> `requirements-turkish-nlp.txt`) — `evidence/chat/search_query.py`'nin `_match_term`
> fonksiyonuna üçüncü bir katman olarak eklendi: tam eşleşme ve karakter-bazlı çekim-eki
> toleransı başarısız olursa, Zemberek'in olası köklerinden biri sözlükte varsa kullanılır.
> Zemberek kurulu değilse (varsayılan kurulum) bu katman sessizce atlanır.
>
> **Kasıtlı olarak YAPILMAYAN (bulunan gerçek sınır):** Zemberek'in kendi cümle-bazlı
> disambiguator'ı da test edildi — "Benim adım Ahmet" örneğinde YANLIŞ kökü seçti
> (doğrusu "ad"+iyelik eki olmalıydı, "adım" (step) kelimesini seçti). Yani **tam
> disambiguation sorunu hâlâ çözülmedi** — bu modül bilerek disambiguation yapmıyor,
> yalnızca "bu kelimenin olası köklerinden biri sözlükte var mı" sorusuna cevap
> veriyor. Bu, kısa anahtarların (`len(stem)>=4` sınırı) homograf çakışmasına
> (`"bitmek"` fiil kökü `"bit"`, sözlükteki `"bit"` (parazit) ile yazım olarak
> çakışıyor — canlı testle bulunup düzeltildi) karşı korunarak güvenli tutuldu.
> spaCy tabanlı tam pipeline hâlâ ayrı, daha büyük bir proje olarak açık.
>
> 10 yeni test (`test_turkish_morphology.py`) — Zemberek kurulu olsun olmasın her
> ortamda çalışır (mock'lanan "kurulu değil" senaryosu + gerçek Zemberek testleri
> `skipif` ile korunur).

## 2. Açık kaynak fact-checking araçları

| Proje | Ne yapar | Neden ilgili |
|---|---|---|
| **ClaimBuster** (UT Arlington) | Ücretsiz API + açık ML kodu — "bu cümle gerçek bir iddia mı" sınıflandırması | Bugünkü "bu bir sağlık iddiası mı" güvenlik kapısını elle yazılmış sözlük yerine eğitilmiş bir sınıflandırıcıyla yapabilir. İngilizce eğitilmiş — Türkçe için önce çeviri ya da fine-tune gerekir |
| **Google Fact Check Tools API** (`Claim Search`) | Dünya çapındaki IFCN üyesi fact-check kuruluşlarının (teyit.org dahil, eğer ClaimReview yayınlıyorlarsa) birleşik indeksini sorgular | Mevcut 21 ajanın hiçbiri "başka fact-checker'lar bu iddia hakkında ne dedi" sormuyor — 22. ajan olarak eklenebilir, ücretsiz |
| **ClaimReview / schema.org** + Full Fact'in açık WordPress eklentisi | Fact-check içeriğini Google/Bing'in tükettiği standart formatta işaretler | Altyapı değil dağıtım kazanımı — Arı Kaynak'ın kendi makaleleri bunu yayınlıyor mu kontrol edilmeli |
| **Loki / OpenFactVerification** (`Libr-AI/OpenFactVerification`) | İddia bölme → önem kontrolü → arama sorgusu → kanıt toplama → atıflı doğrulama — kavramsal olarak `evidence/chat/`'in elle yaptığının aynısı | Doğrudan benimsemek yerine, iddia-bölme kodunu referans olarak okumak faydalı |
| **FEVER veri seti** | 185K etiketli iddia+kanıt (Wikipedia) | Entegre edilemez (İngilizce/Wikipedia) ama deterministik hüküm motorunun doğruluğunu **ölçmek** için hâlâ hiç kullanılmayan bir karşılaştırma seti olarak değerli |
| Teyit.org / doğrulukpayı.com | Türkiye'nin IFCN üyesi fact-check kuruluşları | Herkese açık API bulunamadı — programatik entegrasyon için doğrudan kendileriyle görüşülmesi gerekir |

## 3. Gerçek embedding tabanlı RAG (82 makale / 756 chunk ölçeğinde)

> **Durum güncellemesi (2026-08-29):** Bu bölümdeki `ChromaDB` önerisi artık
> uygulandı — `evidence/rag/chroma_store.py` (`ChromaArticleVectorStore`),
> `evidence/requirements-rag-chroma.txt`, `EVIDENCE_RAG_BACKEND=chroma`
> config anahtari (`evidence/config.py`), `evidence/v2/api/app.py`'de
> secim mantigi, ve `evidence/tests/test_chroma_store.py` (agir
> bagimliliklar kurulu degilse otomatik atlanan, kurulunca gercek
> ChromaDB + `paraphrase-multilingual-MiniLM-L12-v2` embedding ile calisan
> testler) hepsi mevcut. Varsayilan hala `tfidf` — Chroma opt-in
> (`EVIDENCE_RAG_BACKEND=chroma`), davranis degisikligi yok. Asagidaki
> Turkce embedding modeli onerileri (emrecan/... , TurkEmbed) henuz
> degerlendirilmedi/entegre edilmedi — varsayilan hala genel-amacli
> `paraphrase-multilingual-MiniLM-L12-v2`.

- **ChromaDB** — pip ile kurulur, Apache 2.0, aktif. <100K vektörde "3 satır kodla" yeterli
  bulunuyor. Envanterdeki `evidence/data/chroma/` klasör adı zaten Chroma'yı çağrıştırıyor
  ama şu an gerçek Chroma kullanılmıyor (bkz. inventory Bölüm 2, 6) — isim ile gerçeklik
  arasındaki farkı kapatmanın en doğal yolu bu.
- **Qdrant** — daha hızlı/güçlü ama Docker/ops yükü bu ölçekte gereksiz; arşiv büyük
  ölçüde büyürse değerlendirilebilir.
- **Türkçe embedding modelleri** (Chroma'ya beslenecek, TF-IDF yerine):
  - `emrecan/bert-base-turkish-cased-mean-nli-stsb-tr` — köklü, sentence-transformers uyumlu, güvenli başlangıç noktası.
  - **TurkEmbed** (2026, arXiv 2511.08376) — Türkçe morfolojisine özel fine-tune, daha yeni/araştırma aşamasında, kullanmadan önce HF'de gerçekten yayınlanmış mı kontrol edilmeli.
  - Tümü `sentence-transformers` ile yerelde, ücretsiz, API anahtarı gerektirmeden çalışır — RAG tarafı için "API anahtarı yok" kısıtını tamamen ortadan kaldırır.
  - **Not:** Uygulanan `ChromaArticleVectorStore` şu an bu Türkçe'ye özel
    modellerden birini değil, çok dilli genel-amaçlı
    `paraphrase-multilingual-MiniLM-L12-v2`'yi kullanıyor — bu üç seçenek
    hâlâ ayrı, yapılmamış bir değerlendirme/iyileştirme adımı.

## 4. Ücretsiz/ucuz LLM — üretim için gerçekçi seçenekler


> **Durum güncellemesi:** Aşağıdaki `GroqProvider` önerisi artık uygulandı —
> `evidence/llm_providers.py`, `evidence/provider_registry.py` ve
> `evidence/config.py`'ye eklendi, `evidence/tests/test_llm_providers.py`'de
> test kapsamı var (50/50 geçiyor), ve `.env.example` / README dosyaları
> güncellendi. Kalan tek adım: `console.groq.com`'dan gerçek bir API anahtarı
> alıp `EVIDENCE_GROQ_API_KEY` olarak ayarlamak — kod tarafı tamam.

Şu an hiçbir sağlayıcı (Claude/OpenAI/Gemini) için ücretli anahtar yok; bugün test için
opencode CLI'nin ücretsiz modeli kullanıldı (uygun ama zaman zaman kesintiye giren geçici
bir çözüm). Daha kalıcı, üretime uygun seçenekler:

| Sağlayıcı | Ücretsiz katman | Not |
|---|---|---|
| **Groq** | Kredi kartsız, **kalıcı** — 30 RPM / 30K TPM / günde 14.400 istek (Llama 3.1 8B, Llama 4 Scout, Qwen3 32B, DeepSeek R1 Distill) | Düşük trafikli bu site için muhtemelen test değil, gerçekten üretime yeter. `evidence/llm_providers.py`'deki `LLMProvider` soyut sınıfı zaten var — `GroqProvider` eklemek küçük, izole bir iş, mevcut `ClaudeProvider`/`OpenAIProvider` deseniyle birebir aynı şekilde |
| **Google AI Studio (Gemini)** | Kredi kartsız — Flash/Flash-Lite, günde ~1000 istek | `GeminiProvider` zaten kodda var; muhtemelen sadece ücretsiz bir anahtar kaydı yeterli, yeni kod gerekmeyebilir |
| **OpenRouter** | Tek anahtarla 14-20+ ücretsiz model, günde 50 istek | Groq'un günlük limiti dolarsa yedek/rotasyon seçeneği |

**En somut öneri:** Groq — kalıcı ücretsiz katmanı ve mevcut `LLMProvider` mimarisine
küçük bir eklemeyle uyması nedeniyle.

## 5. Görsel analiz (kısmen başlandı — bkz. inventory Bölüm 6 güncelleme notu)

> **Durum güncellemesi (2026-08-29):** İlk satırdaki Tesseract OCR önerisi
> uygulandı — `evidence/vision/ocr.py` (metin çıkarımı, fail-closed,
> güven skoru, boyut sınırları) + `evidence/chat/image_claim.py` (OCR
> çıktısını mevcut `has_health_topic`/dogrulama hattına bağlayan köprü),
> `evidence/requirements-vision.txt` (opt-in, Chroma ile aynı desen),
> 20 test (`test_ocr.py`, `test_image_claim.py`, Tesseract kurulu değilse
> otomatik atlanır). **Kapsam dışı bırakılan, hâlâ açık kısım:** bir HTTP
> upload endpoint'i (multipart form, boyut/rate-limit, güvenlik taraması)
> — bu ayrı, kendi PR'ını hak eden bir iş olarak bilinçli olarak
> yapılmadı. Tablodaki diğer 3 satır (modern OCR alternatifleri, vision
> LLM analizi, ters görsel arama/sahte-görsel tespiti) hâlâ tamamen açık.

| İhtiyaç | Açık kaynak/ücretsiz seçenek |
|---|---|
| Ekran görüntüsündeki metni çıkarma (viral bir haber/iddia görseli) | **Tesseract OCR** — olgun, aktif, Apache 2.0, Türkçe dahil 100+ dil. En basit ve en ucuz kazanım: metni çıkarıp mevcut metin-tabanlı iddia hattına sokmak **(uygulandı — `evidence/vision/ocr.py`)** |
| Ekran görüntüsü gibi düzensiz görsellerde daha iyi doğruluk | PaddleOCR / EasyOCR / docTR / Surya — Tesseract'a göre modern alternatifler, gerçek ekran görüntüsü örnekleriyle karşılaştırılıp seçilmeli |
| "Bu görselde ne var" analizi | **Claude/Gemini vision** — `ClaudeProvider`/`GeminiProvider` zaten kodda var, görsel-kodlama desteği eklemek gerekiyor (Bölüm 4'teki ücretsiz katmanlarla da çalışır) |
| "Bu görsel nereden geldi / ters görsel arama" | Açık kaynak, hazır bir "TinEye alternatifi" yok. En yakın açık desen: CLIP tabanlı embedding + vektör DB (Bölüm 3'teki Chroma ile aynı altyapı) — kendi arşivin içinde benzer görsel arama yapılabilir, gerçek "web'de bu görsel nerede kullanılmış" için ücretsiz/açık bir çözüm bulunamadı |
| Yapay zeka üretimi/sahte görsel tespiti | Araştırmada somut, kullanıma hazır bir açık kaynak proje/model bulunamadı — bu ihtiyaç şu an açık kaynak ekosisteminde karşılanmıyor gibi görünüyor, ayrı ve daha hedefli bir araştırma gerekebilir |

## 6. Ajan orkestrasyon framework'ü (LangGraph vb.)

**Öneri: şimdilik atlanmalı.** LangGraph incelendi (model-agnostik, mevcut elle yazılmış
`LLMProvider`larla çalışabilir, ücretsiz/lokal kullanılabilir) ama envanterdeki mevcut
`SourceOrchestrator` + `Planner` + `EvidenceInvestigator` zaten benzer işi yapıyor ve 359
testle iyi kapsanmış durumda (bkz. inventory Bölüm 7). Bir framework'ün asıl kazandırdığı
şey — dallanma, yeniden deneme, insan-döngüde onay karmaşıklığı — şu an bu projede
gözlenmiyor. Görsel analiz gerçekten farklı bir dallanma eklerse (Bölüm 5) o zaman tekrar
değerlendirilebilir.

## 7. İddia bölme (claim decomposition) — GPT-Researcher'dan uyarlandı (2026-08-29)

**Uygulandı.** Kullanıcı talebi üzerine ("araştırma butonu çok sağlam ve ileri düzeyde
olmalı, GitHub'daki açık kaynaklara bak") en popüler açık kaynak "deep research" ajanı
incelendi: `assafelovic/gpt-researcher` (GitHub, 28k+ yıldız, Apache-2.0). Mimarisi:
**Planner** iddiayı birden fazla alt-soruya böler → **Execution** ajanları her birini
PARALEL araştırır → **Publisher** bulguları birleştirir. Bizim sistemde tek bir dar
İngilizce sorgu tüm dış kaynaklara gidiyordu — bu, iddianın farklı yönlerini (mekanizma,
karşılaştırmalı çalışma, hedef popülasyon, meta-analizler) kaçırabilirdi.

Eklenenler:
- `evidence/chat/planner.py`: `_decompose_claim()` (LLM'e tool-calling ile 2-4 farklı
  İngilizce arama açısı ürettirir, `editor.py`'deki aynı yapısal-güvenli desen — şema
  kısıtlı, doğrulanmış, başarısızlıkta boş liste), `Planner.augment_with_subquestions()`
  (bu alt-soruları planın zaten paralel çalışan `_run_steps_parallel`'ine ek
  `SEARCH_EXTERNAL` adımları olarak ekler).
- `evidence/chat/conversation.py`: LLM sağlayıcı mevcutsa (Groq gibi ücretsiz katman
  dahil) `VERIFY_CLAIM` niyeti için bu genişletme otomatik devreye giriyor.
- `evidence/chat/investigator.py`: `_categorize_results`'a URL bazlı tekilleştirme
  eklendi — birden fazla alt-soru aynı makaleyi bulursa "X kaynak incelendi" sayısı
  şişmiyor.

**Fail-closed tasarım:** LLM yoksa (`llm_provider=None`, örn. Groq anahtarı ayarlı
değilse) plan hiç değişmez — mevcut tek-sorgulu davranış aynen korunur. Bu, projenin
genel `NullProvider` felsefesiyle tutarlı: özellik LLM'siz kurulumlarda sessizce
devre dışı kalır, hiçbir şeyi bozmaz.

19 yeni test (`test_claim_decomposition.py`). Canlı doğrulandı: sahte bir tool-calling
sağlayıcıyla planın 4 adımdan 6 adıma çıktığı, 2 yeni adımın farklı araştırma açılarını
(mekanizma, karşılaştırmalı deneme) hedeflediği doğrulandı.

## 8. Sayısal-tutarlılık güvenlik ağı + Türkçe tokenizer hatası — humanchaos/factcheck'ten uyarlandı (2026-08-29)

**Uygulandı.** Aynı GitHub taramasında incelenen `humanchaos/factcheck` projesinde
somut bir güvenlik mekanizması bulundu: iddia edilen bir sayısal değer (yüzde/kat)
kanıttaki değerden ≥10x farklıysa, hüküm otomatik olarak geçersiz kılınıyor
("math_outlier") — LLM'lerin büyük sayılarda halüsinasyon görme eğilimine karşı.
Bizim `evidence/engine.py`'deki `compare_claim_evidence` (hem `/v1/verify` hem
`evidence/chat/conversation.py`'nin kullandığı çekirdek karşılaştırma motoru) bu
kontrolü **hiç yapmıyordu** — yalnızca kelime örtüşmesine bakıyordu. Yani "kahve
kanseri %500 artırır" gibi bir iddia, kanıt yalnızca "%15 artış" gösterse bile kelime
örtüşmesi yeterliyse "Destekleniyor" diyebiliyordu.

Eklenen: `check_numeric_consistency()` — iddia ve en alakalı pasajdaki AYNI BİRİMLİ
(yüzde-yüzde, kat-kat — birimler arası dönüşüm bilerek yapılmıyor, kendi
varsayım hatamızı güvenlik kontrolüne sokmamak için) sayısal büyüklükleri
karşılaştırır; oran ≥5x ise (humanchaos/factcheck'in 10x'inden biraz daha temkinli)
hüküm `UNSUPPORTED`'a düşürülür — kelime örtüşmesi ne kadar yüksek olursa olsun.

**Ek bulgu (bu çalışma sırasında tesadüfen bulundu):** `_tokens()` fonksiyonunun
regex'i (`[a-z0-9]+`) yalnızca ASCII karakter yakalıyordu — Türkçe özel karakterler
(ç, ğ, ı, ö, ş, ü) kelime sınırı sayılıp kelimeleri parçalıyordu (`"sağlığına"` tamamen
kayboluyor, `"gösteriyor"` → `"steriyor"` oluyordu). Bu, fonksiyonun TÜM Türkçe
metin karşılaştırmasını sessizce bozan sistemik bir hataydı. Regex'e Türkçe karakterler
eklendi, `_NEGATIONS`/`_QUALIFIERS` setlerine de yaygın Türkçe kelimeler
(`"değil"`, `"yok"`, `"olabilir"` vb.) eklendi. **Kalan, çözülmemiş kısım:** fiil-eki-
tabanlı Türkçe olumsuzlama (`"gelmediğini"` gibi) hâlâ yakalanamıyor — bu, tam Türkçe
morfoloji gerektirir (bkz. Bölüm 1'deki Zeyrek sınırlaması, aynı kök sorun).

16 yeni test (`test_numeric_consistency.py`). Doğrudan `compare_claim_evidence`
üzerinde kapsamlı doğrulama yapıldı (bu fonksiyonun daha önce hiç testi yoktu).

---

## Özet — inventory'deki 7 sınırlamaya karşılık gelen seçenekler

> **Durum (2026-08-29):** Asagidaki tablo bu notun ilk yazildigi tarihteki
> durumu yansitiyor. O tarihten beri tamamlananlar: satir 1 (Chroma —
> bkz. Bölüm 3 guncelleme notu), satir 3'un "iki sapmış kopya" kısmı
> (evidence/chat/search_query.py ve evidence/v2/pipeline/pipeline.py'deki

> sözlükler birleştirildi), ve Bölüm 4'teki Groq önerisi. Kalan acik
> kalemler: satir 1'in Turkce-ozel embedding modeli kismi (halen genel-
> amacli model kullaniliyor), satir 3'un Zeyrek/spaCy-tr morfoloji kismi,
> satir 5 (kaynak ajani saglamlastirma), satir 7 (gorsel kanal).

| Inventory'deki sınırlama | Bu nottaki karşılığı |
|---|---|
| 1. TF-IDF leksikeldir, semantik değil | Bölüm 3 — Chroma (**uygulandı**, opt-in) + Türkçe embedding modeli (**hâlâ açık**) |
| 2. Matris her mutasyonda baştan kuruluyor | Chroma'ya geçiş bunu da native olarak çözer (**uygulandı**) |
| 3. Terim sözlüğü ölçeklenmiyor + iki sapmış kopya var | Bölüm 1 — Zeyrek/spaCy-tr (**hâlâ açık**); iki kopyanın birleştirilmesi (**uygulandı**) |
| 4. Framework yokluğunun artı/eksisi | Bölüm 6 — şimdilik framework'süz devam, LangGraph rezervde |
| 5. Scraping kırılganlığı (6 ajan HTML, 8 ajan Crossref'e bağımlı) | Retry/backoff **uygulandı** (paylaşılan `get_with_retry`); regex kırılganlığı da **uygulandı** (6 ajan BeautifulSoup'a taşındı) — **kalem tamamen kapandı** |
| 6. "Chroma" adlandırması yanıltıcı | Bölüm 3 — gerçek Chroma'ya geçiş adı gerçeğe uydurdu (**uygulandı**) |
| 7. Görsel kanal tamamen boş | Bölüm 5 — **kısmen uygulandı** (Tesseract OCR metin çıkarımı); vision-LLM analizi ve ters görsel arama hâlâ açık |
