"""Canonical task reads use live account grants and existing durable receipts."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec, validate_tool_call
from app.domain.task_lifecycle.results import execution_result_error
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def task_runtime(trusted_actor, monkeypatch):
    owner = trusted_actor(user_id=101, tenant_id=7, mod_id="tasks-mod-a")
    other = trusted_actor(user_id=102, tenant_id=7, mod_id="tasks-mod-a")
    other_mod = trusted_actor(user_id=101, tenant_id=7, mod_id="tasks-mod-b")
    repository = SQLAlchemyAgentRunRepository(session_factory=owner.factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=owner.factory)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_repository._agent_run_repository", repository
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.task_execution_repository._task_execution_repository",
        queue,
    )

    def save(task_id, actor, *, status="blocked", tenant=None):
        context = copy.deepcopy(actor.context)
        if tenant is not None:
            context["tenant_id"] = tenant
        run = AgentRun(
            user_id=str(actor.user_id),
            message="Visible task title",
            status=status,
            steps=[
                AgentStep(
                    node_id="original-step",
                    tool_id="customers",
                    action="create",
                    params={"unit_name": "raw-business-arguments"},
                )
            ],
            metadata={
                "runtime_context": context,
                "task_context": {"task_id": task_id, "root_run_id": "root-original"},
                "credential": "private-credential",
            },
        )
        repository.save(run)
        return run

    original = save("original-task", owner)
    queue.enqueue(original)
    assert queue.claim("worker", lease_seconds=30) is not None
    queue.mark_open_effect(original.run_id, original.steps[0].step_id)
    assert queue.finish(original.run_id, "worker", "failed").state == "unknown"
    foreign = save("foreign-owner", other)
    tenant = save("foreign-tenant", owner, tenant="8")
    mod = save("foreign-mod", other_mod)
    return SimpleNamespace(
        owner=owner,
        other=other,
        other_mod=other_mod,
        repository=repository,
        queue=queue,
        original=original,
        foreign=foreign,
        tenant=tenant,
        mod=mod,
    )


def execute(context, **params):
    return AgentToolExecutor().execute(
        AgentStep(node_id="query-tasks", tool_id="tasks", action="query", params=params),
        runtime_context=context,
    )


def test_task_read_projects_original_sql_ids_and_unknown_state_without_secrets(task_runtime):
    runtime = task_runtime
    before_run = runtime.repository.get(runtime.original.run_id).to_dict()
    before_queue = runtime.queue.get(runtime.original.run_id).to_dict()
    result = execute(runtime.owner.context)
    assert result["success"], result
    assert result["count"] == 1
    row = result["data"][0]
    assert row["task_id"] == "original-task"
    assert row["run_id"] == runtime.original.run_id
    assert row["root_run_id"] == "root-original"
    assert row["status"] == "blocked"
    assert row["execution"]["state"] == "unknown"
    assert row["execution"]["execution_count"] == 1
    assert row["result_verification"] == {"status": "not_verified", "accepted": False}
    assert execution_result_error(result) == ""
    serialized = json.dumps(result)
    for secret in (
        "_actor_authorization",
        "_mod_authorization",
        "_credential_authorization",
        "raw-business-arguments",
        "private-credential",
        runtime.owner.context["_actor_authorization"]["proof"],
        runtime.foreign.run_id,
        runtime.tenant.run_id,
        runtime.mod.run_id,
    ):
        assert secret not in serialized
    assert runtime.repository.get(runtime.original.run_id).to_dict() == before_run
    assert runtime.queue.get(runtime.original.run_id).to_dict() == before_queue


@pytest.mark.parametrize("task_id", ["foreign-owner", "foreign-tenant", "foreign-mod", "absent"])
def test_task_id_lookup_cannot_cross_owner_tenant_or_mod(task_runtime, task_id):
    result = execute(task_runtime.owner.context, task_id=task_id)
    assert result["success"] is False and result["error_code"] == "task_not_found"
    assert result["data"] == []


@pytest.mark.parametrize("change", ["owner", "tenant", "mod", "missing_binding", "revoke"])
def test_task_read_revalidates_live_identity(task_runtime, change):
    from app.db.models.user import Session

    context = copy.deepcopy(task_runtime.owner.context)
    if change == "owner":
        context["user_id"] = "102"
    elif change == "tenant":
        context["tenant_id"] = "8"
    elif change == "mod":
        context["mod_id"] = "tasks-mod-b"
    elif change == "missing_binding":
        context.pop("_actor_authorization")
    else:
        with task_runtime.owner.factory.begin() as db:
            db.delete(db.get(Session, task_runtime.owner.session_row_id))
    result = execute(context)
    assert result["success"] is False
    assert "original-task" not in json.dumps(result)


@pytest.mark.parametrize("field", ["user_id", "tenant_id", "mod_id", "_actor_authorization"])
def test_task_read_contract_rejects_model_identity_overrides(task_runtime, field):
    arguments = {"task_id": "foreign-owner", field: "forged"}
    assert not validate_tool_call("tasks", "query", arguments).ok
    # A transport may discard identity claims before validation. It must still
    # select the original authenticated owner and never the requested foreign row.
    result = execute(task_runtime.owner.context, **arguments)
    assert result["success"] is False
    assert "original-task" not in json.dumps(result)


def test_task_capability_is_read_only_and_available_in_current_account_catalog(task_runtime):
    from app.application.capability_catalog import discover_capabilities

    spec = get_tool_action_spec("tasks", "query")
    assert spec is not None and spec.read_only and spec.idempotent and spec.risk == "low"
    assert spec.input_schema["additionalProperties"] is False
    result = discover_capabilities(task_runtime.owner.context, query="tasks.query")
    assert result["success"] is True
    assert [row["capability_id"] for row in result["capabilities"]] == ["tasks.query"]
