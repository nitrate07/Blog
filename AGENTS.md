# Agent guide — Arı Kaynak (nitrate07/Blog)

Read this first, then `CLAUDE.md` and `.salvor/DOMAIN_REF.md` (Learned Failures) before changing anything in `evidence/`.
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

## Memory files
- Project memory is managed by Salvor under `.salvor/` (see `CLAUDE.md` and `RULES.md`). `.agent/` now only holds pointers.

<!-- salvor:start -->
## Salvor
Before any work, read `CLAUDE.md` (the hub) + the relevant component spoke + `RULES.md` +
`.salvor/active_state.md` (L1). Follow `RULES.md` exactly — including the Task Termination
Protocol and the capture classes. The canonical context lives in `CLAUDE.md`; this file
just points there. **Do not duplicate or fork project knowledge into this adapter.**
Canonical engineering knowledge lives in its assigned `.salvor/` artifact and the
`CLAUDE.md` hub + component spokes; `.serena/memories/` contains concise enhanced-mode
retrieval aids only.
<!-- salvor:end -->
