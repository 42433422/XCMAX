"""Authenticated model-tool adapter; all proposed business actions use original tasks."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from app.application.enterprise_cognition.service import (
    cognition_result_verified,
    get_cognition_service,
)
from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def execute_enterprise_cognition(action: str, params: dict, context: dict) -> dict:
    try:
        context = dict(context)
        if action == "plan":
            parent_run = context.get("agent_run_id") or context.get("run_id")
            if parent_run:
                context["parent_run_id"] = str(parent_run)
                context["parent_task_id"] = str(context.get("task_id") or "")
        result = get_cognition_service().invoke(action, params, context=context)
        if action == "plan":
            from app.application.agent_orchestrator.business_harness import harness_event_context

            identity = harness_event_context(result)
            return {
                "success": True,
                "pending_approval": result.status == "waiting_user",
                "execution_state": "waiting_approval"
                if result.status == "waiting_user"
                else result.status,
                "message": "方案已进入原任务链；实际执行和指标变化以该任务审批及回执为准。",
                "data": {**identity, "status": result.status},
            }
        return {
            "success": cognition_result_verified(action, params, result),
            "data": result,
        }
    except (AgentModAuthorizationError, PermissionError):
        return {
            "success": False,
            "error_code": "enterprise_access_denied",
            "message": "当前账号无权访问该企业状态或任务。",
        }
    except (ValidationError, ValueError):
        return {
            "success": False,
            "error_code": "enterprise_contract_rejected",
            "message": "企业实体、目标或请求与已有证据不一致；本次未派发新业务动作。",
        }
    except RECOVERABLE_ERRORS:
        logger.exception("enterprise cognition receipt unavailable")
        return {
            "success": False,
            "error_code": "enterprise_receipt_unavailable",
            "execution_state": "unknown",
            "retryable": False,
            "reconciliation_required": True,
            "message": "企业状态或任务回执暂不可读，请按原任务核对结果。",
        }
