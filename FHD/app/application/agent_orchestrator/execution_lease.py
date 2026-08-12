"""Durable execution ownership around cooperative AgentRun checkpoints."""

from __future__ import annotations

from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso


class DurableExecutionLeaseMixin:
    _repo: Any

    def _execute_ready_steps(
        self,
        run: AgentRun,
        *,
        runtime_context: dict[str, Any],
        approved_step_id: str = "",
    ) -> None: ...

    def _apply_requested_control(self, run: AgentRun) -> bool: ...

    def _execute_with_durable_lease(
        self,
        run: AgentRun,
        *,
        runtime_context: dict[str, Any],
        approved_step_id: str = "",
    ) -> None:
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
            self._execute_ready_steps(
                run,
                runtime_context=runtime_context,
                approved_step_id=approved_step_id,
            )
        finally:
            try:
                self._apply_requested_control(run)
            finally:
                now = utc_now_iso()
                execution = dict(run.metadata.get("execution") or {})
                execution.update(
                    {
                        "state": "idle",
                        "updated_at": now,
                        "finished_at": now,
                    }
                )
                run.metadata["execution"] = execution
                self._repo.save(run)


__all__ = ["DurableExecutionLeaseMixin"]
