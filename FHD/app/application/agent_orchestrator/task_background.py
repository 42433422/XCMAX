"""Stage approved tasks for background dispatch and recover expired executions."""

from __future__ import annotations

from typing import Any

from app.application.agent_orchestrator.artifact_attachment import ArtifactAttachmentMixin
from app.application.agent_orchestrator.budget import apply_ai_budget_metadata
from app.application.agent_orchestrator.run_lifecycle import RunLifecycleMixin
from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso
from app.application.agent_orchestrator.task_plan import UnifiedTaskPlanMixin

_WORKER_EXECUTION_FAILED = "worker_execution_failed"
_WORKER_LEASE_EXPIRED = "worker_lease_expired"
_NON_IDEMPOTENT_RECOVERY_BLOCKED = "non_idempotent_recovery_blocked"


def task_execution_context(run: AgentRun, step: Any) -> dict[str, Any]:
    task_context = run.metadata.get("task_context")
    task_context = task_context if isinstance(task_context, dict) else {}
    return {
        "task_id": str(task_context.get("task_id") or ""),
        "task_attempt": int(task_context.get("attempt") or 1),
        "idempotency_key": f"agent:{run.run_id}:{step.step_id}",
    }


class BackgroundTaskExecutionMixin:
    _repo: Any

    def stage_run_for_dispatch(
        self,
        run_id: str,
        *,
        requested_by: str = "",
    ) -> AgentRun | None:
        run = self._repo.get(run_id)
        if run is None or run.status not in {"planning", "running", "queued", "retrying"}:
            return run
        run.status = "queued"
        run.error = ""
        run.metadata["dispatch"] = {
            "state": "queued",
            "approved_step_id": "",
            "requested_by": str(requested_by or ""),
            "queued_at": utc_now_iso(),
        }
        run.add_event(
            "task.queued",
            "任务已进入后台执行队列",
            {"requested_by": str(requested_by or "")},
        )
        return self._repo.save(run)

    def stage_approved_run(
        self,
        run_id: str,
        *,
        approved_by: str,
        approved_step_id: str,
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentRun | None:
        run = self._repo.get(run_id)
        if run is None:
            return None
        step = self._find_waiting_step(run, approved_step_id=approved_step_id)
        if step is None:
            return self._repo.save(run)
        context = dict(run.metadata.get("runtime_context") or {})
        context.update(dict(runtime_context or {}))
        run.metadata["runtime_context"] = context
        apply_ai_budget_metadata(run, context)
        step.status = "pending"
        run.status = "queued"
        run.error = ""
        run.metadata["dispatch"] = {
            "state": "queued",
            "approved_step_id": step.step_id,
            "approved_by": str(approved_by or ""),
            "queued_at": utc_now_iso(),
        }
        run.add_event(
            "step.approved",
            f"步骤 {step.node_id} 已确认继续",
            {
                "step_id": step.step_id,
                "node_id": step.node_id,
                "tool_id": step.tool_id,
                "action": step.action,
                "approved_by": str(approved_by or ""),
            },
        )
        run.add_event(
            "task.queued",
            "任务已进入后台执行队列",
            {
                "step_id": step.step_id,
                "node_id": step.node_id,
                "approved_by": str(approved_by or ""),
            },
        )
        return self._repo.save(run)

    def stage_resume_run(
        self,
        run_id: str,
        *,
        requested_by: str = "",
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentRun | None:
        run = self._repo.get(run_id)
        if run is None or run.status != "paused":
            return run
        control = run.metadata.get("control")
        resume_status = str(control.get("resume_status") or "") if isinstance(control, dict) else ""
        command = self._repo.request_task_control(run_id, "resume", requested_by=requested_by)
        context = dict(run.metadata.get("runtime_context") or {})
        context.update(dict(runtime_context or {}))
        run.metadata["runtime_context"] = context
        run.metadata["control"] = {
            "state": "queued",
            "requested_by": requested_by,
            "command_id": command.command_id,
        }
        run.status = "waiting_user" if resume_status == "waiting_user" else "queued"
        if run.status == "queued":
            run.metadata["dispatch"] = {
                "state": "queued",
                "approved_step_id": "",
                "requested_by": requested_by,
                "queued_at": utc_now_iso(),
            }
        run.add_event(
            "run.resumed",
            "Agent run 已恢复并等待后台执行",
            {"requested_by": requested_by, "command_id": command.command_id},
        )
        stored = self._repo.save(run)
        self._repo.mark_task_control(command.command_id, "applied", applied_at=utc_now_iso())
        return stored

    def execute_dispatched_run(
        self,
        run_id: str,
        *,
        recovered: bool = False,
    ) -> AgentRun | None:
        run = self._repo.get(run_id)
        if run is None:
            return None
        if run.status not in {"queued", "running", "retrying"}:
            return run
        if recovered and not self._prepare_expired_execution_recovery(run):
            return self._repo.save(run)
        if self._apply_requested_control(run):
            return self._repo.get(run_id)
        dispatch = run.metadata.get("dispatch")
        dispatch = dict(dispatch) if isinstance(dispatch, dict) else {}
        approved_step_id = str(dispatch.get("approved_step_id") or "")
        dispatch.update({"state": "running", "started_at": utc_now_iso()})
        run.metadata["dispatch"] = dispatch
        run.status = "running"
        run.add_event(
            "task.dispatched",
            "后台工作线程开始执行任务",
            {"recovered": bool(recovered)},
        )
        self._repo.save(run)
        self._execute_with_durable_lease(
            run,
            runtime_context=dict(run.metadata.get("runtime_context") or {}),
            approved_step_id=approved_step_id,
        )
        dispatch = dict(run.metadata.get("dispatch") or {})
        dispatch.update({"state": str(run.status), "finished_at": utc_now_iso()})
        run.metadata["dispatch"] = dispatch
        return self._repo.save(run)

    def fail_dispatched_run(self, run_id: str) -> AgentRun | None:
        run = self._repo.get(run_id)
        if run is None or run.status in {"completed", "failed", "cancelled"}:
            return run
        run.status = "failed"
        run.error = _WORKER_EXECUTION_FAILED
        run.add_event(
            "task.worker_failed",
            "后台执行失败",
            {"error_code": _WORKER_EXECUTION_FAILED},
        )
        return self._repo.save(run)

    def _prepare_expired_execution_recovery(self, run: AgentRun) -> bool:
        running_steps = [step for step in run.steps if step.status == "running"]
        if not running_steps:
            run.add_event("task.worker_recovered", "任务执行租约已恢复", {})
            return True
        if any(not step.idempotent for step in running_steps):
            run.status = "blocked"
            run.error = _NON_IDEMPOTENT_RECOVERY_BLOCKED
            run.metadata["non_retryable"] = True
            run.metadata["recovery"] = {
                "state": "manual_reconciliation_required",
                "error_code": _NON_IDEMPOTENT_RECOVERY_BLOCKED,
                "step_ids": [step.step_id for step in running_steps],
            }
            run.add_event(
                "task.recovery_blocked",
                "非幂等步骤结果未知，已阻止自动重放",
                {
                    "error_code": _NON_IDEMPOTENT_RECOVERY_BLOCKED,
                    "step_ids": [step.step_id for step in running_steps],
                },
            )
            return False
        for step in running_steps:
            step.status = "pending"
            step.error = ""
            for call in run.tool_calls:
                if call.step_id != step.step_id or call.status != "running":
                    continue
                call.status = "failed"
                call.error = _WORKER_LEASE_EXPIRED
                call.finished_at = utc_now_iso()
                call.output = {"success": False, "error_code": _WORKER_LEASE_EXPIRED}
        run.status = "queued"
        run.error = ""
        run.add_event(
            "task.worker_recovered",
            "幂等任务从过期执行租约恢复",
            {
                "error_code": _WORKER_LEASE_EXPIRED,
                "step_ids": [step.step_id for step in running_steps],
            },
        )
        return True


class AgentOrchestratorTaskMixin(
    BackgroundTaskExecutionMixin,
    UnifiedTaskPlanMixin,
    RunLifecycleMixin,
    ArtifactAttachmentMixin,
):
    """Composed task lifecycle kept outside the legacy oversized orchestrator."""


__all__ = ["AgentOrchestratorTaskMixin", "task_execution_context"]
