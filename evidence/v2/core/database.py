"""Persistent storage for evidence graph using SQLite."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from ..core.types import (
    Claim,
    Contradiction,
    Evidence,
    MethodologicalEvidence,
    Passage,
    Source,
    SourceType,
    StudyDesign,
    VerificationRecord,
    Verdict,
)

logger = logging.getLogger(__name__)


class EvidenceDatabase:
    """SQLite-based persistent storage for evidence graph."""
    
    def __init__(self, db_path: str = "evidence_graph.db") -> None:
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS claims (
                    id TEXT PRIMARY KEY,
                    text TEXT,
                    author TEXT,
                    category TEXT,
                    date_filed TEXT,
                    file_number INTEGER
                );
                
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY,
                    url TEXT,
                    title TEXT,
                    source_type TEXT,
                    doi TEXT,
                    pmid TEXT,
                    published_year INTEGER,
                    journal TEXT,
                    impact_factor REAL,
                    study_design TEXT,
                    authors TEXT
                );
                
                CREATE TABLE IF NOT EXISTS passages (
                    id TEXT PRIMARY KEY,
                    text TEXT,
                    source_id TEXT,
                    relevance REAL,
                    content_hash TEXT,
                    start_offset INTEGER,
                    end_offset INTEGER,
                    verified INTEGER,
                    verification_url TEXT
                );
                
                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY,
                    claim_id TEXT,
                    verdict TEXT,
                    confidence REAL,
                    rating_value INTEGER,
                    rating_explanation TEXT,
                    methodological_evidence TEXT,
                    supporting_sources TEXT,
                    contradicting_sources TEXT
                );
                
                CREATE TABLE IF NOT EXISTS evidence_passages (
                    evidence_id TEXT,
                    passage_id TEXT,
                    PRIMARY KEY (evidence_id, passage_id)
                );
                
                CREATE TABLE IF NOT EXISTS contradictions (
                    id TEXT PRIMARY KEY,
                    source1_id TEXT,
                    source2_id TEXT,
                    claim_id TEXT,
                    contradiction_type TEXT,
                    description TEXT,
                    source1_verdict TEXT,
                    source2_verdict TEXT
                );
                
                CREATE TABLE IF NOT EXISTS verification_history (
                    id TEXT PRIMARY KEY,
                    query TEXT,
                    claim_text TEXT,
                    verdict TEXT,
                    confidence REAL,
                    rating_value INTEGER,
                    sources_count INTEGER,
                    passages_count INTEGER,
                    contradictions_count INTEGER,
                    created_at TEXT,
                    steps TEXT,
                    cited_response TEXT
                );
            """)
    
    def save_claim(self, claim: Claim) -> None:
        """Save a claim to the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO claims VALUES (?, ?, ?, ?, ?, ?)",
                (claim.id, claim.text, claim.author, claim.category,
                 claim.date_filed, claim.file_number)
            )
    
    def save_source(self, source: Source) -> None:
        """Save a source to the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (source.id, source.url, source.title, source.source_type.value,
                 source.doi, source.pmid, source.published_year, source.journal,
                 source.impact_factor, source.study_design.value,
                 json.dumps(source.authors))
            )
    
    def save_passage(self, passage: Passage) -> None:
        """Save a passage to the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO passages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (passage.id, passage.text, passage.source_id, passage.relevance,
                 passage.content_hash, passage.start_offset, passage.end_offset,
                 1 if passage.verified else 0, passage.verification_url)
            )
    
    def save_evidence(self, evidence: Evidence) -> None:
        """Save evidence to the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (evidence.id, evidence.claim_id, evidence.verdict.value,
                 evidence.confidence, evidence.rating_value,
                 evidence.rating_explanation,
                 json.dumps([m.to_dict() for m in evidence.methodological_evidence]),
                 json.dumps(evidence.supporting_sources),
                 json.dumps(evidence.contradicting_sources))
            )
            for passage in evidence.passages:
                conn.execute(
                    "INSERT OR REPLACE INTO evidence_passages VALUES (?, ?)",
                    (evidence.id, passage.id)
                )
    
    def save_contradiction(self, contradiction: Contradiction) -> None:
        """Save a contradiction to the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO contradictions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (contradiction.id, contradiction.source1_id, contradiction.source2_id,
                 contradiction.claim_id, contradiction.contradiction_type.value,
                 contradiction.description, contradiction.source1_verdict,
                 contradiction.source2_verdict)
            )
    
    def save_verification_record(self, record: VerificationRecord) -> None:
        """Save a verification record to the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO verification_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (record.id, record.query, record.claim_text, record.verdict,
                 record.confidence, record.rating_value, record.sources_count,
                 record.passages_count, record.contradictions_count,
                 record.created_at, json.dumps(record.steps), record.cited_response)
            )
    
    def get_claim(self, claim_id: str) -> Claim | None:
        """Get a claim from the database."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if row:
                return Claim(
                    id=row[0], text=row[1], author=row[2],
                    category=row[3], date_filed=row[4], file_number=row[5]
                )
        return None
    
    def get_verification_history(self, limit: int = 100) -> list[VerificationRecord]:
        """Get verification history."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM verification_history ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [
                VerificationRecord(
                    id=r[0], query=r[1], claim_text=r[2], verdict=r[3],
                    confidence=r[4], rating_value=r[5], sources_count=r[6],
                    passages_count=r[7], contradictions_count=r[8],
                    created_at=r[9], steps=json.loads(r[10]), cited_response=r[11]
                )
                for r in rows
            ]
    
    def get_stats(self) -> dict[str, Any]:
        """Get database statistics."""
        with sqlite3.connect(self.db_path) as conn:
            return {
                "claims": conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0],
                "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
                "passages": conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0],
                "evidence": conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0],
                "contradictions": conn.execute("SELECT COUNT(*) FROM contradictions").fetchone()[0],
                "verifications": conn.execute("SELECT COUNT(*) FROM verification_history").fetchone()[0],
            }
