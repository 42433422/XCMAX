"""Employee domain types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass(frozen=True)
class Employee:
    """Logical employee identity exposed to callers."""

    employee_id: str
    label: str = ""


@dataclass(frozen=True)
class EmployeePack:
    """Registered employee pack artifact."""

    pack_id: str
    mod_id: str
    version: str
    author_id: int
    manifest: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EmployeeExecution:
    """Single task execution record."""

    employee_id: str
    user_id: int
    task: str
    status: ExecutionStatus
    detail: dict[str, Any] = field(default_factory=dict)
