"""Canonical risk types and decision aggregation for the autonomy domain."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"


class MediumRiskPolicy(str, Enum):
    AUTO_APPROVE = "auto_approve"
    REQUIRE_HUMAN = "require_human"
    COOLDOWN_60MIN = "cooldown_60min"


class ProhibitedActionError(PermissionError):
    def __init__(self, action: str, reason: str, *, action_id: str = "") -> None:
        self.action = action
        self.reason = reason
        self.action_id = action_id
        super().__init__(f"prohibited autonomous action {action}: {reason}")


@dataclass
class RiskDecision:
    # First three fields preserve the established workflow-gate constructor.
    requires_confirmation: bool
    reason: str
    blocking_nodes: list[str] | None = field(default_factory=list)
    allowed: bool = False
    risk_level: RiskLevel = RiskLevel.BLOCKED
    decision: str = "blocked"
    action: str = "unknown"
    action_id: str = ""
    rollback_path: str = ""
    policy: str = ""
    approver: str = ""
    prohibited: bool = False
    denied_nodes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "action_id": self.action_id,
            "allowed": self.allowed,
            "approver": self.approver or None,
            "blocking_nodes": list(self.blocking_nodes or []),
            "decision": self.decision,
            "denied_nodes": list(self.denied_nodes or []),
            "policy": self.policy,
            "prohibited": self.prohibited,
            "reason": self.reason,
            "requires_confirmation": self.requires_confirmation,
            "risk_level": self.risk_level.value,
            "rollback_path": self.rollback_path,
        }


def truthy(value: Any) -> bool:
    if value is True:
        return True
    return isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}


def parse_risk_level(value: Any, *, default: RiskLevel = RiskLevel.BLOCKED) -> RiskLevel:
    if isinstance(value, RiskLevel):
        return value
    raw = str(getattr(value, "value", value) or "").strip().lower()
    try:
        return RiskLevel(raw)
    except ValueError:
        return default


def enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def aggregate_risk_decisions(
    node_decisions: Iterable[tuple[str, RiskDecision]],
    *,
    action: str,
    action_id: str,
) -> RiskDecision:
    """Combine evaluated nodes without recreating risk policy in application callers."""

    decisions = list(node_decisions)
    blocking_nodes = [node_id for node_id, decision in decisions if decision.requires_confirmation]
    denied_nodes = [
        node_id
        for node_id, decision in decisions
        if not decision.requires_confirmation and not decision.allowed
    ]
    rank = {
        RiskLevel.LOW: 0,
        RiskLevel.MEDIUM: 1,
        RiskLevel.HIGH: 2,
        RiskLevel.BLOCKED: 3,
    }
    aggregate = max(
        (decision.risk_level for _, decision in decisions),
        key=lambda item: rank[item],
        default=RiskLevel.LOW,
    )
    reason = (
        "plan contains actions denied by autonomy_guard"
        if denied_nodes
        else "plan requires human risk approval"
        if blocking_nodes
        else "all plan actions approved by autonomy_guard"
    )
    return RiskDecision(
        requires_confirmation=bool(blocking_nodes),
        reason=reason,
        blocking_nodes=blocking_nodes,
        allowed=not blocking_nodes and not denied_nodes,
        risk_level=aggregate,
        decision="blocked" if denied_nodes else "require_human" if blocking_nodes else "allow",
        action=action,
        action_id=action_id,
        denied_nodes=denied_nodes,
    )


__all__ = [
    "MediumRiskPolicy",
    "ProhibitedActionError",
    "RiskDecision",
    "RiskLevel",
    "aggregate_risk_decisions",
    "enum_value",
    "parse_risk_level",
    "truthy",
]
