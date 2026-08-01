from __future__ import annotations

import time
from typing import Any

from app.application.agent_orchestrator.budget import apply_ai_budget_metadata
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, RunEvent, utc_now_iso
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.application.workflow.types import PlanGraph, WorkflowNode


class AgentRunLifecycleMixin:
    def _apply_plan(self, run: AgentRun, plan: PlanGraph) -> None:
        run.plan_id = plan.plan_id
        run.intent = plan.intent
        run.metadata["plan"] = {
            "todo_steps": list(plan.todo_steps or []),
            "risk_level": plan.risk_level,
            "metadata": dict(plan.metadata or {}),
        }
        run.steps = [self._step_from_node(node) for node in plan.nodes]
        self._apply_repair_policy(run, dict(plan.metadata or {}))
        self._attach_artifacts_from_payload(
            run,
            getattr(plan, "metadata", {}) or {},
            source="plan.metadata",
        )
        self._refresh_artifact_metadata(run)
        run.status = "running" if run.steps else "blocked"
        if not run.steps:
            run.error = "planner returned no executable steps"
            run.add_event("planner.blocked", "计划没有可执行节点")

    @staticmethod
    def _step_from_node(node: WorkflowNode) -> AgentStep:
        spec = get_tool_action_spec(node.tool_id, node.action)
        return AgentStep(
            node_id=node.node_id,
            tool_id=node.tool_id,
            action=spec.action if spec is not None else node.action,
            params=dict(node.params or {}),
            risk=spec.risk if spec is not None else str(node.risk or "low"),
            idempotent=bool(spec.idempotent) if spec is not None else bool(node.idempotent),
            description=str(node.description or ""),
            depends_on=list(node.depends_on or []),
        )

    @staticmethod
    def _find_waiting_step(
        run: AgentRun,
        *,
        approved_step_id: str = "",
    ) -> AgentStep | None:
        wanted = str(approved_step_id or "").strip()
        for step in run.steps:
            if step.status != "waiting_user":
                continue
            if wanted and wanted not in {step.step_id, step.node_id}:
                continue
            return step
        return None

    def approve_run_step(
        self,
        run_id: str,
        *,
        approved_by: str = "",
        approved_step_id: str = "",
        approval_request_id: str = "",
    ) -> AgentRun | None:
        """Resume one formal-approval step after Approval Workspace approval."""

        run = self._repo.get(run_id)
        if run is None:
            return None
        waiting_step = self._find_waiting_step(run, approved_step_id=approved_step_id)
        if waiting_step is None:
            return self._repo.save(run)
        formal_nodes = {
            str(node_id or "").strip()
            for node_id in (run.metadata.get("formal_approval_node_ids") or [])
        }
        if waiting_step.node_id not in formal_nodes:
            return self._repo.save(run)
        run.metadata.setdefault("approved_request_ids", []).append(
            str(approval_request_id or "").strip()
        )
        return self._continue_waiting_step(
            run,
            waiting_step=waiting_step,
            approved_by=approved_by,
            runtime_context={
                "formal_approval": True,
                "approval_request_id": str(approval_request_id or "").strip(),
            },
        )

    def _continue_waiting_step(
        self,
        run: AgentRun,
        *,
        waiting_step: AgentStep,
        approved_by: str,
        runtime_context: dict[str, Any] | None,
    ) -> AgentRun:
        context = dict(run.metadata.get("runtime_context") or {})
        context.update(dict(runtime_context or {}))
        run.metadata["runtime_context"] = context
        apply_ai_budget_metadata(run, context)
        waiting_step.status = "pending"
        run.status = "running"
        run.error = ""
        run.add_event(
            "step.approved",
            f"步骤 {waiting_step.node_id} 已确认继续",
            {
                "step_id": waiting_step.step_id,
                "node_id": waiting_step.node_id,
                "tool_id": waiting_step.tool_id,
                "action": waiting_step.action,
                "approved_by": approved_by,
            },
        )
        self._execute_ready_steps(
            run,
            runtime_context=context,
            approved_step_id=waiting_step.step_id,
        )
        return self._repo.save(run)

    def submit_run_for_approval(
        self,
        run_id: str,
        *,
        requested_by: str = "",
    ) -> tuple[AgentRun | None, list[str]]:
        """Create idempotent Approval Workspace requests linked to a durable run."""

        run = self._repo.get(run_id)
        if run is None:
            return None, []
        formal_nodes = {
            str(node_id or "").strip()
            for node_id in (run.metadata.get("formal_approval_node_ids") or [])
        }
        existing = {
            str(node_id): str(request_id)
            for node_id, request_id in dict(
                run.metadata.get("approval_request_by_node") or {}
            ).items()
            if str(node_id).strip() and str(request_id).strip()
        }
        if not formal_nodes:
            return self._repo.save(run), list(existing.values())

        from app.application.workflow import get_approval_service

        approval_service = get_approval_service()
        runtime_context = dict(run.metadata.get("runtime_context") or {})
        for step in run.steps:
            if step.node_id not in formal_nodes or step.node_id in existing:
                continue
            node = WorkflowNode(
                node_id=step.node_id,
                tool_id=step.tool_id,
                action=step.action,
                params=dict(step.params or {}),
                risk="high",
                idempotent=step.idempotent,
                description=step.description,
                depends_on=list(step.depends_on or []),
            )
            request = approval_service.create_approval_request(
                plan_id=run.plan_id,
                node=node,
                runtime_context={
                    **runtime_context,
                    "agent_run_id": run.run_id,
                    "agent_step_id": step.step_id,
                    "agent_node_id": step.node_id,
                    "requested_by": str(requested_by or ""),
                },
            )
            if bool(getattr(request, "persistence_confirmed", True)):
                existing[step.node_id] = request.request_id

        request_ids = list(existing.values())
        run.metadata["approval_request_by_node"] = existing
        run.metadata["approval_request_ids"] = request_ids
        run.add_event(
            "step.waiting_user",
            "正式审批请求已提交，等待审批中心处理",
            {
                "approval_required": True,
                "approval_request_ids": request_ids,
                "requested_by": str(requested_by or ""),
            },
        )
        return self._repo.save(run), request_ids

    def cancel_run(self, run_id: str, *, cancelled_by: str = "") -> AgentRun | None:
        """Cancel a durable run that has not reached a terminal state."""

        run = self._repo.get(run_id)
        if run is None:
            return None
        if run.status in {"completed", "failed", "cancelled"}:
            run.add_event(
                "run.cancel_ignored",
                "任务已经结束，无法取消",
                {"status": run.status, "cancelled_by": str(cancelled_by or "")},
            )
            return self._repo.save(run)

        for step in run.steps:
            if step.status in {"pending", "running", "retrying", "waiting_user"}:
                step.status = "skipped"
                step.error = "cancelled by user"
        run.status = "cancelled"
        run.error = ""
        run.metadata["cancelled_by"] = str(cancelled_by or "")
        run.final_output = {
            "cancelled": True,
            "cancelled_by": str(cancelled_by or ""),
            "tool_calls": [call.to_dict() for call in run.tool_calls],
            "artifacts": [artifact.to_dict() for artifact in run.artifacts],
        }
        run.add_event("run.cancelled", "任务已取消，未再执行后续步骤", run.final_output)
        return self._repo.save(run)

    def list_runs(self, *, user_id: str | None = None, limit: int = 50) -> list[AgentRun]:
        return self._repo.list_recent(user_id=user_id, limit=limit)

    def reconcile_interrupted_runs(self, *, limit: int = 500) -> int:
        """Fail process-owned runs left executing by a previous app process.

        Waiting-user runs are intentionally durable and remain resumable.  Runs
        in an executing state cannot be trusted after process restart because a
        non-idempotent tool may have applied a side effect before its receipt was
        persisted; they therefore become an explicit, auditable failure instead
        of a forever-running zombie.
        """

        reconciled = 0
        for run in self._repo.list_recent(limit=limit):
            if run.status not in {"queued", "planning", "running", "retrying"}:
                continue
            interrupted_step_ids: list[str] = []
            manual_review_required = False
            for step in run.steps:
                if step.status in {"running", "retrying"}:
                    interrupted_step_ids.append(step.step_id)
                    step.status = "failed"
                    step.error = "app process restarted before a verified tool receipt"
                    if not step.idempotent:
                        manual_review_required = True
                elif step.status == "pending":
                    step.status = "skipped"
                    step.error = "not executed because the previous app process stopped"
            for call in run.tool_calls:
                if call.status == "running":
                    call.status = "failed"
                    call.error = "app process restarted before a verified tool receipt"
                    call.finished_at = utc_now_iso()
                    linked_step = next(
                        (step for step in run.steps if step.step_id == call.step_id),
                        None,
                    )
                    if linked_step is None or not linked_step.idempotent:
                        manual_review_required = True

            verified_calls = [
                call.to_dict() for call in run.tool_calls if call.status == "completed"
            ]
            if verified_calls:
                manual_review_required = True
            run.status = "failed"
            run.error = "app restarted while the task was executing"
            run.final_output = {
                "success": False,
                "executed": bool(verified_calls),
                "error_code": "agent_run_interrupted",
                "error": run.error,
                "interrupted_step_ids": interrupted_step_ids,
                "verified_tool_calls": verified_calls,
                "manual_review_required": manual_review_required,
                "retry_automatically": False,
            }
            run.add_event(
                "run.failed",
                "应用重启中断了任务；未取得回执的业务步骤不会自动重试",
                dict(run.final_output),
            )
            self._repo.save(run)
            reconciled += 1
        return reconciled

    def restart_run(
        self,
        run_id: str,
        *,
        requested_by: str = "",
    ) -> tuple[AgentRun | None, AgentRun | None, str]:
        """Create a new durable run when replay is provably safe.

        The old run remains immutable evidence.  Unknown or verified side effects
        block replay so an ERP mutation is never duplicated for UI convenience.
        """

        source = self._repo.get(run_id)
        if source is None:
            return None, None, "not_found"
        if source.status not in {"failed", "cancelled"}:
            return source, None, "run_not_terminal"
        if bool(source.final_output.get("manual_review_required")):
            return source, None, "manual_review_required"
        if any(call.status == "completed" for call in source.tool_calls):
            return source, None, "verified_side_effects_present"

        step_by_id = {step.step_id: step for step in source.steps}
        for call in source.tool_calls:
            linked_step = step_by_id.get(call.step_id)
            if linked_step is None or not linked_step.idempotent:
                return source, None, "unverified_non_idempotent_call"

        old_plan = dict(source.metadata.get("plan") or {})
        plan = PlanGraph(
            plan_id=f"{source.plan_id or source.run_id}_restart_{int(time.time() * 1000)}",
            intent=source.intent or "agent_run_restart",
            todo_steps=list(old_plan.get("todo_steps") or []),
            nodes=[
                WorkflowNode(
                    node_id=step.node_id,
                    tool_id=step.tool_id,
                    action=step.action,
                    params=dict(step.params or {}),
                    risk=step.risk if step.risk in {"low", "medium", "high"} else "medium",
                    idempotent=step.idempotent,
                    description=step.description,
                    depends_on=list(step.depends_on or []),
                )
                for step in source.steps
            ],
            risk_level=(
                old_plan.get("risk_level")
                if old_plan.get("risk_level") in {"low", "medium", "high"}
                else "medium"
            ),
            metadata={
                **dict(old_plan.get("metadata") or {}),
                "restarted_from_run_id": source.run_id,
                "restart_requested_by": str(requested_by or ""),
            },
        )
        restarted = self.start_run_from_plan(
            user_id=source.user_id,
            message=source.message,
            plan=plan,
            runtime_context=dict(source.metadata.get("runtime_context") or {}),
            auto_execute=True,
            approval_required_node_ids=list(source.metadata.get("formal_approval_node_ids") or []),
        )
        restarted.metadata["restarted_from_run_id"] = source.run_id
        restarted.metadata["restart_requested_by"] = str(requested_by or "")
        return source, self._repo.save(restarted), ""

    def list_events(self, run_id: str, *, after_event_id: str | None = None) -> list[RunEvent]:
        return self._repo.list_events(run_id, after_event_id=after_event_id)
