# evidence — FastAPI verification backend

Python 3, FastAPI, pytest. The deployed app is `evidence.v2.api.app` (Docker on Render). It retrieves evidence from
academic and health-organisation agents plus the site's own archive (RAG), judges it with a deterministic engine and
optionally narrates the result with an LLM (fail-closed: any LLM failure falls back to rule-based text).

## Key Files
- `v2/api/app.py` — DEPLOYED app (`/v1/verify`, `/v1/chat`, `/v1/search`, `/health`, MCP mount).
- `v2/engine/engine.py` — `DeterministicEngine` (deployed verdict engine).
- `v2/pipeline/`, `v2/sources/` — evidence pipeline, source agents, shared HTTP retry.
- `chat/` — conversation layer: intent, planner, investigator, `conversation.py` (`_derive_verdict`), editor/narrator.
- `graph/pipeline.py` + `api.py` — legacy app and graph pipeline (`/v1/pipeline`), not deployed.
- `rag/` — archive indexing over the site's articles. `security.py` — SSRF-safe fetching.
- `tests/`, `v2/tests/` — two separate suites; CI runs both.

## Architecture Notes
- **Parity (RULES §0.5/§6.3):** verdict/confidence logic exists in three engines (`v2/engine/engine.py`,
  `chat/conversation.py`, `graph/pipeline.py`); change them together in one commit.
- LLM output never decides a verdict; it only narrates, and cited URLs must come from the retrieved evidence.
- No evidence / no health topic ⇒ `unverified`, never a confident guess.

## Build
- `pip install -r evidence/requirements.txt` (optional extras: `requirements-*.txt`). Run both test suites before a PR.

For domain logic: see `.salvor/DOMAIN_REF.md`. For infra/ops: see `.salvor/INFRA.md`.
