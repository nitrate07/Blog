"""Safe defaults for retrieval, persistence, and public API access."""

from dataclasses import dataclass
import os


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    request_timeout_seconds: float = float(os.getenv("EVIDENCE_REQUEST_TIMEOUT_SECONDS", "8"))
    max_response_bytes: int = int(os.getenv("EVIDENCE_MAX_RESPONSE_BYTES", "1000000"))
    max_redirects: int = int(os.getenv("EVIDENCE_MAX_REDIRECTS", "3"))
    user_agent: str = os.getenv("EVIDENCE_USER_AGENT", "AriKaynakEvidence/0.1 (+https://github.com/nitrate07/Blog)")
    database_path: str = os.getenv("EVIDENCE_DATABASE_PATH", "evidence/data/evidence.db")
    require_api_key: bool = _env_bool("EVIDENCE_REQUIRE_API_KEY", True)
    bootstrap_api_key: str | None = os.getenv("EVIDENCE_BOOTSTRAP_API_KEY") or None
    api_rate_limit_per_minute: int = int(os.getenv("EVIDENCE_API_RATE_LIMIT_PER_MINUTE", "30"))


settings = Settings()
