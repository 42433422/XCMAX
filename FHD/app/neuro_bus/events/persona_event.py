# FHD/app/neuro_bus/events/persona_event.py
"""Persona 领域事件。"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.persona.value_objects import PersonaAxes


@dataclass(frozen=True)
class PersonaUpdated:
    """Persona 画像更新事件。

    发布时机：
    - L1 每轮发布（轻量）
    - L2/L3 触发时发布（重量）
    - 身份漂移时发布（重要，需监控）
    """

    user_id: str
    axes: PersonaAxes
    rapport: float
    identity: str
    source: str  # "l1" | "l2" | "l3" | "fusion"
    trace_id: str

    @property
    def event_type(self) -> str:
        return "persona.updated"

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "axes": self.axes.to_dict(),
            "rapport": self.rapport,
            "identity": self.identity,
            "source": self.source,
            "trace_id": self.trace_id,
        }
