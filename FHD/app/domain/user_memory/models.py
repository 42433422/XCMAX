"""Value objects shared by the lightweight user-memory service."""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ActionPattern:
    pattern: str
    intent: str
    slots: dict[str, Any]
    frequency: int = 1
    last_used: str = field(default_factory=lambda: datetime.now().isoformat())
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionPattern":
        return cls(**data)


@dataclass
class FeedbackRecord:
    timestamp: str
    message: str
    recognized_intent: str
    user_feedback: str
    corrected_intent: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FeedbackRecord":
        return cls(**data)


@dataclass
class ContextSummary:
    timestamp: str
    intent: str
    slots: dict[str, Any]
    message: str
    turn_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextSummary":
        return cls(**data)


@dataclass
class UserMemory:
    user_id: str
    preferences: dict[str, Any] = field(default_factory=dict)
    frequent_actions: list[dict[str, Any]] = field(default_factory=list)
    historical_contexts: list[dict[str, Any]] = field(default_factory=list)
    feedback_history: list[dict[str, Any]] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserMemory":
        return cls(**data)
