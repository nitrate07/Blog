# AI Altyapısı Envanteri (`evidence/`)

> Hazırlanma tarihi: 2026-08-24 · Dal: `main` · Amaç: bir sonraki geliştirme dalgası
> (Türkçe NLP, embedding tabanlı RAG, görsel analiz, ücretsiz/ucuz LLM seçenekleri)
> öncesinde **mevcut durumun** ölçülebilir envanteri. Bu belge yalnızca gözlem içerir;
> çözüm önerileri ayrı araştırma raporuna aittir.

---

## 1. Bağımlılıklar

Tek bağımlılık dosyası `evidence/requirements.txt`'dir. Repo kökünde `requirements.txt`
veya `pyproject.toml` yoktur; kökteki `Dockerfile` yalnızca bu dosyayı kurar
(`pip install -r evidence/requirements.txt`). Versiyonlar aralık olarak sabitlenmiştir
(alt/üst sınır), kesin pin (lock) yoktur:

| Paket | Kısıt | Rol |
|---|---|---|
| fastapi | >=0.115, <1.0 | REST API (`evidence/api.py`, `evidence/v2/api/`) |
| pydantic | >=2.7, <3.0 | Modeller/ayarlar (`evidence/models.py`, `evidence/config.py`) |
| httpx | >=0.27, <1.0 | Tüm dış HTTP çağrıları (LLM + kaynak ajanları) |
| uvicorn | >=0.30, <1.0 | ASGI sunucu |
| scikit-learn | >=1.5, <2.0 | TF-IDF vektörleştirme + cosine similarity (RAG) |
| numpy | >=2.0, <3.0 | TF-IDF matrisi kalıcılığı (`matrix.npy`) |
| pytest | >=8.0, <9.0 | Test |
| pytest-asyncio | >=0.23, <1.0 | Async test |

**Dikkat çekici eksikler:** Hiçbir resmi LLM SDK'sı yok (`anthropic`, `openai`,
`google-generativeai` kurulu değil); embedding kütüphanesi yok
(`sentence-transformers`, `transformers`, `torch` yok); vektör veritabanı yok
(`chromadb` yok — klasör adı `evidence/data/chroma/` olmasına rağmen ChromaDB
kullanılmaz); Türkçe NLP kütüphanesi yok; framework yok (LangChain/LlamaIndex:
tüm repoda `*.py`/`*.txt`/`*.toml` üzerinde grep → **0 eşleşme**, doğrulandı).

## 2. RAG / Arama Altyapısı

- **Algoritma: TF-IDF + kosinüs benzerliği** — embedding DEĞİL.
  `evidence/rag/store.py:22-27`: `TfidfVectorizer(max_features=10000,
  ngram_range=(1,2), stop_words="english", sublinear_tf=True)`;
  sorgu skoru `sklearn.metrics.pairwise.cosine_similarity`
  (`store.py:12`, `store.py:136`).
- **Kullanılan kütüphaneler:** yalnızca `scikit-learn` ve `numpy`. Harici bir
  vektör DB yok; `ArticleVectorStore` bellek-içi liste + sparse matris tutar,
  Chroma benzeri yanıt şeması üretir (`ids/documents/metadatas/distances`,
  `store.py:145-150`) ve `$and` / `$in` meta-filtrelerini kendisi uygular
  (`_match_where`, `store.py:152-164`).
- **Kalıcılık:** `evidence/data/chroma/` altında üç dosya: `ids.json`,
  `chunks.json`, `matrix.npy`. Matris her yazımda `.toarray()` ile **dense**
  kaydedilir (`store.py:97-98`); yüklenirken vocabulary/idf durumu korunmadığı
  için vektörizer aynı dokümanlarla yeniden `fit` edilir (`store.py:57-64`).
- **İndekslenen hacim** (`evidence/data/chroma/chunks.json` sayımı):
  - Toplam chunk: **756**
  - Benzersiz makale: **82**
  - Dil dağılımı: **378 EN + 378 TR** (birebir çeviri çiftleri)
  - Chunk türü: metadata **82**, body **514**, sources **101**, verdict **41**,
    evidence **18**
- `evidence/rag/retriever.py` (`ArticleRetriever`) makaleleri ayrıştırıp
  (`parse_all_articles`) indeksler; `retrieve()` meta-filtreli top-k döner,
  `build_context()` LLM için ~4000 karakterlik bağlam penceresi kurar.

## 3. Terim / İddia Çıkarma

Dosya: `evidence/chat/search_query.py`. Tamamen kural tabanlıdır, LLM kullanmaz.

- `_TERM_MAP` (TR→EN sağlık terimi sözlüğü): **117 anahtar**
  - Tek kelimelik: **107**
  - İki kelimelik bileşik kalıp: **10** — `vitamin c`, `c vitamini`,
    `göz sağlığı`, `göz tembelliği`, `baş ağrısı`, `soğuk algınlığı`,
    `adım sayısı`, `günlük adım`, `ağır kaldırma`, `uzun ömür`
- Yardımcı listeler: `_QUESTION_FILLER` (~50 soru/dolgu kelimesi),
  `_VERB_SUFFIXES` (~25 fiil kalıbı).
- Eşleşme davranışı: tam eşleşme + ≤3 karakterlik Türkçe çekim eki toleransı
  (`_MAX_SUFFIX_LEN = 3`, `_match_term` satır 138-148). Sözlükte olmayan
  Türkçe kelime **düşürülür**; hiç eşleşme yoksa orijinal sorgu döner.
- **Yapısal sınırlama (not):** Bugün düzeltilmiş yanlış-pozitifler — bare
  `"adım"`, bare `"göz"`, tek harf `"c"` — sözlükten **kasıtlı olarak
  çıkarılmıştır** (satır 56-58, 71-73, 91-95'teki yorumlar). Yani mimari,
  belirsiz kısa kelimeleri ancak "sözlükten silerek" koruyabiliyor; bağlam
  (POS, komşuluk) bilmeden ayırt edemiyor. Ayrıca aynı kavramın ikinci bir
  kopyası `evidence/v2/pipeline/pipeline.py:67`'de durur
  (`TURKISH_TO_ENGLISH_QUERIES`, **46 anahtar**) ve bu kopyada bare `"göz"`
  hâlâ mevcuttur — iki sözlük birbirinden sapmış durumdadır.

## 4. Kaynak Ajanları (`evidence/v2/sources/`)

21 ajan `__init__.py`'den dışa aktarılır; buna ek olarak 2 temel sınıf
(`health_base.py`, `journal_base.py`) ve `orchestrator.py` (paralel çalıştırma +
URL deduplasyonu) vardır. Dağılım:

**Doğrudan JSON/XML API çağıranlar (6):**

| Ajan | Ulaşım | Yöntem |
|---|---|---|
| `pubmed.py` | NCBI EUtils (`esearch/esummary/efetch.fcgi`) | HTTP API, XML parse (`ElementTree`) |
| `crossref.py` | `api.crossref.org/works` | HTTP API, JSON |
| `clinicaltrials.py` | `clinicaltrials.gov/api/v2/studies` | HTTP API, JSON |
| `fda.py` | `api.fda.gov/drug/label.json` (openFDA) | HTTP API, JSON |
| `europepmc.py` | `ebi.ac.uk/europepmc/webservices/rest/search` | HTTP API, JSON |
| `openalex.py` | `api.openalex.org/works` | HTTP API, JSON |

**Crossref üzerinden dolaylı erişen dergi/kurum sarmalayıcıları (8)** — tümü
`journal_base.py::CrossrefJournalAgent`; docstring'lere göre yayıncı siteleri
bot koruması (403) verdiği için Crossref meta verisine yönlendirilmişler:
`who.py` (IRIS 403 → Crossref), `cdc.py` (search.cdc.gov HTML döndürüyordu →
Crossref/MMWR), `cochrane.py` (api.cochrane.com DNS çözünmüyordu → Crossref),
`nejm.py`, `jama.py`, `lancet.py`, `bmj.py`, `aha.py`.

**HTML scraping yapanlar (6)** — hepsi `health_base.py::HealthOrgAgent`
alt sınıfı; arama sayfası HTML'i regex ile link/ayraç çıkarma yapar:
`ecdc.py` (`ecdc.europa.eu/en/publications-data`), `ema.py`
(`ema.europa.eu/en/search`), `esc.py` (`escardio.org` kılavuz sayfası),
`google_scholar.py` (`scholar.google.com/scholar`), `nice.py`
(`nice.org.uk/search`), `tuseb.py` (`tuseb.gov.tr/arama`).

**Ağ erişimi olmayan (1):** `archive.py` — yerel arşivi yukarıdaki RAG
retriever ile sorgular.

Tüm ajanlar `httpx` (async) kullanır; scraping ajanlarının dayanıklılığı hedef
sitelerin HTML yapısına bağlıdır.

## 5. LLM Sağlayıcıları

İki katman vardır; **her ikisi de resmi SDK yerine `httpx.AsyncClient` ile ham
HTTP POST kullanır.** Framework (LangChain/LlamaIndex vb.) kullanılmaz
(bknz. Bölüm 1 — 0 eşleşme).

`evidence/llm_providers.py` (sohbet + doğrulama):

| Sınıf | Varsayılan model | Endpoint | SDK? |
|---|---|---|---|
| `ClaudeProvider` (satır 283) | `claude-sonnet-5` | `https://api.anthropic.com/v1/messages` | Hayır — ham httpx, manuel `anthropic-version` başlığı |
| `OpenAIProvider` (satır 370) | `gpt-5.6-terra` | `https://api.openai.com/v1/chat/completions` | Hayır — ham httpx, Bearer başlığı |
| `GroqProvider` (satır 458) | `openai/gpt-oss-120b` | `https://api.groq.com/openai/v1/chat/completions` | Hayır — ham httpx, OpenAI-uyumlu Bearer başlığı |
| `GeminiProvider` (satır 546) | `gemini-3.7-flash` | `generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` | Hayır — ham httpx, `?key=` parametresi |

> **Güncelleme notu:** Bu envanterin ilk yazıldığı tarihte yalnızca 3
> sağlayıcı vardı; `GroqProvider` o zamandan beri eklendi ve
> `ai-infrastructure-roadmap.md`'de "yapılmadı" olarak listelenen Groq
> önerisi artık uygulanmış durumda (bkz. `evidence/tests/test_llm_providers.py::TestGroqProvider`,
> 50/50 test geçiyor). Model adları da güncel varsayılanlarla eşleşecek
> şekilde yukarıda düzeltildi.

Ortak temel `LLMProvider`, sohbet geçmişini kendisi yönetir (`Conversation`,
son 20 mesaj çifti), kararları JSON'dan `Verdict` enum'una ayrıştırır.

`evidence/providers.py` (yalnız doğrulama seam):
`AnthropicVerificationProvider` — yine ham httpx; Anthropic **tool-use**
(`report_verdict` zorunlu araç çağrısı) ile kısıtlı karar üretir, varsayılan
model `claude-haiku-4-5-20251001` (satır 61). Anahtar yoksa `NullProvider`
döner (deterministik yol). Seçim `evidence/provider_registry.py` üzerinden
`claude` / `openai` / `gemini` / `groq` isimleriyle yapılır; anahtarlar ortam
değişkenlerinden okunur (`evidence/config.py`).

Sonuç: 4 sağlayıcı (bunlardan biri, Groq, kalıcı ücretsiz katmana sahip) ×
1-2 katman = 4-5 farklı elle yazılmış HTTP istemcisi; streaming, yeniden
deneme, rate-limit gibi SDK özelliklerinin hiçbiri yok.

## 6. Görsel / Vision Desteği

**Yok. Sıfırdan eklenecek.** `evidence/` içinde resim işleyen kod bulunmadığı
doğrulandı: `PIL/Pillow`, `opencv/cv2`, `torch`, `transformers`,
`sentence_transformers` import'ları ve görsel dosya uzantısı işlemesi yok
(grep → yalnız iki ilgisiz eşleşme: `search_query.py:74` içindeki "eye health
vision" İngilizce arama terimi ve `v2/api/app.py:740` içindeki CSS SVG
arka-plan veri URI'si). Bağımlılık listesinde de görsel işlemeye uygun hiçbir
paket yok (Bölüm 1). Mevcut RAG yalnızca metin chunk'ları üzerindedir.

## 7. Test Kapsamı

`pytest evidence/tests evidence/v2/tests --collect-only -q` sonucu:

- **Toplam toplanan test: 359**
  - `evidence/tests/` : **274** test (19 dosya: rag_store/rag_parser/rag_api,
    llm_providers, providers, search_query, engine, pipeline, agents,
    health_agents, journal_base, connectors, cross_verify, security, api,
    chat_intents, editor, social_chat, models)
  - `evidence/v2/tests/` : **85** test (5 dosya: test_v2, test_adversarial,
    test_auto_index, test_integration, test_investigator_api)

---

## Gözlemlenen Mimari Sınırlamalar

Objektif gözlemler; çözüm içermez.

1. **TF-IDF, semantik değil leksikeldir.** Eş anlamlı/parafraz edilmiş sorgular
   ("kalp dostu" ↔ "cardiovascular benefit") yalnızca kelime örtüşmesi kadar
   yakalanır. `stop_words="english"` Türkçe metne de uygulanır ama Türkçe stop
   word listesi ve kök bulma (stemming) yoktur; ek zengin Türkçe morfolojisinde
   bu, eşleşmeyi sözlükteki yüzey forma daraltır. Çift dilli corpus (378+378)
   bu yüzden birebir çeviri çiftlerine dayanır.
2. **Ölçeklenebilirlik:** Matris her mutasyonda dense'e çevrilip tam dosya
   olarak yazılır ve her upsert/delete'te tüm corpus `fit_transform` ile
   baştan kurulur (`store.py:97-98`, `118-124`); `max_features=10000` üst sınırı
   vocabulary büyümesini sabitler. 82 makale / 756 chunk için sorun değil,
   büyüme eğrisinde maliyet artar.
3. **Terim sözlüğü ölçeklenmez.** 117 girişlik el yapımı sözlük + ≤3 karakterlik
   ek toleransı bağlam farkındalığına sahip değildir; yanlış-pozitiflerle mücadele
   bugüne dek girdi *silerek* yapıldı (`adım`, `göz`, `c`). Aynı kavramın ikinci,
   sapmış bir kopyası `v2/pipeline/pipeline.py`'de yaşar (46 giriş, bare `"göz"`
   dahil) — tek kaynak (single source of truth) yok.
4. **Framework yokluğunun iki yüzü:** Artı — minimal bağımlılık (8 paket),
   şeffaf akış, kolay test (359 test). Eksi — sohbet geçmişi, tool-use, retry,
   streaming, sağlayıcı soyutlamaları elle yazıldı ve 4 istemci arasında
   davranış tekrarı var; yeni bir sağlayıcı eklemek yeni bir ham HTTP istemcisi
   demek.
5. **Scraping kırılganlığı:** 6 ajan HTML regex'e, 8 ajan tek bir upstream'e
   (Crossref) bağlı; docstring'ler bu yönlendirmelerin birçoğunun zaten birer
   kesinti/403 tepkisi olduğunu gösteriyor (WHO IRIS, Cochrane DNS, CDC HTML).
6. **"Chroma" adlandırması yanıltıcıdır:** `evidence/data/chroma/` altında özel
   bir TF-IDF deposu vardır; gerçek bir vektör veritabanı veya embedding
   altyapısı yoktur.
7. **Görsel kanal tamamen boş:** Makale içi görsellerin doğrulanması, OCR ya da
   çok-modlu sorgulama için ne kod ne bağımlılık mevcut.
