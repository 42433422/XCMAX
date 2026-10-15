"""Detect missing or ambiguous write inputs; lifecycle helpers pause and resume safely."""

from __future__ import annotations

from typing import Any

from app.services.tools_execution.registry import (
    REQUIRED_PARAMS_BY_TOOL_ACTION as _WRITE_REQUIRED_FALLBACK,
)

from . import clarification_lifecycle as _lifecycle
from .types import PlanGraph, WorkflowNode

build_clarify_node = _lifecycle.build_clarify_node
clarification_ttl_seconds = _lifecycle.clarification_ttl_seconds
entry_is_expired = _lifecycle.entry_is_expired
insert_clarify_node = _lifecycle.insert_clarify_node
make_pending_entry = _lifecycle.make_pending_entry
resolve_confirmed_target = _lifecycle.resolve_confirmed_target
sweep_expired = _lifecycle.sweep_expired


def _action_required(node: WorkflowNode, tool_registry: dict[str, Any] | None) -> list[str]:
    meta = tool_registry
    for key in (node.tool_id, "actions", node.action):
        meta = meta.get(key) if isinstance(meta, dict) else None
    if isinstance(meta, dict) and isinstance(meta.get("required_params"), list):
        return [str(x) for x in meta["required_params"]]
    return list(_WRITE_REQUIRED_FALLBACK.get((node.tool_id, node.action), []))


def _missing_fields(params: dict[str, Any], required: list[str]) -> list[str]:
    return [
        key
        for key in required
        if params.get(key) is None
        or isinstance(params.get(key), str)
        and not params[key].strip()
        or isinstance(params.get(key), list)
        and not params[key]
    ]


def _build_missing_question(node: WorkflowNode, missing: list[str]) -> str:
    return (
        f"执行 {node.tool_id}.{node.action} 前需要补充必填参数："
        f"{'、'.join(missing)}。请提供后再执行，避免误操作。"
    )


def _build_ambiguous_question(node: WorkflowNode, candidates: list[dict[str, Any]]) -> str:
    lines = [f"检测到 {node.tool_id}.{node.action} 存在多个候选目标，请确认实际要操作的对象："]
    for index, cand in enumerate(candidates[:10], start=1):
        name = str(
            cand.get("name") or cand.get("customer_name") or cand.get("unit_name") or ""
        ).strip()
        cid = str(cand.get("id") or "").strip()
        label = f"{name}（#{cid}）" if name and cid else (name or cid or f"候选{index}")
        lines.append(f"{index}. {label}")
    lines.append("请回复序号或唯一 ID 以确认目标。")
    return "\n".join(lines)


def needs_clarification(
    plan: PlanGraph,
    tool_registry: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Detect missing write inputs and ambiguous targets before execution."""
    items: list[dict[str, Any]] = []
    for node in plan.nodes or []:
        if node.tool_id == "clarify":
            continue
        if node.risk != "high" and node.idempotent:
            continue
        params = node.params or {}
        required = _action_required(node, tool_registry)

        if node.tool_id == "business_db" and node.action == "write":
            operation = str(params.get("operation") or "").strip().lower()
            payload = params.get("payload")
            if operation in {"update", "delete"} and isinstance(payload, dict):
                from app.services.tools_workflow_registered import (
                    prepare_business_db_write_target,
                )

                resolved = prepare_business_db_write_target(
                    str(params.get("entity") or ""), operation, payload
                )
                if resolved.get("success"):
                    params["payload"] = resolved["payload"]
                else:
                    candidates = list(resolved.get("candidates") or [])
                    reason = str(resolved.get("reason") or "missing_target")
                    question = str(resolved.get("message") or "请提供唯一目标后再执行。")
                    if len(candidates) > 1:
                        reason = "ambiguous_target"
                        question = _build_ambiguous_question(node, candidates)
                    items.append(
                        {
                            "node_id": node.node_id,
                            "tool_id": node.tool_id,
                            "action": node.action,
                            "reason": reason,
                            "field": "id",
                            "candidates": candidates[:20],
                            "question": question,
                        }
                    )
                    continue
        general_candidates = params.get("_candidates") or params.get("candidates")

        # 多候选歧义优先：目标 id 未解析 && 存在 >1 个候选 → 反问确认目标。
        if isinstance(general_candidates, list) and len(general_candidates) > 1:
            if not _missing_fields(params, ["id"]) and params.get("id"):
                continue
            items.append(
                {
                    "node_id": node.node_id,
                    "tool_id": node.tool_id,
                    "action": node.action,
                    "reason": "ambiguous_target",
                    "field": (required[0] if required else "target") or "id",
                    "candidates": general_candidates[:20],
                    "question": _build_ambiguous_question(node, general_candidates),
                }
            )
            continue

        missing = _missing_fields(params, required)
        from app.application.shipment_inputs import missing_shipment_call_fields

        missing += missing_shipment_call_fields(node.tool_id, node.action, params)
        missing = list(dict.fromkeys(missing))
        if (node.tool_id, node.action) == ("inventory", "stock_in"):
            from app.application.inventory_inputs import missing_stock_in_fields

            missing = missing_stock_in_fields(params)
        if node.tool_id == "sales" and node.action in {"quote", "create_order"}:
            from app.application.sales_quote_inputs import missing_quote_fields

            missing = missing_quote_fields(params)
        if missing:
            items.append(
                {
                    "node_id": node.node_id,
                    "tool_id": node.tool_id,
                    "action": node.action,
                    "reason": "missing_required",
                    "field": missing[0],
                    "missing_fields": missing,
                    "question": _build_missing_question(node, missing),
                }
            )
    return items


# 多单位换算：斤/公斤/吨/克/千克 等常见重量单位，出现多个单位字面量即视为换算歧义。
_ERP_UNIT_RE = "斤|公斤|千克|克|吨|Kg|kg|KG|g|G|件|个|箱|包|瓶|米|卷"


def detect_erp_clarification(
    plan: PlanGraph,
    *,
    user_message: str = "",
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Detect unit ambiguity, missing report/batch scope and destructive confirmations."""
    items: list[dict[str, Any]] = []
    message = str(user_message or "").strip()
    ctx = context or {}

    # 1) 多单位换算歧义
    if message:
        for node in plan.nodes or []:
            if node.tool_id == "clarify":
                continue
            if node.tool_id in ("inventory", "sales", "purchase") and node.action in (
                "stock_in",
                "stock_out",
                "transfer",
                "quote",
                "create_order",
            ):
                params = node.params or {}
                quantity = params.get("quantity") or params.get("items")
                if _has_multi_unit_text(quantity) or _has_multi_unit_text(message):
                    items.append(
                        _erp_clar(
                            node.node_id,
                            "multi_unit",
                            "单位",
                            "检测到数量涉及多个单位（斤/KG/吨等），请确认实际操作单位与换算口径后我再执行。",
                            severity="high",
                        )
                    )
                    break

    # 2) 报表口径缺失
    for node in plan.nodes or []:
        if node.tool_id == "reports" and node.action in (
            "sales_summary",
            "purchase_summary",
        ):
            params = node.params or {}
            if not params.get("start_date") or not params.get("end_date"):
                items.append(
                    _erp_clar(
                        node.node_id,
                        "report_scope",
                        "日期范围",
                        "报表口径未指定日期范围，请确认统计起止日期后我再汇总。",
                        severity="medium",
                    )
                )
            if node.action != "dashboard" and not params.get("group_by"):
                items.append(
                    _erp_clar(
                        node.node_id,
                        "report_scope",
                        "group_by",
                        "报表未指定分组口径（按产品/客户/供应商/日期），请确认后再输出。",
                        severity="low",
                    )
                )

    # 3) 冲销/盘点确认
    for node in plan.nodes or []:
        if node.tool_id in ("finance", "inventory") and node.action in (
            "journal_entry_create",
            "delete_transaction",
            "stock_out",
            "transfer",
        ):
            reversal_hint = _has_reversal_hint(message) or _has_reversal_hint(
                str(ctx.get("intent") or ctx.get("action") or "")
            )
            if reversal_hint:
                items.append(
                    _erp_clar(
                        node.node_id,
                        "reversal_confirm",
                        "确认",
                        "该操作疑似冲销/盘点/作废类改动，确认后不可撤回。请明确确认后我再执行。",
                        severity="high",
                    )
                )

    # 4) 批量操作范围
    for node in plan.nodes or []:
        if node.tool_id in ("sales", "inventory", "purchase", "business_event") and node.action in (
            "batch_delete",
            "generate_batch",
            "import_records",
            "execute_import",
        ):
            params = node.params or {}
            ids = params.get("ids") or params.get("shipments") or params.get("records")
            if isinstance(ids, list) and len(ids) > 50:
                items.append(
                    _erp_clar(
                        node.node_id,
                        "batch_scope",
                        "范围",
                        f"批量操作涉及 {len(ids)} 条记录，请确认操作范围无误后再执行。",
                        severity="high",
                    )
                )

    for node in plan.nodes or []:
        if node.tool_id == "clarify":
            continue
        # 盘点差异复审：inventory_count 未确认时澄清，避免直接调整库存
        if node.tool_id == "inventory" and node.action == "inventory_count":
            params = node.params or {}
            if not bool(params.get("confirmed", False)):
                system = params.get("system_quantity")
                actual = params.get("actual_quantity")
                if system is not None and actual is not None and float(actual) != float(system):
                    diff_desc = (
                        f"系统 {system} vs 实盘 {actual}，存在差异 {float(actual) - float(system)}"
                    )
                else:
                    diff_desc = "需确认实盘数量与差异调整"
                items.append(
                    _erp_clar(
                        node.node_id,
                        "inventory_count_diff",
                        "确认",
                        f"库存盘点操作需确认：{diff_desc}。请确认实盘数量与差异调整后再执行。",
                        severity="high",
                    )
                )
        # 凭证冲销确认：journal_entry_reverse 执行前二次确认（不可逆）
        if node.tool_id == "finance" and node.action == "journal_entry_reverse":
            items.append(
                _erp_clar(
                    node.node_id,
                    "journal_entry_reverse",
                    "确认",
                    "凭证冲销操作不可逆，确认后将生成反向分录并标记原凭证已冲销。请明确确认后我再执行。",
                    severity="high",
                )
            )
        # 信用额度超限：设置额度低于已用额度时澄清
        if node.tool_id == "customers" and node.action == "set_credit_limit":
            params = node.params or {}
            credit_limit = params.get("credit_limit")
            credit_used = params.get("credit_used", 0)
            try:
                limit_num = float(credit_limit or 0.0)
                used_num = float(credit_used)
            except (TypeError, ValueError):
                limit_num, used_num = None, None
            if limit_num is not None and used_num is not None and used_num > limit_num:
                items.append(
                    _erp_clar(
                        node.node_id,
                        "credit_limit_exceed",
                        "确认",
                        f"设置信用额度 {limit_num} 低于当前已用额度 {used_num}，是否仍要保存？",
                        severity="high",
                    )
                )
    return items


def _erp_clar(
    node_id: str, reason: str, field: str, question: str, severity: str
) -> dict[str, Any]:
    return {
        "node_id": node_id or f"erp_clarify_{why_uuid()}",
        "reason": reason,
        "field": field,
        "question": question,
        "severity": severity,
    }


def _has_multi_unit_text(value: Any) -> bool:
    """Detect quantity-and-unit expressions."""
    import re

    text = str(value or "")
    if not text:
        return False
    # 数量+单位：数字（含小数）后紧跟单位字面量
    quantity_unit = re.compile(rf"\d+(\.\d+)?\s*({_ERP_UNIT_RE})")
    if quantity_unit.search(text):
        return True
    # 多个不同单位字面量同时出现
    raw_units = re.findall(rf"({_ERP_UNIT_RE})", text)
    return len({u.lower() for u in raw_units}) >= 2


def _has_reversal_hint(text: str) -> bool:
    if not text:
        return False
    hints = ("冲销", "红冲", "作废", "盘点", "调整", "反记", "reversal", "void", "revert")
    return any(h in text for h in hints)


def why_uuid() -> str:
    import uuid as _uuid

    return _uuid.uuid4().hex[:8]


__all__ = [
    "build_clarify_node",
    "clarification_ttl_seconds",
    "detect_erp_clarification",
    "entry_is_expired",
    "insert_clarify_node",
    "make_pending_entry",
    "needs_clarification",
    "resolve_confirmed_target",
    "sweep_expired",
]
