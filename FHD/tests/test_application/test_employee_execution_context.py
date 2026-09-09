"""Async employee bridges retain account and Mod scope across real threads."""

import threading

import pytest

from app.application.agent_orchestrator.execution_identity import (
    current_execution_actor,
    execution_actor_scope,
)
from app.application.employee_runtime.agent_runner import _run_async
from app.application.employee_runtime.executor import _run_maybe_async
from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope
from app.request_active_mod_ctx import (
    get_request_active_mod_id,
    reset_request_active_mod_id,
    set_request_active_mod_id,
)


def test_employee_tool_binds_account_and_tenant_from_durable_task(monkeypatch):
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    monkeypatch.setattr(
        "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
        lambda: {"employee_pack_tools": []},
    )
    observed = []

    def execute(employee_id, task, payload, **kwargs):
        observed.append(
            (kwargs["user_id"], payload["user_id"], current_execution_actor(), current_tenant_id())
        )
        return {"success": True}

    monkeypatch.setattr(
        "app.application.employee_runtime.executor.execute_employee_task_local", execute
    )
    step = AgentStep(
        node_id="employee",
        tool_id="employee",
        action="execute",
        params={"employee_id": "example", "task": "查询库存"},
    )
    with tenant_scope(None):
        result = AgentToolExecutor().execute(
            step, runtime_context={"local_user_id": "17", "tenant_id": "7"}
        )
        assert current_tenant_id() is None
    assert result["success"] is True
    assert observed == [(17, 17, "17", 7)]
    step.params["user_id"] = "18"
    result = AgentToolExecutor().execute(
        step, runtime_context={"local_user_id": "17", "tenant_id": "7"}
    )
    assert result["code"] == "EMPLOYEE_ACCOUNT_MISMATCH"
    assert len(observed) == 1


def test_raw_employee_tool_cannot_inject_a_task_identity(monkeypatch):
    from app.services.tools_workflow_registered import execute_registered_workflow_tool

    monkeypatch.setattr(
        "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
        lambda: {"employee_pack_tools": []},
    )
    result = execute_registered_workflow_tool(
        "employee",
        "execute",
        {
            "employee_id": "example",
            "task": "查询库存",
            "user_id": "18",
            "_runtime_context": {"local_user_id": "18", "user_id": "18", "tenant_id": "7"},
        },
    )
    assert result["code"] == "EMPLOYEE_IDENTITY_REQUIRED"


@pytest.mark.parametrize("flag", ["blocked_by_risk_gate", "blocked_by_product_plane"])
def test_scheduler_does_not_count_a_blocked_employee_as_success(monkeypatch, flag):
    from app.application.employee_runtime.scheduler import EmployeeCronJob
    from app.application.employee_runtime.scheduler_execution import _execute_job_task

    monkeypatch.setattr(
        "app.application.employee_runtime.executor.execute_employee_task_local",
        lambda *args, **kwargs: {"success": True, flag: True, "error": "blocked"},
    )
    job = EmployeeCronJob(
        job_id="job",
        employee_id="example",
        task="task",
        schedule="daily",
        hour=8,
        minute=0,
        timezone="UTC",
        enabled=True,
    )
    ok, result, error = _execute_job_task(
        job,
        task=None,
        input_data=None,
        user_id=17,
        workspace_root=None,
        session_id=None,
        source="cron",
    )
    assert ok is False
    assert result[flag] is True
    assert error == "blocked"


@pytest.mark.asyncio
@pytest.mark.parametrize("bridge", ["agent", "handler"])
async def test_employee_thread_bridge_preserves_identity_and_does_not_leak_changes(bridge):
    parent_thread = threading.get_ident()

    async def employee():
        observed = (current_execution_actor(), current_tenant_id(), get_request_active_mod_id())
        assert threading.get_ident() != parent_thread
        # Worker changes must not alter the parent execution context.
        set_request_active_mod_id("worker-only")
        return observed

    token = set_request_active_mod_id("customer-workspace")
    try:
        with execution_actor_scope("17"), tenant_scope(7):
            result = _run_async(employee()) if bridge == "agent" else _run_maybe_async(employee)
            assert result == ("17", 7, "customer-workspace")
            assert get_request_active_mod_id() == "customer-workspace"
            assert current_execution_actor() == "17"
            assert current_tenant_id() == 7
    finally:
        reset_request_active_mod_id(token)
