"""Deterministic workflow risk review and durable approval request creation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .approval_service import ApprovalService, get_approval_service
from .risk_gate import HybridRiskGate, RiskDecision
from .workflow_types import PlanGraph, RiskLevel


@dataclass
class GatedNodeDecision:
    node_id: str
    tool_id: str
    action: str
    risk: str
    requires_approval: bool
    approval_request_id: str = ""
    approved: bool | None = None
    rejected: bool | None = None
    reason: str = ""


@dataclass
class GatedPlanDecision:
    plan_id: str
    risk_decision: RiskDecision
    node_decisions: list[GatedNodeDecision] = field(default_factory=list)
    approval_request_ids: list[str] = field(default_factory=list)
    all_approved: bool = False
    any_rejected: bool = False
    pending_approval: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "risk_decision": {
                "requires_confirmation": self.risk_decision.requires_confirmation,
                "reason": self.risk_decision.reason,
                "blocking_nodes": list(self.risk_decision.blocking_nodes or []),
                "denied_nodes": list(self.risk_decision.denied_nodes or []),
            },
            "node_decisions": [
                {
                    "node_id": item.node_id,
                    "tool_id": item.tool_id,
                    "action": item.action,
                    "risk": item.risk,
                    "requires_approval": item.requires_approval,
                    "approval_request_id": item.approval_request_id,
                    "approved": item.approved,
                    "rejected": item.rejected,
                    "reason": item.reason,
                }
                for item in self.node_decisions
            ],
            "approval_request_ids": list(self.approval_request_ids),
            "all_approved": self.all_approved,
            "any_rejected": self.any_rejected,
            "pending_approval": self.pending_approval,
        }


class WorkflowApprovalPolicy:
    """Review a complete plan and request human approval where policy requires it.

    This class cannot execute or resume a workflow. AgentOrchestrator owns all
    business execution and approval continuation through the persisted AgentRun.
    """

    def __init__(
        self,
        risk_gate: HybridRiskGate | None = None,
        approval_service: ApprovalService | None = None,
        *,
        require_persistence: bool = False,
    ) -> None:
        self._risk_gate = risk_gate or HybridRiskGate()
        self._approval_service = approval_service or get_approval_service()
        self._require_persistence = require_persistence

    def evaluate_plan(
        self,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None = None,
    ) -> GatedPlanDecision:
        context = dict(runtime_context or {})
        if not plan.nodes:
            return self._rejected_plan(plan, "计划没有可审核的执行节点")
        try:
            risk = self._risk_gate.evaluate(plan=plan, context=context)
        except (TypeError, ValueError) as exc:
            return self._rejected_plan(plan, f"计划风险审核失败：{type(exc).__name__}")

        decision = GatedPlanDecision(plan_id=plan.plan_id, risk_decision=risk)
        denied_nodes = set(risk.denied_nodes or [])
        blocking_nodes = set(risk.blocking_nodes or [])
        for node in plan.nodes:
            item = GatedNodeDecision(
                node_id=node.node_id,
                tool_id=node.tool_id,
                action=node.action,
                risk=node.risk,
                requires_approval=node.node_id in blocking_nodes,
            )
            if node.node_id in denied_nodes:
                item.rejected = True
                item.reason = "denied by autonomy_guard"
            elif item.requires_approval:
                request = self._approval_service.create_approval_request(
                    plan_id=plan.plan_id,
                    node=node,
                    runtime_context=context,
                    plan=plan,
                    require_persistence=self._require_persistence,
                )
                item.approval_request_id = str(request.request_id or "")
                if not item.approval_request_id:
                    item.rejected = True
                    item.reason = "approval request was not persisted"
                else:
                    decision.approval_request_ids.append(item.approval_request_id)
                    item.reason = "pending human approval"
            else:
                item.approved = True
                item.reason = "deterministic policy allows execution"
            decision.node_decisions.append(item)

        decision.any_rejected = any(item.rejected for item in decision.node_decisions)
        decision.pending_approval = any(
            item.requires_approval and item.approved is None and not item.rejected
            for item in decision.node_decisions
        )
        decision.all_approved = bool(decision.node_decisions) and all(
            item.approved is True for item in decision.node_decisions
        )
        return decision

    @staticmethod
    def _rejected_plan(plan: PlanGraph, reason: str) -> GatedPlanDecision:
        risk = RiskDecision(
            requires_confirmation=True,
            reason=reason,
            blocking_nodes=[],
            allowed=False,
            risk_level=RiskLevel.HIGH,
            decision="reject_invalid_plan",
            action=f"workflow:{plan.plan_id}",
            action_id=plan.plan_id,
        )
        return GatedPlanDecision(
            plan_id=plan.plan_id,
            risk_decision=risk,
            node_decisions=[
                GatedNodeDecision(
                    node_id=node.node_id,
                    tool_id=node.tool_id,
                    action=node.action,
                    risk="high",
                    requires_approval=False,
                    rejected=True,
                    reason=reason,
                )
                for node in plan.nodes
            ],
            any_rejected=True,
        )


__all__ = ["GatedNodeDecision", "GatedPlanDecision", "WorkflowApprovalPolicy"]
