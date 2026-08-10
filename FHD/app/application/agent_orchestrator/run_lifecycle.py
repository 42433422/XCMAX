from __future__ import annotations

from typing import Any

from app.application.agent_orchestrator.run_control import (
    clear_run_control,
    get_run_control,
    request_run_control,
)
from app.application.agent_orchestrator.run_models import AgentRun


class RunLifecycleMixin:
    """Cooperative pause, resume, and cancellation for an agent orchestrator."""

    _repo: Any

    def pause_run(self, run_id: str, *, requested_by: str = "") -> AgentRun | None:
        run = self._repo.get(run_id)
        if run is None:
            return None
        if run.status in {"completed", "failed", "cancelled"}:
            return run
        request_run_control(run_id, "pause")
        run.status = "paused"
        run.metadata["control"] = {"state": "paused", "requested_by": requested_by}
        run.add_event("run.paused", "Agent run 已暂停", {"requested_by": requested_by})
        return self._repo.save(run)

    def cancel_run(self, run_id: str, *, requested_by: str = "") -> AgentRun | None:
        run = self._repo.get(run_id)
        if run is None:
            return None
        if run.status in {"completed", "failed", "cancelled"}:
            return run
        request_run_control(run_id, "cancel")
        self._mark_controlled(run, "cancel", requested_by=requested_by)
        return self._repo.save(run)

    def resume_run(
        self,
        run_id: str,
        *,
        requested_by: str = "",
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentRun | None:
        run = self._repo.get(run_id)
        if run is None:
            return None
        if run.status != "paused":
            return run
        clear_run_control(run_id)
        context = dict(run.metadata.get("runtime_context") or {})
        context.update(dict(runtime_context or {}))
        run.metadata["runtime_context"] = context
        run.metadata["control"] = {"state": "running", "requested_by": requested_by}
        run.status = "running"
        run.add_event("run.resumed", "Agent run 已恢复", {"requested_by": requested_by})
        self._repo.save(run)
        self._execute_ready_steps(run, runtime_context=context)
        return self._repo.save(run)

    def retry_run(
        self,
        run_id: str,
        *,
        requested_by: str = "",
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentRun | None:
        previous = self._repo.get(run_id)
        if previous is None:
            return None
        for event in reversed(previous.events):
            if event.event_type != "run.retry_created":
                continue
            existing_retry_id = str(event.data.get("retry_run_id") or "").strip()
            existing_retry = self._repo.get(existing_retry_id) if existing_retry_id else None
            if existing_retry is not None:
                return existing_retry
        if previous.status not in {"failed", "cancelled", "blocked"}:
            return previous

        previous_task = previous.metadata.get("task_context")
        task = dict(previous_task) if isinstance(previous_task, dict) else {}
        context = dict(previous.metadata.get("runtime_context") or {})
        context.update(dict(runtime_context or {}))
        context.update(
            {
                "task_id": task.get("task_id") or context.get("task_id"),
                "conversation_id": task.get("conversation_id") or context.get("conversation_id"),
                "parent_run_id": previous.run_id,
                "root_run_id": task.get("root_run_id") or previous.run_id,
                "task_attempt": int(task.get("attempt") or 1) + 1,
                "task_title": task.get("title") or previous.message,
                "workspace_id": task.get("workspace_id") or context.get("workspace_id"),
                "workspace_path": task.get("workspace_path") or context.get("workspace_path"),
                "workspace_isolation": task.get("isolation") or context.get("workspace_isolation"),
            }
        )
        retried = self.start_run(
            user_id=previous.user_id,
            message=previous.message,
            runtime_context=context,
            auto_execute=True,
        )
        retried.add_event(
            "run.retried",
            "任务已重新执行",
            {"parent_run_id": previous.run_id, "requested_by": requested_by},
        )
        previous.add_event(
            "run.retry_created",
            "已创建新的重试任务",
            {"retry_run_id": retried.run_id, "requested_by": requested_by},
        )
        self._repo.save(previous)
        return self._repo.save(retried)

    def _apply_requested_control(self, run: AgentRun) -> bool:
        control = get_run_control(run.run_id)
        if control is None:
            return False
        self._mark_controlled(run, control)
        self._repo.save(run)
        return True

    @staticmethod
    def _mark_controlled(
        run: AgentRun,
        control: str,
        *,
        requested_by: str = "",
    ) -> None:
        if control == "cancel":
            for step in run.steps:
                if step.status in {"pending", "retrying", "waiting_user"}:
                    step.status = "skipped"
                    step.error = "run cancelled before execution"
            run.status = "cancelled"
            run.error = "run cancelled"
            run.metadata["control"] = {"state": "cancelled", "requested_by": requested_by}
            run.final_output = {
                **dict(run.final_output or {}),
                "cancelled": True,
                "completed_step_ids": [
                    step.step_id for step in run.steps if step.status == "completed"
                ],
            }
            if not any(event.event_type == "run.cancelled" for event in run.events):
                run.add_event("run.cancelled", "Agent run 已取消", {"requested_by": requested_by})
            return
        run.status = "paused"
        run.metadata["control"] = {"state": "paused", "requested_by": requested_by}
        if not any(event.event_type == "run.paused" for event in run.events):
            run.add_event("run.paused", "Agent run 已暂停", {"requested_by": requested_by})
