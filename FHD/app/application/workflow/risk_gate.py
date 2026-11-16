"""Workflow facade; all decisions delegate to domain autonomy_guard."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.domain.autonomy.autonomy_guard import RiskDecision, evaluate_risk, get_autonomy_guard
from app.domain.autonomy.risk_types import RiskLevel
from app.infrastructure.policy.external_policy import evaluate_external_policy

from .workflow_types import PlanGraph, database_restore_error


class HybridRiskGate:
    def evaluate(self, plan: PlanGraph, context: dict[str, object]) -> RiskDecision:
        if error := database_restore_error(plan):
            raise ValueError(error)
        node_decisions: list[tuple[str, RiskDecision]] = []
        runtime_context: dict[str, Any] = dict(context or {})
        actions: list[dict[str, Any]] = []
        for node in plan.nodes:
            spec = get_autonomy_guard().get_action_spec(node.tool_id, node.action)
            risk = node.risk if spec is not None or node.tool_id == "clarify" else "blocked"
            decision = evaluate_risk(
                {
                    "action": f"{node.tool_id}.{node.action}",
                    "tool_id": node.tool_id,
                    "operation": node.action,
                    "risk_level": risk,
                    "action_id": f"{plan.plan_id}:{node.node_id}",
                },
                runtime_context,
                action_id=f"{plan.plan_id}:{node.node_id}",
                source="workflow",
            )
            node_decisions.append((node.node_id, decision))
            actions.append(
                {
                    "action": f"{node.tool_id}.{node.action}",
                    "tool_id": node.tool_id,
                    "operation": node.action,
                    "risk_level": risk,
                }
            )

        decided = get_autonomy_guard().aggregate_decisions(
            node_decisions,
            action=f"workflow:{plan.plan_id}",
            action_id=plan.plan_id,
        )
        # 未配置外置策略或 fail-open 降级时保持原有行为
        external = evaluate_external_policy(actions=actions, context=runtime_context)
        if external is None or decided.decision == "blocked":
            return decided
        external_reason = str(external.get("reason") or "").strip()
        if not external.get("allow"):
            return replace(
                decided,
                allowed=False,
                requires_confirmation=False,
                decision="blocked",
                risk_level=RiskLevel.BLOCKED,
                reason=f"外置策略拒绝：{external_reason}"
                if external_reason
                else "外置策略拒绝该计划",
            )
        if external.get("require_approval") and not decided.requires_confirmation:
            # 下游要求需审批的决策必须给出 blocking_nodes，否则会被判为风险拒绝
            node_ids = [node.node_id for node in plan.nodes]
            return replace(
                decided,
                allowed=False,
                requires_confirmation=True,
                decision="require_human",
                blocking_nodes=list(decided.blocking_nodes or []) or node_ids,
                reason=(
                    f"外置策略要求人工审批：{external_reason}"
                    if external_reason
                    else "外置策略要求人工审批"
                ),
            )
        return decided


__all__ = ["HybridRiskGate", "RiskDecision"]
