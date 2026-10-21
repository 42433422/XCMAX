from __future__ import annotations

import math
import os
import time
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from typing import Any

from app.application.agent_orchestrator.param_references import (
    UNRESOLVED_CODE,
    unresolved_placeholders,
)
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_spec import validate_tool_call, validate_tool_result
from app.application.tool_execution_deadline import invocation_deadline
from app.utils.operational_errors import RECOVERABLE_ERRORS

_SQL_TENANT_SCOPED_TOOL_IDS = frozenset(
    {"business_db", "inventory", "shipment_records", "shipment_orders", "document_template", "purchase"}
)


class AgentToolExecutor:
    def execute_with_deadline(self, step, *, runtime_context, deadline_monotonic):
        from app.application.agent_orchestrator.tool_process import execute_isolated

        if (
            step.tool_id == "dataset_rag"
            and step.action == "rebuild_index"
            and step.params.get("background", True)
        ):
            from app.application.dataset_rag_queue import ensure_host_worker

            ensure_host_worker()
        return execute_isolated(self, step, runtime_context, deadline_monotonic)

    def execute(
        self,
        step: AgentStep,
        *,
        runtime_context: dict[str, Any],
    ) -> dict[str, Any]:
        from app.application.facades.tools_facade import execute_registered_workflow_tool

        params = dict(step.params or {})
        validation = validate_tool_call(step.tool_id, step.action, params)
        if not validation.ok:
            return {
                "success": False,
                "error_code": validation.error_code,
                "message": validation.message,
                "tool_id": validation.tool_id,
                "action": validation.action,
            }
        leftover = unresolved_placeholders(params)
        if leftover:
            return {
                "success": False,
                "error_code": UNRESOLVED_CODE,
                "message": "参数包含未解析的占位符，已拒绝执行：" + "、".join(leftover)[:200],
                "tool_id": validation.tool_id,
                "action": validation.action or step.action,
            }
        params["_runtime_context"] = dict(runtime_context or {})
        action = validation.action or step.action
        runtime_tenant_raw = params["_runtime_context"].get("tenant_id")
        runtime_tenant_id: int | None = None
        if step.tool_id in _SQL_TENANT_SCOPED_TOOL_IDS and runtime_tenant_raw not in (None, ""):
            try:
                if isinstance(runtime_tenant_raw, bool) or not str(runtime_tenant_raw).isdigit():
                    raise ValueError
                runtime_tenant_id = int(runtime_tenant_raw)
                if runtime_tenant_id <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return {
                    "success": False,
                    "error_code": "invalid_tenant_context",
                    "message": "任务租户上下文无效，已拒绝执行工具",
                    "tool_id": validation.tool_id,
                    "action": action,
                }

        from app.infrastructure.auth.agent_mod_scope import (
            AgentModAuthorizationError,
            agent_mod_execution_scope,
        )
        from app.infrastructure.tenant_scope import tenant_scope

        try:
            # Durable/background Agent runs execute outside the originating HTTP
            # request. Restore the authenticated integer tenant recorded in
            # runtime_context so repository/raw-SQL boundaries keep their fail-closed
            # isolation. Dataset/document tools deliberately keep their own opaque
            # string tenant keys and must not be coerced here.
            with (
                agent_mod_execution_scope(params["_runtime_context"].get("_mod_authorization")),
                tenant_scope(runtime_tenant_id) if runtime_tenant_id is not None else nullcontext(),
            ):
                result = execute_registered_workflow_tool(step.tool_id, action, params)
        except AgentModAuthorizationError as exc:
            return {
                "success": False,
                "error_code": "mod_authorization_invalid",
                "message": str(exc),
                "tool_id": validation.tool_id,
                "action": action,
            }
        if not isinstance(result, dict):
            return {
                "success": False,
                "error_code": "tool_result_not_object",
                "message": "工具返回值必须是 object",
                "tool_id": validation.tool_id,
                "action": action,
                "raw_result_type": type(result).__name__,
            }

        output_validation = validate_tool_result(validation.tool_id, action, result)
        if not output_validation.ok:
            return {
                "success": False,
                "error_code": output_validation.error_code,
                "message": output_validation.message,
                "tool_id": output_validation.tool_id,
                "action": output_validation.action,
                "raw_success": result.get("success"),
                "raw_message": result.get("message") or result.get("error"),
                "raw_error_code": result.get("error_code"),
                "output_keys": sorted(str(key) for key in result.keys()),
            }
        return result


def execute_with_tool_deadline(
    executor: Any, step: AgentStep, *, runtime_context: dict[str, Any], timeout_seconds: float
) -> dict[str, Any]:
    """Propagate deadlines; workers restore scopes, strict custom adapters must be bounded."""
    timeout = float(timeout_seconds)
    if not math.isfinite(timeout) or timeout <= 0:
        return {"success": False, "error_code": "invalid_tool_timeout", "retryable": False}
    started = time.monotonic()
    deadline = started + timeout
    context = dict(runtime_context)
    context.update(
        {
            "timeout_seconds": timeout,
            "deadline_monotonic": deadline,
            "deadline_utc": (datetime.now(UTC) + timedelta(seconds=timeout)).isoformat(),
        }
    )
    bounded = getattr(executor, "execute_with_deadline", None)
    required = os.environ.get("XCAGI_AGENT_TOOL_HARD_TIMEOUT_REQUIRED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if required and not callable(bounded):
        return {
            "success": False,
            "error_code": "tool_deadline_unsupported",
            "retryable": False,
            "message": "工具缺少可取消/隔离的有界执行适配器，已拒绝执行",
        }
    result: Any = None
    try:
        with invocation_deadline(deadline) as invocation:
            result = (
                bounded(step, runtime_context=context, deadline_monotonic=deadline)
                if callable(bounded)
                else executor.execute(step, runtime_context=context)
            )
    except TimeoutError:
        pass
    except RECOVERABLE_ERRORS as exc:
        if not invocation.uncertain:
            raise
        result = {
            "error_code": "tool_exception_after_unknown_io",
            "exception_type": type(exc).__name__,
        }
    else:
        if (
            time.monotonic() <= deadline
            and isinstance(result, dict)
            and not invocation.uncertain
            and result.get("outcome") != "unknown"
            and not result.get("reconciliation_required")
        ):
            return result
    return {
        "success": False,
        "error_code": "tool_timeout_unknown",
        "reconciliation_evidence": result if isinstance(result, dict) else {},
        "io_reconciliation": list(invocation.uncertain),
        "outcome": "unknown",
        "retryable": False,
        "reconciliation_required": True,
        "message": "工具超时，业务结果未知；必须核对原调用，不可自动重试",
    }
