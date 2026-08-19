"""Evidence Graph store — in-memory graph with JSON persistence."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .model import (
    Claim, Evidence, Passage, Source, SourceType, VerificationChain, Verdict,
)

logger = logging.getLogger(__name__)


class EvidenceGraph:
    def __init__(self, persist_path: str | None = None) -> None:
        self._persist_path = persist_path
        self._claims: dict[str, Claim] = {}
        self._sources: dict[str, Source] = {}
        self._passages: dict[str, Passage] = {}
        self._evidence: dict[str, Evidence] = {}
        self._claim_sources: dict[str, set[str]] = {}
        self._source_claims: dict[str, set[str]] = {}
        self._category_claims: dict[str, set[str]] = {}
        self._author_claims: dict[str, set[str]] = {}
        if persist_path:
            self._load()

    def _load(self) -> None:
        if not self._persist_path:
            return
        path = Path(self._persist_path)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for c in data.get("claims", []):
                claim = Claim(**c)
                self._claims[claim.id] = claim
            for s in data.get("sources", []):
                s["source_type"] = SourceType(s["source_type"])
                source = Source(**s)
                self._sources[source.id] = source
            for p in data.get("passages", []):
                passage = Passage(**p)
                self._passages[passage.id] = passage
            for e in data.get("evidence", []):
                e["verdict"] = Verdict(e["verdict"])
                e["passages"] = [self._passages[pid] for pid in e.get("passage_ids", []) if pid in self._passages]
                ev = Evidence(**e)
                self._evidence[ev.id] = ev
            self._rebuild_indexes()
            logger.info(f"Loaded graph: {len(self._claims)} claims, {len(self._sources)} sources, {len(self._evidence)} evidence")
        except Exception as e:
            logger.warning(f"Failed to load graph: {e}")

    def _save(self) -> None:
        if not self._persist_path:
            return
        path = Path(self._persist_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "claims": [c.to_dict() for c in self._claims.values()],
            "sources": [s.to_dict() for s in self._sources.values()],
            "passages": [p.to_dict() for p in self._passages.values()],
            "evidence": [
                {**e.to_dict(), "passage_ids": [p.id for p in e.passages]}
                for e in self._evidence.values()
            ],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _rebuild_indexes(self) -> None:
        self._claim_sources.clear()
        self._source_claims.clear()
        self._category_claims.clear()
        self._author_claims.clear()
        for ev in self._evidence.values():
            claim_id = ev.claim_id
            for passage in ev.passages:
                source_id = passage.source_id
                self._claim_sources.setdefault(claim_id, set()).add(source_id)
                self._source_claims.setdefault(source_id, set()).add(claim_id)
        for claim in self._claims.values():
            self._category_claims.setdefault(claim.category.lower(), set()).add(claim.id)
            self._author_claims.setdefault(claim.author.lower(), set()).add(claim.id)

    def add_claim(self, claim: Claim) -> None:
        self._claims[claim.id] = claim
        self._category_claims.setdefault(claim.category.lower(), set()).add(claim.id)
        self._author_claims.setdefault(claim.author.lower(), set()).add(claim.id)
        self._save()

    def add_source(self, source: Source) -> None:
        self._sources[source.id] = source
        self._save()

    def add_passage(self, passage: Passage) -> None:
        self._passages[passage.id] = passage
        self._save()

    def add_evidence(self, evidence: Evidence) -> None:
        self._evidence[evidence.id] = evidence
        claim_id = evidence.claim_id
        for passage in evidence.passages:
            self._claim_sources.setdefault(claim_id, set()).add(passage.source_id)
            self._source_claims.setdefault(passage.source_id, set()).add(claim_id)
        self._save()

    def get_claim(self, claim_id: str) -> Claim | None:
        return self._claims.get(claim_id)

    def get_source(self, source_id: str) -> Source | None:
        return self._sources.get(source_id)

    def get_evidence_for_claim(self, claim_id: str) -> list[Evidence]:
        return [ev for ev in self._evidence.values() if ev.claim_id == claim_id]

    def get_sources_for_claim(self, claim_id: str) -> list[Source]:
        source_ids = self._claim_sources.get(claim_id, set())
        return [self._sources[sid] for sid in source_ids if sid in self._sources]

    def get_claims_for_source(self, source_id: str) -> list[Claim]:
        claim_ids = self._source_claims.get(source_id, set())
        return [self._claims[cid] for cid in claim_ids if cid in self._claims]

    def get_related_claims(self, claim_id: str) -> list[Claim]:
        claim = self._claims.get(claim_id)
        if not claim:
            return []
        related_ids: set[str] = set()
        source_ids = self._claim_sources.get(claim_id, set())
        for sid in source_ids:
            for cid in self._source_claims.get(sid, set()):
                if cid != claim_id:
                    related_ids.add(cid)
        category_ids = self._category_claims.get(claim.category.lower(), set())
        related_ids.update(category_ids - {claim_id})
        return [self._claims[cid] for cid in related_ids if cid in self._claims]

    def get_contradictions(self) -> list[tuple[Claim, Claim, str]]:
        contradictions: list[tuple[Claim, Claim, str]] = []
        evidence_by_claim: dict[str, list[Evidence]] = {}
        for ev in self._evidence.values():
            evidence_by_claim.setdefault(ev.claim_id, []).append(ev)
        claim_ids = list(evidence_by_claim.keys())
        for i, cid1 in enumerate(claim_ids):
            for cid2 in claim_ids[i + 1:]:
                e1 = evidence_by_claim[cid1]
                e2 = evidence_by_claim[cid2]
                v1 = e1[0].verdict if e1 else None
                v2 = e2[0].verdict if e2 else None
                if v1 and v2:
                    if v1 == Verdict.SUPPORTED and v2 in (Verdict.MISLEADING, Verdict.UNSUPPORTED):
                        contradictions.append((self._claims[cid1], self._claims[cid2], f"{v1.value} vs {v2.value}"))
                    elif v2 == Verdict.SUPPORTED and v1 in (Verdict.MISLEADING, Verdict.UNSUPPORTED):
                        contradictions.append((self._claims[cid1], self._claims[cid2], f"{v1.value} vs {v2.value}"))
        return contradictions

    def search_claims(self, query: str, category: str | None = None, verdict: str | None = None) -> list[Claim]:
        results: list[Claim] = []
        query_lower = query.lower()
        for claim in self._claims.values():
            if category and claim.category.lower() != category.lower():
                continue
            if verdict:
                evs = self.get_evidence_for_claim(claim.id)
                if evs and evs[0].verdict.value != verdict.lower():
                    continue
            if query_lower in claim.text.lower() or query_lower in claim.category.lower():
                results.append(claim)
        return results

    def get_chain(self, claim_id: str) -> VerificationChain | None:
        claim = self._claims.get(claim_id)
        if not claim:
            return None
        evidence_list = self.get_evidence_for_claim(claim_id)
        evidence = evidence_list[0] if evidence_list else None
        if not evidence:
            return VerificationChain(claim=claim, evidence=Evidence(
                id="", claim_id=claim_id, passages=[], verdict=Verdict.UNVERIFIED,
                confidence=0.0, rating_value=0,
            ), sources=[])
        sources = self.get_sources_for_claim(claim_id)
        return VerificationChain(claim=claim, evidence=evidence, sources=sources)

    def get_stats(self) -> dict[str, Any]:
        return {
            "claims": len(self._claims),
            "sources": len(self._sources),
            "passages": len(self._passages),
            "evidence": len(self._evidence),
            "categories": list(self._category_claims.keys()),
            "verdict_distribution": self._verdict_distribution(),
        }

    def _verdict_distribution(self) -> dict[str, int]:
        dist: dict[str, int] = {}
        for ev in self._evidence.values():
            key = ev.verdict.value
            dist[key] = dist.get(key, 0) + 1
        return dist

    def clear(self) -> None:
        self._claims.clear()
        self._sources.clear()
        self._passages.clear()
        self._evidence.clear()
        self._claim_sources.clear()
        self._source_claims.clear()
        self._category_claims.clear()
        self._author_claims.clear()
        self._save()
