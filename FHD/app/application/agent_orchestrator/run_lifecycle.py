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
