"""Project terminal Business Harness results back into their conversation."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.application.agent_orchestrator.business_harness import (
    BUSINESS_HARNESS_PROTOCOL,
    ensure_terminal_business_result,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_FACT_LABELS = {
    "id": "记录 ID",
    "customer_id": "客户 ID",
    "product_id": "产品 ID",
    "material_id": "原材料 ID",
    "order_id": "订单 ID",
    "record_id": "记录 ID",
    "request_id": "请求 ID",
    "request_no": "请求单号",
    "order_number": "业务单号",
    "document_id": "文档 ID",
    "doc_name": "文档",
    "name": "名称",
    "created": "新增",
    "updated": "更新",
    "deleted": "删除",
    "count": "数量",
    "total": "合计",
}


def _message_for_result(result: dict[str, Any], approval_request_id: str) -> str:
    status = str(result.get("status") or "")
    summary = str(result.get("summary") or "").strip()
    if status == "completed":
        prefix = "审批已完成，业务操作执行成功"
    elif status == "cancelled":
        prefix = "审批已拒绝，业务任务已取消，未继续执行"
    else:
        prefix = "审批流程已结束，但业务操作执行失败"
    parts = [prefix]
    if summary and summary not in prefix:
        parts.append(summary)
    facts = result.get("facts")
    if isinstance(facts, dict):
        rendered = [
            f"{_FACT_LABELS.get(key, key)}：{value}"
            for key, value in facts.items()
            if value not in ("", None)
        ]
        if rendered:
            parts.append("；".join(rendered))
    if approval_request_id:
        parts.append(f"审批单：{approval_request_id}")
    return "。".join(part.rstrip("。") for part in parts if part).strip() + "。"


def project_terminal_run_to_conversation(
    run_id: str,
    *,
    approval_request_id: str = "",
) -> int | None:
    """Write one idempotent terminal assistant message for an approval-backed run."""
    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id:
        return None
    try:
        from app.application.agent_orchestrator import AgentOrchestrator
        from app.services import get_conversation_service

        run = AgentOrchestrator().get_run(normalized_run_id)
        if run is None:
            return None
        result = ensure_terminal_business_result(run)
        if not result:
            return None
        runtime = run.metadata.get("runtime_context")
        runtime = runtime if isinstance(runtime, dict) else {}
        session_id = str(
            result.get("conversation_id")
            or runtime.get("conversation_id")
            or runtime.get("session_id")
            or ""
        ).strip()
        if not session_id:
            return None
        projection_key = str(result.get("projection_key") or "").strip()
        metadata = json.dumps(
            {
                "role_hint": "assistant",
                "idempotency_key": projection_key,
                "business_harness": {
                    "protocol": BUSINESS_HARNESS_PROTOCOL,
                    "event": "task.terminal_result",
                    "task_id": result.get("task_id"),
                    "turn_id": result.get("turn_id"),
                    "run_id": result.get("run_id"),
                    "approval_request_id": approval_request_id,
                },
                "ui": {
                    "workflowAction": "business_harness_terminal",
                    "businessResult": result,
                },
            },
            ensure_ascii=False,
            default=str,
        )[:12000]
        return get_conversation_service().save_message(
            session_id=session_id,
            user_id=str(run.user_id or ""),
            role="assistant",
            content=_message_for_result(result, approval_request_id)[:8000],
            intent="business_harness_result",
            metadata=metadata,
            idempotency_key=projection_key,
        )
    except RECOVERABLE_ERRORS as exc:
        logger.warning(
            "business harness result projection failed run_id=%s type=%s",
            normalized_run_id,
            type(exc).__name__,
        )
        return None


__all__ = ["project_terminal_run_to_conversation"]
