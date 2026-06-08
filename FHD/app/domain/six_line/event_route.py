"""六线事件轨路由值对象。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EventRoute:
    id: str
    action: str
    priority: str = "P2"
    step_id: str | None = None
    line_step: str | None = None
    six_line: str | None = None
    event_type: str | None = None
    status_in: tuple[str, ...] = ()
    triggers: tuple[str, ...] = ()
    dispatch_line: str | None = None
    list_kind: str | None = None
    also_incident: str | None = None
    from_step: str | None = None
    to_step: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EventRoute:
        status = raw.get("status_in") or []
        triggers = raw.get("triggers") or []
        step_id = raw.get("step_id") or raw.get("line_step")
        return cls(
            id=str(raw.get("id") or ""),
            action=str(raw.get("action") or "incident"),
            priority=str(raw.get("priority") or "P2"),
            step_id=step_id,
            line_step=raw.get("line_step") or raw.get("step_id"),
            six_line=raw.get("six_line"),
            event_type=raw.get("event_type"),
            status_in=tuple(str(s) for s in status),
            triggers=tuple(str(t) for t in triggers),
            dispatch_line=raw.get("dispatch_line"),
            list_kind=raw.get("list_kind"),
            also_incident=raw.get("also_incident"),
            from_step=raw.get("from_step"),
            to_step=raw.get("to_step"),
        )

    def matches_step_status(self, step_id: str, status: str) -> bool:
        sid = self.step_id or self.line_step
        if sid and sid != step_id:
            return False
        if self.status_in and status not in self.status_in:
            return False
        return True

    def matches_event_type(self, event_type: str | None) -> bool:
        if not event_type:
            return self.event_type is None
        if self.event_type and self.event_type == event_type:
            return True
        if self.also_incident and self.also_incident == event_type:
            return True
        return False
