"""LLM domain types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LlmCredential:
    """User-scoped LLM credential reference (secrets live encrypted at rest)."""

    user_id: int
    provider: str
    credential_ref: str


@dataclass(frozen=True)
class LlmQuotaTicket:
    """Metering slice for a single LLM call."""

    user_id: int
    provider: str
    model: str
    tokens: int
    cost: float
