"""Append-only provenance and privacy-minimised audit storage."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterator
from uuid import uuid4

from .models import VerificationResponse


class VerificationStore:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        if database_path != ":memory:":
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    key_prefix TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    rate_limit_per_minute INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS verifications (
                    id TEXT PRIMARY KEY,
                    api_key_id TEXT,
                    claim_hash TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source_quality TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    FOREIGN KEY(api_key_id) REFERENCES api_keys(id)
                );
                CREATE TABLE IF NOT EXISTS evidence_provenance (
                    id TEXT PRIMARY KEY,
                    verification_id TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    title TEXT,
                    passage TEXT NOT NULL,
                    relevance REAL NOT NULL,
                    content_hash TEXT,
                    captured_at TEXT NOT NULL,
                    FOREIGN KEY(verification_id) REFERENCES verifications(id)
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    api_key_id TEXT,
                    event_type TEXT NOT NULL,
                    resource_id TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(api_key_id) REFERENCES api_keys(id)
                );
                """
            )

    @staticmethod
    def hash_secret(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def ensure_api_key(self, raw_key: str, name: str, rate_limit_per_minute: int) -> str:
        key_hash = self.hash_secret(raw_key)
        with self._connection() as connection:
            existing = connection.execute("SELECT id FROM api_keys WHERE key_hash = ?", (key_hash,)).fetchone()
            if existing:
                return str(existing["id"])
            key_id = uuid4().hex
            connection.execute(
                "INSERT INTO api_keys (id, name, key_prefix, key_hash, rate_limit_per_minute, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (key_id, name, raw_key[:8], key_hash, rate_limit_per_minute, self._now()),
            )
            return key_id

    def find_api_key(self, raw_key: str) -> sqlite3.Row | None:
        key_hash = self.hash_secret(raw_key)
        with self._connection() as connection:
            return connection.execute(
                "SELECT id, name, key_hash, rate_limit_per_minute, enabled FROM api_keys WHERE key_hash = ?", (key_hash,)
            ).fetchone()

    def record_verification(self, response: VerificationResponse, api_key_id: str | None) -> str:
        verification_id = uuid4().hex
        response.verification_id = verification_id
        payload = response.model_dump(mode="json")
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO verifications VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    verification_id, api_key_id, self.hash_secret(response.claim), response.checked_at.isoformat(),
                    response.verdict.value, response.confidence, response.source_quality.value, json.dumps(payload, separators=(",", ":")),
                ),
            )
            for evidence in response.evidence:
                connection.execute(
                    "INSERT INTO evidence_provenance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        uuid4().hex, verification_id, evidence.source_url, evidence.source_type.value, evidence.title,
                        evidence.passage, evidence.relevance, evidence.source_content_hash, response.checked_at.isoformat(),
                    ),
                )
            self._audit(connection, api_key_id, "verification.created", verification_id)
        return verification_id

    def get_verification(self, verification_id: str) -> VerificationResponse | None:
        with self._connection() as connection:
            row = connection.execute("SELECT response_json FROM verifications WHERE id = ?", (verification_id,)).fetchone()
        return VerificationResponse.model_validate_json(row["response_json"]) if row else None

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _audit(self, connection: sqlite3.Connection, api_key_id: str | None, event_type: str, resource_id: str | None) -> None:
        connection.execute("INSERT INTO audit_events VALUES (?, ?, ?, ?, ?)", (uuid4().hex, api_key_id, event_type, resource_id, self._now()))
