"""Model-facing ERP capabilities from the approval-gated workflow registry."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from app.application.workflow.workflow_types import normalize_workflow_risk
from app.utils.json_safe import json_safe
from app.utils.operational_errors import RECOVERABLE_ERRORS

ERP_CAPABILITY_TOOL_NAME = "execute_erp_capability"


def _workflow_registry() -> dict[str, Any]:
    from resources.config.risk_actions_loader import get_workflow_tools_from_registry

    registry = get_workflow_tools_from_registry()
    return registry if isinstance(registry, dict) else {}


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def _capability_catalog_lines(registry: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for tool_id in sorted(registry):
        tool = registry.get(tool_id)
        tool_data: dict[str, Any] = tool if isinstance(tool, dict) else {}
        actions = tool_data.get("actions")
        if not isinstance(actions, dict):
            continue
        action_bits = []
        for action, spec in sorted(actions.items()):
            risk = str((spec or {}).get("risk") or "low").lower()
            action_bits.append(f"{action}({risk})")
        description = str(tool_data.get("description") or "").strip()
        suffix = f" — {description}" if description else ""
        lines.append(f"{tool_id}: {', '.join(action_bits)}{suffix}")
    return lines


def registered_capability_catalog() -> dict[str, Any]:
    """Return a compact, model-safe view of every registered product capability."""

    registry = _workflow_registry()
    capabilities: list[dict[str, Any]] = []
    for tool_id in sorted(registry):
        tool = registry.get(tool_id)
        tool_data: dict[str, Any] = tool if isinstance(tool, dict) else {}
        actions = tool_data.get("actions")
        if not isinstance(actions, dict):
            continue
        capabilities.append(
            {
                "tool_id": tool_id,
                "description": str(tool_data.get("description") or ""),
                "actions": {
                    str(action): {
                        "risk": str((spec or {}).get("risk") or "low").lower(),
                        "required_params": list((spec or {}).get("required_params") or []),
                        "idempotent": bool((spec or {}).get("idempotent", False)),
                    }
                    for action, spec in sorted(actions.items())
                    if isinstance(spec, dict)
                },
            }
        )
    return {
        "capability_count": len(capabilities),
        "capability_ids": [row["tool_id"] for row in capabilities],
        "capabilities": capabilities,
    }


def build_registered_capability_tool_definition() -> dict[str, Any]:
    """Build the single model tool which covers all registered ERP functions."""

    registry = _workflow_registry()
    catalog = _capability_catalog_lines(registry)
    catalog_text = "\n".join(catalog)
    return {
        "type": "function",
        "function": {
            "name": ERP_CAPABILITY_TOOL_NAME,
            "description": (
                "执行已登记的 ERP 产品能力。只能使用下方 capability catalog 中的 "
                "tool_id 与 action；params 必须只包含该动作需要的业务参数。低风险动作会执行，"
                "中高风险动作会沿用产品审批流；不得把内部 HTTP、账号鉴权、权限管理或系统密钥 "
                "当作 capability 调用。调用前要确认用户意图，执行后依据返回的 success 与 approval "
                "结果如实回复。\n\nCapability catalog:\n"
                f"{catalog_text}"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_id": {
                        "type": "string",
                        "enum": sorted(registry),
                        "description": "ERP 产品能力 ID。",
                    },
                    "action": {
                        "type": "string",
                        "description": "所选 tool_id 支持的动作；精确名称见 capability catalog。",
                    },
                    "params": {
                        "type": "object",
                        "description": "该动作的业务参数。不会接受 _runtime_context 或鉴权注入字段。",
                        "additionalProperties": True,
                    },
                },
                "required": ["tool_id", "action"],
            },
        },
    }


def extend_workflow_tool_registry(registry: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append the product capability tool without making a second hard-coded catalog."""

    try:
        return [*registry, build_registered_capability_tool_definition()]
    except RECOVERABLE_ERRORS:
        return registry


def resolve_registered_capability_call(args: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and normalize one model tool call against the SSOT registry."""

    payload = dict(args or {})
    tool_id = str(payload.get("tool_id") or payload.get("capability_id") or "").strip()
    params = payload.get("params")
    if not isinstance(params, dict):
        return {"success": False, "error": "params 必须是 JSON 对象"}
    params = dict(params)
    # Runtime context and authorization are injected only by the host workflow,
    # never accepted from a model-generated tool argument.
    params.pop("_runtime_context", None)
    registry = _workflow_registry()
    tool = registry.get(tool_id)
    if not isinstance(tool, dict):
        return {
            "success": False,
            "error": f"未登记的 ERP capability: {tool_id or '(empty)'}",
            "available_tool_ids": sorted(registry),
        }

    from app.services.tools_execution.registry import _normalize_action

    action = _normalize_action(str(payload.get("action") or ""), params)
    actions = tool.get("actions")
    spec = actions.get(action) if isinstance(actions, dict) else None
    if not isinstance(spec, dict):
        return {
            "success": False,
            "error": f"未登记的 capability action: {tool_id}.{action or '(empty)'}",
            "available_actions": sorted(actions) if isinstance(actions, dict) else [],
        }
    required = [str(key) for key in spec.get("required_params") or [] if str(key)]
    missing = [key for key in required if not _has_value(params.get(key))]
    if missing:
        return {
            "success": False,
            "error": f"缺少参数：{', '.join(missing)}",
            "tool_id": tool_id,
            "action": action,
            "required_params": required,
        }
    if (tool_id, action) == ("inventory", "stock_in"):
        from app.domain.app_pure.inventory_inputs import validate_stock_in_request

        try:
            validate_stock_in_request(params)
        except ValueError as exc:
            return {"success": False, "error": str(exc), "tool_id": tool_id, "action": action}
    if tool_id == "sales" and action in {"quote", "create_order"}:
        from app.application.sales_quote_inputs import validated_quote_request

        try:
            validated_quote_request(params)
        except ValueError as exc:
            return {"success": False, "error": str(exc), "tool_id": tool_id, "action": action}
    return {
        "success": True,
        "tool_id": tool_id,
        "action": action,
        "params": params,
        "risk": str(spec.get("risk") or "low").lower(),
        "idempotent": bool(spec.get("idempotent", False)),
        "required_params": required,
        "description": str(tool.get("description") or ""),
    }


def execute_registered_capability(
    args: dict[str, Any] | None,
    *,
    workspace_root: str | None = None,
    runtime_context: dict[str, Any] | None = None,
) -> str:
    """Execute a registered product operation through risk and approval gates."""

    resolved = resolve_registered_capability_call(args)
    if not resolved.get("success"):
        return json.dumps(resolved, ensure_ascii=False)

    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    tool_id = str(resolved["tool_id"])
    action = str(resolved["action"])
    params = dict(resolved["params"])
    context: dict[str, Any] = dict(runtime_context or {})
    approval_request_id = None
    if tool_id in {"customers", "products"} and action == "batch_delete":
        from app.application.agent_orchestrator.tool_permission import actor_tool_denial
        from app.infrastructure.auth.agent_mod_scope import _bound_actor
        from app.infrastructure.tenant_scope import current_tenant_id

        try:
            actor = _bound_actor(context)
            tenant = current_tenant_id()
            key = str(context.get("idempotency_key") or context.get("turn_id") or "").strip()
            if (
                not tenant
                or str(tenant) != str(context.get("tenant_id"))
                or not key
                or actor_tool_denial(tool_id, action, context) is not None
            ):
                raise ValueError("删除操作缺少有效身份、权限或请求标识")
            identity = json.dumps([tenant, str(actor.id), key, tool_id, action], ensure_ascii=False)
            approval_request_id = hashlib.sha256(identity.encode()).hexdigest()
        except RECOVERABLE_ERRORS:
            return json.dumps(
                {"success": False, "error": "删除操作身份或请求标识无效"}, ensure_ascii=False
            )
    plan_id = f"erp-capability-{tool_id}-{action}-{uuid.uuid4().hex[:12]}"
    if approval_request_id:
        plan_id = f"erp-capability-{approval_request_id}"
    plan = PlanGraph(
        plan_id=plan_id,
        intent=f"ERP Agent 请求执行 {tool_id}.{action}",
        todo_steps=[f"执行已登记产品能力 {tool_id}.{action}"],
        nodes=[
            WorkflowNode(
                node_id="registered_capability",
                tool_id=tool_id,
                action=action,
                params=params,
                risk=normalize_workflow_risk(str(resolved["risk"])),
                idempotent=bool(resolved["idempotent"]),
                description=str(resolved["description"]),
            )
        ],
        risk_level=normalize_workflow_risk(str(resolved["risk"])),
        metadata={"source": "erp_agent_capability_tool"},
    )
    # 合并调用方（已认证会话）传入的上下文，而不是凭空重建，否则审批申请人无法解析。
    # 安全约束：申请人标识只能来自调用方会话；params 由模型产生，
    # 因此**不得**从 params 读取 local_user_id / actor_id / user_id。
    context["source"] = "erp_agent_capability_tool"
    context["workspace_root"] = workspace_root
    context.setdefault("message", str(params.get("user_request") or params.get("message") or ""))
    actor_id = str(
        context.get("user_id") or context.get("local_user_id") or context.get("actor_id") or ""
    ).strip()
    if not actor_id:
        return json.dumps(
            {
                "success": False,
                "error": "ERP capability 缺少已认证的调用人上下文，未执行",
                "tool_id": tool_id,
                "action": action,
            },
            ensure_ascii=False,
        )
    try:
        from app.application.agent_orchestrator import AgentOrchestrator
        from app.application.workflow import get_approval_service

        approvals = get_approval_service()
        required_nodes = approvals.get_approval_required_nodes(plan)
        required_ids = [node.node_id for node in required_nodes]
        if required_ids:
            plan.metadata["approval_required_node_ids"] = required_ids
        agent_run = AgentOrchestrator().start_run_from_plan(
            user_id=actor_id,
            message=str(context.get("message") or ""),
            plan=plan,
            runtime_context=context,
            auto_execute=True,
        )
    except RECOVERABLE_ERRORS:
        return json.dumps(
            {
                "success": False,
                "error": "ERP capability 风险门检查失败，未执行",
                "tool_id": tool_id,
                "action": action,
            },
            ensure_ascii=False,
        )

    capability = {
        key: resolved[key] for key in ("tool_id", "action", "risk", "idempotent", "required_params")
    }
    response = {"success": False, "capability": capability, "agent_run_id": agent_run.run_id}
    if agent_run.status == "waiting_user":
        waiting = next((step for step in agent_run.steps if step.status == "waiting_user"), None)
        if waiting and waiting.node_id in required_ids:
            node = next((item for item in plan.nodes if item.node_id == waiting.node_id), None)
            request_id = ""
            try:
                if node is None or (node.tool_id, node.action, node.params) != (
                    waiting.tool_id,
                    waiting.action,
                    waiting.params,
                ):
                    raise RuntimeError("审批节点与完整计划不一致")
                request = approvals.create_approval_request(
                    plan_id=plan.plan_id,
                    node=node,
                    runtime_context={**context, "_approval_agent_run_required": True},
                    plan=plan,
                    require_persistence=True,
                    request_id=approval_request_id,
                )
                request_id = str(request.request_id or "").strip()
                if not request_id or not approvals.attach_pending_agent_run(
                    request_id, agent_run_id=agent_run.run_id, approved_step_id=waiting.node_id
                ):
                    raise RuntimeError("AgentRun 未关联到审批请求")
            except RECOVERABLE_ERRORS:
                response.update(
                    message="ERP 操作已暂停，但审批请求未能安全保存；未执行等待审批的步骤。",
                    run_status=agent_run.status,
                )
            else:
                response.update(
                    pending_approval=True,
                    approval_request_id=request_id,
                    message="该 ERP 操作已创建审批请求，审批前不会执行。",
                )
        else:
            response.update(
                requires_confirmation=True,
                message="该 ERP 操作已在 AgentRun 中安全暂停，等待确认后继续。",
                run_status=agent_run.status,
            )
    elif agent_run.status == "completed":
        step = next((item for item in agent_run.steps if item.status == "completed"), None)
        output = dict(step.output or {}) if step else {}
        response.update(
            success=bool(output.get("success", False)),
            message=str(output.get("message") or ""),
            result=output,
        )
    else:
        response.update(
            message=str(agent_run.error or "该 ERP 操作未完成。"),
            run_status=agent_run.status,
        )
    return json.dumps(response, ensure_ascii=False, default=json_safe)


__all__ = [
    "ERP_CAPABILITY_TOOL_NAME",
    "build_registered_capability_tool_definition",
    "execute_registered_capability",
    "extend_workflow_tool_registry",
    "registered_capability_catalog",
    "resolve_registered_capability_call",
]
