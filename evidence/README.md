# Arı Kaynak — Evidence Verification Infrastructure

Arı Kaynak is an evidence-first verification layer, not a general-purpose chatbot. It takes a specific claim, retrieves supplied independent sources, extracts the relevant passage, assesses source quality, and returns a constrained verdict. Its operating principle is: **no evidence, no confident verdict**.

The deterministic comparison is inspectable and conservative; optional LLM providers implement the `VerificationProvider` protocol and cannot change the public API contract. The public API requires an API key by default. No LLM key is needed — the system works with deterministic comparison when no provider is configured.

## Architecture

```
AI / agent -> Evidence API -> safe source retrieval -> source quality
          -> evidence extraction -> deterministic comparison -> verdict + citation
          -> [optional] LLM verification -> enhanced verdict
```

`EvidenceVerifier` owns orchestration. `SourceFetcher` handles SSRF-safe retrieval and extraction. `llm_providers.py` contains Claude, OpenAI, and Gemini implementations. `provider_registry.py` creates providers from configuration. The system is evidence-first: LLM providers enhance but never replace the deterministic comparison.

## API

Run locally (Python 3.11+):

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r evidence/requirements.txt
uvicorn evidence.api:app --reload
```

Before starting a non-development server, set a strong, private bootstrap key in your deployment secret store:

```bash
export EVIDENCE_BOOTSTRAP_API_KEY="replace-with-a-random-secret-at-least-32-characters"
```

Pass it in `X-API-Key` on every `/v1/*` request. It is hashed before storage; the raw value is never written to SQLite or audit logs. `EVIDENCE_REQUIRE_API_KEY=false` is intended only for local development and tests.

`POST /v1/verify`

```json
{
  "claim": "A claim that needs verification",
  "sources": [{"url": "https://example.com/source"}],
  "context": "Optional context"
}
```

The response contains only `supported`, `partially_supported`, `unsupported`, or `unverified`. It returns extracted passages, source URL, source type, relevance, a source-content hash, a conservative confidence value, and an ISO-8601 `checked_at` time. Every result has a `verification_id`; retrieve its immutable record with `GET /v1/verifications/{verification_id}`. Insufficient relevant evidence produces `unverified`, not a guess.

`GET /v1/search?query=...` searches PubMed and Crossref for citable metadata. Search results are discovery candidates, **not evidence**: an agent must retrieve a candidate source and submit it to `/v1/verify` before relying on it. The endpoint uses the same API-key and rate-limit policy as verification.

## Source quality

- `primary`: official institutions, regulatory documents, original research/data, and official documentation
- `secondary`: systematic reviews, reviews, reputable analysis
- `tertiary`: blogs, social media, aggregators, unsourced summaries
- `unknown`: unclassified sources

Quality influences confidence and tie-breaking; it never substitutes for direct evidence.

## MCP tools

`evidence.mcp` exposes these structured-JSON tools:

- `verify_claim(claim, sources, context)`
- `search_evidence(query)` — deliberately reports no search backend in this URL-source MVP
- `get_source(url)`
- `compare_evidence(claim, evidence)`

`search_evidence` discovers PubMed/Crossref metadata and clearly labels it as non-evidence. `create_mcp_server()` creates a FastMCP server when the optional MCP package is installed; otherwise it returns the same callable tool surface, keeping the core dependency-light and testable.

## Security

Remote sources must be public `http`/`https` URLs with no embedded credentials. Loopback, private/reserved IPs, local hostnames, and DNS names resolving to non-public addresses are rejected. Retrieval uses timeouts, a bounded response body, a fixed redirect limit, and revalidates every redirect target. For public deployment, run retrieval through an egress proxy that blocks private address ranges to defend against DNS rebinding at connection time.

Verification records are stored in SQLite with the API key ID, a hash of the submitted claim (not the raw claim), outcome metadata, evidence passage, source URL/type, content hash, and capture time. API keys are hashed, and successful verifications generate a minimal audit event. The built-in limiter is per-process; use a gateway or Redis-backed limiter when running multiple workers.

## Tests

```bash
pytest evidence/tests -q
```

The tests cover supported, partial, contradicted, and insufficient evidence; source-quality ordering; private URL rejection; and FastAPI validation/response shape.

## LLM Provider Integration

The system supports optional LLM providers for enhanced evidence verification. When configured, the LLM provider analyzes claim-evidence pairs and returns a verdict. If the LLM fails or is not configured, the system falls back to the deterministic comparison engine.

### Supported Providers

| Provider | Default Model | API Key Env Var | Model Env Var |
|----------|---------------|-----------------|---------------|
| Claude | claude-sonnet-4-20250514 | `EVIDENCE_CLAUDE_API_KEY` | `EVIDENCE_CLAUDE_MODEL` |
| OpenAI | gpt-4o-mini | `EVIDENCE_OPENAI_API_KEY` | `EVIDENCE_OPENAI_MODEL` |
| Gemini | gemini-1.5-flash | `EVIDENCE_GEMINI_API_KEY` | `EVIDENCE_GEMINI_MODEL` |

### Configuration

Two approaches — provider-specific (recommended) or generic:

```bash
# Provider-specific (allows multiple providers configured at once)
export EVIDENCE_CLAUDE_API_KEY=your-anthropic-key
export EVIDENCE_CLAUDE_MODEL=claude-sonnet-4-20250514  # optional

export EVIDENCE_OPENAI_API_KEY=your-openai-key
export EVIDENCE_GEMINI_API_KEY=your-google-key

# Generic fallback (used when provider-specific not set)
# export EVIDENCE_LLM_PROVIDER=claude
# export EVIDENCE_LLM_API_KEY=your-key
# export EVIDENCE_LLM_MODEL=claude-sonnet-4-20250514
# export EVIDENCE_LLM_TEMPERATURE=0.0
# export EVIDENCE_LLM_MAX_TOKENS=256
```

The system auto-detects the active provider: provider-specific env vars take precedence, then `EVIDENCE_LLM_PROVIDER`, then the first provider with a configured API key.

### Constrained Verdict Provider (`VerificationProvider` seam)

Separate from the free-form provider above, `providers.py` exposes `AnthropicVerificationProvider` for the deterministic `/v1/verify` engine. It judges a claim strictly against an already-retrieved passage via a single forced tool call constrained to the four verdicts, never fetches its own sources, and fails closed to the deterministic comparison on any error. It activates automatically when a Claude key is configured (`EVIDENCE_CLAUDE_API_KEY`, model defaults to `claude-haiku-4-5-20251001`); unset keeps pure deterministic behavior.

### Provider Status API

```bash
# Check which providers are configured
curl http://localhost:8000/v1/provider/status

# Test provider connectivity
curl -X POST http://localhost:8000/v1/provider/test/claude
```

### How It Works

1. **Source retrieval**: The system fetches and extracts text from provided source URLs
2. **Deterministic comparison**: Token overlap and keyword matching produces an initial verdict
3. **LLM verification** (if configured): The LLM analyzes the claim against the extracted passage
4. **Final verdict**: LLM verdict takes precedence; deterministic verdict is used as fallback

### Provider Architecture

```python
from evidence.provider_registry import create_provider_from_config, create_provider

# Auto-create from environment (recommended)
provider = create_provider_from_config()

# Or create explicitly
provider = create_provider(
    provider_name="claude",
    api_key="your-key",
    model="claude-sonnet-4-20250514",
)

# Health check
status = await provider.health_check()
# {"status": "ok", "provider": "ClaudeProvider", "model": "claude-sonnet-4-20250514", ...}

# Or use directly
from evidence.llm_providers import ClaudeProvider
provider = ClaudeProvider(api_key="your-key")
```

### Custom Providers

Implement the `VerificationProvider` protocol:

```python
from evidence.providers import VerificationProvider
from evidence.models import Verdict

class MyCustomProvider:
    async def compare(self, claim: str, passage: str, context: str | None = None) -> Verdict | None:
        # Your logic here
        return Verdict.SUPPORTED

    async def health_check(self) -> dict:
        return {"status": "ok", "provider": "MyCustomProvider", "model": "custom"}
```

### Security

- API keys are loaded from environment variables, never committed to the repository
- LLM providers fail gracefully — verification continues with deterministic comparison
- Provider credentials belong in deployment secrets, never in this repository

## RAG — Semantic Article Search

The RAG system provides semantic search over all Arı Kaynak articles using TF-IDF vector embeddings.

### How It Works

1. **Parser** (`rag/parser.py`): Extracts structured chunks from article HTML — metadata, body sections, verdicts, and sources — with ClaimReview structured data
2. **Vector Store** (`rag/store.py`): TF-IDF embeddings with scikit-learn, cosine similarity search, disk persistence
3. **Retriever** (`rag/retriever.py`): Query → embed → search → filter → context assembly for LLM consumption

### API Endpoints

```bash
# Index all articles (EN + TR)
curl -X POST http://localhost:8000/v1/rag/index -H "X-API-Key: your-key"

# Semantic search
curl -X POST http://localhost:8000/v1/rag/query \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"query": "statin muscle pain nocebo", "n_results": 5, "language": "en"}'

# Quick search (GET)
curl "http://localhost:8000/v1/rag/search?q=exercise+heart+health&language=en" \
  -H "X-API-Key: your-key"

# Index stats
curl http://localhost:8000/v1/rag/stats -H "X-API-Key: your-key"
```

### Query Options

| Field | Type | Description |
|-------|------|-------------|
| `query` | string | Search text (min 3 chars) |
| `n_results` | int | Number of results (1-20, default 5) |
| `language` | string | Filter by `en` or `tr` |
| `category` | string | Filter by category (Health, Exercise, Nutrition, etc.) |

### Response Shape

```json
{
  "query": "statin muscle pain",
  "context": "FILE No. en:samson-trial... | Verdict: Supported (5/5)\n...",
  "results": [
    {
      "article_id": "en:samson-trial-statin-nocebo",
      "title": "Is 90% of Statin Muscle Pain Really 'All in Your Head'?",
      "verdict": "Supported",
      "rating_value": 5,
      "distance": 0.42,
      "source_url": "https://nitrate07.github.io/Blog/articles/samson-trial-statin-nocebo.html"
    }
  ],
  "total_results": 5
}
```

The `context` field is pre-formatted for direct use as LLM context in RAG pipelines.

### Configuration

```bash
# RAG settings (optional, defaults shown)
export EVIDENCE_RAG_PERSIST_DIRECTORY=evidence/data/chroma
export EVIDENCE_RAG_ARTICLES_DIR=articles
export EVIDENCE_RAG_TR_DIR=tr/makaleler
export EVIDENCE_RAG_MAX_RESULTS=10
export EVIDENCE_RAG_MAX_CONTEXT_LENGTH=4000
```

### Indexing

Call `POST /v1/rag/index` to (re)index all articles. The index is built from the `articles/` and `tr/makaleler/` directories. Each article is parsed into chunks: metadata, body sections (by heading), verdict, and sources. Turkish articles with the same English article ID are stored separately.

### Dependencies

- `scikit-learn` — TF-IDF vectorizer + cosine similarity
- `numpy` — matrix operations

No GPU or external embedding service required. The TF-IDF model runs entirely in-process.

## Cross-Verification — Multi-Source Evidence Discovery

The cross-verification system searches multiple evidence sources simultaneously and consolidates results into a single report.

### How It Works

1. **Parallel search**: Queries PubMed, Crossref, and existing Arı Kaynak articles concurrently
2. **Source consolidation**: Deduplicates and merges results from all sources
3. **Coverage scoring**: Computes a confidence score based on source diversity and count
4. **Summary generation**: Produces a human-readable summary of findings

### API Endpoint

```bash
# Cross-verify a claim
curl -X POST http://localhost:8000/v1/cross-verify \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"claim": "statin drugs cause muscle pain in 90% of patients"}'
```

### Request Body

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `claim` | string | required | The claim to verify (min 3 chars) |
| `academic_limit` | int | 5 | Max results per academic source (1-20) |
| `article_limit` | int | 5 | Max results from existing articles (1-20) |

### Response Shape

```json
{
  "claim": "statin drugs cause muscle pain in 90% of patients",
  "existing_articles": [
    {
      "provider": "ari_kaynak",
      "title": "Is 90% of Statin Muscle Pain Really 'All in Your Head'?",
      "url": "https://nitrate07.github.io/Blog/articles/samson-trial-statin-nocebo.html",
      "source_type": "primary",
      "relevance": 0.72
    }
  ],
  "academic_sources": [
    {
      "provider": "pubmed",
      "title": "Nocebo effect and statin intolerance",
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
  "summary": "Found 3 source(s) for: 'statin drugs...' — 1 existing Arı Kaynak article(s) + 1 PubMed record(s) + 1 Crossref record(s). Coverage confidence: high (80%)."
}
```

### Coverage Score

The coverage score (0.0–1.0) indicates how well a claim is supported by available evidence:

| Score | Confidence | Meaning |
|-------|------------|---------|
| ≥ 0.7 | High | Multiple sources across categories |
| ≥ 0.4 | Moderate | Some evidence available |
| < 0.4 | Low | Limited or no evidence found |

Score components:
- PubMed record(s): +0.4
- Crossref record(s): +0.3
- Existing articles: +0.3
- Bonus for 2+ PubMed records: +0.1
- Bonus for 2+ existing articles: +0.1

### Use Cases

- **Pre-publication check**: Verify a claim before writing a new article
- **Fact-check research**: Quickly find academic sources for a viral claim
- **Gap analysis**: Identify claims with low coverage that need new articles

## Evidence Graph

The Evidence Graph unifies all verification data into a single graph structure: **claim → evidence → source → passage → verdict**.

### Core Principle

> **LLM is an interpreter (yorumcu), NEVER an evidence source.**
> Evidence comes ONLY from: PubMed, Crossref, Arı Kaynak Archive.
> Evidence Engine is the hakem (referee) — it processes, scores, and judges.
> LLM only explains the verdict in natural language.

### Architecture

```
User Query
  → Claim Extraction (rule-based)
  → Source Discovery: Archive (RAG) + External (PubMed/Crossref)
  → Evidence Engine (hakem — deterministic, no LLM)
    - Source Quality Scoring
    - Claim-Evidence Matching
    - Verdict Computation
  → LLM Interpreter (yorumcu — explains verdict, never generates evidence)
  → Cited Response
  → Graph Update (records the chain)
```

### Graph Model

| Type | Description |
|------|-------------|
| `Claim` | A fact-checkable statement with metadata |
| `Source` | An evidence source (PubMed, Crossref, article) with quality rating |
| `Passage` | A text excerpt from a source with relevance score |
| `Evidence` | Links claim → passages with verdict and confidence |
| `Verdict` | supported, mostly_supported, partly_supported, misleading, unsupported, unverified |
| `VerificationChain` | Full path: claim → evidence → sources |

### API Endpoints

```bash
# Run the full verification pipeline
curl -X POST http://localhost:8000/v1/pipeline \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"query": "Is exercise good for heart health?"}'

# Build graph from claims.json
curl -X POST "http://localhost:8000/v1/graph/build?source=claims_json" \
  -H "X-API-Key: your-key"

# Get verification chain for a claim
curl http://localhost:8000/v1/graph/chain/{claim_id} -H "X-API-Key: your-key"

# Find related claims
curl http://localhost:8000/v1/graph/related/{claim_id} -H "X-API-Key: your-key"

# Find contradictions
curl http://localhost:8000/v1/graph/contradictions -H "X-API-Key: your-key"

# Search claims
curl "http://localhost:8000/v1/graph/search?q=vitamin+d" -H "X-API-Key: your-key"

# Graph statistics
curl http://localhost:8000/v1/graph/stats -H "X-API-Key: your-key"
```

### Pipeline Response

```json
{
  "query": "Is exercise good for heart health?",
  "extracted_claim": "exercise good for heart health?",
  "archive_results": [{"title": "...", "verdict": "Mostly Supported", "distance": 0.3}],
  "external_results": [{"title": "...", "source_type": "primary", "doi": "10.1234/..."}],
  "verdict": "Mostly Supported",
  "verdict_confidence": 0.7,
  "rating_value": 4,
  "cited_response": "**Claim:** exercise good for heart health?\n**Verdict:** Mostly Supported...",
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
