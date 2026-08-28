# Arı Kaynak — Kanıt Doğrulama Altyapısı

Arı Kaynak, kanıt öncelikli bir doğrulama katmanıdır, genel amaçlı bir chatbot değildir. Belirli bir iddiayı alır, bağımsız kaynakları getirir, ilgili pasajı çıkarır, kaynak kalitesini değerlendirir ve kısıtlı bir karar verir. Çalışma ilkesi: **kanıt yoksa, güvenilir karar da yoktur.**

Belirleyici karşılaştırma denetlenebilir ve muhafazakardır; isteğe bağlı LLM sağlayıcıları `VerificationProvider` protokolünü uygular ve kamu API sözleşmesini değiştiremez. Kamu API varsayılan olarak API anahtarı gerektirir. LLM anahtarı gerekmez — sağlayıcı yapılandırılmamışken sistem belirleyici karşılaştırma ile çalışır.

## Mimari

```
Yapay Zeka / ajan -> Kanıt API -> güvenli kaynak getirme -> kaynak kalitesi
           -> kanıt çıkarma -> belirleyici karşılaştırma -> karar + atıf
           -> [isteğe bağlı] LLM doğrulama -> gelişmiş karar
```

`EvidenceVerifier` orkestrasyonu yönetir. `SourceFetcher` SSRF-güvenli getirme ve çıkarmayı yönetir. `llm_providers.py` Claude, OpenAI ve Gemini uygulamalarını içerir. `provider_registry.py` yapılandırmadan sağlayıcılar oluşturur. Sistem kanıt önceliklidir: LLM sağlayıcıları belirleyici karşılaştırmayı asla değiştirmez, yalnızca geliştirir.

## API

Yerel çalıştırma (Python 3.11+):

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r evidence/requirements.txt
uvicorn evidence.api:app --reload
```

Geliştirme dışı sunucu başlatmadan önce, dağıtım gizli mağazanızda güçlü bir özel başlangıç anahtarı ayarlayın:

```bash
export EVIDENCE_BOOTSTRAP_API_KEY="en-az-32-karakterlik-rastgele-bir-sir"
```

Her `/v1/*` isteğinde `X-API-Key` olarak gönderin. Depolanmadan önce karma_rsa; ham değer asla SQLite'e veya denetim kayıtlarına yazlmaz. `EVIDENCE_REQUIRE_API_KEY=false` yalnızca yerel geliştirme ve testler içindir.

`POST /v1/verify`

```json
{
  "claim": "Doğrulanması gereken bir iddia",
  "sources": [{"url": "https://ornek.com/kaynak"}],
  "context": "İsteğe bağlı bağlam"
}
```

Yanıt yalnızca `supported`, `partially_supported`, `unsupported` veya `unverified` içerir. Çıkarılan pasajları, kaynak URL'sini, kaynak türünü, ilgiyi, kaynak-içerik karma değerini, muhafazakar güven değerini ve ISO-8601 `checked_at` zamanını döndürür. Her sonucun bir `verification_id`'si vardır; `GET /v1/verifications/{verification_id}` ile değişmez kaydını alın. Yetersiz ilgili kanıt `unverified` üretir, tahmin değil.

`GET /v1/search?query=...` atıf yapılabilecek metadata için PubMed ve Crossref'i arar. Arama sonuçları keşif adaylarıdır, **kanıt değildir**: bir ajan bir aday kaynağı alıp `/v1/verify`'e göndermeden önce ona güvenmemelidir. Endpoint, doğrulama ile aynı API anahtarı ve hız sınırlama politikasını kullanır.

## Kaynak kalitesi

- `primary`: resmi kurumlar, düzenleyici belgeler, orijinal araştırma/veri ve resmi belgeler
- `secondary`: sistematik derlemeler, incelemeler, saygın analizler
- `tertiary`: bloglar, sosyal medya, toplayıcılar, kaynaksız özetler
- `unknown`: sınıflanmamış kaynaklar

Kalite, güveni ve bağ决胜 belirlemeyi etkiler; asla doğrudan kanıtın yerini tutmaz.

## MCP araçları

`evidence.mcp` şu yapılandırılmış JSON araçlarını sunar:

- `verify_claim(claim, sources, context)`
- `search_evidence(query)` — bu URL-kaynak MVP'sinde kasıtlı olarak arama arka planı raporlamaz
- `get_source(url)`
- `compare_evidence(claim, evidence)`

`search_evidence` PubMed/Crossref metadata'sını keşfeder ve bunu açıkça kanıt dışı olarak etiketler. `create_mcp_server()`, isteğe bağlı MCP paketi yüklüyken FastMCP sunucusu oluşturur; aksi takdirde aynı çağrılabilir araç yüzeyini döndürerek çekirdeği hafif ve test edilebilir tutar.

## Güvenlik

Uzak kaynaklar, gömülü kimlik bilgisi içermeyen herkese açık `http`/`https URL'leri olmalıdır. Geri döngü, özel/ayırtlmış IP'ler, yerel ana bilgisayar adları ve herkese açık olmayan adreslere çözümleyen DNS adları reddedilir. Getirme zaman aşımları, sınırlı bir yanıt gövdesi, sabit bir yönlendirme sınırı kullanır ve her yönlendirme hedefini yeniden doğrular. Herkese açık dağıtım için, bağlantı zamanında DNS yeniden bağlama saldırılarına karşı savunmak için özel adres aralıklarını engelleyen bir çıkış proxy'si üzerinden getirme çalıştırın.

Doğrulama kayıtları, API anahtarı kimliği, gönderilen iddianın karma değeri (ham iddia değil), sonuç metadata'sı, kanıt pasajı, kaynak URL/türü, içerik karma değeri ve yakalama zamanı ile SQLite'ta depolanır. API anahtarları karma_rsa edilir ve başarılı doğrulamalar minimum bir denetim olayı üretir. Dahil edilmiş sınırlayıcı süreç bazlıdır; çoklu işçi çalıştırırken bir ağ geçidi veya Redis destekli sınırlayıcı kullanın.

## Testler

```bash
pytest evidence/tests -q
```

Testler desteklenen, kısmen desteklenen, çelişen ve yetersiz kanıtı; kaynak-kalite sıralamasını; özel URL reddini ve FastAPI doğrulama/yanıt形状'ını kapsar.

## LLM Sağlayıcı Entegrasyonu

Sistem, gelişmiş kanıt doğrulama için isteğe bağlı LLM sağlayıcılarını destekler. Yapılandırıldığında, LLM sağlayıcı kanıt-eşleştirme çiftlerini analiz eder ve bir karar verir. LLM başarısız olursa veya yapılandırılmamışsa, sistem belirleyici karşılaştırma motoruna geri döner.

### Desteklenen Sağlayıcılar

| Sağlayıcı | Varsayılan Model | API Anahtarı Env Değişkeni | Model Env Değişkeni |
|-----------|-----------------|---------------------------|---------------------|
| Claude | claude-sonnet-5 | `EVIDENCE_CLAUDE_API_KEY` | `EVIDENCE_CLAUDE_MODEL` |
| OpenAI | gpt-5.6-terra | `EVIDENCE_OPENAI_API_KEY` | `EVIDENCE_OPENAI_MODEL` |
| Gemini | gemini-3.7-flash | `EVIDENCE_GEMINI_API_KEY` | `EVIDENCE_GEMINI_MODEL` |

### Yapılandırma

İki yaklaşım — sağlayıcıya özgü (önerilen) veya genel:

```bash
# Sağlayıcıya özgü (aynı anda birden fazla sağlayıcı yapılandırılmasına izin verir)
export EVIDENCE_CLAUDE_API_KEY=your-anthropic-key
export EVIDENCE_CLAUDE_MODEL=claude-sonnet-5  # isteğe bağlı

export EVIDENCE_OPENAI_API_KEY=your-openai-key
export EVIDENCE_GEMINI_API_KEY=your-google-key

# Genel geri dönüş (sağlayıcıya özgü ayarlanmadığında kullanılır)
# export EVIDENCE_LLM_PROVIDER=claude
# export EVIDENCE_LLM_API_KEY=your-key
# export EVIDENCE_LLM_MODEL=claude-sonnet-5
# export EVIDENCE_LLM_TEMPERATURE=0.0
# export EVIDENCE_LLM_MAX_TOKENS=256
```

Sistem etkin sağlayıcıyı otomatik algılar: sağlayıcıya özgü ortam değişkenleri önce gelir, ardından `EVIDENCE_LLM_PROVIDER`, ardından yapılandırılmış bir API anahtarına sahip ilk sağlayıcı.

### Sağlayıcı Durumu API

```bash
# Hangi sağlayıcıların yapılandırıldığını kontrol edin
curl http://localhost:8000/v1/provider/status

# Sağlayıcı bağlantısını test edin
curl -X POST http://localhost:8000/v1/provider/test/claude
```

### Nasıl Çalışır

1. **Kaynak getirme**: Sistem, sağlanan kaynak URL'lerinden metin getirir ve çıkarır
2. **Belirleyici karşılaştırma**: Token örtüşmesi ve anahtar kelime eşleştirmesi ilk karar üretir
3. **LLM doğrulama** (yapılandırılmışsa): LLM, çıkarılan pasaja karşı iddiayı analiz eder
4. **Nihai karar**: LLM kararı önceliklidir; belirleyici karar geri dönüş olarak kullanılır

### Sağlayıcı Mimarisi

```python
from evidence.provider_registry import create_provider_from_config, create_provider

# Ortamdan otomatik oluşturma (önerilen)
provider = create_provider_from_config()

# Veya açıkça oluşturun
provider = create_provider(
    provider_name="claude",
    api_key="your-key",
    model="claude-sonnet-5",
)

# Sağlık kontrolü
status = await provider.health_check()
# {"status": "ok", "provider": "ClaudeProvider", "model": "claude-sonnet-5", ...}

# Veya doğrudan kullanın
from evidence.llm_providers import ClaudeProvider
provider = ClaudeProvider(api_key="your-key")
```

### Özel Sağlayıcılar

`VerificationProvider` protokolünü uygulayın:

```python
from evidence.providers import VerificationProvider
from evidence.models import Verdict

class MyCustomProvider:
    async def compare(self, claim: str, passage: str, context: str | None = None) -> Verdict | None:
        # Mantığınız burada
        return Verdict.SUPPORTED

    async def health_check(self) -> dict:
        return {"status": "ok", "provider": "MyCustomProvider", "model": "custom"}
```

### Güvenlik

- API anahtarları ortam değişkenlerinden yüklenir, asla depoya-commit edilmez
- LLM sağlayıcıları zarif şekilde başarısız olur — doğrulama belirleyici karşılaştırma ile devam eder
- Sağlayıcı kimlik bilgileri dağıtım sırlarına aittir, asla bu depoda değildir

## RAG — Anlamsal Makale Arama

RAG sistemi, TF-IDF vektör gömme'utilisation tüm Arı Kaynak makaleleri üzerinde anlamsal arama sağlar.

### Nasıl Çalışır

1. **Ayrıştırıcı** (`rag/parser.py`): Makale HTML'inden yapılandırılmış parçacıklar çıkarır — metadata, gövde bölümleri, kararlar ve kaynaklar — ClaimReview yapılandırılmış verisiyle
2. **Vektör Mağazası** (`rag/store.py`): scikit-learn ile TF-IDF gömmeleri, kosinüs benzerliği arama, disk kalıcılığı
3. **Getirici** (`rag/retriever.py`): Sorgu → göm → ara → filtrele → LLM tüketimi için bağlam oluşturma

### API Uç Noktaları

```bash
# Tüm makaleleri dizin edin (EN + TR)
curl -X POST http://localhost:8000/v1/rag/index -H "X-API-Key: your-key"

# Anlamsal arama
curl -X POST http://localhost:8000/v1/rag/query \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"query": "statin kas ağrısı nocebo", "n_results": 5, "language": "tr"}'

# Hızlı arama (GET)
curl "http://localhost:8000/v1/rag/search?q=egzersiz+kalp+sağlığı&language=tr" \
  -H "X-API-Key: your-key"

# Dizin istatistikleri
curl http://localhost:8000/v1/rag/stats -H "X-API-Key: your-key"
```

### Sorgu Seçenekleri

| Alan | Tür | Açıklama |
|------|-----|----------|
| `query` | string | Arama metni (min 3 karakter) |
| `n_results` | int | Sonuç sayısı (1-20, varsayılan 5) |
| `language` | string | `en` veya `tr` ile filtrele |
| `category` | string | Kategori ile filtrele (Sağlık, Egzersiz, Beslenme, vb.) |

### Yanıt Şekli

```json
{
  "query": "statin kas ağrısı",
  "context": "FILE No. en:samson-trial... | Karar: Destekleniyor (5/5)\n...",
  "results": [
    {
      "article_id": "en:samson-trial-statin-nocebo",
      "title": "Statın Kas Ağrısının %90'ı gerçekten 'Başınızda mı'?",
      "verdict": "Destekleniyor",
      "rating_value": 5,
      "distance": 0.42,
      "source_url": "https://nitrate07.github.io/Blog/makaleler/samson-trial-statin-nocebo.html"
    }
  ],
  "total_results": 5
}
```

`context` alanı, RAG hatlarında LLM bağlamı olarak doğrudan kullanım için önceden biçimlendirilmiştir.

### Yapılandırma

```bash
# RAG ayarları (isteğe bağlı, varsayılanlar gösteriliyor)
export EVIDENCE_RAG_PERSIST_DIRECTORY=evidence/data/chroma
export EVIDENCE_RAG_ARTICLES_DIR=articles
export EVIDENCE_RAG_TR_DIR=tr/makaleler
export EVIDENCE_RAG_MAX_RESULTS=10
export EVIDENCE_RAG_MAX_CONTEXT_LENGTH=4000
```

### Dizin Oluşturma

`POST /v1/rag/index` çağrısıyla tüm makaleleri (yeniden) dizinleyin. Dizin, `articles/` ve `tr/makaleler/` dizinlerinden oluşturulur. Her makale parçacıklara ayrılır: metadata, gövde bölümleri (başlığa göre), karar ve kaynaklar. Aynı İngilizce makale kimliğine sahip Türkçe makaleler ayrı olarak depolanır.

### Bağımlılıklar

- `scikit-learn` — TF-IDF vektörleştirici + kosinüs benzerliği
- `numpy` — matris işlemleri

GPU veya harici gömme hizmeti gerekmez. TF-IDF modeli tamamen süreç içinde çalışır.

## Çapraz Doğrulama — Çoklu Kaynak Kanıt Keşfi

Çapraz doğrulama sistemi,birden fazla kanıt kaynağını aynı anda arar ve sonuçları tek bir raporda birleştirir.

### Nasıl Çalışır

1. **Paralel arama**: PubMed, Crossref ve mevcut Arı Kaynak makalelerini eş zamanlı olarak sorgular
2. **Kaynak birleştirme**: Tüm kaynaklardan sonuçları tekrarlar ve birleştirir
3. **Kapsama puanlama**: Kaynak çeşitliliğine ve sayısına dayalı bir güven puanı hesaplar
4. **Özet oluşturma**: Bulguların insan tarafından okunabilir bir özetini üretir

### API Uç Noktası

```bash
# Bir iddiayı çapraz doğrulayın
curl -X POST http://localhost:8000/v1/cross-verify \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"claim": "statin ilaçları hastaların %90'ında kas ağrısına neden olur"}'
```

### İstek Gövdesi

| Alan | Tür | Varsayılan | Açıklama |
|------|-----|-----------|----------|
| `claim` | string | gerekli | Doğrulanacak iddia (min 3 karakter) |
| `academic_limit` | int | 5 | Akademik kaynak başına maks sonuç (1-20) |
| `article_limit` | int | 5 | Mevcut makalelerden maks sonuç (1-20) |

### Yanıt Şekli

```json
{
  "claim": "statin ilaçları hastaların %90'ında kas ağrısına neden olur",
  "existing_articles": [
    {
      "provider": "ari_kaynak",
      "title": "Statın Kas Ağrısının %90'ı gerçekten 'Başınızda mı'?",
      "url": "https://nitrate07.github.io/Blog/makaleler/samson-trial-statin-nocebo.html",
      "source_type": "primary",
      "relevance": 0.72
    }
  ],
  "academic_sources": [
    {
      "provider": "pubmed",
      "title": "Nocebo etkisi ve statin intoleransı",
      "url": "https://pubmed.ncbi.nlm.nih.gov/12345/",
      "pmid": "12345",
      "published_year": 2024,
      "source_type": "unknown"
    }
  ],
  "source_count": 3,
  "pubmed_count": 1,
  "crossref_count": 1,
  "existing_count": 1,
  "coverage_score": 0.8,
  "summary": "'statin ilaçları...' için 3 kaynak bulundu — 1 mevcut Arı Kaynak makalesi + 1 PubMed kaydı + 1 Crossref kaydı. Kapsama güveni: yüksek (%80)."
}
```

### Kapsama Puanı

Kapsama puanı (0.0–1.0), bir iddianın mevcut kanıtla ne kadar desteklendiğini gösterir:

| Puan | Güven | Anlam |
|------|-------|-------|
| ≥ 0.7 | Yüksek | Kategoriler arası birden fazla kaynak |
| ≥ 0.4 | Orta | Bazı kanıtlar mevcut |
| < 0.4 | Düşük | Sınırlı veya hiç kanıt bulunamadı |

Puan bileşenleri:
- PubMed kayıtları: +0.4
- Crossref kayıtları: +0.3
- Mevcut makaleler: +0.3
- 2+ PubMed kaydı bonusu: +0.1
- 2+ mevcut makale bonusu: +0.1

### Kullanım Durumları

- **Yayın öncesi kontrol**: Yeni bir makale yazmadan önce bir iddiayı doğrulayın
- **Doğrulama araştırması**: Viral bir iddia için hızla akademik kaynaklar bulun
- **Boşluk analizi**: Yeni makaleler gerektiren düşük kapsamalı iddiaları belirleyin

## Kanıt Grafiği

Kanıt Grafiği, tüm doğrulama verilerini tek bir graf yapısında birleştirir: **iddia → kanıt → kaynak → pasaj → karar**.

### Temel İlke

> **LLM bir yorumcudur, ASLA kanıt kaynağı değildir.**
> Kanıt YALNIZCA şuradan gelir: PubMed, Crossref, Arı Kaynak Arşivi.
> Kanıt Motoru hakemdir — işler, puan verir ve hüküm verir.
> LLM yalnızca kararı doğal dilde açıklar.

### Mimari

```
Kullanıcı Sorgusu
  → İddia Çıkarma (kural tabanlı)
  → Kaynak Keşfi: Arşiv (RAG) + Dış (PubMed/Crossref)
  → Kanıt Motoru (hakem — belirleyici, LLM yok)
    - Kaynak Kalite Puanlama
    - İddia-Kanıt Eşleştirme
    - Karar Hesaplama
  → LLM Yorumcusu (sadece açıklar, kanıt üretmez)
  → Atıflı Yanıt
  → Graf Güncelleme (zinciri kaydeder)
```

### Graf Modeli

| Tür | Açıklama |
|-----|----------|
| `Claim` | Doğrulanabilir bir ifade, metadata ile |
| `Source` | Bir kanıt kaynağı (PubMed, Crossref, makale), kalite puanı ile |
| `Passage` | Bir kaynaktan metin alıntı, ilgi puanı ile |
| `Evidence` | İddia → pasajları bağlar, karar ve güven ile |
| `Verdict` | supported, mostly_supported, partly_supported, misleading, unsupported, unverified |
| `VerificationChain` | Tam yol: iddia → kanıt → kaynaklar |

### API Uç Noktaları

```bash
# Tam doğrulama hattını çalıştırın
curl -X POST http://localhost:8000/v1/pipeline \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"query": "Egzersiz kalp sağlığı için iyi mi?"}'

# claims.json'dan graf oluşturun
curl -X POST "http://localhost:8000/v1/graph/build?source=claims_json" \
  -H "X-API-Key: your-key"

# Bir iddianın doğrulama zincirini alın
curl http://localhost:8000/v1/graph/chain/{claim_id} -H "X-API-Key: your-key"

# İlgili iddiaları bulun
curl http://localhost:8000/v1/graph/related/{claim_id} -H "X-API-Key: your-key"

# Çelişkileri bulun
curl http://localhost:8000/v1/graph/contradictions -H "X-API-Key: your-key"

# İddiaları arayın
curl "http://localhost:8000/v1/graph/search?q=vitamin+d" -H "X-API-Key: your-key"

# Graf istatistikleri
curl http://localhost:8000/v1/graph/stats -H "X-API-Key: your-key"
```

### Hat Yanıtı

```json
{
  "query": "Egzersiz kalp sağlığı için iyi mi?",
  "extracted_claim": "egzersiz kalp sağlığı için iyi mi?",
  "archive_results": [{"title": "...", "verdict": "Çoğunlukla Destekleniyor", "distance": 0.3}],
  "external_results": [{"title": "...", "source_type": "primary", "doi": "10.1234/..."}],
  "verdict": "Çoğunlukla Destekleniyor",
  "verdict_confidence": 0.7,
  "rating_value": 4,
  "cited_response": "**İddia:** egzersiz kalp sağlığı için iyi mi?\n**Karar:** Çoğunlukla Destekleniyor...",
  "steps": [
    {"name": "claim_extraction", "status": "done"},
    {"name": "source_discovery", "status": "done"},
    {"name": "evidence_engine", "status": "done"},
    {"name": "llm_interpreter", "status": "done"},
    {"name": "graph_update", "status": "done"}
  ],
  "graph_claim_id": "claim::pipeline::12345"
}
```
