"""失败后的补偿执行（saga 的最小实现）。

补偿动作只能来自受信的风险注册表（``action_spec.compensate``），不接受模型在
计划里自带的补偿声明，避免失败后执行未经审批的写操作。默认开启，可用
``XCAGI_COMPENSATION=0`` 全局停用，或在计划元数据里显式写
``{"compensation": false}`` 跳过。

声明形如::

    "compensate": {
        "tool_id": "customers",
        "action": "delete",
        "params": {"force": false},
        "params_from": {"local_key": "compensation_param"},
        "params_from_output": {"id": ["id", "data.id"]},
    }

``params_from`` 从步骤入参取值；``params_from_output`` 从步骤输出取值，支持
点路径与候选列表（按顺序取第一个命中的非空值）。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.workflow.workflow_types import PlanGraph
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

ExecuteFn = Callable[[str, str, dict[str, Any]], dict[str, Any]]

_MISSING = object()


def compensation_enabled(plan: PlanGraph | None) -> bool:
    """服务端开关优先；计划元数据只能显式关闭。"""
    if plan is None:
        return False
    raw = str(os.environ.get("XCAGI_COMPENSATION") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    metadata = getattr(plan, "metadata", None)
    if isinstance(metadata, dict) and metadata.get("compensation") is False:
        return False
    return True


def _spec_for(tool_id: str, action: str) -> dict[str, Any] | None:
    try:
        from app.domain.autonomy.autonomy_guard import get_autonomy_guard

        spec = get_autonomy_guard().get_action_spec(tool_id, action) or {}
    except RECOVERABLE_ERRORS:
        return None
    compensate = spec.get("compensate")
    return compensate if isinstance(compensate, dict) else None


def _lookup_path(source: Any, path: str) -> Any:
    current = source
    for part in str(path).split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _resolve_output_value(output: Any, spec: Any) -> Any:
    paths = spec if isinstance(spec, (list, tuple)) else [spec]
    for path in paths:
        value = _lookup_path(output, str(path))
        if value is not _MISSING and value not in (None, ""):
            return value
    return _MISSING


def _compensation_params(
    compensate: dict[str, Any],
    step_params: dict[str, Any],
    step_output: Any,
) -> dict[str, Any]:
    params = dict(compensate.get("params") or {})
    mapping = compensate.get("params_from")
    if isinstance(mapping, dict):
        for source, target in mapping.items():
            if source in step_params:
                params[str(target)] = step_params[source]
    output_mapping = compensate.get("params_from_output")
    if isinstance(output_mapping, dict):
        for target, source in output_mapping.items():
            value = _resolve_output_value(step_output, source)
            if value is not _MISSING:
                params[str(target)] = value
    return params


def run_compensations(
    run: AgentRun,
    *,
    plan: PlanGraph | None,
    execute: ExecuteFn,
    runtime_context: dict[str, Any],
) -> list[dict[str, Any]]:
    """按逆序补偿已完成的非幂等步骤；失败只记录，不改变原始失败结论。"""
    if not compensation_enabled(plan):
        return []
    done = list(run.metadata.get("compensated_node_ids") or [])
    executed: list[dict[str, Any]] = []
    for step in reversed(run.steps):
        if step.status != "completed" or step.node_id in done:
            continue
        if step.idempotent:
            continue
        compensate = _spec_for(step.tool_id, step.action)
        if compensate is None:
            continue
        tool_id = str(compensate.get("tool_id") or step.tool_id)
        action = str(compensate.get("action") or "")
        if not action:
            continue
        params = _compensation_params(compensate, dict(step.params or {}), step.output)
        params["_runtime_context"] = dict(runtime_context or {})
        record: dict[str, Any] = {
            "node_id": step.node_id,
            "tool_id": tool_id,
            "action": action,
        }
        try:
            result = execute(tool_id, action, params)
            record["success"] = (result or {}).get("success") is True
            record["error_code"] = str((result or {}).get("error_code") or "")
            record["reconciliation_required"] = bool((result or {}).get("reconciliation_required"))
            record["message"] = str((result or {}).get("message") or "")[:200]
        except RECOVERABLE_ERRORS as exc:
            logger.warning("补偿执行失败：%s.%s %s", tool_id, action, exc)
            record.update(success=False, message=f"补偿执行失败：{exc}")
        executed.append(record)
        done.append(step.node_id)
        run.add_event("compensation.executed", "执行失败补偿", record)
    if executed:
        run.metadata["compensated_node_ids"] = done
        run.metadata["compensation_results"] = executed
    return executed


def plan_parallel_enabled() -> bool:
    """只读且幂等的独立节点允许同层并行；写节点仍由读写闸门与串行调度约束。"""
    raw = str(os.environ.get("XCAGI_PLAN_PARALLEL") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def execute_authorized_compensation(
    orchestrator: Any,
    run: AgentRun,
    tool_id: str,
    action: str,
    params: dict[str, Any],
    *,
    runtime_context: dict[str, Any],
) -> dict[str, Any]:
    """Undo is a new action, not authority inherited from an approved create."""
    from app.application.agent_orchestrator.budget import budget_exceeded_payload
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_permission import actor_tool_denial
    from app.application.agent_orchestrator.tool_spec import validate_tool_call

    concrete = dict(params)
    concrete.pop("_runtime_context", None)
    validation = validate_tool_call(tool_id, action, concrete)
    if not validation.ok or validation.spec is None:
        return {"success": False, "error_code": "compensation_contract_invalid"}
    spec = validation.spec
    context = dict(runtime_context)
    denial = actor_tool_denial(tool_id, spec.action, context, concrete)
    if denial is not None:
        return denial
    identity = canonical_hash(
        {"run_id": run.run_id, "tool_id": tool_id, "action": spec.action, "params": concrete}
    )
    step = AgentStep(
        node_id=f"compensation_{identity}",
        step_id=f"step_compensation_{identity}",
        tool_id=tool_id,
        action=spec.action,
        params=concrete,
        risk=spec.risk,
        idempotent=bool(spec.idempotent),
    )
    # The original step/plan's approval does not approve a compensating delete.
    # Never mint approval or call the unguarded business-dispatch facade here.
    if not orchestrator._can_auto_execute(step):
        return {
            "success": False,
            "error_code": "compensation_approval_required",
            "message": "补偿动作需要单独授权；原业务结果保留，等待人工核对。",
            "reconciliation_required": True,
        }
    budget = budget_exceeded_payload(
        run,
        additional_cost_units=orchestrator._step_cost_units(step),
        scope=f"{tool_id}.{action}",
    )
    if budget is not None:
        return {"success": False, "error_code": "budget_exceeded"}
    previous = next((item for item in run.steps if item.node_id == step.node_id), None)
    if previous is not None:
        return dict(previous.output or {"success": False, "error_code": "compensation_incomplete"})
    run.steps.append(step)
    original_status, original_error = run.status, run.error
    try:
        # Same billing, cancellation, deadline, idempotency and audit path as
        # ordinary steps, using a distinct deterministic execution identity.
        orchestrator._execute_step(run, step, runtime_context=context, node_outputs={})
        return dict(step.output or {"success": False, "error_code": "compensation_incomplete"})
    finally:
        run.status, run.error = original_status, original_error
        orchestrator._repo.save(run)


def apply_failure_compensations(
    orchestrator: Any,
    run: AgentRun,
    *,
    plan: PlanGraph | None,
    runtime_context: dict[str, Any],
) -> None:
    try:
        run_compensations(
            run,
            plan=plan,
            execute=lambda tool_id, action, params: execute_authorized_compensation(
                orchestrator, run, tool_id, action, params, runtime_context=runtime_context
            ),
            runtime_context=runtime_context,
        )
    except RECOVERABLE_ERRORS:
        logger.warning("失败补偿执行异常", exc_info=True)


__all__ = [
    "compensation_enabled",
    "run_compensations",
    "plan_parallel_enabled",
    "execute_authorized_compensation",
    "apply_failure_compensations",
]
