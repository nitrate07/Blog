# Arı Kaynak — Editorial Standard

This document describes how Arı Kaynak turns a viral claim into a published case file. It exists so the process is auditable, not just asserted on the Method page.

## 1. What qualifies as a claim worth checking

A claim is eligible for a file when it:
- Is actively circulating in short-form video, social media, or word-of-mouth form
- Makes a specific, checkable assertion (a number, a mechanism, a comparison) — not a vague mood ("eat healthier")
- Can plausibly be traced to a real study, dataset, or professional guideline

Claims that cannot be traced to any identifiable source are not published as verdicts. If we investigate and find nothing, the honest output is "no credible primary source found," not a fabricated citation.

## 2. How sources are selected

Priority order, highest to lowest:

1. The original peer-reviewed paper (via PubMed, the publishing journal, or DOI)
2. Official professional-body position statements or clinical guidelines (e.g. WHO, AHA, NATA)
3. Systematic reviews and meta-analyses
4. Individual peer-reviewed studies (RCTs, cohort studies, case-control studies)
5. Preliminary/preprint research or animal studies — used only when clearly labeled as such

We do not treat news coverage, aggregator blogs, or other secondary sources as evidence. They may be cited for context (e.g. market-research figures with no single academic source), but never as the scientific backbone of a verdict.

## 3. Evidence hierarchy

Files label the evidence type they're built on using this hierarchy, strongest to weakest:

| Level | Type | What it means |
|---|---|---|
| 1 | Systematic review / meta-analysis | Synthesizes many studies; strongest available evidence |
| 2 | Randomized controlled trial | Controlled, causal inference possible within the study's scope |
| 3 | Position statement / clinical guideline | Expert consensus, usually evidence-graded by the issuing body |
| 4 | Cohort / observational study | Real-world association; causation not established by the study alone |
| 5 | Animal / mechanistic study | Biological plausibility; cannot be assumed to transfer to humans |
| 6 | Preliminary / preprint | Not yet peer-reviewed; treated with extra caution |

A file's "Evidence Strength" rating (Strong / Moderate / Limited) reflects this hierarchy combined with sample size, replication, and how directly the source measured what the claim asserts — not how convenient or interesting the finding is.

## 4. How verdicts are assigned

The verdict evaluates the **claim's exact wording** against the **source's exact finding** — not whether the general topic or underlying science is legitimate. A claim built on excellent research can still be downgraded if its own phrasing (an absolute like "proven" or "no matter what," a stronger verb than the data supports) reaches further than what was measured.

Verdict scale:

- **Supported** — the claim's wording and the source's finding line up closely, with no meaningful gap.
- **Mostly Supported** — the core claim holds, but the specific wording overreaches in an identifiable way (e.g. implies a causal or universal claim the source didn't test).
- **Partly Supported** — real evidence exists, but a significant part of the claim (often a specific number, mechanism, or outcome) is not what the source actually shows.
- **Misleading** — the claim uses a technically true fact to imply something the evidence does not support.
- **Unsupported** — no credible evidence was found connecting the claim to real research.
- **False** — the claim directly contradicts the available evidence.

## 5. How uncertainty is communicated

- Animal studies are always identified as animal studies in the article body, never presented as human evidence.
- Observational/correlational findings are described as associations, not causes, unless the source itself demonstrates causation (e.g. via a controlled experiment).
- Preliminary or single-study findings are flagged as such, with a note that replication may change the picture.
- Study limitations acknowledged by the source's own authors (small sample size, specific population, short duration) are carried into the file rather than omitted.

## 6. How corrections are handled

See `CORRECTIONS.md` for the full policy. In short: verified errors are corrected transparently on the affected file, not silently edited or removed.

## 7. How AI-assisted drafts are fact-checked

Article drafts may be AI-assisted, but every citation, DOI, PMID, journal name, and statistic is checked against a real, retrievable source before publication. Nothing is published on the basis of a plausible-sounding but unverified citation. If a source cannot be independently confirmed, the claim is not published with a verdict — the gap is disclosed instead.

---
Last updated: August 16, 2026
