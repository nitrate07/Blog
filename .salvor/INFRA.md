# Arı Kaynak Infrastructure

Operational reference: running locally, deployment, env vars, external APIs, observability.

## Local
- Backend: `python -m venv .venv && . .venv/bin/activate && pip install -r evidence/requirements.txt`, then
  `uvicorn evidence.v2.api.app:app --reload` → http://localhost:8000 (`/docs` = OpenAPI). Details: `README.md`.
- Tests (CI runs both): `python -m pytest evidence/tests -q` and `python -m pytest evidence/v2/tests -q`.
- Site: static files, open `index.html` or serve the repo root with any static server.

## Deployment
- Backend: Render (`render.yaml`, free plan, `runtime: docker`, `Dockerfile` CMD `uvicorn evidence.v2.api.app:app`,
  health check `/health`). Secrets are set in Render (`sync: false`), never in the repo.
- Site: GitHub Pages (nitrate07.github.io/Blog). `ask.html` / `tr/ask.html` call the Render API
  (`window.ARI_API_BASE` fallback: `https://ari-kaynak-evidence-api.onrender.com`).

## Env vars
All prefixed `EVIDENCE_` (names only; values live in `.env` locally / Render in prod): LLM (`LLM_PROVIDER`, `LLM_API_KEY`,
`LLM_MODEL`, `GROQ_*`, `CLAUDE_*`, `OPENAI_*`, `GEMINI_*`, `LLM_MAX_TOKENS`, `LLM_TEMPERATURE`), RAG (`RAG_BACKEND`,
`RAG_ARTICLES_DIR`, `RAG_TR_DIR`, `RAG_PERSIST_DIRECTORY`, `RAG_CHROMA_PERSIST_DIRECTORY`, `RAG_MAX_RESULTS`,
`RAG_MAX_CONTEXT_LENGTH`), API/security (`REQUIRE_API_KEY`, `BOOTSTRAP_API_KEY`, `API_RATE_LIMIT_PER_MINUTE`,
`DATABASE_PATH`), fetching (`REQUEST_TIMEOUT_SECONDS`, `MAX_REDIRECTS`, `MAX_RESPONSE_BYTES`, `USER_AGENT`),
`LANGUAGE`. Source of truth: `evidence/config.py`.

## External APIs
PubMed, Crossref, Europe PMC, OpenAlex (academic, shared retry/backoff); WHO, CDC, ECDC, Cochrane, ClinicalTrials, FDA,
EMA, NICE, ESC, AHA and journal sites (HTML agents, BeautifulSoup); LLM providers (Groq default). Retrieval is SSRF-safe
(private/loopback IPs rejected, size/redirect limits).

## Observability
Render service logs; `/health`; `/v1/stats`. No metrics dashboard.
