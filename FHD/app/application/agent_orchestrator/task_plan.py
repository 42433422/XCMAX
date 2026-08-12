"""Plan snapshot and approval staging for server-backed tasks."""

from __future__ import annotations

import copy
from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.workflow.types import Branch, PlanGraph, WorkflowNode


class UnifiedTaskPlanMixin:
    def get_run(self, run_id: str) -> AgentRun | None:
        return self._repo.get(run_id)

    def list_task_runs(self, *, user_id: str, task_id: str) -> list[AgentRun]:
        return self._repo.list_task_runs(user_id=user_id, task_id=task_id)

    def save_run(self, run: AgentRun) -> AgentRun:
        return self._repo.save(run)

    def start_task_from_plan(
        self,
        *,
        user_id: str,
        message: str,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentRun:
        """Create a durable task at a real approval checkpoint."""
        run = self.start_run_from_plan(
            user_id=user_id,
            message=message,
            plan=plan,
            runtime_context=runtime_context,
            auto_execute=False,
        )
        if run.status != "running":
            return run
        step = next((item for item in run.steps if item.status == "pending"), None)
        if step is None:
            return run
        step.status = "waiting_user"
        run.status = "waiting_user"
        run.metadata["task_model"] = {
            "version": 1,
            "execution": "agent_run",
            "approval": "required_before_first_tool",
            "evidence": "steps_tool_calls_events_artifacts",
        }
        run.metadata["provided_plan"] = self._plan_snapshot(plan)
        run.add_event(
            "task.approval_required",
            f"任务 {step.node_id} 等待审批",
            {
                "step_id": step.step_id,
                "node_id": step.node_id,
                "tool_id": step.tool_id,
                "action": step.action,
            },
        )
        return self._repo.save(run)

    @staticmethod
    def _plan_snapshot(plan: PlanGraph) -> dict[str, Any]:
        return {
            "plan_id": plan.plan_id,
            "intent": plan.intent,
            "todo_steps": list(plan.todo_steps or []),
            "risk_level": plan.risk_level,
            "metadata": copy.deepcopy(plan.metadata or {}),
            "nodes": [
                {
                    "node_id": node.node_id,
                    "tool_id": node.tool_id,
                    "action": node.action,
                    "params": copy.deepcopy(node.params or {}),
                    "risk": node.risk,
                    "idempotent": node.idempotent,
                    "description": node.description,
                    "depends_on": list(node.depends_on or []),
                    "next": node.next,
                    "branches": [
                        {"target": branch.target, "condition": copy.deepcopy(branch.condition)}
                        for branch in node.branches
                    ],
                }
                for node in plan.nodes
            ],
        }

    @staticmethod
    def plan_from_snapshot(snapshot: dict[str, Any]) -> PlanGraph:
        nodes = []
        for row in snapshot.get("nodes") or []:
            if not isinstance(row, dict):
                continue
            nodes.append(
                WorkflowNode(
                    node_id=str(row.get("node_id") or ""),
                    tool_id=str(row.get("tool_id") or ""),
                    action=str(row.get("action") or ""),
                    params=copy.deepcopy(row.get("params") or {}),
                    risk=str(row.get("risk") or "medium"),
                    idempotent=bool(row.get("idempotent", False)),
                    description=str(row.get("description") or ""),
                    depends_on=[str(item) for item in (row.get("depends_on") or [])],
                    next=str(row.get("next") or "") or None,
                    branches=[
                        Branch(
                            target=str(branch.get("target") or ""),
                            condition=copy.deepcopy(branch.get("condition") or {}),
                        )
                        for branch in (row.get("branches") or [])
                        if isinstance(branch, dict)
                    ],
                )
            )
        return PlanGraph(
            plan_id=str(snapshot.get("plan_id") or ""),
            intent=str(snapshot.get("intent") or ""),
            todo_steps=[str(item) for item in (snapshot.get("todo_steps") or [])],
            nodes=nodes,
            risk_level=str(snapshot.get("risk_level") or "medium"),
            metadata=copy.deepcopy(snapshot.get("metadata") or {}),
        )


__all__ = ["UnifiedTaskPlanMixin"]
