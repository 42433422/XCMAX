"""Product policy over the existing platform budget and employee runtimes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

IDENTITY_ID = "xcmax:management:xiaoc"
MINIMUM_LEVEL = {"enterprise": 4, "exploration": 5, "reflection": 6}


class LifePolicyError(ValueError):
    """A mode, authority, budget or concurrency boundary rejected the operation."""


def utcnow() -> datetime:
    return datetime.now(UTC)


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include its timezone")
    return parsed.astimezone(UTC)


class LifePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    daily_token_limit: int = Field(default=0, ge=0, le=1_000_000)
    daily_cycle_limit: int = Field(default=4, ge=1, le=96)
    exploration_percent: int = Field(default=20, ge=0, le=50)
    wake_interval_seconds: int = Field(default=900, ge=60, le=86400)
    authorization_expires_at: str | None = None
    portfolio_limits: dict[str, Any] | None = None
    employee_id: str = Field(default="", max_length=128)
    task_input: dict[str, Any] = Field(default_factory=dict)

    @field_validator("task_input")
    @classmethod
    def valid_task_input(cls, value: dict[str, Any]) -> dict[str, Any]:
        from modstore_server.strategic_execution_contract import validate_input

        return validate_input(value)

    @field_validator("authorization_expires_at")
    @classmethod
    def valid_expiry(cls, value: str | None) -> str | None:
        return parse_time(value).isoformat() if value else None

    @field_validator("portfolio_limits")
    @classmethod
    def valid_portfolio(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        from modstore_server.strategic_portfolio import PortfolioLimits

        return PortfolioLimits.model_validate(value).model_dump()


class LifeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1)
    level: int | None = Field(default=None, ge=1, le=6)
    paused: bool | None = None
    mission: str | None = Field(default=None, min_length=1, max_length=1000)
    policy: dict[str, Any] | None = None
