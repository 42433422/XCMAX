"""本地员工执行 observed AgentRun（trace 包装，不双跑业务）。"""

from __future__ import annotations

from typing import Any

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_repository import get_agent_run_repository


def begin_observed_employee_run(
    *,
    user_id: str,
    employee_id: str,
    task: str,
    runtime_context: dict[str, Any] | None = None,
) -> str:
    ctx = dict(runtime_context or {})
    ctx.update({"employee_id": employee_id, "task": task, "observed": True})
    run = AgentRun(user_id=str(user_id or "admin"), message=str(task or ""))
    run.metadata["runtime_context"] = ctx
    run.metadata["observed_employee_id"] = str(employee_id or "").strip()
    run.status = "running"
    run.add_event("run.observed_started", "员工本地执行 observed run", {"employee_id": employee_id})
    saved = get_agent_run_repository().save(run)
    return saved.run_id


def finish_observed_employee_run(
    run_id: str,
    *,
    success: bool,
    output: dict[str, Any] | None = None,
    error: str = "",
) -> AgentRun | None:
    orch = AgentOrchestrator()
    run = orch.get_run(run_id)
    if run is None:
        return None
    run.status = "completed" if success else "failed"
    run.error = "" if success else (error or "employee run failed")
    run.final_output = dict(output or {})
    run.add_event(
        "run.observed_finished",
        "员工本地执行 observed run 结束",
        {"success": success, "error": run.error},
    )
    return get_agent_run_repository().save(run)


__all__ = ["begin_observed_employee_run", "finish_observed_employee_run"]
