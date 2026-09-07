"""Verdict regression harness over real, already-published case files.

Why this exists: the branch/repo audit for the 2026-09-07 GEO push found that
60+ PRs have touched the verification pipeline (source agents, dictionaries,
claim decomposition, retry hardening, provider infrastructure...) with zero
automated check that `compare_claim_evidence()` still agrees with itself, or
with the site's own already-published, human-reviewed verdicts. A source
agent change or an LLM provider swap could silently shift what a claim gets
rated without any test failing.

This is a lightweight, RAGAS-inspired regression set rather than a full RAGAS
integration: RAGAS's own metrics (faithfulness, answer relevance, context
precision/recall) are LLM-judge-based, and this environment has no LLM
provider configured (`EVIDENCE_LLM_PROVIDER` unset -> NullProvider) — the
same constraint every other test in this suite already runs under. Instead,
this feeds the *deterministic* `compare_claim_evidence()` engine (the same
fallback path every other test exercises) real claim text + real published
article prose for 20 already-verified case files spanning all four verdict
buckets (Supported / Mostly Supported / Partly Supported / Misleading), and
asserts the deterministic verdict isn't a flat *contradiction* of the human
one -- not that it reproduces human nuance exactly, which a token-overlap
heuristic was never going to do.

If this test starts failing after a pipeline change, it means the
deterministic engine now flatly contradicts a human-reviewed, published
verdict where it didn't before -- worth a real look, not necessarily a bug
in the same shape as the failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evidence.engine import compare_claim_evidence
from evidence.models import Verdict
from evidence.sources import extract_html

REPO_ROOT = Path(__file__).resolve().parents[2]
CLAIMS_JSON = REPO_ROOT / "claims.json"

# One case file per Misleading/Supported/Partly-Supported entry (small buckets,
# every example matters) plus the first 6 Mostly-Supported by file_number
# (deterministic selection, not cherry-picked for passing).
_INCLUDE_VERDICTS_FULLY = {"Supported", "Misleading", "Partly Supported"}
_MOSTLY_SUPPORTED_SAMPLE_SIZE = 6

# A human verdict this deterministic engine's binary/near-binary verdict must
# not flatly contradict. UNVERIFIED (relevance too low to call) is always an
# acceptable outcome -- it's a "couldn't tell", never a contradiction.
_ACCEPTABLE_DETERMINISTIC_VERDICTS = {
    "Supported": {Verdict.SUPPORTED, Verdict.PARTIALLY_SUPPORTED, Verdict.UNVERIFIED},
    "Mostly Supported": {Verdict.SUPPORTED, Verdict.PARTIALLY_SUPPORTED, Verdict.UNVERIFIED},
    "Partly Supported": {Verdict.SUPPORTED, Verdict.PARTIALLY_SUPPORTED, Verdict.UNVERIFIED, Verdict.UNSUPPORTED},
    "Misleading": {Verdict.UNSUPPORTED, Verdict.PARTIALLY_SUPPORTED, Verdict.UNVERIFIED},
}


def _load_regression_cases() -> list[dict]:
    data = json.loads(CLAIMS_JSON.read_text(encoding="utf-8"))
    claims = data["claims"]
    by_verdict: dict[str, list[dict]] = {}
    for c in claims:
        by_verdict.setdefault(c["verdict"], []).append(c)

    selected: list[dict] = []
    for verdict in _INCLUDE_VERDICTS_FULLY:
        selected.extend(by_verdict.get(verdict, []))
    mostly = sorted(by_verdict.get("Mostly Supported", []), key=lambda c: c["file_number"])
    selected.extend(mostly[:_MOSTLY_SUPPORTED_SAMPLE_SIZE])

    selected.sort(key=lambda c: c["file_number"])
    return selected


def _article_text(source_url: str) -> str:
    slug = source_url.rsplit("/", 1)[-1]
    path = REPO_ROOT / "articles" / slug
    html = path.read_text(encoding="utf-8")
    _, text = extract_html(html)
    return text


# KNOWN BUG, found by this harness (2026-09-07): extract_html() folds the
# page's <title> and every <h1> into the same text blob it hands back as
# "body text" (see _TextExtractor.handle_data in evidence/sources.py -- it
# never excludes title/h1 content from `self.parts`). When a source's own
# headline closely restates the claim being checked -- extremely common,
# since "does X really do Y?" is precisely the headline shape a claim like
# this gets fact-checked *because* it exists -- that headline sentence wins
# compare_claim_evidence()'s token-overlap ranking outright (relevance=1.0)
# over every sentence that actually states a finding, and the engine
# confidently emits a verdict off a bare interrogative restatement instead
# of the evidence. This is a real gap in compare_claim_evidence /
# extract_html, not an artifact of this test's fixtures -- any live source
# fetched via SourceFetcher.fetch() whose own headline echoes the claim
# hits the exact same failure mode. Fixing it (e.g. excluding <title>/<h1>
# text from the comparison pool, or discounting interrogative sentences) is
# separate follow-up work; these cases are left failing on purpose so a fix
# shows up here as an unexpected xpass rather than silently going unnoticed.
_KNOWN_TITLE_ECHO_FAILURES = {5, 17, 21, 23, 29}

_CASES = _load_regression_cases()


@pytest.mark.parametrize(
    "case",
    _CASES,
    ids=[f"file{c['file_number']:03d}-{c['verdict'].replace(' ', '')}" for c in _CASES],
)
def test_deterministic_verdict_does_not_contradict_published_verdict(case: dict, request: pytest.FixtureRequest) -> None:
    if case["file_number"] in _KNOWN_TITLE_ECHO_FAILURES:
        request.node.add_marker(pytest.mark.xfail(
            reason="known bug: compare_claim_evidence matches the source's own "
                   "title/h1 instead of a finding when the headline echoes the "
                   "claim -- see _KNOWN_TITLE_ECHO_FAILURES comment above",
            strict=True,
        ))

    claim = case["claim_reviewed"]
    article_text = _article_text(case["source_url"])

    verdict, passage, relevance = compare_claim_evidence(claim, article_text)

    acceptable = _ACCEPTABLE_DETERMINISTIC_VERDICTS[case["verdict"]]
    assert verdict in acceptable, (
        f"File #{case['file_number']} ({case['title']!r}) is published as "
        f"{case['verdict']!r}, but compare_claim_evidence() against the "
        f"article's own body text returned {verdict.value!r} "
        f"(relevance={relevance}, matched passage: {passage[:160]!r}). "
        "This is either a real pipeline regression, or this test's "
        "acceptable-verdict mapping needs updating for a deliberate change "
        "in how the deterministic engine scores things -- check which "
        "before changing the assertion."
    )


def test_regression_set_covers_every_verdict_bucket() -> None:
    """Guards the harness itself: if claims.json ever drops a verdict bucket
    entirely (e.g. the last Misleading file gets corrected to something else),
    this fails loudly instead of the parametrized set silently shrinking."""
    verdicts_present = {case["verdict"] for case in _CASES}
    assert verdicts_present == set(_ACCEPTABLE_DETERMINISTIC_VERDICTS.keys())
