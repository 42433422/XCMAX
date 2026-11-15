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


__all__ = ["compensation_enabled", "run_compensations"]
