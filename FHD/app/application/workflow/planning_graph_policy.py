"""Registry visibility, graph decoration and required-parameter validation."""

from __future__ import annotations

from typing import Any

from app.application.workflow.clarification_node import build_clarify_node, needs_clarification
from app.application.workflow.workflow_types import (
    PlanGraph,
    WorkflowNode,
    validate_plan_graph,
)


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


def apply_clarification(
    plan: PlanGraph,
    tool_registry: dict[str, Any],
    *,
    user_message: str = "",
    context: dict[str, Any] | None = None,
) -> PlanGraph:
    """确定性反问规则：写/高风险节点存在关键参数缺失或多候选歧义时，在图首部插入 clarify 节点。

    复用 ``clarification_node.needs_clarification`` 检测，并用 ``build_clarify_node``
    生成反问节点，其 ``branches`` 依据用户确认结果路由回原操作节点。
    """
    items = needs_clarification(plan, tool_registry)
    from .clarification_node import detect_erp_clarification

    items = list(items) + detect_erp_clarification(plan, user_message=user_message, context=context)
    existing_clarifications: dict[str, list[WorkflowNode]] = {}
    for node in plan.nodes:
        target_id = str((node.params or {}).get("target_node_id") or "")
        if node.tool_id == "clarify" and node.action == "ask" and target_id:
            existing_clarifications.setdefault(target_id, []).append(node)
    used_existing: set[str] = set()
    remaining: list[dict[str, Any]] = []
    for item in items:
        target_id = str(item.get("node_id") or "")
        existing = next(
            (
                node
                for node in existing_clarifications.get(target_id, [])
                if node.node_id not in used_existing
            ),
            None,
        )
        if existing is None:
            remaining.append(item)
            continue
        used_existing.add(existing.node_id)
        params = dict(existing.params or {})
        detail = dict(item)
        detail["question"] = str(params.get("question") or item.get("question") or "")
        params["question"] = detail["question"]
        params["clarification"] = detail
        existing.params = params
    items = remaining
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
    """Preflight every node against the current registry before graph execution."""
    clarification_by_target: dict[str, dict[str, Any]] = {}
    node_by_id = {node.node_id: node for node in plan.nodes or []}
    for candidate in plan.nodes or []:
        if candidate.tool_id != "clarify" or candidate.action != "ask":
            continue
        params = candidate.params or {}
        target_id = str(params.get("target_node_id") or "")
        detail = params.get("clarification")
        if target_id:
            target = node_by_id.get(target_id)
            if target is None or not any(
                branch.target == target_id
                and (branch.condition or {}).get("key") == "answer_confirmed"
                and (branch.condition or {}).get("equals") is True
                for branch in candidate.branches or []
            ):
                return f"澄清节点 {candidate.node_id} 未安全绑定到目标节点 {target_id}"
        if target_id and isinstance(detail, dict):
            current = clarification_by_target.get(target_id)
            if current is None or (
                current.get("reason") != "missing_required"
                and detail.get("reason") == "missing_required"
            ):
                clarification_by_target[target_id] = detail
    for node in plan.nodes or []:
        if node.tool_id == "clarify" and node.action == "ask":
            if not str((node.params or {}).get("question") or "").strip():
                return f"澄清节点 {node.node_id} 缺少 question"
            node.risk, node.idempotent = "low", True
            continue
        tool_spec = (tool_registry or {}).get(str(node.tool_id) or "")
        if not isinstance(tool_spec, dict):
            return f"节点 {node.node_id} 使用未授权工具: {node.tool_id}"
        actions = tool_spec.get("actions") or {}
        if not isinstance(actions, dict):
            return f"工具 {node.tool_id} 没有可用动作"
        action_meta = actions.get(str(node.action) or "")
        if not isinstance(action_meta, dict):
            return f"节点 {node.node_id} 使用未授权动作: {node.tool_id}.{node.action}"
        from app.application.workflow.workflow_types import normalize_workflow_risk

        node.risk = normalize_workflow_risk(str(action_meta.get("risk") or "high"))
        node.idempotent = bool(action_meta.get("idempotent", False))
        required_params = action_meta.get("required_params") or []
        if not isinstance(required_params, list):
            required_params = []
        params = node.params or {}
        clarification = clarification_by_target.get(node.node_id) or {}
        allowed_missing: set[str] = set()
        if clarification.get("reason") == "missing_required":
            missing_fields = clarification.get("missing_fields")
            if isinstance(missing_fields, list):
                allowed_missing.update(
                    str(value)
                    for value in missing_fields
                    if isinstance(value, (str, int)) and str(value).strip()
                )
        # Ambiguous target confirmation also supplies the required identifier.
        # Permit only the exact field named by the server-created clarification;
        # all other required fields remain subject to normal plan validation.
        if clarification.get("reason") == "ambiguous_target":
            field = clarification.get("field")
            if isinstance(field, (str, int)) and str(field).strip():
                allowed_missing.add(str(field))
        from app.application.agent_orchestrator.param_references import (
            validate_plan_references,
        )

        reference_error = validate_plan_references(params, set(node.depends_on or []))
        if reference_error:
            return f"节点 {node.node_id} 参数预检失败：{reference_error}"
        for key in required_params:
            if key not in params or params.get(key) is None or str(params.get(key)).strip() == "":
                if str(key) in allowed_missing:
                    continue
                return f"节点 {node.node_id} 缺少 required_params: {key}"
        from app.application.agent_orchestrator.tool_spec import validate_tool_call

        validation = validate_tool_call(
            node.tool_id,
            node.action,
            params,
            allow_references_from=set(node.depends_on or []),
            allow_missing_fields=allowed_missing,
        )
        if not validation.ok:
            return f"节点 {node.node_id} 未通过工具参数预检：{validation.message}"
    return None
