# Arı Kaynak
### CURRENT STATE (L1 Cache)
@.salvor/active_state.md

> For deep historical context, architecture logs, or context recovery: `.salvor/active_state_verbose.md`

## Project Overview
Arı Kaynak is a bilingual (TR/EN) evidence-first fact-checking site for viral health claims: static case-file pages plus
an `evidence/` FastAPI backend (verification API and the "Soruşturucu" chat) that retrieves from PubMed, Crossref,
Europe PMC, WHO/CDC and other agents, and from the site's own article archive. The dominant non-obvious constraint:
**no evidence, no confident verdict** — a verdict and its confidence must reflect real evidence relevance, never a
floor or a guess, and article verdict/body text is never edited unless explicitly asked (`EDITORIAL_STANDARD.md`).

## Architecture

| Component | Stack | Spoke |
|-----------|-------|-------|
| site | static HTML/CSS, no build step (root `*.html`, `articles/`, `tr/`, `assets/`) | @articles/CLAUDE.md |
| evidence | Python 3, FastAPI, pytest (Docker on Render) | @evidence/CLAUDE.md |

## Documentation Map

| Document | Purpose | When to Read |
|----------|---------|-------------|
| `.salvor/DOMAIN_REF.md` | Domain logic, business rules, learned failures (`LF:`) | Changing core logic |
| `.salvor/INFRA.md` | Running, env vars, deployment, external APIs | Changing infra/deployment/APIs |
| `.salvor/DEFERRED_TODOS.md` | Deferred findings (out-of-scope, not yet fixed) | Before starting related work |
| `.salvor/decisions/` | Design decisions + load-bearing invariants | Before changing/refactoring anything non-trivial |
| `EDITORIAL_STANDARD.md` | Claim eligibility, source priority, evidence hierarchy, verdict scale (canonical in place) | Writing or judging any case file |
| `CORRECTIONS.md` | Corrections policy (canonical in place) | Changing a published verdict or article |
| `docs/ai-infrastructure-inventory.md` / `-roadmap.md` | Backend inventory and research notes (canonical in place) | Planning backend work |
| `articles/CLAUDE.md` | site component: pages, bilingual structure, SEO invariants | Working on any HTML/CSS |
| `evidence/CLAUDE.md` | evidence component: verification pipeline, tests | Working in `evidence/` |

### SYSTEM DIRECTIVE: TWO-TIER MEMORY MANAGEMENT
You maintain two memory ledgers: `.salvor/active_state.md` (L1 Cache — Concise) and `.salvor/active_state_verbose.md`
(L2 Cache — Deep Memory).

**L1 — active_state.md (Concise)**
- **Role:** Primary context for every session. Auto-loaded via `@` import (Claude Code) or read first (other CLIs).
- **Content:** Final confirmed logic, active deltas vs published behavior, infra status, and "Learned Failures."
- **Constraints:** MAXIMUM 50 LINES. Dense technical shorthand; non-standard abbreviations optimal for token density.
- **Update Trigger:** After every confirmed resolution, milestone, or architectural shift.

**L2 — active_state_verbose.md (Deep Archive)**
- **Role:** Curated repository for reasoning, condensed logs, evidence, and rejected hypotheses.
- **Update Trigger:** Immediately after updating L1 — offload the nuance pruned from L1.
- **Constraint:** Detailed but CURATED, never a raw dump — summarize command output; keep evidence, conclusions, and
  commit/test/issue IDs. Rotate: past ~1,500 lines, or at each release milestone, condense the oldest resolved sections
  into brief summaries (keep durable conclusions, drop noise). Do NOT read unless explicitly instructed or during
  Context Recovery (RULES §1).

**Execution Rules:**
- Routine L1/L2 operational-state maintenance is automatic — do not ask permission for these writes. Salvor may update
  concise operational state as work progresses. It must ask before promoting a decision, domain learning, learned
  failure, or deferred finding into the repository's durable shared engineering record.
- On any major learning or infra nuance: update L1 instantly with shorthand and L2 with detail.
- NEVER persist secrets, credentials, PII, or unredacted logs to any memory file (RULES §9). Redact before writing.

### SYSTEM DIRECTIVE: THREE CAPTURE CLASSES (user-gated)
You self-identify knowledge worth persisting durably and ask me, verbatim, before persisting it. Three capture classes
(see `RULES.md` §2 and §7):
1. **Decision / Domain Learning** — a discovery, decision, or design invariant + its *why*. Two subtypes: for a
   deliberate **Design Decision or load-bearing invariant**, ask `"Record this as a design decision? (yes/no)"` →
   `.salvor/decisions/` (with its Invariant & Coupling); for an empirical **Domain Learning**, ask
   `"Save this as a domain learning? (yes/no)"` → `.salvor/domain-learnings/`.
2. **Learned Failure (`LF:<slug>`)** (a structural failure mode) → registered in `.salvor/DOMAIN_REF.md` as part of the above.
3. **Deferred Finding** (an out-of-scope finding surfaced mid-task) → `"Log this to .salvor/DEFERRED_TODOS.md? (yes/no)"`
