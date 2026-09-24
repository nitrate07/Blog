# .salvor/ — Arı Kaynak's brain

This folder is Arı Kaynak's **git-tracked memory**, maintained by Salvor. Shared and
Git-tracked does not mean co-canonical: every durable fact has one canonical owner (see
RULES §8's one-owner table), and other shared files contain concise routing instructions,
summaries, derived retrieval aids, or links to that owner. (Governance and entrypoints live
at the repo root: `CLAUDE.md` hub + spokes, `RULES.md`, and `VERSION.md` — here a minimal *Arı Kaynak Project History* log, since the
repo has no other version source and strict build counters are disabled.)

Salvor-Protocol: v1.0.0-beta
<!-- The protocol stamp above records which Salvor version scaffolded/last
     upgraded this install. Re-running a newer SETUP_PROMPT reads it to propose
     a delta-scoped upgrade (protocol layer only — never your knowledge). -->

| File | What it is |
|------|-----------|
| `active_state.md` | **L1** — ≤50-line dense current state + Learned Failures (auto-loaded) |
| `active_state_verbose.md` | **L2** — curated deep archive (rotated past ~1,500 lines): reasoning, rejected hypotheses |
| `DOMAIN_REF.md` | Authoritative current truth + the `LF:` learned-failure registry |
| `INFRA.md` | Running, env vars, deployment, external APIs |
| `DEFERRED_TODOS.md` | Deferred findings parked (out-of-scope, not yet fixed) |
| `domain-learnings/` | Dated, frozen empirical findings (probes, bakeoffs — the receipts) |
| `decisions/` | Design decisions + load-bearing invariants (why it's this way; what must stay; what depends on it) |
| `postmortems/` | Incident write-ups feeding `LF:` entries + deferred findings |
| `archive/` | EXPERIMENTAL (§10.6) — parked rejected/aged agent contributions; agents don't read it unless instructed |

Everything here is meant to be **read by humans and agents alike** — it's the *why*
behind the code.
