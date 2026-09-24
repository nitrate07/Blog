# Agent guide — Arı Kaynak (nitrate07/Blog)

Read this first, then `.agent/LEARNED_FAILURES.md` before changing anything in `evidence/`.
Applies to any coding agent (Claude Code, opencode, Codex, Gemini).

## What this repo is
- Static bilingual (EN/TR) fact-checking site: `index.html`, `articles/*.html`, `tr/`, `assets/style.css`. No build step.
- `evidence/`: FastAPI backend (verification API + "Soruşturucu" chat). Deployed on Render.
- Editorial rules: `EDITORIAL_STANDARD.md`, `CORRECTIONS.md`. Do not edit article verdicts or body text unless explicitly asked.

## Workflow rules
- Work on a `feat/*` or `fix/*` branch, open a PR. Never merge to `main` yourself; the owner merges.
- Never commit secrets. `.env` is gitignored; keys come from env vars (`EVIDENCE_LLM_*`, `EVIDENCE_ANTHROPIC_*`).
- Run BOTH test suites (CI runs both):
  - `python -m pytest evidence/tests -q`
  - `python -m pytest evidence/v2/tests -q`
- For chat/verdict changes, also probe the real pipeline with real claims (no mocks). Several bugs were only visible that way.

## Memory files (keep them short)
- `.agent/LEARNED_FAILURES.md` — approaches/bugs that already bit us. Add an `LF:` entry when a fix teaches something a future agent could repeat.
- `.agent/DEFERRED.md` — known issues parked on purpose. Add instead of silently dropping out-of-scope findings; remove when fixed.
