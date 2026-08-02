"""Deterministic customer changes initiated from natural-language chat.

Customer deletion is deliberately resolved before a write plan is created.  A
name must match exactly and the write always enters a durable ``AgentRun`` that
waits for explicit confirmation.  This keeps conversational convenience while
making the business-system receipt, rather than model prose, the source of
truth.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.workflow.types import PlanGraph, WorkflowNode

_CUSTOMER_MARKERS = ("客户", "购买单位", "买家", "客商")
_DELETE_VERBS = ("删除", "删掉", "去掉", "移除", "注销")
_POLITE_PREFIXES = ("请", "帮我", "麻烦")
_UNSAFE_EXACT_TARGETS = {"这个", "那个", "该", "上述", "上面", "他", "她", "它", "对方", "客户"}
_UNSAFE_TARGET_SUFFIXES = (
    "电话",
    "手机号",
    "地址",
    "联系人",
    "备注",
    "标签",
    "字段",
    "记录",
    "发货单",
    "订单",
)
_TARGET_PUNCTUATION = frozenset("，。,.!?！？；;")


def _recent_customer_context(context: dict[str, Any] | None, message: str) -> bool:
    if any(marker in message for marker in _CUSTOMER_MARKERS):
        return True
    rows = (context or {}).get("recent_messages") if isinstance(context, dict) else None
    if not isinstance(rows, list):
        return False
    current = "".join(str(message or "").split())
    for item in rows[-6:]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "")
        # The frontend includes the current message in recent_messages.  It is
        # not enough by itself to establish the omitted business entity.
        if "".join(content.split()) == current:
            continue
        if any(marker in content for marker in _CUSTOMER_MARKERS):
            return True
    return False


def _parse_customer_delete_target(text: str) -> str:
    """Parse one exact delete command without regex backtracking on user text."""
    remaining = " ".join(str(text or "").split())
    if not remaining:
        return ""

    while True:
        matched_prefix = next(
            (prefix for prefix in _POLITE_PREFIXES if remaining.startswith(prefix)),
            "",
        )
        if not matched_prefix:
            break
        remaining = remaining[len(matched_prefix) :].lstrip()

    if remaining.startswith("把"):
        remaining = remaining[1:].lstrip()
    verb = next((candidate for candidate in _DELETE_VERBS if remaining.startswith(candidate)), "")
    if not verb:
        return ""
    remaining = remaining[len(verb) :].lstrip()
    subject = next((noun for noun in _CUSTOMER_MARKERS if remaining.startswith(noun)), "")
    if subject:
        remaining = remaining[len(subject) :].lstrip()

    name = remaining.strip(" \t\"'“”《》")
    for suffix in ("这个客户", "这位客户", "该客户", "客户"):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
            break
    if (
        len(name) < 2
        or len(name) > 64
        or any(char in _TARGET_PUNCTUATION for char in name)
        or name in _UNSAFE_EXACT_TARGETS
        or any(name.endswith(suffix) for suffix in _UNSAFE_TARGET_SUFFIXES)
    ):
        return ""
    return name


def classify_customer_delete_intent(
    message: str,
    *,
    runtime_context: dict[str, Any] | None = None,
) -> str:
    """Return an exact-name customer delete target, or ``""`` when unsafe."""

    text = str(message or "").strip()
    if not text or not _recent_customer_context(runtime_context, text):
        return ""
    return _parse_customer_delete_target(text)


def _runtime_context(
    *,
    user_id: str,
    message: str,
    source: str | None,
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    resolved: dict[str, Any] = {
        "user_id": str(user_id or ""),
        "message": str(message or ""),
        "source": str(source or ""),
        "workflow_trace_mode": "agent_orchestrator",
        "deterministic_workflow": True,
        "business_domain": "customers",
    }
    if isinstance(context, dict):
        for key in ("ui_surface", "intent_channel", "tool_execution_profile"):
            if context.get(key) is not None:
                resolved[key] = context[key]
    return resolved


def _query_only_payload(
    *,
    run,
    customer_name: str,
    text: str,
    reason: str,
) -> dict[str, Any]:
    receipt = {
        "receipt_id": f"customer_preflight_{uuid.uuid4().hex}",
        "domain": "customers",
        "operation": "delete",
        "status": "not_executed",
        "executed": False,
        "verified": True,
        "affected_rows": 0,
        "reason": reason,
        "details": {"customer_name": customer_name, "run_id": run.run_id},
    }
    return {
        "success": True,
        "message": text,
        "response": text,
        "run_id": run.run_id,
        "agent_run_id": run.run_id,
        "execution_receipt": receipt,
        "business_receipt": receipt,
        "data": {
            "text": text,
            "action": "business_action_not_executed",
            "run_id": run.run_id,
            "agent_run_id": run.run_id,
            "data": {
                "intent": "customer_delete",
                "run_id": run.run_id,
                "agent_run_id": run.run_id,
                "execution_receipt": receipt,
            },
        },
    }


def try_start_customer_mutation_agent_run(
    message: str,
    *,
    runtime_context: dict[str, Any] | None = None,
    user_id: str,
    source: str | None = None,
) -> dict[str, Any] | None:
    """Resolve and stage a verified customer delete workflow from chat."""

    customer_name = classify_customer_delete_intent(
        message,
        runtime_context=runtime_context,
    )
    if not customer_name:
        return None

    from app.application import get_customer_app_service

    service = get_customer_app_service()
    query_result = service.get_all(keyword=customer_name, page=1, per_page=50) or {}
    rows = query_result.get("data") if isinstance(query_result, dict) else []
    rows = rows if isinstance(rows, list) else []
    exact = [
        row
        for row in rows
        if isinstance(row, dict)
        and str(row.get("customer_name") or row.get("unit_name") or "").strip() == customer_name
    ]

    query_node = WorkflowNode(
        node_id="verify_customer",
        tool_id="customers",
        action="query",
        params={"keyword": customer_name, "page": 1, "per_page": 50},
        risk="low",
        idempotent=True,
        description=f"精确核对客户“{customer_name}”",
    )
    nodes = [query_node]
    todo = [f"在真实客户库中精确核对“{customer_name}”"]
    target: dict[str, Any] | None = None
    if query_result.get("success") is not False and len(exact) == 1:
        target = exact[0]
        try:
            customer_id = int(target.get("id") or 0)
        except (TypeError, ValueError):
            customer_id = 0
        if customer_id > 0:
            nodes.append(
                WorkflowNode(
                    node_id="delete_customer",
                    tool_id="customers",
                    action="delete",
                    params={"id": customer_id, "force": False},
                    risk="medium",
                    idempotent=False,
                    description=f"删除客户“{customer_name}”（ID {customer_id}）",
                    depends_on=["verify_customer"],
                )
            )
            todo.extend(
                [
                    f"展示删除目标“{customer_name}”（ID {customer_id}）并等待确认",
                    "执行客户删除并返回数据库工具回执",
                ]
            )

    plan = PlanGraph(
        plan_id=f"plan_customer_delete_{uuid.uuid4().hex[:12]}",
        intent="customer_delete",
        todo_steps=todo,
        nodes=nodes,
        risk_level="medium" if len(nodes) > 1 else "low",
        metadata={
            "source": "deterministic_customer_mutation",
            "customer_name": customer_name,
            "preflight_match_count": len(exact),
            "target_snapshot": dict(target or {}),
        },
    )
    run = AgentOrchestrator().start_run_from_plan(
        user_id=user_id,
        message=message,
        plan=plan,
        runtime_context=_runtime_context(
            user_id=user_id,
            message=message,
            source=source,
            context=runtime_context,
        ),
        auto_execute=True,
    )

    if query_result.get("success") is False:
        return _query_only_payload(
            run=run,
            customer_name=customer_name,
            text=f"客户删除未执行：真实客户库查询失败（{query_result.get('message') or '未知错误'}）。",
            reason="customer_query_failed",
        )
    if not exact:
        return _query_only_payload(
            run=run,
            customer_name=customer_name,
            text=f"客户删除未执行：真实客户库中没有精确匹配“{customer_name}”。未删除任何数据。",
            reason="customer_not_found",
        )
    if len(exact) > 1:
        ids = [str(row.get("id") or "-") for row in exact[:10]]
        return _query_only_payload(
            run=run,
            customer_name=customer_name,
            text=(
                f"客户删除未执行：找到 {len(exact)} 个同名客户“{customer_name}”"
                f"（ID：{', '.join(ids)}）。请指定客户 ID。"
            ),
            reason="ambiguous_customer_name",
        )

    if run.status != "waiting_user":
        error = str(run.error or "未进入等待确认状态")
        return _query_only_payload(
            run=run,
            customer_name=customer_name,
            text=f"客户删除未执行：{error}。",
            reason="customer_delete_plan_failed",
        )

    target_id = int((target or {}).get("id") or 0)
    blocking_nodes = [step.node_id for step in run.steps if step.status == "waiting_user"]
    reason = "删除会改变真实客户数据；确认后才执行，若有关联发货记录会安全失败。"
    response_text = (
        f"已核对真实客户库，准备删除：{customer_name}（ID {target_id}）。\n"
        "当前尚未删除任何数据。请确认执行或取消；执行后会返回数据库工具回执。"
    )
    inner = {
        "run_id": run.run_id,
        "agent_run_id": run.run_id,
        "plan_id": plan.plan_id,
        "intent": plan.intent,
        "todo": plan.todo_steps,
        "blocking_nodes": blocking_nodes,
        "reason": reason,
        "approval_required": False,
        "approval_nodes": [],
        "target": {"id": target_id, "customer_name": customer_name},
    }
    from app.application.ai_chat.excel_import_policy import _enrich_confirmation_inner

    return {
        "success": True,
        "message": "等待确认",
        "response": response_text,
        "run_id": run.run_id,
        "agent_run_id": run.run_id,
        "data": {
            "text": response_text,
            "action": "workflow_confirmation_required",
            "run_id": run.run_id,
            "agent_run_id": run.run_id,
            "data": _enrich_confirmation_inner(
                inner,
                action="workflow_confirmation_required",
            ),
        },
    }


__all__ = [
    "classify_customer_delete_intent",
    "try_start_customer_mutation_agent_run",
]
