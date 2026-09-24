# Arı Kaynak Development Rules

These rules are MANDATORY. They supplement CLAUDE.md and take precedence over default behavior.

## Rule tiers
- **[CORE] Core Protocol** — the vendor-portable substrate: context loading, L1/L2 state maintenance, capture approval,
  canonical ownership, context recovery, security, and git-safe operation. Always on; removing these breaks Salvor.
- **[STRICT] Optional Strict Engineering Defaults** — opinionated, project-specific, fully editable: build counters
  (§0.1, §3), mirror parity (§0.5, §6.3), whole-file-read limits (§4.1), impact-analysis-before-every-edit (§4.3),
  env-var conventions (§4.4, §6.2), container permission gates (§5.1), branch-deletion hygiene (§6.11), pre-merge
  brain reconcile (§0.6, §10.2). Tune, replace,
  or disable per project — disabling them must NOT break the Core Protocol. Status (from setup Q4): **DISABLED — [STRICT] items inactive until the team opts in, EXCEPT the parity rules §0.5 / §6.3 and
  §6.9 (LF atomicity), which the operator explicitly enabled at setup (2026-09-24).**
- **[EXPERIMENTAL] Beta features** — agentic provisional capture and the archive (§10.5–§10.6) are beta, **default
  OFF**, opt-in only by editing their config lines, and may change based on community feedback. Never required by
  Core or Strict behavior.

---

## 0. CRITICAL: Task Termination Protocol [CORE; items 1, 5 & 6 STRICT]
Before declaring any task "Complete" or "Done," you MUST verify and execute this checklist. **No task is complete until
spokes are synced and L1/L2 caches are updated** — plus, when strict defaults are enabled, the [STRICT] items below.

1. **[STRICT] Version Check:** If any logic in a component changed, increment its build ID in `VERSION.md` and update
   the "Last Updated" date. No hardcoded versions in source — they derive from VERSION.md at build time. On a feature
   branch, record the history row with the literal build ID `pending` instead — real numbers are assigned at
   integration (§3, §10.2).
2. **L1 Sync (`.salvor/active_state.md`):** Dense technical shorthand. Keep under 50 lines.
3. **L2 Sync (`.salvor/active_state_verbose.md`):** Offload full reasoning, logs, and nuance here.
4. **Spoke Sync:** Update the changed component's spoke `CLAUDE.md`. Update `.salvor/DOMAIN_REF.md` if domain logic changed;
   `.salvor/INFRA.md` if infra changed. Do NOT edit root CLAUDE.md for component-specific changes.
5. **[STRICT — ENABLED by operator] Verdict-engine parity:** the three verdict engines —
   `evidence/chat/conversation.py` (`_derive_verdict`), `evidence/graph/pipeline.py` (`_compute_verdict`, used by
   `POST /v1/pipeline`) and `evidence/v2/engine/engine.py` (`DeterministicEngine.judge`) — must keep verdict/confidence
   logic aligned. A change to one lands in the SAME commit as the matching change to the others. See §6.3.
6. **[STRICT] Brain Reconcile (feature branches):** if this task ends in a PR or a merge into the integration branch,
   fetch the target branch and run the §10.2 Brain Reconcile ceremony against it BEFORE the merge.

## 1. Context Recovery Procedure [CORE]
If I ask for "context recovery" — or you find yourself in a logic loop, repeating already-falsified reasoning:
1. **Stop** all code generation.
2. **Re-read** `.salvor/active_state_verbose.md` from the beginning.
3. **Compare** current logic against "Learned Failures" in `.salvor/DOMAIN_REF.md` and L1/L2.
4. **Summarize** the source of the confusion before proceeding.

## 2. Continued Learning Protocol [CORE] — capture class: Decision / Domain Learning
Every domain discovery, hypothesis falsification, validation, vendor/model verdict, or parameter learning is a **mandatory
save checkpoint**. The discovery is not the end — persisting it across the stack is.

**Trigger:** any of — hypothesis tested with evidence (accepted OR falsified); multi-dataset matrix / bakeoff result;
vendor / dependency probe with a verdict; new technique validated; Learned Failure (`LF:<slug>`) registered or updated; a
**deliberate design decision or load-bearing invariant** (why the code is shaped this way and what must stay true); or a
taxonomy clarification that will outlive the refactor.

**Mandatory prompt:** at the trigger moment, pause and ask me verbatim — the phrasing that matches the kind:

> "Save this as a domain learning? (yes/no)"  — an empirical **finding**
>
> "Record this as a design decision? (yes/no)"  — a **design decision / invariant**

Non-negotiable — it is the signal that the rule is working. Do not infer the answer, do not batch multiple discoveries
into one prompt, do not defer.

**On `yes` — execute the full stack update:**
1. **Dedupe by subject first:** search the matching registry/index (and `DOMAIN_REF.md`) by **Subject tags** — not just
   title or slug — before creating anything. If an artifact with overlapping subject and the same claim already exists,
   surface it and ask whether to augment it instead of adding a duplicate (same contract as §7's deferred dedupe).
2. **Dated artifact with ID + structured header:** create the frozen record — a **finding** in
   `.salvor/domain-learnings/YYYY-MM-DD-[CATEGORY]-[OUTCOME].md` (ID `DL:<kebab-slug>`, or `LF:<kebab-slug>` for a
   Learned Failure spec; hypothesis, evidence, verdict, cross-links) per `.salvor/domain-learnings/README.md`, **or** a
   **design decision** in `.salvor/decisions/YYYY-MM-DD-[slug].md` (ID `DEC:<kebab-slug>`; Context, Decision, Rationale,
   **Invariant**, **Coupling/blast-radius**, Alternatives) per `.salvor/decisions/README.md`. Every artifact opens with
   the structured header — ID / Subject / Claim / Evidence date / Status (§10.1).
3. **TOC update:** add a row to the matching chronological index:
   `.salvor/domain-learnings/README.md` for empirical findings, or
   `.salvor/decisions/README.md` for design decisions.
4. **DOMAIN_REF.md:** update to reflect new authoritative state — new/updated `LF:<slug>` entry, parameter rationale,
   finding status. DOMAIN_REF is current truth; the artifact is the frozen audit trail.
5. **Stack evaluation — update if affected:** `CLAUDE.md` hub (only if project-wide context shifts); spoke `CLAUDE.md`;
   L1 (`.salvor/active_state.md`); L2 (`.salvor/active_state_verbose.md`); Serena memories (`.serena/memories/`,
   enhanced mode — concise pointers only, per §8); per-user auto-memory (if enabled — see §8).
6. **Confirmation report:** list which files were touched so I can verify end-to-end.

**On `no`:** acknowledge and continue. Do not silently save a partial version.

**Rationale:** analytical context is lost to chat rotation, compaction, and tool drift. A discovery not written to git +
propagated will be re-litigated next session. This rule makes propagation visible and user-gated so it cannot silently
fail. The contract: Salvor may update concise operational state as work progresses. It must ask before promoting a
decision, domain learning, learned failure, or deferred finding into the repository's durable shared engineering record.

## 3. Version Increment Rules [STRICT — DISABLED]
Strict defaults are disabled (setup Q4 = no): no per-component build counters, no derived version constants. The repo has
no established version source (no `package.json` / `pyproject.toml` / tags); `VERSION.md` is a minimal Salvor
project-history log only.

## 4. Search & Tools [STRICT / enhanced]
1. **[STRICT] Search-Before-Read:** do not `read_file` on any file >100 lines without first using `grep`, `find_symbol`,
   or `get_symbols_overview` to find specific line ranges. Targeted reads only.
2. **[enhanced mode — INACTIVE: Core mode, no Serena MCP] Priority:** Serena MCP symbolic tools first (`find_symbol`, `get_symbols_overview`). Fall back to
   `grep`/`glob` only if Serena can't resolve. (Core mode: `grep`/`glob` are the primary tools.)
3. **[STRICT, enhanced mode — INACTIVE: Core mode, no GitNexus MCP] Impact before edits:** before modifying a function/class/method, run GitNexus impact
   analysis and report the blast radius. Run change-detection before committing. (Core mode: state that impact analysis
   is unavailable rather than pretending it ran.)
4. **[STRICT] App Name:** never hardcode the project name — use `APP_NAME` or the build constant.

## 5. Infrastructure & Safety
1. **[STRICT] Docker / containers:** explicit permission required for `build`, `up/down`, or `restart`. Treat as
   destructive — the operator may run parallel sessions.
2. **[CORE] Production endpoints / external APIs:** explicit permission required for any call that mutates external
   state, costs money, or touches shared infrastructure.

## 6. Coding required practices [STRICT] (§6.1, §6.4, §6.10 are Core-grade — keep them even if the rest is disabled)
1. Read root `CLAUDE.md`, the relevant spoke `CLAUDE.md`(s), and referenced L1/L2 state before coding any component.
2. Do NOT hardcode values that change often — versions, run modes, environment endpoints. Wire them to variables.
3. **[ENABLED by operator] Live ↔ Mirror parity changes land in the same commit** (here: the three verdict engines, §0.5). If a live path AND a mirror/simulator/replay path exist,
   patching one and "catching up" later is forbidden — silent drift is the failure mode.
4. **Full code-path traversal.** When you change one area, follow every related code path and update it. Example: a new
   config parameter must be added to the config UI, audit/report output, import/export, and everywhere it's read — never a
   half-wired value. Never work on assumptions; if uncertain, STOP AND ASK.
5. **Smoke-test before declaring a numerically-sensitive fix done.** Math changes (numeric constants, thresholds, limits,
   allocation, rounding, guards) require an explicit smoke run before "done," or a stated reason it can't be smoke-tested.
   "Compiles, ship it" is not acceptable.
6. **Verify long-running / observability processes are alive before trusting output.** Liveness check (`ps`, `kill -0`,
   `wc -l`) before relying on a background tool's output; mid-run checkpoints for multi-hour runs.
7. **Identifier hygiene at external API boundaries.** Pass the domain-correct identifier at every external call site
   (slug ≠ id ≠ external-id). When in doubt, grep the API docs / proxy handler.
8. **Cache key invariants.** Any cache key must include EVERY input that changes the output (model name, prompt-version
   hash, schema version). Adding an input without bumping the key = silent staleness.
9. **[ENABLED by operator] The Learned Failure is the atomic unit of work.** Upgrading a fix (v1 → v2) updates every site listed under that
   `LF:<slug>` entry in DOMAIN_REF.md together. A new mirror site = a new LF-amendment commit, not a quiet one-liner.
10. **Production-affecting code requires explicit operator ack before deploy.** Any path touching money, customer data,
    external mutations, or shared infra — operator sees the diff first. Not "I think this is right, pushing."
11. **Delete merged branches in the same step as the merge.** After merge + push: `git branch -d <name>` AND
    `git push origin --delete <name>` in one task. Exception: long-lived integration branches need operator confirmation.

## 7. Out-of-scope finding capture [CORE] — capture class: Deferred Finding
When in-progress work surfaces a bug, risk, tech-debt item, or other finding **not directly related to the current task**,
you MUST prompt me before doing anything else with it. Never silently ignore an unrelated finding (it gets lost), and
never silently log one (I own prioritization).

**Mandatory prompt:**

> "Log this to .salvor/DEFERRED_TODOS.md? (yes/no)"

Bundle multiple findings that emerge together into one prompt. **On `yes`:**
1. Read `.salvor/DEFERRED_TODOS.md` first and **deduplicate by subject** — if the finding (or a close relative) already
   exists, surface it and ask whether to augment rather than add a duplicate.
2. If new, append an entry headed by a self-allocating slug ID — `### deferred:<kebab-slug> — <short title>` (never a
   sequential number; §10.1) — with: **Subject** (tags), **Where** (file/location), **What**, **Severity** (Low /
   Medium / High — judged as "impact if left ~6 months," not "broken today"), and **Suggested fix**.
3. Do not derail the current task to fix it — capture and continue.

When one is later fixed: delete its entry, and reference the stable ID in the fixing commit (`closes deferred:<slug>`).

## 8. Memory layers & canonical ownership [CORE]
- **Shared and Git-tracked does not mean co-canonical. Every durable fact has one canonical owner. Other shared files
  contain concise routing instructions, summaries, derived retrieval aids, or links to that owner.** The in-repo files
  (`CLAUDE.md` hub + spokes, `RULES.md`, the version source — `VERSION.md` when Strict defaults are enabled (Q4=YES),
  otherwise the repo's established version mechanism — `.salvor/*`, `.serena/memories/` in enhanced mode, the
  hand-authored GitNexus routing note in the hub) are all shared and available to each supported agent through its
  compatible entrypoint — but each durable fact still has exactly ONE owner; everything else points at it.
- **Per-user, optional, NOT shared (Claude Code only):** auto-memory at `~/.claude/projects/.../memory/`. Useful for
  personal/operator preferences, but it is not version-controlled and does not reach teammates. Never put shared truth
  there — that belongs in-repo.
- **ONE-OWNER RULE:** each durable fact has exactly ONE canonical artifact. Every other location links or summarizes —
  never a copied full narrative:

  | Durable fact | Canonical owner |
  |--------------|-----------------|
  | Concise current state | `.salvor/active_state.md` |
  | Curated recovery history | `.salvor/active_state_verbose.md` |
  | Current domain facts + terminology | `.salvor/DOMAIN_REF.md` |
  | Design rationale | decision artifact (`.salvor/decisions/`) |
  | Validated empirical discovery | domain-learning artifact (`.salvor/domain-learnings/`) |
  | Incident / failed-approach evidence | learned-failure / postmortem artifact (`.salvor/postmortems/`) |
  | Deferred findings | `.salvor/DEFERRED_TODOS.md` |
  | Machine-derived structural code knowledge | GitNexus |
  | Symbol retrieval + semantic navigation | Serena |
  | Spec Kit requirements + plans | existing Spec Kit artifacts (`.specify/`, `specs/`) |
  | Vendor context routing | thin vendor adapter (`AGENTS.md`, `GEMINI.md`) |
  | Tool-specific retrieval aids | derived pointer / summary |

- **Serena memory is NOT co-canonical:** `.serena/memories/` holds concise pointers and summaries that help Serena route
  to `.salvor/` — canonical content lives in `.salvor/`, never as a competing full copy in Serena.
- **GitNexus-generated context is NOT co-canonical:** it is a machine-derived, regenerable retrieval aid, not an owner of
  durable facts.
- **Vendor adapters are NOT co-canonical:** `AGENTS.md` / `GEMINI.md` carry thin routing only — never a knowledge fork.
- **Component spokes link to the owner rather than duplicate:** a spoke points at the canonical artifact instead of
  restating its content.

## 9. Security & Git-safe operation [CORE]
1. **NEVER persist** to any memory/knowledge file: API keys, passwords, tokens, private keys, cookies, `.env` contents,
   credential-bearing URLs, customer PII, production datasets, unredacted logs, dependency dumps, large build output, or
   hidden model reasoning. **Redact before writing.** Summarize command output — keep evidence, conclusions, and
   commit/test/issue IDs; drop the noise.
2. `.gitignore` does not remove already-committed data. If credentials were ever committed: revoke them AND remediate
   git history — ignoring the file afterward is not a fix.
3. **Git-safe operation:** never blanket-stage (no catch-all add flags, no staging `.`), never commit without explicit
   approval, never silently overwrite files or another tool's managed sections. Stage explicit path lists; show
   `git diff --cached` before any commit you were asked to make.

## 10. Distributed Brain: IDs, Reconcile & Audit [CORE; §10.2 trigger 1 STRICT]
The brain travels through Git. Parallel branches, agents, and worktrees can capture semantically duplicate or
contradictory knowledge under different names, and shared single-file surfaces conflict textually. This section keeps
the brain single-truth with no central ID authority.

### 10.1 Knowledge IDs [CORE]
- Every durable knowledge artifact has a **self-allocating slug ID** — `<CLASS>:<kebab-slug>` — assigned at capture
  time: `LF:` (Learned Failure), `DL:` (Domain Learning), `DEC:` (Design Decision), `PM:` (Postmortem), `deferred:`
  (Deferred Finding). **Never a sequential number** — no ID allocation may read shared state.
- Every artifact opens with the **structured header** (the semantic-dedupe key):
  **ID** · **Subject** (tags: the system/vendor/component the claim is about) · **Claim** (one-line invariant) ·
  **Evidence date** · **Status** (`live` | `superseded-by: <id>`).
- IDs are immutable once merged to the integration branch; renaming before merge (on the owning branch) is fine.
- Registries/indexes enforce slug uniqueness per class. A slug collision found at reconcile time is a probable
  duplicate (§10.4), not an error. Superseded artifacts keep their ID with `Status: superseded-by: <id>` — never
  delete an ID from a registry; references must not dangle.

### 10.2 Brain Reconcile (merge/pull ceremony)
**Triggers:**
1. **[STRICT] Pre-merge:** on a feature branch, before opening a PR or merging into the integration branch, fetch the
   target and reconcile against it (§0 item 6) — dedupe lands BEFORE the textual conflict.
2. **[CORE] Post-pull:** at session start, if incoming commits touched `.salvor/`, the version source, `RULES.md`, or
   `.serena/memories/`, ask verbatim:
   > "Incoming brain changes detected — run brain reconcile? (yes/no)"

**Procedure:** three-way diff (merge base / ours / theirs) over the brain surfaces → semantic comparison (§10.4) →
per-surface resolution. Every merge/augment/supersede of durable knowledge is operator-gated, verbatim:
> "Merge these two <class> artifacts into one? (yes/no)"

| Surface | Resolution rule |
|---------|-----------------|
| Artifacts (DL / DEC / PM / LF specs) | Winner absorbs loser with a provenance block; loser becomes a one-line redirect stub (`superseded-by:`). |
| `.salvor/DOMAIN_REF.md` | Single current truth — contradictions resolve to ONE `Status: live` entry; loser marked superseded with date + why. |
| L1 (`active_state.md`) | NEVER textually merged — re-synthesize from both sides' L2 + artifacts after resolution (≤50 lines). |
| L2 (`active_state_verbose.md`) | Union both sides, normalize to chronological order, collapse duplicate sections. |
| Index READMEs + `DEFERRED_TODOS.md` | Union rows, re-sort, dedupe. (Optional `.gitattributes` `merge=union` convenience — reconcile normalizes regardless.) |
| `RULES.md` | Governance — conflicting edits to Salvor-managed sections are ALWAYS operator-decided; never auto-merged. |
| `.serena/memories/` | Derived views — re-derive from the reconciled canonical artifacts; never merge textually. |
| Spoke `CLAUDE.md` | Update knowledge references to the reconciled IDs; [STRICT] build lines per §3 integration bump. |
| Version source | [STRICT] §3 integration bump: assign real numbers to `pending` rows — one bump per component per integration. |

End with the standard confirmation report (every touched file).

### 10.3 Brain Audit (recurring semantic self-audit)
Reconcile only sees what a merge brings in; duplicates also accrete on a single branch or pre-date the protocol.
- **Cadence:** due every **3 days** — `AUDIT_INTERVAL_DAYS = 3`, operator-tunable (beta default; feedback welcome on
  the default and its configurability). Tracked by the `## Last Brain Audit:` line in L1. At session start, if
  overdue, ask verbatim:
  > "Brain audit is due (last run N days ago) — run it now? (yes/no)"
- **Sweep:** the §10.4 comparison run all-pairs across the whole brain, plus: contradiction check against DOMAIN_REF
  current truth; missing/empty Subject/Claim headers; stale L1 lines; dangling or superseded cross-links; aging
  deferred findings; L1 ≤50-line and L2 rotation checks.
- Findings route through the same classification + operator gates as §10.2. Update the L1 audit line and land the run
  as an ordinary commit.

### 10.4 Semantic comparison (never filename-only)
1. **Pair by Subject:** for each new/changed artifact, collect every existing artifact (any class, any date) sharing
   ≥1 Subject tag. Subject overlap — not name similarity — is the pairing key.
2. **Compare Claims** (read both artifacts in full):
   - same claim, compatible evidence → **duplicate** — merge into one (keep the richer body, union evidence, one live ID)
   - compatible claims, different facets → **overlapping** — augment the canonical one
   - incompatible claims → **contradictory** — operator decision required (present both evidence dates, with a
     newest-evidence presumption); exactly ONE `Status: live` entry survives
   - one retests/upgrades the other → **supersedes** — v1 → v2 per §6.9 atomicity
3. No pair → **distinct** — keep as-is.

### 10.5 [EXPERIMENTAL] Agentic provisional capture — default OFF
**Config: `AGENT_CAPTURE = provisional`** (operator-tunable: `off` | `provisional`). **Beta feature under active
calibration** — graduation criteria are tracked publicly (see the project's CONTRIBUTING). When `off` (the default),
nothing changes: ALL durable capture remains user-gated per §2/§7 — agents never write durable knowledge without the
verbatim prompt.

When the operator sets `provisional`:
- **Trust tier.** Agents may create durable artifacts without the per-item gate, but every such artifact enters a
  visibly lower trust tier: its structured header carries `Contributed-by: agent — <vendor/model>, <date>` and
  `Review: unreviewed`. Human-gated captures carry `Contributed-by: operator-approved` and no `Review:` field (the
  capture gate itself is the ratification). Provenance is plain Markdown data — it must survive any vendor switch and
  never rely on vendor-specific state.
- **Per-class policy.** Allowed provisionally: **Deferred Findings**, **Domain Learnings**, and **Learned Failures**
  — with `Claim:` and evidence content mandatory (no evidence, no capture). **Design Decisions:** agents may only
  file proposals (`Review: proposed`); a `DEC:` never becomes governing rationale without human ratification.
  **RULES changes: never agentic** (§10.2 governance), under any setting.
- **Consumption rule (all vendors).** Treat `Review: unreviewed` knowledge as *hypothesis, not invariant*: cite its
  provenance when acting on it, never let it relax a rule, and never let it override ratified knowledge. An
  unreviewed↔ratified contradiction resolves automatically in favor of the ratified entry pending review.
- **L1 marking.** L1 shorthand derived from unreviewed knowledge carries a `(prov)` tag until ratification — L1 must
  never launder provisional claims into apparent truth.
- **Commit trailer.** Commits introducing agent contributions carry the trailer `Salvor-Contribution: agent`. Header
  and trailer must agree — a mismatch is an audit red flag.
- **Ratification.** The Brain Audit (§10.3) enumerates every `Review: unreviewed` / `Review: proposed` artifact by
  scanning headers (no separate ledger — derived, conflict-free) and presents each through the §10.4 classification
  with the verbatim gate:
  > "Ratify this agent contribution? (yes / no / archive)"
  `yes` → `Review: ratified`, drop the L1 `(prov)` tags; `no` → one-line redirect stub stays in place, full content
  moves to the archive (§10.6); `archive` → moved untouched for later review. Review each item individually — bulk
  ratification defeats the tier.

### 10.6 [EXPERIMENTAL] Archive — `.salvor/archive/`
Unreviewed knowledge is parked, never silently discarded — the same principle as deferred findings, one tier down.
- **Layout:** mirrors the live folder structure (`archive/domain-learnings/`, `archive/decisions/`,
  `archive/postmortems/`). An archived artifact keeps its ID and full content; the live registry keeps a one-line
  `Status: archived` pointer (never delete an ID — §10.1).
- **Aging:** `ARCHIVE_AFTER_DAYS = 90` (operator-tunable). The Brain Audit surfaces unreviewed contributions older
  than the window with the verbatim gate:
  > "Archive N stale unreviewed contributions? (yes/no)"
  **Ratified knowledge never ages out** — it lives until superseded.
- **Load rule:** agents never read `.salvor/archive/` unless explicitly instructed (same contract as L2). The
  archive optimizes attention, not disk — git history retains everything regardless.
- **Un-archive:** late ratification moves the artifact back and flips `Review:`; references never dangled because
  the ID persisted.
- **Offloading** (e.g. object storage) is out of core scope — community integrations welcome; Salvor itself installs
  no hooks.
