"""AI Agent V1 写操作门控引擎（基于 HybridRiskGate + ApprovalService）。

V0 → V1 升级点：
- V0 只能跑只读链；V1 允许写操作（订单/客户/发货等），但**必经审批门控**。
- 集成现有 HybridRiskGate + ApprovalService，无缝衔接 /api/approval 工作台。
- 支持：自动审批（CLI 演示用）、人工审批（生产用）、批量审批。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .approval_service import ApprovalService, get_approval_service
from .engine import WorkflowEngine
from .risk_gate import HybridRiskGate, RiskDecision
from .types import PlanGraph, WorkflowRunResult

logger = logging.getLogger(__name__)


@dataclass
class GatedNodeDecision:
    """单个节点的审批决策。"""

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
    """整个计划的门控决策。"""

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
            },
            "node_decisions": [
                {
                    "node_id": nd.node_id,
                    "tool_id": nd.tool_id,
                    "action": nd.action,
                    "risk": nd.risk,
                    "requires_approval": nd.requires_approval,
                    "approval_request_id": nd.approval_request_id,
                    "approved": nd.approved,
                    "rejected": nd.rejected,
                    "reason": nd.reason,
                }
                for nd in self.node_decisions
            ],
            "approval_request_ids": list(self.approval_request_ids),
            "all_approved": self.all_approved,
            "any_rejected": self.any_rejected,
            "pending_approval": self.pending_approval,
        }


class ApprovalGatedEngine:
    """
    在 HybridRiskGate + ApprovalService 之上做"先审批、后执行"的门控执行。

    流程：
      1) gate = HybridRiskGate().evaluate(plan, context) — 决策是否需要确认
      2) 对每个 blocking_node，调用 ApprovalService.create_approval_request()
      3) 若 strategy=auto_approve，则自动 approve；strategy=reject 自动 reject
      4) 若 strategy=interactive，返回 pending 状态（等人工调 /api/approval/approve）
      5) 全部通过后调用 resume_after_approval() 继续执行
    """

    APPROVAL_STRATEGY_AUTO = "auto"
    APPROVAL_STRATEGY_INTERACTIVE = "interactive"
    APPROVAL_STRATEGY_REJECT = "reject"

    def __init__(
        self,
        engine: WorkflowEngine,
        risk_gate: HybridRiskGate | None = None,
        approval_service: ApprovalService | None = None,
    ) -> None:
        self._engine = engine
        self._risk_gate = risk_gate or HybridRiskGate()
        self._approval_service = approval_service or get_approval_service()

    def evaluate_plan(
        self,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None = None,
        strategy: str = APPROVAL_STRATEGY_INTERACTIVE,
    ) -> GatedPlanDecision:
        runtime_context = dict(runtime_context or {})
        risk_decision = self._risk_gate.evaluate(plan=plan, context=runtime_context)
        decision = GatedPlanDecision(plan_id=plan.plan_id, risk_decision=risk_decision)

        for node in plan.nodes:
            nd = GatedNodeDecision(
                node_id=node.node_id,
                tool_id=node.tool_id,
                action=node.action,
                risk=node.risk,
                requires_approval=node.node_id in (risk_decision.blocking_nodes or []),
            )

            if nd.requires_approval:
                req = self._approval_service.create_approval_request(
                    plan_id=plan.plan_id,
                    node=node,
                    runtime_context=runtime_context,
                    plan=plan,
                )
                nd.approval_request_id = req.request_id
                decision.approval_request_ids.append(req.request_id)

                if strategy == ApprovalGatedEngine.APPROVAL_STRATEGY_AUTO:
                    self._approval_service.approve(
                        req.request_id, comment="auto-approved by gated engine"
                    )
                    nd.approved = True
                    nd.reason = "auto-approved"
                elif strategy == ApprovalGatedEngine.APPROVAL_STRATEGY_REJECT:
                    self._approval_service.reject(
                        req.request_id, comment="auto-rejected by gated engine"
                    )
                    nd.rejected = True
                    nd.reason = "auto-rejected"
                else:
                    nd.reason = "pending human approval"
            else:
                nd.approved = True
                nd.reason = "low-risk auto-approved"

            decision.node_decisions.append(nd)

        if any(nd.rejected for nd in decision.node_decisions):
            decision.any_rejected = True
        if all(nd.approved for nd in decision.node_decisions):
            decision.all_approved = True
        if any(
            nd.requires_approval and nd.approved is None and not nd.rejected
            for nd in decision.node_decisions
        ):
            decision.pending_approval = True

        return decision

    def run(
        self,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None = None,
        strategy: str = APPROVAL_STRATEGY_INTERACTIVE,
    ) -> tuple[GatedPlanDecision, WorkflowRunResult | None]:
        decision = self.evaluate_plan(plan, runtime_context, strategy=strategy)
        if decision.pending_approval:
            logger.info("plan %s pending approval: %s", plan.plan_id, decision.approval_request_ids)
            return decision, None
        if decision.any_rejected:
            logger.info("plan %s rejected: cannot execute", plan.plan_id)
            return decision, None
        if not decision.all_approved:
            logger.warning("plan %s not fully approved; skipping execution", plan.plan_id)
            return decision, None

        run_result = self._engine.run(
            plan=plan,
            runtime_context=runtime_context,
            max_retries=1,
            agentic_loop=False,
        )
        return decision, run_result

    def resume_after_approval(
        self,
        plan: PlanGraph,
        request_id_to_approved: dict[str, bool],
        runtime_context: dict[str, Any] | None = None,
    ) -> WorkflowRunResult:
        all_approved = all(request_id_to_approved.values())
        if not all_approved:
            return WorkflowRunResult(
                plan_id=plan.plan_id,
                success=False,
                message=f"未全部通过审批：{request_id_to_approved}",
            )
        return self._engine.run(
            plan=plan,
            runtime_context=runtime_context,
            max_retries=1,
            agentic_loop=False,
        )


def build_gated_evidence(
    *,
    input_message: str,
    plan: PlanGraph,
    decision: GatedPlanDecision,
    run_result: WorkflowRunResult | None,
    execution_mode: str,
    strategy: str,
) -> dict[str, Any]:
    """构造留证 JSON（与 V0 风格一致，便于 grep/diff）。"""
    nodes = [
        {
            "node_id": n.node_id,
            "tool_id": n.tool_id,
            "action": n.action,
            "risk": n.risk,
            "depends_on": list(n.depends_on or []),
            "params": dict(n.params or {}),
        }
        for n in plan.nodes
    ]
    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_message": input_message,
        "execution_mode": execution_mode,
        "approval_strategy": strategy,
        "plan_id": plan.plan_id,
        "intent": plan.intent,
        "risk_level": plan.risk_level,
        "nodes": nodes,
        "gated_decision": decision.to_dict(),
    }

    if run_result is None:
        if decision.pending_approval:
            payload["success"] = False
            payload["message"] = "plan pending approval; not executed"
        elif decision.any_rejected:
            payload["success"] = False
            payload["message"] = "plan rejected; not executed"
        else:
            payload["success"] = False
            payload["message"] = "not executed"
        return payload

    payload["success"] = bool(run_result.success)
    payload["message"] = str(run_result.message or "")
    payload["node_results_summary"] = [
        {
            "node_id": item.node_id,
            "tool_id": item.tool_id,
            "action": item.action,
            "success": bool(item.success),
            "error": str(item.error or "")[:200],
            "output_summary": _summarize_output(item.output),
        }
        for item in (run_result.node_results or [])
    ]
    return payload


def _summarize_output(output: Any, *, max_len: int = 400) -> Any:
    if not isinstance(output, dict):
        text = str(output)
        return text[:max_len] if len(text) > max_len else text
    summary: dict[str, Any] = {}
    if "success" in output:
        summary["success"] = output.get("success")
    if "message" in output:
        summary["message"] = str(output.get("message") or "")[:200]
    data = output.get("data")
    if isinstance(data, list):
        summary["data_count"] = len(data)
        if data and isinstance(data[0], dict):
            summary["data_sample_keys"] = list(data[0].keys())[:6]
    elif data is not None:
        summary["data_preview"] = str(data)[:max_len]
    for key in ("unit_name", "exists", "created", "matched_count", "id"):
        if key in output:
            summary[key] = output[key]
    return summary or {k: output[k] for k in list(output.keys())[:8]}
