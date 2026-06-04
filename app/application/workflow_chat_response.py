"""工作流运行结果 → 聊天响应格式化（从 ai_chat_app_service 拆出）。"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_workflow_thinking_steps(plan: Any, decision_reason: str) -> str:
    steps = []
    if decision_reason:
        steps.append(f"决策：{decision_reason}")
    for idx, node in enumerate(getattr(plan, "nodes", []) or [], start=1):
        name = getattr(node, "tool_name", None) or getattr(node, "name", "") or "step"
        steps.append(f"{idx}. {name}")
    return "\n".join(steps) if steps else "工作流已规划"


def workflow_products_float_query(plan: Any, run_result: Any, user_message: str) -> str:
    msg = str(user_message or "").strip()
    if not msg:
        return ""
    try:
        nodes = getattr(plan, "nodes", []) or []
        if not nodes:
            return ""
        last = run_result.outputs if hasattr(run_result, "outputs") else {}
        if isinstance(last, dict) and last.get("products"):
            return msg
    except Exception:
        logger.debug("workflow_products_float_query skipped", exc_info=True)
    return ""


def format_workflow_run_response(
    *,
    plan: Any,
    run_result: Any,
    user_message: str,
    decision_reason: str = "",
) -> dict[str, Any]:
    """将 WorkflowEngine 运行结果格式化为聊天 API 响应片段。"""
    thinking = build_workflow_thinking_steps(plan, decision_reason)
    content_parts: list[str] = [thinking]
    outputs = getattr(run_result, "outputs", None) or {}
    if isinstance(outputs, dict):
        summary = outputs.get("summary") or outputs.get("message")
        if summary:
            content_parts.append(str(summary))
        elif outputs:
            content_parts.append(
                "```json\n" + json.dumps(outputs, ensure_ascii=False, indent=2)[:4000] + "\n```"
            )
    float_q = workflow_products_float_query(plan, run_result, user_message)
    data: dict[str, Any] = {
        "content": "\n\n".join(p for p in content_parts if p),
        "workflow": {
            "plan_id": getattr(plan, "plan_id", ""),
            "status": getattr(run_result, "status", "completed"),
        },
    }
    if float_q:
        data["float_query"] = float_q
    return data
