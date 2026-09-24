# Arı Kaynak Active State — (2026-09-24)
## Architecture: site = static HTML/CSS (root *.html, articles/ EN 41, tr/makaleler/ TR 41, assets/), no build. evidence = FastAPI; DEPLOYED app = evidence.v2.api.app (Docker, :8000/$PORT). Legacy evidence/api.py (graph pipeline, /v1/pipeline) NOT deployed.
## Pipeline: /v1/verify + /v1/chat -> v2 EvidencePipeline -> SourceOrchestrator (PubMed/Crossref/EuropePMC/WHO/CDC/...) + archive RAG -> DeterministicEngine (v2/engine/engine.py) -> optional LLM narration (fail-closed).
## DEPLOYED: Render free plan, docker, healthCheck /health, LLM provider groq (key via env, sync:false). Site: nitrate07.github.io/Blog.
## Current Delta to Published Logic: none on this branch (salvor-provisional = Salvor field-trial branch; main untouched).
## LEARNED FAILURES (13, DOMAIN_REF): LF:two-test-suites · LF:turkish-word-collision · LF:normalize-strips-meaning · LF:contentless-question · LF:fake-confidence-floor · LF:lexical-match-numbers · LF:retry-only-on-429 · LF:silent-except · LF:rag-load-not-fitted · LF:frontend-localhost · LF:relative-asset-path · LF:llm-language-guess · LF:dead-model-id
## Open: Salvor §10.5 provisional-capture field trial (dwasyluk/salvor #1). Verdict-engine parity rule active (RULES §0.5/§6.3): chat/conversation.py + graph/pipeline.py + v2/engine/engine.py.
## Last Brain Audit: 2026-09-24 (interval 3d — RULES §10.3)
