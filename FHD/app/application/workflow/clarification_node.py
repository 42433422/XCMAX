"""反问澄清门控（clarification gate）：写/高风险操作参数缺失或歧义时先反问，待用户确认后再执行。

对标 MODstore ``retort_clarification_gate`` 与 LangGraph ``human-in-the-loop`` interrupt：

- 写/高风险节点（``risk == "high"`` 或非幂等）若必填参数缺失，或多候选目标歧义（如同一客户
  存在多个同名候选），则规划器/服务侧先插入一个"反问节点"。
- 反问节点执行时**不调用业务工具**，仅产出 ``output`` 含 ``requires_confirmation=true`` 与
  ``question``，从而暂停工作流（等价 interrupt）。
- 用户回复后，服务侧用确认答案丰富目标节点参数，再经条件边（``branches`` 依据
  ``answer_confirmed``）路由回原操作节点继续执行。
- TTL 防堆积：过期未答的澄清会话被自动取消，避免积压队列。

本模块为自包含实现，仅依赖 ``app.application.workflow.types`` 的 ``WorkflowNode``/``Branch``。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from .types import Branch, PlanGraph, WorkflowNode

# 写/高风险节点必填参数回退表（与 services/tools_execution/registry REQUIRED_PARAMS 对齐，
# 规避依赖完整 registry 的耦合；调用方可传 tool_registry 覆盖，见 needs_clarification）。
_WRITE_REQUIRED_FALLBACK: dict[tuple[str, str], list[str]] = {
    ("customers", "delete"): ["id"],
    ("customers", "batch_delete"): ["ids"],
    ("customers", "update"): ["id"],
    ("products", "delete"): ["id"],
    ("products", "update"): ["id"],
    ("products", "batch_delete"): ["ids"],
    ("materials", "delete"): ["id"],
    ("materials", "update"): ["id"],
    ("shipment_records", "delete"): ["id"],
    ("shipment_records", "update"): ["id"],
    ("shipment_orders", "delete"): ["id"],
    ("finance", "delete_transaction"): ["transaction_id"],
    ("finance", "update_transaction"): ["transaction_id"],
    ("document_template", "delete"): ["id"],
    ("document_template", "update"): ["id"],
    ("inventory", "transfer"): [
        "product_id",
        "from_warehouse_id",
        "to_warehouse_id",
        "quantity",
    ],
    ("inventory", "stock_in"): ["product_id", "warehouse_id", "quantity"],
    ("inventory", "stock_out"): ["product_id", "warehouse_id", "quantity"],
    ("business_db", "write"): ["entity", "operation", "payload"],
    # ERP 工具（吸收 Odoo 18，Task 5/6）
    ("sales", "quote"): ["customer_id", "items"],
    ("sales", "confirm"): ["order_id"],
    ("sales", "deliver"): ["order_id"],
    ("sales", "invoice"): ["order_id"],
    ("sales", "payment"): ["order_id", "amount"],
    ("sales", "cancel"): ["order_id"],
    ("finance", "journal_entry_create"): ["lines"],
}

# 澄清会话 TTL（秒），可通过环境变量覆盖。
_DEFAULT_TTL_SECONDS = 1800


def clarification_ttl_seconds() -> int:
    import os

    try:
        return max(
            30, int(os.environ.get("XCAGI_CLARIFICATION_TTL_SECONDS") or str(_DEFAULT_TTL_SECONDS))
        )
    except ValueError:
        return _DEFAULT_TTL_SECONDS


def _is_write_or_high_risk(node: WorkflowNode) -> bool:
    return node.risk == "high" or not node.idempotent


def _action_required(node: WorkflowNode, tool_registry: dict[str, Any] | None) -> list[str]:
    """从 tool_registry 的动作元信息取 required_params；缺失时回退到本地表。"""
    if isinstance(tool_registry, dict):
        spec = tool_registry.get(node.tool_id)
        if isinstance(spec, dict):
            actions = spec.get("actions")
            if isinstance(actions, dict):
                meta = actions.get(node.action)
                if isinstance(meta, dict) and isinstance(meta.get("required_params"), list):
                    return [str(x) for x in meta["required_params"]]
    return list(_WRITE_REQUIRED_FALLBACK.get((node.tool_id, node.action), []))


def _missing_fields(params: dict[str, Any], required: list[str]) -> list[str]:
    missing = []
    for key in required:
        value = params.get(key)
        if value is None:
            missing.append(key)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(key)
            continue
        if isinstance(value, list) and len(value) == 0:
            missing.append(key)
            continue
    return missing


def _first_required(node: WorkflowNode, required: list[str]) -> str:
    return required[0] if required else "target"


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
    """对写/高风险节点检测"必填缺失 / 多候选歧义"，返回需澄清的字段/问题列表。

    返回空列表表示无需澄清；每个元素为澄清描述：
    ``node_id`` / ``tool_id`` / ``action`` / ``reason``（missing_required | ambiguous_target）
    / ``field`` / ``question`` / 可选 ``candidates`` / ``missing_fields``。
    """
    items: list[dict[str, Any]] = []
    for node in plan.nodes or []:
        if node.tool_id == "clarify":
            continue
        if not _is_write_or_high_risk(node):
            continue
        params = node.params or {}
        required = _action_required(node, tool_registry)
        candidates = params.get("_candidates") or params.get("candidates")

        # 多候选歧义优先：目标 id 未解析 && 存在 >1 个候选 → 反问确认目标。
        if isinstance(candidates, list) and len(candidates) > 1:
            if not _missing_fields(params, ["id"]) and params.get("id"):
                continue
            items.append(
                {
                    "node_id": node.node_id,
                    "tool_id": node.tool_id,
                    "action": node.action,
                    "reason": "ambiguous_target",
                    "field": _first_required(node, required) or "id",
                    "candidates": candidates[:20],
                    "question": _build_ambiguous_question(node, candidates),
                }
            )
            continue

        missing = _missing_fields(params, required)
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


def build_clarify_node(
    question: str,
    ambient: dict[str, Any] | None = None,
) -> WorkflowNode:
    """生成一个"反问节点"。

    反问节点 ``tool_id="clarify"``、``action="ask"``，执行时引擎不调用业务工具，仅产出
    ``requires_confirmation=true`` 与 ``question`` 从而暂停工作流（interrupt）。``branches``
    依据用户后续消息中确认的答案（output 的 ``answer_confirmed``）路由到原操作节点
    （``target_node_id``）；未确认时经 ``next``（默认 None）正常结束，屏蔽写节点。

    ``ambient`` 支持：``node_id`` / ``target_node_id`` / ``answer_key`` / ``cancel_node_id``。
    """
    ambient = ambient or {}
    node_id = str(ambient.get("node_id") or f"clarify_{uuid.uuid4().hex[:8]}")
    target = str(ambient.get("target_node_id") or "")
    return WorkflowNode(
        node_id=node_id,
        tool_id="clarify",
        action="ask",
        params={
            "question": str(question or ""),
            "answer_key": str(ambient.get("answer_key") or "confirmed"),
            "target_node_id": target,
        },
        risk="low",
        idempotent=True,
        description="反问澄清：写/高风险操作参数缺失或歧义，待用户确认后再继续",
        branches=[Branch(target=target, condition={"key": "answer_confirmed", "equals": True})],
        next=ambient.get("cancel_node_id"),
    )


def insert_clarify_node(
    plan: PlanGraph,
    clarify_node: WorkflowNode,
) -> None:
    """将反问节点追加到计划节点列表（幂等：已存在同名节点则不重复插入）。"""
    if any(n.node_id == clarify_node.node_id for n in plan.nodes):
        return
    plan.nodes.append(clarify_node)


# ---------------------------------------------------------------------------
# TTL 防堆积（澄清会话生命周期）
# ---------------------------------------------------------------------------


def entry_is_expired(entry: dict[str, Any] | None, now: float | None = None) -> bool:
    """判断一条"澄清待确认"记录是否已过期（TTL 后自动取消）。"""
    if not isinstance(entry, dict):
        return False
    if entry.get("kind") != "clarification":
        return False
    now = time.time() if now is None else now
    try:
        created = float(entry.get("created_at") or 0)
    except (TypeError, ValueError):
        created = 0.0
    try:
        ttl = float(entry.get("ttl_seconds") or clarification_ttl_seconds())
    except (TypeError, ValueError):
        ttl = float(clarification_ttl_seconds())
    return created > 0 and (now - created) > ttl


def sweep_expired(entries: dict[str, Any], now: float | None = None) -> list[str]:
    """扫描并移除所有过期的澄清待确认记录；返回被移除的 user_id 列表（防堆积）。"""
    now = time.time() if now is None else now
    expired: list[str] = []
    for uid, entry in list(entries.items()):
        if entry_is_expired(entry, now):
            expired.append(str(uid))
            entries.pop(uid, None)
    return expired


def make_pending_entry(
    *,
    plan: PlanGraph,
    runtime_context: dict[str, Any],
    thinking_steps: str,
    clarification: dict[str, Any],
    clarify_node_id: str,
    target_node_id: str,
    now: float | None = None,
) -> dict[str, Any]:
    """构造一条与 ai_chat_app_service._pending_workflows 同构的"澄清待确认"记录。"""
    return {
        "plan": plan,
        "runtime_context": runtime_context,
        "pending_id": uuid.uuid4().hex,
        "thinking_steps": thinking_steps,
        "kind": "clarification",
        "clarify_node_id": clarify_node_id,
        "target_node_id": target_node_id,
        "clarification": clarification,
        "created_at": time.time() if now is None else now,
        "ttl_seconds": clarification_ttl_seconds(),
        "approval_required": False,
        "approval_nodes": [],
    }


def resolve_confirmed_target(
    message: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """从用户确认消息解析唯一目标参数（如 ``{"id": "cust_123"}``）；无法唯一确定返回 None。

    支持：唯一 ID 精确匹配、候选名称匹配、序号（候选列表第 N 个）。
    """
    if not candidates:
        return None
    text = str(message or "").strip()
    if not text:
        return None

    # 1) 唯一 ID 精确匹配
    for cand in candidates:
        cid = str(cand.get("id") or "").strip()
        if cid and cid == text:
            return {"id": cid}

    # 2) 名称匹配（含别名）
    for cand in candidates:
        name = str(
            cand.get("name") or cand.get("customer_name") or cand.get("unit_name") or ""
        ).strip()
        if name and (name == text or name in text or text in name):
            return {"id": str(cand.get("id") or "")}

    # 3) 序号匹配（候选列表第 N 个）
    if text.isdigit():
        idx = int(text)
        if len(candidates) >= 1 and idx <= len(candidates):
            cand = candidates[idx - 1]
            return {"id": str(cand.get("id") or "")}

    return None


# ---------------------------------------------------------------------------
# ERP 业务澄清（吸收 Odoo 18 业务深度，Task 6）
# ---------------------------------------------------------------------------

# 多单位换算：斤/公斤/吨/克/千克 等常见重量单位，出现多个单位字面量即视为换算歧义。
_ERP_UNIT_RE = "斤|公斤|千克|克|吨|Kg|kg|KG|g|G|件|个|箱|包|瓶|米|卷"


def detect_erp_clarification(
    plan: PlanGraph,
    *,
    user_message: str = "",
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """对 ERP 业务场景做"业务澄清"检测，返回需反问的描述列表。

    覆盖（吸收 Odoo 18 业务深度）：
    - ``multi_unit`` 多单位换算歧义：同一数量出现多个单位字面量（如"出 500 斤"应确认是
      斤/KG 还是按产品多单位换算），不直接执行。
    - ``report_scope`` 报表口径缺失：销售/库存/采购报表未给日期范围或分组口径。
    - ``reversal_confirm`` 冲销/盘点确认：冲销凭证、盘点调整、作废等破坏性操作需二次确认。
    - ``batch_scope`` 批量操作范围：批量删除/导入未指明范围或数量过大时需确认。

    返回元素：``node_id`` / ``reason`` / ``field`` / ``question`` / ``severity``。
    复用 ``build_clarify_node`` 与 TTL 防堆积（调用方插入反问节点与 pending entry）。
    """
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
            "inventory_summary",
            "purchase_summary",
            "dashboard",
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

    # 5) ERP 业务确认（Task 6：盘点差异复审 / 凭证冲销确认 / 信用额度超限）
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
                limit_num = float(credit_limit)
                used_num = float(credit_used)
            except (TypeError, ValueError):
                limit_num, used_num = None, None
            if limit_num is not None and used_num > limit_num:
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
    """判断文本是否含"数量+单位"（斤/KG/吨等）的量词表达。

    出现数字后紧跟单位（如"500 斤"、"出 500 斤"）即视为存在单位换算歧义——Agent 需确认
    实际操作单位与换算口径，避免把斤当公斤执行。多个单位字面量同样命中。
    """
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
