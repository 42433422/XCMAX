"""工单状态机。"""

from __future__ import annotations

from enum import Enum


class WorkOrderStatus(str, Enum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset(
    {WorkOrderStatus.SUCCEEDED.value, WorkOrderStatus.FAILED.value, WorkOrderStatus.CANCELLED.value}
)

# 允许的状态流转（单向推进，禁止从终态复活）。
_ALLOWED: dict[str, frozenset[str]] = {
    WorkOrderStatus.PENDING.value: frozenset(
        {WorkOrderStatus.DISPATCHED.value, WorkOrderStatus.CANCELLED.value}
    ),
    WorkOrderStatus.DISPATCHED.value: frozenset(
        {
            WorkOrderStatus.RUNNING.value,
            WorkOrderStatus.SUCCEEDED.value,
            WorkOrderStatus.FAILED.value,
            WorkOrderStatus.CANCELLED.value,
        }
    ),
    WorkOrderStatus.RUNNING.value: frozenset(
        {WorkOrderStatus.SUCCEEDED.value, WorkOrderStatus.FAILED.value}
    ),
}


def can_transition(current: str, target: str) -> bool:
    """current → target 是否为合法流转。"""
    return str(target) in _ALLOWED.get(str(current), frozenset())
