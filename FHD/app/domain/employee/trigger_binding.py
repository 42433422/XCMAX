# -*- coding: utf-8 -*-
"""员工触发绑定值对象。

把 manifest 顶层 ``triggers``（on_error / on_quality_fail / on_coverage_miss）
+ ``sla``（escalate_to_human / timeout）建模为「该员工应订阅的事件类型 + 预算约束」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.employee.events import event_types_for_triggers


@dataclass(frozen=True)
class TriggerBinding:
    employee_id: str
    event_types: tuple[str, ...] = field(default_factory=tuple)
    max_patch_budget_tokens: int = 0
    max_patch_steps: int = 0
    escalate_to_human: bool = False

    @property
    def active(self) -> bool:
        return bool(self.event_types)

    @classmethod
    def from_manifest(cls, employee_id: str, manifest: dict[str, Any] | None) -> TriggerBinding:
        manifest = manifest if isinstance(manifest, dict) else {}
        triggers = manifest.get("triggers") if isinstance(manifest.get("triggers"), dict) else {}
        v2 = manifest.get("employee_config_v2") if isinstance(manifest.get("employee_config_v2"), dict) else {}
        if not triggers and isinstance(v2.get("triggers"), dict):
            triggers = v2["triggers"]
        sla = manifest.get("sla") if isinstance(manifest.get("sla"), dict) else {}
        if not sla and isinstance(v2.get("sla"), dict):
            sla = v2["sla"]
        event_types = tuple(event_types_for_triggers(triggers))
        return cls(
            employee_id=str(employee_id or "").strip(),
            event_types=event_types,
            max_patch_budget_tokens=int(triggers.get("max_patch_budget_tokens") or 0),
            max_patch_steps=int(triggers.get("max_patch_steps") or 0),
            escalate_to_human=bool(sla.get("escalate_to_human")),
        )


__all__ = ["TriggerBinding"]
