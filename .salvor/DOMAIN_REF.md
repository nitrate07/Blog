# Arı Kaynak Domain Reference

Authoritative current-truth for domain logic. Artifacts in `.salvor/domain-learnings/` are frozen audit trails; this file is
what's currently true.

## Sections
- **Verdict scale & evidence hierarchy** — canonical in `EDITORIAL_STANDARD.md` (kept in place; not duplicated here).
- **Verdict engines (3 copies, parity rule RULES §0.5/§6.3):** `evidence/v2/engine/engine.py` `DeterministicEngine.judge`
  (DEPLOYED, serves `/v1/verify` + `/v1/chat`); `evidence/chat/conversation.py` `_derive_verdict` (chat investigator);
  `evidence/graph/pipeline.py` `_compute_verdict` (legacy `evidence/api.py`, `/v1/pipeline`, not deployed). Archive
  confidence = `1 - distance` clamped to [0,1] in all three (no floor).
- **Verdict gate:** no recognized health topic / no substantive content ⇒ no verdict (`unverified`), never a guess.

## Learned Failures (LF:)
One entry per failure mode (RULES §10.1 header). Root cause, fix sites and evidence commit per entry; update in place when a fix is upgraded (RULES §6.9).

### LF:two-test-suites (2026-08-29)
- **Subject**: tests, ci, evidence/v2/tests
- **Claim**: Two separate suites (evidence/tests, evidence/v2/tests); CI runs both, so a change must pass both.
- **Evidence date**: 2026-08-29
- **Status**: live
- **Contributed-by**: operator-approved (adopted at Salvor setup, 2026-09-24, from `.agent/LEARNED_FAILURES.md`, nitrate07/Blog#67)
- **What happened**: #36 dictionary refactor passed evidence/tests but broke GLP-1 matching in evidence/v2/tests.
- **Rule / fix sites**: Run both suites before every PR.
- **Evidence**: commit 1a3938e (#39)

### LF:turkish-word-collision (2026-08-24)
- **Subject**: search_query, term dictionary, turkish
- **Claim**: A dictionary key that is also an everyday Turkish word produces fake verdicts.
- **Evidence date**: 2026-08-24
- **Status**: live
- **Contributed-by**: operator-approved (adopted at Salvor setup, 2026-09-24, from `.agent/LEARNED_FAILURES.md`, nitrate07/Blog#67)
- **What happened**: 'adım' (step) matched 'benim adım Ümit' → 'Destekleniyor %85'.
- **Rule / fix sites**: Check new keys against non-health usage; keep the no-health-topic ⇒ no-research gate.
- **Evidence**: commit 7737c4c

### LF:normalize-strips-meaning (2026-08-29)
- **Subject**: search_query, tokenizer, normalization
- **Claim**: Normalization must not split medical terms (e.g. glp-1 → glp + 1).
- **Evidence date**: 2026-08-29
- **Status**: live
- **Contributed-by**: operator-approved (adopted at Salvor setup, 2026-09-24, from `.agent/LEARNED_FAILURES.md`, nitrate07/Blog#67)
- **What happened**: _normalize() stripped hyphens; glp-1 lost its dictionary match.
- **Rule / fix sites**: Tokenizer changes need tests with hyphenated/numeric medical terms.
- **Evidence**: commit 1a3938e (#39)

### LF:contentless-question (2026-08-29)
- **Subject**: chat gate, intent, verdict
- **Claim**: A question with no topic words must never produce a verdict.
- **Evidence date**: 2026-08-29
- **Status**: live
- **Contributed-by**: operator-approved (adopted at Salvor setup, 2026-09-24, from `.agent/LEARNED_FAILURES.md`, nitrate07/Blog#67)
- **What happened**: Loosening the interrogative gate (#48) let 'Bu doğru mu?' into research → verdicts from TF-IDF noise.
- **Rule / fix sites**: Any gate loosening ships with a no-topic ⇒ no-verdict test.
- **Evidence**: commit 50c4500 (#52)

### LF:fake-confidence-floor (2026-09-24)
- **Subject**: verdict engines, confidence, archive
- **Claim**: Confidence must reflect real relevance; never floor it to a constant.
- **Evidence date**: 2026-09-24
- **Status**: live
- **Contributed-by**: operator-approved (adopted at Salvor setup, 2026-09-24, from `.agent/LEARNED_FAILURES.md`, nitrate07/Blog#67)
- **What happened**: max(0.3, …) showed a flat 30% for relevant and unrelated matches alike. #43 fixed only chat/conversation.py; the deployed v2 engine and graph/pipeline.py kept the floor until #68.
- **Rule / fix sites**: Fix sites: chat/conversation.py, v2/engine/engine.py, graph/pipeline.py (parity rule RULES §0.5/§6.3).
- **Evidence**: commit 63cd2b3 (#43), 9163de7 (#68)

### LF:lexical-match-numbers (2026-08-29)
- **Subject**: engine, numeric claims
- **Claim**: Token overlap alone can rate a wildly wrong number as supported.
- **Evidence date**: 2026-08-29
- **Status**: live
- **Contributed-by**: operator-approved (adopted at Salvor setup, 2026-09-24, from `.agent/LEARNED_FAILURES.md`, nitrate07/Blog#67)
- **What happened**: '%500 artırır' matched evidence with a much smaller effect.
- **Rule / fix sites**: Keep the numeric-outlier guard when touching evidence/engine.py.
- **Evidence**: commit c94609f (#54)

### LF:retry-only-on-429 (2026-08-29)
- **Subject**: source agents, http retry
- **Claim**: A retry loop must retry timeouts/5xx, not only 429.
- **Evidence date**: 2026-08-29
- **Status**: live
- **Contributed-by**: operator-approved (adopted at Salvor setup, 2026-09-24, from `.agent/LEARNED_FAILURES.md`, nitrate07/Blog#67)
- **What happened**: journal_base.py looked like 3 retries but returned [] on any non-429 failure.
- **Rule / fix sites**: Test retry loops with a non-429 failure.
- **Evidence**: commit e727157 (#44)

### LF:silent-except (2026-08-25)
- **Subject**: error handling, agents, rag
- **Claim**: Except blocks must log; silent failures hid fetch/parse errors.
- **Evidence date**: 2026-08-25
- **Status**: live
- **Contributed-by**: operator-approved (adopted at Salvor setup, 2026-09-24, from `.agent/LEARNED_FAILURES.md`, nitrate07/Blog#67)
- **What happened**: 7 bare except blocks swallowed failures with no trace.
- **Rule / fix sites**: Always log inside except blocks.
- **Evidence**: commit 644726e (#32)

### LF:rag-load-not-fitted (2026-08-24)
- **Subject**: rag store, persistence
- **Claim**: A persisted TF-IDF index is unusable unless the vectorizer is refit on load.
- **Evidence date**: 2026-08-24
- **Status**: live
- **Contributed-by**: operator-approved (adopted at Salvor setup, 2026-09-24, from `.agent/LEARNED_FAILURES.md`, nitrate07/Blog#67)
- **What happened**: Loading matrix.npy without refitting made query() raise NotFittedError after restart.
- **Rule / fix sites**: Test persistence with a fresh instance and no upsert.
- **Evidence**: commit e9a49f3 (#24)

### LF:frontend-localhost (2026-08-29)
- **Subject**: site, ask.html, deploy
- **Claim**: The chat page must call the deployed API, not localhost.
- **Evidence date**: 2026-08-29
- **Status**: live
- **Contributed-by**: operator-approved (adopted at Salvor setup, 2026-09-24, from `.agent/LEARNED_FAILURES.md`, nitrate07/Blog#67)
- **What happened**: ask.html defaulted to http://localhost:8000, so the live chat never reached the backend.
- **Rule / fix sites**: After deploy-related changes, check which URL the live page calls.
- **Evidence**: commit d8cb2d6 (#42)

### LF:relative-asset-path (2026-08-29)
- **Subject**: site, tr/, assets
- **Claim**: Pages under tr/ need ../assets/ paths.
- **Evidence date**: 2026-08-29
- **Status**: live
- **Contributed-by**: operator-approved (adopted at Salvor setup, 2026-09-24, from `.agent/LEARNED_FAILURES.md`, nitrate07/Blog#67)
- **What happened**: tr/ask.html used assets/style.css; the TR chat page was unstyled.
- **Rule / fix sites**: Run an internal-link/asset scan after adding pages under tr/.
- **Evidence**: commit 17945cf (#58)

### LF:llm-language-guess (2026-08-29)
- **Subject**: llm narration, i18n
- **Claim**: Pass the explicit page language to the LLM; do not let it guess.
- **Evidence date**: 2026-08-29
- **Status**: live
- **Contributed-by**: operator-approved (adopted at Salvor setup, 2026-09-24, from `.agent/LEARNED_FAILURES.md`, nitrate07/Blog#67)
- **What happened**: Short messages ('hi') got wrong-language answers.
- **Rule / fix sites**: Use ConversationManager.language in prompts.
- **Evidence**: commit 7a30b6b (#61)

### LF:dead-model-id (2026-08-28)
- **Subject**: llm providers, config
- **Claim**: A default model ID can be retired by the provider.
- **Evidence date**: 2026-08-28
- **Status**: live
- **Contributed-by**: operator-approved (adopted at Salvor setup, 2026-09-24, from `.agent/LEARNED_FAILURES.md`, nitrate07/Blog#67)
- **What happened**: Groq llama-3.3-70b-versatile returned model_not_found.
- **Rule / fix sites**: Verify default model IDs against the provider's live model list.
- **Evidence**: commit 02c9026
