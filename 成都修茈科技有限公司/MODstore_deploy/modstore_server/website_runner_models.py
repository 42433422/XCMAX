"""Value objects emitted by the website incident runner."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ActionResult:
    action: str
    ok: bool
    detail: str = ""
    response_excerpt: str = ""
    duration_ms: float = 0.0


@dataclass
class DispatchReport:
    event_id: int
    event_type: str
    scope: str
    action: str
    ok: bool
    reason: str = ""
    results: list[ActionResult] = field(default_factory=list)
    dispatched_count_before: int = 0
    dispatched_count_after: int = 0
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["ActionResult", "DispatchReport"]
