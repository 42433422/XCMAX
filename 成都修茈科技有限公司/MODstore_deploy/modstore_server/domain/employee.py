"""AI 员工领域模型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EmployeeRef:
    employee_id: str
    name: str
