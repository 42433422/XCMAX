"""Registry visibility, graph decoration and required-parameter validation."""

from __future__ import annotations

from typing import Any

from app.application.workflow.clarification_node import build_clarify_node, needs_clarification
from app.application.workflow.types import Branch, PlanGraph, WorkflowNode, validate_plan_graph


def filter_registry_for_profile(tool_registry: dict[str, Any], profile: str) -> dict[str, Any]:
    """
    - normal：剔除 pro_only 工具与动作（普通界面走槽位/共享工具）。
    - pro_default：剔除 normal_only 工具与动作（全专业链路不暴露纯普通槽位工具）。
    """
    filtered: dict[str, Any] = {}
    for tool_id, spec in tool_registry.items():
        if not isinstance(spec, dict):
            continue
        tool_av = str(spec.get("availability") or "shared").strip().lower()
        if profile == "normal" and tool_av == "pro_only":
            continue
        if profile == "pro_default" and tool_av == "normal_only":
            continue
        actions = spec.get("actions") or {}
        if not isinstance(actions, dict):
            continue
        kept_actions: dict[str, Any] = {}
        for aname, ameta in actions.items():
            if not isinstance(ameta, dict):
                continue
            av = str(ameta.get("availability") or "shared").strip().lower()
            if profile == "normal" and av == "pro_only":
                continue
            if profile == "pro_default" and av == "normal_only":
                continue
            kept_actions[aname] = ameta
        if not kept_actions:
            continue
        new_spec = dict(spec)
        new_spec["actions"] = kept_actions
        filtered[tool_id] = new_spec
    return filtered


def apply_conditional_edges(
    plan: PlanGraph, message: str, tool_registry: dict[str, Any]
) -> PlanGraph:
    """确定性条件边规则：把"检查/查询 + 后续决策"表达为 branches。

    当前规则：计划含库存检查（query/read/check_stock）且消息带采购意图时，
    为检查节点挂上 ``{"key": "low_stock", "equals": true}`` → 采购节点 的条件边。
    """
    if any(k in message for k in ("库存", "stock", "Stock")):
        check_nodes = [
            n
            for n in plan.nodes
            if str(n.action or "").lower() in ("query", "read", "check", "check_stock")
            and "stock" in str(n.tool_id or "").lower()
        ]
        purchase_nodes = [
            n
            for n in plan.nodes
            if "purchase" in str(n.tool_id or "").lower() or "采购" in (n.description or "")
        ]
        if check_nodes and purchase_nodes:
            check = check_nodes[0]
            if not check.branches:
                check.branches.append(
                    Branch(
                        target=purchase_nodes[0].node_id,
                        condition={"key": "low_stock", "equals": True},
                    )
                )
    return plan


def apply_clarification(plan: PlanGraph, tool_registry: dict[str, Any]) -> PlanGraph:
    """确定性反问规则：写/高风险节点存在关键参数缺失或多候选歧义时，在图首部插入 clarify 节点。

    复用 ``clarification_node.needs_clarification`` 检测，并用 ``build_clarify_node``
    生成反问节点，其 ``branches`` 依据用户确认结果路由回原操作节点。
    """
    items = needs_clarification(plan, tool_registry)
    from .clarification_node import detect_erp_clarification

    items = list(items) + detect_erp_clarification(plan)
    if not items:
        return plan
    inserted: list[WorkflowNode] = []
    for item in items:
        clarify = build_clarify_node(
            item["question"],
            ambient={"target_node_id": item["node_id"], "clarification": item},
        )
        plan.nodes.insert(0, clarify)
        inserted.append(clarify)
    if validate_plan_graph(plan) is not None:
        for clarify in inserted:
            if clarify in plan.nodes:
                plan.nodes.remove(clarify)
    return plan


def validate_required_params(plan: PlanGraph, tool_registry: dict[str, Any]) -> str | None:
    """检查节点 params 是否满足 tool_registry 的 required_params。"""
    for node in plan.nodes or []:
        tool_spec = (tool_registry or {}).get(str(node.tool_id) or "")
        if not isinstance(tool_spec, dict):
            continue
        actions = tool_spec.get("actions") or {}
        if not isinstance(actions, dict):
            continue
        action_meta = actions.get(str(node.action) or "")
        if not isinstance(action_meta, dict):
            continue
        required_params = action_meta.get("required_params") or []
        if not isinstance(required_params, list):
            required_params = []
        params = node.params or {}
        for key in required_params:
            if key not in params or params.get(key) is None or str(params.get(key)).strip() == "":
                return f"节点 {node.node_id} 缺少 required_params: {key}"
    return None
