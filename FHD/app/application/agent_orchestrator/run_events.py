"""Event record model for the agent-run control plane."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.application.agent_orchestrator.run_model_support import new_id, utc_now_iso


@dataclass
class RunEvent:
    run_id: str
    event_type: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: new_id("evt"))
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "message": self.message,
            "data": self.data,
            "created_at": self.created_at,
        }


def run_event_from_dict(data: dict[str, Any]) -> RunEvent:
    return RunEvent(
        run_id=str(data.get("run_id") or ""),
        event_type=str(data.get("event_type") or ""),
        message=str(data.get("message") or ""),
        data=dict(data.get("data") or {}),
        event_id=str(data.get("event_id") or "") or new_id("evt"),
        created_at=str(data.get("created_at") or "") or utc_now_iso(),
    )
