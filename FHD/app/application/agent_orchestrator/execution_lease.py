"""Durable execution ownership around cooperative AgentRun checkpoints."""

from __future__ import annotations

from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso
from app.application.agent_orchestrator.task_context import observe_run_phase


class DurableExecutionLeaseMixin:
    _repo: Any

    def _execute_ready_steps(
        self,
        run: AgentRun,
        *,
        runtime_context: dict[str, Any],
        approved_step_id: str = "",
    ) -> None: ...

    def _apply_requested_control(self, run: AgentRun) -> bool:
        raise NotImplementedError

    def _execute_with_durable_lease(
        self,
        run: AgentRun,
        *,
        runtime_context: dict[str, Any],
        approved_step_id: str = "",
    ) -> None:
        if run.status in {"blocked", "completed", "failed", "cancelled", "rejected"}:
            return
        execution = dict(run.metadata.get("execution") or {})
        execution.update(
            {
                "state": "active",
                "started_at": execution.get("started_at") or utc_now_iso(),
                "updated_at": utc_now_iso(),
            }
        )
        run.metadata["execution"] = execution
        self._repo.save(run)
        try:
            from app.application.agent_orchestrator.browser_loop import (
                browser_round_expired,
                browser_round_ready,
            )

            with observe_run_phase(run, "execution"):
                while True:
                    if browser_round_expired(run):
                        break
                    self._execute_ready_steps(
                        run,
                        runtime_context=runtime_context,
                        approved_step_id=approved_step_id,
                    )
                    if not browser_round_ready(run) or self._apply_requested_control(run):
                        break
                    # An approval is bound to its original step, never the next page action.
                    approved_step_id = ""
        finally:
            try:
                self._apply_requested_control(run)
            finally:
                now = utc_now_iso()
                execution = dict(run.metadata.get("execution") or {})
                execution.update(state="idle", updated_at=now, finished_at=now)
                run.metadata["execution"] = execution
                self._repo.save(run)
                self._release_browser_run_resources(run, runtime_context=runtime_context)

    @staticmethod
    def _release_browser_run_resources(
        run: AgentRun, *, runtime_context: dict[str, Any] | None = None
    ) -> None:
        if not run.metadata.get("browser_loop") or run.status not in {
            "completed",
            "failed",
            "cancelled",
            "blocked",
            "rejected",
        }:
            return
        from app.application.tools.mcp.registry import release_run_browser_sessions

        scope = {
            **(runtime_context or run.metadata.get("runtime_context") or {}),
            "run_id": run.run_id,
        }
        # Match StepExecution: the signed-in actor can differ from the conversation owner.
        if not isinstance(scope.get("_actor_authorization"), dict):
            scope["user_id"] = run.user_id
        release_run_browser_sessions(scope)


__all__ = ["DurableExecutionLeaseMixin"]
