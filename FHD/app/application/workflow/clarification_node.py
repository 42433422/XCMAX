"""Detect missing or ambiguous tool inputs; lifecycle helpers pause and resume safely."""

from __future__ import annotations

from typing import Any

from app.services.tools_execution.registry import (
    REQUIRED_PARAMS_BY_TOOL_ACTION as _WRITE_REQUIRED_FALLBACK,
)

from . import clarification_lifecycle as _lifecycle
from .clarification_inputs import action_input_metadata, input_field_schema, missing_tool_fields
from .workflow_types import PlanGraph, WorkflowNode

build_clarify_node = _lifecycle.build_clarify_node
clarification_ttl_seconds = _lifecycle.clarification_ttl_seconds
entry_is_expired = _lifecycle.entry_is_expired
insert_clarify_node = _lifecycle.insert_clarify_node
make_pending_entry = _lifecycle.make_pending_entry
resolve_confirmed_target = _lifecycle.resolve_confirmed_target
sweep_expired = _lifecycle.sweep_expired


def _action_metadata(node: WorkflowNode, tool_registry: dict[str, Any] | None) -> dict[str, Any]:
    meta = tool_registry
    for key in (node.tool_id, "actions", node.action):
        meta = meta.get(key) if isinstance(meta, dict) else None
    meta = (
        meta
        if isinstance(meta, dict)
        else {
            "required_params": list(_WRITE_REQUIRED_FALLBACK.get((node.tool_id, node.action), []))
        }
    )
    return action_input_metadata(node.tool_id, node.action, meta)


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


def _build_missing_question(node: WorkflowNode, missing: list[str], meta: dict[str, Any]) -> str:
    labels = []
    for key in missing:
        field = input_field_schema(meta.get("input_schema") or {}, key)
        label = str(field.get("title") or field.get("description") or key)
        if key.endswith(".tin_spec"):
            label = "计量单位和每件/每桶规格"
        parts = key.split(".")
        if len(parts) > 1 and parts[-2].isdigit():
            label = f"第 {int(parts[-2]) + 1} 项的{label}"
        labels.append(label)
    action = node.description or meta.get("description") or "这项任务"
    alternatives = "；可替代字段任选一种填写" if meta.get("required_any") else ""
    return f"继续{action}前，请补充：{'、'.join(labels)}{alternatives}。"


def _build_ambiguous_question(node: WorkflowNode, candidates: list[dict[str, Any]]) -> str:
    lines = [f"检测到 {node.tool_id}.{node.action} 存在多个候选目标，请确认实际要操作的对象："]
    for index, cand in enumerate(candidates[:20], start=1):
        name = str(
            cand.get("name")
            or cand.get("customer_name")
            or cand.get("unit_name")
            or cand.get("product_name")
            or cand.get("material_name")
            or ""
        ).strip()
        cid = str(cand.get("id") or "").strip()
        label = f"{name}（#{cid}）" if name and cid else (name or cid or f"候选{index}")
        details = " / ".join(
            str(cand[key])
            for key in ("model_number", "specification", "contact_person", "address")
            if cand.get(key)
        )
        if details:
            label += f" — {details}"
        lines.append(f"{index}. {label}")
    lines.append("请回复「第几个」、唯一 ID（如 ID 123）或能区分对象的名称/属性。")
    return "\n".join(lines)


def _resolve_clear_dataset_target(
    node: WorkflowNode,
    params: dict[str, Any],
    required: list[str],
    context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """清空知识库时从会话上下文解析目标空间，避免向用户索要内部 dataset_id。"""
    if "dataset_id" not in required or str(params.get("dataset_id") or "").strip():
        return None
    raw_ids = (context or {}).get("chat_clearable_dataset_ids") or []
    ids = [str(item).strip() for item in raw_ids if str(item).strip()]
    if len(ids) == 1:
        params["dataset_id"] = ids[0]
        return None
    if len(ids) > 1:
        return {
            "node_id": node.node_id,
            "tool_id": node.tool_id,
            "action": node.action,
            "reason": "missing_required",
            "field": "dataset_id",
            "missing_fields": ["dataset_id"],
            "question": (
                "要清空哪个知识空间？可选："
                f"{'、'.join(ids)}。请回复空间名称后再执行，避免误删其他空间。"
            ),
        }
    return {
        "node_id": node.node_id,
        "tool_id": node.tool_id,
        "action": node.action,
        "reason": "missing_required",
        "field": "dataset_id",
        "missing_fields": ["dataset_id"],
        "question": "当前没有可清空的知识库空间。如需清空，请先在知识库页面确认空间名称。",
    }


def needs_clarification(
    plan: PlanGraph,
    tool_registry: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Detect missing tool inputs and ambiguous targets before execution."""
    items: list[dict[str, Any]] = []
    for node in plan.nodes or []:
        if node.tool_id == "clarify":
            continue
        params = node.params or {}
        meta = _action_metadata(node, tool_registry)
        required = (
            meta.get("required_params") or (meta.get("input_schema") or {}).get("required") or []
        )

        if (node.tool_id, node.action) == ("dataset_rag", "clear_dataset"):
            resolved = _resolve_clear_dataset_target(node, params, required, context)
            if resolved is not None:
                items.append(resolved)
                continue
            if not _missing_fields(params, required):
                continue

        if node.tool_id == "business_db" and node.action == "write":
            operation = str(params.get("operation") or "").strip().lower()
            payload = params.get("payload")
            if operation in {"update", "delete"} and isinstance(payload, dict):
                from app.domain.shared_services.tools_workflow_registered import (
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
        general_candidates = params.get("_candidates") or params.get("candidates")

        # 多候选歧义优先：目标 id 未解析 && 存在 >1 个候选 → 反问确认目标。
        ambiguous = (
            isinstance(general_candidates, list)
            and len(general_candidates) > 1
            and _missing_fields(params, ["id"])
        )
        if ambiguous and isinstance(general_candidates, list):
            items.append(
                {
                    "node_id": node.node_id,
                    "tool_id": node.tool_id,
                    "action": node.action,
                    "reason": "ambiguous_target",
                    "field": "id",
                    "candidates": general_candidates[:20],
                    "question": _build_ambiguous_question(node, general_candidates),
                }
            )

        missing = missing_tool_fields(node.tool_id, node.action, params, meta)
        if ambiguous:
            missing = [key for key in missing if key != "id"]
        if missing:
            items.append(
                {
                    "node_id": node.node_id,
                    "tool_id": node.tool_id,
                    "action": node.action,
                    "reason": "missing_required",
                    "field": missing[0],
                    "missing_fields": missing,
                    "question": _build_missing_question(node, missing, meta),
                }
            )
    return items


# Numeric quantity tokens only; names and unrelated clauses are not unit evidence.
_ERP_UNIT_RE = (
    r"(?<![A-Za-z\d.])\d+(?:\.\d+)?\s*(公斤|千克|kg|斤|吨|克|g|件|个|箱|包|瓶|米|卷|桶)(?![A-Za-z])"
)


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

    # 1) Only compare quantities belonging to the same task/item. A whole-turn
    # fallback is safe only for a single operation without a structured item list.
    operations = [node for node in plan.nodes or [] if node.tool_id != "clarify"]
    for node in operations:
        if node.tool_id in ("inventory", "sales", "purchase") and node.action in (
            "stock_in",
            "stock_out",
            "transfer",
            "quote",
            "create_order",
        ):
            params = node.params or {}
            rows = params.get("items")
            quantities = (
                [item.get("quantity") for item in rows if isinstance(item, dict)]
                if isinstance(rows, list)
                else [params.get("quantity")]
            )
            ambiguous = any(_has_multi_unit_text(quantity) for quantity in quantities)
            if not isinstance(rows, list) and len(operations) == 1:
                ambiguous = ambiguous or _has_multi_unit_text(message)
            if ambiguous:
                items.append(
                    _erp_clar(
                        node.node_id,
                        "multi_unit",
                        "单位",
                        "检测到数量涉及多个单位（斤/KG/吨等），请确认实际操作单位与换算口径后我再执行。",
                        severity="high",
                    )
                )

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
    # A single stated unit is concrete input, not ambiguity. Require at least two
    # distinct unit tokens before asking the user to choose a conversion basis.
    raw_units = re.findall(_ERP_UNIT_RE, text, flags=re.IGNORECASE)
    aliases = {"公斤": "kg", "千克": "kg", "克": "g"}
    return len({aliases.get(unit.lower(), unit.lower()) for unit in raw_units}) >= 2


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
