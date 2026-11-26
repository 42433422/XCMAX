"""Read back goal, child-task and observation identities from their existing owners."""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import select

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.run_audit_scope import _result_scope
from app.application.agent_orchestrator.verification_readback import _report
from app.utils.operational_errors import RECOVERABLE_ERRORS


def plan_admission_receipt(output: dict) -> bool:
    """An admitted child can still await approval; its business effect is not complete."""
    if set(output) - {"success", "pending_approval", "execution_state", "message", "data"}:
        return False
    data = output.get("data")
    if (
        not isinstance(data, dict)
        or set(data)
        - {"protocol", "task_id", "turn_id", "conversation_id", "run_id", "attempt", "status"}
        or data.get("status")
        not in {
            "waiting_user",
            "queued",
            "planning",
            "running",
            "retrying",
            "completed",
        }
    ):
        return False
    state = "waiting_approval" if data["status"] == "waiting_user" else data["status"]
    return (
        output.get("success") is True
        and output.get("execution_state") == state
        and (output.get("pending_approval") is (data["status"] == "waiting_user"))
    )


def verified_plan_admission(step, output: dict, context: dict) -> bool:
    """Preserve only a real admission, never a tool's claimed unfinished child.

    Generic execution normalization must still reject arbitrary pending writes.
    This one host action completes by admitting a separately approved task, so
    independently read its original parent, goal and child before preserving the
    receipt. The ordinary frozen-contract verifier remains the final step gate.
    """
    if (step.tool_id, step.action) != (
        "enterprise_cognition",
        "plan",
    ) or not plan_admission_receipt(output):
        return False
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.infrastructure.auth.agent_mod_scope import _bound_actor

    try:
        _bound_actor(context)
        with _scope(context):
            parent = get_agent_run_repository().get(str(context.get("run_id") or ""))
            expected_scope = (
                str(context.get("user_id") or ""),
                str(context.get("tenant_id") or ""),
                str(context.get("mod_id") or ""),
            )
            if (
                parent is None
                or _result_scope(parent) != expected_scope
                or not any(
                    (row.step_id, row.node_id, row.tool_id, row.action, row.params)
                    == (step.step_id, step.node_id, step.tool_id, step.action, step.params)
                    for row in parent.steps
                )
            ):
                return False
            goal = _goal(step.params.get("goal_id"), context)
            return (
                goal is not None and _plan(parent, step, output["data"], context, goal) is not None
            )
    except (PermissionError,) + RECOVERABLE_ERRORS:
        return False


def normalize_tool_execution_result(step, output: dict, context: dict) -> dict:
    """Apply the common result contract after checking this host admission kind."""
    from app.application.agent_orchestrator.result_verification import pending_execution_receipt
    from app.domain.task_lifecycle.results import normalize_execution_result

    # Only scoped readback admits a plan receipt, regardless of its action.
    if (step.tool_id, step.action) == ("enterprise_cognition", "plan") or plan_admission_receipt(
        output
    ):
        if verified_plan_admission(step, output, context):
            return output
        normalized = normalize_execution_result(output)
        if output.get("success") is True:
            return {**normalized, "success": False, "retryable": False}
        return normalized
    if pending_execution_receipt(output) or _original_employee_delegation(step, output, context):
        return output
    return normalize_execution_result(output)


def _original_employee_delegation(step, output: dict, context: dict) -> bool:
    """Keep a known admin child wait only after reading its original host binding."""
    from app.application.agent_orchestrator.run_audit_scope import (
        attach_child_result,
        project_child_results,
    )
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.domain.task_lifecycle.results import (
        execution_result_envelopes,
        execution_result_outcome_unknown,
        execution_result_pending_state,
    )
    from app.infrastructure.auth.agent_mod_scope import _bound_actor

    waiting = {"queued", "planning", "running", "retrying", "pending", "accepted"}
    if (
        (step.tool_id, step.action) != ("employee", "execute")
        or context.get("source") != "admin_employee_execute"
        or execution_result_pending_state(output) not in waiting
        or execution_result_outcome_unknown(output)
        or any(row.get("error") for row in execution_result_envelopes(output))
    ):
        return False
    child_ids = {
        str(row["agent_run_id"])
        for row in execution_result_envelopes(output)
        if row.get("agent_run_id")
    }
    if len(child_ids) != 1:
        return False
    try:
        _bound_actor(context)
        repository = get_agent_run_repository()
        if not isinstance(repository, SQLAlchemyAgentRunRepository):
            return False
        parent = repository.get(str(context.get("run_id") or ""))
        child = repository.get(next(iter(child_ids)))
        expected = (
            str(context.get("user_id") or ""),
            str(context.get("tenant_id") or ""),
            str(
                (context.get("_mod_authorization") or {}).get("mod_id")
                or context.get("mod_id")
                or ""
            ),
        )
        if (
            parent is None
            or child is None
            or parent.run_id == child.run_id
            or _result_scope(parent) != expected
            or not parent.metadata.get("admin_employee_key")
            or (parent.metadata.get("task_context") or {}).get("task_id") != context.get("task_id")
            or len(parent.steps) != 1
            or len(parent.tool_calls) != 1
            or (parent.steps[0].tool_id, parent.steps[0].action) != ("employee", "execute")
            or parent.steps[0].params != step.params
            or parent.tool_calls[0].params != step.params
            or parent.tool_calls[0].step_id != parent.steps[0].step_id
            or step.params.get("employee_id") != parent.metadata.get("admin_employee_id")
            or (child.metadata.get("runtime_context") or {}).get("parent_run_id") != parent.run_id
            or (child.metadata.get("runtime_context") or {}).get("parent_task_id")
            != context.get("task_id")
            or (child.metadata.get("runtime_context") or {}).get("employee_id")
            != parent.metadata.get("admin_employee_id")
            or not attach_child_result(parent, child)
        ):
            return False
        observed = project_child_results(parent, repository.get).get(child.run_id) or {}
        return observed.get("execution_state") in waiting
    except (PermissionError,) + RECOVERABLE_ERRORS:
        return False


@contextmanager
def _scope(context):
    from app.infrastructure.auth.agent_mod_scope import agent_mod_execution_scope
    from app.infrastructure.tenant_scope import owned_tenant_scope
    from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id

    token = set_request_active_mod_id("")
    try:
        with (
            owned_tenant_scope(int(context["tenant_id"])),
            agent_mod_execution_scope(context.get("_mod_authorization")),
        ):
            yield
    finally:
        reset_request_active_mod_id(token)


def _goal(goal_id, context):
    from app.application.enterprise_cognition.goals import _decode_goal
    from app.db import HostSessionLocal
    from app.db.models.enterprise_goal import EnterpriseGoalBinding
    from app.domain.enterprise_cognition.catalog import definition_for
    from app.infrastructure.auth.enterprise_scope import SourceScope
    from app.infrastructure.enterprise_cognition_sources import AuthorityReader

    scope = SourceScope(
        int(context["tenant_id"]), str(context["user_id"]), str(context.get("mod_id") or "")
    )
    with HostSessionLocal() as db:
        record = db.scalar(
            select(EnterpriseGoalBinding).where(
                EnterpriseGoalBinding.tenant_id == scope.tenant_id,
                EnterpriseGoalBinding.actor_id == scope.actor_id,
                EnterpriseGoalBinding.mod_id == scope.mod_id,
                EnterpriseGoalBinding.goal_id == goal_id,
            )
        )
        if record is None:
            return None
        goal = _decode_goal(record)
        reader, definition = AuthorityReader(), definition_for(goal["entity_type"])
        reader.authorize(scope, definition)
        return goal if reader.visible(db, definition, scope, goal["entity_id"]) else None


def _plan(run, step, data, context, goal):
    from app.application.agent_orchestrator.business_harness import harness_event_context
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository

    repository = get_agent_run_repository()
    task_id = (
        "enterprise_"
        + canonical_hash(
            [
                int(context["tenant_id"]),
                str(context["user_id"]),
                str(context.get("mod_id") or ""),
                step.params["request_id"],
            ]
        )[:40]
    )
    task = repository.get_task(
        user_id=str(context["user_id"]), tenant_id=str(context["tenant_id"]), task_id=task_id
    )
    child = repository.get(task.active_run_id) if task else None
    scope = (str(context["user_id"]), str(context["tenant_id"]), str(context.get("mod_id") or ""))
    if child is None or child.run_id == run.run_id or _result_scope(child) != scope:
        return None
    runtime = child.metadata.get("runtime_context") or {}
    binding = runtime.get("enterprise_cognition") or {}
    parent_task = (run.metadata.get("task_context") or {}).get("task_id") or context.get("task_id")
    expected = canonical_hash(
        {
            "goal": goal["binding_sha256"],
            "message": step.params["message"],
            "task_id": task_id,
            "parent_run_id": run.run_id,
            "parent_task_id": parent_task,
        }
    )
    historical_approval = data.get("status") == "waiting_user" and any(
        event.event_type in {"task.approval_required", "step.waiting_user"}
        and event.run_id == child.run_id
        for event in child.events
    )
    dynamic = child.metadata.get("runtime_type") == "xiaox"
    if dynamic:
        from app.domain.task_lifecycle.agent_runtime_contract import validate_runtime_goal

        if child.metadata.get("runtime_goal_contract") is not None:
            try:
                validate_runtime_goal(child)
            except ValueError:
                return None
        constraints = runtime.get("_runtime_goal_constraints") or {}
        if (
            child.intent != "xiaox.runtime"
            or child.message != step.params["message"]
            or child.metadata.get("runtime_task_id") != task_id
            or constraints.get("goal_binding_sha256") != goal["binding_sha256"]
            or constraints.get("request_sha256") != expected
            or constraints.get("requires_approval") is not True
            or not any(event.event_type == "runtime.queued" for event in child.events)
        ):
            return None
        historical_approval = historical_approval or data.get("status") == "queued"
    if (
        binding.get("goal") != goal
        or binding.get("request_sha256") != expected
        or (not dynamic and child.metadata.get("task_request_fingerprint") != expected)
        or runtime.get("parent_run_id") != run.run_id
        or runtime.get("parent_task_id") != parent_task
        or (child.metadata.get("task_context") or {}).get("task_id") != task_id
        or (
            not dynamic
            and ((child.metadata.get("plan") or {}).get("metadata") or {}).get(
                "enterprise_cognition"
            )
            != binding
        )
        or data != {**harness_event_context(child), "status": data.get("status")}
        or (data.get("status") != child.status and not historical_approval)
    ):
        return None
    return {
        "task_id": task_id,
        "run_id": child.run_id,
        "request_sha256": expected,
        "current_child_status": child.status,
        "admission_verified": True,
        "business_execution_verified": False,
    }


def _observation(step, data, context):
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.application.agent_task_context import scoped_personal_memory_id
    from app.application.enterprise_cognition.outcomes import _execution_evidence, _frozen, _time
    from app.application.memory_v2_facade import get_user_memory_service

    original = get_agent_run_repository().get(step.params["run_id"])
    scope = (str(context["user_id"]), str(context["tenant_id"]), str(context.get("mod_id") or ""))
    if original is None or _result_scope(original) != scope:
        return None
    binding = (original.metadata.get("runtime_context") or {}).get("enterprise_cognition") or {}
    goal = _goal((binding.get("goal") or {}).get("goal_id"), context)
    if goal is None or goal != binding.get("goal"):
        return None
    observed = _frozen(original, goal)
    if not observed or any(data.get(key) != value for key, value in observed.items()):
        return None
    _execution_evidence(original, _time(binding.get("bound_at")))
    owner = scoped_personal_memory_id(
        {"tenant_id": scope[1], "actor_id": scope[0], "mod_id": scope[2]}
    )
    candidate = next(
        (
            row
            for row in get_user_memory_service().list_memories(owner)
            if row.get("memory_id") == data.get("memory_id")
        ),
        None,
    )
    if candidate is None:
        return None
    revisions = [
        candidate,
        *(entry.get("previous") or {} for entry in candidate.get("history", [])),
    ]
    if not any(
        row.get("key") == "enterprise_outcome:" + observed["observation_id"]
        and row.get("value") == observed
        and row.get("status") == data.get("memory_status")
        for row in revisions
    ):
        return None
    return {
        "run_id": original.run_id,
        "observation_id": observed["observation_id"],
        "memory_id": candidate["memory_id"],
        "memory_status": candidate["status"],
        "attribution": "not_inferred",
    }


def verify_cognition_result(run, step, output: dict, context: dict) -> dict:
    data = output.get("data")
    if not isinstance(data, dict):
        return _report(
            "inconclusive", "enterprise_receipt_identity_missing", "enterprise_authority"
        )
    with _scope(context):
        evidence = None
        if step.action == "evaluate":
            evidence = _observation(step, data, context)
        else:
            goal = _goal(step.params.get("goal_id"), context)
            if goal is not None and step.action == "plan" and plan_admission_receipt(output):
                evidence = _plan(run, step, data, context, goal)
            elif goal is not None:
                from app.domain.enterprise_cognition.goal_contract import GoalDefinition

                expected = GoalDefinition.model_validate(step.params).model_dump(mode="json")
                if data == goal and all(goal.get(key) == value for key, value in expected.items()):
                    evidence = {
                        "goal_id": goal["goal_id"],
                        "binding_sha256": goal["binding_sha256"],
                    }
        if evidence is None:
            return _report("inconclusive", "enterprise_authority_mismatch", "enterprise_authority")
        return _report("verified", "result_verified", "enterprise_authority", **evidence)
