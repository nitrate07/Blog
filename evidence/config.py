"""Safe, conservative defaults for remote-source retrieval."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    request_timeout_seconds: float = float(os.getenv("EVIDENCE_REQUEST_TIMEOUT_SECONDS", "8"))
    max_response_bytes: int = int(os.getenv("EVIDENCE_MAX_RESPONSE_BYTES", "1000000"))
    max_redirects: int = int(os.getenv("EVIDENCE_MAX_REDIRECTS", "3"))
    user_agent: str = os.getenv("EVIDENCE_USER_AGENT", "AriKaynakEvidence/0.1 (+https://github.com/nitrate07/Blog)")


settings = Settings()
