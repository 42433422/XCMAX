"""Workflow facade; all decisions delegate to domain autonomy_guard."""

from __future__ import annotations

from typing import Any

from app.domain.autonomy.autonomy_guard import RiskDecision, evaluate_risk, get_autonomy_guard

from .types import PlanGraph


class HybridRiskGate:
    def evaluate(self, plan: PlanGraph, context: dict[str, object]) -> RiskDecision:
        node_decisions: list[tuple[str, RiskDecision]] = []
        runtime_context: dict[str, Any] = dict(context or {})
        for node in plan.nodes:
            decision = evaluate_risk(
                {
                    "action": f"{node.tool_id}.{node.action}",
                    "tool_id": node.tool_id,
                    "operation": node.action,
                    "risk_level": node.risk,
                    "action_id": f"{plan.plan_id}:{node.node_id}",
                },
                runtime_context,
                action_id=f"{plan.plan_id}:{node.node_id}",
                source="workflow",
            )
            node_decisions.append((node.node_id, decision))

        return get_autonomy_guard().aggregate_decisions(
            node_decisions,
            action=f"workflow:{plan.plan_id}",
            action_id=plan.plan_id,
        )


__all__ = ["HybridRiskGate", "RiskDecision"]
