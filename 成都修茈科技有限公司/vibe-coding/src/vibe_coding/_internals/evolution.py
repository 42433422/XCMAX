"""``now_iso`` + minimal ``EvolutionEvent`` lifted from eskill.models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class EvolutionEvent:
    skill_id: str
    event_type: str
    run_id: str = ""
    stage: str = ""
    trigger_signal: str = ""
    strategy: str = ""
    patch: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    solidified_version: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    diagnosis: dict[str, Any] | None = None
    analysis_report: dict[str, Any] | None = None
    sandbox_summary: dict[str, Any] | None = None
    rollout_phase: str = ""
    event_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "event_type": self.event_type,
            "run_id": self.run_id,
            "stage": self.stage,
            "trigger_signal": self.trigger_signal,
            "strategy": self.strategy,
            "patch": self.patch,
            "validation": self.validation,
            "solidified_version": self.solidified_version,
            "details": dict(self.details),
            "diagnosis": self.diagnosis,
            "analysis_report": self.analysis_report,
            "sandbox_summary": self.sandbox_summary,
            "rollout_phase": self.rollout_phase,
            "event_id": self.event_id,
            "created_at": self.created_at,
        }
