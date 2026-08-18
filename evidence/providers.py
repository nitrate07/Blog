"""Provider seam. No LLM provider is required for the deterministic MVP."""

from typing import Protocol

from .models import Verdict


class VerificationProvider(Protocol):
    """Optional future provider for comparing a claim with an extracted passage."""

    async def compare(self, claim: str, passage: str, context: str | None = None) -> Verdict | None:
        """Return a constrained verdict, or None when unable to determine one."""


class NullProvider:
    """Makes the evidence-first deterministic path explicit when no LLM is configured."""

    async def compare(self, claim: str, passage: str, context: str | None = None) -> Verdict | None:
        return None
