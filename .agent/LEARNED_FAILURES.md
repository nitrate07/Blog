# Learned failures

One entry per lesson. Format: `LF:<slug>` — what went wrong, why, the rule. Link the PR/commit.

- **LF:two-test-suites** — `evidence/v2/tests` is separate from `evidence/tests`; a dictionary refactor (#36) passed one suite and broke hyphenated terms (`GLP-1`) in the other (#39). Always run both.
- **LF:turkish-word-collision** — Dictionary terms that are also everyday Turkish words cause fake verdicts: "adım" (step) matched "benim adım Ümit" and produced "Destekleniyor %85" (7737c4c). Check new dictionary keys against common non-health usage; keep the "no health topic, no research" gate.
- **LF:normalize-strips-meaning** — `_normalize()` once stripped hyphens, splitting `glp-1` into `glp` + `1` (#39). Tokenizer changes need tests with hyphenated/numeric medical terms.
- **LF:contentless-question** — Loosening the interrogative gate (#48) let "Bu doğru mu?" through to research and produced verdicts from TF-IDF noise (#52). Any gate loosening needs a "no topic words ⇒ no verdict" test.
- **LF:fake-confidence-floor** — `max(0.3, ...)` on archive relevance showed a flat "güven %30" for relevant and irrelevant matches alike (#43). Never floor confidence to a constant; confidence must reflect actual relevance.
- **LF:lexical-match-numbers** — Token overlap alone rated "%500 artırır" as supported by evidence with a much smaller number. Numeric-outlier guard exists (#54); keep it when touching `engine.py`.
- **LF:retry-only-on-429** — `journal_base.py` looked like it retried 3 times but only retried on 429; timeouts/5xx returned `[]` at once (#44). Test retry loops with a non-429 failure.
- **LF:silent-except** — Bare `except: pass` hid fetch/parse failures in 7 places (644726e). Always log inside except blocks.
- **LF:rag-load-not-fitted** — Loading the persisted TF-IDF matrix without refitting the vectorizer made `query()` crash after restart (#24). Test persistence with a fresh instance, no upsert.
- **LF:frontend-localhost** — `ask.html` defaulted to `http://localhost:8000`, so the live chat never reached the backend no matter the API keys (#42). After deploy-related changes, check what URL the live page actually calls.
- **LF:relative-asset-path** — `tr/ask.html` used `assets/style.css` instead of `../assets/style.css`; TR chat page was unstyled for everyone (#58). Pages under `tr/` need `../`.
- **LF:llm-language-guess** — Letting the LLM infer reply language from short text ("hi") gave wrong-language answers (#61). Pass the explicit page language.
- **LF:dead-model-id** — Groq `llama-3.3-70b-versatile` was retired (02c9026). Verify default model IDs against the provider's live models list before relying on them.
