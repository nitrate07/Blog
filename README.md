# Arı Kaynak — Evidence Verification Infrastructure

Sağlık iddialarını birincil kaynaklardan doğrulayan, kanıt toplayıp hüküm veren AI altyapısı.
Yerel makale arşivi (RAG) ve 19 harici tıbbi kaynak ajanıyla (PubMed, Cochrane, WHO, NEJM, ...) çalışır.

## Mimari

```
evidence/
├── v2/                      # Aktif sürüm — temiz katmanlı mimari
│   ├── api/app.py           # FastAPI: REST + SSE streaming + Web UI
│   ├── core/                # Tipler, arayüzler, SQLite kalıcılık, rate limiter
│   ├── engine/              # Deterministik doğrulama motoru + çelişki analizi
│   ├── pipeline/            # Kanıt toplama hattı
│   └── sources/             # 19 kaynak ajanı (PubMed, WHO, CDC, NEJM, TÜSEB, ...)
├── chat/                    # Konuşmacı Soruşturucu katmanı (intent → plan → araştır → hüküm)
├── graph/                   # Ajan grafiği (sağlık ajanları, pipeline)
├── rag/                     # Yerel arşiv parser + retriever + store
├── llm_providers.py         # Claude / OpenAI / Gemini provider arayüzü
├── mcp.py                   # MCP araç yüzeyi
└── tests/                   # Birim testler
```

## Kurulum

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install fastapi uvicorn httpx pydantic scikit-learn numpy pytest pytest-asyncio

cp .env.example .env             # değerleri doldurun (LLM API anahtarı vb.)
```

## Çalıştırma

```bash
uvicorn evidence.v2.api.app:app --reload
# → http://localhost:8000        (Web UI)
# → http://localhost:8000/docs   (OpenAPI)
```

## API Örneği

```bash
# Temel doğrulama
curl -X POST http://localhost:8000/v1/verify \
  -H "Content-Type: application/json" \
  -d '{"query": "Kahve kolesterolü yükseltir mi?"}'

# Konuşmacı Soruşturucu (SSE akışı)
curl -N -X POST http://localhost:8000/v1/investigator/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "Günlük aspirin kalp krizinden korur mu?"}'
```

SSE olay tipleri: `start` → `step` (sıra sıra soruşturma adımları) → `steps_done` → `chunk` (yanıt metni) → `done` (hüküm, güven, kaynak sayısı).

### Hüküm değerleri

| Değer | Anlam |
|---|---|
| `supported` | Kanıt iddiayı destekliyor |
| `mostly_supported` | Büyük ölçüde destekli |
| `partly_supported` | Kısmen destekli |
| `unsupported` | Kanıt iddiayı desteklemiyor |
| `unverified` | Yetersiz kanıt — hüküm verilmez |

## MCP Kullanımı

`evidence/mcp.py` dört araç sunar: `verify_claim`, `search_evidence`, `get_source`, `compare_evidence`.
`mcp` paketi kuruluysa FastMCP sunucusu döner; değilse çağrılabilir araç sınıfı döner.

## Testler

```bash
pytest evidence/v2/tests/ -q
```

## Dağıtım (Docker)

```bash
cp .env.example .env        # LLM anahtarını doldurun
docker compose up -d --build
# → http://localhost:8000
```

- Kalıcı veri (SQLite + Chroma) `ari-data` volume'ünde tutulur.
- Sağlık kontrolü: `GET /health`.
- Statik site (GitHub Pages) `allow_origins=["*"]` sayesinde bu API'ye doğrudan çağrı yapabilir.
- Üretimde `EVIDENCE_REQUIRE_API_KEY=true` bırakın ve `EVIDENCE_BOOTSTRAP_API_KEY` ile ilk anahtarınızı oluşturun.

## Güvenlik Notları

- Gerçek API anahtarlarını asla commit etmeyin; yalnızca `.env` kullanın (`.env.example` şablondur).
- `/v1/*` uçları varsayılan olarak API anahtarı ister (`EVIDENCE_REQUIRE_API_KEY=true`).
