# Arı Kaynak Active State — VERBOSE ARCHIVE

L2 cache. Detailed but CURATED deep history of reasoning, rejected hypotheses, and condensed evidence pruned from L1.
Update trigger: immediately after every L1 update. Summarize command output — keep evidence, conclusions, and
commit/test/issue IDs, not raw dumps. Rotation: when this file exceeds ~1,500 lines, or at each release milestone,
condense the oldest resolved sections into brief summaries (keep durable conclusions, drop noise). Never persist
secrets, credentials, PII, or unredacted logs here (RULES §9) — redact before writing.

---

## 2026-09-24 — Project initialized
Initial Salvor scaffold: hub-and-spoke CLAUDE.md, L1/L2 cache, RULES.md §0–§10 (strict defaults
DISABLED, except operator-enabled parity §0.5/§6.3 and LF atomicity §6.9), three capture classes. Versioning owned by
the minimal Salvor project-history file `VERSION.md` — no per-component counters. Mode: CORE (Serena/GitNexus not
installed). Branch `salvor-provisional` — a field trial of RULES §10.5 provisional capture for the Salvor beta
(dwasyluk/salvor issue #1); `main` is untouched.

## 2026-09-24 — Setup notes
- Operator decisions at setup: parity rule enabled as the only [STRICT] exception (§0.5/§6.3 + §6.9) because Q3
  asked for it while Q4 disabled strict defaults; site spoke placed at `articles/CLAUDE.md` (site has no own dir);
  13 LF entries migrated from `.agent/LEARNED_FAILURES.md` into DOMAIN_REF (source files now pointers).
- Fact established while filling INFRA: the deployed backend is `evidence.v2.api.app` (Dockerfile CMD). Legacy
  `evidence/api.py` (`/v1/pipeline`, graph pipeline) is not deployed. See LF:fake-confidence-floor fix sites.
