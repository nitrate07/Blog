# Arı Kaynak — Evidence Verification Infrastructure

Arı Kaynak is an evidence-first verification layer, not a general-purpose chatbot. It takes a specific claim, retrieves supplied independent sources, extracts the relevant passage, assesses source quality, and returns a constrained verdict. Its operating principle is: **no evidence, no confident verdict**.

The deterministic comparison is inspectable and conservative; optional future providers implement the `VerificationProvider` protocol and cannot change the public API contract. The public API requires an API key by default. No LLM key is needed.

## Architecture

```
AI / agent -> Evidence API -> safe source retrieval -> source quality
          -> evidence extraction -> claim/evidence comparison -> verdict + citation
```

`EvidenceVerifier` owns orchestration. `SourceFetcher` handles SSRF-safe retrieval and extraction. `providers.py` is the extension seam for a future Claude, OpenAI, Gemini, or custom provider; none is hard-coded or required.

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

## Future provider integration

An LLM provider may propose a verdict only after a source passage has been retrieved. It should implement `VerificationProvider.compare`, return one of the constrained verdicts (or `None`), and preserve evidence-first behavior. Provider credentials belong in deployment secrets, never in this repository.
